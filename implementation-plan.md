# Implementation Plan — v2 Round 1: Local_Deals comment lifecycle + full sheet backup

- **Date:** 2026-09-09 · **Stage:** 02 Plan → 03 Code
- **Inputs:** `architecture-spec.md` (v2, §2 Q19 + §16 boundaries),
  `rebuild-plan.md` (Round 1), `core/local_deals.py` @ HEAD
  (`feature/qrs-shop-multibuy`), `tests/test_local_deals.py`,
  `grocery_price_cli.py` (parent root).
- **Scope guard:** Round 1 ONLY. No schema changes, no deletions, no new
  commands beyond `--comment-repair`, no VPS behavior change. The system
  stays fully functional throughout (user rule Q19).
- **Rule:** this file is overwritten in place every planning round —
  never renamed, never forked.

## 0. Audit matrix (the charter deliverable — every price-removal path)

| # | Path | Where | Status entering Round 1 | Round-1 action |
|---|------|-------|------------------------|----------------|
| A1 | Expire sweep clears a dated special | `sweep_expired_specials` (core/local_deals.py:2661) | FIXED by FIX-4 — comment dies with the cell; test `test_expired_cell_cleared_comment_dies_with_it` exists | none (already green) |
| A2 | New-post merge, item matched, now plain | `merge_store_tab` matched branch (2598–2622) + `build_rows` (1423–1429) | FIXED by FIX-4 — newest deal owns the segment; empty note clears | add merge-level regression test T5.4 |
| A3 | New-post merge, item DROPPED by the post | `merge_store_tab` — loop only visits the new post's rows | BY DESIGN (spec §4.4 / Q7): board rotation never deletes; an unexpired/undated cell + its comment survive TOGETHER until the sweep clears the pair | pin the invariant with test T5.5 so no future change separates them |
| A4 | Manual plain reprice (`--set-special`/`--set-permanent` without `--note`) | `set_store_prices` matched branch (2869–2877) | **GAP — the `if note:` guard leaves the stale promo segment** | **FIX (Task 1) + tests T5.1–T5.3** |
| A5 | Item (row) removal | none — v1 never deletes Local_Deals rows | no code path exists; v2 `remove` verb (Round 3) deletes the row wholesale, so the comment dies with the row | document only |
| A6 | Dunya site sync reprice/offer-end | `sync_dunya_site` → `merge_store_tab` (3041) | covered by A2 | document only |
| A7 | Pre-fix residue on the LIVE tab | Local_Deals rows 115 (Celery /ea) + 116 (Carrots 1kg Bag /ea): `[FRU] [multi buy 2 for $1.50 — $0.75/ea]` on empty cells | confirmed by the architect's live probe 2026-09-09 | repair function (Task 2) + CLI flag (Task 3) + live run (Task 6) |

Edge rules for the repair (binding): a shop's tagged segment is stripped
ONLY when BOTH that shop's permanent and special cells are blank
(whitespace-only). Non-numeric offer text in a cell counts as PRESENT
(never stripped). Untagged free text in the Comments column is preserved
verbatim. The repair never deletes rows and never touches other columns.

## Task 1 — Fix A4: manual plain reprice clears the shop's segment

**File:** `grocery-price-tracker/core/local_deals.py` (1 file, ~4 lines)
**Anchor (search block, `set_store_prices`, lines 2869–2877):**

```python
        else:
            old = grid[match][col]
            grid[match][col] = cell
            if note:
                grid[match][comments_col] = _merge_comment_cell(
                    grid[match][comments_col], store_key, note)
```

**Replace with:**

```python
        else:
            old = grid[match][col]
            grid[match][col] = cell
            # R1-A4: the newest entry owns the Comments cell — a plain
            # reprice (no note) CLEARS this shop's stale segment, same
            # rule as the ingest merge path (FIX-4).
            grid[match][comments_col] = _merge_comment_cell(
                grid[match][comments_col], store_key, note)
```

Error boundary: none new — `_merge_comment_cell` already handles
empty/None cells. The new-row branch (`if note:` at 2864) stays as-is
(a new row has no prior segment to clear).

**Verify (Local Terminal, tracker root):**
```bash
"$USERPROFILE/anaconda3/python.exe" -m py_compile core/local_deals.py
"$USERPROFILE/anaconda3/python.exe" -m pytest tests/test_local_deals.py -k "manual_reprice" -q
```

## Task 2 — `repair_orphan_comments` (A7 core)

**File:** `grocery-price-tracker/core/local_deals.py` (1 file, 1 insert)
**Insert exactly after `sweep_expired_specials` ends (after its final
`return lines`, line 2766) and BEFORE the `# --- manual pricing entry`
comment line (2769):**

```python
def repair_orphan_comments(worksheet) -> list[str]:
    """Strip shop-tagged Comments segments whose shop has NO price
    left in the row (both the permanent AND special cells blank).

    Round-1 (A7): clears the pre-FIX-4 sweep residue (e.g. '[FRU]
    multi buy 2 for $1.50' on empty cells — Local_Deals rows 115/116).
    Conservative by design: a NON-NUMERIC offer-text cell counts as a
    present price (never stripped); untagged free text is preserved
    verbatim; rows and other columns are never touched. Idempotent —
    a second run reports nothing.

    Args:
        worksheet: gspread/Fake worksheet handle for Local_Deals.

    Returns:
        list[str]: report lines, e.g. "Fruitopia Mt Druitt: Celery
        /ea — orphan comment '[FRU] multi buy …' removed".
    """
    try:
        grid = worksheet.get_all_values() or []
    except Exception:  # noqa: BLE001 — missing tab -> nothing to do
        return []
    if len(grid) < 3:
        return []
    width = len(TAB_COLUMNS) + 1
    grid = [(list(r) + [""] * width)[:width] for r in grid]
    names = {k: name for k, name in STORE_COLUMNS}
    comments_col = _grid_col("comments")
    lines: list[str] = []
    changed = False
    for row in grid[2:]:
        name = str(row[0]).strip()
        if not name or name in SECTION_ORDER:
            continue
        cell = str(row[comments_col] or "")
        if not _TAG_RE.search(cell):
            continue
        kept: list[str] = []
        for seg in cell.split(";"):
            seg = seg.strip()
            if not seg:
                continue
            m = _TAG_RE.match(seg)
            if m is None:
                kept.append(seg)            # free text survives
                continue
            shop = _shop_key_for_tag(m.group(1))
            priced = any(
                col is not None and len(row) > col
                and str(row[col]).strip()
                for col in (_perm_column_for(shop),
                            _special_column_for(shop)))
            if priced:
                kept.append(seg)
            else:
                lines.append(f"{names.get(shop, shop)}: {name} — "
                             f"orphan comment '{seg}' removed")
                changed = True
        rebuilt = "; ".join(kept)
        if rebuilt != cell:
            row[comments_col] = rebuilt
    if changed:
        worksheet.clear()
        worksheet.update(values=grid,
                         range_name=f"A1:J{len(grid)}")
    return lines
```

Error boundary: missing/empty tab → `[]` (mirrors the sweep). No new
imports (`re`, `TAB_COLUMNS`, `STORE_COLUMNS`, `_TAG_RE`,
`_shop_key_for_tag`, `_grid_col`, `_perm_column_for`,
`_special_column_for`, `SECTION_ORDER` are all module-level already).

**Verify:**
```bash
"$USERPROFILE/anaconda3/python.exe" -m py_compile core/local_deals.py
"$USERPROFILE/anaconda3/python.exe" -m pytest tests/test_local_deals.py -k "repair" -q
```

## Task 3 — CLI flag `--comment-repair`

**File:** `grocery_price_cli.py` (parent root; 2 small inserts)

**(a) Parser — insert immediately after the `--expire-sweep` block
(anchor: lines 463–467, before `ld.set_defaults(func=_cmd_local_deals)`):**

```python
    ld.add_argument("--comment-repair", action="store_true",
                    help="Strip shop-tagged Comments segments whose "
                         "shop has no price left in the row (both "
                         "permanent + special cells empty) — clears "
                         "the pre-fix sweep residue")
```

**(b) Handler — insert immediately after the `expire_sweep` handler
block (anchor: after its `return 0` at line 4129, before the
`provision_topic` block):**

```python
    if getattr(args, "comment_repair", False):
        from core.sheets_client import connect_spreadsheet
        from core.local_deals import (ensure_local_deals_tab,
                                      repair_orphan_comments)
        worksheet = ensure_local_deals_tab(connect_spreadsheet())
        removed = repair_orphan_comments(worksheet)
        print(f"[local-deals] comment repair: {len(removed)} "
              f"orphan segment(s) removed")
        for line in removed:
            print(f"  • {line}")
        return 0
```

Placement note: this sits in the flag-check chain that runs BEFORE any
default scan action, so `local-deals --comment-repair` (flag alone)
does exactly one thing and returns. Mirror the expire-sweep handler's
import style exactly.

**Verify:**
```bash
"$USERPROFILE/anaconda3/python.exe" -m py_compile grocery_price_cli.py
"$USERPROFILE/anaconda3/python.exe" grocery_price_cli.py local-deals --help
# expect the new flag listed; running it bare waits for Task 6 (live sheet)
```

## Task 4 — Full sheet backup utility (work-order deliverable)

**File:** `grocery-price-tracker/tools/sheet_backup.py` (NEW — the
designated home for the v2 one-shot utilities; Round 2's migration
tools land here too. Recorded as a §16 interpretation: the spec
authorizes "one-time migration/parity utilities" without naming a
folder — `tools/` is it.)

```python
"""One-shot FULL Google Sheet backup (v2 rebuild Round 1).

Copies the grocery spreadsheet (EVERY tab) to a new spreadsheet named
grocery-tracker-backup-YYYY-MM-DD, then re-opens the copy and verifies
each tab's row count + row width against the source. Exit 0 = every
tab verified; exit 1 = any mismatch or failure (copy kept for
inspection). Never prints secret values.

Run from the tracker root:
  anaconda3/python.exe tools/sheet_backup.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.sheets_client import connect_spreadsheet  # noqa: E402


def tab_counts(spreadsheet) -> list[tuple[str, int, int]]:
    """[(title, data-row count, max row width)] for every tab."""
    out: list[tuple[str, int, int]] = []
    for ws in spreadsheet.worksheets():
        grid = ws.get_all_values() or []
        width = max((len(r) for r in grid), default=0)
        out.append((ws.title, len(grid), width))
    return out


def compare_counts(src: list[tuple[str, int, int]],
                   dst: list[tuple[str, int, int]]) -> list[str]:
    """Mismatch lines ('Products_Master: 113x19 -> 110x19'); empty =
    identical (order-insensitive by title). Missing tabs mismatch."""
    dst_map = {t: (r, w) for t, r, w in dst}
    lines: list[str] = []
    for title, rows, width in src:
        got = dst_map.get(title)
        if got is None:
            lines.append(f"{title}: MISSING from backup")
        elif got != (rows, width):
            lines.append(f"{title}: {rows}x{width} -> "
                         f"{got[0]}x{got[1]}")
    return lines


def main() -> int:
    from datetime import date
    try:
        src = connect_spreadsheet()
        title = f"grocery-tracker-backup-{date.today():%Y-%m-%d}"
        before = tab_counts(src)
        resp = src.copy(title=title)
        new_id = (resp["spreadsheetId"] if isinstance(resp, dict)
                  else resp.id)
        print(f"[backup] copy created: {title}")
        print(f"[backup] "
              f"https://docs.google.com/spreadsheets/d/{new_id}/edit")
        dst = src.client.open_by_key(new_id)
        problems = compare_counts(before, tab_counts(dst))
        for t, rows, width in before:
            mark = "FAIL" if any(t in p for p in problems) else "ok"
            print(f"[backup] {mark}: {t} {rows} rows x {width} cols")
        if problems:
            print("[backup] VERIFICATION FAILED:")
            for p in problems:
                print(f"  • {p}")
            return 1
        print("[backup] BACKUP VERIFIED — all tabs match")
        return 0
    except Exception as exc:  # noqa: BLE001 — secret-free report
        print(f"[backup] FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

(Coder note: if `src.client.open_by_key` is unavailable on the
installed gspread version, use a fresh `gspread.authorize` on the
same credentials — but NO new pip installs. The backup copy retains
the source's tab set by default; no permission changes are needed.)

**Verify:**
```bash
"$USERPROFILE/anaconda3/python.exe" -m py_compile tools/sheet_backup.py
"$USERPROFILE/anaconda3/python.exe" -m pytest tests/test_sheet_backup.py -q
```

## Task 5 — Regression tests (mandatory, zero-skip, offline-only)

**File A:** `grocery-price-tracker/tests/test_local_deals.py` — append
ONE class at end of file. Reuse the existing `FakeWorksheet`,
`_v2_ws`, `_deal` helpers and the column indexes used by
`TestSweepExpiredSpecials` (FRUITS section row, fruitopia special =
index 6, comments = index 9). Mirror neighboring tests' deal-dict
shape for fruitopia merges (see `TestTabDedupWordOrder`).

```python
class TestCommentLifecycleRound1(unittest.TestCase):
    """Round-1 audit pins: no path orphans a shop-tagged comment."""

    def test_manual_reprice_without_note_clears_segment(self):
        # A4: plain --set-special over a multibuy cell -> the [FRU]
        # promo segment must die with the old price.
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Carrots /ea", "", "", "", "", "",
             "0.75 (till 12 Sep)", "", "",
             "[FRU] multi buy 2 for $1.50 — $0.75/ea"],
        ])
        ld.set_store_prices(ws, "fruitopia", "special",
                            [{"item": "Carrots", "price": 0.60,
                              "unit": "ea"}])
        grid = ws.get_all_values()
        self.assertEqual(str(grid[3][6]), "0.6")
        self.assertEqual(grid[3][9], "")

    def test_manual_reprice_with_note_replaces_segment(self):
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Carrots /ea", "", "", "", "", "",
             "0.75 (till 12 Sep)", "", "",
             "[FRU] multi buy 2 for $1.50 — $0.75/ea"],
        ])
        ld.set_store_prices(ws, "fruitopia", "special",
                            [{"item": "Carrots", "price": 0.60,
                              "unit": "ea", "note": "3 for $1.80"}])
        self.assertEqual(
            ws.get_all_values()[3][9], "[FRU] 3 for $1.80")

    def test_manual_new_row_note_still_tags_shop(self):
        ws = _v2_ws([["FRUITS", "", "", "", "", "", "", "", "", ""]])
        ld.set_store_prices(ws, "fruitopia", "special",
                            [{"item": "Celery", "price": 1.20,
                              "unit": "ea", "note": "fresh cut"}])
        self.assertEqual(
            ws.get_all_values()[3][9], "[FRU] fresh cut")

    def test_merge_plain_reprice_clears_segment(self):
        # A2 merge-level pin (FIX-4 was parser-level tested).
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Carrots /ea", "", "", "", "", "",
             "0.75 (till 12 Sep)", "", "",
             "[FRU] multi buy 2 for $1.50 — $0.75/ea"],
        ])
        ld.merge_store_tab(ws, "fruitopia", [
            {"item": "Carrots", "category": "fruit",
             "price_kind": "single", "price": 0.6, "unit": "ea"}])
        grid = ws.get_all_values()
        row = next(r for r in grid if str(r[0]).startswith("Carrots"))
        self.assertEqual(str(row[6]), "0.6")
        self.assertEqual(row[9], "")

    def test_merge_dropped_item_keeps_cell_and_comment_together(self):
        # A3 design pin: a post that no longer lists the item leaves
        # cell AND comment TOGETHER (board rotation never deletes;
        # the sweep clears the pair later — test_expired_cell_…).
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Carrots /ea", "", "", "", "", "",
             "0.75 (till 12 Sep)", "", "",
             "[FRU] multi buy 2 for $1.50 — $0.75/ea"],
        ])
        ld.merge_store_tab(ws, "fruitopia", [
            {"item": "Apples", "category": "fruit",
             "price_kind": "single", "price": 2.5, "unit": "kg"}])
        row = next(r for r in ws.get_all_values()
                   if str(r[0]).startswith("Carrots"))
        self.assertEqual(row[6], "0.75 (till 12 Sep)")
        self.assertIn("[FRU]", row[9])

    def test_repair_strips_orphan_segments(self):
        # A7: the live residue shape (rows 115/116) — empty FRU cells.
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Celery /ea", "", "", "", "", "", "", "", "",
             "[FRU] multi buy 2 for $1.50 — $0.75/ea"],
            ["Carrots 1kg Bag /ea", "", "", "", "", "", "", "", "",
             "[FRU] multi buy 2 for $1.50 — $0.75/ea"],
        ])
        lines = ld.repair_orphan_comments(ws)
        self.assertEqual(len(lines), 2)
        grid = ws.get_all_values()
        self.assertEqual(grid[3][9], "")
        self.assertEqual(grid[4][9], "")
        self.assertEqual(grid[3][0], "Celery /ea")   # row KEPT
        self.assertEqual(ld.repair_orphan_comments(ws), [])  # idem.

    def test_repair_keeps_segment_when_shop_priced(self):
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Carrots /ea", "", "", "", "", 6.50, "", "", "",
             "[FRU] multi buy 2 for $1.50 — $0.75/ea"],
        ])
        self.assertEqual(ld.repair_orphan_comments(ws), [])
        self.assertIn("[FRU]", ws.get_all_values()[3][9])

    def test_repair_preserves_untagged_text_and_other_shops(self):
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", 6.50, "", "", "",
             "[FRU] note; loose text; [MER] orphan note"],
        ])
        lines = ld.repair_orphan_comments(ws)
        self.assertEqual(len(lines), 1)          # only MER stripped
        self.assertEqual(ws.get_all_values()[3][9],
                         "[FRU] note; loose text")

    def test_repair_no_tags_writes_nothing(self):
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Carrots /ea", "", "", "", "", 6.50, "", "", "",
             "loose text only"],
        ])
        self.assertEqual(ld.repair_orphan_comments(ws), [])
        self.assertEqual(ws.clear_calls, 0)
```

**File B:** `grocery-price-tracker/tests/test_sheet_backup.py` (NEW):

```python
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
```

**Verify (all of Task 5, zero skips):**
```bash
"$USERPROFILE/anaconda3/python.exe" -m pytest tests/test_local_deals.py -k TestCommentLifecycleRound1 -q
"$USERPROFILE/anaconda3/python.exe" -m pytest tests/test_sheet_backup.py -q
"$USERPROFILE/anaconda3/python.exe" -m pytest tests/ -q
```
Expected: 9 new local_deals tests + 3 backup tests green; full suite
green (baseline 1250 → 1262). NO test may be skipped or marked xfail.

## Task 6 — Live execution (scripted; Local Terminal only)

Order matters: backup FIRST, then the repair.

```bash
# 1. Full sheet backup (expect: BACKUP VERIFIED — all tabs match:
#    Products_Master, User_Shopping_Lists, Price_History, Local_Deals)
cd "C:/Users/User.DESKTOP-R2G441H/Documents/AI related/grocery-price-tracker"
"$USERPROFILE/anaconda3/python.exe" tools/sheet_backup.py

# 2. Orphan repair on the LIVE tab (expect: the 2 known segments —
#    Celery row 115 + Carrots row 116 — plus any others the scan
#    finds, each printed with a '•' line; second run reports 0)
cd ..
"$USERPROFILE/anaconda3/python.exe" grocery_price_cli.py local-deals --comment-repair
"$USERPROFILE/anaconda3/python.exe" grocery_price_cli.py local-deals --comment-repair

# 3. Post-state probe: read the live Comments column and assert no
#    tagged segment remains on any row whose shop cells are both
#    empty (scratch tmp_* probe script; delete it after the check)
```

Failure boundary: if the backup exits 1, STOP — do not run the repair;
report the mismatch lines verbatim. If the repair output exceeds the
two known orphans, list every line in the report (each is a correct
strip by the rule, but the report must show them all).

## Task 7 — Suite, commit, three-way sync

**Local Terminal (both repos — the CLI file is parent-repo, the rest
are tracker-repo; commit ONLY the files this round touched):**
```bash
cd "C:/Users/User.DESKTOP-R2G441H/Documents/AI related/grocery-price-tracker"
"$USERPROFILE/anaconda3/python.exe" -m pytest tests/ -q        # expect 1262 passed, 0 failed

git add core/local_deals.py tests/test_local_deals.py tests/test_sheet_backup.py tools/sheet_backup.py implementation-plan.md
git commit -m "R1 plan + comment lifecycle: manual plain reprice clears the shop segment (audit A4 fix), repair_orphan_comments + --comment-repair (A7 residue: Local_Deals rows 115/116), tools/sheet_backup.py full-backup utility; audit A1-A6 pinned/documented"
git push origin feature/qrs-shop-multibuy

cd ..
git add grocery_price_cli.py
git commit -m "R1: local-deals --comment-repair flag (orphan comment residue cleanup)"
git push origin feature/qrs-shop-multibuy
```

**Remote VPS (runtime mirror — the backup/repair run LOCAL-only, but
the changed code files must mirror):**
```bash
scp grocery_price_cli.py myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery_price_cli.py
scp grocery-price-tracker/core/local_deals.py myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/core/local_deals.py
scp grocery-price-tracker/implementation-plan.md myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/implementation-plan.md
# checksum-verify both code files (md5sum local vs ssh myvps md5sum) — pairs must match
```

**Manual steps: NONE.** Everything above is agent-executable; the only
human-visible artifacts are the backup URL (report it) and the repair
report lines (quote them verbatim in the coder report).

## Acceptance criteria (from rebuild-plan.md Round 1)

1. Every audit row A1–A7 has either a pre-existing test, a new test,
   or a documented no-path conclusion in the coder report.
2. Rows 115/116 clean on the live tab; a follow-up `--comment-repair`
   run reports 0.
3. Backup spreadsheet exists, all 4 tabs verified (URL + counts in the
   report); backup exit code 0.
4. Full suite green, zero skips (expect 1262 passed).
5. Both repos pushed; VPS md5s match local; report ends with the
   three-way sync status (in sync / not, one line).

---

## ADDENDUM (orchestrator corrections, 2026-09-09 — binding, same authority as the plan)

1. **MISSING SCOPE RESTORED — A3 test-hygiene riders (spec §18/A3, rebuild-plan Round 1 item 4).** The plan omitted them. Add as Task 5b (tests/test_cli.py + tests/test_local_deals.py):
   - (a) `TestCLI::test_specials_leads_with_fresh_report` — the fixture crafts a Wednesday report "generated 2026-09-02", which aged out of the ≤7-day window on Sep 9. Fix: generate the fixture date ROLLING (e.g. `_dt.now() - 1 day`) so the test cannot rot again.
   - (b) `TestScanWindowsAndCutoff::test_between_alerts_window_enforced` — the final scenario's post is created 0.05s before its scan; when two consecutive `run_daily_scan` calls execute <50ms apart the assertion misses (1-in-4 flake). Fix: widen the offset to 5s.
   - Acceptance: both tests pass on 10 consecutive suite runs; no other test changes.
2. **CORRECTED TEST-COUNT EXPECTATIONS (Task 7 / acceptance criterion 4).** The plan's "baseline 1250 → 1262" is stale (round-2 era). Current reality: **1307 collected (1306 passed + 1 failed = the date-rot nit)**. After this round WITH the restored A3 riders: expect **1319 collected, 1319 passed, 0 failed, 0 skipped** (1307 + 9 comment-lifecycle + 3 backup + 2 rider-fixes do not add tests, they fix existing ones... net = 1319 total, all green).
3. **FakeWorksheet note (Task 5):** `test_repair_no_tags_writes_nothing` asserts `ws.clear_calls == 0` — if the shared `FakeWorksheet` does not track `clear()` calls, add a counter to it (one attribute + one increment); do NOT weaken the assertion.
4. Everything else in the plan stands as written. The coder follows plan + this addendum; any further deviation = STOP and report.
