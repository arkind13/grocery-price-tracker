#!/usr/bin/env python3
"""Lookup engine: generic name -> keywords -> live search (display-only).

Context 2 (user query) state machine. Fuzzy + alias learning IS allowed
here, per TASK_3.5.8 Operating Rule #10. This is SEPARATE from the sync
path (Context 1) which uses exact-only matching against Col I/J/K.

Lookup chain (find_product):
    Step 1: Exact match on Col A (generic name) or Col I/J/K (store kw).
    Step 2: Keywords column (Col P) two-pass:
            2a exact alias  -> normalized query equals a Col P alias.
            2b token match  -> all significant query tokens in an alias.
    Step 3: Partial candidates in Col A with interactive selection.
    Step 4: Persist alias to Col P on user selection (persist_alias).
    Step 5: Not in sheet -> live search Woolworths (curl_cffi, no login)
            + Coles (Scrape.do). Ranked per store; the shown pair passes
            the UOM 20% gate (core/uom.py). Display-only: no auto-add —
            explicit adds go through `search --add-item` / `map --add`
            (spec §0.7 / B2).
    Step 6: Genuine "not found" only if BOTH stores return empty.

Col P ("Keywords") stores user-side aliases, pipe-delimited within a
cell ("milk 3l|skim milk"). Col I/J/K store exact store-site names for
sync and must never be conflated with Col P.
"""
from __future__ import annotations

import difflib
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

# Bootstrap so core/ and extractors/ are importable
_HERE = Path(__file__).resolve().parent          # core/
_PROJECT = _HERE.parent                          # grocery-price-tracker/
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core.uom import Verdict, compare_sizes, parse_size
from core.sheets_sync import PRICE_COL, _find_col, _col_letter, _pad_rows
from core.sheets_sync import _update_with_backoff, _sydney_now_str

# Column indices in Products_Master (0-based, positional, locked)
COL_GENERIC = 0       # A — Product_Name
COL_BRAND = 6         # G — Brand_Type
COL_LAST_UPDATED = 7   # H — Last_Updated
COL_KW_WOOL = 8        # I — Search_Keyword_Woolworths (sync path)
COL_KW_COLES = 9      # J — Search_Keyword_Coles (sync path)

# Header-driven (resolved at runtime via _find_col)
KEYWORDS_HEADER = "Keywords"            # Col P — user-side aliases
SPECIALS_HEADER = {
    "woolworths": "Woolworths_Specials",  # Col M
    "coles": "Coles_Specials",            # Col N
}
REWARDS_HEADER = "Rewards_Points"        # Col O

# Alias delimiter within a Col P cell (pipe avoids commas in product names)
ALIAS_DELIM = "|"

# Stopwords excluded from "significant words" in partial/token matching.
STOPWORDS = {
    "the", "and", "a", "an", "of", "for", "with", "to", "in", "on", "at",
    "pk", "pack", "g", "kg", "l", "ml", "ea", "1", "2", "3", "500",
    "1000", "750", "brand", "size",
}
MIN_WORD_LEN = 3
MAX_CANDIDATES = 5  # Step 3 — max candidates to offer the user


# ============================================================================
# Section A: Result types
# ============================================================================


class LookupStatus(str, Enum):
    """Terminal state of the lookup chain for one query."""
    EXACT_SHEET = "exact_sheet"        # Step 1 hit (Col A or Col I/J/K)
    KEYWORD_ALIAS = "keyword_alias"    # Step 2 hit (Col P alias)
    CANDIDATES = "candidates"          # Step 3 — needs user pick
    LIVE_SEARCH = "live_search"        # Step 5 — live results, needs confirm
    SHEET_AND_LIVE = "sheet_and_live"  # sheet prices kept + missing
                                       # stores live-filled (compare auto;
                                       # per-store sources on the result)
    NOT_FOUND = "not_found"            # Step 6 — both stores empty


# The two priced stores (mirrors core.price_comparator.STORES; the
# live-fill merge needs the order for deterministic source tags).
STORES = ("woolworths", "coles")


@dataclass(frozen=True)
class CandidateRow:
    """One partial-match candidate for Step 3 interactive selection.

    Attributes:
        row_index: 1-based sheet row.
        generic_name: Col A value.
        brand: Col G value.
        size: Col C value.
        score: partial match score (higher = better).
        subcategory: Col Q value (additive, spec §9; "" when absent).
        item_code: Col R value ("" when absent).
        preferred: Col S value ("" or "P").
    """
    row_index: int
    generic_name: str
    brand: str
    size: str
    score: int
    subcategory: str = ""   # Col Q (additive, spec §9)
    item_code: str = ""     # Col R
    preferred: str = ""     # Col S ("" or "P")


@dataclass(frozen=True)
class LookupResult:
    """Outcome of the lookup chain for one query.

    Attributes:
        query: the original user-typed string (unmodified).
        status: terminal LookupStatus.
        row_index: 1-based sheet row for Steps 1, 2 (and after Step 4
            persist). None for Steps 3 (pre-pick), 5, 6.
        generic_name: matched Col A value (Steps 1, 2). Best live name
            (Step 5). "" for Steps 3 (pre-pick), 6.
        prices: store -> float price. Populated for Steps 1, 2, 5.
        specials: store -> special_desc string.
        brand: brand string.
        candidates: list[CandidateRow] for Step 3 (empty otherwise).
        live_items: list[ProductItem] for Step 5 (empty otherwise).
        note: human-readable resolution note.
        matched_names: store -> matched product name for the price shown
            (Col A value for sheet steps; raw store name for live).
        matched_sizes: store -> matched size string (Col C for sheet
            steps; the live listing size for live).
        closest: store -> {"name", "size"} of the top-ranked product when
            no comparable pair was found (found-block data, Step 5).
        uom_reason: "" or "family_mismatch" | "beyond_20pct" |
            "missing_size" | "no_results_<store>" (Step 5 gate outcome).
        store_unavailable: stores not checked this run (e.g. Coles when
            Scrape.do is unavailable/breaker-open/cap-exceeded).
        sources: store -> "sheet" | "live" for the prices dict.
            Populated for SHEET_AND_LIVE results (the merged outcome);
            single-source results derive it from the status.
        subcategory: resolved row's Col Q (additive, spec §9).
        item_code: resolved row's Col R ("" when absent).
        preferred: resolved row's Col S ("" or "P").
    """
    query: str
    status: LookupStatus
    row_index: Optional[int] = None
    generic_name: str = ""
    prices: dict = field(default_factory=dict)
    specials: dict = field(default_factory=dict)
    brand: str = ""
    candidates: list = field(default_factory=list)
    live_items: list = field(default_factory=list)
    note: str = ""
    matched_names: dict = field(default_factory=dict)
    matched_sizes: dict = field(default_factory=dict)
    closest: dict = field(default_factory=dict)
    uom_reason: str = ""
    store_unavailable: list = field(default_factory=list)
    sources: dict = field(default_factory=dict)
    subcategory: str = ""   # resolved row's Col Q (additive)
    item_code: str = ""     # resolved row's Col R
    preferred: str = ""     # resolved row's Col S


# ============================================================================
# Section B: LookupIndex (read-only sheet view incl. Col P aliases)
# ============================================================================


class LookupIndex:
    """In-memory read-only view of Products_Master for user-query lookup.

    Built ONCE from get_all_values() rows (header excluded). Holds:
        - _rows: list of per-row dicts (generic_name, brand, prices, ...)
        - _generic_map: normalized Col A -> row dict (first wins)
        - _keyword_map: normalized Col I/J/K -> row dict (first wins)
        - _alias_exact: normalized Col P alias -> row dict (first wins)
        - _alias_token: list of (alias_tokens_set, row dict) for token match

    Provides Step 1 (exact), Step 2 (Col P two-pass), Step 3 (candidates).
    """

    def __init__(self, rows: list[list[str]], header: list[str]) -> None:
        """Build from all_values()[1:] and all_values()[0].

        Resolves specials columns M/N, rewards O, and Keywords P by header
        name via sheets_sync._find_col (header-driven, robust to absence).
        """
        self._rows: list[dict] = []
        self._generic_map: dict[str, dict] = {}
        self._keyword_map: dict[str, dict] = {}

        # Col P alias structures
        self._alias_exact: dict[str, dict] = {}
        self._alias_token: list[tuple[set, dict]] = []

        # Resolve column indices by header name
        specials_col: dict[str, int] = {}
        for store_key, header_name in SPECIALS_HEADER.items():
            idx = _find_col(header, header_name)
            if idx is not None:
                specials_col[store_key] = idx

        rewards_col = _find_col(header, REWARDS_HEADER)
        keywords_col = _find_col(header, KEYWORDS_HEADER)  # Col P
        subcategory_col = _find_col(header, "Sub_Category")   # Q
        item_code_col = _find_col(header, "Item_Code")        # R
        preferred_col = _find_col(header, "Preferred")        # S

        _price_re = re.compile(r"(?:A\$|\$)\s*(\d+\.?\d*)")

        for i, row in enumerate(rows):
            generic_name = str(row[0]).strip() if len(row) > 0 else ""
            if not generic_name:
                continue

            row_index = i + 2  # 1-based (row 1 = header)
            brand = str(row[COL_BRAND]).strip() if len(row) > COL_BRAND else ""
            category = str(row[1]).strip() if len(row) > 1 else ""
            size = str(row[2]).strip() if len(row) > 2 else ""

            # Parse prices D/E/F
            prices: dict = {}
            for store_key, col_idx in PRICE_COL.items():
                if col_idx < len(row) and row[col_idx]:
                    cell = str(row[col_idx])
                    m = _price_re.search(cell)
                    if m:
                        prices[store_key] = float(m.group(1))
                    else:
                        try:
                            prices[store_key] = float(cell)
                        except (ValueError, TypeError):
                            pass

            # Parse specials M/N
            specials: dict = {}
            for store_key, col_idx in specials_col.items():
                if col_idx < len(row) and row[col_idx].strip():
                    specials[store_key] = str(row[col_idx]).strip()

            # Parse rewards O
            rewards = ""
            if rewards_col is not None and rewards_col < len(row):
                rewards = str(row[rewards_col]).strip()

            # Parse Col P aliases (pipe-delimited)
            aliases: list[str] = []
            if keywords_col is not None and keywords_col < len(row):
                raw_kw = str(row[keywords_col]).strip()
                if raw_kw:
                    aliases = [
                        a.strip() for a in raw_kw.split(ALIAS_DELIM) if a.strip()
                    ]

            row_dict = {
                "row_index": row_index,
                "generic_name": generic_name,
                "brand": brand,
                "category": category,
                "size": size,
                "prices": prices,
                "specials": specials,
                "rewards": rewards,
                "aliases": aliases,
                # Raw store-keyword cells (Col I/J) — let callers tell a
                # missing KEYWORD from a missing PRICE (optimize confirm
                # flow, 2026-09-03).
                "ww_kw": (str(row[COL_KW_WOOL]).strip()
                          if len(row) > COL_KW_WOOL else ""),
                "coles_kw": (str(row[COL_KW_COLES]).strip()
                             if len(row) > COL_KW_COLES else ""),
                "subcategory": (str(row[subcategory_col]).strip()
                                if subcategory_col is not None
                                and len(row) > subcategory_col
                                else ""),
                "item_code": (str(row[item_code_col]).strip()
                              .upper()
                              if item_code_col is not None
                              and len(row) > item_code_col
                              else ""),
                "preferred": (str(row[preferred_col]).strip()
                              if preferred_col is not None
                              and len(row) > preferred_col
                              else ""),
            }
            self._rows.append(row_dict)

            # Col A exact map (first wins)
            norm = self._normalize(generic_name)
            if norm not in self._generic_map:
                self._generic_map[norm] = row_dict

            # Col I/J keyword map (first wins)
            for kw_col in (COL_KW_WOOL, COL_KW_COLES):
                if kw_col < len(row) and row[kw_col].strip():
                    kw_norm = self._normalize(row[kw_col])
                    if kw_norm not in self._keyword_map:
                        self._keyword_map[kw_norm] = row_dict

            # Col P alias structures
            for alias in aliases:
                a_norm = self._normalize(alias)
                if a_norm and a_norm not in self._alias_exact:
                    self._alias_exact[a_norm] = row_dict
                tokens = self._significant_tokens(alias)
                if tokens:
                    self._alias_token.append((tokens, row_dict))

    @staticmethod
    def _normalize(s: str) -> str:
        """Lowercase, trim, collapse internal whitespace runs to one space."""
        return re.sub(r"\s+", " ", str(s).strip().lower())

    @staticmethod
    def _significant_tokens(s: str) -> set:
        """Return set of significant words (len>=3, not stopword)."""
        return {
            w for w in LookupIndex._normalize(s).split()
            if len(w) >= MIN_WORD_LEN and w not in STOPWORDS
        }

    # --- Step 1: exact match ---

    def find_exact(self, query: str) -> Optional[dict]:
        """Step 1: exact match on Col A (generic name) or Col I/J/K.

        Returns the row dict or None.
        """
        norm = self._normalize(query)
        if norm in self._generic_map:
            return self._generic_map[norm]
        if norm in self._keyword_map:
            return self._keyword_map[norm]
        return None

    # --- Step 2: Col P two-pass ---

    def find_alias_exact(self, query: str) -> Optional[dict]:
        """Step 2a: exact alias match in Col P.

        Normalizes the query and checks if it exactly equals any Col P
        alias. Returns the row dict or None.
        """
        norm = self._normalize(query)
        return self._alias_exact.get(norm)

    def find_alias_token(self, query: str) -> Optional[dict]:
        """Step 2b: token match in Col P.

        Checks if ALL significant tokens of the query appear in a Col P
        alias's significant tokens (subset match), with singular/plural
        normalisation on both sides ("apples" matches the alias token
        "apple" — user report 2026-09-03). Returns the best match
        (highest token overlap) or None.
        """
        query_tokens = self._significant_tokens(query)
        if not query_tokens:
            return None

        best_row: Optional[dict] = None
        best_overlap = 0
        for alias_tokens, row_dict in self._alias_token:
            alias_variants: set = set()
            for token in alias_tokens:
                alias_variants |= _token_variants(token)
            # Every query token must be present in the alias, allowing
            # singular/plural forms on either side ("apples" <-> "apple").
            if all(
                _token_variants(token) & alias_variants
                for token in query_tokens
            ):
                overlap = len(query_tokens)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_row = row_dict
        return best_row

    # --- Step 3: partial candidates ---

    def find_candidates(self, query: str,
                        limit: int = MAX_CANDIDATES) -> list[CandidateRow]:
        """Step 3: partial candidates in Col A.

        Deterministic scoring (NOT rapidfuzz), mirroring recipe_resolver:
            +2 if query_normalized is a substring of col_a_normalized
            +2 if col_a_normalized is a substring of query_normalized
            +1 per significant query word present in col_a_normalized
                (singular/plural variants count — "apples" matches a
                Col A containing "apple", user report 2026-09-03)
        Returns top `limit` candidates with score > 0, sorted by score
        descending then shortest Col A then lowest row_index.
        """
        norm_query = self._normalize(query)
        tokens = self._significant_tokens(query)
        if not tokens:
            return []

        scored: list[tuple[int, dict]] = []
        for row_dict in self._rows:
            norm_a = self._normalize(row_dict["generic_name"])
            score = 0
            if norm_query in norm_a:
                score += 2
            if norm_a in norm_query:
                score += 2
            for token in tokens:
                if any(v in norm_a for v in _token_variants(token)):
                    score += 1
            if score > 0:
                scored.append((score, row_dict))

        if not scored:
            return []

        # Sort: score desc, then shortest generic_name, then lowest row_index
        scored.sort(key=lambda t: (-t[0], len(t[1]["generic_name"]),
                                    t[1]["row_index"]))

        return [
            CandidateRow(
                row_index=rd["row_index"],
                generic_name=rd["generic_name"],
                brand=rd.get("brand", ""),
                size=rd.get("size", ""),
                score=score,
                subcategory=rd.get("subcategory", ""),
                item_code=rd.get("item_code", ""),
                preferred=rd.get("preferred", ""),
            )
            for score, rd in scored[:limit]
        ]

    def get_row(self, row_index: int) -> Optional[dict]:
        """Return the row dict for a 1-based sheet row_index, or None."""
        for rd in self._rows:
            if rd["row_index"] == row_index:
                return rd
        return None


# ============================================================================
# Section B2: live-search ranking + UOM pair selection (Step 5)
# ============================================================================


def _token_variants(token: str) -> set:
    """Return singular/plural normalisation variants of one token.

    Absorbs the tomatoes/tomato class: "ies"->"y", trailing "es", and
    trailing "s" each produce an extra candidate variant.

    Args:
        token (str): lowercased single word.

    Returns:
        set: the token plus its plausible singular/plural forms.
    """
    variants = {token}
    if token.endswith("ies") and len(token) > 4:
        variants.add(token[:-3] + "y")
    if token.endswith("es") and len(token) > 3:
        variants.add(token[:-2])
    if token.endswith("s") and len(token) > 2:
        variants.add(token[:-1])
    return variants


def rank_live_results(query: str, items: list) -> list:
    """Rank live-search results by tolerant relevance. NEVER rejects.

    Score = 2 x (fraction of significant query tokens present in the
    product name, singular/plural normalised) + difflib SequenceMatcher
    ratio on the normalised full strings. Stdlib only.

    Args:
        query (str): the user-typed search string.
        items (list): ProductItem-like objects for ONE store.

    Returns:
        list: the same items, ordered rank desc then raw_name asc.
        Every input item is returned.
    """
    norm_query = LookupIndex._normalize(query)
    query_variants = [
        _token_variants(t) for t in norm_query.split()
        if len(t) >= MIN_WORD_LEN and t not in STOPWORDS
    ]
    scored = []
    for item in items:
        name = str(getattr(item, "raw_name", "") or "")
        norm_name = LookupIndex._normalize(name)
        name_variants = {
            v for t in norm_name.split() for v in _token_variants(t)
        }
        overlap = sum(1 for vs in query_variants if vs & name_variants)
        fraction = overlap / len(query_variants) if query_variants else 0.0
        ratio = difflib.SequenceMatcher(None, norm_query, norm_name).ratio()
        scored.append((fraction * 2.0 + ratio, name, item))
    scored.sort(key=lambda t: (-t[0], t[1].lower()))
    return [item for _score, _name, item in scored]


# Price sanity ceiling: among gate-passing pairs prefer the first whose
# prices are within 10x of each other (spec §3.2.3).
PAIR_PRICE_CEILING = 10.0


def select_live_pair(query: str, ww_items: list,
                     coles_items: list) -> dict:
    """Pick the Woolworths+Coles pair to show, gated by the UOM rule.

    Pairwise walk: Woolworths rank order (outer) x Coles rank order
    (inner); every pair whose compare_sizes verdict is COMPARABLE_*
    collects (in walk order). Among those, the first whose prices sit
    within 10x of each other wins; if none, the first passing pair.
    Ranking never rejects: single-sided results come back ranked for
    display (found-block / map flow).

    Args:
        query (str): the user-typed search string.
        ww_items (list): Woolworths ProductItems (unranked ok).
        coles_items (list): Coles ProductItems (unranked ok).

    Returns:
        dict: {"ww": ProductItem | None, "coles": ProductItem | None,
        "pair_passed": bool, "reason": str, "ww_ranked": list,
        "coles_ranked": list}. reason is the first attempted
        comparison's failure reason ("family_mismatch" | "beyond_20pct"
        | "missing_size") when no pair passed.
    """
    ww_ranked = rank_live_results(query, ww_items or [])
    coles_ranked = rank_live_results(query, coles_items or [])
    result = {
        "ww": None,
        "coles": None,
        "pair_passed": False,
        "reason": "",
        "ww_ranked": ww_ranked,
        "coles_ranked": coles_ranked,
    }
    if not ww_ranked or not coles_ranked:
        return result

    passing: list[tuple] = []
    first_reason = ""
    for ww_item in ww_ranked:
        ww_size = parse_size(getattr(ww_item, "size", "") or "")
        for coles_item in coles_ranked:
            coles_size = parse_size(getattr(coles_item, "size", "") or "")
            cmp = compare_sizes(ww_size, coles_size)
            if cmp.verdict in (Verdict.COMPARABLE_SAME,
                               Verdict.COMPARABLE_TOLERANT):
                passing.append((ww_item, coles_item))
            elif not first_reason and cmp.reason:
                first_reason = cmp.reason

    if not passing:
        result["reason"] = first_reason
        return result

    chosen = None
    for ww_item, coles_item in passing:
        ww_price = float(getattr(ww_item, "price", 0.0) or 0.0)
        coles_price = float(getattr(coles_item, "price", 0.0) or 0.0)
        low, high = sorted((ww_price, coles_price))
        if low > 0 and high / low <= PAIR_PRICE_CEILING:
            chosen = (ww_item, coles_item)
            break
    if chosen is None:
        chosen = passing[0]

    result["ww"] = chosen[0]
    result["coles"] = chosen[1]
    result["pair_passed"] = True
    result["reason"] = ""
    return result


# ============================================================================
# Section C: LookupEngine (state machine)
# ============================================================================


class LookupEngine:
    """Drives the lookup chain Steps 1 -> 2 -> 3 -> 5 -> 6.

    Args:
        worksheet: optional pre-connected gspread Worksheet. If None,
            connects fresh via sheets_client.connect_worksheet() on first
            use (lazy). Tests pass a FakeWorksheet.
    """

    def __init__(self, worksheet=None) -> None:
        self._worksheet = worksheet
        self._index: Optional[LookupIndex] = None
        self._raw_rows = None
        self._header = None

    def _ensure_index(self) -> LookupIndex:
        """Build LookupIndex from the worksheet (lazy, once)."""
        if self._index is not None:
            return self._index
        ws = self._worksheet
        if ws is None:
            from core.sheets_client import connect_worksheet
            ws = connect_worksheet()
        all_values = ws.get_all_values()
        if not all_values:
            raise RuntimeError("Products_Master sheet is empty")
        header = all_values[0]
        rows = all_values[1:]
        self._raw_rows = rows
        self._header = header
        self._index = LookupIndex(rows, header)
        return self._index

    def _halal_scoped_index(self) -> "LookupIndex":
        """Halal-visible view: halal-marked rows PLUS rows outside
        the auto-halal scope (non-halal meat rows are invisible to
        generic meat terms — §12.2). Read-only filter over the SAME
        values; ranking logic untouched.
        """
        from core.halal import is_auto_halal_scope, is_halal_row
        from core.sheets_sync import _find_col
        q = _find_col(self._header, "Sub_Category")
        p = _find_col(self._header, "Keywords")
        visible = []
        for row in self._raw_rows:
            sub = (str(row[q]).strip() if q is not None
                   and len(row) > q else "")
            col_p = (str(row[p]).strip() if p is not None
                     and len(row) > p else "")
            name = str(row[0]).strip() if row else ""
            if is_auto_halal_scope(sub) and not is_halal_row(col_p,
                                                             name):
                continue
            visible.append(row)
        return LookupIndex(visible, self._header)

    def find_product(self, query: str, *,
                     interactive: bool = True,
                     _halal_chain: bool = False) -> LookupResult:
        """Run the lookup chain Steps 1 -> 2 -> 3 -> 5 -> 6 for one query.

        Args:
            query: the user-typed product name (e.g. "milk").
            interactive: if True (default), Step 3 returns candidates for
                the caller to present for user selection. If False, Step 3
                auto-picks the top candidate (used by compare --mode auto).
            _halal_chain: private recursion guard for the halal tier
                chain — chain mode injects the 'halal ' prefix into
                Step 5 and returns the plain live result so
                resolve_halal_item can verify candidates (prevents
                resolve_halal_item <-> find_product infinite
                recursion).

        Returns:
            LookupResult with the terminal status.
        """
        query = (query or "").strip()
        if not query:
            return LookupResult(
                query="", status=LookupStatus.NOT_FOUND,
                note="empty query",
            )

        idx = self._ensure_index()

        # Step 1: exact match on Col A or Col I/J/K
        exact = idx.find_exact(query)
        if exact is not None:
            sheet_res = LookupResult(
                query=query,
                status=LookupStatus.EXACT_SHEET,
                row_index=exact["row_index"],
                generic_name=exact["generic_name"],
                prices=dict(exact["prices"]),
                specials=dict(exact["specials"]),
                brand=exact.get("brand", ""),
                subcategory=exact.get("subcategory", ""),
                item_code=exact.get("item_code", ""),
                preferred=exact.get("preferred", ""),
                matched_names={s: exact["generic_name"]
                               for s in exact["prices"]},
                matched_sizes={s: exact.get("size", "")
                               for s in exact["prices"]},
                note=f"exact match: '{exact['generic_name']}'",
            )
            return self._finish_sheet_result(sheet_res, query, interactive)

        # --- PART-2 halal intercept (§12.4): generic raw-meat terms
        # resolve halal-scoped. Step 1 exact matches are UNSCOPED —
        # a full non-halal name is a database query (D-H4). ---
        from core.halal import is_meat_term
        halal_scoped = is_meat_term(query)
        if halal_scoped:
            idx = self._halal_scoped_index()

        # Step 2a: exact alias in Col P
        alias = idx.find_alias_exact(query)
        if alias is not None:
            sheet_res = LookupResult(
                query=query,
                status=LookupStatus.KEYWORD_ALIAS,
                row_index=alias["row_index"],
                generic_name=alias["generic_name"],
                prices=dict(alias["prices"]),
                specials=dict(alias["specials"]),
                brand=alias.get("brand", ""),
                subcategory=alias.get("subcategory", ""),
                item_code=alias.get("item_code", ""),
                preferred=alias.get("preferred", ""),
                matched_names={s: alias["generic_name"]
                               for s in alias["prices"]},
                matched_sizes={s: alias.get("size", "")
                               for s in alias["prices"]},
                note=f"Col P alias match: '{alias['generic_name']}'",
            )
            return self._finish_sheet_result(sheet_res, query, interactive)

        # Step 2b: token match in Col P
        token_match = idx.find_alias_token(query)
        if token_match is not None:
            sheet_res = LookupResult(
                query=query,
                status=LookupStatus.KEYWORD_ALIAS,
                row_index=token_match["row_index"],
                generic_name=token_match["generic_name"],
                prices=dict(token_match["prices"]),
                specials=dict(token_match["specials"]),
                brand=token_match.get("brand", ""),
                subcategory=token_match.get("subcategory", ""),
                item_code=token_match.get("item_code", ""),
                preferred=token_match.get("preferred", ""),
                matched_names={s: token_match["generic_name"]
                               for s in token_match["prices"]},
                matched_sizes={s: token_match.get("size", "")
                               for s in token_match["prices"]},
                note=f"Col P token match: '{token_match['generic_name']}'",
            )
            return self._finish_sheet_result(sheet_res, query, interactive)

        # Step 3: partial candidates in Col A
        candidates = idx.find_candidates(query)
        if candidates:
            if interactive:
                return LookupResult(
                    query=query,
                    status=LookupStatus.CANDIDATES,
                    candidates=candidates,
                    note=(f"{len(candidates)} candidate(s) found "
                          f"— pick one to persist alias"),
                )
            # Non-interactive: auto-pick the top candidate
            top = candidates[0]
            row_dict = idx.get_row(top.row_index)
            if row_dict is not None:
                sheet_res = LookupResult(
                    query=query,
                    status=LookupStatus.EXACT_SHEET,
                    row_index=top.row_index,
                    generic_name=top.generic_name,
                    prices=dict(row_dict["prices"]),
                    specials=dict(row_dict["specials"]),
                    brand=row_dict.get("brand", ""),
                    subcategory=row_dict.get("subcategory", ""),
                    item_code=row_dict.get("item_code", ""),
                    preferred=row_dict.get("preferred", ""),
                    matched_names={s: top.generic_name
                                   for s in row_dict["prices"]},
                    matched_sizes={s: row_dict.get("size", "")
                                   for s in row_dict["prices"]},
                    note=f"auto-picked candidate: '{top.generic_name}'",
                )
                return self._finish_sheet_result(
                    sheet_res, query, interactive)

        # Step 5: live search — PART-2: raw-meat queries run the
        # halal fallback chain (sheet -> live+LLM-verify -> butchery);
        # chain mode (_halal_chain) injects the 'halal ' prefix and
        # returns the plain live result to resolve_halal_item.
        if halal_scoped:
            from core.halal import (
                halal_search_suffix, resolve_halal_item,
            )
            if _halal_chain:
                return self._live_result(halal_search_suffix(query))
            return resolve_halal_item(query, worksheet=self._worksheet)
        return self._live_result(query)

    def _finish_sheet_result(self, sheet_res: LookupResult, query: str,
                             interactive: bool) -> LookupResult:
        """Sheet resolution + live fill of missing stores (compare only).

        A resolved row can still carry unusable prices (legacy rows
        with unavailable / N-A / blank cells — user report 2026-09-03:
        "bread"/"beef mince" never reached live search). For
        NON-INTERACTIVE callers (compare auto mode) the MISSING stores
        are live-searched and merged in: usable sheet prices are never
        overwritten, and the merged result is tagged per store
        (SHEET_AND_LIVE + sources) so the report labels each price
        honestly. Interactive callers (the map resolve flow) keep the
        pure sheet answer — list semantics are untouched.

        Args:
            sheet_res: the resolved sheet LookupResult (steps 1-3).
            query: the original user-typed string.
            interactive: False for compare auto mode; True keeps the
                pure sheet result.

        Returns:
            LookupResult: the pure sheet result when complete,
            interactive, or when live search adds nothing usable;
            otherwise the SHEET_AND_LIVE merge.
        """
        if interactive:
            return sheet_res
        missing = [s for s in STORES if s not in sheet_res.prices]
        if not missing:
            return sheet_res
        live = self._live_result(query)
        additions = {s: live.prices[s] for s in missing
                     if s in live.prices}
        if not additions:
            # Live search added nothing usable — keep the sheet answer.
            return sheet_res
        return LookupResult(
            query=sheet_res.query,
            status=LookupStatus.SHEET_AND_LIVE,
            row_index=sheet_res.row_index,
            generic_name=sheet_res.generic_name,
            prices={**sheet_res.prices, **additions},
            specials={**sheet_res.specials,
                      **{s: live.specials[s] for s in additions
                         if s in live.specials}},
            brand=sheet_res.brand or live.brand,
            live_items=list(live.live_items),
            subcategory=sheet_res.subcategory,
            item_code=sheet_res.item_code,
            preferred=sheet_res.preferred,
            matched_names={**sheet_res.matched_names,
                           **{s: live.matched_names[s] for s in additions
                              if s in live.matched_names}},
            matched_sizes={**sheet_res.matched_sizes,
                           **{s: live.matched_sizes[s] for s in additions
                              if s in live.matched_sizes}},
            store_unavailable=[s for s in live.store_unavailable
                               if s in additions],
            sources={**{s: "sheet" for s in sheet_res.prices},
                     **{s: "live" for s in additions}},
            note=(f"sheet prices kept; live-filled: "
                  f"{', '.join(sorted(additions))}"),
        )

    def _live_result(self, query: str) -> LookupResult:
        """Steps 5 -> 6: live search both stores (or honest not-found).

        Extracted verbatim from the former find_product tail so the
        sheet-result live-fill can reuse the exact same gate/found-block
        behaviour.

        Args:
            query: the user-typed product name.

        Returns:
            LookupResult: LIVE_SEARCH (pair / single-sided / found-block)
            or NOT_FOUND.
        """
        ww_items, coles_items, coles_status = self._live_search_pair(query)
        ww_ranked = rank_live_results(query, ww_items)
        coles_ranked = rank_live_results(query, coles_items)
        coles_unavailable = coles_status in (
            "unavailable", "breaker_open", "cap_exceeded")

        if ww_ranked and coles_ranked:
            pair = select_live_pair(query, ww_items, coles_items)
            if pair["pair_passed"]:
                chosen_ww = pair["ww"]
                chosen_coles = pair["coles"]
                prices = {
                    "woolworths": chosen_ww.price,
                    "coles": chosen_coles.price,
                }
                specials: dict = {}
                if chosen_ww.is_special and chosen_ww.special_desc:
                    specials["woolworths"] = chosen_ww.special_desc
                if chosen_coles.is_special and chosen_coles.special_desc:
                    specials["coles"] = chosen_coles.special_desc
                matched_names = {
                    "woolworths": chosen_ww.raw_name,
                    "coles": chosen_coles.raw_name,
                }
                matched_sizes = {
                    "woolworths": chosen_ww.size,
                    "coles": chosen_coles.size,
                }
                rest = [
                    it for it in ww_ranked + coles_ranked
                    if it is not chosen_ww and it is not chosen_coles
                ]
                return LookupResult(
                    query=query,
                    status=LookupStatus.LIVE_SEARCH,
                    generic_name=chosen_ww.raw_name or chosen_coles.raw_name,
                    prices=prices,
                    specials=specials,
                    brand=chosen_ww.brand or chosen_coles.brand,
                    matched_names=matched_names,
                    matched_sizes=matched_sizes,
                    live_items=[chosen_ww, chosen_coles] + rest,
                    note="live match from store APIs (UOM-gated pair)",
                )
            # No pair passed the gate -> honest found-block (IN-1):
            # no prices, closest top-ranked product per returning store.
            closest = {}
            if ww_ranked:
                closest["woolworths"] = {
                    "name": ww_ranked[0].raw_name,
                    "size": ww_ranked[0].size,
                }
            if coles_ranked:
                closest["coles"] = {
                    "name": coles_ranked[0].raw_name,
                    "size": coles_ranked[0].size,
                }
            return LookupResult(
                query=query,
                status=LookupStatus.LIVE_SEARCH,
                generic_name=(ww_ranked[0].raw_name if ww_ranked
                              else coles_ranked[0].raw_name),
                prices={},
                specials={},
                brand="",
                closest=closest,
                uom_reason=pair["reason"],
                live_items=ww_ranked + coles_ranked,
                note="no comparable pair — closest products shown",
            )

        # Single-sided: Woolworths only
        if ww_ranked and not coles_ranked:
            top = ww_ranked[0]
            if coles_unavailable:
                # B4.3: show the Woolworths-only answer.
                return LookupResult(
                    query=query,
                    status=LookupStatus.LIVE_SEARCH,
                    generic_name=top.raw_name,
                    prices={"woolworths": top.price},
                    specials=({"woolworths": top.special_desc}
                              if top.is_special and top.special_desc else {}),
                    brand=top.brand,
                    matched_names={"woolworths": top.raw_name},
                    matched_sizes={"woolworths": top.size},
                    store_unavailable=["coles"],
                    live_items=ww_ranked,
                    note="woolworths only — coles not checked",
                )
            # Coles returned 0 hits: no price enters the report (IN-1).
            return LookupResult(
                query=query,
                status=LookupStatus.LIVE_SEARCH,
                generic_name=top.raw_name,
                prices={},
                specials={},
                brand="",
                closest={"woolworths": {
                    "name": top.raw_name, "size": top.size}},
                uom_reason="no_results_coles",
                live_items=ww_ranked,
                note="coles found no matching product",
            )

        # Single-sided: Coles only (Woolworths empty or failed)
        if coles_ranked and not ww_ranked:
            top = coles_ranked[0]
            return LookupResult(
                query=query,
                status=LookupStatus.LIVE_SEARCH,
                generic_name=top.raw_name,
                prices={},
                specials={},
                brand="",
                closest={"coles": {
                    "name": top.raw_name, "size": top.size}},
                uom_reason="no_results_woolworths",
                live_items=coles_ranked,
                note="woolworths found no matching product",
            )

        # Step 6: genuine not found
        return LookupResult(
            query=query,
            status=LookupStatus.NOT_FOUND,
            note="no match in sheet or either store",
        )

    def persist_alias(self, query: str, row_index: int, *,
                      worksheet=None) -> dict:
        """Step 4: persist the query string as an alias to Col P.

        Appends the query to the existing Col P value (pipe-delimited).
        Idempotent: if the alias already exists in the cell, no change.

        Args:
            query: the user-typed string to save as an alias.
            row_index: 1-based sheet row of the chosen product.
            worksheet: optional pre-connected worksheet.

        Returns:
            dict with keys: wrote, row_index, range_written, aliases,
            error.
        """
        query = (query or "").strip()
        if not query:
            return {"wrote": False, "row_index": row_index,
                    "range_written": "", "aliases": [], "error": "empty query"}

        ws = worksheet if worksheet is not None else self._worksheet
        if ws is None:
            from core.sheets_client import connect_worksheet
            ws = connect_worksheet()

        all_values = ws.get_all_values()
        header = all_values[0] if all_values else []
        rows = all_values[1:] if len(all_values) > 1 else []

        keywords_col = _find_col(header, KEYWORDS_HEADER)
        if keywords_col is None:
            return {"wrote": False, "row_index": row_index,
                    "range_written": "", "aliases": [],
                    "error": "Keywords (Col P) column not found — "
                             "run schema_upgrade"}

        list_idx = row_index - 2  # 0-based into rows
        if list_idx < 0 or list_idx >= len(rows):
            return {"wrote": False, "row_index": row_index,
                    "range_written": "", "aliases": [],
                    "error": f"row_index {row_index} out of bounds"}

        row = rows[list_idx]
        # Pad row to include Col P
        while len(row) <= keywords_col:
            row.append("")

        existing_raw = str(row[keywords_col]).strip()
        existing = [
            a.strip() for a in existing_raw.split(ALIAS_DELIM) if a.strip()
        ]

        # Idempotent: skip if alias already present
        query_norm = LookupIndex._normalize(query)
        if any(LookupIndex._normalize(a) == query_norm for a in existing):
            return {"wrote": False, "row_index": row_index,
                    "range_written": "", "aliases": existing,
                    "error": "alias already exists"}

        existing.append(query)
        new_value = ALIAS_DELIM.join(existing)
        row[keywords_col] = new_value

        # Write just the Col P cell for this row (use A:A format so the
        # range is parseable by both gspread and FakeWorksheet mock)
        col_letter = _col_letter(keywords_col)
        range_name = f"{col_letter}{row_index}:{col_letter}{row_index}"
        _update_with_backoff(ws, [[new_value]], range_name)

        return {"wrote": True, "row_index": row_index,
                "range_written": range_name, "aliases": existing,
                "error": ""}

    def _live_search_pair(self, query: str) -> tuple[list, list, str]:
        """Step 5: search each store separately, keeping Coles status.

        Woolworths via curl_cffi noauth search; Coles via the
        credit-guarded fetch_coles_search_status. Per-store failures
        yield [] for that store (never raise).

        Args:
            query (str): the user-typed search string.

        Returns:
            tuple[list, list, str]: (ww_items, coles_items, coles_status)
            where coles_status is one of "ok" | "empty" | "unavailable" |
            "breaker_open" | "cap_exceeded".
        """
        if not query or not query.strip():
            return [], [], "empty"
        # Lazy imports to avoid import cycles and keep test import cheap
        from extractors.woolworths_extractor import fetch_woolworths_search_noauth
        from extractors.coles_extractor import fetch_coles_search_status
        ww_items: list = []
        try:
            ww_items = fetch_woolworths_search_noauth(query, page_size=5) or []
        except Exception as exc:
            print(
                f"[lookup] woolworths live search failed: {exc}",
                file=sys.stderr,
            )
        coles_items: list = []
        coles_status = "unavailable"
        try:
            coles_items, coles_status = fetch_coles_search_status(
                query, page_size=5)
        except Exception as exc:
            print(
                f"[lookup] coles live search failed: {exc}",
                file=sys.stderr,
            )
        return ww_items, coles_items or [], coles_status

    def _live_search(self, query: str) -> list:
        """Legacy Step-5 concat (kept for compatibility): both stores in
        one list, Woolworths first. Swallow exceptions (return [] on
        total failure). Each store failure yields [] for that store.
        """
        if not query or not query.strip():
            return []
        out = []
        # Lazy imports to avoid import cycles and keep test import cheap
        from extractors.woolworths_extractor import fetch_woolworths_search_noauth
        from extractors.coles_extractor import fetch_coles_search
        try:
            out += fetch_woolworths_search_noauth(query, page_size=5)
        except Exception as exc:
            print(
                f"[lookup] woolworths live search failed: {exc}",
                file=sys.stderr,
            )
        try:
            out += fetch_coles_search(query, page_size=5)
        except Exception as exc:
            print(
                f"[lookup] coles live search failed: {exc}",
                file=sys.stderr,
            )
        return out


# ============================================================================
# Section D: CLI (__main__)
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Lookup engine: generic -> keywords -> live search"
    )
    parser.add_argument(
        "query", nargs="?", default="",
        help="Product name to look up (e.g. 'milk')",
    )
    parser.add_argument(
        "--non-interactive", action="store_true", default=False,
        help="Auto-pick top candidate in Step 3 (no prompt)",
    )
    args = parser.parse_args()

    if not args.query:
        print(
            "Usage: python core/lookup.py 'milk'",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        engine = LookupEngine()
        result = engine.find_product(
            args.query, interactive=not args.non_interactive
        )
        print(f"Query: {result.query}")
        print(f"Status: {result.status.value}")
        if result.row_index:
            print(f"Row: {result.row_index}")
        if result.generic_name:
            print(f"Match: {result.generic_name}")
        if result.prices:
            # Always-on display discounts: the Woolworths entry shows the
            # discounted price only — "(was $x)" rides along ONLY for
            # genuine specials carrying a store WasPrice. Shared math,
            # no chain changes.
            from core.woolworths_discounts import (
                format_discounted_price,
                is_woolworths_home_brand,
                was_price_from_special_desc,
            )
            segments = []
            for store, p in sorted(result.prices.items()):
                if store == "woolworths":
                    is_home = is_woolworths_home_brand(
                        result.generic_name or "", result.brand or ""
                    )
                    disp = format_discounted_price(p, is_home)
                    was = was_price_from_special_desc(
                        result.specials.get("woolworths", "")
                    )
                    if was is not None:
                        disp += f" (was ${was:.2f})"
                    segments.append(f"woolworths: {disp}")
                else:
                    segments.append(f"{store}: ${p:.2f}")
            print(f"Prices: {', '.join(segments)}")
        if result.candidates:
            print("Candidates:")
            for i, c in enumerate(result.candidates, 1):
                print(f"  {i}) {c.generic_name} (score {c.score})")
        if result.live_items:
            print(f"Live results: {len(result.live_items)} item(s)")
            for item in result.live_items[:5]:
                spec = f" [{item.special_desc}]" if item.is_special else ""
                print(f"  - {item.store}: {item.raw_name} "
                      f"${item.price:.2f}{spec}")
        print(f"Note: {result.note}")
        sys.exit(0 if result.status != LookupStatus.NOT_FOUND else 1)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
