#!/usr/bin/env python3
"""Pure unit tests for core/add_to_list.py (manual website-add queue).

No network, no live sheet, no .env. Every test isolates the queue file
path via patch.object(atl, "ADD_TO_LIST_PATH", tmp path).
"""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))


class TestAddToListModule(unittest.TestCase):
    """Module tests for core/add_to_list.py (plan matrix A1-A20)."""

    # ========================================================================
    # Helpers
    # ========================================================================

    def _patched(self, tmpdir):
        """Return a patcher context for an isolated ADD_TO_LIST_PATH."""
        from core import add_to_list as atl
        return patch.object(
            atl, "ADD_TO_LIST_PATH", Path(tmpdir) / "add_to_list.json")

    def _read_file(self):
        """Read the raw queue file as a JSON list (isolated path)."""
        from core import add_to_list as atl
        with open(atl.ADD_TO_LIST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    # ========================================================================
    # load_pending
    # ========================================================================

    def test_load_missing_file_returns_empty(self):
        """A1: No file -> load_pending() == [], no raise."""
        from core import add_to_list as atl
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._patched(tmpdir):
                self.assertEqual(atl.load_pending(), [])

    def test_load_corrupt_file_returns_empty(self):
        """A2: Corrupt JSON -> [], no raise."""
        from core import add_to_list as atl
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._patched(tmpdir):
                atl.ADD_TO_LIST_PATH.write_text("{not json", encoding="utf-8")
                self.assertEqual(atl.load_pending(), [])

    # ========================================================================
    # add_entry
    # ========================================================================

    def test_add_entry_creates_file_and_stores_fields(self):
        """A3: First add creates the file with exact fields + UTC stamp."""
        from core import add_to_list as atl
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._patched(tmpdir):
                result = atl.add_entry(
                    "woolworths", "Woolworths Beef Mince 500g",
                    "Beef Mince 500g")
                self.assertTrue(result["added"])
                self.assertTrue(atl.ADD_TO_LIST_PATH.exists())
                data = self._read_file()
                self.assertEqual(len(data), 1)
                entry = data[0]
                self.assertEqual(entry["store"], "woolworths")
                self.assertEqual(entry["keyword"],
                                 "Woolworths Beef Mince 500g")
                self.assertEqual(entry["generic_name"], "Beef Mince 500g")
                dt = datetime.fromisoformat(entry["added_at"])
                self.assertIsNotNone(dt.tzinfo)
                self.assertEqual(dt.utcoffset(), timedelta(0))

    def test_add_entry_dup_same_store_skipped(self):
        """A4: Same store + same generic (different casing/whitespace,
        different keyword text) -> added=False, still 1 entry, original
        added_at preserved."""
        from core import add_to_list as atl
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._patched(tmpdir):
                first = atl.add_entry(
                    "woolworths", "Woolworths Beef Mince 500g",
                    "Beef Mince 500g")
                second = atl.add_entry(
                    "woolworths", "WW Beef Mince Premium 500g",
                    "  beef   MINCE 500g ")
                self.assertTrue(first["added"])
                self.assertFalse(second["added"])
                data = self._read_file()
                self.assertEqual(len(data), 1)
                self.assertEqual(data[0]["keyword"],
                                 "Woolworths Beef Mince 500g")
                self.assertEqual(data[0]["added_at"],
                                 first["entry"]["added_at"])

    def test_add_entry_different_store_appends(self):
        """A5: Same generic on both stores -> 2 entries."""
        from core import add_to_list as atl
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._patched(tmpdir):
                atl.add_entry("woolworths", "WW Butter 500g", "Butter 500g")
                atl.add_entry("coles", "Coles Butter 500g", "Butter 500g")
                self.assertEqual(len(self._read_file()), 2)

    def test_add_entry_returns_existing_entry(self):
        """A6: Dup result carries the existing entry dict."""
        from core import add_to_list as atl
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._patched(tmpdir):
                first = atl.add_entry("coles", "Coles Milk 2L", "Milk 2L")
                second = atl.add_entry("coles", "Coles Full Cream 2L",
                                       "Milk 2L")
                self.assertFalse(second["added"])
                self.assertEqual(second["entry"], first["entry"])

    def test_add_entry_invalid_store_raises(self):
        """A7: add_entry('aldi', ...) -> ValueError."""
        from core import add_to_list as atl
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._patched(tmpdir):
                with self.assertRaises(ValueError):
                    atl.add_entry("aldi", "Aldi Milk 2L", "Milk 2L")

    def test_add_entry_blank_names_raise(self):
        """A8: Blank keyword or generic_name -> ValueError."""
        from core import add_to_list as atl
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._patched(tmpdir):
                with self.assertRaises(ValueError):
                    atl.add_entry("coles", "   ", "Milk 2L")
                with self.assertRaises(ValueError):
                    atl.add_entry("coles", "Coles Milk 2L", "")

    # ========================================================================
    # remove_by_numbers
    # ========================================================================

    def _seed_four(self, atl):
        """Seed 2 Coles + 2 Woolworths entries; return their keywords."""
        atl.add_entry("coles", "Coles Item One", "Generic One")
        atl.add_entry("coles", "Coles Item Two", "Generic Two")
        atl.add_entry("woolworths", "Woolies Item Three", "Generic Three")
        atl.add_entry("woolworths", "Woolies Item Four", "Generic Four")

    def test_remove_by_numbers_valid(self):
        """A9: Seed 4 (2C+2W), remove [1,3] -> removed names match; file
        holds the other 2 in order."""
        from core import add_to_list as atl
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._patched(tmpdir):
                self._seed_four(atl)
                result = atl.remove_by_numbers([1, 3])
                removed_names = [e["keyword"] for e in result["removed"]]
                self.assertEqual(removed_names,
                                 ["Coles Item One", "Woolies Item Three"])
                self.assertEqual(result["remaining_count"], 2)
                remaining = [e["keyword"] for e in self._read_file()]
                self.assertEqual(remaining,
                                 ["Coles Item Two", "Woolies Item Four"])

    def test_remove_by_numbers_out_of_range_nothing_removed(self):
        """A10: Remove [1,7] on 4 items -> ValueError naming range 1-4;
        file byte-identical to before."""
        from core import add_to_list as atl
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._patched(tmpdir):
                self._seed_four(atl)
                before = atl.ADD_TO_LIST_PATH.read_bytes()
                with self.assertRaises(ValueError) as ctx:
                    atl.remove_by_numbers([1, 7])
                msg = str(ctx.exception)
                self.assertIn("1-4", msg)
                self.assertEqual(atl.ADD_TO_LIST_PATH.read_bytes(), before)

    def test_remove_by_numbers_empty_queue_raises(self):
        """A11: Empty queue -> ValueError, no file created."""
        from core import add_to_list as atl
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._patched(tmpdir):
                with self.assertRaises(ValueError):
                    atl.remove_by_numbers([1])
                self.assertFalse(atl.ADD_TO_LIST_PATH.exists())

    def test_remove_numbering_is_coles_first(self):
        """A12: Wool entry inserted first, Coles second -> number 1 is
        the Coles entry."""
        from core import add_to_list as atl
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._patched(tmpdir):
                atl.add_entry("woolworths", "Woolies First", "Generic W")
                atl.add_entry("coles", "Coles Second", "Generic C")
                ordered = atl.ordered_entries()
                self.assertEqual(ordered[0]["store"], "coles")
                self.assertEqual(ordered[0]["keyword"], "Coles Second")
                # Number 1 in the render is the Coles entry.
                render = atl.render_show()
                one_line = [ln for ln in render.splitlines()
                            if ln.startswith("1)")]
                self.assertEqual(one_line[0], "1) Coles Second")

    # ========================================================================
    # parse_items_arg
    # ========================================================================

    def test_parse_items_comma_space_and_item_word(self):
        """A13: "1,2,3", "1 2 3", "item 1, 2,3" all -> [1,2,3];
        "1,1,2" -> [1,2] (dedupe)."""
        from core import add_to_list as atl
        self.assertEqual(atl.parse_items_arg("1,2,3"), [1, 2, 3])
        self.assertEqual(atl.parse_items_arg("1 2 3"), [1, 2, 3])
        self.assertEqual(atl.parse_items_arg("item 1, 2,3"), [1, 2, 3])
        self.assertEqual(atl.parse_items_arg("1,1,2"), [1, 2])

    def test_parse_items_invalid_token_raises(self):
        """A14: "1,two", "", "item" -> ValueError."""
        from core import add_to_list as atl
        for raw in ("1,two", "", "item"):
            with self.assertRaises(ValueError):
                atl.parse_items_arg(raw)

    # ========================================================================
    # render_show / render_remaining_flat
    # ========================================================================

    def test_render_empty_message(self):
        """A15: Empty queue render contains the friendly empty line."""
        from core import add_to_list as atl
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._patched(tmpdir):
                output = atl.render_show()
        self.assertIn("add_to_list is empty", output)

    def test_render_continuous_numbering_and_order(self):
        """A16: 2C+2W -> Coles lines numbered 1-2, Woolworths 3-4;
        keywords present; Coles section before Woolworths."""
        from core import add_to_list as atl
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._patched(tmpdir):
                self._seed_four(atl)
                output = atl.render_show()
        lines = output.splitlines()
        self.assertIn("1) Coles Item One", lines)
        self.assertIn("2) Coles Item Two", lines)
        self.assertIn("3) Woolies Item Three", lines)
        self.assertIn("4) Woolies Item Four", lines)
        lowered = output.lower()
        self.assertLess(lowered.index("coles"), lowered.index("woolworths"))

    def test_render_skips_empty_store_section(self):
        """A17: Only woolworths items -> no Coles section header."""
        from core import add_to_list as atl
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._patched(tmpdir):
                atl.add_entry("woolworths", "Woolies Only Item", "Generic W")
                output = atl.render_show()
        self.assertIn("1) Woolies Only Item", output)
        self.assertNotIn("coles", output.lower())

    def test_render_remaining_flat_and_empty_variant(self):
        """A18: Flat lines "n) kw (Store)"; empty list -> now-empty line."""
        from core import add_to_list as atl
        entries = [
            {"store": "coles", "keyword": "Oak Chocolate Milk 750ml"},
            {"store": "woolworths", "keyword": "Obela Hommus 3Pk 60g"},
        ]
        output = atl.render_remaining_flat(entries)
        lines = output.splitlines()
        self.assertEqual(lines[0], "1) Oak Chocolate Milk 750ml (Coles)")
        self.assertEqual(lines[1], "2) Obela Hommus 3Pk 60g (Woolworths)")
        self.assertIn("now empty", atl.render_remaining_flat([]))

    # ========================================================================
    # save_pending atomicity
    # ========================================================================

    def test_save_atomic_tempfile_and_replace(self):
        """A19: os.replace called once on success; when it raises, the
        OSError propagates, the target file is unchanged, and no
        add_to_list_* temp files remain."""
        from core import add_to_list as atl
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._patched(tmpdir):
                # Seed a valid file first (unmocked write).
                atl.add_entry("coles", "Coles Seed Item", "Generic Seed")
                before = atl.ADD_TO_LIST_PATH.read_bytes()

                # Success: os.replace called exactly once.
                with patch("core.add_to_list.os.replace",
                           side_effect=atl.os.replace) as mock_replace:
                    atl.save_pending([])
                    mock_replace.assert_called_once()
                # Restore the seeded content for the failure branch.
                atl.ADD_TO_LIST_PATH.write_bytes(before)

                # Failure: OSError propagates, target unchanged, no temps.
                with patch("core.add_to_list.os.replace",
                           side_effect=OSError("disk full")):
                    with self.assertRaises(OSError):
                        atl.save_pending([{"store": "coles"}])
                self.assertEqual(atl.ADD_TO_LIST_PATH.read_bytes(), before)
                leftovers = list(Path(tmpdir).glob("add_to_list_*"))
                self.assertEqual(leftovers, [])

    # ========================================================================
    # since_label
    # ========================================================================

    def test_since_label_formats_day_month(self):
        """A20: ISO stamp -> "28 Aug"; garbage -> raw string echoed."""
        from core import add_to_list as atl
        label = atl.since_label({"added_at": "2026-08-28T02:00:00+00:00"})
        self.assertEqual(label, "28 Aug")
        raw = atl.since_label({"added_at": "not-a-timestamp"})
        self.assertEqual(raw, "not-a-timestamp")


if __name__ == "__main__":
    unittest.main()
