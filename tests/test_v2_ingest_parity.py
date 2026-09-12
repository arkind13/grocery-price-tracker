"""T-set 3 — Round-3 ingest changes (spec §5/§9/§18-A1/A2): the Q17
halal prefix at deal normalization, bottom-append parity auto-create
on BOTH tabs in one operation, and the set-prices manual mirror.
Offline (fake worksheets; no network, no sheet)."""
from __future__ import annotations
import io
import contextlib
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


def _ld_grid(rows):
    """[header, validity, FRUITS, item..., BUTCHERY, item...] grid."""
    return [list(r) for r in rows]


LD_HEADER = ["Product"] + [n for _k, n in ld.TAB_COLUMNS]


class FakeWS:
    def __init__(self, rows):
        self.grid = [list(r) for r in rows]

    def get_all_values(self):
        return [list(r) for r in self.grid]

    def clear(self):
        pass

    def freeze(self, rows=0):
        pass

    def update(self, *, values, range_name):
        self.grid = [list(r) for r in values]


def _aligned_pair(ld_rows):
    """An aligned 13-col master + 11-col LD tab (master order ==
    LD item order)."""
    master = [["Product_Name", "", "Size", "Woolworths_Price",
               "Brand_Type", "Last_Updated", "Keyword",
               "Specials", "Rewards", "Keywords", "Sub_Category",
               "Item_Code", "Preferred"]]
    for i, code in enumerate(ld_rows, 1):
        m = [""] * 13
        m[0], m[11] = f"Item {code}", code
        master.append(m)
    return master


class TestHalalPrefix(unittest.TestCase):
    """Q17: every butchery-source item prefixed, whatever the type;
    fruit shops never."""

    def test_butchery_items_all_prefixed(self):
        deals = [{"item": "beef mince"},
                 {"item": "carrots"},              # non-meat item
                 {"item": "Halal Chicken"},
                 {"item": " lamb shoulder "}]
        out = ld._prefix_butcher_deals("merjan", deals)
        self.assertEqual([d["item"] for d in out],
                         ["Halal beef mince", "Halal carrots",
                          "Halal Chicken", "Halal lamb shoulder"])
        # 'Halal Chicken' not double-prefixed (idempotent)
        self.assertEqual(out[2]["item"], "Halal Chicken")

    def test_fruit_shop_never_prefixed(self):
        deals = [{"item": "carrots"}, {"item": "apples"}]
        out = ld._prefix_butcher_deals("fruitopia", deals)
        self.assertEqual([d["item"] for d in out],
                         ["carrots", "apples"])

    def test_ingest_applies_prefix_to_butchery_post(self):
        """The ingest flow prefixes EVERY parsed item of a butchery
        post (carrot juice on a butchery board included) before the
        merge ever sees it."""
        import tempfile as tf
        with tf.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / "MER0909260500"
            inbox.mkdir(parents=True)
            (inbox / "board.txt").write_text(
                "Valid until 20 September\n"
                "Chicken Breast \u2013 $11 each\n"
                "Carrot Juice \u2013 $4 each\n", encoding="utf-8")
            state = {"stores": {"merjan": {
                "baselined": True,
                "notified": {"p1": "MER0909260500"}}}}
            seen = {}
            with patch.object(ld, "INBOX_DIR", Path(tmp)), \
                    patch.object(ld, "SCAN_STATE_PATH",
                                 Path(tmp) / "s.json"), \
                    patch.object(ld, "_save_scan_state"), \
                    patch.object(ld, "_load_scan_state",
                                 return_value=state), \
                    patch("core.sheets_client."
                          "connect_spreadsheet"), \
                    patch("core.sheets_client."
                          "connect_worksheet"), \
                    patch.object(ld, "_load_master_rows",
                                 return_value=[]), \
                    patch.object(ld, "ensure_local_deals_tab",
                                 return_value=FakeWS([])), \
                    patch.object(ld, "merge_store_tab",
                                 side_effect=lambda *a, **k:
                                 seen.update(deals=a[2]) or (5, [])) \
                    as mst, \
                    patch.object(ld, "match_and_detect",
                                 return_value=[]), \
                    patch.object(ld, "render_post1",
                                 return_value="x"), \
                    patch.object(ld, "render_post2_blocks",
                                 return_value=[]), \
                    patch.object(ld, "_send_message",
                                 return_value={"ok": True}):
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = ld.ingest_code("MER0909260500")
            self.assertEqual(rc, 0)
            mst.assert_called_once()
            items = [d["item"] for d in seen["deals"]]
            self.assertEqual(sorted(items),
                             ["Halal Carrot Juice",
                              "Halal Chicken Breast"])


class TestBottomAppendParity(unittest.TestCase):
    """§4.2/§18-A2: new rows append at grid END on BOTH tabs in one
    operation; the master row is blank on D/G and coded."""

    def _merged(self, master_rows, ld_rows, deals,
                store_key="merjan"):
        ld_tab = _ld_grid(
            [[LD_HEADER[0]] + LD_HEADER[1:],
             ["Prices valid until", "n/a (live site)", "", "", "",
              "", "", "", "", "", "", "", ""],
             ["FRUITS"] + [""] * 10]
            + ld_rows
            + [["BUTCHERY"] + [""] * 10])
        master_tab = FakeWS(master_rows)
        worksheet = FakeWS(ld_tab)
        rows, new_lines = ld.merge_store_tab(
            worksheet, store_key, deals,
            master_ws=master_tab)
        return worksheet, master_tab, rows, new_lines

    def test_new_row_mirrors_to_master_both_tabs_aligned(self):
        ld_item = ["Halal Beef Mince 500g", "", "", "", "", "", "",
                   "", "", "", "", "", ""]
        master = _aligned_pair(["EYF"])
        master[1][0] = "Tomato"           # the EYF row named
        ld_rows = [["Tomato", "", "", "", "", "", "0.90", "", "", "",
                    "", "", "EYF"]]
        worksheet, master_tab, rows, new_lines = self._merged(
            master, ld_rows,
            [{"item": "Halal Beef Mince 500g", "raw_text": "x",
              "price": 8.99, "unit": "",
              "price_kind": "single", "multibuy_qty": None,
              "bulk_size": None, "category": "butchery",
              "notes": ""}])
        # (the Q17 prefix ran at ingest normalization — merge sees
        # the already-prefixed deal)
        # LD: appended at GRID END with the code in col K
        grid = worksheet.grid
        self.assertEqual(grid[-1][0], "Halal Beef Mince 500g")
        code = grid[-1][12]
        self.assertRegex(code, r"^[A-Z]{3}$")
        self.assertEqual(rows, len(grid))
        # Master: blank counterpart appended, same code, D/G blank
        mgrid = master_tab.grid
        self.assertEqual(len(mgrid), 3)
        m = mgrid[-1]
        self.assertEqual(m[0], "Halal Beef Mince 500g")
        self.assertEqual(m[11], code)
        self.assertEqual(m[3], "")        # D: NO price (§4.2)
        self.assertEqual(m[6], "")        # G: NO keyword (§4.2)
        self.assertEqual(m[10], "butchery")
        self.assertIn(f"[new row, code {code}]", new_lines[0])
        # Parity holds after the write (audit on the written grids)
        result = audit_fn(mgrid, grid)
        self.assertEqual(result["status"], "aligned")

    def test_fruit_shop_new_row_gets_fruit_domain(self):
        ld_rows = [["Tomato", "", "", "", "", "", "0.90", "", "", "",
                    "", "", "EYF"]]
        master = _aligned_pair(["EYF"])
        master[1][0] = "Tomato"
        worksheet, master_tab, _rows, _lines = self._merged(
            master, ld_rows,
            [{"item": "Cos Lettuce", "raw_text": "x",
              "price": 0.99, "unit": "ea",
              "price_kind": "single", "multibuy_qty": None,
              "bulk_size": None, "category": "fruits",
              "notes": ""}],
            store_key="fruitopia")
        self.assertEqual(master_tab.grid[-1][10], "fruit & veg")
        self.assertEqual(worksheet.grid[-1][0], "Cos Lettuce /ea")
        self.assertEqual(master_tab.grid[-1][0], "Cos Lettuce /ea")

    def test_matched_row_update_appends_nothing(self):
        ld_rows = [["Tomato", "", "", "", "", "", "0.90", "", "", "",
                    "", "", "EYF"]]
        master = _aligned_pair(["EYF"])
        master[1][0] = "Tomato"
        worksheet, master_tab, _rows, new_lines = self._merged(
            master, ld_rows,
            [{"item": "tomatoes", "raw_text": "x",
              "price": 1.10, "unit": "",
              "price_kind": "single", "multibuy_qty": None,
              "bulk_size": None, "category": "fruits",
              "notes": ""}],
            store_key="fruitopia")
        self.assertEqual(len(worksheet.grid), 5)   # no new row
        self.assertEqual(new_lines, [])
        self.assertEqual(len(master_tab.grid), 2)
        self.assertEqual(worksheet.grid[3][7], 1.10)  # FRU special


class TestSetStorePricesMirror(unittest.TestCase):
    def test_manual_butchery_entry_mirrors_to_master(self):
        ws = FakeWS([
            [LD_HEADER[0]] + LD_HEADER[1:],
            ["Prices valid until", "n/a (live site)", "", "", "",
             "", "", "", "", "", "", ""],
            ["BUTCHERY"] + [""] * 12,
            ["Halal Beef Mince 500g", "", "", "9.20", "", "", "",
             "", "", "", "", "", "AUG"],
        ])
        master = _aligned_pair(["AUG"])
        master[1][0] = "Halal Beef Mince 500g"
        master_tab = FakeWS(master)
        lines = ld.set_store_prices(
            ws, "merjan", "special",
            [{"item": "lamb shoulder", "price": 12.99,
              "unit": "kg"}],
            master_ws=master_tab)
        self.assertIn("[new row]", lines[0])
        grid = ws.get_all_values()
        self.assertEqual(grid[-1][0], "Halal lamb shoulder /kg")
        code = grid[-1][12]
        self.assertRegex(code, r"^[A-Z]{3}$")
        m = master_tab.grid[-1]
        self.assertEqual(m[0], "Halal lamb shoulder /kg")
        self.assertEqual(m[11], code)
        self.assertEqual(m[3], "")       # D blank
        self.assertEqual(m[6], "")       # G blank
        result = audit_fn(master_tab.grid, grid)
        self.assertEqual(result["status"], "aligned")


if __name__ == "__main__":
    unittest.main()
