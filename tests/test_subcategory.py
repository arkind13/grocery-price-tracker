#!/usr/bin/env python3
"""Unit tests for core/subcategory (taxonomy, spec §4 + plan §S1).

No network, no sheet — pure function tests.
Usage:
    python -m pytest tests/test_subcategory.py -q
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

from core.subcategory import (
    NEEDS_REVIEW,
    all_labels,
    classify_subcategory,
    normalize_subcategory,
)


class TestNormalize(unittest.TestCase):
    """Normalisation contract: case, underscores, hyphens, spaces."""

    def test_normalize_collapses_case_underscore_hyphen(self):
        self.assertEqual(
            normalize_subcategory("  Shredded_Cheese "), "shredded cheese"
        )
        self.assertEqual(
            normalize_subcategory("Long-Life  Milk"), "long life milk"
        )

    def test_normalize_empty_returns_empty(self):
        self.assertEqual(normalize_subcategory(""), "")
        self.assertEqual(normalize_subcategory(None), "")
        self.assertEqual(normalize_subcategory("   "), "")


class TestClassify(unittest.TestCase):
    """Classifier rules: spec examples, ordering, boundary safety."""

    def test_spec_examples(self):
        # Spec-mandated examples (§2): bread, apples, eggs,
        # shredded cheese, cheese slice.
        cases = {
            "Woolworths White Bread 650g": "bread",
            "Royal Gala Apples 1kg": "apples",
            "Woolworths 12 Extra Large Free Range Eggs 700g": "eggs",
            "Coles Shredded Cheese Tasty 500g": "shredded cheese",
            "Devondale Cheese Slices Full Fat 500g": "cheese slice",
        }
        for name, want in cases.items():
            got, conf = classify_subcategory(name)
            self.assertEqual(got, want, msg=name)
            self.assertEqual(conf, 1.0, msg=name)

    def test_compound_before_generic(self):
        # D-SC ordering: "Hillview Cheese Slices Full Fat 500g" must
        # hit "cheese slice", NOT "cheese" and NOT "slices".
        got, conf = classify_subcategory(
            "Hillview Cheese Slices Full Fat 500g")
        self.assertEqual(got, "cheese slice")
        self.assertEqual(conf, 1.0)

    def test_breading_not_bread(self):
        # Boundary safety: "breading" must NOT match the \bbreads?\b
        # rule -> ("", 0.0) -> caller writes NEEDS_REVIEW (D-SC2).
        got, conf = classify_subcategory(
            "AJI CRISPY FRY BREADING MIX ORIGINAL")
        self.assertEqual(got, "")
        self.assertEqual(conf, 0.0)

    def test_breadcrumbs_not_bread(self):
        got, conf = classify_subcategory("Panko Breadcrumbs 200g")
        self.assertEqual(got, "")
        self.assertEqual(conf, 0.0)

    def test_substring_misfires_land_in_review(self):
        # USER REVISION 2026-09-05: substrings must never guess wrong.
        # The live misfires the user reported (V energy drinks filed
        # as sugar/water) plus the same trap class — every case falls
        # through to NEEDS_REVIEW instead of a confident mislabel
        # (verified against the real classifier 2026-09-05).
        misfires = {
            "V Sugarfree Energy 4x250ml": "sugar",   # NOT sugar
            "V Watermelon 250ml": "water",           # NOT water
            "Woolworths Eggplant 300g": "eggs",      # NOT eggs
            "Pineapple Pieces 450g": "apples",       # NOT apples
        }
        for name, wrong in misfires.items():
            got, conf = classify_subcategory(name)
            self.assertNotEqual(got, wrong,
                                msg=f"{name} misfired to {wrong}")
            self.assertEqual((got, conf), ("", 0.0), msg=name)

    def test_v_energy_drink_classifies(self):
        # The user's reported case: V energy drinks must reach the
        # energy drink label when the wording is on the pack. A
        # brand-only wording ("V Guarana Energy") has NO rule match —
        # it goes to review (ask-first), never to a food cluster.
        got, conf = classify_subcategory("V Energy Drink 500ml")
        self.assertEqual((got, conf), ("energy drink", 1.0))
        got, conf = classify_subcategory("V Guarana Energy 250ml")
        self.assertEqual((got, conf), ("", 0.0))

    def test_word_boundary_positives_still_match(self):
        # The \b anchors must not break the real words.
        cases = {
            "Coles Sugar 1kg": "sugar",
            "Mount Franklin Water 600ml": "water",
            "Sun Rice Long Grain 2kg": "rice",
            "PB Spread Smooth 500g": "spread",
        }
        for name, want in cases.items():
            got, conf = classify_subcategory(name)
            self.assertEqual(got, want, msg=name)
            self.assertEqual(conf, 1.0, msg=name)

    def test_corn_chips_before_potato_chips(self):
        # Compound ordering: corn chips before the generic chips rule.
        got, _conf = classify_subcategory("Supreme Cheese Corn Chips")
        self.assertEqual(got, "corn chips")

    def test_confidence_is_1_or_0(self):
        hit, hit_conf = classify_subcategory("Fresh Bananas")
        self.assertEqual((hit, hit_conf), ("bananas", 1.0))
        miss, miss_conf = classify_subcategory("Zzqx Plonk 999")
        self.assertEqual((miss, miss_conf), ("", 0.0))

    def test_category_hint_never_rescues(self):
        # D-SC2: the Col B hint NEVER manufactures a label for a name
        # the rules cannot match.
        got, conf = classify_subcategory("AJI CRISPY FRY BREADING MIX",
                                         category_hint="bread")
        self.assertEqual((got, conf), ("", 0.0))

    def test_empty_name_returns_empty(self):
        self.assertEqual(classify_subcategory(""), ("", 0.0))
        self.assertEqual(classify_subcategory(None), ("", 0.0))


class TestAllLabels(unittest.TestCase):
    """all_labels(): dedupe, order, non-empty, spec coverage."""

    def test_labels_ordered_deduped_nonempty(self):
        labels = all_labels()
        self.assertTrue(labels)
        self.assertEqual(len(labels), len(set(labels)))
        for label in labels:
            self.assertTrue(label)
            self.assertEqual(label, label.strip().lower())
        # Rule order = precedence order: "cheese slice" precedes
        # "cheese"; "corn chips" precedes "potato chips".
        self.assertLess(labels.index("cheese slice"),
                        labels.index("cheese"))
        self.assertLess(labels.index("corn chips"),
                        labels.index("potato chips"))

    def test_spec_mandated_labels_present(self):
        # §2 mandated example labels.
        for want in ("bread", "apples", "eggs", "shredded cheese",
                     "cheese slice"):
            self.assertIn(want, all_labels())

    def test_needs_review_is_not_a_taxonomy_label(self):
        # NEEDS_REVIEW is a caller-side marker, never a rule label.
        self.assertNotIn(NEEDS_REVIEW, all_labels())


if __name__ == "__main__":
    unittest.main()
