#!/usr/bin/env python3
"""Pure unit tests for core/searched_items.py (explicit-add queue).

Covers plan matrix S-1..S-30. No network, no live sheet, no .env. Every
test isolates BOTH queue paths (SEARCHED_ITEMS_PATH + TOMBSTONES_PATH)
via patch.object to temp files.
"""
from __future__ import annotations
import json
import random
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

UTC = timezone.utc


class SearchedItemsTestCase(unittest.TestCase):
    """Base: isolates both module paths into a temp dir."""

    def setUp(self):
        from core import searched_items as si
        self.si = si
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._patchers = [
            patch.object(si, "SEARCHED_ITEMS_PATH",
                         tmp / "searched_items.json"),
            patch.object(si, "TOMBSTONES_PATH",
                         tmp / "searched_item_code_tombstones.json"),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------
    def read_queue(self):
        """Read the raw queue file as a JSON list."""
        with open(self.si.SEARCHED_ITEMS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def read_tombstones(self):
        """Read the raw tombstone file as a JSON list."""
        with open(self.si.TOMBSTONES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def seed(self, entries):
        """Write a queue file directly."""
        self.si.SEARCHED_ITEMS_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.si.SEARCHED_ITEMS_PATH.write_text(
            json.dumps(entries, ensure_ascii=False), encoding="utf-8")

    def seed_tombstones(self, tombstones):
        """Write a tombstone file directly."""
        self.si.TOMBSTONES_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.si.TOMBSTONES_PATH.write_text(
            json.dumps(tombstones, ensure_ascii=False), encoding="utf-8")

    def add_two(self):
        """Seed via API: KAT (coles) + RUM (woolworths); returns entries."""
        r1 = self.si.add_entry(
            "coles", "Obela Classic Hommus 200g", "Hommus 200g", size="200g")
        r1["entry"]["code"] = "KAT"
        r2 = self.si.add_entry(
            "woolworths", "Woolworths Rum & Raisin 1L", "Rum Raisin 1L")
        r2["entry"]["code"] = "RUM"
        self.seed([r1["entry"], r2["entry"]])
        return r1["entry"], r2["entry"]


class TestLoadAndAdd(SearchedItemsTestCase):
    """S-1..S-6, S-27, S-28, S-30: load / add / dup guard."""

    def test_s1_missing_file_loads_empty(self):
        """S-1: missing file -> load_pending() == [], no raise."""
        self.assertEqual(self.si.load_pending(), [])

    def test_s2_corrupt_json_loads_empty(self):
        """S-2: corrupt JSON -> [], no raise."""
        self.si.SEARCHED_ITEMS_PATH.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.si.load_pending(), [])

    def test_s3_add_entry_stores_exact_fields(self):
        """S-3: add creates file with EXACT fields + UTC added_at."""
        result = self.si.add_entry(
            "coles", "Obela Classic Hommus 200g", "Hommus 200g",
            store_product_id="123456")
        self.assertTrue(result["added"])
        data = self.read_queue()
        self.assertEqual(len(data), 1)
        entry = data[0]
        self.assertEqual(set(entry.keys()), {
            "store", "keyword", "store_product_id", "generic_name",
            "code", "size", "added_at"})
        self.assertEqual(entry["store"], "coles")
        self.assertEqual(entry["keyword"], "Obela Classic Hommus 200g")
        self.assertEqual(entry["store_product_id"], "123456")
        self.assertEqual(entry["generic_name"], "Hommus 200g")
        self.assertEqual(len(entry["code"]), 3)
        # UTC ISO stamp parseable + timezone-aware.
        stamp = datetime.fromisoformat(entry["added_at"])
        self.assertIsNotNone(stamp.utcoffset())

    def test_s4_dup_guard_same_store_normalised(self):
        """S-4: same store + same normalised generic -> added=False."""
        first = self.si.add_entry(
            "coles", "Obela Classic Hommus 200g", "Hommus 200g")
        dup = self.si.add_entry(
            "coles", "Obela Classic Hommus 200G ", "HOMMUS  200g")
        self.assertTrue(first["added"])
        self.assertFalse(dup["added"])
        self.assertEqual(dup["entry"]["added_at"],
                         first["entry"]["added_at"])
        self.assertEqual(len(self.read_queue()), 1)

    def test_s5_same_generic_other_store_appends(self):
        """S-5: same generic other store -> appends (2 entries)."""
        self.si.add_entry("coles", "Coles Milk 2L", "Milk 2L")
        self.si.add_entry("woolworths", "WW Milk 2L", "Milk 2L")
        self.assertEqual(len(self.read_queue()), 2)

    def test_s6_invalid_inputs_raise_file_untouched(self):
        """S-6: invalid store / blank keyword / blank generic -> ValueError."""
        for kwargs in (
                {"store": "aldi", "keyword": "X", "generic_name": "Y"},
                {"store": "coles", "keyword": "  ", "generic_name": "Y"},
                {"store": "coles", "keyword": "X", "generic_name": ""}):
            with self.assertRaises(ValueError):
                self.si.add_entry(**kwargs)
        self.assertFalse(self.si.SEARCHED_ITEMS_PATH.exists())

    def test_s27_queue_written_readable(self):
        """S-27: queue written with ensure_ascii=False + indent 2."""
        self.si.add_entry("coles", "Obela Café-Style Hommus 200g",
                          "Hommus 200g")
        raw = self.si.SEARCHED_ITEMS_PATH.read_text(encoding="utf-8")
        self.assertIn("Obela Café-Style Hommus 200g", raw)
        self.assertIn('\n  {', raw)  # indent=2 list item

    def test_s28_entries_preserve_insertion_order(self):
        """S-28: entries stay in insertion order across adds."""
        self.si.add_entry("coles", "First", "first")
        self.si.add_entry("woolworths", "Second", "second")
        self.si.add_entry("coles", "Third", "third")
        names = [e["keyword"] for e in self.read_queue()]
        self.assertEqual(names, ["First", "Second", "Third"])

    def test_s30_import_has_no_env_or_network_side_effects(self):
        """S-30: module source has no _load_env()/requests at import."""
        source = Path(self.si.__file__).read_text(encoding="utf-8")
        self.assertNotIn("_load_env()", source)
        self.assertNotIn("import requests", source)


class TestCodes(SearchedItemsTestCase):
    """S-7..S-11, S-24..S-26: code generation + tombstones."""

    def test_s7_code_letters_valid(self):
        """S-7: code is 3 letters, each from A-Z minus I/O."""
        for _ in range(50):
            code = self.si.generate_code()
            self.assertEqual(len(code), 3)
            for ch in code:
                self.assertIn(ch, self.si.CODE_ALPHABET)

    def test_s8_no_repeated_letter_within_code(self):
        """S-8: exhaustive over >=200 generated codes — no dup letter."""
        for _ in range(200):
            code = self.si.generate_code()
            self.assertEqual(len(set(code)), 3, code)

    def test_s9_code_unique_vs_current_queue(self):
        """S-9: pre-seeded queue code never regenerated."""
        self.seed([{"store": "coles", "keyword": "X", "generic_name": "x",
                    "store_product_id": "", "code": "AAA",
                    "added_at": "2026-08-29T00:00:00+00:00"}])
        for _ in range(50):
            self.assertNotEqual(self.si.generate_code(), "AAA")

    def test_s10_code_unique_vs_live_tombstones(self):
        """S-10: tombstoned code within 7 days is not reused."""
        now = datetime.now(UTC)
        self.seed_tombstones(
            [{"code": "BBB", "removed_at": now.isoformat()}])
        for _ in range(50):
            self.assertNotEqual(self.si.generate_code(), "BBB")

    def test_s11_expired_tombstone_code_reusable(self):
        """S-11: tombstone older than 7 days -> code may be reused."""
        stale = (datetime.now(UTC) - timedelta(days=8)).isoformat()
        self.seed_tombstones([{"code": "CDE", "removed_at": stale}])
        self.seed([{"store": "coles", "keyword": "X", "generic_name": "x",
                    "store_product_id": "", "code": "DDD",
                    "added_at": "2026-08-29T00:00:00+00:00"}])
        # Force generation into the tombstoned letters by shrinking the
        # alphabet to exactly {C,D,E}; any valid arrangement proves the
        # expired tombstone no longer blocks reuse.
        with patch.object(self.si, "CODE_ALPHABET", "CDE"):
            code = self.si.generate_code()
        self.assertEqual(sorted(code), sorted("CDE"))

    def test_s24_deterministic_under_injected_rng(self):
        """S-24: generate_code(rng=...) is deterministic."""
        rng_a = random.Random(42)
        rng_b = random.Random(42)
        seq_a = [self.si.generate_code(rng=rng_a) for _ in range(5)]
        seq_b = [self.si.generate_code(rng=rng_b) for _ in range(5)]
        self.assertEqual(seq_a, seq_b)
        for code in seq_a:
            self.assertEqual(len(set(code)), 3, code)

    def test_s25_remove_then_readd_yields_new_code(self):
        """S-25: add -> remove -> re-add same generic gives a NEW code."""
        added = self.si.add_entry("coles", "Obela Hommus 200g",
                                  "Hommus 200g")
        old_code = added["entry"]["code"]
        self.si.remove_by_codes([old_code])
        re_added = self.si.add_entry("coles", "Obela Hommus 200g",
                                     "Hommus 200g")
        self.assertTrue(re_added["added"])
        self.assertNotEqual(re_added["entry"]["code"], old_code)

    def test_s26_corrupt_tombstone_file_reads_empty(self):
        """S-26: corrupt tombstone file -> [] (generation proceeds)."""
        self.si.TOMBSTONES_PATH.write_text("not json[", encoding="utf-8")
        self.assertEqual(self.si._load_tombstones(), [])
        code = self.si.generate_code()
        self.assertEqual(len(code), 3)


class TestRemoveAndClear(SearchedItemsTestCase):
    """S-12..S-18, S-21, S-29: removal, all-or-nothing, clear, consume."""

    def test_s12_remove_by_code(self):
        """S-12: remove_by_codes(['KAT']) removes exactly it."""
        self.add_two()
        result = self.si.remove_by_codes(["KAT"])
        self.assertEqual(result["removed"][0]["code"], "KAT")
        self.assertEqual(result["remaining_count"], 1)
        remaining = self.read_queue()
        self.assertEqual([e["code"] for e in remaining], ["RUM"])

    def test_s13_comma_separated_multi_remove(self):
        """S-13: 'KAT,RUM' removes both."""
        self.add_two()
        codes = self.si.parse_codes_arg("KAT,RUM")
        result = self.si.remove_by_codes(codes)
        self.assertEqual(result["remaining_count"], 0)

    def test_s14_case_insensitive_removal(self):
        """S-14: 'kat' (lowercase) removes KAT."""
        self.add_two()
        result = self.si.remove_by_codes(["kat"])
        self.assertEqual(result["removed"][0]["code"], "KAT")

    def test_s15_unknown_code_exact_error(self):
        """S-15: unknown code -> EXACT self-correcting message."""
        self.add_two()
        with self.assertRaises(ValueError) as ctx:
            self.si.remove_by_codes(["KA"])
        self.assertEqual(
            str(ctx.exception),
            "⚠️ Code 'KA' not found. Current queue codes: KAT, RUM.")

    def test_s16_all_or_nothing(self):
        """S-16: one unknown among valid -> NOTHING removed."""
        self.add_two()
        with self.assertRaises(ValueError):
            self.si.remove_by_codes(["KAT", "ZZZ"])
        self.assertEqual(len(self.read_queue()), 2)
        self.assertEqual(self.si._load_tombstones(), [])

    def test_s17_removal_writes_tombstones(self):
        """S-17: removed codes get tombstones with removed_at."""
        self.add_two()
        self.si.remove_by_codes(["KAT"])
        tombs = self.read_tombstones()
        self.assertEqual([t["code"] for t in tombs], ["KAT"])
        self.assertIn("removed_at", tombs[0])
        datetime.fromisoformat(tombs[0]["removed_at"])  # parseable

    def test_s18_clear_all_empties_and_tombstones(self):
        """S-18: clear_all empties + tombstones every code."""
        self.add_two()
        result = self.si.clear_all()
        self.assertEqual(result["remaining_count"], 0)
        self.assertEqual(self.read_queue(), [])
        tomb_codes = {t["code"] for t in self.read_tombstones()}
        self.assertEqual(tomb_codes, {"KAT", "RUM"})

    def test_s21_consume_entries_removes_and_tombstones(self):
        """S-21: consume_entries(store, entries) = flush-success path."""
        kat, rum = self.add_two()
        self.si.consume_entries("coles", [kat])
        remaining = self.read_queue()
        self.assertEqual([e["code"] for e in remaining], ["RUM"])
        tomb_codes = {t["code"] for t in self.si._load_tombstones()}
        self.assertIn("KAT", tomb_codes)
        self.assertNotIn("RUM", tomb_codes)

    def test_s29_parse_codes_arg(self):
        """S-29: 'KAT,RUM' / whitespace / invalid -> list or error."""
        self.assertEqual(self.si.parse_codes_arg("KAT,RUM"),
                         ["KAT", "RUM"])
        self.assertEqual(self.si.parse_codes_arg(" kat  rum "),
                         ["KAT", "RUM"])
        with self.assertRaises(ValueError):
            self.si.parse_codes_arg("K1T")
        with self.assertRaises(ValueError):
            self.si.parse_codes_arg("  ")


class TestRenderAndOrder(SearchedItemsTestCase):
    """S-19, S-20, S-23: render + ordering + since_label."""

    def test_s19_render_show_format(self):
        """S-19: 'store · name · unit tag [CODE]' lines; empty friendly."""
        self.assertEqual(self.si.render_show(), "searched_items is empty ✅")
        self.add_two()
        rendered = self.si.render_show()
        # B5: the RUM entry was added with no size -> it now carries the
        # canonical marker and renders the ⚠️ note (Rule A, no omission).
        self.assertIn("coles · Obela Classic Hommus 200g · 200g [KAT]",
                      rendered)
        self.assertIn(
            "woolworths · Woolworths Rum & Raisin 1L · ⚠️ unit "
            "unavailable [RUM]", rendered)

    def test_s20_ordered_entries_coles_first(self):
        """S-20: ordered_entries = Coles section first, then Woolworths."""
        self.si.add_entry("woolworths", "WW Item", "ww")
        self.si.add_entry("coles", "Coles Item", "coles")
        self.si.add_entry("woolworths", "WW Item 2", "ww2")
        stores = [e["store"] for e in self.si.ordered_entries()]
        self.assertEqual(stores, ["coles", "woolworths", "woolworths"])

    def test_s23_since_label(self):
        """S-23: since_label -> 'DD Mon'; raw string on parse failure."""
        label = self.si.since_label(
            {"added_at": "2026-08-29T02:00:00+00:00"})
        self.assertEqual(label, "29 Aug")
        self.assertEqual(self.si.since_label({"added_at": "gibberish"}),
                         "gibberish")


class TestAtomicWrites(SearchedItemsTestCase):
    """S-22: atomic write temp cleanup on replace failure."""

    def test_s22_temp_file_cleaned_when_replace_fails(self):
        """S-22: patch os.replace to raise -> temp cleaned, raises."""
        self.seed([])
        real_replace = self.si.os.replace
        leftovers = []

        original_mkstemp = self.si.tempfile.mkstemp

        def spy_mkstemp(*args, **kwargs):
            fd, path = original_mkstemp(*args, **kwargs)
            leftovers.append(path)
            return fd, path

        def boom(src, dst):
            raise OSError("replace failed")

        with patch.object(self.si.os, "replace", boom), \
                patch.object(self.si.tempfile, "mkstemp", spy_mkstemp):
            with self.assertRaises(OSError):
                self.si.save_pending([{"store": "coles"}])
        for path in leftovers:
            self.assertFalse(Path(path).exists())
        self.assertEqual(self.read_queue(), [])
        _ = real_replace  # silence unused warning


class TestSearchedItemsSizeContract(SearchedItemsTestCase):
    """B5/A8: size always stored; show always renders the tag."""

    def test_add_entry_blank_size_stores_marker(self):
        result = self.si.add_entry("coles", "Beans 400g", "Beans 400g")
        self.assertEqual(result["entry"]["size"], "unit unavailable")

    def test_add_entry_real_size_stored_trimmed(self):
        result = self.si.add_entry(
            "coles", "Beans 400g", "Beans 400g", size="  400g ")
        self.assertEqual(result["entry"]["size"], "400g")

    def test_show_renders_unit_and_marker(self):
        self.seed([
            {"store": "coles", "keyword": "Beans 400g", "code": "AAA",
             "generic_name": "Beans 400g", "store_product_id": "",
             "size": "400g", "added_at": "2026-08-29T02:00:00+00:00"},
            # legacy entry: no "size" key at all
            {"store": "woolworths", "keyword": "Milk", "code": "BBB",
             "generic_name": "Milk", "store_product_id": "",
             "added_at": "2026-08-29T02:00:00+00:00"},
        ])
        out = self.si.render_show()
        self.assertIn(" · 400g [AAA]", out)
        self.assertIn(" · ⚠️ unit unavailable [BBB]", out)


if __name__ == "__main__":
    unittest.main()
