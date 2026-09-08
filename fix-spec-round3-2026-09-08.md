# FIX SPEC — ROUND 3 — 2026-09-08 — the final three (R2-11 residue + 2 new smalls)

Source: `data/test_logs/2026-09-08-verification-2/verification-report-2-2026-09-08.md`
(tally: 15/16 R2 items FIXED, 7/7 Round-1 fixes hold, 0 regressions).
This is a small round: three items, each with a named root cause. Same
hard rules as round 2 (no undocumented behavior changes, every existing-
test edit named, pytest green, offline only — live verification belongs
to the next Round B). Deliverable: `fix-round-report-3-<date>.md`, one
line per R3 ID: `R3-<n> | DONE/PARTIAL | proof | behavior changes`.

## R3-1 (R2-11 still broken — P1 for bulk ingests): grid-ceiling guard reads an attribute gspread doesn't have
**Root cause (proven live by the verifier):**
`_worksheet_grid_rows()` reads `getattr(worksheet, "rows", None)` —
gspread 6.2.1's Worksheet exposes **`row_count`**, not `.rows`. The
helper therefore returns None against any real worksheet and the
grid-expansion guard is silently skipped; two raw
`APIError [400] … exceeds grid limits. Max rows: 218` escaped mid-battery
(t8/t8r2_c_run.log). The offline tests pass only because their fakes
define `.rows`.
**Fix:** key the guard on `worksheet.row_count` (keep a tolerant fallback
for test fakes, but never by trusting an attribute gspread lacks — detect
fakes by the presence of `row_count` OR an explicit marker). Add a
regression test whose fake mirrors gspread 6.2.1's REAL attribute surface
(row_count present, .rows absent) — this is the test that would have
caught it.
**Accept:** offline: fake with row_count at the limit → expansion fires;
with headroom → no-op; broken expansion → clear actionable error. The
verifier's live-accept (next Round B): a bulk add crossing the real grid
limit with no raw APIError.

## R3-2 (R19 — P2): pytest goes red when the user's REAL breaker state is dirty
**Root cause (reproduced twice):** R2-4's regression tests read the live
`data/scrapedo_health.json` via `_store_unavailable_reason()`. With a
real `fail_streak` present, two tests fail (`test_tagged_add_broken_store_
never_borrows`, `test_cli10_coles_unavailable_single_line_ww_shown`) —
1301 passed with a clean file, 2 failed with a dirty one.
**Fix:** add `scrapedo_health.json` to the R2-8 conftest tmp-dir isolation
set (and/or inject the reason deterministically in the two tests).
**Accept:** full suite green with a deliberately dirty real health file;
the four state files + health file all sha256-identical after a run.

## R3-3 (R18 — P3, cosmetic): doubled "⚠️ ⚠️" on the unavailable-store line
**Root cause:** `_store_unavailable_line()` builds
`head = f"⚠️ {store.capitalize()} unavailable…"` and `warn()` prepends
its own "⚠️ " — all 8 call sites show "⚠️ ⚠️".
**Fix:** drop the emoji from `head` (keep `warn()`); update the tests
that pin the line text.
**Accept:** single ⚠️ everywhere; suites green.

## Post-round note for the verifier
Carry-over probe: one targeted `set_store_keyword` read-back check in the
next battery (R10 intermittent-write family, single occurrence last
round). Inherited observation, no action: Local_Deals rows 115/116 carry
orphan `[FRU]` comments on empty cells (pre-existing baseline residue).
