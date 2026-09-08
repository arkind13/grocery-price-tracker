# VERIFICATION REPORT 3 — 2026-09-09 — Round B3 (light): independent retest of fix round 3 (R3-1…R3-3)

Evidence-only round: NOTHING was fixed, no code file touched. Every
verdict rests on receipts produced by THIS round in `outputs/`,
`commands_log.csv`, the battery logs `t1_r31_bulk_*`, and the baselines/
vs-final diff. Interpreter `C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe`
(gspread 6.2.1), work dir `AI related/`, live CLI = parent-repo
`grocery_price_cli.py` (R3-3 side confirmed at `ceed5ec`: head builds no
emoji). Single writer, ≥1.3 s throttle on every driver.

## §0 Preconditions and fresh baselines
- Fixes committed: tracker `1fecb39` (R3-1), `5997fc6` (R3-2), `428a70e`
  (R3-3 test side) + report `aa056f5`; parent `ceed5ec` (R3-3 CLI side). ✓
- Fresh baselines (`baselines/`): Products_Master **114 grid rows incl.
  header / 113 named product rows**, grid capacity **380**; Local_Deals
  **133 rows**; 30 top-level state files copied; FULL data/ tree sha256
  manifest **7513 files** (`data_full_manifest_before.txt`).
  `data/scrapedo_health.json` at clean baseline, sha256
  `2d501b81e438266e…58a162` (== the round-3 report's close-out hash).
- Live list state moved since round 2 (user's own work, not gated):
  unmatched debt 2 lines (both `[coles]`), ww-missing 0, coles-missing 5.
- Quota calm this round — zero 429s across ~35 sheet-write ops.

## §1 Status matrix

| ID | Verdict | Evidence (this round) |
|----|---------|----------------------|
| R3-1 (R2-11, P1-for-bulk) | **FIXED (verified)** | (a) Live guard-engage probe (`outputs/S1_R31_guard_probe_live.txt`): `_worksheet_grid_rows(connect_worksheet())` → **380** — the sheet's REAL row count, NOT None; real Worksheet exposes `row_count`, `.rows` **ABSENT** (the exact old bug condition now returns the real number). (b) Offline (`S1_offline_guard_tests.txt`): `TestGridCeilingGuardR3_1` 4/4 + `TestGridCeilingGuardR2_11` 3/3 = **7 passed** (fake mirrors gspread 6.2.1's real surface: row_count present, .rows absent, genuine APIError [400] past the grid). (c) Reduced live-accept per the B3 prompt (`t1_r31_bulk_add.py`, `t1_r31_bulk_summary.json`, `t1_r31_bulk_ops_log.csv`): **25 synthetic adds** through the guard-bearing `add_product_row` — **25/25 written, ZERO raw APIError**, every row landed (115→139), teardown deleted the contiguous block `delete_rows(115, 139)` inclusive, **0 leftovers, 113 named rows**. `delete_rows` shrank grid capacity 380→355 (gspread semantics — the sheet's grid, not a defect); capacity restored to **380** (`t1_r31_grid_restore.txt`), so the summary JSON's `pass:false` (grid_before≠grid_after at battery end) is the documented pre-restore reading, superseded by the restore receipt. Crossing the REAL grid limit (hundreds of junk rows) skipped per the prompt — probe + real-surface fake are the accepted evidence. |
| R3-2 (R19, P2) | **FIXED (verified)** | Real `data/scrapedo_health.json` deliberately dirtied to the R19 repro state `fail_streak: 1, open_until: 0.0` (sha `d31a0b17…`; in-process `_store_unavailable_reason('coles')` → `'1 failed attempt'`, `S2_health_dirtied.txt`). FULL suite with the dirty file (`S2_pytest_dirty_health.txt`): **1306 passed, 1 failed in 69.6 s** — the ONLY failure is the documented date-rot nit `TestCLI::test_specials_leads_with_fresh_report` (Wednesday fixture "generated 2026-09-02" aged out of the ≤7-day window on Sep 9 — deferred finding #1 of the round-3 report, proven unrelated there); the timing flake `test_between_alerts_window_enforced` did NOT fire. Both R19 tests PASS inside the run, and re-run explicitly while still dirty (`S2_r19_tests_dirty_explicit.txt`): `test_tagged_add_broken_store_never_borrows` + `test_cli10_coles_unavailable_single_line_ww_shown` + both `TestHealthFileIsolationR3_2` (note: the class lives in `tests/test_cli.py`, not test_sheets_sync) = **4 passed**. File restored from baseline, sha256 `2d501b81…` verified (`S2_health_restored.txt`). Collection gate: **1307 collected** (`S6_collect_count.txt`). |
| R3-3 (R18, P3) | **FIXED (verified)** | Breaker forced open (`open_until` now+2 h) → live `map unmatched --add` (rc=1, 4.4 s, zero writes; `outputs/R3-3_map_unmatched_add_breaker_open.txt`): stdout line reads **`⚠️ Coles unavailable (breaker open until 09:32) — nothing written, item left on the list. …`** — programmatic count of `"⚠️ "` in the receipt = **exactly 1**; `"⚠️ ⚠️"` ABSENT; stderr carries the extractor's own breaker-skip note. Health file restored sha-identical immediately after. All-8-call-sites coverage is anchored by the two strengthened line-pinning tests (green in the R3-2 suite runs). |

## §2 Spot-checks (one command each, breaker CLOSED)

| Check | Receipt | Result |
|-------|---------|--------|
| `compare --items "sugar"` | `outputs/R2-1_compare_sugar.txt` (rc=0, 46.5 s) | `🟢 Woolworths $4.06 — Raw Sugar 3Kg (sheet)`; **zero "V Zero" occurrences**; honest `⚠️ 1 item missing at Coles`. R2-1 behavior holds. |
| `compare --items "Sunbites Sour 60g"` | `outputs/D6_compare_sunbites_sour_60g.txt` (rc=0, 18.2 s) | `🔴 Coles $2.70 — Sunbites Sour 60g (sheet)` — Coles sheet side ONLY, **no 110 g live pair** anywhere. D6 gate holds. |
| `compare --items "halal chicken mince"` | `outputs/R2-7_compare_halal_chicken_mince.txt` (rc=0, 72.9 s) | Full render (halal chain verdict block, Zwan candidate resolution, honest missing-at-WW + missing-at-Coles, totals). **Products_Master 113 named rows before/after, drift NONE** — no Zwan row written (D18/R2-7 render-only contract holds). |
| Breaker-open map line (reason + retry time) | = the R3-3 receipt | `⚠️ Coles unavailable (breaker open until 09:32) — nothing written…` — reason AND retry time present. |

## §3 Carry-over probe (R10 intermittent-write family) — PASS

`outputs/S5_set_store_keyword_probe.json`: fixture row added (row 115) →
one targeted `set_store_keyword('ZZV3B3 KW Probe 01', 'woolworths', …)` →
`wrote=True, range A115:I115` → **first fresh read-back returned the
keyword exactly** (no lag re-reads needed; the 4/5 miss did not
reproduce) → teardown: row deleted (inclusive), grid re-expanded to 380,
113 named rows, sheet drift NONE. The fixture `add_product_row` burned
one item-code registry entry (`SVW`, `sheet: ""`, row since deleted) —
own-battery residue, restored from baseline like round 2's t8 codes.

## §4 Observations (none numbered — no R20 this round)

1. **Item-code reservations from live compares (cache-only, by design):**
   today's halal compare ran the live search + halal chain FRESH (nothing
   cached for today), which reserved 5 item codes (`sheet: ""` — never
   written to the sheet) and cached 2 designed halal verdicts
   (El-Amin's cutlets/portions) in `halal_status.json`. Round 2's
   identical command showed a byte-identical registry only because its
   candidates were already cached same-day. Sheet-write contract intact;
   all restored from baseline. Worth remembering when reading registry
   diffs after compare batteries.
2. **`scrapedo_health.json` rewrite formatting:** a compare's live Coles
   path rewrote the file indented (`json.dump(indent=2)`) with semantics
   identical to baseline (`fail_streak 0`). Cosmetic; restored.
3. **Inherited, untouched:** Local_Deals rows 115/116 orphan `[FRU]`
   comments (pre-baseline residue, carried since round 2).

## §5 Final gates (all green)

- pytest: **1307 collected**; full dirty-health run **1306 passed / 1
  failed** — the 1 is the documented date-rot nit; zero failures in any
  round-3 code path; R19 pair + isolation class 4/4 explicit.
- State files: **30/30 sha256-identical** to fresh baselines at close;
  `scrapedo_health.json` sha `2d501b81…` (clean-baseline hash).
- FULL data/ tree manifest before vs final (`baselines/data_full_manifest_final.txt`,
  7534 files): **zero changed files outside this evidence dir**
  (the intermediate `…_final_check.txt` snapshot documents the §3
  registry burn discovered and restored before the final manifest).
- Sheet: Products_Master **114 grid / 113 named rows, drift NONE**;
  Local_Deals **133 rows, drift NONE**; grid capacity **380** preserved.
- Evidence hygiene: `baselines/session_state.json` WITHHELD from the
  committed/scp'd tree (browser cookies) — `baselines/WITHHELD.txt`,
  same policy as round 2.

## §6 Campaign-close recommendation

**CLEAN CLOSE.** R3-1 / R3-2 / R3-3 all verified FIXED on live surfaces;
both inherited observations carried from round 2 are resolved or pinned
(R10 probe pass; R18/R19 fixed). No new numbered defects (R20 unused).
Residual non-blocking items for whoever runs the next battery:
1. `test_specials_leads_with_fresh_report` date-rot — refresh the
   Wednesday fixture to a rolling date (deferred #1; it will fail every
   suite run from now until fixed).
2. `test_between_alerts_window_enforced` 0.05 s offset — de-flake with a
   larger offset (deferred #2; did not fire this round).
3. R3-1's full live-accept (a bulk add CROSSING the real grid limit)
   remains proven by probe + real-surface fake only, per the B3 prompt's
   accepted-evidence rule — one cheap probe during the next real bulk
   ingest (grid at 380, 113 named rows: ~267 adds of headroom) would
   close it completely.
4. Telegram/VPS gateway paths: NOT retested (unchanged scope from
   round 2).
