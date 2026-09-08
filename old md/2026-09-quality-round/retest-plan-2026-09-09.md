# RETEST PLAN — run after the fix-spec-2026-09-09 fixes land

Purpose: prove each of the 8 confirmed defects is fixed, then re-run the
full-scale battery to prove nothing regressed. Record results in `test.md`
as a new round ("Re-verification round 2026-09-__").

Everything reuses the tooling from the 2026-09-08 round, all in
`grocery-price-tracker/data/test_logs/2026-09-08-comprehensive/`:
- `harness.py` — runs one CLI command, logs rc/timing/output receipt to
  `commands_log.csv` + `outputs/`. Start a NEW log dir for the retest
  round (copy harness.py, point LOGDIR at the new folder).
- `batch_*.json` — the command batches (compare variants, live searches,
  list mechanics, local-deals).
- `t8_driver2.py` / `t8_driver3.py` — the 500-item battery (apply the
  harness fixes in §7 first).
- `baselines/` — pre-round snapshots (for diffing).

Interpreter: `C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe`
(the default python3.13 lacks curl_cffi). Work from
`C:\Users\User.DESKTOP-R2G441H\Documents\AI related\`.

---

## 0. Preconditions
1. All fixes from `fix-spec-2026-09-09.md` committed; `git log` shows them.
2. Offline suite green: `cd grocery-price-tracker && anaconda3/python.exe -m pytest tests/ -q`
   → expect ≥ 1219 + the new regression tests, **0 failed**.
3. Fresh baselines: snapshot the sheet (the recon script in
   `baselines/` flow) + copy `data/*.txt|*.json` state files + note
   `lists` / `todo show` / `missed-pricing` counts.
4. Quota hygiene: NEVER run two sheet-writing things at once (that's what
   crashed the first round); keep 1.25s+ between writes in any driver.

## 1. Per-defect regression checks (the whole point — run these FIRST)

| # | Check | Command | EXPECTED after fix |
|---|-------|---------|--------------------|
| FIX-1 UOM mixed pairs | sheet GONE cell + different-size live product | `compare --items "Sunbites Sour 60g"` | NO 110g-live vs 60g-sheet pair; found-block or honest per-store note; no totals for the rejected pair |
| FIX-1 regression | within-tolerance mixed pair still works | pick any sheet row whose store cell is GONE/blank with a same-product live hit within 20% | pair allowed, provenance lines shown |
| FIX-2 dry run | state untouched | hash every file in `data/` before and after `wednesday --dry-run --no-prompt --no-telegram --no-scp` (or compare against fresh copies) | ZERO file changes; unmatched items still PRINTED as "would write"; "DRY RUN COMPLETE" |
| FIX-3 multibuy math | real FRUT board re-ingest | put the FRUT anniversary txt back in `data/local_deals_inbox/FRUT/`, run `local-deals --ingest FRUT --no-telegram`… **but the board is expired — after FIX-4 this writes nothing, so test the math via the unit tests + a crafted future-dated post with "Celery – 2 for $2.99"** | cell = 1.50, comment = "[multi buy 2 for $2.99 — $1.50/ea]" |
| FIX-4 freshness | expired board dropped | same re-ingest of expired FRUT | "deals ended 06 Sep — nothing written"; 0 tab cells changed; post log entry flagged expired |
| FIX-4 comments | promo removal clears comment | crafted future post: first "Carrots 1kg Bag – 2 for $4.00" (ingest), then "Carrots 1kg Bag – $2.20" (ingest) | after 2nd ingest: price 2.2 AND the "[multi buy…]" comment segment GONE (empty) |
| FIX-4 sweep | sweep clears price AND comment | `--set-special merjan 'beef mince' 8.99/kg --till "5 September"` then `--expire-sweep` | price cell AND its comment segment cleared |
| FIX-5 store-scoped add | cross-store fallback dead | recreate the Yallamundi scenario: a `[coles]` unmatched entry + Coles breaker forced open (craft via `data/scrapedo_health.json` open_until future) → `map unmatched --add` | NO write, NO to-do entry, honest "Coles unavailable" message, debt intact; then clear the breaker and confirm a healthy add prices Col E + queues a coles to-do entry |
| FIX-6 halal chain | meat term never answered by chips | `compare --items "chicken breast"` | no Jumpy's rows; halal-chain answer or honest "not available" |
| FIX-6 boundary | sugar ≠ sugarfree drinks | `compare --items "sugar"` | RAW SUGAR / sugar rows or a question — NEVER "Red Bull Sugar Free" / "V Sugarfree"; also spot-check `compare --items "eggplant"` |
| FIX-7 floor | nonsense never priced | `compare --items "xyzzy plugh quantum banana 999"` | found-block, NO totals, add-item hint |
| FIX-7 legit fuzzy still works | misspelling | `compare --items "milkk"` | still resolves (above floor) or asks — your call, but no silent nonsense |
| FIX-8 tab dedup | word-order merge | crafted post with "5kg Bag Washed Potatoes – $2.99" while "Washed Potatoes 5kg Bag" row exists | merges into the existing row (row count unchanged, price updated) |
| FIX-9/10 adds | volume add integrity | t8 battery §5 below | refused adds leave NO rows; created-rows == written-count |

After §1: restore the Local_Deals tab from the pre-test snapshot (the
2026-09-08 round's restore script pattern) and clean any crafted inbox
folders + post-log entries.

## 2. T1 re-run — comparison & analysis (37 commands)
`harness.py batch batch_t1_compare.json`, then `batch_t1_variants.json`,
then `batch_t1_analysis.json` + `batch_t1_analysis2.json`.
EXPECT: all rc=0 (V07 junk → found-block post-FIX-7); multi-buy rows with
real terms (after a sync writes them) show 🏷️ notes; everything else as
in the 09-08 round receipts.

## 3. T2 re-run — live search (20 commands)
`harness.py batch batch_t2.json`. EXPECT: all execute; Coles may still hit
transient failures (that's Scrape.do, not the CLI) — but if D13 gets fixed,
the failure line should now SAY why + when retry is possible.

## 4. T3 re-run — Wednesday dry run + state integrity
1. `wednesday --dry-run --no-prompt --no-telegram --no-scp`
2. EXPECT: to-do shown first, parse/match/report as before, "DRY RUN
   COMPLETE", and **`data/` directory hash identical to before** (FIX-2).
3. This round is allowed to run for real ONLY on Wednesday with fresh docx
   pastes — not during retesting.

## 5. T4 re-run — list mechanics battery
Re-run the controlled fixture flow (t4_fixture.py pattern: ZZTEST row +
2 to-do entries) then `batch_t4a.json` (todo done/gone, missed-pricing
gone → delete-pending → row delete + archive). Rules that saved us last
time: **never `--purge` while real delete-pending rows exist** (use
per-code `gone`), put fake test entries at the END of list files and
target them by walking the session, verify every write by cell read-back.
Clean up: delete fixture rows, restore queue counts.

## 6. T6/T7 re-run — local-deals + expiry
`batch_t67.json` + the §1 FIX-3/4 crafted-post cycle + `--expire-sweep`
twice (second must remove 0) + `--post-log` + `--friday-gate` + off-window
`--daily-scan`. Restore the tab from snapshot afterward.

## 7. T8 re-run — the 500-item battery (driver fixes REQUIRED first)
The 09-08 drivers had four harness bugs (product code was fine; the bugs
are in MY test code — fix these in the copies before re-running):
1. **Verify desync:** after a refused add, the verify loop's store parity
   desynced (store_of(k) vs the item's real j) → 306 false FAILs. Track the
   store IN the added-dict (`added[name] = (row, store, j)`).
2. **Throttle reads too:** v3 crashed on the READ quota — global 1.3s min
   gap on EVERY ws call, and bulk-verify (one get_all_values per chunk)
   instead of per-item `ws.get`.
3. **Float compare:** "10.0" vs sheet-normalized "10" — compare numerically.
4. **gspread delete_rows semantics (CORRECTED R2-9/R16, 2026-09-09 —
   the old guidance below was WRONG and cost a real row):** installed
   gspread 6.2.1's `delete_rows(start_index, end_index=None)` is
   **1-based INCLUSIVE-INCLUSIVE** — delete rows a..b (1-based) =
   `ws.delete_rows(a, b)`; a single row is `ws.delete_rows(a)` or
   `ws.delete_rows(a, a)` (both verified live on 2026-09-08, including
   the incident post-mortem: the old formula `ws.delete_rows(a - 1, b)`
   deleted row a-1 too — the real Lindt row 114 went with test row
   115 and had to be restored from baseline).
   ~~"0-based half-open: delete rows a..b = `ws.delete_rows(a - 1, b)`"~~
   — do NOT use; keep the calibrated inclusive form + a contiguity
   assert in every teardown driver.
Then: run the battery (113 real + 387 synthetic, subsets, rule battery,
teardown, full-grid drift check). EXPECT: created-rows == written-count
(FIX-9), 0 phantom rows, drift 0, and per-defect behaviors consistent
with the fixes.

## 8. Final gates
1. `pytest tests/ -q` → 0 failed.
2. Full-grid diff vs the fresh baseline → **0 drift**; sheet row count
   unchanged; to-do/queue counts unchanged.
3. Telegram path spot-check (2–3 messages via the VPS gateway:
   lists / compare / one controlled write) — receipts in the round log.
4. Record the round in `test.md`, commit, push, scp (three-way sync).

## Pass criteria
- §1: every row PASS (these are the user-confirmed bugs — no partial credit).
- §2–§7: no NEW defects beyond what's already recorded; any new finding
  gets a defect ID + evidence in the round's folder.
- Sheet integrity: byte-identical restore after every destructive step.
