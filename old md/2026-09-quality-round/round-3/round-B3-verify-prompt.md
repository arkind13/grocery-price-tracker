# ROUND B3 — LIGHT VERIFIER PROMPT (fresh session; paste everything below the line)

---

You are an independent verifier for the grocery-price-tracker project.
Round 3 (3 small fixes) is claimed DONE in
`grocery-price-tracker/fix-round-report-3-2026-09-09.md`. This is a LIGHT
verification pass — the round's diff is tiny, so do NOT run the full
battery. Your ONLY job is testing and recording. Fix nothing.

## Read first
1. `grocery-price-tracker/fix-spec-round3-2026-09-08.md` — acceptance per item.
2. `grocery-price-tracker/fix-round-report-3-2026-09-09.md` — claims (unproven).
3. `grocery-price-tracker/data/test_logs/2026-09-08-verification-2/verification-report-2-2026-09-08.md`
   — baseline you extend (D1–D22, R13–R19).

Environment: anaconda python
(`C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe`), work from
`C:\Users\User.DESKTOP-R2G441H\Documents\AI related\`, single sheet
writer, ≥1.3s write throttle. New evidence dir:
`grocery-price-tracker/data/test_logs/<today>-verification-3/` (same
structure; fresh sheet + state-file baselines first).

## The checks (in order)
1. **R3-1 guard engages against the REAL sheet:** call
   `_worksheet_grid_rows(connect_worksheet())` directly — it must return
   the sheet's real row count (NOT None; that was the bug). Offline
   re-run `TestGridCeilingGuardR3_1` + `TestGridCeilingGuardR2_11`.
   Then a modest bulk add (20–30 synthetic rows) with zero raw APIError
   and clean teardown. (Crossing the real grid limit would need hundreds
   of junk rows — skip it; the guard-engage probe + the fake that
   mirrors gspread 6.2.1's real attributes are the accepted evidence.)
2. **R3-2 dirty-health acceptance:** deliberately dirty the REAL
   `data/scrapedo_health.json` (fail_streak: 1), run the FULL pytest
   suite, restore the file, sha-verify. EXPECT: both R19 tests
   (`test_tagged_add_broken_store_never_borrows`,
   `test_cli10_coles_unavailable_single_line_ww_shown`) PASS. The ONLY
   acceptable failures are the two documented pre-existing nits:
   `test_specials_leads_with_fresh_report` (date rot since Sep 9) and,
   if it flakes, `test_between_alerts_window_enforced`. Anything else
   failing = a NEW defect.
3. **R3-3 single emoji:** force the breaker open, run any surface that
   prints the unavailable line; assert stdout contains exactly one
   "⚠️ " (assertNotIn "⚠️ ⚠️"). Restore the health file after.
4. **Spot-checks (one command each, from the prior rounds' receipts):**
   `compare --items "sugar"` → Raw Sugar, never V Zero ·
   `compare --items "Sunbites Sour 60g"` → no 110g live pair ·
   `compare --items "halal chicken mince"` → renders, sheet row count
   unchanged (113 named rows before/after) · one breaker-open map line
   shows reason + retry time.
5. **Carry-over probe (R10 family):** one targeted `set_store_keyword`
   write + read-back verify on a fixture row (add → set → read → clean).
6. **Final gates:** pytest counts (expect 1307 collected; the 2
   documented nits are the only tolerable failures); all state files +
   health file sha256-identical; Products_Master and Local_Deals 0 drift
   vs your fresh baselines; 113 named rows.

## Deliverable
`verification-report-3-<date>.md` in your evidence dir: a short matrix
(`R3-1/R3-2/R3-3 | verdict | evidence`), the spot-check results, the
probe result, final gates, and the campaign-close recommendation (clean
close vs items remaining). New problems continue the numbering (R20+).
Then: short entry in `test.md`, commit the evidence dir, push, scp to
`myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/data/test_logs/`,
checksum-verify. Touch no code files.
