#!/usr/bin/env python3
"""Pure unit tests for core/name_matcher.py — no network, no live sheet.

Usage:
    python grocery-price-tracker/tests/test_name_matcher.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Bootstrap sys.path so core/ and extractors/ are importable
_HERE = Path(__file__).resolve().parent  # tests/
_PROJECT = _HERE.parent  # grocery-price-tracker/
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core.name_matcher import (
    KeywordIndex,
    NameMatcher,
    MatchResult,
    classify_product,
    append_unmatched,
    get_pending_mappings,
    clear_resolved,
    QUEUE_PATH,
)
from core.lookup import LookupIndex
from extractors.models import ProductItem

# ---------------------------------------------------------------------------
# Mock Products_Master rows (header excluded)
# rows[i] -> sheet row i+2
# Columns: A(generic), B(category), C(size), ..., I(Woolworths kw),
#           J(Coles kw), K(Aldi kw), ...
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Mock Products_Master rows (header excluded)
# rows[i] -> sheet row i+2
# Columns: A(generic), B(category), C(size), ..., I(Woolworths kw),
#           J(Coles kw), K(Aldi kw), ...
# ---------------------------------------------------------------------------
MOCK_ROWS = [
    ["Oat Milk", "Dairy", "1L", "", "", "", "", "", "Oatly Barista 1L", "Oatly Barista 1L", "", ""],
    ["Full Cream Milk", "Dairy", "2L", "", "", "", "", "", "", "Coles Full Cream Milk 2L", ""],
    ["Beef Mince", "Meat", "500g", "", "", "", "", "", "Woolworths Beef Mince 500g", "", ""],
    ["Cheese Block", "Dairy", "500g", "", "", "", "", "", "Bega Cheese Block 500g", "Bega Cheese Block 500g", ""],
]

# ---------------------------------------------------------------------------
# Extended mock rows with Col P (Keywords) for Phase 9.7.b two-pass tests
# Columns: A(generic), B(cat), C(size), D/E/F(prices), G(brand), H(ts),
#           I(Woolworths kw), J(Coles kw), K(Aldi kw), L(Aldi_Refresh),
#           M/N(specials), O(rewards), P(Keywords)
# ---------------------------------------------------------------------------
MOCK_HEADER_EXTENDED = [
    "Product_Name", "Category", "Size", "Woolworths_Price",
    "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
    "Search_Keyword_Woolworths", "Search_Keyword_Coles",
    "Search_Keyword_Aldi", "Aldi_Refresh",
    "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
    "Keywords",
]

MOCK_ROWS_EXTENDED = [
    # Row 1: Oat Milk — exact alias "oatly" in Col P
    ["Oat Milk", "Dairy", "1L", "", "", "", "", "",
     "Oatly Barista 1L", "", "", "", "", "", "", "oatly"],
    # Row 2: Full Cream — no Col P alias
    ["Full Cream Milk", "Dairy", "2L", "", "", "", "", "",
     "", "Coles Full Cream Milk 2L", "", "", "", "", "", ""],
    # Row 3: Beef Mince — token alias "beef mince" in Col P
    ["Beef Mince 500g", "Meat", "500g", "", "", "", "", "",
     "Woolworths Beef Mince 500g", "", "", "", "", "", "", "beef mince"],
    # Row 4: Cheese Block — multiple aliases pipe-delimited
    ["Cheese Block", "Dairy", "500g", "", "", "", "", "",
     "Bega Cheese Block 500g", "Bega Cheese Block 500g", "",
     "", "", "", "", "cheese|bega|tasty cheese"],
    # Row 5: Eggs — multi-word alias
    ["Free Range Eggs", "Dairy", "12pk", "", "", "", "", "",
     "", "", "", "", "", "", "", "free range eggs dozen"],
]


def _make_item(store: str, raw_name: str) -> ProductItem:
    """Create a minimal ProductItem for testing."""
    return ProductItem(
        store=store,
        raw_name=raw_name,
        price=0.0,
    )


class TestNameMatcher(unittest.TestCase):
    """12 pure unit tests for exact keyword matching."""

    @classmethod
    def setUpClass(cls):
        cls.index = KeywordIndex(MOCK_ROWS)
        cls.matcher = NameMatcher(cls.index)

    # --- Test 1: exact match returns correct row_index and generic_name ---
    def test_exact_match_returns_row_index(self):
        item = _make_item("woolworths", "Oatly Barista 1L")
        result = self.matcher.match(item)
        self.assertTrue(result.matched)
        self.assertEqual(result.row_index, 2)
        self.assertEqual(result.generic_name, "Oat Milk")
        self.assertEqual(result.strategy, "exact_keyword")
        self.assertEqual(result.store, "woolworths")

    # --- Test 2: case-insensitive match ---
    def test_case_insensitive_match(self):
        item = _make_item("woolworths", "oatly barista 1l")
        result = self.matcher.match(item)
        self.assertTrue(result.matched)
        self.assertEqual(result.row_index, 2)

    # --- Test 3: whitespace-normalized match ---
    def test_whitespace_normalized_match(self):
        item = _make_item("woolworths", "Oatly   Barista   1L")
        result = self.matcher.match(item)
        self.assertTrue(result.matched)
        self.assertEqual(result.row_index, 2)

    # --- Test 4: Coles keyword matches Coles column ---
    def test_coles_keyword_matches_coles_column(self):
        item = _make_item("coles", "Coles Full Cream Milk 2L")
        result = self.matcher.match(item)
        self.assertTrue(result.matched)
        self.assertEqual(result.row_index, 3)
        self.assertEqual(result.generic_name, "Full Cream Milk")

    # --- Test 5: per-store isolation — Woolworths keyword not in Coles ---
    def test_per_store_isolation_woolworths_keyword_not_in_coles(self):
        item = _make_item("coles", "Woolworths Beef Mince 500g")
        result = self.matcher.match(item)
        self.assertFalse(result.matched)
        self.assertIsNone(result.row_index)
        self.assertEqual(result.strategy, "none")

    # --- Test 6: unknown item is unmapped ---
    def test_unknown_item_is_unmapped(self):
        item = _make_item("woolworths", "Some Random New Product 200g")
        result = self.matcher.match(item)
        self.assertFalse(result.matched)
        self.assertIsNone(result.row_index)
        self.assertEqual(result.strategy, "none")

    # --- Test 7: classify_product extracts brand, size, category ---
    def test_classify_product_extracts_brand_size_category(self):
        classification = classify_product("Oatly Barista Edition Oat Milk 1L")
        self.assertEqual(classification["brand"], "Oatly")
        self.assertIn(classification["size"].lower(), {"1l", "1 l"})
        self.assertEqual(classification["category"], "Dairy")

    # --- Test 8: append_unmatched is idempotent ---
    def test_append_unmatched_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_path = QUEUE_PATH
            try:
                # Monkey-patch QUEUE_PATH to temp directory
                import core.name_matcher as nm
                test_queue = Path(tmpdir) / "unmapped_queue.json"
                nm.QUEUE_PATH = test_queue

                item = _make_item("woolworths", "New Product XYZ 500g")
                classification = classify_product(item.raw_name)

                # Append same item twice
                append_unmatched(item, classification)
                append_unmatched(item, classification)

                entries = get_pending_mappings()
                self.assertEqual(len(entries), 1)
                self.assertEqual(entries[0]["count"], 2)
                self.assertEqual(entries[0]["first_seen"], entries[0]["last_seen"])
            finally:
                nm.QUEUE_PATH = orig_path

    # --- Test 9: get_pending_mappings returns queued entries ---
    def test_get_pending_mappings_returns_queued(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import core.name_matcher as nm
            orig_path = nm.QUEUE_PATH
            try:
                test_queue = Path(tmpdir) / "unmapped_queue.json"
                nm.QUEUE_PATH = test_queue

                item = _make_item("coles", "Another New Item 1kg")
                classification = classify_product(item.raw_name)
                append_unmatched(item, classification)

                pending = get_pending_mappings()
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0]["store"], "coles")
                self.assertEqual(pending[0]["raw_name"], "Another New Item 1kg")
                self.assertEqual(pending[0]["status"], "pending")
            finally:
                nm.QUEUE_PATH = orig_path

    # --- Test 10: clear_resolved removes entry from pending ---
    def test_clear_resolved_removes_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import core.name_matcher as nm
            orig_path = nm.QUEUE_PATH
            try:
                test_queue = Path(tmpdir) / "unmapped_queue.json"
                nm.QUEUE_PATH = test_queue

                item = _make_item("woolworths", "Resolvable Item 300g")
                classification = classify_product(item.raw_name)
                append_unmatched(item, classification)

                # Clear it
                clear_resolved("woolworths", "Resolvable Item 300g")
                pending = get_pending_mappings()
                self.assertEqual(len(pending), 0)

                # Idempotent: second call should not raise
                clear_resolved("woolworths", "Resolvable Item 300g")
            finally:
                nm.QUEUE_PATH = orig_path

    # --- Test 11: empty index matches nothing ---
    def test_empty_index_matches_nothing(self):
        empty_index = KeywordIndex([])
        empty_matcher = NameMatcher(empty_index)
        item = _make_item("woolworths", "Anything At All")
        result = empty_matcher.match(item)
        self.assertFalse(result.matched)
        self.assertIsNone(result.row_index)
        self.assertEqual(result.strategy, "none")

    # --- Test 12: match_batch preserves order and count ---
    def test_match_batch_preserves_order_and_count(self):
        items = [
            _make_item("woolworths", "Oatly Barista 1L"),          # match
            _make_item("coles", "Coles Full Cream Milk 2L"),       # match
            _make_item("woolworths", "Woolworths Beef Mince 500g"), # match
            _make_item("aldi", "Totally Unknown Product 999g"),    # unmapped
        ]
        results = self.matcher.match_batch(items)
        self.assertEqual(len(results), 4)
        self.assertTrue(results[0].matched)
        self.assertTrue(results[1].matched)
        self.assertTrue(results[2].matched)
        self.assertFalse(results[3].matched)
        matched_count = sum(1 for r in results if r.matched)
        self.assertEqual(matched_count, 3)
        # Order preserved
        self.assertEqual(results[0].raw_name, "Oatly Barista 1L")
        self.assertEqual(results[1].raw_name, "Coles Full Cream Milk 2L")
        self.assertEqual(results[2].raw_name, "Woolworths Beef Mince 500g")
        self.assertEqual(results[3].raw_name, "Totally Unknown Product 999g")

    # ------------------------------------------------------------------ #
    # Test 13: KeywordIndex handles extended rows with Col P data
    # ------------------------------------------------------------------ #
    def test_keyword_index_with_extended_rows(self):
        """KeywordIndex correctly indexes Col I/J/K even with 16-col rows."""
        index = KeywordIndex(MOCK_ROWS_EXTENDED)
        matcher = NameMatcher(index)
        # Col I/J/K still work
        item = _make_item("woolworths", "Oatly Barista 1L")
        result = matcher.match(item)
        self.assertTrue(result.matched)
        self.assertEqual(result.generic_name, "Oat Milk")
        # Coles keyword still works
        item2 = _make_item("coles", "Coles Full Cream Milk 2L")
        result2 = matcher.match(item2)
        self.assertTrue(result2.matched)
        self.assertEqual(result2.generic_name, "Full Cream Milk")

    # ------------------------------------------------------------------ #
    # Test 14: No cross-contamination between Col I/J/K and Col P
    # ------------------------------------------------------------------ #
    def test_no_cross_contamination_col_p_and_keywords(self):
        """Col P aliases do NOT leak into KeywordIndex Col I/J/K matching."""
        index = KeywordIndex(MOCK_ROWS_EXTENDED)
        # "oatly" is in Col P, not Col I/J/K — should NOT match
        item = _make_item("woolworths", "oatly")
        result = NameMatcher(index).match(item)
        self.assertFalse(result.matched)
        # "bega" is a Col P alias, not a store keyword — should NOT match
        item2 = _make_item("woolworths", "bega")
        result2 = NameMatcher(index).match(item2)
        self.assertFalse(result2.matched)

    # ------------------------------------------------------------------ #
    # Test 15: LookupIndex Col P exact alias match (Step 2a)
    # ------------------------------------------------------------------ #
    def test_lookup_index_alias_exact(self):
        """LookupIndex.find_alias_exact returns row for exact alias match."""
        idx = LookupIndex(MOCK_ROWS_EXTENDED, MOCK_HEADER_EXTENDED)
        # "oatly" is an exact alias in Col P for row 1
        row = idx.find_alias_exact("oatly")
        self.assertIsNotNone(row)
        self.assertEqual(row["generic_name"], "Oat Milk")
        self.assertEqual(row["row_index"], 2)

    # ------------------------------------------------------------------ #
    # Test 16: LookupIndex Col P exact alias case-insensitive
    # ------------------------------------------------------------------ #
    def test_lookup_index_alias_exact_case_insensitive(self):
        """Exact alias match is case-insensitive."""
        idx = LookupIndex(MOCK_ROWS_EXTENDED, MOCK_HEADER_EXTENDED)
        row = idx.find_alias_exact("OATLY")
        self.assertIsNotNone(row)
        self.assertEqual(row["generic_name"], "Oat Milk")

    # ------------------------------------------------------------------ #
    # Test 17: LookupIndex Col P token match (Step 2b)
    # ------------------------------------------------------------------ #
    def test_lookup_index_alias_token_match(self):
        """Token match finds row when query tokens are subset of alias."""
        idx = LookupIndex(MOCK_ROWS_EXTENDED, MOCK_HEADER_EXTENDED)
        # "tasty" is a token in the "tasty cheese" alias
        row = idx.find_alias_token("tasty")
        self.assertIsNotNone(row)
        self.assertEqual(row["generic_name"], "Cheese Block")

    # ------------------------------------------------------------------ #
    # Test 18: LookupIndex Col P token match multi-word query
    # ------------------------------------------------------------------ #
    def test_lookup_index_alias_token_multi_word(self):
        """Token match with multi-word query on multi-word alias."""
        idx = LookupIndex(MOCK_ROWS_EXTENDED, MOCK_HEADER_EXTENDED)
        # "free eggs" tokens are subset of "free range eggs dozen"
        row = idx.find_alias_token("free eggs")
        self.assertIsNotNone(row)
        self.assertEqual(row["generic_name"], "Free Range Eggs")

    # ------------------------------------------------------------------ #
    # Test 19: LookupIndex Col P token match no hit
    # ------------------------------------------------------------------ #
    def test_lookup_index_alias_token_no_hit(self):
        """Token match returns None when no alias contains all query tokens."""
        idx = LookupIndex(MOCK_ROWS_EXTENDED, MOCK_HEADER_EXTENDED)
        row = idx.find_alias_token("chocolate")
        self.assertIsNone(row)

    # ------------------------------------------------------------------ #
    # Test 20: LookupIndex _normalize consistency across modules
    # ------------------------------------------------------------------ #
    def test_lookup_index_normalize_consistent(self):
        """LookupIndex._normalize and KeywordIndex._normalize are identical."""
        self.assertEqual(
            LookupIndex._normalize("  Multiple   Spaces  "),
            KeywordIndex._normalize("  Multiple   Spaces  "),
        )
        self.assertEqual(LookupIndex._normalize("CamelCase"), "camelcase")
        self.assertEqual(
            LookupIndex._normalize("UPPER lower"),
            "upper lower",
        )

    # ------------------------------------------------------------------ #
    # Test 21: LookupIndex _significant_tokens filters stopwords
    # ------------------------------------------------------------------ #
    def test_lookup_index_significant_tokens_filters_stopwords(self):
        """_significant_tokens excludes short words and stopwords."""
        tokens = LookupIndex._significant_tokens(
            "the milk 1L for bar"
        )
        self.assertIn("milk", tokens)
        self.assertNotIn("the", tokens)
        self.assertNotIn("1l", tokens)    # "1l" = len 2 < MIN_WORD_LEN
        self.assertNotIn("for", tokens)
        self.assertIn("bar", tokens)      # "bar" = len 3, not a stopword


class TestColPTwoPass(unittest.TestCase):
    """4 pure unit tests for the LookupIndex Col P two-pass lookup."""

    @classmethod
    def setUpClass(cls):
        cls.idx = LookupIndex(MOCK_ROWS_EXTENDED, MOCK_HEADER_EXTENDED)

    def test_two_pass_exact_hit_stops_early(self):
        """Exact alias match returns without reaching token pass."""
        row = self.idx.find_alias_exact("oatly")
        self.assertIsNotNone(row)
        self.assertEqual(row["generic_name"], "Oat Milk")

    def test_two_pass_token_hit_after_exact_miss(self):
        """Token match succeeds when exact pass misses."""
        # "dozen eggs" is not an exact alias, but tokens match
        # "free range eggs dozen"
        exact = self.idx.find_alias_exact("dozen eggs")
        self.assertIsNone(exact)
        token = self.idx.find_alias_token("dozen eggs")
        self.assertIsNotNone(token)
        self.assertEqual(token["generic_name"], "Free Range Eggs")

    def test_two_pass_both_miss_returns_none(self):
        """Both passes miss -> None."""
        exact = self.idx.find_alias_exact("nonexistent")
        self.assertIsNone(exact)
        token = self.idx.find_alias_token("nonexistent")
        self.assertIsNone(token)

    def test_pipe_delimited_aliases_parsed_correctly(self):
        """Pipe-delimited aliases produce separate exact and token entries."""
        idx = self.idx
        # "cheese" is exact alias
        self.assertIsNotNone(idx.find_alias_exact("cheese"))
        # "bega" is exact alias
        self.assertIsNotNone(idx.find_alias_exact("bega"))
        # "tasty cheese" is exact alias (multi-word)
        self.assertIsNotNone(idx.find_alias_exact("tasty cheese"))
        # "tasty" alone should token-match "tasty cheese"
        self.assertIsNotNone(idx.find_alias_token("tasty"))
        self.assertEqual(
            idx.find_alias_token("tasty")["generic_name"],
            "Cheese Block",
        )


if __name__ == "__main__":
    unittest.main()
