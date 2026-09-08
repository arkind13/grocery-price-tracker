# VERIFICATION REPORT 2 — 2026-09-08 — independent retest of fix round 2 (R2-1…R2-16)

Evidence-only round: NOTHING was fixed. Every verdict below rests on
receipts produced by THIS round in `outputs/` (one file per check),
`t8/t8_ops_log.csv` + `t8/t8r2_summary.json` (the volume battery), and
`commands_log.csv` (every CLI command with rc + timing). Baselines:
`baselines/` (Products_Master grid 114 rows incl. header / 113 named
product rows, Local_Deals tab 133 rows, 30 data state files + FULL-tree
sha256 manifest, 7388 files). Pre-round live state matched the prior
round's close-out: 113 product rows, to-do 4, unmatched 2 debt lines,
missed-pricing 5 (4 fixable · 1 delete-pending), Coles-missing 24.

Interpreter: `C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe`
(gspread 6.2.1). Work dir `AI related/`. Live CLI = parent-repo
`grocery_price_cli.py` (carries the R2 CLI-side commits — verified by
grep before testing).

## §0 Preconditions
- Fixes committed: tracker 7161518…cf801d7 (R2-1…R2-16 + stale-CLI
  cleanup), parent 644cc63…f167a17 (CLI side). ✓
- Offline suite: **1301 passed, 0 failed** in 88.84s — matches the fix
  round's claim (1250 baseline + 51 new). ✓ `outputs/S0_pytest_baseline.txt`
- Fresh baselines captured. ✓ Quota discipline: single writer, ≥1.3s
  throttle in drivers. ✓
- NOTE (environment): the Google-Sheets write quota was heavily
  contended during this round's T8 battery (repeated 429 storms,
  possibly the VPS sharing the credentials). The full 387-add battery
  could not complete; it was replaced by a quota-aware reduced battery
  (~124 adds total across runs) that preserves every evidence element —
  see T8 below.

## §1 Status matrix (one row per R2 ID, judged only by the spec's EXPECTED)

| ID | Verdict | Evidence (this round) |
|----|---------|----------------------|
| R2-1 (D19, P1) | **FIXED** | Offline (`outputs/S1_offline_probes_R2-1_3_D14_R2-2.txt`): `find_product('sugar', interactive=False)` → **row 47 'Raw Sugar 3Kg'** via Col P token match (was row 30 'V Zero 250 Ml'); directionality holds — `'zero sugar'` → row 30 V Zero; plain `'milk'` → Full Cream Milk 3L (not over-blocked). Live: `compare --items "sugar"` → "🟢 Woolworths $4.06 — Raw Sugar 3Kg (sheet)", NO V Zero anywhere (`outputs/R2-1_compare_sugar_live.txt`). 6/6 `TestAliasNegationGuardR2_1` green. |
| R2-2 (D20, P1) | **FIXED** | Live `compare --items "Lindt Hot Choc Flakes Tin 210g"` → Coles sheet side only ($14.00), NO Lindor gift-box pairing, NO "save $3.10", honest "⚠️ 1 item missing at Woolworths" (`outputs/R2-2_compare_lindt_live.txt`). Offline `is_same_product` = False for the pair. Parametrized blank/GONE tests green. |
| R2-3 (D22, P1) | **FIXED** | Offline: reorder "pack Evamay Pads With Wings Super 14" parses to the SAME body-token set + `is_same_product = True` (`outputs/S1_offline_probes_R2-1_3_D14_R2-2.txt`). LIVE probe (`outputs/S1_R2-3_D22_live_probe.txt`): the exact variant that appended a dup row last round now `merged=true row_index=23` with named rows staying 113; price/P/H reverted after. T8 Phase B: 10 true reorder/lowercase variants MERGED, 6 whitespace-only no-ops correctly refused by the exact-guard, 0 new rows (`t8/t8_ops_log.csv` phase B). 4/4 `TestSizeTokenReorderMergeR2_3` green. |
| R2-4 (D3-res/D13-R/D13) | **FIXED** | All three surfaces live with the breaker crafted open (`open_until` future): (a) `map unmatched --add` on a [coles] debt line → "⚠️ ⚠️ Coles unavailable (breaker open until 22:27) — nothing written, item left on the list…", rc=1, no write, session held (`outputs/R2-4a_map_unmatched_add_breaker.txt`); (b) `map coles` item resolve prints the same honest line INSTEAD of "No coles results found", zero store calls (`outputs/R2-16b_map_coles_start.txt`); (c) plain `search --product milk` → "⚠️ Coles not checked (unavailable — breaker open until 22:27)" (`outputs/R2-4c_search_breaker_open.txt`). Healthy back-compat: T2 receipts show "Coles not checked (unavailable — 1 failed attempt)" only on real failures, normal lines otherwise. 9/9 `TestStoreUnavailableReasonR2_4` green. Cosmetic wart on the line → **R18** below. |
| R2-5 (D8-residue) | **FIXED** | `wednesday --dry-run --no-prompt --no-telegram --no-scp` with a FULL `data/` tree sha256 manifest (7388 files incl. subdirs) before/after: the ONLY diffs are this round's own verification artifacts (harness commands_log.csv row + receipt files). **unmapped_queue.json byte-identical; zero changes from the dry run itself.** "DRY RUN COMPLETE", would-write list printed (`outputs/R2-5_wednesday_dry_run.txt`, `baselines/data_full_manifest_*.txt`). |
| R2-6 (D21, P2) | **FIXED** | Live Local_Deals flow: crafted expired Fruitopia special (till 5 Sep) + future Merjan canary (till 12 Sep, alongside real row 104 "27.99 (till 11 Sep)"). After `--expire-sweep`: expired cell removed, **Merjan stamp E2 SURVIVED re-derived to "valid until Sat 12 Sep"** (max remaining till — the exact D21 scenario), Fruitopia stamp G2 correctly DELETED (zero remaining live specials — the other branch, also live), second sweep removed 0. Tab restored from baseline, 0 drift (`outputs/S1_R2-6_post_sweep_cells.txt`, R2-6a/b/c receipts). 3/3 `TestSweepStampReDerivationR2_6` green. |
| R2-7 (D18 default) | **FIXED** | Live `compare --items "halal chicken mince"`: Products_Master 114 grid rows / 113 named rows BEFORE and AFTER — **no Zwan row written** (last round this exact command auto-added row 115); unmapped_queue/item_code_registry/add_to_list/deleted_rows byte-identical (`outputs/R2-7_compare_halal_chicken_mince.txt` + `S1_R2-7_pre_state.sha`); the halal resolution still renders (Zwan priced line, WW $10.16). `chicken breast` compare also wrote nothing (113 named rows after). Halal/comparator suites 110 passed incl. `test_tier2_render_only_never_writes_r2_7`. **D18 decision implemented = render-only default; user can flip to "accept + document" later by removing the two `allow_auto_add=False` flags in `_cmd_compare`/`_cmd_recipe`.** Note: when the halal candidate IS priced, no separate "butcher note" line renders — the resolution itself is the displayed answer (notes render on unpriced results); contract satisfied (nothing written). |
| R2-8 (R13, P2) | **FIXED (for the named scope)** | Full suite twice left the 4 named files byte-identical (§0 run + final gate, `outputs/S0_state4_before_pytest*.sha`). BUT a leak OUTSIDE the named set exists → **R19** below. |
| R2-9 (R16, doc) | **FIXED** | retest-plan §7 item 4 now reads gspread 6.2.1 **1-based INCLUSIVE-INCLUSIVE** (`delete_rows(a, b)`, single `delete_rows(a)`/`(a, a)`), old 0-based formula struck through with the row-114 incident recorded (`outputs/S1_R2-9_retestplan_section7.txt`). Teardown drivers this round used the calibrated form. |
| R2-10 (R14, P3) | **FIXED (no code defect existed)** | Live `local-deals --set-special merjan "zzver2 sweep canary" 8.99/kg --till "12 September" --note 'multi buy 2 for $15 and $2x'` → Comments cell reads **`[MER] multi buy 2 for $15 and $2x`** — verbatim, `$15` and `$2x` intact (read-back in the R2-6 flow, row 105; `outputs/S1_R2-6_post_sweep_cells.txt` + T2 receipts). The round-1 mangling is consistent with the fixer's shell-expansion misdiagnosis (my run quoted the note). Regression test green. |
| R2-11 (R17, P2) | **STILL BROKEN** | The grid-ceiling guard never engages against the REAL sheet. `_worksheet_grid_rows()` reads `getattr(worksheet, "rows", None)` — **gspread 6.2.1's Worksheet has no `.rows` attribute (it is `.row_count`)**, so the helper returns None and the guard is silently skipped; the offline tests pass only because their fakes define `.rows`. Proven live: `_worksheet_grid_rows(connect_worksheet()) → None` (`outputs/S1_R2-11_guard_skipped_live.txt`), and **two raw `APIError [400] Range (Products_Master!A219:S219) exceeds grid limits. Max rows: 218` escapes mid-battery** (`t8/t8r2_c_run.log`, `outputs/S1_R2-11_crash_t8r2d.log`) — the second with a freshly connected worksheet whose cached grid was accurate, i.e. exactly the production condition. Spec acceptance "never a raw 400 mid-run" is violated live. Fix: key the guard on `row_count` (and add a test with a fake exposing gspread's REAL attribute set). P1 for the next bulk-ingest week. |
| R2-12 (T1.A03) | **FIXED** | Live `specials --store coles` → only "🏷️ SPECIALS — COLES", the saved Wednesday WW report no longer prints (0 "WOOLWORTHS SPECIALS" hits); `--store woolworths` shows report + WW section; no flag shows report + "ALL STORES" (`outputs/R2-12*.txt`). 3/3 renderer tests green. |
| R2-13 (R3) | **FIXED** | Live with breaker open: `map unmatched --next` on debt items renders sheet-only recommendations in 5.7–7.0s (Google-auth dominated; vs 46.1s live-search burn last round) with "live search runs when you choose an action" prompts (`outputs/R2-13*.txt`); `--forget` on the junk line costs **0.4s / 0 credits**; `--skip` ×2 never touched the stores. `--next`/`--skip` lazy tests green. |
| R2-14 (R8) | **FIXED** | `compare --items ""` and `--items "   "` → **rc=2**, stdout empty (no basket header), stderr `Error: provide --items "item1, item2"` (`outputs/R2-14*.txt`). Tests green. |
| R2-15 (D15) | **FIXED (as specified)** | Live: the Wednesday dry-run Step-3 summary now lists "**Multi-buy rows awaiting deal terms (2)**" (Jumpy's Chicken Potato Chips 5 pack / V Watermelon 4*250 — the keyword-matched bare-marker rows) (`outputs/R2-5_wednesday_dry_run.txt`). Offline `TestBareMultibuyMarkerR2_15` 3/3: payload-with-terms upgrades the cell, no-terms leaves the marker + reports it, stale vocabulary still clears. The baseline sheet still holds 16 bare `multi-buy` markers (M/N) — awaiting terms is the designed state until a real sync carries deal payloads (the upgrade path cannot fire live without a real Wednesday sync). Nuance: only keyword-MATCHED awaiting rows are listed (2 of 16) — matches the spec sentence ("a keyword-matched row whose specials cell is the BARE marker…"). |
| R2-16 (D9) | **FIXED** | Live: `map coles` start → "**live work list: 24 of 24 missing-keyword row(s) from the sheet; file kept as the offline record**" == live `lists` count 24, while the stale file held 8 (`outputs/R2-16a_lists_live.txt`, `R2-16b`). Resolve half, via a fixture row (appended to the sheet, deleted after): `map wool` saw exactly 1/1 (fixture, J-keyword set); `map wool --na` wrote NA only to the fixture row (D115='NA'), **removed the item from the session AND the file line** (wool_missing.txt shrunk, header recount), second start showed the reduced set ("0 missing-keyword rows, 1 handled"), `map status` shows live remaining ("coles · 1 handled · 23 remaining (live)"). Legacy int progress `{"wool": 0}` migrated live to `{"wool": {"resolved": [...]}}` (`outputs/R2-16d…i`, state receipts in commands_log). 4/4 `TestLiveMapWorklistR2_16` green (incl. sheet-unreachable fallback). |

## Round-1 regression re-confirms (the 7 FIXED verdicts)

| ID | Verdict | This round's evidence |
|----|---------|----------------------|
| D1 multibuy math | **FIXED (holds)** | Live crafted post: "Celery – 2 for $2.99" → G115 `1.5 (till 14 Sep)` + comment `[FRU] [multi buy 2 for $2.99 — $1.50/ea]` (T67a receipt + cell read). |
| D2 freshness gate | **FIXED (holds)** | Expired crafted board → "deals ended Sun 06 Sep — nothing written", post-log entry `"expired": true` (`outputs/T67a_ingest_post1.txt`, post-log read). |
| D4 tab dedup | **FIXED (holds)** | "5kg Bag Washed Potatoes – $2.99" merged into existing row 118 "Washed Potatoes 5kg Bag" (price 2.99, no new row). |
| D6 UOM 20% gate | **FIXED (holds)** | `compare "Sunbites Sour 60g"` → Coles sheet side only, NO 110g live pair, honest missing-at-WW (`outputs/D6_compare_sunbites.txt`). |
| D7 halal chain | **FIXED (holds)** | `compare "chicken breast"` → halal chain ran (LLM verdicts: non_halal 0.70 / uncertain 0.50), NO Jumpy's chips answer, honest "No matching product — sizes don't compare" block, nothing written (`outputs/D7_compare_chicken_breast.txt`). |
| D11 comment lifecycle | **FIXED (holds)** | Carrots posted multibuy then plain: final row 134 = `2.2 (till 14 Sep)` with the multibuy comment segment GONE. |
| D16 add integrity | **FIXED (holds)** | T8: 114 synthetic adds written across runs (each passing `add_product_row`'s in-call read-back verify), bulk verify: on-sheet == written, 0 phantom, 0 refused (`t8/t8r2_summary.json`, `t8_ops_log.csv` phase A). Reduced from the historical 500-item scale by quota pressure — see §0 NOTE. |

**No regressions found in any Round-1 fix.** D14 watch: all 4 user-retracted
distinct pairs (Organic Free Range Eggs/Eggs Free Rage, both Sunbites
pairs, both V Watermelon rows) remain `is_same_product = False` and no
battery variant merged them (`outputs/S1_offline_probes_R2-1_3_D14_R2-2.txt`).

## New problems this round (next-round scope)

- **R18 (P3, cosmetic): the R2-4 honest line prints a doubled "⚠️ ⚠️".**
  `_store_unavailable_line()` builds `head = f"⚠️ {store.capitalize()} unavailable…"` and then wraps it in `warn()`, which prepends ANOTHER "⚠️ " (grocery_price_cli.py `_store_unavailable_line` + `core/telegram_format.warn`). Reproduced on stdout in `outputs/R2-4a_map_unmatched_add_breaker.txt` and `R2-16b_map_coles_start.txt`, and visible inside the assertion dump of the R19 repro. All 8 call sites are affected. One-character-class fix: drop the emoji from `head` (keep `warn()`).

- **R19 (P2): R13's test isolation missed `data/scrapedo_health.json` — the suite's PASS/FAIL depends on the user's REAL breaker state.** R2-4's regression tests read the live health file through `_store_unavailable_reason()`. Reproduced twice: with the real `fail_streak: 1` left by T2's transient Coles failures, the full suite reported **2 failed / 1299 passed** — `TestAddToListCLI::test_tagged_add_broken_store_never_borrows` (expects `'Coles unavailable right now'`, got `'Coles unavailable (1 failed attempt) …'`) and `TestCLIPartB::test_cli10_coles_unavailable_single_line_ww_shown` (expects the exact no-reason line) — and with the file clean the same suite reports **1301 passed** (`outputs/R19_health_state_failure_repro.txt`, `outputs/S0_pytest_final.txt`). A real Coles outage will turn the offline suite red with zero code regressions. Fix: point `scrapedo_health.json` at a tmp dir in the R2-8 conftest fixture (or inject the reason in tests).

- **Observation (extends the R10 intermittent-write family, not numbered):** in the T8 subset battery one of 5 `set_store_keyword` writes reported success but its read-back verify missed ("kw 4/5", `t8/t8r2_e_run.log`). Single occurrence; the synthetic rows were deleted at teardown before the cell could be re-inspected. NA writes were 7/7 this round (R10's flaky op). Worth one targeted probe next time a battery runs.

- **Observation (inherited state, not new):** Local_Deals rows 115/116 (Celery, Carrots 1kg Bag) carry `[FRU] [multi buy 2 for $1.50 — $0.75/ea]` comments on EMPTY special cells — an orphan-comment D11-class residue present in the pre-round baseline (restored state of the earlier testing rounds). Left untouched.

## Batteries
- **T1 compare variants (reduced core set):** sugar, Lindt, halal chicken mince, chicken breast, Sunbites, junk, milkk — all rc=0, behaviors per the matrix above.
- **T2 live searches (12 cmds, `outputs/T2R2.S01–S12`):** all executed; S12 empty-product rc=1 by design; S05/S07 hit real transient Coles failures and now render the R2-4 reason line ("1 failed attempt"); the injection-style string still slow-fails (189.3s — R1 class, unchanged, no FIX ID existed).
- **T3 dry run + FULL data/ hash:** clean — see R2-5. Real Wednesday NOT run.
- **T4 list mechanics (fixture + map + to-do):** fixture row added/deleted cleanly; `map wool` live-count 1/1, `--na` resolve (file + session + sheet NA on the fixture only), second-start reduced; `add-to-list show` listed the fixture entry with a fresh code; `done` wrote the I-col keyword (verified cell). The missed-pricing gone/archive/purge path was NOT re-exercised (untouched by round 2, green in both prior rounds); `--purge` correctly never fired (1 real delete-pending row present).
- **T6/T7 local-deals + expiry:** crafted-post battery (multibuy math, plain reprice, expired board) + the R2-6 sweep flow + R2-10 note — all live; tab + post-log + inbox restored to baseline, 0 drift.
- **T8 volume battery (reduced, quota-aware):** ~124 adds total (34 + ~90 + 10 + battery-internal re-adds), 0 refused, 0 phantom, read-back verify on every add; Phase B 16 variants (10 merged / 6 correctly refused) + the dedicated D22 live probe; exact dups 5/5 refused; subsets alias 5/5, kw 4/5 (observation above), na 7/7, GONE→resurrect 4/4; teardown deleted all synthetic rows contiguously (inclusive `delete_rows`), grid restored to 380, **final drift 0, named rows 113, 0 leftover** (`t8/t8r2_summary.json`). The R2-11 crashes occurred inside this battery and were repaired inline (grid manually restored) — receipts retained.

## §8 Final gates
- pytest after the round: **1301 passed, 0 failed** with the health file at baseline (`outputs/S0_pytest_final.txt`); the 2-failure state-dependence is R19, reproduced and documented.
- State files: unmapped_queue / local_deals_post_log / item_code_registry / search_last_results **byte-identical to pre-round baseline** at close (item codes burned by the T8 battery were restored from baseline — that residue was this round's own battery, not pytest).
- Sheet: Products_Master **0 drift** vs baseline grid; Local_Deals **0 drift** (both verified after teardown/restore).
- Telegram/VPS gateway spot-check: NOT RETESTED this round (out of live scope, unchanged from prior round).
- baselines/session_state.json withheld from the committed/scp'd evidence (browser cookies; `baselines/WITHHELD.txt`), same policy as the prior round.

## Tally & next-round scope

**R2 fixed: 15 / 16 — R2-1, R2-2, R2-3, R2-4, R2-5, R2-6, R2-7, R2-8, R2-9, R2-10, R2-12, R2-13, R2-14, R2-15, R2-16**
**Still broken: 1 — R2-11** (guard keyed on nonexistent gspread `.rows`; raw 400 escapes live; P1-for-bulk-ingest)
**Partial: 0** · Round-1 regression re-confirms: **7/7 FIXED, no regressions** · D14 watch: clean.

**New: 2 — R18 (P3 doubled warning emoji on the R2-4 line), R19 (P2 pytest depends on real scrapedo_health.json).**

**NEXT FIX ROUND SCOPE (the entire list):**
1. **R2-11** — rewrite `_worksheet_grid_rows()` to read `worksheet.row_count` (gspread 6.2.1), keep the fake-fallback tolerance WITHOUT trusting an attribute gspread doesn't have, and add a regression test whose fake mirrors gspread 6.2.1's REAL attribute surface; live-accept = a bulk add run crossing the grid limit with no raw APIError.
2. **R19** — add `scrapedo_health.json` to the R2-8 conftest isolation set (and/or inject the reason into `_store_unavailable_reason` in tests); accept = full suite green with a dirty real breaker.
3. **R18** — remove the doubled ⚠️ from `_store_unavailable_line` (keep `warn()`), update the two tests that pin the line text.
4. **Observation carry-over:** one targeted `set_store_keyword` read-back probe in the next battery (R10 family).
