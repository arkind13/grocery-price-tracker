#!/usr/bin/env python3
"""D25/WP3: classifier matrix, Coles docx markers, sheet writes, reporter.

No network. Docx fixtures are written with python-docx into a temp dir.
"""
from __future__ import annotations
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from extractors.specials_parser import (  # noqa: E402
    WAS_RE, ANY_RE, SPECIAL_FLAG_RE, classify_special,
)
from extractors.doc_parser import parse_docx  # noqa: E402
from core.specials_reporter import get_active_specials  # noqa: E402


class FakeWorksheet:
    """Minimal gspread Worksheet mock (get_all_values only)."""

    def __init__(self, rows):
        self._values = [list(r) for r in rows]

    def get_all_values(self):
        return [list(r) for r in self._values]


def _write_docx(paragraphs):
    """Write a temp .docx with the given paragraph strings; return path."""
    from docx import Document
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "list.docx"
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    doc.save(str(path))
    return path, tmp


class TestClassifySpecial(unittest.TestCase):
    """Full precedence matrix (decision 25)."""

    def test_empty_and_not_special_is_no(self):
        self.assertEqual(classify_special(False, ""), "no")

    def test_flag_only_is_discount(self):
        self.assertEqual(classify_special(True, ""), "discount")

    def test_save_desc_is_discount(self):
        self.assertEqual(classify_special(True, "save $1.53 (35% off)"),
                         "discount")

    def test_was_desc_is_discount_even_without_flag(self):
        self.assertEqual(classify_special(False, "Was $13.20"), "discount")

    def test_for_desc_is_multi_buy(self):
        self.assertEqual(classify_special(True, "2 for $4.50"), "multi-buy")
        self.assertEqual(classify_special(True, "6 for $10"), "multi-buy")

    def test_any_desc_is_multi_buy(self):
        self.assertEqual(classify_special(True, "Any 2 | $9"), "multi-buy")

    def test_any_desc_spacing_case_tolerant(self):
        self.assertEqual(classify_special(False, "any 2|$9.00"), "multi-buy")
        self.assertEqual(classify_special(False, "ANY 2 |  $9"), "multi-buy")

    def test_any_beats_save(self):
        self.assertEqual(
            classify_special(True, "Any 2 | $9 and Save $2"), "multi-buy")

    def test_special_flag_desc_is_discount(self):
        self.assertEqual(classify_special(True, "SPECIAL"), "discount")

    def test_half_price_is_discount(self):
        self.assertEqual(classify_special(True, "Half Price"), "discount")

    def test_coles_promotion_type_multi_buy_is_discount(self):
        # P3c: promotionType MULTI_BUY renders as "Multi Buy" — no D25
        # desc pattern matches -> spec-sanctioned "else discount".
        self.assertEqual(classify_special(True, "Multi Buy"), "discount")


class TestMarkerRegexes(unittest.TestCase):
    def test_was_re(self):
        self.assertIsNotNone(WAS_RE.search("Was $13.20"))
        self.assertIsNotNone(WAS_RE.search("was\xa0$9"))
        self.assertIsNone(WAS_RE.search("save $1"))

    def test_any_re(self):
        self.assertIsNotNone(ANY_RE.search("Any 2 | $9"))
        self.assertIsNotNone(ANY_RE.search("ANY 2 | $9.00"))
        self.assertIsNone(ANY_RE.search("Any 2"))
        self.assertIsNone(ANY_RE.search("Any | $9"))

    def test_special_flag_re(self):
        self.assertIsNotNone(SPECIAL_FLAG_RE.match("SPECIAL"))
        self.assertIsNotNone(SPECIAL_FLAG_RE.match(" special "))
        self.assertIsNone(SPECIAL_FLAG_RE.match("SPECIAL OFFER"))
        self.assertIsNone(SPECIAL_FLAG_RE.match("Was $1"))


class TestDocxColesMarkers(unittest.TestCase):
    def _parse(self, paragraphs):
        path, tmp = _write_docx(paragraphs)
        self.addCleanup(tmp.cleanup)
        return parse_docx(str(path), store="coles")

    def test_special_flag_above_name(self):
        items = self._parse(
            ["SPECIAL", "Coles Milk 2L", "$3.20"])
        self.assertTrue(items[0].is_special)
        self.assertEqual(items[0].special_desc, "SPECIAL")

    def test_was_below_price(self):
        items = self._parse(
            ["Coles Bread Loaf", "$2.50", "Was $3.20"])
        self.assertTrue(items[0].is_special)
        self.assertEqual(items[0].special_desc, "Was $3.20")

    def test_any_below_price(self):
        items = self._parse(
            ["Coles Chips 175g", "$4.00", "Any 2 | $9"])
        self.assertTrue(items[0].is_special)
        self.assertEqual(items[0].special_desc, "Any 2 | $9")

    def test_below_line_wins_over_flag_above(self):
        items = self._parse(
            ["SPECIAL", "Coles Yogurt 700g", "$5.00", "Was $6.00"])
        self.assertTrue(items[0].is_special)
        self.assertEqual(items[0].special_desc, "Was $6.00")

    def test_a7_misfire_save_above_next_product_not_attached(self):
        items = self._parse(
            ["WW Product A", "$5.00", "save $1.00", "WW Product B", "$4.00"])
        by_name = {i.raw_name: i for i in items}
        self.assertTrue(by_name["WW Product A"].is_special)
        self.assertFalse(by_name["WW Product B"].is_special)

    def test_plain_item_not_special(self):
        items = self._parse(["Coles Milk 2L", "$3.20"])
        self.assertFalse(items[0].is_special)
        self.assertEqual(items[0].special_desc, "")


class TestReporterVocabulary(unittest.TestCase):
    HEADER = ["Product_Name", "Category", "Size", "Woolworths_Price",
              "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
              "Search_Keyword_Woolworths", "Search_Keyword_Coles",
              "Search_Keyword_Aldi", "Aldi_Refresh",
              "Woolworths_Specials", "Coles_Specials", "Rewards_Points"]

    def _rows(self, ww_cell, coles_cell):
        return [
            self.HEADER,
            ["Milk 2L", "", "", "$4.50", "$4.20", "", "", "",
             "", "", "", "", ww_cell, coles_cell, ""],
        ]

    def test_no_and_empty_excluded(self):
        ws = FakeWorksheet(self._rows("no", ""))
        self.assertEqual(get_active_specials(worksheet=ws), [])

    def test_vocabulary_included_with_cell_as_desc(self):
        ws = FakeWorksheet(self._rows("discount", "multi-buy"))
        result = get_active_specials(worksheet=ws)
        descs = sorted(r["special_desc"] for r in result)
        self.assertEqual(descs, ["discount", "multi-buy"])

    def test_legacy_free_text_reports_as_discount_special(self):
        ws = FakeWorksheet(self._rows("50% off", ""))
        result = get_active_specials(worksheet=ws)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["special_desc"], "50% off")


if __name__ == "__main__":
    unittest.main()
