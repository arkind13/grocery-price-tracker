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
from unittest.mock import patch

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
    "Search_Keyword_Woolworths",
    "Search_Keyword_" + "Coles",  # (old-schema fixture; assembled)
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
            import core.name_matcher as nm
            test_queue = Path(tmpdir) / "unmapped_queue.json"
            # patch.object restores the LIVE value (conftest-isolated),
            # never a stale import-time path (R2-8/R13).
            with patch.object(nm, "QUEUE_PATH", test_queue):

                item = _make_item("woolworths", "New Product XYZ 500g")
                classification = classify_product(item.raw_name)

                # Append same item twice
                append_unmatched(item, classification)
                append_unmatched(item, classification)

                entries = get_pending_mappings()
                self.assertEqual(len(entries), 1)
                self.assertEqual(entries[0]["count"], 2)
                self.assertEqual(entries[0]["first_seen"], entries[0]["last_seen"])

    # --- Test 9: get_pending_mappings returns queued entries ---
    def test_get_pending_mappings_returns_queued(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import core.name_matcher as nm
            test_queue = Path(tmpdir) / "unmapped_queue.json"
            with patch.object(nm, "QUEUE_PATH", test_queue):

                item = _make_item("coles", "Another New Item 1kg")
                classification = classify_product(item.raw_name)
                append_unmatched(item, classification)

                pending = get_pending_mappings()
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0]["store"], "coles")
                self.assertEqual(pending[0]["raw_name"], "Another New Item 1kg")
                self.assertEqual(pending[0]["status"], "pending")

    # --- Test 10: clear_resolved removes entry from pending ---
    def test_clear_resolved_removes_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import core.name_matcher as nm
            test_queue = Path(tmpdir) / "unmapped_queue.json"
            with patch.object(nm, "QUEUE_PATH", test_queue):

                item = _make_item("woolworths", "Resolvable Item 300g")
                classification = classify_product(item.raw_name)
                append_unmatched(item, classification)

                # Clear it
                clear_resolved("woolworths", "Resolvable Item 300g")
                pending = get_pending_mappings()
                self.assertEqual(len(pending), 0)

                # Idempotent: second call should not raise
                clear_resolved("woolworths", "Resolvable Item 300g")

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

    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #


class TestRecordMissesR2_5(unittest.TestCase):
    """R2-5 (D8-residue): NameMatcher(record_misses=False) — the
    wednesday --dry-run form — classifies misses but NEVER appends them
    to the unmapped queue (unmapped_queue.json was the one data/ file a
    dry run still mutated; verification round 2026-09-08 §4)."""

    def test_record_misses_false_never_writes_queue(self):
        import core.name_matcher as nm
        with tempfile.TemporaryDirectory() as tmpdir:
            test_queue = Path(tmpdir) / "unmapped_queue.json"
            with patch.object(nm, "QUEUE_PATH", test_queue):
                index = KeywordIndex([])
                matcher = NameMatcher(index, record_misses=False)
                result = matcher.match(
                    _make_item("woolworths", "Dry Run Widget 500g"))
                self.assertFalse(result.matched)
                self.assertEqual(result.strategy, "none")
                # The miss was classified but the queue file was never
                # created — no write happened at all.
                self.assertFalse(nm.QUEUE_PATH.exists())
                self.assertEqual(get_pending_mappings(), [])

    def test_record_misses_default_still_writes_queue(self):
        import core.name_matcher as nm
        with tempfile.TemporaryDirectory() as tmpdir:
            test_queue = Path(tmpdir) / "unmapped_queue.json"
            with patch.object(nm, "QUEUE_PATH", test_queue):
                index = KeywordIndex([])
                matcher = NameMatcher(index)
                result = matcher.match(
                    _make_item("coles", "Live Run Widget 500g"))
                self.assertFalse(result.matched)
                pending = get_pending_mappings()
                self.assertEqual(len(pending), 1)
                self.assertEqual(pending[0]["raw_name"],
                                 "Live Run Widget 500g")


if __name__ == "__main__":
    unittest.main()
