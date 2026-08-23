#!/usr/bin/env python3
"""Three-step recipe/shopping-list resolver: sheet exact -> partial -> live.

Reads Products_Master via ONE get_all_values() per resolve_list() call.
Partial matching is deterministic (substring + word-overlap) — NOT rapidfuzz.
"""
from __future__ import annotations
import argparse
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

from core.sheets_sync import _find_col, PRICE_COL

# Stopwords excluded from "significant words" in partial matching.
STOPWORDS = {
    "the", "and", "a", "an", "of", "for", "with", "to", "in", "on", "at",
    "of", "pk", "pack", "g", "kg", "l", "ml", "ea", "1", "2", "3", "500",
    "1000", "750", "brand", "size",
}

MIN_WORD_LEN = 3


# ============================================================================
# Section B: Data structures
# ============================================================================


@dataclass(frozen=True)
class SheetProductRow:
    """One Products_Master row resolved for read-only intelligence.

    Attributes:
        row_index: 1-based sheet row (2 = first data row).
        generic_name: Col A value.
        brand: Col G (Brand_Type) value.
        category: Col B value.
        size: Col C value.
        prices: store -> float price (only stores with a parseable price).
            Keys are lowercase store ids: "woolworths", "coles", "aldi".
        specials: store -> special_desc string (only stores whose specials
            column M/N exists and is non-empty).
        rewards: rewards string from col O ("" if absent/empty).
    """
    row_index: int
    generic_name: str
    brand: str = ""
    category: str = ""
    size: str = ""
    prices: dict = field(default_factory=dict)
    specials: dict = field(default_factory=dict)
    rewards: str = ""


@dataclass(frozen=True)
class ResolvedItem:
    """Result of resolving a user-typed product query.

    Attributes:
        query: the original user-typed string (unmodified).
        source: "exact_sheet" | "partial_sheet" | "live_search" | "not_found".
        confidence: "exact" | "partial" | "live" | "none".
        generic_name: matched Col A value (sheet sources), or the chosen
            live result's raw_name (live source), or "" if not_found.
        row_index: 1-based sheet row for sheet sources, else None.
        prices: store -> float price. For sheet sources, copied from the
            SheetProductRow.prices. For live source, the first/best
            ProductItem price per store. Empty for not_found.
        specials: store -> special_desc (same sourcing rule as prices).
        brand: brand string (Col G for sheet, ProductItem.brand for live).
        live_items: list[ProductItem] from the live search (empty unless
            source == "live_search").
        note: human-readable resolution note.
    """
    query: str
    source: str
    confidence: str
    generic_name: str = ""
    row_index: Optional[int] = None
    prices: dict = field(default_factory=dict)
    specials: dict = field(default_factory=dict)
    brand: str = ""
    live_items: list = field(default_factory=list)
    note: str = ""


# ============================================================================
# Section D: SheetIndex
# ============================================================================


class SheetIndex:
    """In-memory read-only view of Products_Master for recipe resolution.

    Built ONCE from get_all_values() rows (header excluded). Holds:
        - _rows: list[SheetProductRow]
        - _generic_map: normalized generic name -> SheetProductRow (first wins)
        - _keyword_map: normalized keyword -> SheetProductRow (covers Col
          I/J/K for all stores; first wins)

    Provides exact lookup (generic or keyword) and partial lookup
    (substring + word-overlap on Col A).
    """

    def __init__(self, rows: list[list[str]], header: list[str]) -> None:
        """Build from all_values()[1:] and all_values()[0].

        Resolves specials columns M/N and rewards column O by header name
        via sheets_sync._find_col (header-driven, robust to absence).
        Parses prices D/E/F via the same float regex pattern as
        sheets_sync.update_single_price: (?:A$|$)\\s*(\\d+\\.?\\d*)
        then float() fallback. Blank/unparseable -> omit from prices dict.
        """
        self._rows: list[SheetProductRow] = []
        self._generic_map: dict[str, SheetProductRow] = {}
        self._keyword_map: dict[str, SheetProductRow] = {}

        # Resolve specials column indices by header name
        specials_col: dict[str, int] = {}
        for store_key in ("woolworths", "coles"):
            header_name = f"{store_key.capitalize()}_Specials"
            idx = _find_col(header, header_name)
            if idx is not None:
                specials_col[store_key] = idx

        # Resolve rewards column
        rewards_col = _find_col(header, "Rewards_Points")

        _price_re = re.compile(r"(?:A\$|\$)\s*(\d+\.?\d*)")

        for i, row in enumerate(rows):
            generic_name = str(row[0]).strip() if len(row) > 0 else ""
            if not generic_name:
                continue

            row_index = i + 2  # 1-based
            brand = str(row[6]).strip() if len(row) > 6 else ""
            category = str(row[1]).strip() if len(row) > 1 else ""
            size = str(row[2]).strip() if len(row) > 2 else ""

            # Parse prices from D (idx 3), E (idx 4), F (idx 5)
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

            # Parse specials from resolved M/N column indices
            specials: dict = {}
            for store_key, col_idx in specials_col.items():
                if col_idx < len(row) and row[col_idx].strip():
                    specials[store_key] = str(row[col_idx]).strip()

            # Parse rewards from resolved O column
            rewards = ""
            if rewards_col is not None and rewards_col < len(row):
                rewards = str(row[rewards_col]).strip()

            sheet_row = SheetProductRow(
                row_index=row_index,
                generic_name=generic_name,
                brand=brand,
                category=category,
                size=size,
                prices=prices,
                specials=specials,
                rewards=rewards,
            )
            self._rows.append(sheet_row)

            # Populate _generic_map (first wins)
            norm = self._normalize(generic_name)
            if norm not in self._generic_map:
                self._generic_map[norm] = sheet_row

            # Populate _keyword_map from Col I (idx 8), J (idx 9), K (idx 10)
            for kw_col in (8, 9, 10):
                if kw_col < len(row) and row[kw_col].strip():
                    kw_norm = self._normalize(row[kw_col])
                    if kw_norm not in self._keyword_map:
                        self._keyword_map[kw_norm] = sheet_row

    @staticmethod
    def _normalize(s: str) -> str:
        """Re-export KeywordIndex._normalize for consistency."""
        from core.name_matcher import KeywordIndex
        return KeywordIndex._normalize(s)

    def find_exact(self, query: str) -> Optional[SheetProductRow]:
        """Step 1: exact match.

        Normalize query; return the row whose normalized generic name (Col
        A) equals it, ELSE whose normalized keyword (Col I/J/K) equals it.
        First wins. None if no hit.
        """
        norm = self._normalize(query)
        if norm in self._generic_map:
            return self._generic_map[norm]
        if norm in self._keyword_map:
            return self._keyword_map[norm]
        return None

    def find_partial(self, query: str) -> Optional[SheetProductRow]:
        """Step 2: partial match (deterministic, NOT rapidfuzz).

        Normalize query -> tokens = significant words (len>=3, not stopword).
        Score each row's normalized Col A:
            +2 if query_normalized is a substring of col_a_normalized
            +2 if col_a_normalized is a substring of query_normalized
            +1 per significant query word present in col_a_normalized
        Return the highest-scoring row with score > 0. Tie-break: shortest
        Col A, then lowest row_index. None if no row scores > 0.
        """
        norm_query = self._normalize(query)
        tokens = [
            w for w in norm_query.split()
            if len(w) >= MIN_WORD_LEN and w not in STOPWORDS
        ]
        if not tokens:
            return None

        best_score = 0
        best_row: Optional[SheetProductRow] = None
        for row in self._rows:
            norm_a = self._normalize(row.generic_name)
            score = 0
            if norm_query in norm_a:
                score += 2
            if norm_a in norm_query:
                score += 2
            for token in tokens:
                if token in norm_a:
                    score += 1
            if score > best_score:
                best_score = score
                best_row = row
            elif score == best_score and best_row is not None and score > 0:
                # Tie-break: shortest Col A, then lowest row_index
                if len(row.generic_name) < len(best_row.generic_name):
                    best_row = row
                elif (
                    len(row.generic_name) == len(best_row.generic_name)
                    and row.row_index < best_row.row_index
                ):
                    best_row = row

        return best_row


# ============================================================================
# Section E: RecipeResolver
# ============================================================================


class RecipeResolver:
    """Three-step resolver: sheet exact -> sheet partial -> live search.

    Args:
        worksheet: optional pre-connected gspread Worksheet. If None,
            connects fresh via sheets_client.connect_worksheet() on first
            use (lazy). Tests pass a FakeWorksheet.
    """

    def __init__(self, worksheet=None) -> None:
        self._worksheet = worksheet
        self._index = None  # SheetIndex, built lazily

    def _ensure_index(self) -> SheetIndex:
        """Build SheetIndex from the worksheet (lazy, once)."""
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
        self._index = SheetIndex(rows, header)
        return self._index

    def resolve(self, query: str) -> ResolvedItem:
        """Resolve ONE query through the three steps. Stop at first hit.

        1. exact = self._index.find_exact(query) -> SheetProductRow
        2. partial = self._index.find_partial(query) -> SheetProductRow
        3. live = self._live_search(query) -> list[ProductItem]
        4. Else: source="not_found", confidence="none", all fields empty.
        """
        idx = self._ensure_index()

        # Step 1: exact
        exact = idx.find_exact(query)
        if exact is not None:
            return ResolvedItem(
                query=query,
                source="exact_sheet",
                confidence="exact",
                generic_name=exact.generic_name,
                row_index=exact.row_index,
                prices=dict(exact.prices),
                specials=dict(exact.specials),
                brand=exact.brand,
                note=f"matched generic '{exact.generic_name}'",
            )

        # Step 2: partial
        partial = idx.find_partial(query)
        if partial is not None:
            return ResolvedItem(
                query=query,
                source="partial_sheet",
                confidence="partial",
                generic_name=partial.generic_name,
                row_index=partial.row_index,
                prices=dict(partial.prices),
                specials=dict(partial.specials),
                brand=partial.brand,
                note=f"matched generic '{partial.generic_name}' via partial",
            )

        # Step 3: live search
        live_items = self._live_search(query)
        if live_items:
            # Pick first result per store
            prices = {}
            specials = {}
            brand = ""
            name = ""
            seen_stores = set()
            for item in live_items:
                store = item.store.lower()
                if store not in seen_stores and store in ("woolworths", "coles"):
                    seen_stores.add(store)
                    prices[store] = item.price
                    if item.is_special and item.special_desc:
                        specials[store] = item.special_desc
                    if not brand and item.brand:
                        brand = item.brand
                    if not name and item.raw_name:
                        name = item.raw_name
            return ResolvedItem(
                query=query,
                source="live_search",
                confidence="live",
                generic_name=name,
                prices=prices,
                specials=specials,
                brand=brand,
                live_items=live_items,
                note="live match from store APIs",
            )

        # Not found
        return ResolvedItem(
            query=query,
            source="not_found",
            confidence="none",
            note="no match in any source",
        )

    def resolve_list(self, items_str) -> list[ResolvedItem]:
        """Parse a comma/newline/semicolon string (or list) and resolve each.

        Uses _parse_ingredients. Preserves input order. One resolve() per
        item.
        """
        if isinstance(items_str, list):
            names = [str(n).strip() for n in items_str if str(n).strip()]
        else:
            names = self._parse_ingredients(str(items_str))
        return [self.resolve(name) for name in names]

    @staticmethod
    def _parse_ingredients(text: str) -> list[str]:
        """Split on comma/newline/semicolon, strip, drop empties, drop
        duplicates (preserve first occurrence)."""
        parts = re.split(r"[,;\n]+", text)
        seen = set()
        out = []
        for p in parts:
            p = p.strip()
            if p and p.lower() not in seen:
                seen.add(p.lower())
                out.append(p)
        return out

    def _live_search(self, query: str) -> list:
        """Call fetch_woolworths_search + fetch_coles_search for the query.
        Concatenate results. Swallow exceptions (return [] on failure)."""
        if not query or not query.strip():
            return []
        out = []
        # Lazy imports to avoid import cycles and keep test import cheap
        from extractors.woolworths_extractor import fetch_woolworths_search
        from extractors.coles_extractor import fetch_coles_search
        try:
            out += fetch_woolworths_search(query, page_size=5)
        except Exception as exc:
            print(
                f"[recipe_resolver] woolworths live search failed: {exc}",
                file=sys.stderr,
            )
        try:
            out += fetch_coles_search(query, page_size=5)
        except Exception as exc:
            print(
                f"[recipe_resolver] coles live search failed: {exc}",
                file=sys.stderr,
            )
        return out


# ============================================================================
# Section F: __main__
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Resolve a recipe/shopping list against Products_Master"
    )
    parser.add_argument(
        "items", nargs="?", default="",
        help="Comma/newline/semicolon-separated product names"
    )
    args = parser.parse_args()

    if not args.items:
        print(
            "Usage: python core/recipe_resolver.py 'milk, bread, beef mince'",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        resolver = RecipeResolver()
        results = resolver.resolve_list(args.items)
        for item in results:
            prices_str = ", ".join(
                f"{store}: ${price:.2f}"
                for store, price in sorted(item.prices.items())
            ) if item.prices else "no prices"
            print(
                f"{item.query:30s} | {item.source:15s} "
                f"| {item.generic_name:25s} | {prices_str}"
            )
        not_found = [r.query for r in results if r.source == "not_found"]
        if not_found:
            print(f"\nNot found: {', '.join(not_found)}")
        sys.exit(0 if not not_found else 1)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
