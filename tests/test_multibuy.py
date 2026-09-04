#!/usr/bin/env python3
"""Unit tests for core/multibuy (spec §7 + plan §S2, spec §13.5).

No network, no sheet — pure function tests.
Usage:
    python -m pytest tests/test_multibuy.py -q
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Bootstrap sys.path so core/ and extractors/ are importable
_HERE = Path(__file__).resolve().parent  # tests/
_PROJECT = _HERE.parent  # grocery-price-tracker/
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core.multibuy import (
    MULTIBUY_PREFIX,
    decode_multibuy_cell,
    effective_unit_rate,
    encode_multibuy_cell,
    format_multibuy_note,
    is_mixed_promo,
    is_multibuy_cell,
    parse_multibuy,
)


class TestParseMultibuy(unittest.TestCase):
    """parse_multibuy: FOR / ANY styles + negatives."""

    def test_parse_for_style(self):
        self.assertEqual(parse_multibuy("2 for $6.00"), (2, 6.0))

    def test_parse_any_style(self):
        self.assertEqual(parse_multibuy("Any 2 | $9"), (2, 9.0))

    def test_parse_negative_cream_for_men(self):
        # Spec's canonical false-positive case: FOR_RE requires a
        # leading quantity digit, "Cream For Men" has none.
        self.assertIsNone(parse_multibuy("Cream For Men"))

    def test_parse_negative_qty_one(self):
        self.assertIsNone(parse_multibuy("1 for $3.00"))

    def test_parse_negative_empty_and_garbage(self):
        self.assertIsNone(parse_multibuy(""))
        self.assertIsNone(parse_multibuy(None))
        self.assertIsNone(parse_multibuy("discount"))


class TestIsMixedPromo(unittest.TestCase):
    """D-MB3: 'any N' without FOR terms is informational only."""

    def test_is_mixed_promo_true_for_any_only(self):
        self.assertTrue(is_mixed_promo("Any 2 | $9"))

    def test_is_mixed_promo_false_for_for(self):
        self.assertFalse(is_mixed_promo("2 for $6.00"))

    def test_is_mixed_promo_false_for_plain_text(self):
        self.assertFalse(is_mixed_promo("Save $1.00"))


class TestEffectiveRate(unittest.TestCase):
    """Rate math: total / qty with validation."""

    def test_effective_rate_six_over_two(self):
        self.assertEqual(effective_unit_rate(2, 6.00), 3.00)

    def test_effective_rate_raises_on_bad_args(self):
        with self.assertRaises(ValueError):
            effective_unit_rate(1, 6.00)
        with self.assertRaises(ValueError):
            effective_unit_rate(2, 0.0)
        with self.assertRaises(ValueError):
            effective_unit_rate(2, -1.0)


class TestCellCodec(unittest.TestCase):
    """M/N cell encode/decode (D25 + §7.2)."""

    def test_encode_decode_roundtrip(self):
        cell = encode_multibuy_cell(2, 6.00)
        self.assertEqual(cell, "multi-buy 2/$6.00")
        self.assertEqual(decode_multibuy_cell(cell), (2, 6.0))

    def test_decode_bare_legacy_cell_returns_none(self):
        # Legacy bare "multi-buy" has no terms — informational only.
        self.assertIsNone(decode_multibuy_cell("multi-buy"))

    def test_decode_non_multibuy_returns_none(self):
        for cell in ("discount", "", "no", None):
            self.assertIsNone(decode_multibuy_cell(cell), msg=cell)

    def test_is_multibuy_cell_bare_and_terms(self):
        self.assertTrue(is_multibuy_cell("multi-buy"))
        self.assertTrue(is_multibuy_cell("multi-buy 2/$6.00"))
        self.assertTrue(is_multibuy_cell("  Multi-Buy 3/$10.00 "))
        self.assertFalse(is_multibuy_cell("discount"))

    def test_prefix_vocabulary(self):
        self.assertEqual(MULTIBUY_PREFIX, "multi-buy")


class TestFormatNote(unittest.TestCase):
    """Display tag: EXACT mandatory text (§7.3 rule 2)."""

    def test_format_note_exact_text(self):
        self.assertEqual(
            format_multibuy_note(2, 6.00),
            "🏷️ 2 for $6.00  [Note: must purchase 2+ units to "
            "receive this price]",
        )


if __name__ == "__main__":
    unittest.main()
