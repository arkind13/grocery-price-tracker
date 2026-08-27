#!/usr/bin/env python3
"""Lookup engine: generic name -> keywords -> live search -> auto-add.

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
            + Coles (Scrape.do). Results returned for confirm/auto-add.
    Step 6: Genuine "not found" only if BOTH stores return empty.

Col P ("Keywords") stores user-side aliases, pipe-delimited within a
cell ("milk 3l|skim milk"). Col I/J/K store exact store-site names for
sync and must never be conflated with Col P.
"""
from __future__ import annotations

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
    NOT_FOUND = "not_found"            # Step 6 — both stores empty


@dataclass(frozen=True)
class CandidateRow:
    """One partial-match candidate for Step 3 interactive selection.

    Attributes:
        row_index: 1-based sheet row.
        generic_name: Col A value.
        brand: Col G value.
        size: Col C value.
        score: partial match score (higher = better).
    """
    row_index: int
    generic_name: str
    brand: str
    size: str
    score: int


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
        alias's significant tokens (subset match). Returns the best match
        (highest token overlap) or None.
        """
        query_tokens = self._significant_tokens(query)
        if not query_tokens:
            return None

        best_row: Optional[dict] = None
        best_overlap = 0
        for alias_tokens, row_dict in self._alias_token:
            if query_tokens.issubset(alias_tokens):
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
                if token in norm_a:
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
        self._index = LookupIndex(rows, header)
        return self._index

    def find_product(self, query: str, *,
                     interactive: bool = True) -> LookupResult:
        """Run the lookup chain Steps 1 -> 2 -> 3 -> 5 -> 6 for one query.

        Args:
            query: the user-typed product name (e.g. "milk").
            interactive: if True (default), Step 3 returns candidates for
                the caller to present for user selection. If False, Step 3
                auto-picks the top candidate (used by compare --mode auto).

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
            return LookupResult(
                query=query,
                status=LookupStatus.EXACT_SHEET,
                row_index=exact["row_index"],
                generic_name=exact["generic_name"],
                prices=dict(exact["prices"]),
                specials=dict(exact["specials"]),
                brand=exact.get("brand", ""),
                note=f"exact match: '{exact['generic_name']}'",
            )

        # Step 2a: exact alias in Col P
        alias = idx.find_alias_exact(query)
        if alias is not None:
            return LookupResult(
                query=query,
                status=LookupStatus.KEYWORD_ALIAS,
                row_index=alias["row_index"],
                generic_name=alias["generic_name"],
                prices=dict(alias["prices"]),
                specials=dict(alias["specials"]),
                brand=alias.get("brand", ""),
                note=f"Col P alias match: '{alias['generic_name']}'",
            )

        # Step 2b: token match in Col P
        token_match = idx.find_alias_token(query)
        if token_match is not None:
            return LookupResult(
                query=query,
                status=LookupStatus.KEYWORD_ALIAS,
                row_index=token_match["row_index"],
                generic_name=token_match["generic_name"],
                prices=dict(token_match["prices"]),
                specials=dict(token_match["specials"]),
                brand=token_match.get("brand", ""),
                note=f"Col P token match: '{token_match['generic_name']}'",
            )

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
                return LookupResult(
                    query=query,
                    status=LookupStatus.EXACT_SHEET,
                    row_index=top.row_index,
                    generic_name=top.generic_name,
                    prices=dict(row_dict["prices"]),
                    specials=dict(row_dict["specials"]),
                    brand=row_dict.get("brand", ""),
                    note=f"auto-picked candidate: '{top.generic_name}'",
                )

        # Step 5: live search (Woolworths curl_cffi + Coles Scrape.do)
        live_items = self._live_search(query)
        if live_items:
            # Pick first result per store
            prices: dict = {}
            specials: dict = {}
            brand = ""
            name = ""
            seen_stores = set()
            for item in live_items:
                store = item.store.lower()
                if (store in ("woolworths", "coles")
                        and store not in seen_stores):
                    seen_stores.add(store)
                    prices[store] = item.price
                    if item.is_special and item.special_desc:
                        specials[store] = item.special_desc
                    if not brand and item.brand:
                        brand = item.brand
                    if not name and item.raw_name:
                        name = item.raw_name
            return LookupResult(
                query=query,
                status=LookupStatus.LIVE_SEARCH,
                generic_name=name,
                prices=prices,
                specials=specials,
                brand=brand,
                live_items=live_items,
                note="live match from store APIs",
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

    def _live_search(self, query: str) -> list:
        """Step 5: live search Woolworths (curl_cffi, no login) + Coles.

        Concatenates results from both stores. Swallow exceptions (return
        [] on total failure). Each store failure yields [] for that store.
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
            # Always-on display discounts: the Woolworths entry shows
            # discounted price + raw; shared math, no chain changes.
            from core.woolworths_discounts import (
                format_discounted_price,
                is_woolworths_home_brand,
            )
            segments = []
            for store, p in sorted(result.prices.items()):
                if store == "woolworths":
                    is_home = is_woolworths_home_brand(
                        result.generic_name or "", result.brand or ""
                    )
                    segments.append(
                        f"woolworths: {format_discounted_price(p, is_home)}"
                    )
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
