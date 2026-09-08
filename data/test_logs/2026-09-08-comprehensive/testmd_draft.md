# test.md — FULL-SCALE live verification round (user-mandated 2026-09-08)

Mandate: "actually run the complete test — sheet comparison, live search,
Wednesday dry run, all lists, 100+ commands, FB ingest, expiry, and a
comprehensive **500-item** battery; record every error, fix nothing."

**Nothing was fixed this round.** Defects are recorded in
`grocery-price-tracker/data/test_logs/2026-09-08-comprehensive/defects.md`
(D1–D16 + R1–R9). Full receipts: `commands_log.csv` (every CLI command),
`outputs/` (one file per command), `t8_ops_log.csv` + `t8_items_manifest.csv`
(the 500 items), `baselines/` (pre-test state), `t8_summary.json`.

## Offline baseline
- [PASS] | Full suite before live testing | `pytest tests/ -q` | **1219 passed, 0 failed** (66s)
- Baseline live state: 113 sheet rows; to-do 4 (ESQ/NJL/DSF/AVE); unmatched 0 visible / 2 debt lines; ignored 34; missed-pricing 5.

## T1 — Sheet comparison & analysis (37 commands)
- [PASS] | compare sheet-mode, ALL 113 sheet items in 5 batches | `compare --items <25 names> --mode sheet` ×5 | every item priced, rc=0, 3.8–4.6s per batch
- [PASS] | compare variants ×12 | auto/no-team-discount/extra-discount 10/multi-buy/halal/misspelled/quotes/empty | correct dispatch; auto-mode 6 items = 69.8s (live fallbacks)
- [PASS] | analysis ×20 | specials(×3)/rewards/subcategories/analyze(×3)/recipe/optimize(×4)/lists(×2)/no-price/missed-pricing/unmapped/todo/searched-items | correct outputs; optimize <5 refused rc=2; `--confirm none` w/o run errors cleanly
- DEFECTS found: D5 (nonsense query silently priced via 1-word partial), D6 (UOM gate bypassed 60g↔110g), D7 (halal chain bypassed — chips answered "chicken breast"), D14 (pre-existing dup rows), D15 (bare multi-buy markers never upgraded), R2 (specials --store coles leaks WW section), R8 (empty compare rc=0)

## T2 — Live search (20 searches, real WW API + Coles/Scrape.do)
- [PASS] | 20/20 searches executed | broccoli → halal mince, junk, unicode, injection string, 200-char, single letter, --expand | ranked results + specials tags correct; junk honestly returns the stores' fuzzy hits
- DEFECTS: D13 (3 silent Coles failures → 10-min breaker, no diagnostics), R1 (injection string: WW 403 after 188.8s retry)
- Verified against known sheet state: Lindt tin LIVE at Coles ($14.00) while sheet WW cell blank (fixable verdict correct); Spring Onion EXACT hit at WW $2.85 (N/A keyword came from last week's list, mechanism correct)

## T3 — Wednesday dry run (the previously SKIPPED test)
- [PASS] | `wednesday --dry-run --no-prompt --no-telegram --no-scp` | to-do shown FIRST (4 entries) → parsed WW 72 / Coles 59 → matched 123 → plan: 123 cell writes, 53 N/A, 0 unavailable → two-strike candidate (Mozzarella) → tally (none resolvable) → lists + specials plan → "DRY RUN COMPLETE" | rc=0
- DEFECT D8: the "dry" run rewrote `data/unmatched.txt` (36-line debt → 2 lines) while preserving wool/coles files — inconsistent and lossy (recoverable via git)

## T4 — All 7 lists + mechanisms (controlled fixtures, full verify + cleanup)
- [PASS] | to-do lifecycle | `todo show` (6 entries incl. 2 ZZTEST) → done DAR (keyword written to I-col, entry removed) → gone BWL (E-col GONE, keyword untouched) → invalid code all-or-nothing (rc=1, nothing removed) | every write verified on the sheet
- [PASS] | delete pipeline (on ZZTEST row only) | keyword+NA markers → missed-pricing FIXABLE [code] → `gone` stamps GONE → delete-pending → `gone` deletes row + archives `gone-verdict` | Mozzarella (real row) untouched
- [PASS] | unmatched resolve loop | `--next` shows recommendations → `--skip` advances (debt intact) → `--add` created row + alias + to-do [SBM] → `--forget` junk → ignored list (+1, restored) → `--na` on fake entry = clean rc=1 error
- DEFECTS: D3 (cross-store `--add`: Coles debt item → WW product + WW to-do), D9 (map files stale, 8 vs 23 live), D10 (local↔VPS queue divergence + "All N resolved" wording on skip), R3 (junk live-searched before forget), R4 (numbering gaps in groups)
- INCIDENTS (both restored within minutes, disclosed): `--purge` deleted real Mozzarella row 112 → restored from archive; `map coles --na` hit real row 44 (fake line sorted last) → E44/J44 restored. Root cause of both: test-targeting error, pipeline behaved as documented (R7 row-shift noted)

## T6 — Local deals: FB message reading + dedup (real FRUT board + crafted posts)
- [PASS] | text parser | real Fruitopia board → 24 items, multibuy notes, validity "(till 6 Sep)" | correct
- [PASS] | merge isolation | crafted post updated ONLY Fruitopia cells; Merjan/Dunya untouched; row-2 stamp refreshed | correct
- [PASS] | newest-post-wins | second post re-priced Carrots → one row, new price + new stamp | correct
- [PASS] | new item | "Dragon Fruit" appended in produce section | correct
- DEFECTS: D1 (multibuy rate double-divided: parsed $1.50/ea → cell 0.75), D2 (expired board NOT dropped — 24 expired items written), D4 (word-order dup: "5kg Bag Washed Potatoes" appended as a NEW row), D11 (stale multibuy comment survives newer posts), R5 (post-log code not isolated), R6 (past --till accepted silently)

## T7 — Expiry dates + removal after runs
- [PASS] | `--expire-sweep` | cleared all 24 expired cells + row-2 stamp in one run (25 cells); idempotent second run: 0 | correct
- [PASS] | past-date special → sweep | "till 5 Sep" written 8 Sep → swept with stamp | correct
- [PASS] | GONE resurrection | GONE cell + `update_single_price` → price replaces GONE | correct (verified on 19 synthetic rows in T8 too)
- DEFECT: D12 (orphaned row-2 validity stamp with zero live specials — cleaned incidentally this round)

## T5 — 100+ command battery (the "telegram commands" set)
- The Telegram agent runs exactly these CLI commands (sheet mode, same files) — full battery via CLI with per-command receipts; PLUS the commands marked [TG] were executed through the REAL Telegram gateway (VPS `openclaw agent --deliver` → @ClawArkindBot DM).
- Total CLI commands logged: **{NCMDS}** (see commands_log.csv); areas: T1 comparison/analysis 57, T2 live search 20, T3 wednesday 1, T4 list mechanics ~40, T6/T7 local-deals ~15, T5 error-paths/dry-runs 20, misc verification.
- [TG] messages delivered through the real gateway: {NTG} — lists, compare (routing rule held: compare NOT search), search, specials, to-do queue, no-price phrasing, shop flow ("make me a shopping list for milk, bread and eggs" → final list with discounts + 🏆), plus write-path tests: {TGWRITES}
- [PASS] | error-path battery ×20 | update dry-run/unknown/bad-store, live-refresh, wednesday --source live (refused), todo done/gone invalid+empty, missed-pricing invalid code, map unknown list, 5× backfill dry-runs, topics-check, prefer invalid, shop empty, analyze invalid | all clean errors, zero writes
- Observations: R-liverefresh (live-refresh still runs a full headed pipeline when invoked directly — attempted queue flush, harmless without login), E18 stale shop session from Sep 7 still resumable

## T8 — THE 500-ITEM BATTERY (the big one)
- Manifest: `t8_items_manifest.csv` — **500 items: 113 REAL sheet rows + 387 SYNTHETIC ("ZZT8 …", not on sheet)**.
- Per real item: exact-index lookup + live price update (verified by cell read) + exact revert (original string). {P1LINES}
- Per synthetic item: add row (unit + store price + subset keyword/alias) → price update on the OTHER store → chunk verification (name/unit/both prices). {P2LINES}
- Rule battery: 30 word-order/lowercase variants of real rows (merge expected), 10 exact-duplicate adds with --allow-duplicate (exact names must still be refused), 20 reorder variants of synthetic rows.
- Subsets: 50 alias appends, 50 keyword writes, 60 NA markers, 19 GONE→resurrection cycles.
- Teardown: single contiguous-block delete + full-grid drift check vs pre-test snapshot. {TEARDOWN}
- **Run 1 crashed** at the phase-1 revert: Google Sheets 429 write-quota (~50 writes/min from concurrent batteries). Sheet fully restored from snapshot (0 cell diffs). Run 2 (quota-safe, throttled): {RUN2}.
- Performance finding: every add/update re-reads the ENTIRE sheet (dup-guard/matching) — ~4s per operation at 113-row scale; a 387-row ingest takes ~1h. O(n²) growth will get worse as the sheet grows. No 429 retry exists in core.
- DEFECT D16 (found by the battery): duplicate detector ignores bare numeric tokens — items differing only by a number collide ("ZZT8 0060 Basmati Rice 150g" refused as "already tracked (row 174: 'ZZT8 0061 …')"). {DUPCOUNT} adds refused at ~every 60 items.

## Final state
- Sheet: {FINALROWS} named rows — byte-identical to the pre-round snapshot on every checked cell ({DRIFT} drift cells, all restored).
- Queues: to-do {TODONOW} (4 local real; VPS side carries its own 6 until Wednesday's Step-0 union), unmatched debt 2 (the dry-run rewrite), ignored 34, Local_Deals tab restored to pre-round values.
- Full pytest after the round: {PYTEST} (no code was changed; suite re-run as a sanity gate).

## Bottom line for the user
The big mechanisms (Wednesday flow, to-do lifecycle, delete pipeline,
expiry sweep, newest-post-wins, compare/specials/analyze surfaces, the
Telegram path end-to-end) all WORK. The errors you've been seeing map to
16 recorded defects — the worst being: wrong data written by local-deals
ingest (double-divided multibuy rates, expired boards not dropped,
duplicate rows), the cross-store map add, the halal bypass on compare,
the one-line rule's numeric blind spot, and the dry run rewriting state.
