"""Offline tests for tools/sheet_backup.compare_counts (no network)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from sheet_backup import compare_counts


class TestCompareCounts(unittest.TestCase):
    def test_identical_passes(self):
        src = [("Products_Master", 113, 19), ("Local_Deals", 133, 10)]
        self.assertEqual(compare_counts(src, list(src)), [])

    def test_row_mismatch_flagged(self):
        src = [("Products_Master", 113, 19)]
        self.assertEqual(
            compare_counts(src, [("Products_Master", 110, 19)]),
            ["Products_Master: 113x19 -> 110x19"])

    def test_missing_tab_flagged(self):
        self.assertEqual(
            compare_counts([("Local_Deals", 133, 10)], []),
            ["Local_Deals: MISSING from backup"])


if __name__ == "__main__":
    unittest.main()
