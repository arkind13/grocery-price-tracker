# VERIFICATION REPORT — 2026-09-08 — Round B (independent retest of the fix-spec-2026-09-09 fixes)

Verifier session, evidence-only: NOTHING was fixed. Every verdict below
rests on receipts produced by THIS round in `outputs/` (S1.* = §1
per-defect checks, T1/T2/T3/T4 = battery re-runs), `t8_ops_log.csv` +
`t8_summary.json` (the volume battery), and `commands_log.csv` (every
CLI command with rc + timing). Baselines: `baselines/` (Products_Master
grid, Local_Deals tab, 28 data state files + sha256 manifest) — live
pre-round state was identical to the 09-08 round's (113 rows, to-do 4,
unmatched 2 debt lines, missed-pricing 5).

Interpreter: `C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe`
(gspread 6.2.1 — note R16). Work dir: `AI related/`.

## §0 Preconditions
- Fixes committed: tracker 9b10fcb→7a8c893 (FIX-1,3,4,5,6+7,8,9,10),
  parent 6136395+f8fbf9a (FIX-2, FIX-5). ✓
- Offline suite: **1250 passed, 0 failed** in 103s — matches the fix
  round's claim exactly (1219 baseline + 31 new). ✓ `outputs/S0_pytest_baseline.txt`
- Fresh baselines + live counts captured. ✓
- Quota discipline: single writer; ≥1.3s throttle in drivers. ✓

## Status matrix (baseline D1–D17 minus retracted D14, R1–R12)

| ID | Verdict | Evidence (this round) |
|----|---------|----------------------|
| D1 | **FIXED** | S1.F02: crafted "Celery – 2 for $2.99" → G115 `1.5 (till 20 Sep)` + comment `[FRU] [multi buy 2 for $2.99 — $1.50/ea]`; ingest prints "$1.50/ea (2 for $2.99)". Carrots "2 for $4.00" → 2.0 + correct note. |
| D2 | **FIXED** | S1.F01: expired FRUT anniversary board re-ingest → "deals ended Sun 06 Sep — nothing written", "0 cells written", post-log entry carries `"expired": true`. |
| D3 | **PARTIAL** | Cross-store borrow is DEAD: S1.M03 (breaker forced open) → no WW search, no write, no to-do, rc=1, debt + position intact; S1.M06 (healthy) → Coles-only search, `coles $14.30` into Col E row 115, to-do entry store = Coles. BUT the spec's honest message is missing: stdout says "No live search results found … Use --skip or --forget" (indistinguishable from not-listed); the breaker note appears only on stderr. = D13-R class, now proven on the unmatched path too. |
| D4 | **FIXED** | S1.F02: crafted "5kg Bag Washed Potatoes – $2.99" merged into existing row 118 "Washed Potatoes 5kg Bag /ea" (price 2.99, tab stayed 133 rows, no new row). |
| D5 | **PARTIAL** | Junk query fixed: S1.V06 + T1.V07 → found-block with per-store candidates, NO prices, NO totals, add-item hint. Sugar acceptance (folded into D5/FIX-6) FAILED → new **D19** (V Zero via alias token; the shipped guards cannot see it). |
| D6 | **FIXED** (its own scenario) | S1.V01: `compare "Sunbites Sour 60g"` → Coles sheet side only ($2.70, "· 60g"), NO 110g live pair, "⚠️ 1 item missing at Woolworths". (Product-identity gap on blank cells carved out as new **D20**.) |
| D7 | **FIXED** | S1.V03 + T1.V10: no Jumpy's/chips rows on meat terms; halal chain runs (LLM verdicts in receipts); honest "No matching product — sizes don't compare" block, no price. (Contract side-effect registered as confirmed **D18**.) |
| D8 | **PARTIAL** | Twice-proven (S1.W01 hash pair + clean §4 pass T3.D01): unmatched.txt preserved with would-write list printed, debt enrichment + scp + Telegram + sheet writes all gated, "DRY RUN COMPLETE". BUT `data/unmapped_queue.json` is still written by the parse step during the dry run (count/last_seen bumps on exactly the debt + docx-junk entries; mtime 14:06:01 inside the 14:05:43–14:06:13 run window; the ONLY file that changed in the clean §4 pass). Spec explicitly required "queue files" inside the skip. Root cause: `NameMatcher.match → append_unmatched` (core/name_matcher.py:298) is ungated. |
| D9 | **STILL BROKEN** | T4.X01: `map coles --next` resolves the stale file snapshot ("Item 1/8") while live `lists` reports 24 — same 8-vs-live gap as 09-08 (no FIX ID existed; correctly untouched). |
| D10 | **NOT RETESTED** | Needs the VPS gateway (Telegram) queue comparison; Telegram gates were out of this round's live scope (§8.3 not executed — see gates). |
| D11 | **FIXED** | S1.F03: plain reprice of Carrots ("$2.20") → G116 `2.2 (till 15 Sep)` and the Comments cell is EMPTY (the "[multi buy …]" segment died with its price). S1.F02 also shows a new promo REPLACING the pre-round stale `[FRU]` segment. |
| D12 | **STILL OPEN (inverse bug found)** | The sweep does clear expired stamps, but see **D21**: it also cleared Merjan's row-2 stamp while a live Merjan special (row 104, till 11 Sep) remained. The literal D12 scenario (zero specials + future stamp) was not re-exercised after D21 surfaced; D12 had no FIX ID. |
| D13 | **STILL BROKEN** | T2 S15/S16/S17: breaker-open Coles produces silent skips — stdout gives only the generic unavailable line, reason/retry time still absent (no FIX ID; unchanged). |
| D15 | **STILL BROKEN** | T1.V09: multi-buy row still shows no 🏷️ deal note (bare legacy markers; no FIX ID). |
| D16 | **FIXED (live-verified)** | T8 runs 1–2: 568 adds written, 0 refused, 0 phantom; the new read-back verify passed on every run-2 add and converted a read-quota 429 into a loud, item-named failure instead of silent success (t8_run.run2.log tail). |
| D17 | **PARTIAL** | T8 run 3 Phase B: 18/18 true word-reorder/lowercase variants MERGED with price+alias, and 10/10 exact case-identical adds refused — but see new **D22**: 1 reorder variant ("pack Evamay Pads With Wings Super 14") APPENDED a duplicate row instead of merging (the "14 pack"→"pack … 14" move breaks the size parse). The other 11 non-merges were identity-shaped variants correctly refused (exact means exact). |

### Round A findings judged this round
- **D18 — CONFIRMED (live).** `compare --items "halal chicken mince"` (T1.V10) AUTO-ADDED sheet row 115 "Zwan Luncheon Meat Halal Chicken 850g" (WW $10.70, alias "chicken breast|halal", row timestamp 14:39 = the T1.V10 window; grid was 0-drift at 13:57). No to-do entry. Violates the documented "compare | Never writes" contract. Artifacts fully undone (row deleted; registry/queue restored; 0 drift re-verified). User decision: accept + document, or make compare's halal chain render-only.
- **D13-R — CONFIRMED** and extended: the same silent-failure conflation now proven on `map unmatched --add` (see D3).

## New defects this round (next-round scope)

- **D19. `compare --items "sugar"` auto-answers "V Zero 250 Ml" (energy drink)** — KEYWORD_ALIAS short-circuit on Col P alias "V Energy Zero Sugar Original | 250mL" (full token "sugar") fires BEFORE the new AUTO_PICK_MIN_SCORE / boundary guards, which only catch substring crossings ("sugar" ⊂ "sugarfree"). Priced in totals, $2.52/$2.65 (outputs/S1.V04; offline repro: find_product('sugar') → row 30, note "Col P token match"). RAW SUGAR rows exist (47, 90). P1.
- **D20. Blank-cell live fill pairs a different product when sizes are within 20%.** `compare "Lindt Hot Choc Flakes Tin 210g"` (WW blank) live-filled the WW side with "Lindt Lindor Assorted Chocolate Gift Box 235g" $17.10 → normal totals + "save $3.10" (outputs/S1.V02). `is_same_product` = False offline; only the size gate ran. Same-product rule is applied to GONE cells only. P1.
- **D21. `--expire-sweep` removes the store's row-2 validity stamp even when live specials of that store remain.** Merjan: row 104 "27.99 (till 11 Sep)" survived, stamp "valid until Fri 11 Sep" deleted (outputs/S1.F04/F05 + cell reads). P2.
- **R13. Offline pytest suite writes REAL state files** (test-isolation leak): unmapped_queue.json (fixture names re-bumped; proven by controlled full-suite vs single-module runs), local_deals_post_log.json (+10 fixture entries at pytest time), item_code_registry.json (+8 codes burned, `row: 2, sheet: ''`). Mechanism: NameMatcher.match → append_unmatched + non-isolated post-log/code-registry callers. All restored from baseline. P2.
- **R14. `--set-special --note` mangles `$<digit>`**: note "multi buy 2 for $15" → cell "[MER] multi buy 2 for 5" ($1 eaten as a replacement-group reference) (outputs/S1.F04). Pre-existing-vs-new undetermined. P3.
- **R16. retest-plan §7's delete_rows formula is stale for gspread 6.2.1** (1-based INCLUSIVE-INCLUSIVE; "0-based half-open" no longer holds). INCIDENT (disclosed, repaired): FIX-5 cleanup's `delete_rows(114, 115)` deleted the real Lindt row 114 together with the test row 115; repaired from baseline within minutes (cells + E114 number format), 0 drift re-verified. Single-row `delete_rows(115, 115)` and `delete_rows(115)` verified correct afterwards. T8 driver uses the calibrated inclusive form with a contiguity assert. P2 process/watch.
- **R17. add_product_row hits the sheet grid ceiling at volume with an opaque crash** — T8 run 1: 380/387 adds succeeded, then `APIError: [400] … exceeds grid limits. Max rows: 381` killed the battery mid-run (t8_run.crashed-run1.log; stranded rows cleaned, 0 drift). A bulk ingest week would hit the same wall. Battery re-run after a temporary grid expansion (restored at teardown). P2.

## Battery re-runs (§2–§7)
- **§2 T1 (37 cmds):** all rc=0 except designed error paths (A11 optimize <5 → rc=2; A13 re-run "nothing to confirm" → rc=1). Junk found-block, halal chain, multi-buy note absence (D15) all as expected. **D18 confirmed here (T1.V10 wrote the Zwan row — undone).**
- **§3 T2 (20 live searches):** all executed (S18 empty-product rc=1 by design). Mid-batch the Scrape.do breaker tripped again after the S07 injection slow-fail (187.8s → WW 403) — D13/R1 classes unchanged. No silent WW-side anomalies.
- **§4 T3 dry run:** clean pass — only unmapped_queue.json changed (D8 evidence); everything else byte-identical; would-write list printed; "DRY RUN COMPLETE".
- **§5 T4 list mechanics:** fixture ZZTEST row 116 + 2 to-do codes → all-or-nothing refusal (rc=1, code list intact) → `done` wrote I-col keyword (verified cell) → `gone` stamped Coles GONE (verified) → price-0 rejected rc=1 → fixture pushed to ☠ delete-pending [ABH] → single `gone` completed archive + row delete (source "gone-verdict" in deleted_rows.json) — consumed its code, so a second `gone` correctly errors "unknown code". Fixture fully cleaned (0 ZZTEST rows). Map U/X: D9 re-confirmed (8 stale vs 24 live); X04/X05 (--na via map coles) deliberately skipped — same targeting incident class the 09-08 round hit; NA-marking was covered precisely via the API + T8 Phase D instead.
- **§6 T6/T7 local-deals + expiry:** folded into §1c (S1.F01–F06): freshness gate, multibuy math, comment lifecycle, sweep + idempotent second sweep all verified live; tab restored byte-identical afterwards (0 drift).
- **§7 T8 volume battery (three runs; add-phase evidence banked across runs 1–2, remaining phases in run 3):**
  - Run 1: **380/387 adds written, 0 refused**, crashed at add #381 on the sheet GRID CEILING (381 rows) — R17. Stranded rows cleaned.
  - Run 2 (after temporary grid expansion): **188 more adds, 0 refused**, each passing `add_product_row`'s new read-back verify, until a read-quota 429 made the verify RAISE LOUDLY naming row+item ("add verify failed: row 303 unreadable (APIError) after writing 'ZZT8V 0189…'") — precisely FIX-9's designed fail-loud behavior (the stranded row itself HAD been written; the verify correctly refused to report success without reading it back). Stranded rows cleaned.
  - Combined FIX-9 evidence: **568 adds written, 0 refusals, 0 phantom** (no add ever reported wrote without existing on sheet).
  - Run 3 (finisher): FIX-10 variant battery 18 true variants merged + 10/10 exact dups refused + 11 identity-variants correctly refused, BUT 1 reorder variant appended a duplicate row (**D22**, artifact deleted, 0 drift restored). Subsets: alias 4/4, keyword 4/4, NA 5/5 verified by read-back; GONE→resurrect 3/3; teardown 0 leftover; grid size restored to 381; merge side-effect H-col timestamps restored → final **0 drift** (t8_summary.json + t8_ops_log.csv).

## §8 Final gates
- pytest after the round: **1250 passed, 0 failed** (80.99s) — and it immediately re-polluted 4 real state files (unmapped_queue, local_deals_post_log, item_code_registry, search_last_results), live-confirming R13 once more; all restored.
- Final state (`restore_check.py check`): state files **30/30 identical** to baseline · Products_Master drift **0** · Local_Deals drift **0**. **GATES PASS.**
- Telegram spot-check (§8.3): NOT RETESTED this round (out of the session's live scope; needs the VPS gateway).
- Three-way sync: evidence dir + report committed & pushed to GitHub (tracker + parent for test.md); evidence dir scp'd to myvps and checksum-verified — see the round entry in test.md.

## Tally & next-round scope

**Fixed: 7** — D1, D2, D4, D6, D7, D11, D16
**Partial: 4** — D3, D5, D8, D17
**Still broken: 3** — D9, D13, D15 (+ D12 open with new inverse evidence D21; R-classes R1/R2/R4/R6/R7/R8/R11/R12 unchanged — none had FIX IDs)
**New: 9** — D18 (confirmed), D19, D20, D21, D22, R13, R14, R16, R17

**NEXT FIX ROUND SCOPE (the entire list):**
1. **D19** — sugar→V Zero via Col P alias token; route the KEYWORD_ALIAS path through the same boundary/negation guards (or drop negation-containing aliases from auto-pick).
2. **D20** — blank-cell live fill must require `is_same_product` (same rule GONE cells got).
3. **D22** — add-path merge key must not split when a reorder breaks the size-suffix pattern ("14 pack"→"pack … 14"); it appended a duplicate row.
4. **D3-residue / D13-R + D13** — honest unavailable-store message on `map unmatched --add` (spec wording), and the silent Coles failure class (breaker state on stdout + retry time).
5. **D8-residue** — gate `append_unmatched` (and any other state write in the parse step) behind dry_run; the fixer's offline FIX-2 test must also catch it (their temp-dir test missed the leak).
6. **D21** — sweep must re-derive row-2 stamps from the store's remaining live specials instead of deleting them.
7. **D18** — user decision: compare halal tier-2 auto-add vs the "compare never writes" contract (render-only recommended by the contract; user's call).
8. **R13** — test isolation: patch QUEUE_PATH/post-log/code-registry in the offending tests (or a conftest fixture that points the data dir at tmp).
9. **R16** — update retest-plan §7's gspread guidance (6.2.1 semantics) + keep the calibrated teardown formula in drivers.
10. **R14** — escape `$` in `--note` (re.sub replacement-string interpretation).
11. **R17** — grid-ceiling handling: expand the grid (or warn) when add_product_row approaches max rows, instead of an opaque APIError mid-bulk.

(Still-open pre-existing, no FIX IDs, unchanged: D9, D12-scenario, D15, R1, R2, R3, R4, R5, R6, R7, R8, R9, R10(see T8), R11, R12 — carry on the books.)
