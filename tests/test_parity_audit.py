"""S9/S10.4 — parity audit utility (A2 semantics): all three statuses
+ the verbatim middle-insert alert + structural-row exemptions."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from tools.parity_audit import (                    # noqa: E402
    MIDDLE_INSERT_ALERT, audit, format_report, is_ld_item_row,
)

MASTER_HEADER = ["Product_Name", "Category", "Size",
                 "Woolworths_Price", "Brand_Type", "Last_Updated",
                 "Search_Keyword_Woolworths", "Woolworths_Specials",
                 "Rewards_Points", "Keywords", "Sub_Category",
                 "Item_Code", "Preferred"]
LD_HEADER = ["Product", "Category", "Dunya perm (site)",
             "Dunya special (FB)", "Merjan perm", "Merjan special",
             "Fruitopia perm", "Fruitopia special",
             "Abu Salim perm", "Abu Salim special", "Nazar perm",
             "Comments", "Item_Code"]


def _mrow(name, code, price=""):
    row = [""] * 13
    row[0], row[3], row[11] = name, price, code
    return row


def _lrow(name, code, prices=""):
    row = [""] * 13
    row[0], row[2], row[12] = name, prices, code
    return row


def _aligned(n=3):
    """master grid + LD grid whose first n item rows pair by code."""
    master = [MASTER_HEADER]
    ld = [LD_HEADER, ["Prices valid until"] + [""] * 12]
    codes = [f"AB{i}".ljust(3, "H") for i in range(n)]
    for i, code in enumerate(codes):
        master.append(_mrow(f"Item {i}", code))
        ld.append(_lrow(f"Local {i}", code))
    return master, ld, codes


class TestAligned(unittest.TestCase):
    def test_aligned_is_silent(self):
        master, ld, _codes = _aligned(3)
        result = audit(master, ld)
        self.assertEqual(result["status"], "aligned")
        self.assertEqual(result["misses"], [])
        self.assertIsNone(result["alert"])
        self.assertEqual(format_report(result), "ALIGNED")

    def test_structural_rows_exempt(self):
        """Section titles + the validity row never break pairing."""
        master, ld, codes = _aligned(3)
        ld.insert(2, ["BUTCHERY"] + [""] * 12)      # title above items
        ld.append(["FRUITS"] + [""] * 12)           # title at the end
        result = audit(master, ld)
        self.assertEqual(result["status"], "aligned")

    def test_blank_uncoded_rows_ignored(self):
        master, ld, _codes = _aligned(2)
        ld.append([""] * 13)
        self.assertEqual(audit(master, ld)["status"], "aligned")

    def test_is_ld_item_row_classification(self):
        self.assertFalse(is_ld_item_row(0, LD_HEADER))
        self.assertFalse(is_ld_item_row(
            1, ["Prices valid until"] + [""] * 12))
        self.assertFalse(is_ld_item_row(2, ["BUTCHERY"] + [""] * 12))
        self.assertTrue(is_ld_item_row(3, _lrow("Beef", "ABC")))
        self.assertTrue(is_ld_item_row(4, _lrow("", "ABC")))  # mirror


class TestBottomAppend(unittest.TestCase):
    def test_extra_master_rows_at_end(self):
        master, ld, _codes = _aligned(2)
        master.append(_mrow("Wool Only", "WOX"))
        result = audit(master, ld)
        self.assertEqual(result["status"], "bottom_append")
        self.assertIsNone(result["alert"])
        self.assertEqual(len(result["misses"]), 1)
        miss = result["misses"][0]
        self.assertEqual(miss["side"], "master")
        self.assertEqual(miss["code"], "WOX")
        self.assertEqual(miss["name"], "Wool Only")

    def test_extra_ld_rows_at_end(self):
        master, ld, _codes = _aligned(1)
        ld.append(_lrow("Local Only", "LOX"))
        result = audit(master, ld)
        self.assertEqual(result["status"], "bottom_append")
        self.assertEqual(result["misses"][0]["side"], "ld")
        self.assertEqual(result["misses"][0]["sheet_row"],
                         len(ld))          # LD sheet row number


class TestMiddleInsert(unittest.TestCase):
    def test_code_break_alerts_verbatim(self):
        master, ld, codes = _aligned(3)
        # A row appears BETWEEN existing LD rows (sheet row 4).
        ld.insert(3, _lrow("Intruder", "NEW"))
        result = audit(master, ld)
        self.assertEqual(result["status"], "middle_insert")
        self.assertEqual(
            result["alert"],
            MIDDLE_INSERT_ALERT.format(n=4))
        self.assertIn("move it to the bottom manually", result["alert"])

    def test_master_side_break_reports_ld_row_number(self):
        master, ld, _codes = _aligned(3)
        master.insert(2, _mrow("Shifted In", "SHX"))
        result = audit(master, ld)
        self.assertEqual(result["status"], "middle_insert")
        # pair 0 still matches; the break is the SECOND item row —
        # Local1 at sheet row 4
        self.assertEqual(result["alert"],
                         MIDDLE_INSERT_ALERT.format(n=4))
        self.assertTrue(result["misses"][0]["master_code"])
        self.assertTrue(result["misses"][0]["ld_code"])


if __name__ == "__main__":
    unittest.main()
