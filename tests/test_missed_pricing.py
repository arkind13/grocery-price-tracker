#!/usr/bin/env python3
"""Missed-pricing (list #7) + GONE word + two-strike auto-delete tests.

Sandboxed (2026-09-03 rule): tmp dirs + FakeWorksheet only — the real
data/ folder and the real sheet are never touched.
"""
from __future__ import annotations
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))
_ROOT = _PROJECT.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import grocery_price_cli as gcli  # noqa: E402


def _row(generic, ww_price, coles_price, ww_kw, coles_kw,
         size="500g", last_updated="2026-09-02 10:00"):
    """10-col Products_Master row (A..J)."""
    return [generic, "", size, ww_price, coles_price, "", "",
            last_updated, ww_kw, coles_kw]


class FakeDeleteWorksheet:
    """FakeWorksheet with update() + delete_rows tracking."""

    def __init__(self, rows):
        self._values = [list(r) for r in rows]
        self.deleted = []

    def get_all_values(self):
        return [list(r) for r in self._values]

    def update(self, *, values, range_name):
        # A2:C4 -> rows 2..4, cols 1..3
        import re as _re
        m = _re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", range_name)
        sc = ord(m.group(1)) - ord("A")
        sr = int(m.group(2))
        for offset, row_vals in enumerate(values):
            r = sr + offset - 1
            while len(self._values) <= r:
                self._values.append([])
            for c, val in enumerate(row_vals):
                col = sc + c
                while len(self._values[r]) <= col:
                    self._values[r].append("")
                self._values[r][col] = val

    def delete_rows(self, row_index, number=1):
        self.deleted.append(row_index)
        for _ in range(number):
            del self._values[row_index - 1]


_SHEET = [
    _row("Name", "WW", "Coles", "I", "J"),                     # header
    _row("Healthy", "3.50", "3.60", "milk 2l", "milk coles"),  # fine
    _row("Mismatch WW", "N/A 2026-09-02", "3.60",
         "broken kw", "good coles kw"),                        # fixable WW
    _row("Mismatch Coles", "3.50", "N/A 2026-09-02",
         "good ww kw", "broken coles kw"),                     # fixable Coles
    _row("NoKw Coles", "3.50", "", "good ww kw", ""),          # A: excluded
    _row("Gone Coles", "3.50", "GONE", "good ww kw", "old coles kw"),  # GONE
    _row("NA keyword", "N/A 2026-09-02", "3.60", "NA", "good"),  # captured
    _row("Blank price", "", "3.60", "real kw", "good"),        # captured
    _row("Both Dead", "N/A 2026-09-02", "unavailable 2026-09-02",
         "kw1", "kw2"),                                        # delete-pending
    _row("Both Dead GONE", "GONE", "N/A 2026-09-02",
         "kw1", "kw2"),                                        # delete-pending
]


# ============================================================================
# Classification
# ============================================================================

class TestClassifyMissedPricing(unittest.TestCase):

    def setUp(self):
        self.fix, self.dead = gcli._classify_missed_pricing(_SHEET[1:])

    def test_fixable_captures_mismatches_na_and_blank(self):
        """B (NA kw), C (mismatch), blank-price rows captured with
        keyword; no-keyword rows (A) excluded; GONE excluded."""
        names = {e["generic"]: e for e in self.fix}
        self.assertIn("Mismatch WW", names)
        self.assertIn("Mismatch Coles", names)
        self.assertIn("NA keyword", names)
        self.assertIn("Blank price", names)
        self.assertNotIn("NoKw Coles", names)     # A — keyword empty
        self.assertNotIn("Gone Coles", names)     # GONE cell
        self.assertNotIn("Both Dead", names)      # dead, not fixable
        self.assertEqual(names["Mismatch WW"]["store"], "woolworths")
        self.assertEqual(names["Mismatch WW"]["keyword"], "broken kw")

    def test_delete_pending_captures_both_dead_incl_gone(self):
        names = {e["generic"]: e for e in self.dead}
        self.assertIn("Both Dead", names)
        self.assertIn("Both Dead GONE", names)   # GONE counts as dead
        self.assertNotIn("Mismatch WW", names)
        self.assertNotIn("Gone Coles", names)    # one live price remains
        # 1-based sheet row index (header row 1)
        by_name = {e["generic"]: e for e in self.dead}
        self.assertEqual(by_name["Both Dead"]["row_index"], 9)


# ============================================================================
# Two-strike rule
# ============================================================================

class TestTwoStrike(unittest.TestCase):

    def _dead(self, names):
        return [{"generic": n, "row_index": 2, "row": []} for n in names]

    def test_first_sighting_waits(self):
        to_delete, ledger = gcli._apply_two_strike(
            self._dead(["A"]), {}, "2026-09-03")
        self.assertEqual(to_delete, [])
        self.assertEqual(ledger, {"A": "2026-09-03"})

    def test_second_strike_deletes(self):
        to_delete, ledger = gcli._apply_two_strike(
            self._dead(["A"]), {"A": "2026-08-27"}, "2026-09-03")
        self.assertEqual([e["generic"] for e in to_delete], ["A"])
        self.assertEqual(ledger, {})

    def test_same_day_rerun_is_not_second_strike(self):
        """Re-running Wednesday the same day must not delete."""
        to_delete, ledger = gcli._apply_two_strike(
            self._dead(["A"]), {"A": "2026-09-03"}, "2026-09-03")
        self.assertEqual(to_delete, [])
        self.assertEqual(ledger, {"A": "2026-09-03"})

    def test_recovered_row_leaves_ledger(self):
        to_delete, ledger = gcli._apply_two_strike(
            self._dead(["B"]), {"A": "2026-08-27", "B": "2026-08-27"},
            "2026-09-03")
        self.assertEqual([e["generic"] for e in to_delete], ["B"])
        self.assertEqual(ledger, {})


# ============================================================================
# missed-pricing command
# ============================================================================

class TestMissedPricingCommand(unittest.TestCase):

    def _run(self, tmp, ws, purge=False, dry_run=False):
        args = MagicMock(purge=purge, dry_run=dry_run)
        with patch.object(gcli, "_TRACKER", tmp), \
                patch.object(gcli, "_load_env"), \
                patch("core.sheets_client.connect_worksheet",
                      MagicMock(return_value=ws)):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = gcli._cmd_missed_pricing(args)
        return buf.getvalue(), code

    def test_report_groups(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "data").mkdir()
            out, code = self._run(tmp, FakeDeleteWorksheet(_SHEET))
            self.assertEqual(code, 0)
            self.assertIn("4 fixable · 2 delete-pending", out)
            self.assertIn("Mismatch WW", out)
            self.assertIn("Both Dead", out)
            self.assertIn("GONE", out)  # the GONE hint text

    def test_purge_deletes_dead_and_archives(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "data").mkdir()
            # ledger with a pending strike for one dead row
            (tmp / "data" / "delete_candidates.json").write_text(
                json.dumps({"Both Dead": "2026-08-27"}), encoding="utf-8")
            ws = FakeDeleteWorksheet(_SHEET)
            out, code = self._run(tmp, ws, purge=True)
            self.assertEqual(code, 0)
            # bottom-up: sheet rows 9 and 10 (1-based)
            self.assertEqual(sorted(ws.deleted), [9, 10])
            self.assertIn("Purged 2 row(s)", out)
            archive = json.loads(
                (tmp / "data" / "deleted_rows.json").read_text(
                    encoding="utf-8"))
            self.assertEqual(len(archive), 2)
            self.assertEqual(archive[0]["source"], "manual-purge")
            # ledger strike cleared
            ledger = json.loads(
                (tmp / "data" / "delete_candidates.json").read_text(
                    encoding="utf-8"))
            self.assertNotIn("Both Dead", ledger)

    def test_dry_run_reports_without_deleting(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "data").mkdir()
            ws = FakeDeleteWorksheet(_SHEET)
            out, code = self._run(tmp, ws, dry_run=True)
            self.assertEqual(code, 0)
            self.assertEqual(ws.deleted, [])
            self.assertIn("[DRY RUN] Purge would delete 2 row(s)", out)


# ============================================================================
# Wednesday auto-delete step
# ============================================================================

class TestAutoDeleteStep(unittest.TestCase):

    def _run(self, tmp, ws, dry_run=False):
        with patch.object(gcli, "_TRACKER", tmp), \
                patch("core.sheets_client.connect_worksheet",
                      MagicMock(return_value=ws)):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                removed = gcli._auto_delete_dead_rows(dry_run=dry_run)
        return buf.getvalue(), removed

    def test_first_wednesday_only_records(self):
        """Strike 1: nothing deleted, ledger records the row."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "data").mkdir()
            ws = FakeDeleteWorksheet(_SHEET)
            out, removed = self._run(tmp, ws)
            self.assertEqual(removed, [])
            self.assertEqual(ws.deleted, [])
            self.assertIn("2 new candidate(s)", out)
            ledger = json.loads(
                (tmp / "data" / "delete_candidates.json").read_text(
                    encoding="utf-8"))
            self.assertIn("Both Dead", ledger)

    def test_second_wednesday_deletes_and_archives(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "data").mkdir()
            (tmp / "data" / "delete_candidates.json").write_text(
                json.dumps({"Both Dead": "2026-08-27",
                            "Both Dead GONE": "2026-08-27"}),
                encoding="utf-8")
            ws = FakeDeleteWorksheet(_SHEET)
            out, removed = self._run(tmp, ws)
            self.assertEqual(len(removed), 2)
            self.assertEqual(sorted(ws.deleted), [9, 10])
            archive = json.loads(
                (tmp / "data" / "deleted_rows.json").read_text(
                    encoding="utf-8"))
            self.assertEqual(len(archive), 2)
            self.assertEqual(archive[0]["source"], "wednesday-two-strike")

    def test_no_dead_rows_clears_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "data").mkdir()
            (tmp / "data" / "delete_candidates.json").write_text(
                json.dumps({"Ghost": "2026-08-27"}), encoding="utf-8")
            healthy = [_row("Name", "WW", "Coles", "I", "J"),
                       _row("Fine", "3.50", "3.60", "a", "b")]
            out, removed = self._run(tmp, FakeDeleteWorksheet(healthy))
            self.assertEqual(removed, [])
            ledger = json.loads(
                (tmp / "data" / "delete_candidates.json").read_text(
                    encoding="utf-8"))
            self.assertEqual(ledger, {})

    def test_dry_run_never_writes(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "data").mkdir()
            (tmp / "data" / "delete_candidates.json").write_text(
                json.dumps({"Both Dead": "2026-08-27",
                            "Both Dead GONE": "2026-08-27"}),
                encoding="utf-8")
            ws = FakeDeleteWorksheet(_SHEET)
            out, removed = self._run(tmp, ws, dry_run=True)
            self.assertEqual(ws.deleted, [])
            ledger = json.loads(
                (tmp / "data" / "delete_candidates.json").read_text(
                    encoding="utf-8"))
            self.assertIn("Both Dead", ledger)  # untouched


# ============================================================================
# GONE guards in sync_prices
# ============================================================================

class TestGoneGuardsInSync(unittest.TestCase):

    def _sync(self, rows, matched_price, store="woolworths"):
        """Run sync_prices with one matched item at sheet row 2."""
        from core import sheets_sync as ssync

        item = SimpleNamespace(
            price=matched_price, store=store, raw_name="Milk 2L",
            size="2L", is_special=False, special_desc="", rewards_points="",
        )
        result = SimpleNamespace(
            matched=True, row_index=2, store=store,
            generic_name="Milk 2L",
        )
        ws = FakeDeleteWorksheet(rows)
        report = ssync.sync_prices(
            [result], [item], worksheet=ws, dry_run=False)
        return ws, report

    def test_marker_never_stomps_gone(self):
        """Listed item with unusable price must keep its GONE cell."""
        rows = [_row("Name", "WW", "Coles", "I", "J"),
                _row("Milk 2L", "GONE", "", "milk 2l", "")]
        ws, _ = self._sync(rows, matched_price=None)
        self.assertEqual(ws.get_all_values()[1][3], "GONE")

    def test_notfound_pass_never_stomps_gone(self):
        """Keyword present, item not in this run's list, cell GONE ->
        the not-found pass must leave it alone."""
        rows = [_row("Name", "WW", "Coles", "I", "J"),
                _row("Milk 2L", "GONE", "", "milk 2l", ""),
                _row("Other", "3.00", "", "other", "")]
        item = SimpleNamespace(
            price=3.0, store="woolworths", raw_name="Other", size="",
            is_special=False, special_desc="", rewards_points="",
        )
        result = SimpleNamespace(
            matched=True, row_index=3, store="woolworths",
            generic_name="Other",
        )
        from core import sheets_sync as ssync
        ws = FakeDeleteWorksheet(rows)
        ssync.sync_prices([result], [item], worksheet=ws, dry_run=False)
        # Row 2: woolworths keyword present, not seen this run — the
        # not-found pass targeted it; GONE must survive.
        self.assertEqual(ws.get_all_values()[1][3], "GONE")

    def test_real_price_resurrects_gone(self):
        """A returning real price overwrites GONE (item resurrected)."""
        rows = [_row("Name", "WW", "Coles", "I", "J"),
                _row("Milk 2L", "GONE", "", "milk 2l", "")]
        ws, _ = self._sync(rows, matched_price=3.5)
        self.assertEqual(ws.get_all_values()[1][3], 3.5)


# ============================================================================
# First-fail ages ledger (data/missed_pricing_ages.json, 2026-09-03)
# ============================================================================

def _days_ago(n):
    """YYYY-MM-DD stamp n days before today (deterministic seeds)."""
    import datetime as _dt
    return (_dt.date.today() - _dt.timedelta(days=n)).isoformat()


class TestMissedPricingAgesLedger(unittest.TestCase):
    """The ages ledger: seeded history -> correct label immediately;
    read-only callers never write; GONE rows drop out; the two-strike
    deletion ledger is untouched. Sandboxed: tmp data_dir only."""

    def _seed(self, data_dir, ages):
        (Path(data_dir) / gcli._MISSED_AGES_FILE).write_text(
            json.dumps(ages), encoding="utf-8")

    def _read(self, data_dir):
        return json.loads(
            (Path(data_dir) / gcli._MISSED_AGES_FILE).read_text(
                encoding="utf-8"))

    def test_seeded_history_shows_two_weeks_immediately(self):
        """Acceptance: a row failing since 14 days ago shows (2 weeks)
        on the FIRST run, even though its cell anchor (N/A 2026-09-02)
        would read (new) after the anchor reset."""
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            self._seed(data_dir, {"Mismatch WW": _days_ago(14)})
            fix, _dead = gcli._classify_missed_pricing(
                _SHEET[1:], persist_ages=True, data_dir=data_dir)
            entry = {e["generic"]: e for e in fix}["Mismatch WW"]
            self.assertEqual(entry["weeks"], "2 weeks")
            self.assertEqual(
                self._read(data_dir)["Mismatch WW"], _days_ago(14))

    def test_new_failure_records_today_and_shows_new(self):
        """Genuinely-new failures (<7d) still show (new) and record
        today as their first_seen."""
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            today = _days_ago(0)
            fresh = _row("Fresh Item", "", "3.60", "kw", "good",
                         last_updated=f"{today} 09:00")
            fix, _dead = gcli._classify_missed_pricing(
                [fresh], persist_ages=True, data_dir=data_dir)
            self.assertEqual(fix[0]["weeks"], "new")
            self.assertEqual(self._read(data_dir),
                             {"Fresh Item": today})

    def test_full_run_upserts_keeps_oldest_and_prunes(self):
        """Every failing row is upserted (OLDEST date wins on
        collision); entries no longer failing are dropped."""
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            today = _days_ago(0)
            old = _days_ago(21)
            self._seed(data_dir, {"Mismatch WW": old,
                                  "Recovered Item": _days_ago(60)})
            fix, dead = gcli._classify_missed_pricing(
                _SHEET[1:], persist_ages=True, data_dir=data_dir)
            ages = self._read(data_dir)
            failing = ({e["generic"] for e in fix}
                       | {e["generic"] for e in dead})
            self.assertEqual(set(ages), failing)
            self.assertEqual(ages["Mismatch WW"], old)  # oldest kept
            self.assertNotIn("Recovered Item", ages)    # pruned
            for name in failing - {"Mismatch WW"}:
                self.assertEqual(ages[name], today)

    def test_read_only_callers_never_write_ledger(self):
        """persist_ages=False (the `lists` path) never creates or
        modifies the ledger file — labels keep legacy anchor behaviour."""
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            gcli._classify_missed_pricing(_SHEET[1:], data_dir=data_dir)
            self.assertFalse(
                (data_dir / gcli._MISSED_AGES_FILE).exists())
            self._seed(data_dir, {"Mismatch WW": _days_ago(14)})
            path = data_dir / gcli._MISSED_AGES_FILE
            before = path.read_text(encoding="utf-8")
            gcli._classify_missed_pricing(
                _SHEET[1:], data_dir=data_dir)
            self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_gone_row_leaves_ledger(self):
        """A manual GONE verdict removes the row from the lists — its
        ledger entry is dropped (re-ages from scratch if undeleted)."""
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            self._seed(data_dir, {"Gone Coles": _days_ago(14),
                                  "Mismatch WW": _days_ago(14)})
            gcli._classify_missed_pricing(
                _SHEET[1:], persist_ages=True, data_dir=data_dir)
            ages = self._read(data_dir)
            self.assertNotIn("Gone Coles", ages)
            self.assertIn("Mismatch WW", ages)

    def test_two_strike_delete_ledger_untouched(self):
        """The ages ledger write must never touch the Wednesday
        two-strike ledger (delete_candidates.json)."""
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            self._seed(data_dir, {"Both Dead": _days_ago(14)})
            candidates = data_dir / "delete_candidates.json"
            candidates.write_text('{"Both Dead": "2026-08-27"}',
                                  encoding="utf-8")
            gcli._classify_missed_pricing(
                _SHEET[1:], persist_ages=True, data_dir=data_dir)
            self.assertEqual(
                candidates.read_text(encoding="utf-8"),
                '{"Both Dead": "2026-08-27"}')

    def test_cell_weeks_prefers_ledger_then_falls_back(self):
        """_cell_weeks: ledger date wins when present; without a
        ledger entry the anchor/Col-H fallback is unchanged."""
        today = _days_ago(0)
        ages = {"Ledgered": _days_ago(21)}
        self.assertEqual(
            gcli._cell_weeks("N/A 2026-09-02",
                             last_updated="2026-09-02 10:00",
                             generic="Ledgered", ages=ages),
            "3 weeks")
        self.assertEqual(
            gcli._cell_weeks("", last_updated=f"{today} 09:00",
                             generic="Other", ages=ages),
            "new")
        self.assertEqual(
            gcli._cell_weeks("", last_updated="",
                             generic="Other", ages=ages),
            "?")

    def test_missed_pricing_command_creates_ledger(self):
        """One missed-pricing run creates the ledger for every
        fixable + delete-pending row (write caller)."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "data").mkdir()
            args = MagicMock(purge=False, dry_run=False)
            with patch.object(gcli, "_TRACKER", tmp), \
                    patch.object(gcli, "_load_env"), \
                    patch("core.sheets_client.connect_worksheet",
                          MagicMock(
                              return_value=FakeDeleteWorksheet(_SHEET))):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    code = gcli._cmd_missed_pricing(args)
            self.assertEqual(code, 0)
            ages = self._read(tmp / "data")
            self.assertEqual(
                set(ages),
                {"Mismatch WW", "Mismatch Coles", "NA keyword",
                 "Blank price", "Both Dead", "Both Dead GONE"})


if __name__ == "__main__":
    unittest.main()
