#!/usr/bin/env python3
"""Unit tests for core/item_codes (spec §8.2 + plan §S3/S4, §13.2).

No network, no sheet — FakeWorksheet simulates gspread; registry and
lock files are patched into a temp dir.
Usage:
    python -m pytest tests/test_item_codes.py -q
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

# Bootstrap sys.path so core/ and extractors/ are importable
_HERE = Path(__file__).resolve().parent  # tests/
_PROJECT = _HERE.parent  # grocery-price-tracker/
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

import core.item_codes as ic
from core.item_codes import (
    CODE_ALPHABET,
    generate_codes,
    is_valid_code,
    load_registry,
    retired_codes,
    save_registry,
)


def _header_a_to_s():
    """Products_Master header A..S (19 columns)."""
    letters = "ABCDEFGHIJKLMNOPQRS"
    return [c for c in letters]


class FakeWorksheet:
    """Mock gspread Worksheet (same pattern as tests/test_cli.py)."""

    def __init__(self, rows, spreadsheet_id="test-sheet-id"):
        self._values = [list(r) for r in rows]
        self.updates = []
        self.spreadsheet = type(
            "SS", (), {"id": spreadsheet_id})()

    def get_all_values(self):
        return [list(r) for r in self._values]

    def update(self, *, values, range_name):
        self.updates.append((values, range_name))
        # Single-cell form "R12" (used by ensure_codes).
        if ":" not in range_name:
            col = ord(range_name[0]) - ord("A")
            row = int(range_name[1:]) - 1
            while len(self._values) <= row:
                self._values.append([])
            self._values[row][col:col + 1] = list(values[0])
        else:  # "A12:S12" full-row form
            import re
            m = re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", range_name)
            col = ord(m.group(1)) - ord("A")
            row = int(m.group(2)) - 1
            while len(self._values) <= row:
                self._values.append([])
            self._values[row][col:col + len(values[0])] = values[0]


class TestIsValidCode(unittest.TestCase):
    """Validity: shape, alphabet, distinct letters, case handling."""

    def test_is_valid_code_accepts_abc(self):
        self.assertTrue(is_valid_code("ABC"))

    def test_is_valid_code_rejects_repeated_letter(self):
        self.assertFalse(is_valid_code("ABA"))

    def test_is_valid_code_rejects_wrong_length(self):
        self.assertFalse(is_valid_code("AB"))
        self.assertFalse(is_valid_code("ABCD"))

    def test_is_valid_code_rejects_excluded_letters(self):
        self.assertFalse(is_valid_code("ABI"))
        self.assertFalse(is_valid_code("ABL"))
        self.assertFalse(is_valid_code("ABO"))

    def test_is_valid_code_lowercased_input_accepted(self):
        # Caller input is uppercased before validation.
        self.assertTrue(is_valid_code("abc"))

    def test_is_valid_code_rejects_empty_none(self):
        self.assertFalse(is_valid_code(""))
        self.assertFalse(is_valid_code(None))


class TestAlphabet(unittest.TestCase):
    """Alphabet contract: 23 letters, no I/L/O."""

    def test_alphabet_excludes_i_l_o(self):
        self.assertEqual(len(CODE_ALPHABET), 23)
        self.assertEqual(
            CODE_ALPHABET, "ABCDEFGHJKMNPQRSTUVWXYZ")
        for excluded in "ILO":
            self.assertNotIn(excluded, CODE_ALPHABET)


class TestGenerateCodes(unittest.TestCase):
    """Generation: uniqueness, validity, determinism."""

    def test_generate_codes_unique_and_valid(self):
        codes = generate_codes(set(), 200)
        self.assertEqual(len(codes), len(set(codes)))
        for code in codes:
            self.assertTrue(is_valid_code(code), msg=code)

    def test_generate_codes_avoids_existing(self):
        existing = {"ABC", "XYZ"}
        codes = generate_codes(existing, 50)
        for code in codes:
            self.assertNotIn(code, existing)
            self.assertTrue(is_valid_code(code), msg=code)

    def test_generate_codes_deterministic_with_seed(self):
        a = generate_codes(set(), 5, seed="seed-1")
        b = generate_codes(set(), 5, seed="seed-1")
        self.assertEqual(a, b)

    def test_generate_codes_exhaustion_raises(self):
        # Take every code; the next call must raise RuntimeError.
        all_codes = generate_codes(set(), 23 * 22 * 21)
        with self.assertRaises(RuntimeError):
            generate_codes(set(all_codes), 1)


class TestRegistryIO(unittest.TestCase):
    """Registry persistence: atomic write, corrupt -> {}."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.reg_path = Path(self._tmp.name) / "registry.json"

    def test_registry_roundtrip_atomic(self):
        save_registry({"ABC": {"row": 2}}, path=self.reg_path)
        self.assertEqual(
            load_registry(self.reg_path), {"ABC": {"row": 2}})
        # No leftover temp files.
        leftovers = list(Path(self._tmp.name).glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_missing_registry_reads_empty(self):
        self.assertEqual(load_registry(self.reg_path), {})

    def test_corrupt_registry_reads_empty(self):
        self.reg_path.write_text("{not json", encoding="utf-8")
        self.assertEqual(load_registry(self.reg_path), {})

    def test_non_dict_registry_reads_empty(self):
        self.reg_path.write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(load_registry(self.reg_path), {})

    def test_retired_codes_uppercased(self):
        self.assertEqual(
            retired_codes({"abc": {}, "XYZ": {}}), {"ABC", "XYZ"})


class TestSheetLayer(unittest.TestCase):
    """Sheet layer (S4): sheet_codes, reserve/confirm/verify,
    ensure_codes backfill, advisory lock."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp_path = Path(self._tmp.name)
        self.reg_patch = mock.patch.object(
            ic, "REGISTRY_PATH", tmp_path / "registry.json")
        self.lock_patch = mock.patch.object(
            ic, "LOCK_PATH", tmp_path / ".item_code_lock")
        self.reg_patch.start()
        self.lock_patch.start()
        self.addCleanup(self.reg_patch.stop)
        self.addCleanup(self.lock_patch.stop)

    def _sheet_with_header(self, data_rows):
        return FakeWorksheet([_header_a_to_s(), *data_rows])

    def test_sheet_codes_reads_col_r(self):
        ws = self._sheet_with_header([
            ["Milk", "Dairy", *[""] * 15, "ABC"],
            ["Bread", "Bakery", *[""] * 15, ""],
            ["", "", *[""] * 16, "ZZZ"],  # empty name ignored
        ])
        self.assertEqual(ic.sheet_codes(ws), {"ABC"})

    def test_reserve_code_unused_and_registered_avoided(self):
        ws = self._sheet_with_header([["Milk", *[""] * 16, "ABC"]])
        save_registry({"QRS": {"row": 99}})
        code = ic.reserve_code(ws, 2)
        self.assertTrue(ic.is_valid_code(code))
        self.assertNotIn(code, {"ABC", "QRS"})

    def test_confirm_code_idempotent_same_row(self):
        ic.confirm_code("ABC", 7, spreadsheet_id="s1")
        ic.confirm_code("ABC", 7, spreadsheet_id="s1")  # no raise
        self.assertEqual(
            load_registry()["ABC"]["row"], 7)

    def test_confirm_code_collision_raises(self):
        ic.confirm_code("ABC", 7)
        with self.assertRaises(RuntimeError):
            ic.confirm_code("ABC", 9)

    def test_verify_code_true_single_owner(self):
        ws = self._sheet_with_header([
            ["Milk", *[""] * 16, "ABC"],
            ["Eggs", *[""] * 16, "DEF"],
        ])
        self.assertTrue(ic.verify_code(ws, 2, "abc"))
        self.assertFalse(ic.verify_code(ws, 2, "DEF"))

    def test_verify_code_false_on_injected_collision(self):
        # Simulate the concurrent writer: another row grabs the code
        # between write and verify.
        ws = self._sheet_with_header([
            ["Milk", *[""] * 16, "ABC"],
            ["Eggs", *[""] * 16, "ABC"],
        ])
        self.assertFalse(ic.verify_code(ws, 2, "ABC"))

    def test_ensure_codes_backfills_all_empty_named_rows(self):
        rows = [[f"Product {i}", *[""] * 18]
                for i in range(200)]
        ws = self._sheet_with_header(rows)
        result = ic.ensure_codes(ws)
        self.assertEqual(result["planned"], 200)
        self.assertEqual(result["written"], 200)
        self.assertEqual(result["failed"], 0)
        codes = result["codes"]
        self.assertEqual(len(codes), len(set(codes)))
        for code in codes:
            self.assertTrue(ic.is_valid_code(code), msg=code)
        # Registry entries == written count.
        registry = load_registry()
        self.assertEqual(len(registry), 200)
        # Every written R cell matches the planned code.
        for offset, code in enumerate(codes, start=2):
            self.assertEqual(
                ws.get_all_values()[offset - 1][17], code)

    def test_ensure_codes_idempotent_second_run(self):
        rows = [[f"Product {i}", *[""] * 18] for i in range(5)]
        ws = self._sheet_with_header(rows)
        ic.ensure_codes(ws)
        second = ic.ensure_codes(ws)
        self.assertEqual(second["planned"], 0)
        self.assertEqual(second["skipped"], 5)

    def test_ensure_codes_dry_run_writes_nothing(self):
        rows = [[f"Product {i}", *[""] * 18] for i in range(3)]
        ws = self._sheet_with_header(rows)
        result = ic.ensure_codes(ws, dry_run=True)
        self.assertEqual(result["planned"], 3)
        self.assertEqual(ws.updates, [])
        self.assertEqual(load_registry(), {})

    def test_ensure_codes_regenerates_on_collision(self):
        # Inject a concurrent duplicate between write and verify:
        # row 3's R cell is stolen by another writer after the write.
        rows = [["P1", *[""] * 18], ["P2", *[""] * 18]]
        ws = self._sheet_with_header(rows)
        original_update = ws.update
        state = {"done": False}

        def sabotaging_update(*, values, range_name):
            original_update(values=values, range_name=range_name)
            if not state["done"] and range_name == "R3":
                # The concurrent writer grabs the same code here.
                state["done"] = True
                original_update(values=[[values[0][0]]],
                                range_name="R2")

        ws.update = sabotaging_update
        result = ic.ensure_codes(ws)
        self.assertEqual(result["written"], 2)
        # Final state: each row still holds a UNIQUE valid code.
        final = [ws.get_all_values()[1][17],
                 ws.get_all_values()[2][17]]
        self.assertNotEqual(final[0], final[1])
        for code in final:
            self.assertTrue(ic.is_valid_code(code), msg=code)

    def test_lock_roundtrip(self):
        # enter/exit removes the lock file; contention from ANOTHER
        # process (lock file present, depth 0) times out quickly.
        with ic._advisory_lock():
            self.assertTrue(ic.LOCK_PATH.exists())
            with mock.patch.object(ic, "LOCK_TIMEOUT_SECONDS", 0.2):
                saved_depth = ic._advisory_lock._depth
                ic._advisory_lock._depth = 0  # simulate other process
                try:
                    with self.assertRaises(TimeoutError):
                        with ic._advisory_lock():
                            pass
                finally:
                    ic._advisory_lock._depth = saved_depth
            # In-process nesting is reentrant (no self-deadlock).
            with ic._advisory_lock():
                pass
        self.assertFalse(ic.LOCK_PATH.exists())


if __name__ == "__main__":
    unittest.main()
