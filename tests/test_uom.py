#!/usr/bin/env python3
"""Pure unit tests for core/uom.py (UOM size parsing + comparability gate).

Covers plan matrix U-1..U-24. No network, no files, no .env — the module
under test is pure stdlib.
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core.uom import (  # noqa: E402
    FAMILY_COUNT,
    FAMILY_LENGTH,
    FAMILY_VOLUME,
    FAMILY_WEIGHT,
    ParsedSize,
    Verdict,
    compare_sizes,
    parse_size,
    size_families_match,
    within_20pct,
)


def _ps(value: float, unit: str, family: str) -> ParsedSize:
    """Shorthand ParsedSize constructor for test fixtures."""
    return ParsedSize(value=value, unit=unit, family=family)


class TestParseSize(unittest.TestCase):
    """Matrix U-1..U-9, U-20..U-21, U-24: parse_size behaviour."""

    def test_u1_parse_25l_to_millilitres(self):
        """U-1: 25L -> 25000 mL, volume family."""
        parsed = parse_size("25L")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.value, 25000.0)
        self.assertEqual(parsed.unit, "mL")
        self.assertEqual(parsed.family, FAMILY_VOLUME)

    def test_u2_parse_volume_case_and_space_insensitive(self):
        """U-2: 600mL / '600 ml' / '600ML' -> 600 mL, volume."""
        for text in ("600mL", "600 ml", "600ML"):
            parsed = parse_size(text)
            self.assertIsNotNone(parsed, text)
            self.assertEqual(parsed.value, 600.0, text)
            self.assertEqual(parsed.unit, "mL", text)
            self.assertEqual(parsed.family, FAMILY_VOLUME, text)

    def test_u3_parse_180g_weight(self):
        """U-3: 180g -> 180 g, weight family."""
        parsed = parse_size("180g")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.value, 180.0)
        self.assertEqual(parsed.unit, "g")
        self.assertEqual(parsed.family, FAMILY_WEIGHT)

    def test_u4_parse_1_2kg_to_grams(self):
        """U-4: 1.2kg -> 1200 g, weight family."""
        parsed = parse_size("1.2kg")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.value, 1200.0)
        self.assertEqual(parsed.unit, "g")
        self.assertEqual(parsed.family, FAMILY_WEIGHT)

    def test_u5_parse_lengths_to_metres(self):
        """U-5: 10m -> 10 m; 50cm -> 0.5 m (length family)."""
        parsed_m = parse_size("10m")
        self.assertEqual(parsed_m.value, 10.0)
        self.assertEqual(parsed_m.unit, "m")
        self.assertEqual(parsed_m.family, FAMILY_LENGTH)
        parsed_cm = parse_size("50cm")
        self.assertEqual(parsed_cm.value, 0.5)
        self.assertEqual(parsed_cm.unit, "m")
        self.assertEqual(parsed_cm.family, FAMILY_LENGTH)

    def test_u6_parse_count_each(self):
        """U-6: '1 each' -> count family, value 1."""
        parsed = parse_size("1 each")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.value, 1.0)
        self.assertEqual(parsed.unit, "ea")
        self.assertEqual(parsed.family, FAMILY_COUNT)

    def test_u7_parse_multipack_weight_variants(self):
        """U-7: '6 x 170g' / '6x170g' / '6 X 170g' -> 1020 g."""
        for text in ("6 x 170g", "6x170g", "6 X 170g"):
            parsed = parse_size(text)
            self.assertIsNotNone(parsed, text)
            self.assertEqual(parsed.value, 1020.0, text)
            self.assertEqual(parsed.unit, "g", text)
            self.assertEqual(parsed.family, FAMILY_WEIGHT, text)

    def test_u8_parse_multipack_volume(self):
        """U-8: '2 x 1L' -> 2000 mL."""
        parsed = parse_size("2 x 1L")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.value, 2000.0)
        self.assertEqual(parsed.unit, "mL")
        self.assertEqual(parsed.family, FAMILY_VOLUME)

    def test_u9_unparseable_inputs_return_none(self):
        """U-9: '' / None / 'hand tool set' / '$4.20' -> None."""
        for text in ("", None, "hand tool set", "$4.20"):
            self.assertIsNone(parse_size(text), repr(text))

    def test_u20_idempotent_on_canonical_strings(self):
        """U-20: re-parsing the canonical rendering yields the same size."""
        for text in ("600mL", "1.2kg", "10m", "1 each", "0.75L", "180g"):
            once = parse_size(text)
            canonical = f"{once.value:g}{once.unit}"
            if once.family == FAMILY_COUNT:
                canonical = f"{once.value:g} each"
            twice = parse_size(canonical)
            self.assertEqual(once, twice, f"{text} -> {canonical}")

    def test_u21_parse_0_75l(self):
        """U-21: 0.75L -> 750 mL."""
        parsed = parse_size("0.75L")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.value, 750.0)
        self.assertEqual(parsed.unit, "mL")

    def test_u24_curated_real_world_sweep(self):
        """U-24: 20 curated real size strings parse to expected families."""
        cases = [
            ("2L", FAMILY_VOLUME),
            ("3L", FAMILY_VOLUME),
            ("1.25L", FAMILY_VOLUME),
            ("750mL", FAMILY_VOLUME),
            ("500mL", FAMILY_VOLUME),
            ("4 x 200mL", FAMILY_VOLUME),
            ("600g", FAMILY_WEIGHT),
            ("1kg", FAMILY_WEIGHT),
            ("500G", FAMILY_WEIGHT),
            ("2kg", FAMILY_WEIGHT),
            ("8 x 100g", FAMILY_WEIGHT),
            ("250mg", FAMILY_WEIGHT),
            ("30m", FAMILY_LENGTH),
            ("2m", FAMILY_LENGTH),
            ("150cm", FAMILY_LENGTH),
            ("1000mm", FAMILY_LENGTH),
            ("1 each", FAMILY_COUNT),
            ("2 each", FAMILY_COUNT),
            ("6 each", FAMILY_COUNT),
            ("  5kg  ", FAMILY_WEIGHT),
        ]
        for text, expected_family in cases:
            parsed = parse_size(text)
            self.assertIsNotNone(parsed, repr(text))
            self.assertEqual(parsed.family, expected_family, repr(text))


class TestFamiliesAndTolerance(unittest.TestCase):
    """Matrix U-10..U-12, U-22: family matching + tolerance band."""

    def test_u10_family_matching_rules(self):
        """U-10: same family True; cross-family always False."""
        self.assertTrue(size_families_match(
            parse_size("600mL"), parse_size("25L")))
        self.assertFalse(size_families_match(
            parse_size("180g"), parse_size("600mL")))
        self.assertTrue(size_families_match(
            parse_size("1 each"), parse_size("6 each")))
        self.assertFalse(size_families_match(
            parse_size("10m"), parse_size("180g")))
        self.assertFalse(size_families_match(
            parse_size("10m"), parse_size("600mL")))
        self.assertFalse(size_families_match(
            parse_size("600mL"), parse_size("1 each")))
        # None propagation.
        self.assertFalse(size_families_match(None, parse_size("600mL")))
        self.assertFalse(size_families_match(parse_size("600mL"), None))

    def test_u11_within_20pct_exact_boundary_passes(self):
        """U-11: within_20pct(25, 30) -> True (exactly 20%)."""
        self.assertTrue(within_20pct(25.0, 30.0))

    def test_u12_within_20pct_just_beyond_fails(self):
        """U-12: within_20pct(25, 30.25) -> False (20.1%)."""
        self.assertFalse(within_20pct(25.0, 30.25))

    def test_u22_family_constants_distinct_verdict_values_match_spec(self):
        """U-22: family constants distinct; Verdict strings match spec."""
        families = {
            FAMILY_WEIGHT, FAMILY_VOLUME, FAMILY_LENGTH, FAMILY_COUNT}
        self.assertEqual(len(families), 4)
        self.assertEqual(Verdict.COMPARABLE_SAME.value, "comparable_same")
        self.assertEqual(
            Verdict.COMPARABLE_TOLERANT.value, "comparable_tolerant")
        self.assertEqual(Verdict.NOT_COMPARABLE.value, "not_comparable")


class TestCompareSizes(unittest.TestCase):
    """Matrix U-13..U-19, U-23: the gate itself."""

    def test_u13_identical_sizes_are_same(self):
        """U-13: compare_sizes(25L, 25L) -> COMPARABLE_SAME."""
        result = compare_sizes(parse_size("25L"), parse_size("25L"))
        self.assertEqual(result.verdict, Verdict.COMPARABLE_SAME)
        self.assertEqual(result.reason, "")

    def test_u14_within_tolerance_is_tolerant(self):
        """U-14: 180g vs 200g -> COMPARABLE_TOLERANT."""
        result = compare_sizes(parse_size("180g"), parse_size("200g"))
        self.assertEqual(result.verdict, Verdict.COMPARABLE_TOLERANT)
        self.assertEqual(result.reason, "")

    def test_u15_beyond_tolerance_not_comparable(self):
        """U-15: 180g vs 500g -> NOT_COMPARABLE / beyond_20pct."""
        result = compare_sizes(parse_size("180g"), parse_size("500g"))
        self.assertEqual(result.verdict, Verdict.NOT_COMPARABLE)
        self.assertEqual(result.reason, "beyond_20pct")

    def test_u16_family_mismatch(self):
        """U-16: 1.2L vs 180g -> NOT_COMPARABLE / family_mismatch."""
        result = compare_sizes(parse_size("1.2L"), parse_size("180g"))
        self.assertEqual(result.verdict, Verdict.NOT_COMPARABLE)
        self.assertEqual(result.reason, "family_mismatch")

    def test_u17_missing_size_not_comparable(self):
        """U-17: None side(s) -> NOT_COMPARABLE / missing_size (IN-3)."""
        for a, b in ((None, parse_size("180g")),
                     (parse_size("180g"), None),
                     (None, None)):
            result = compare_sizes(a, b)
            self.assertEqual(result.verdict, Verdict.NOT_COMPARABLE)
            self.assertEqual(result.reason, "missing_size")

    def test_u18_multipack_vs_single_within_tolerance(self):
        """U-18: 6x170g (1020g) vs 1kg (1000g) -> COMPARABLE_TOLERANT."""
        result = compare_sizes(parse_size("6 x 170g"), parse_size("1kg"))
        self.assertEqual(result.verdict, Verdict.COMPARABLE_TOLERANT)
        self.assertEqual(result.reason, "")

    def test_u19_count_vs_volume_family_mismatch(self):
        """U-19: '1 each' vs 1.2L -> family_mismatch (Seasol-class guard)."""
        result = compare_sizes(parse_size("1 each"), parse_size("1.2L"))
        self.assertEqual(result.verdict, Verdict.NOT_COMPARABLE)
        self.assertEqual(result.reason, "family_mismatch")

    def test_u23_compare_is_symmetric(self):
        """U-23: verdict + reason identical when arguments swap."""
        pairs = (
            (parse_size("25L"), parse_size("25L")),
            (parse_size("180g"), parse_size("200g")),
            (parse_size("180g"), parse_size("500g")),
            (parse_size("1.2L"), parse_size("180g")),
            (None, parse_size("180g")),
            (parse_size("600mL"), None),
        )
        for a, b in pairs:
            forward = compare_sizes(a, b)
            reverse = compare_sizes(b, a)
            self.assertEqual(forward, reverse, f"{a} vs {b}")


if __name__ == "__main__":
    unittest.main()
