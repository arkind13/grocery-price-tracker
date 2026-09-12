"""Category engine (user directive 2026-09-12): the classifier, the
category-block resort of BOTH tabs, the safe Nazar duplicate merge,
the Wednesday category step, and the --set-category verdict flow.
Offline (fake worksheets; no network, no real sheet)."""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core import local_deals as ld                 # noqa: E402
from tools.parity_audit import audit as audit_fn   # noqa: E402

LD_HEADER = ["Product"] + [n for _k, n in ld.TAB_COLUMNS]
MASTER_HEADER = ["Product_Name", "Category", "Size",
                 "Woolworths_Price", "Brand_Type", "Last_Updated",
                 "Search_Keyword_Woolworths", "Woolworths_Specials",
                 "Rewards_Points", "Keywords", "Sub_Category",
                 "Item_Code", "Preferred"]


class FakeWS:
    def __init__(self, rows):
        self.grid = [list(r) for r in rows]

    def get_all_values(self):
        return [list(r) for r in self.grid]

    def clear(self):
        pass

    def freeze(self, rows=0):
        pass

    def update(self, *, values, range_name=None, **_kw):
        self.grid = [list(r) for r in values]


def _m(name, code, category="", sub="butchery"):
    row = [""] * 13
    row[0], row[1], row[10], row[11] = name, category, sub, code
    return row


def _l(name, code, category=""):
    row = [""] * 13
    row[0], row[1], row[12] = name, category, code
    return row


class TestClassify(unittest.TestCase):
    def test_species_words_win(self):
        self.assertEqual(ld.classify_category("Halal Beef Mince /kg"),
                         "beef")
        self.assertEqual(ld.classify_category("Halal Whole chicken s14 /ea"),
                         "chicken")
        self.assertEqual(ld.classify_category("Diced Goat"), "goat")
        self.assertEqual(ld.classify_category("Halal Lamb Cutlet /kg"),
                         "lamb")

    def test_user_examples_are_unclassified_butchery(self):
        # the user's own examples: charcoal + roti paratha stay in
        # unclassified - butchery (butchery-source items)
        self.assertEqual(ld.classify_category("Halal Charcoal 10kg",
                                              butchery_source=True),
                         "unclassified - butchery")
        self.assertEqual(ld.classify_category("Halal Roti Paratha /ea",
                                              butchery_source=True),
                         "unclassified - butchery")

    def test_produce_split(self):
        self.assertEqual(ld.classify_category("Carrots /ea"),
                         "vegetables")
        self.assertEqual(ld.classify_category("R2E2 Mango"), "fruits")
        self.assertEqual(ld.classify_category("Pink Lady Apples"),
                         "fruits")
        self.assertEqual(ld.classify_category("Chokos"), "vegetables")

    def test_meat_products_without_species(self):
        self.assertEqual(ld.classify_category("Halal Sucuk (Hot) /ea",
                                              butchery_source=True),
                         "unclassified - butchery")
        self.assertEqual(ld.classify_category(
            "Halal Lemon and Pepper Shish /ea", butchery_source=True),
            "unclassified - butchery")

    def test_spices_go_to_misc(self):
        self.assertEqual(ld.classify_category("Mixed Spices 100g"),
                         "misc - butchery")

    def test_nothing_auto_files_into_non_food(self):
        # Non food is user-assigned only — never produced by the
        # classifier
        for name in ("Charcoal", "Fire Starter", "Plastic Bags",
                     "Detergent"):
            self.assertNotEqual(
                ld.classify_category(name, butchery_source=False),
                "Non food")

    def test_norm_category_forgiving(self):
        self.assertEqual(ld._norm_category(" Vegetables "), "vegetables")
        self.assertEqual(ld._norm_category("NON FOOD"), "Non food")
        self.assertEqual(ld._norm_category("mutton"), "")


class TestResort(unittest.TestCase):
    def _pair(self):
        master = [MASTER_HEADER,
                  _m("Tomato", "EYF", category="vegetables"),
                  _m("Halal Lamb Shoulder", "HLS", category="lamb"),
                  _m("Halal Beef Mince 500g", "AUG", category="beef")]
        ld = [LD_HEADER,
              _l("Tomato", "EYF", "vegetables"),
              _l("Halal Lamb Shoulder", "HLS", "lamb"),
              _l("Halal Beef Mince 500g", "AUG", "beef")]
        return master, ld

    def test_blocks_in_user_order(self):
        master, ld_tab = self._pair()
        m_out, l_out, _lines = ld.resort_tabs_by_category(master, ld_tab)
        # lamb(2) < beef(3) < vegetables(6)
        self.assertEqual([r[0] for r in m_out[1:]],
                         ["Halal Lamb Shoulder", "Halal Beef Mince 500g",
                          "Tomato"])
        # row parity preserved: same order on the LD tab
        self.assertEqual([r[12] for r in l_out[1:]],
                         ["HLS", "AUG", "EYF"])
        self.assertEqual(audit_fn(m_out, l_out)["status"], "aligned")

    def test_review_rows_park_at_the_bottom(self):
        master, ld_tab = self._pair()
        ld_tab.append(_l("Halal Chicken Wings /kg", "NEW1", ""))
        m_out, l_out, _lines = ld.resort_tabs_by_category(
            master, ld_tab, review_codes={"NEW1"})
        self.assertEqual(l_out[-1][0], "Halal Chicken Wings /kg")
        self.assertEqual(l_out[-1][1], "")     # category stays blank

    def test_idempotent(self):
        master, ld_tab = self._pair()
        m1, l1, _ = ld.resort_tabs_by_category(master, ld_tab)
        m2, l2, lines = ld.resort_tabs_by_category(m1, l1)
        self.assertEqual(m1, m2)
        self.assertEqual(l1, l2)
        self.assertIn("already ordered", lines[0])


class TestMergeNazarDuplicates(unittest.TestCase):
    def _pair(self):
        master = [MASTER_HEADER,
                  _m("Halal Beef Curry /kg", "BCU"),
                  _m("Halal Beef Curry (with bone) /kg", "BC2")]
        ld_tab = [LD_HEADER,
                  _l("Halal Beef Curry /kg", "BCU"),
                  _l("Halal Beef Curry (with bone) /kg", "BC2")]
        # the duplicate carries the Nazar price
        ld_tab[2][ld._grid_col("nazar_perm")] = 18.9
        return master, ld_tab

    def test_merge_moves_price_and_drops_both_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "deleted_rows.json"
            master, ld_tab = self._pair()
            m_out, l_out, lines = ld.merge_nazar_duplicates(
                master, ld_tab, archive_path=archive)
            self.assertEqual(len(l_out), 2)        # header + survivor
            self.assertEqual(l_out[1][ld._grid_col("nazar_perm")],
                             18.9)                 # price moved
            self.assertEqual(len(m_out), 2)        # parity on master
            self.assertTrue(any("merged" in ln for ln in lines))
            entries = json.loads(archive.read_text(encoding="utf-8"))
            self.assertEqual({e["side"] for e in entries},
                             {"master", "local_deals"})
            self.assertTrue(all(e["source"] == "nazar-merge"
                                for e in entries))
            self.assertEqual(audit_fn(m_out, l_out)["status"],
                             "aligned")

    def test_idempotent_when_already_merged(self):
        master, ld_tab = self._pair()
        m_out, l_out, lines = ld.merge_nazar_duplicates(master, ld_tab)
        m2, l2, lines2 = ld.merge_nazar_duplicates(m_out, l_out)
        self.assertEqual(l2, l_out)
        self.assertTrue(any("not found" in ln or "already" in ln
                            for ln in lines2))


class TestSetupCategories(unittest.TestCase):
    def test_full_setup_classifies_mirrors_resorts(self):
        with tempfile.TemporaryDirectory() as tmp:
            review_path = Path(tmp) / "category_review.json"
            master = [MASTER_HEADER,
                      _m("Halal Beef Curry /kg", "BCU"),
                      _m("Halal Beef Curry (with bone) /kg", "BC2"),
                      _m("Carrots /ea", "CRT", sub="vegetables")]
            ld_tab = [LD_HEADER,
                      _l("Halal Beef Curry /kg", "BCU"),
                      _l("Halal Beef Curry (with bone) /kg", "BC2"),
                      _l("Carrots /ea", "CRT")]
            ld_tab[2][ld._grid_col("nazar_perm")] = 18.9
            master_ws, ld_ws = FakeWS(master), FakeWS(ld_tab)
            with patch.object(ld, "CATEGORY_REVIEW_PATH", review_path):
                rc, report = ld.setup_categories(master_ws, ld_ws)
            self.assertEqual(rc, 0)
            # the duplicate merged; 2 rows survive on BOTH tabs
            self.assertEqual(len(ld_ws.grid), 3)
            self.assertEqual(len(master_ws.grid), 3)
            # categories assigned + mirrored (beef < vegetables)
            self.assertEqual(master_ws.grid[1][1], "beef")
            self.assertEqual(master_ws.grid[2][1], "vegetables")
            self.assertEqual(ld_ws.grid[1][1], "beef")
            self.assertEqual(ld_ws.grid[2][1], "vegetables")
            self.assertEqual(audit_fn(master_ws.grid, ld_ws.grid)
                             ["status"], "aligned")
            self.assertTrue(any("category assignment" in ln
                                for ln in report))

    def test_review_rows_stay_blank_and_parked(self):
        with tempfile.TemporaryDirectory() as tmp:
            review_path = Path(tmp) / "category_review.json"
            master = [MASTER_HEADER,
                      _m("Halal Chicken Wings /kg", "CWG"),
                      _m("Carrots /ea", "CRT", sub="vegetables")]
            ld_tab = [LD_HEADER,
                      _l("Halal Chicken Wings /kg", "CWG"),
                      _l("Carrots /ea", "CRT")]
            ld_tab[1][ld._grid_col("nazar_perm")] = 7.9
            # park the wings row: it is in NAZAR_REVIEW_ROWS
            self.assertTrue(any(n == "Halal Chicken Wings /kg"
                                for n, _p in ld.NAZAR_REVIEW_ROWS))
            master_ws, ld_ws = FakeWS(master), FakeWS(ld_tab)
            with patch.object(ld, "CATEGORY_REVIEW_PATH", review_path):
                ld.setup_categories(master_ws, ld_ws)
            # parked row stays BLANK and sorts BELOW every block
            self.assertEqual(ld_ws.grid[1][0], "Carrots /ea")
            self.assertEqual(ld_ws.grid[2][0], "Halal Chicken Wings /kg")
            self.assertEqual(master_ws.grid[2][1], "")   # parked blank
            self.assertEqual(ld_ws.grid[2][1], "")       # mirror blank
            saved = json.loads(review_path.read_text(encoding="utf-8"))
            self.assertIn("CWG", saved)


class TestSetCategoryVerdicts(unittest.TestCase):
    def test_verdicts_file_rows_and_clear_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            review_path = Path(tmp) / "category_review.json"
            review_path.write_text(json.dumps(["CWG"]), encoding="utf-8")
            master = [MASTER_HEADER,
                      _m("Carrots /ea", "CRT", category="vegetables",
                         sub="vegetables"),
                      _m("Halal Chicken Wings /kg", "CWG")]
            ld_tab = [LD_HEADER,
                      _l("Carrots /ea", "CRT", "vegetables"),
                      _l("Halal Chicken Wings /kg", "CWG")]
            master_ws, ld_ws = FakeWS(master), FakeWS(ld_tab)
            with patch.object(ld, "CATEGORY_REVIEW_PATH", review_path):
                rc, lines = ld.set_category_verdicts(
                    ["CWG=chicken"], master_ws, ld_ws)
            self.assertEqual(rc, 0)
            self.assertTrue(any("✓ chicken" in ln for ln in lines))
            # the resort filed the verdict: wings (chicken) first
            self.assertEqual(ld_ws.grid[1][0], "Halal Chicken Wings /kg")
            self.assertEqual(master_ws.grid[1][1], "chicken")
            self.assertEqual(ld_ws.grid[1][1], "chicken")
            self.assertEqual(ld_ws.grid[2][0], "Carrots /ea")
            self.assertEqual(ld_ws.grid[2][1], "vegetables")
            self.assertEqual(json.loads(
                review_path.read_text(encoding="utf-8")), [])

    def test_unknown_category_rejected(self):
        master = [MASTER_HEADER, _m("X", "XYZ")]
        ld_tab = [LD_HEADER, _l("X", "XYZ")]
        master_ws, ld_ws = FakeWS(master), FakeWS(ld_tab)
        rc, lines = ld.set_category_verdicts(["XYZ=hardware"],
                                             master_ws, ld_ws)
        self.assertEqual(rc, 0)
        self.assertTrue(any("✗ unknown category" in ln for ln in lines))
        self.assertEqual(ld_tab[1][1], "")


class TestBuildRowsPreCategory(unittest.TestCase):
    def test_new_rows_arrive_categorised(self):
        deal = {"item": "Halal Lamb Neck", "price": 15.99,
                "unit": "kg", "price_kind": "single",
                "multibuy_qty": None, "bulk_size": None,
                "category": "butchery", "notes": ""}
        rows = ld.build_rows({"nazar": [deal]})
        row = rows["BUTCHERY"][0]
        self.assertEqual(row[ld._grid_col("category")], "lamb")


if __name__ == "__main__":
    unittest.main()
