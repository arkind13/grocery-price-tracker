# FIX ROUND REPORT 3 — 2026-09-09 — R3-1…R3-3 (final three)

Work order: `fix-spec-round3-2026-09-08.md` (3 items, root causes named).
Evidence base: `data/test_logs/2026-09-08-verification-2/verification-report-2-2026-09-08.md`.
Offline only: no sheet writes, no live batteries, no edits to defect logs /
test.md / verification reports. One commit per item (R3-3 spans two repos —
the live CLI is the parent-repo copy, same split as round 2).

Commits — tracker: `1fecb39` (R3-1), `5997fc6` (R3-2), `428a70e` (R3-3
test side); parent: `ceed5ec` (R3-3 CLI side).

## Status lines

R3-1 | DONE | proof = `TestGridCeilingGuardR3_1` 4/4 — the new fake mirrors gspread 6.2.1's REAL attribute surface (`row_count` present, `.rows` ABSENT, `update()` past the grid raises a genuine `APIError [400] "exceeds grid limits"`), covering: at-limit → expands first with `GRID_EXPAND_HEADROOM`, write lands, NO raw 400; headroom → no-op; failed expansion → the clear actionable error. The old helper's body proven against that fake: `getattr(.rows)` → None (guard skipped = exactly the live t8 crash path), new helper → 381. Legacy `.rows` fakes still pass (`TestGridCeilingGuardR2_11` 3/3, back-compat fallback). Full `test_sheets_sync.py` 125 passed | behavior changes: at the grid ceiling the guard now ENGAGES against real sheets (auto-expands +100 rows headroom before the append; a failed expansion still returns the clear "grid is full … add rows … re-run" error) — the raw `APIError [400]` escape live in t8 is gone; no change with headroom or when neither attribute exists. Live accept (bulk add crossing the real grid) belongs to the next Round B, per the spec.

R3-2 | DONE | proof = `TestHealthFileIsolationR3_2` 2/2 (session health path must point at the throwaway dir; a dirty write into the REAL `data/scrapedo_health.json` cannot reach `_store_unavailable_reason`). Acceptance run: full suite with the REAL health file deliberately dirty (`fail_streak: 1`, the R19 repro state) — both R19 tests (`test_tagged_add_broken_store_never_borrows`, `test_cli10_coles_unavailable_single_line_ww_shown`) PASS; conftest teardown now also asserts the health file byte-identical; real file restored sha256-identical (`2d501b81e438266eedca221964a14dcb40eebbf952fd2e1deab5ea5eba58a162`) | behavior changes: none (test infrastructure only — `extractors.coles_extractor.SCRAPEDO_HEALTH_PATH` joins the R2-8 conftest tmp-dir isolation set; the suite no longer reads the user's real breaker state).

R3-3 | DONE | proof = direct render probe: `⚠️ Coles unavailable (breaker open until HH:MM) — nothing written…` and `⚠️ Coles unavailable right now — …` with exactly ONE emoji; the two line-pinning tests strengthened and green (startswith `⚠️ `, assertNotIn `⚠️ ⚠️`); scanned all 52 `warn()` call sites in the CLI — no other one embeds a second copy | behavior changes: all 8 `_store_unavailable_line()` call sites print a single `⚠️ ` (was `⚠️ ⚠️`).

## Pytest counts

- Baseline (round-2 close, 2026-09-08): **1301 passed**.
- New tests this round: +4 (`TestGridCeilingGuardR3_1`) +2 (`TestHealthFileIsolationR3_2`) = **1307 total**.
- Final full suite (clean health file): **1306 passed, 1 failed** — the one
  failure is the pre-existing date-rotted specials test (see Deferred
  findings #1); **zero failures in any Round-3 code path**.
- Dirty-health acceptance run: **1305 passed, 2 failed** (the date-rotted
  specials test + one timing flake, both pre-existing/unrelated — Deferred
  findings #1/#2); the two R19 tests pass with the dirty file.
- State integrity after every run: `data/scrapedo_health.json`
  sha256-identical (`2d501b81…`); the R2-8 conftest teardown guard (4 state
  files + health file) passed in every full-suite run.

## Deferred findings (observed, NOT fixed — out of round-3 scope)

1. **`TestCLI::test_specials_leads_with_fresh_report` fails since TODAY
   (2026-09-09) — date rot, pre-existing.** The test crafts a Wednesday
   report "generated 2026-09-02" and `_cmd_specials` prints it only when
   `age <= 7 days`; the fixture aged out of the window on Sep 9 (it passed
   the 2026-09-08 verification at age 6 days). Proven unrelated to round 3:
   it fails identically at HEAD with the round-3 working-tree changes
   stashed. Fix would be a dated-fixture refresh (e.g. generate the report
   at `_dt.now() - 1 day` inside the test).
2. **`TestScanWindowsAndCutoff::test_between_alerts_window_enforced` is
   machine-speed flaky (1 failure in 4 full-suite runs).** The final
   scenario's post is created 0.05 s before its scan; when the two
   consecutive `run_daily_scan` calls execute < 50 ms apart, the post's
   creation time lands at/before the previous scan's stored alert cutoff
   and reads as "predates the last alert" → `n3` assertion misses. All
   fetch/messaging is mocked; no health/grid/warn path is involved. Passed
   in isolation, in its own file, and in the final full-suite run. A
   larger offset (e.g. 5 s) would de-flake it.
3. **Parent-repo pre-commit hook is broken by the user's own uncommitted
   deletion of `.pre-commit-config.yaml`** (visible in the parent `git
   status` at round start). Parent commits this round used the sanctioned
   `PRE_COMMIT_ALLOW_NO_CONFIG=1` bypass; nothing was skipped — the hook
   cannot run at all without a config. Environmental, left as found.

## Post-round note for the verifier

Unchanged from the spec: carry-over probe = one targeted `set_store_keyword`
read-back check in the next battery (R10 family); live accept for R3-1 = a
bulk add crossing the real grid limit with no raw APIError. Inherited
observation, no action: Local_Deals rows 115/116 orphan `[FRU]` comments.
