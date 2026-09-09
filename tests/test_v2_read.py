"""S8/S10.3 — minimal v2 read path: one test per §8 lookup row, §6
list-rule cases, and meat-query halal scoping. Offline (parsed-row
dicts; no network, no writes)."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core.v2_read import (                         # noqa: E402
    lookup_item, missing_list, parse_ld_row, parse_master_row,
    render_list, render_lookup,
)

MASTER_HEADER = ["Product_Name", "Category", "Size",
                 "Woolworths_Price", "Brand_Type", "Last_Updated",
                 "Search_Keyword_Woolworths", "Woolworths_Specials",
                 "Rewards_Points", "Keywords", "Sub_Category",
                 "Item_Code", "Preferred"]


def _m(name, code, ww="", keyword="", sub="", alias="", brand="",
       specials="", size=""):
    row = [""] * 13
    row[0], row[2], row[3], row[4], row[6], row[7], row[9], \
        row[10], row[11] = (
        name, size, ww, brand, keyword, specials, alias, sub, code)
    return parse_master_row(2, row)


def _l(name, code, **prices):
    """prices: shop_key -> (cell_value). Special-first parsing is
    tab_store_price's job — feed raw cells through parse_ld_row."""
    row = [""] * 11
    row[0] = name
    row[10] = code
    col = {"dunya_perm": 1, "dunya_sp": 2, "merjan_perm": 3,
           "merjan_sp": 4, "fruitopia_perm": 5, "fruitopia_sp": 6,
           "abusalim_perm": 7, "abusalim_sp": 8}
    for key, value in prices.items():
        row[col[key]] = value
    return parse_ld_row(3, row, today=None)


class TestLookup(unittest.TestCase):
    """§8 search semantics table (sheet-only)."""

    def setUp(self):
        self.master = [
            _m("Halal Beef Mince 500g", "AUG", ww="$8.50",
               sub="butchery", brand="Home"),
            _m("Tomato", "EYF", ww="$0.54", keyword="woolworths tomato",
               sub="tomato"),
            _m("Halal Lamb Shoulder", "HLS", sub="butchery"),
            _m("Greek Salad Kit", "GS1", sub="greek salad"),
            _m("Tasty Cheese Crackers", "PYF", alias="cheese crackers",
               sub="crackers"),
            _m("Wool-only Peas", "WP1", sub=""),
        ]
        self.ld = [
            _l("Halal Beef Mince 500g", "AUG",
               merjan_sp="7.99 (till 12 Sep)", dunya_perm="9.20"),
            _l("Tomato", "EYF", fruitopia_sp="0.90"),
            _l("Halal Lamb Shoulder", "HLS", dunya_sp="12.99"),
            _l("Greek Salad Kit", "GS1", fruitopia_perm="5.00"),
            _l("Wool-only Peas", "WP1"),
        ]

    def test_row1_tracked(self):
        result = lookup_item("tomato", self.master, self.ld)
        self.assertEqual(result["status"], "tracked")
        self.assertEqual(result["master"]["code"], "EYF")
        self.assertEqual(result["best"][0], "fruitopia")

    def test_row2_meat_term_halal_row(self):
        result = lookup_item("halal beef mince 500g", self.master,
                             self.ld)
        self.assertEqual(result["status"], "tracked")
        self.assertIn("halal", result["master"]["name"].lower())

    def test_row3_meat_term_no_halal_row(self):
        result = lookup_item("chicken", self.master, self.ld)
        self.assertEqual(result["status"], "meat-local-only")
        # no halal MASTER row -> local butcher prices via the first
        # halal-named priced LD row in tab order
        self.assertEqual(result["code"], "AUG")
        self.assertTrue(result["local"])

    def test_row3b_plain_meat_row_invisible_to_meat_query(self):
        """A plain (non-halal) meat row NEVER matches a meat query —
        the §8 row-3 answer (butcher prices + missing-list) applies."""
        master = self.master + [_m("Beef Diced", "BD1", ww="$9.00",
                                   sub="beef diced")]
        result = lookup_item("beef diced", master, self.ld)
        self.assertEqual(result["status"], "meat-local-only")
        self.assertNotEqual(result.get("master") or {},
                            {"name": "Beef Diced"})

    def test_row4_not_tracked_local_has_it(self):
        result = lookup_item("halal lamb shoulder", self.master,
                             self.ld)
        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["code"], "HLS")
        self.assertEqual(result["best"][0], "dunya")

    def test_row5_not_tracked_local_blank_too(self):
        result = lookup_item("wool-only peas", self.master, self.ld)
        self.assertEqual(result["status"], "not-tracked")

    def test_row5b_unknown_query_never_raises(self):
        result = lookup_item("zzz unknown", self.master, self.ld)
        self.assertEqual(result["status"], "not-tracked")

    def test_row6_gone(self):
        master = self.master + [_m("Halal Sausages", "HSG",
                                   ww="GONE", sub="butchery")]
        ld = self.ld + [_l("Halal Sausages", "HSG",
                           merjan_perm="8.00")]
        result = lookup_item("halal sausages", master, ld)
        self.assertEqual(result["status"], "gone")
        self.assertTrue(result["local"])

    def test_row7_na_marker(self):
        master = self.master + [_m("Halal Wings", "HWG",
                                   ww="N/A 2026-09-08", sub="butchery")]
        ld = self.ld + [_l("Halal Wings", "HWG", dunya_perm="11.00")]
        result = lookup_item("halal wings", master, ld)
        self.assertEqual(result["status"], "na")
        self.assertEqual(result["master"]["na_marker"],
                         "N/A 2026-09-08")

    def test_row8_out_of_domain(self):
        result = lookup_item("cheese crackers", self.master, self.ld)
        self.assertEqual(result["status"], "out-of-domain")

    def test_row9_no_live_search_on_miss(self):
        """A miss answers from the sheet only — never a live search."""
        result = lookup_item("never tracked item", self.master,
                             self.ld)
        self.assertEqual(result["status"], "not-tracked")
        self.assertEqual(result["local"], {})

    def test_alias_match(self):
        result = lookup_item("cheese crackers", self.master, self.ld)
        self.assertEqual(result["master"]["code"], "PYF")


class TestMissingList(unittest.TestCase):
    def test_rule_cases(self):
        master = [
            _m("Listed", "LST", ww="", keyword="",
               sub="butchery"),                      # listed
            _m("Real Price", "RPR", ww="$2.00", keyword="",
               sub="tomato"),                        # price -> no
            _m("Keyword Only", "KWO", ww="", keyword="kw",
               sub="tomato"),                        # keyword -> no
            _m("Gone Row", "GNE", ww="GONE", keyword="",
               sub="butchery"),                      # GONE -> no
            _m("Price Only No Local", "PNL", ww="$1.00",
               keyword="kw", sub="tomato"),          # no local -> no
            _m("No Local Price", "NLP", ww="", keyword="",
               sub="butchery"),                      # blank local -> no
            _m("Na With Keyword Not Missing", "NAK",
               ww="N/A 2026-09-01", keyword="kw", sub="tomato"),
        ]
        ld = [
            _l("Listed", "LST", dunya_perm="9.20"),
            _l("Real Price", "RPR"),
            _l("Keyword Only", "KWO"),
            _l("Gone Row", "GNE"),
            _l("Price Only No Local", "PNL"),
            _l("No Local Price", "NLP"),
            _l("Na With Keyword Not Missing", "NAK",
               fruitopia_sp="3.00"),
        ]
        items = missing_list(master, ld)
        self.assertEqual([i["code"] for i in items], ["LST"])
        entry = items[0]
        self.assertEqual(entry["best_local"], (9.20, "dunya"))
        self.assertEqual(entry["shops"], ["dunya"])
        self.assertEqual(entry["name"], "Listed")

    def test_na_without_keyword_is_missing(self):
        master = [_m("Halal Okra", "HOK", ww="unavailable 2026-09-01",
                     sub="butchery")]
        ld = [_l("Halal Okra", "HOK", merjan_perm="6.00")]
        items = missing_list(master, ld)
        self.assertEqual([i["code"] for i in items], ["HOK"])


class TestRender(unittest.TestCase):
    def test_render_tracked_has_display_and_winner(self):
        master = [_m("Halal Beef Mince 500g", "AUG", ww="$8.50",
                     sub="butchery", brand="Home")]
        ld = [_l("Halal Beef Mince 500g", "AUG", merjan_sp="7.99")]
        out = render_lookup(lookup_item("halal beef mince 500g",
                                        master, ld))
        self.assertIn("Halal Beef Mince 500g", out)
        self.assertIn("$", out)
        self.assertIn("🏆", out)
        self.assertIn("[AUG]", out)
        # style kit v2 (spec §11): emoji section header for the
        # WW line + compact footer with the code legend
        self.assertIn("🟢 Woolworths", out)
        self.assertIn("⏱️ 2026-", out)
        self.assertIn("[CODE] = sheet Item_Code", out)

    def test_render_gone_keeps_locals(self):
        master = [_m("Halal Sausages", "HSG", ww="GONE",
                     sub="butchery")]
        ld = [_l("Halal Sausages", "HSG", merjan_perm="8.00")]
        out = render_lookup(lookup_item("halal sausages", master, ld))
        self.assertIn("GONE at Woolworths", out)
        self.assertIn("Merjan", out)

    def test_render_list_lines_and_count(self):
        items = [{"code": "LST", "name": "Listed",
                  "best_local": (9.2, "dunya"), "shops": ["dunya"]}]
        out = render_list(items)
        self.assertIn("[LST] Listed — best $9.20 (Dunya (site))", out)
        self.assertIn("1 item(s)", out)
        self.assertIn("empty", render_list([]))


if __name__ == "__main__":
    unittest.main()
