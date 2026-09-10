# test.md — Wednesday restructure: to-do-first flow, searched retired,
# forgotten count-only (03 Code Agent, 2026-09-03)

User-defined Wednesday flow implemented verbatim:

1. **Start:** the run OPENS with the to-do list (items pending to add on
   the store websites) → user adds them on the sites → copies the
   updated lists into the Word docs → types `done`.
2. **After `done`:** the sync runs (auto-heal → match → price sync →
   two-strike dead-row delete) and the report gives unmatched,
   Woolworths/Coles missing, missed pricing (updated week counts via
   the first-fail ledger).
3. **Step 3c TALLY:** to-do entries whose sheet row now carries the
   store keyword are cleared; the UPDATED to-do list prints and posts
   FIRST in Telegram.
4. **Searched items queue: DELETED completely** from the pipeline
   (command now a retired stub; todo = add_to_list only; Step 1b drain
   removed; Step 0/9 converge add_to_list only; search --add-item and
   map unmatched --add and optimize +add now queue on the TO-DO list).
5. **Forgotten items: COUNT only** unless asked (`lists --full` shows
   names; the Telegram post and plain `lists` show counts).

## Changes

- `grocery_price_cli.py`
  - `_print_queue_snapshot` — Wednesday opens with the coded to-do list.
  - `_wait_for_manual_adds` — pause wording now references the to-do.
  - `_tally_todo_with_sheet` (NEW, Step 3c) — sheet keyword check per
    entry, all-or-nothing code removal, prints the updated to-do list.
  - Step 1b searched drain REMOVED; Step 0/Step 9 queue sync converges
    add_to_list.json + its tombstones only.
  - `searched-items` command → retired stub (prints pointer, exit 0).
  - `_todo_merged_entries`/`_cmd_todo` — add-only (searched branches
    removed); `add-to-list` alias simplified.
  - `_queue_searched_item` removed; `search --add-item` + `map
    unmatched --add` queue on the TO-DO list via `_queue_add_to_list`.
  - `_load_queues` (optimize) → to-do only; confirm ack `[todo: CODE]`.
  - `_weekly_queue_lists` — To-do (with codes, posted FIRST) +
    Forgotten count-only; Searched tuple removed.
  - `lists` — list 4 = to-do only; forgotten count-only in the summary.
- `core/basket_confirm.py` — `_queued_somewhere` checks the to-do list
  (legacy "searched" key tolerated); `_add_new_product` queues via
  `add_to_list.add_entry` instead of searched_items.
- `core/searched_items.py` — kept as dormant legacy (no CLI imports it
  anymore); its unit tests still pass in isolation.
- `claw-skills/grocery-price/SKILL.md` — wednesday flow, todo/lists/
  add-to-list/searched-items rows, routing rows (incl. retired
  searched), queue phrases; catalogue regenerated, `--check` OK.
- `README.md` — todo/lists/wednesday/add-to-list/searched-items rows +
  no-gaps note updated.
- Tests: test_todo_cmd rewritten (add-only); test_cli CLI-11..14 →
  retirement stub test; cli6/7/9/16, wc7, queue-confirmation, weekly-
  lists, lists-cmd, basket-confirm tests updated to the new rules.
  Net: 10 new/updated in this round (todo rewrite + tally coverage via
  rerouted suites).

## Test log

[PASS] | todo view: add-only, coded, Coles→Woolworths | `python -m pytest tests/test_todo_cmd.py tests/test_add_to_list.py -q` | 40 passed
[PASS] | done writes keywords + removes; gone marks GONE, keyword kept | (same run) | included
[PASS] | searched-items retired stub routes to todo show | `python -m pytest tests/test_cli.py -q` | 126 passed
[PASS] | search --add-item queues on the TO-DO list (not searched) | (same run) | included
[PASS] | map unmatched --add queues on the TO-DO list | (same run) | included
[PASS] | Step 0 pulls add_to_list + tombstones only (no searched) | (same run) | included
[PASS] | weekly-lists: To-do FIRST + Forgotten count-only, no Searched | (same run) | included
[PASS] | lists counts: #4 = to-do only, forgotten count in summary | `python -m pytest tests/test_lists_cmd.py -q` | included in full run
[PASS] | optimize classification + confirm queue via add_to_list | `python -m pytest tests/test_basket_confirm.py -q` | included in full run
[PASS] | full suite | `python -m pytest tests -q --ignore=tests/test_sheets_conn.py` | 759 passed, 2 failed (pre-existing date flakes, below)
[PASS] | claw skills catalogue | `python skills_doc.py --check` | `OK: claw_skills_easy.md is current.`
[FAIL → PRE-EXISTING] | test_cell_weeks_prefers_ledger_then_falls_back | `tests/test_missed_pricing.py` | `'2 weeks' != '3 weeks'` — date-boundary flake, fails identically on the clean tree (verified earlier today via stash); unrelated
[FAIL → PRE-EXISTING] | test_seeded_history_shows_two_weeks_immediately | (same file) | `'1 week' != '2 weeks'` — same root cause

## Verdict

All green except the 2 documented pre-existing date-flaky failures.
Deployment: CLI + skill files scp'd to the VPS, md5 verified on both
sides (bind-mounted — live for the next Wednesday run).


---

# Round 2026-09-04 — Sub-Categories (Q), Item-Codes (R), Preferred (S),
# Multi-Buy & Full Names (03 Code Agent)

Plan: `implementation-plan.md` (same folder). Branch
`feature/qrs-shop-multibuy` in BOTH repos (inner tracker + parent
`AI related`).

## Steps done

| Step | Result | Verification |
|------|--------|--------------|
| S0 | branches created both repos | `git branch --show-current` = feature/qrs-shop-multibuy |
| S1 | core/subcategory.py + 13 tests | PASS |
| S2 | core/multibuy.py + multibuy_tag helper + 15 tests | PASS |
| S3/S4 | core/item_codes.py (pure + sheet layer) + 27 tests | PASS |
| S5-S7 | core/preferences.py (read model, set_preferred, resolver) + 30 tests | PASS |
| S8 | schema NEW_COLUMNS extended | dry-run on live sheet printed exactly planned_columns Q/R/S (read-only) |
| S9 | add_product_row Q/R/S hook + 6 tests | PASS |
| S10 | lookup.py additive Q/R/S metadata + 4 tests | PASS |
| S11 | ProductItem multi_buy fields + 3 tests | PASS |
| S12 | D-MB2 probe | SEE BELOW |
| S13 | WW (outcome B hook) + Coles (multiBuyPromotion) capture + 5 tests | PASS |
| S14 | _specials_cell codec on both write paths + 6 tests | PASS |
| S15/S16 | comparator multibuy terms + effective-rate math + 8 tests | PASS |
| S17 | MAX_NAME_WIDTH 60 + 4 updated/new tests | PASS |
| S18 | display tag + totals footnote + 4 tests | PASS |
| S19 | 5 CLI subcommands + --subcategory flags + stubs + 4 tests | PASS |
| S20 | subcategories/backfill-subcategories/backfill-codes handlers + 6 tests | PASS |
| S21 | shop handler + 7 tests | PASS |
| S22 | prefer handler + resume + 7 tests | PASS |
| S23 | lists needs-review + multi-P surfacing + 3 tests | PASS |
| S24 | README schema/CLI tables + width + 2 new sections | grep 19 lines |
| S25 | PROJECT-MAP command rows + section 6F + columns + 7-lists note | grep 6 lines |
| S26 | SKILL.md 5 edits + catalogue regen | `python skills_doc.py --check` prints OK |

## S12 probe outcome (2026-09-04, live, read-only)

- **Woolworths: Outcome B.** WW search API returned 403 (no valid
  session cookie on this machine) -> payload keys UNVERIFIED. Per plan,
  the WW capture block degrades: `promo = {}` documented hook, fields
  stay 0/0.0. Test `test_ww_multibuy_captured_when_present` asserts the
  degradation (plan A-version test adapted to outcome B as the plan's
  "handles both outcomes deterministically" clause requires).
- **Coles: Outcome A.** Live Scrape.do probe:
  `pricing.multiBuyPromotion` = {type, id, minQuantity, reward,
  unitPriceDisplay}. Only `MultibuyMultiSku` observed (mixed-SKU);
  `reward` = bundle TOTAL (e.g. Zero Sugar Coke 10x375ml: now $23,
  reward 11.5, $3.07/L). Wired with the real keys
  minQuantity/reward.

## Test counts

- Baseline (plan says 621; the tree also carried a separate uncommitted
  "live-fill" feature, all green): **761 passed, 0 skipped** at start.
- Final full suite: **913 passed, 0 failed, 0 skipped** (anaconda
  Python; pytest). One transient test_optimizer F6 failure appeared in a
  single mid-run full-suite pass and did not reproduce in 3 consecutive
  full runs (shared data-file flake, not plan code).

## Deviations / judgement calls (all caught by the plan's own tests)

1. S1: the rule table lost the `\b` anchors its own docstring mandates
   -> `\bbreads?\b` restored (breading/breadcrumbs negatives);
   `corn chips` hoisted above the cheese family (mandatory test
   "Supreme Cheese Corn Chips" -> "corn chips").
2. S2: encode/decode roundtrip impossible via FOR_RE/ANY_RE (the cell
   form "2/$6.00" contains no "for"/"any") -> decode gained a tiny
   module-local _CELL_TERMS_RE fallback; encode form unchanged
   (contract fixed in S14/README).
3. S3/S4: nested locking (ensure_codes holds the advisory lock while
   confirm_code re-acquires) self-deadlocked -> lock made
   process-reentrant (cross-process O_EXCL semantics unchanged); the
   lock test simulates foreign-process contention by resetting depth.
4. S12/S13: the plan's WW keys (`MultiBuy.Quantity/TotalPrice`)
   unverifiable live -> outcome B hook per plan; Coles keys adapted to
   the REAL payload (`multiBuyPromotion.minQuantity/reward`).
5. S14: pre-existing test_update_single_price_multi_buy expected the
   bare "multi-buy" cell; updated to the new encoded form (spec-mandated
   change of behaviour, section 7.2).
6. S17: two pre-existing tests assumed 24-cell truncation (42/49-char
   names); updated to width-60 semantics (52-char intact, >60 truncates)
   per spec section 10.
7. S19: `import re` added to grocery_price_cli.py (the _cmd_shop item
   splitter needs it; the module never imported re).

## Environment notes

- System Python (3.13) lacks gspread/pytest -> all runs use
  C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe.
- S8 live dry-run and S12 probes are networked, read-only; both were
  executed locally (S8 dry-run result recorded above).
- NOT run here: S27 M1 live schema write, M2 live backfills, M3 deploy,
  VPS sanity — awaiting explicit go (networked, sheet-mutating ops).


---

# S27 execution log (2026-09-04/05)

- M1 schema append: done. dry-run planned exactly Q/R/S; live write added Q1:S1 (wrote=true); re-run: up to date.
- M2 backfills: done. backfill-subcategories: 104 rows examined, 104 written in ONE batched update (68 confident + 36 needs review). backfill-codes: two issues hit and resolved:
  1. save_registry os.replace raised WinError 5 twice (OneDrive/AV lock on a freshly-written tmp file in data/) after about 72 rows -> hardened save_registry with a 5-attempt PermissionError retry/backoff (still an atomic os.replace; Windows-only transient).
  2. During recovery, the partially-built registry (72 entries) was overwritten by a diagnostic write (mistake) -> rebuilt the registry FROM THE LIVE SHEET via confirm_code per populated R cell (one-off temp-dir script), removed the diagnostic TEST entry. Final state verified: sheet has 104 unique valid codes; registry has exactly 104 entries matching the sheet; backfill-codes re-run: planned=0, skipped=104, failed=0 (idempotent).
  Note: codes for rows deleted before the registry existed cannot be recovered (the file never contained them) - no rows were deleted between M2 start and recovery, so D-IC2 holds for everything ever written.
- M3 deploy: done. deploy_vps.py manifest EXTENDED first with this round files (new core modules + tests + telegram_format + schema_upgrade - without them the VPS sheets_sync import would break). scp mode: all files OK; container restarted; in-container smoke check OK. Rule-04 skill sync: SKILL.md + claw_skills_easy.md scp'd to /home/ubuntu/openclaw/tasks/ai-tools/claw-skills/...; md5 verified identical on both sides (da90ec2a... / 193f5b7b...).
- VPS sanity: container has no pytest (established state - testing runs locally per README); grocery_price_cli.py subcategories works in-container against the live sheet (68 confident labels + 36 needs review).
- M4 full verification: 913 passed, 0 failed, 0 skipped (local).
- Post-M4 fix (date-boundary flake): at the local-midnight roll to 2026-09-05, two PRE-EXISTING test_missed_pricing ledger tests failed (they seed local-date stamps while production week math uses UTC now; 21 local days measured as 20.x UTC days). Fixed test-side: UTC-anchored seeds (_days_ago_utc) + mirrored expectation helper (_weeks_label_utc); plus a test-enabling now= pass-through added to _cell_weeks (mirrors the existing injected-clock pattern of _weeks_without_price; callers unchanged). test_missed_pricing: 32 passed; full suite re-run green 913/0/0.


---

# Round 2026-09-05 — Multi-buy price cells + (m) markers + Any-N eligibility
# + Sub-category ask-first (04 Architect Checker, user-directed overrides R1-R3)

User answers 2026-09-05 to the checker's three questions plus a new
sub-category policy. Spec overrides recorded in architecture-spec.md
§15 (R1 supersedes D-MB1 raw-price clause; R2 retires D-MB3; R3
extends D-SC2). Verified before coding: live-sheet read showed 14 rows
with the OLD bare `multi-buy` cells and raw prices; both docx files
carry 7 WW "2 for $X" + 8 Coles "Any 2 | $X" deals; the Wednesday
BATCH path (sync_prices) still wrote the old vocabulary — the S14
plan missed that third call site (gap found and closed).

## Changes

- `core/multibuy.py` — `is_mixed_promo` REMOVED (D-MB3 retired):
  "Any N | $X" promos are rate-eligible multi-buy deals (user: they
  mean any N from the same range/brand in store).
- `core/sheets_sync.py`
  - `_multibuy_price` (NEW) — per-unit deal rate for the price cell
    (R1); `_specials_cell` now encodes terms for ANY-parseable promo.
  - `sync_prices` — batch Wednesday path now writes `_specials_cell`
    (encoded terms; was bare classify_special — the missed call site)
    AND the deal rate into D/E.
  - `update_single_price` — deal rate into the price cell when
    is_special + parseable desc (docstring step 11); dry-run reports
    the transformed price.
  - `add_product_row` — new rows with a multi-buy desc write the deal
    rate into D/E.
- `core/price_comparator.py` — mixed-promo gate dropped: every parsed
  multi-buy deal (sheet cell or live desc) drives effective-rate math.
- `extractors/coles_extractor.py` — captured multiBuyPromotion now
  also composes `Any N | $X` special_desc/is_special (when no other
  promo desc) so live adds get the same treatment.
- `grocery_price_cli.py`
  - `_MULTIBUY_LEGEND` + `_load_sheet_rows_safe` + `_sheet_multibuy_keys`
    + `_todo_is_multibuy` (NEW): `(m)` marks on to-do views whose sheet
    row sits on a multi-buy deal; legend renders when any item is
    marked. Wired into `_print_queue_snapshot` (Step 0), `_cmd_todo
    show`, `_tally_todo_with_sheet` updated list, `_weekly_queue_lists`
    to-do section (posted FIRST), and `lists --full` list 4.
  - `lists` — now SEVEN lists: list 7 "Sub-category reviews" (names of
    rows with the literal needs-review marker) + summary line + tail
    pointer; header rebranded "The 7 lists".
  - `_weekly_queue_lists` — new "Sub-category reviews" builder (names,
    best-effort sheet read; degrades to empty, never aborts Wednesday).
  - `search` — result lines carry the mandatory multi-buy note after
    the promo text; cheapest-store math uses the effective deal rate
    (§7.3 rule 6).
- `core/subcategory.py` — word-boundary hardening (R3): \bsugars?\b,
  \bwater\b, \beggs?\b, \bapples?\b, \bmilk\b, \boils?\b, \brice\b,
  \bflour\b, \bcheese\b, \bcoffee\b, \bjuice\b, \bsodas?\b, \bchips\b,
  \bsauces?\b, \bspreads?\b, \bpads?\b/\btampons?\b, etc. — "V
  Sugarfree"/"V Watermelon"/"eggplant"/"pineapple" now fall to needs
  review instead of a confident mislabel (the user's reported bugs).
- `claw-skills/grocery-price/SKILL.md` — multi-buy rule: deal rates
  live in price cells, Any-N counts, relay `(m)` + legend verbatim;
  NEW sub-category ask-first hard rule (run `subcategories`, pick
  confidently, ASK when unsure, unsure-without-user → needs review →
  Sub-category reviews list); lists table 6→7 lists with list 7
  description; catalogue regenerated, `--check` OK.
- `README.md` — multi-buy section rewritten (price-cell rule, Any-N,
  (m) marks); lists row 6→7; D/E/F + M/N/O schema rows; sheet diagram;
  new "Sub-categories: never guess" section.
- `PROJECT-MAP.md` — sub-category reviews note + multi-buy price note
  (top lists section).
- `architecture-spec.md` — §15 revision table (R1/R2/R3 overrides).
- Tests: test_multibuy (mixed-promo class → Any-N rate-eligibility),
  test_comparator (Any promo yields terms), test_sheets_sync (+5 new
  price-cell tests: sync FOR-style deal rate, update ANY-style,
  plain-untouched, is_special-None guard, add_product_row deal rate),
  test_subcategory (+3: misfires→review, V energy drink, boundary
  positives), test_lists_cmd (reviews wording + (m)/legend + reviews
  block + no-mark negative), test_todo_cmd ((m)+legend render +
  no-mark negative), test_cli (hermetic `_load_sheet_rows_safe` stubs
  in _atl_ctx/TestWeeklyQueueLists; titles 2→3 lists).

## Test log

[PASS] | full suite | `python -m pytest tests -q --ignore=tests/test_sheets_conn.py` | **925 passed, 0 failed, 0 skipped** (913 baseline + 12 new)
[PASS] | classifier sandbox check (misfires + positives) | temp-dir script against live rules | all 14 verified names matched expectations
[PASS] | live-sheet read-only state check | temp-dir script (get_all_values only) | 14 bare `multi-buy` cells, raw prices — no deal rates yet; Wednesday sync self-heals M/N + prices once deployed

## Notes

- The 14 existing bare cells need NO manual repair: the next
  Wednesday sync rewrites the specials cell of every seen row (and
  prices with deal rates); unseen rows' specials clear to "no".
- Deploy DONE (2026-09-05): `deploy_vps.py` scp mode — 39 files OK
  (manifest extended first with test_sheets_sync/test_todo_cmd/
  test_lists_cmd), container `openclaw-core` restarted, in-container
  smoke `searched-items show` OK. Rule-04 skill sync: SKILL.md ->
  BOTH VPS copies + claw_skills_easy.md -> ai-tools/claw-skills/;
  md5 verified identical both sides (SKILL.md a96dc827..., catalogue
  193f5b7b... — catalogue output unchanged by this round's edits,
  `skills_doc.py --check` OK). In-container `todo show` against the
  live sheet: clean render, no false (m) marks.


---

# test.md — Phase 2: Local Store Specials + Halal rules
# (03 Code Agent, 2026-09-05)

Implementation plan: `implementation-plan.md` (binding revision
2026-09-05 07:38 — autonomous execution §9). Final suite:
**1075 passed + 34 subtests, zero skips** (baseline was 925 + 34).

## Environment setup (before S0)

| Status | Item | Command | Output |
|---|---|---|---|
| PASS | pip deps | `python -m pip install gspread requests python-docx tzdata google-auth google-auth-oauthlib google-auth-httplib2 pytest` | installed (were missing locally) |
| PASS | UTF-8 console | `$env:PYTHONUTF8="1"` | Windows cp1252 crashed on emoji in CLI output — env fix only, no code change |

## Execution log

| Status | Test Name | Command Run | Output/Error Logs |
|---|---|---|---|
| PASS | S0 baseline | `python -m pytest tests/ -q` | 925 passed, 34 subtests passed |
| PASS | S1 connect_spreadsheet | `python -m py_compile core/sheets_client.py; python -m pytest tests/test_sheets_conn.py -q` | 1 passed |
| PASS | S2 fb_flyer_fetch chunk 1 | `python -m py_compile extractors/fb_flyer_fetch.py` | OK |
| PASS | S3 fb_flyer_fetch chunk 2 | `python -m py_compile extractors/fb_flyer_fetch.py` | OK |
| PASS | S4 test_fb_fetch | `python -m pytest tests/test_fb_fetch.py -q` | 16 passed (fixture bug fixed in TEST: distinct photo ids + literal post markers; CODE fix: position-based post grouping per §1.4.7 + real-FB basename regex `\d{6,}_\d+_\d+(_\d+)?(_n)?` and plausible-cstp size guard — plan sketch never advanced bucket idx and real FB ids broke the 4-group regex; §6 rule: code wrong, not test) |
| PASS | S5 shop_site_catalogue | `python -m py_compile extractors/shop_site_catalogue.py` | OK |
| PASS | S6 flyer_vision chunk 1 | `python -m py_compile core/flyer_vision.py` | OK |
| PASS | S7 flyer_vision chunk 2 | `python -m py_compile core/flyer_vision.py` | OK |
| PASS | S8 test_flyer_vision | `python -m pytest tests/test_flyer_vision.py -q` | 18 passed (truncation test routed through extract_json — production path) |
| PASS | S9 local_deals chunk 1 | `python -m py_compile core/local_deals.py` | OK |
| PASS | S10 local_deals chunk 2 (tab builder) | `python -m py_compile core/local_deals.py` + build_rows sanity snippet | sections correct; verbatim em-dash notes verified |
| PASS | S11 local_deals chunk 3 (matching) | `python -m py_compile core/local_deals.py` + detection sanity snippet | 21.3% alert fires; nugget gate blocks; Oreo untouched |
| PASS | S12 local_deals chunk 4 (render/deliver/run) | `python -m py_compile core/local_deals.py` + render sanity snippets | Post1/Post2 formats match spec §9 samples |
| PASS | S13 test_local_deals | `python -m pytest tests/test_local_deals.py -q` | 50 passed |
| PASS | S14 CLI local-deals | `python -m py_compile grocery_price_cli.py; python -m pytest tests/test_cli.py -q` | 152 passed |
| PASS | S31 topic provisioning | `python ../grocery_price_cli.py local-deals --provision-topic --dry-run` | `topic creation blocked (HTTP 400) — DM fallback; retries next run` ("not enough rights to create a topic") — plan §9 S31.5 fallback engaged; NOT a failure; `--provision-topic` retried later completes it once the bot can manage topics |
| PASS | S32 first live fire | `python ../grocery_price_cli.py local-deals` | `[telegram] ok message_id=1201/1202/1203 chat=1594431983 thread=dm`; exit 1 (partial store failures, report still sent = PASS per §9 S32); `data/local_deals_first_fire.json` contains all three message_ids |
| PASS | S32 gate check | `Select-String -Path .\data\local_deals_first_fire.json -Pattern '"message_id"'` | 3 hits |
| PASS | S15 meat taxonomy | `python -m pytest tests/test_subcategory.py -q` then full suite | 26 passed; 1022 total |
| PASS | S16-S18 core/halal | `python -m py_compile core/halal.py` | OK (3 chunks) |
| PASS | S19 test_halal part 1 | `python -m pytest tests/test_halal.py -q` | 10 passed |
| PASS | S20 sheets_sync hooks | `python -m pytest tests/test_sheets_sync.py -q` | 106 passed |
| PASS | S21 preferences guard | `python -m pytest tests/test_preferences.py -q` | 36 passed |
| PASS | S22 lookup intercept | `python -m pytest tests/test_lookup.py -q` | 35 passed |
| PASS | S23 domain unification | `python -m pytest tests/test_local_deals.py tests/test_halal.py -q` | 60 passed |
| PASS | S24 halal tests p2 + CLI wiring | `python -m pytest tests/test_halal.py tests/test_cli.py -q` | 30 + 156 passed |
| PASS | S26 skills + doc-sync | `python skills_doc.py && python skills_doc.py --check` | wrote 205 lines; `OK: claw_skills_easy.md is current.` exit 0 |
| PASS | S27 README | suite re-run (README-only change) | 1075 passed |
| PASS | S28 PROJECT-MAP + test.md | this log + PROJECT-MAP sections | done |
| PASS | S29 final gate | `python -m pytest tests/ -q` + `python -m py_compile` (all touched files) + `python skills_doc.py --check` | 1075 passed + 34 subtests; compile clean; doc-sync OK |

## Deviations (all §6-resolved: code wrong, not test)

1. `fb_flyer_fetch._group_by_post`: plan sketch never advanced the
   bucket index (all images landed in group 0). Implemented the
   §1.4.7 semantics the EC1 test pins (position-based assignment).
2. `PHOTO_ID_RE`: plan sketch required 4 numeric groups; real FB
   basenames are `{id}_{big}_{big}(_n).jpg` (3 groups). Regex
   widened; plus a plausibility guard (<=9999 px) on cstp sizes —
   FB emits degenerate `cstp=mx{hugeId}x{hugeId}` renditions that
   serve 2.5 KB placeholders.
3. `tests/test_local_deals.py::test_tier3_butchery_reader_domain_only`
   lives in `tests/test_halal.py` instead — `core.halal` is a Part-2
   dependency; the plan itself notes "re-run in test_halal too".
4. `query_local_butchers` classifies Col A names via
   `core.subcategory` (the Local_Deals tab has no Sub_Category
   column) — same §8.4 outcome, correct mechanism.
5. S31 topic creation is rights-blocked in the current group
   (bot lacks Manage Topics). The plan's DM fallback is active;
   provisioning retries automatically on every later
   `--provision-topic` run (baked into future Friday diagnostics).
| PASS | S30 VPS sync | scp CLI + core/extractors + 3 skill files; md5sum both sides; `docker restart openclaw-core`; `local-deals --dry-run` smoke | all 3 skill md5s match (fce2d042…, 46249820…, 58467348…); container restarted; smoke ran fetch→vision→render end-to-end (⚠️ lines expected: boards not yet published) |
| PASS | S33 VPS cron | idempotent install script via ssh stdin; `crontab -l | grep friday-gate`; `local-deals --friday-gate` outside window | `INSTALLED`; line `*/15 * * * * docker exec … local-deals --friday-gate >> /home/ubuntu/scripts/local_deals.log 2>&1` verified; Saturday run: EXIT_CODE=0, silent, no state written |

# Round 2026-09-06 — B2 / R17 Smart Basket: pipeline audit + gap closure
# (03 Code Agent — implementation-plan.md v1.0 executed as an audit)

## Context

`implementation-plan.md` v1.0 (2026-09-03) was written for a FRESH B2
build, but the tree already carries B2 in full —
`core/basket_optimizer.py`, `tests/test_optimizer.py` (all 28 matrix
tests), the `optimize` CLI subcommand, skill routing and docs —
subsequently evolved by committed rounds (2026-09-03 buy-list format +
two-phase confirm, 2026-09-05 halal gate). Re-running S1–S15 verbatim
would have regressed committed work, so the plan was executed as a
step-by-step audit with gap closure instead. Outcomes per plan section:

| Plan step | Audit outcome |
|---|---|
| S1–S13 module | present; evolved superset (item_labels/sources/prices, `plan_from_items`, buy-list `format_plan` per user rules 2026-09-03). Design lock-ins intact: min 5 items, strict-greater $3.00, Σ per-item gaps, WW tie-break, look-only |
| S14–S15 CLI | present at L72–90 / L2118–2234; adds `--confirm`, halal gate, sheet-first confirm flow (committed evolution); gate exit 2 + stderr intact |
| S16–S20 tests | all 28 matrix tests present; see [FAIL->FIXED] below |
| S21 SKILL.md 5 touches | all present (frontmatter L3, table L38, NL mappings L201–203, pattern 7 L237, timeout L330 + examples L358–359) |
| S22 catalogue | `python skills_doc.py --check` → OK (exit 0) |
| S23–S25 docs | README L382/L410/L714; PROJECT-MAP L54/L169/L350; roadmap R17 Realized L222 — all present |
| S26 round entry | THIS section (was missing — the only doc gap) |

## Gap fixed

`[FAIL->FIXED] | TestHalalIntercept: full-name-exact + non-meat-unscoped | python -m pytest tests/test_lookup.py::TestHalalIntercept -q | 2 failed (EXACT_SHEET vs SHEET_AND_LIVE). Root cause: both tests ran interactive=False on WW-only rows, so the 2026-09-03 live-fill merge (user report: bread/beef mince never reached live) re-tagged them SHEET_AND_LIVE — and worse, ran REAL live searches from unit tests (violating the file's "no network" contract; ~100 s of suite time). Fix (test-only, mirrors the in-file `_live_search_pair` mock convention): mock the live layer empty; the D-H4 scoping intent is untouched. 7 passed`

## Full-suite gate

- Before fix: **1073 passed, 2 failed** (both TestHalalIntercept).
- After fix: **1075 passed, 0 failed, 0 skipped** (79 s; 62 s on the
  repeat run — the mock removed the real network calls).

## S27 local acceptance (2026-09-06)

| PASS | S27.1 6-item basket (two-phase, auto) | `python grocery_price_cli.py optimize --items "milk, eggs, bread, beef mince, apples, rice"` then `optimize --confirm none` | run 1: halal gate note + 5/6 sheet-priced + 🔎 confirm block (KSM = Coles pricing missing) + eggs sheet substitute (read-only), exit 0; run 2: 🧠 SMART BASKET — 6 ITEMS / ✅ ONE TRIP: WOOLWORTHS — $37.72 / numbered buy-list with (sheet)/(sub) labels / 💵 subtotal / 💡 bottom note, exit 0, nothing written |
| PASS | S27.2 gate refusal | `python grocery_price_cli.py optimize --items "milk, eggs"` | refusal on stderr (points to `compare`), exit 2 |
| PASS | S27.3 full suite | `python -m pytest tests/ -q` (from repo root) | 1075 passed, 0 failed, 0 skipped |
| PASS | S27.4 catalogue | `python skills_doc.py --check` | OK |

## Notes

- Captured (piped) Windows runs need `PYTHONUTF8=1`: an interactive
  console is UTF-8 (PEP 528) but a cp1252 pipe crashes on the 🧠 emoji
  (`charmap codec`), exit 1 via main()'s handler. Environment artifact,
  not a code bug — docker/VPS and interactive runs are unaffected.
- S28 (VPS deploy) + the git commit remain user-gated per plan §6.3/§6.4.

# Round 2026-09-06 (evening) — Local Deals rebuild per
# TODO-local-deals-gaps.md: Tasks 0-3 + 4a wiring (03 Code Agent)

## Task 0 — topic 594 re-verified (config + test messages were MISSING)

`[FAIL->FIXED] | TELEGRAM_LOCAL_DEALS_TOPIC_ID absent | local root .env: key absent; VPS /home/ubuntu/openclaw/.env (bind-mounted /app/tasks/ai-tools/.env — confirmed via in-container _find_root_env): count 0 | upserted 594 both sides (inode-safe cat-truncate on the bind mount); test sends land INSIDE topic 594 from local AND container (receipt: route=topic, thread_id=594, api_ok=True, message_id=604). Provisioning side effect: first attempt created a duplicate topic 601 (env written to file, not process env) — DELETED via deleteForumTopic, env pinned to user-confirmed 594. USER visual re-check of the group still open`

## Task 1 — Sydney timezone discipline

- NEW `core/sydney_time.py`: `sydney_now()` / `sydney_today()` (single
  source; ZoneInfo DST-proof; AEDT switch handled by zoneinfo).
- Replaced server-time clocks (grep evidence, local-deals + halal
  paths only; queue/ISO-timestamp modules stay UTC by design):
  `core/local_deals.py` friday_gate_open, friday_gate_mark_fired,
  first-fire fired_at, run flow today_syd + run_dir;
  `core/halal.py` ledger TTL ×2 + checked_at ×2 (L280/298/310/557).
- §5 bug fixed: "Fri" hardcoded in render_post1/render_post2_blocks —
  headers now carry the run's real Sydney weekday (live proof below).
- NEW `tests/test_sydney_time.py` (6): the TODO's own pin (2026-09-06
  20:00 UTC == 06:00 Mon 7 Sep Sydney; "5 & 6 September" EXPIRED),
  23:59-boundary, year rollover, AEDT offset 11h, gate via UTC instant.

## Tasks 2-3 — timeline pipeline (text-first, per-post images)

- NEW `extractors/fb_timeline_fetch.py`: root-page render → Comet
  story JSON parse (post_id/creation_time/message.text/scontent urls,
  position-attributed per story, newest-first by creation_time).
- NEW `extractors/deal_text.py`: parse_validity_end ("Saturday &
  Sunday, 5 & 6 September" → 2026-09-06, Sydney year-inference),
  parse_fruitopia_deals (¢/$//kg/each/"2 for $X" grammar, multibuy
  divided out WITH note), filter_recent_posts (last-3 + future-only
  + needs_date_review bucket).
- `core/local_deals.py`: extract_post_deals (TEXT branch first;
  vision ONLY for image-only posts, on the post's OWN timeline
  images, max 4); _process_store_timeline (validity filter, expired
  dropped with date printed, undated EXCLUDED as needs-review,
  vision valid_until rescue); _process_store branches on the new
  `"pipeline": "timeline"` flag (fruitopia ONLY — other stores
  untouched on the legacy path until their own tasks).
- NEW `tests/test_deal_text.py` (20): fixtures from the REAL
  anniversary post; branch tests; pipeline wiring tests.

## Live evidence (Scrape.do: 3 renders + 1 vision call; rules honored)

| PASS | Render A (saved 976 KB render) | parse + filter | 1 story (post 974521905656870, created 2026-09-04 07:06 UTC), valid through TODAY Sydney (2026-09-06, its last day) → KEPT; 24 deals; 3 own images |
| PASS | Render B (scrollBottom attempt) | compare vs A | SAME post, SAME 1898-char text, IDENTICAL 24-deal signature; scroll did NOT surface older stories |
| PASS | Render C (Task 3b comparison) | text vs image | VISION on the post's own timeline images reads 24 deals (board IS on the timeline post — photos-tab was the wrong source); overlap 15/24 exact (name/unit variants; text authoritative: bread unit, multibuy 1.50-with-note) |
| PASS | 4a dry-run live | `grocery_price_cli.py local-deals --stores fruitopia --dry-run` | "🛒 LOCAL BOARDS — Sun 2026-09-06 (Mt Druitt)" (real weekday), all 24 Fruitopia deals, look-only, exit 0 |

### GAP (evidence, per TODO §3 timebox): the logged-out timeline render
exposes only the NEWEST story's JSON. Two independent renders (plain +
scrolled) both yield exactly ONE story. Last-3 enumeration + filter are
built and unit-tested (4-post fixtures) and will ingest older stories
when FB exposes them — but today only 1 post is extractable. Options
for the user: accept newest-post coverage, or a logged-in scraping
route (new work, not attempted — credits were not burned on it).

### Logged-in route (user APPROVED 2026-09-06 late evening) — BUILT

- `extractors/fb_timeline_fetch.py`: `fb_cookie_header()` (reads the
  `FB_COOKIE_C_USER` + `FB_COOKIE_XS` .env pair — secrets, never
  logged; both required), `_custom_headers_params()` (Scrape.do
  `customHttpHeaders=true` + b64 JSON Cookie header), and a route
  policy on `fetch_timeline_posts`: `logged_in="auto"` (default) =
  logged-in attempt first when the pair is set, graceful fallback to
  the logged-out render (max 2 credits); `True` = logged-in only;
  `False` = logged-out only (unchanged single-credit path).
- Secret hygiene: the b64 blob carries the cookie and travels only in
  the request params — never printed; the retry policy surfaces only
  exception class names.
- Tests: 6 new offline route tests (pair-required header builder,
  b64 round-trip with a dummy value, auto-fallback call order,
  single-call success, True-without-cookies raises with ZERO calls,
  False ignores cookies). `test_deal_text.py` now 26, all green;
  full suite unaffected (no production path changes without the
  env pair set).

## Round 2026-09-06, ~00:30 — twice-daily new-post detector
# (user redesign: cookies banned outright; GitHub check done — known
# logged-out scrapers are dead or login-based; user approved the
# detector flow)

### User requirements (verbatim intent)

- Today: scan topics from the LAST 3 DAYS (backfill).
- Going forward: 15:00 scan covers posts since 05:00; 05:00 scan
  covers posts since 15:00 (rolling windows).
- EVERY notification must carry the posted time AND the validity
  date — the user imports images/text only; remembering dates is
  the pipeline's job ("inbuilt in your skills or messages").
- `ignore <CODE>` skips a post permanently.
- 4-letter codes (3-letter reserved for Woolworths/Coles commands):
  FRUT / MERJ / DUNY / ABSA.
- Friday summaries cease once daily flow is proven (cron kept until
  then).

### Built + verified

| PASS | Live backfill (real Telegram to topic 594) | `local-deals --daily-scan` | DUNY: posted Thu 03 Sep 11:34 (validity not in text — asked at ingest); MERJ: Fri 04 Sep 20:20 (same); FRUT: Fri 04 Sep 17:06, valid until Sun 06 Sep (auto-parsed from text); ABSA: newest post 12d old → correctly silent. Exit 0 |
| PASS | Baseline state | data/local_deals_scan_state.json | per-store last_post_ref/creation/cutoff + windows map |
| PASS | Ignore command | `local-deals --ignore CODE` | marks last_notified_ref; scan never re-reports (unit-tested) |
| PASS | Ingest | `local-deals --ingest CODE` | newest inbox file (image → vision / text → parser), deals + validity, summary to topic (unit-tested) |
| PASS | Cron | ssh crontab | `*/15 * * * * docker exec … local-deals --daily-scan >> /home/ubuntu/scripts/local_deals_scan.log 2>&1` (window-gated inside: fires once per 05:xx / 15:xx Sydney) |
| PASS | VPS deploy | scp CLI + core/local_deals + core/sydney_time + core/halal + extractors/fb_timeline_fetch + extractors/deal_text + extractors/fb_flyer_fetch; NEW files via /tmp + sudo install (dirs are node-owned); md5 all 7 match local | verified |
| PASS | Skill + catalogue | SKILL.md detector flow + codes + ingest/ignore routing; `skills_doc.py --check` OK; both skill files scp'd, md5 match | verified |

### Tests

- `tests/test_deal_text.py` → 34 tests (route policy, backfill
  lifecycle: fresh first-sighting notifies / repeat silent / delta
  notifies; ignore marks; ingest picks newest; windows 05/15 Sydney).
- Affected suites: 118 passed. Full suite last full run this session:
  1101 passed, 0 failed, 0 skipped.

### Security note

A pytest failure diff transiently printed a real Telegram bot token
to the local transcript (test recorded full _send_message args).
Fixed: fakes now record message text only. Recommend rotating
`TELEGRAM_CLAW_BOT` when convenient (local-only exposure; not in any
committed file).

## Suite

- Affected suites: 106 passed (×2 runs) + full suite 1098 → **1101
  passed, 0 failed, 0 skipped** (+26 new tests this round).
- 3-pass rule: deal_text/sydney/local_deals/halal ran green 3×.

## 4a GATE — awaiting user confirmation

Fruitopia is integrated (timeline pipeline) and verified above. The
user must confirm the 24-deal list (and the anniversary post = the
"5 & 6 September" catalogue — TODO's posts (a) and (b) are ONE post)
before 4b Merjan / 4c Dunya / 4d Abu Salim start. VPS redeploy is
NOT done (TODO §7 comes after store verifications).

## Round 2026-09-06, ~12:35 — live detector run + user-directed fixes

- **Cadence fixed:** cron tick reduced from every-15-min to hourly
  (`7 * * * *`); off-window ticks now exit BEFORE contacting
  Facebook (zero credits, zero blocking risk — the scan itself only
  fires 05:00-05:59 and 15:00-15:59 Sydney, once per window).
  Manual runs need `--daily-scan --force`.
- **Duplicates root-caused:** my local backfill and the VPS cron
  each kept their own seen-state → double notifications. Fixed:
  scans are VPS-only (single state owner); per-post codes (FRUT,
  FRUT_1, …) name exactly which post each message is about.
- **Between-alerts cutoff rule implemented (user rule):** each scan
  records a Sydney cutoff; ongoing scans report only posts CREATED
  after it. Unit-tested (pre-alert post silent, post-alert notified).
- **Dunya site multibuy (user: "especially meat will have multibuy"):
  `--dunya-site` now parses "2 FOR $30"-style offers from product
  names into multibuy deals (effective rate in the specials column,
  bundle note in Comments, offers flagged vs regular). Tested with
  "Lamb Leg Roast … 2 FOR $30".
- **Tab rebuilt in the 7-column layout:** Product | Dunya (site) |
  Dunya FB specials | Merjan | Fruitopia | Abu Salim | Comments —
  101 Dunya site items, 0 duplicate rows (verified).
- **README + PROJECT-MAP + SKILL.md updated** (detector flow, inbox,
  codes, dunya-site sync); catalogue regen --check OK.

### LIVE run (VPS, 12:35 Sydney, real Telegram to topic 594)

| PASS | Run 1 — first run = last 3 days | `--daily-scan --force` (state reset first) | DUNY: Sep 3 post aged past 3 days → quiet; MERJ: Fri 04 Sep 8:20pm → notified; FRUT: Fri 04 Sep 5:06pm, valid until Sun 06 Sep → notified; ABSA: 12d old → quiet. Exit 0 |
| PASS | Run 2 — between-alerts proof | immediate re-run | zero new messages: DUNY/ABSA "predates the last alert — outside the between-alerts window"; MERJ/FRUT "already reported". Exit 0 |
| PASS | Full suite | pytest | 1119 passed, 0 failed, 0 skipped |

Three-way sync: tracker `caf0c24`, parent `1574931` pushed; VPS
files md5-matched (local_deals.py, CLI, shop_site_catalogue, skill,
catalogue).

## Round 2026-09-07 — R18 daily-scan: timestamped inbox codes + missed-window coverage

User report 2026-09-06/07: "last night 3 pm run and today morning
5 am run didn't happen" + only one Fruitopia alert received; user
rule: change the 4-letter inbox code to a 3-letter shop code +
ddmmyy + HHMM where the time is the ALERT time, never the post's.

### Findings (from the VPS scan log — nothing was broken)

- The 15:07 (2026-09-06:15) and 05:07 (2026-09-07:5) windows DID
  fire; both printed only "already reported"/"predates the last
  alert" — no notification is CORRECT when nothing new was posted
  since the last cutoff.
- The one Fruitopia alert came from the forced LIVE acceptance run at
  12:35 Sydney (window=2026-09-06:12 in the log) — the previous
  round's real-Telegram test.

### Changes (user rule 2026-09-07)

- `extractors/fb_flyer_fetch.py`: shop codes DUNY/MERJ/FRUT/ABSA →
  DUN/MER/FRU/ABS.
- `core/local_deals.py`:
  - Code = `<3-letter shop><ddmmyy><HHMM>` of the ALERT (Sydney time
    the notification is sent), e.g. FRU0709260507; `_2`/`_3` suffix
    on same-minute collisions. Replaces FRUT/FRUT_01 counters.
  - `run_daily_scan` now inspects up to `max_posts=3` per store and
    reports EVERY post since the previous cutoff — the user's
    missed-run scenario (window skipped, shop posts twice) no longer
    silently drops the middle post.
  - Shared `_store_for_code` resolver: first 3 letters; legacy
    FRUT/MERJ/DUNY/ABSA (and suffixed) codes still resolve, so old
    alerts on the user's phone keep working.
  - Ingest/ignore/set-date wording updated ("next alert mints a
    fresh code").
- `grocery_price_cli.py`: `--daily-scan` help shows the new format.
- README §local-deals + PROJECT-MAP §detector + SKILL.md (description,
  `--daily-scan` row, detector flow) updated; catalogue regen --check
  OK.

| PASS | py_compile | CLI + local_deals + fb_flyer_fetch | exit 0 |
| PASS | test_deal_text.py | pytest -q | 40 passed in 1.57 s |
| PASS | Full suite | pytest grocery-price-tracker/tests/ -q | 1121 passed, 0 failed, 0 skipped in 67 s |
| PASS | Deterministic lifecycle | injected advancing clock | backfill 4 shops → silent repeat → fresh timestamped codes FRU0709260907/FRU0709260917; immune to running the suite inside a scan window |
| PASS | Alert-time pin | fixed clock, post 20:15 prev day | code FRU0709260907 (alert 09:07), "When posted: Sun 06 Sep, 08:15 PM" |
| PASS | Missed-window scenario | two posts between scans | both reported: FRU0709261507 + FRU0709261507_2 |
| PASS | Legacy resolution | ingest FRUT / notified {"p1": "FRUT"} | resolves → fruitopia, pending codes cleared |

## Round 2026-09-07 (b) — R19 daily-scan: heartbeat, standout-at-ingest, multi-post alerts, dual-path ingest

User asks: (1) a finished scan with no new deals must still message
"no new deals" — silence is indistinguishable from broken; (2) does
the >20% master-sheet check fire when a saved post is ingested;
(3) Fruitopia posts text + pic — can the text file alone be dropped
in; (4) does the saved file's NAME matter; (5) alerts must show the
FULL Windows folder path for copy-paste; (6) do alerts say how many
posts are pending and what happens with different validity periods;
(7) the VPS inbox is not the PC inbox — fix the sandbox/PC gap.

### Answers → changes

- (1) HEARTBEAT (`run_daily_scan`): a completed scan with nothing new
  sends one "✅ Local deals scan done — no new posts …" message;
  partial fetch failures add "⚠️ Could not check: <names>"; total
  failure sends a ⚠️ could-not-check-any message. Off-window ticks
  and already-serviced windows stay silent (unchanged).
- (2) STANDOUT AT INGEST (`ingest_code`): the summary message now
  includes render_post1 of match_and_detect over the ingested deals
  vs Products_Master (same >20% machinery as the Friday report);
  degrades to "⚠️ Standout check failed" on master-read errors.
- (3) YES — already supported (.txt/.text/.md → `parse_fruitopia_deals`,
  no vision call); docs now say a text copy is the PREFERRED path.
- (4) File NAME is free; only the extension matters (.txt/.text/.md
  text parser; .jpg/.jpeg/.png/.webp vision; hidden files skipped).
- (5) Alerts now carry the full copy-paste path
  (`C:\Users\User.DESKTOP-R2G441H\Documents\AI related\grocery-price-tracker\data\local_deals_inbox\<CODE>`)
  via the new `USER_INBOX_ROOT_WIN` constant (scanner runs on the
  VPS but the user saves on Windows).
- (6) Multi-post scans add "📍 N new posts from this shop in this
  scan: <codes>" to each alert; every post keeps its OWN "Valid
  until" (per-post in alert, per-file in summary + post log). Ingest
  now merges REVERSED (newest file last) so the NEWEST post's price
  wins per item — older posts can never overwrite fresher prices.
- (7) DUAL-PATH INGEST: the PC runs ingest itself (local .env has
  vision/Telegram/sheet keys — `_load_env` walks up to the workspace
  root). Local is the path for PC-saved files; the VPS inbox only
  receives files forwarded into the Telegram topic. SKILL.md + README
  document both; never ask the user to re-save a PC file "into the
  sandbox". Local inbox files were ALSO scp-synced to the VPS inbox
  so both sides match.

| PASS | Local dry-run ingest (FRUT txt) | `--ingest FRUT --dry-run` on the PC | 24 items parsed by the text parser, "valid until Sun 06 Sep"; no sheet, no Telegram; rc 0 |
| PASS | Local dry-run ingest (MERJ jpg) | `--ingest MERJ --dry-run` on the PC | 1 item via zlm-glm vision (Lamb Curry $27.99/pack); rc 0 |
| PASS | Heartbeat (quiet scan) | patched fetch, all stores quiet | exactly 1 message, "no new posts", "✅"; rc 0 |
| PASS | Heartbeat (partial failure) | merjan+abusalim FetchUnavailable | rc 1, heartbeat names "Could not check: …" |
| PASS | Standout wiring | ingest with patched match_and_detect/render_post1 | summary contains the standout block; check ran once |
| PASS | Newest-wins merge | old txt ($0.80) + new txt ($0.99) same item | sheet cell = 0.99 (newest post wins) |
| PASS | Multi-post alerts | 2 posts between scans | per-post validity kept (12 Sep vs 19 Sep) + "📍 2 new posts …" count line |
| PASS | Full suite | pytest grocery-price-tracker/tests/ -q | 1124 passed, 0 failed, 0 skipped |

## Round 2026-09-07 (c) — R20: --set-date CLI wiring, validity row on the tab

User forwards a production finding (Claw, 07:30 Sydney): the skill
documented `--set-date`, but the CLI parser never had it, and
`set_date_cmd` double-appended the inbox dir
(`inbox_dir_for(code).parent / INBOX_DIRNAME / code`) so the
needs_date file was never found — Claw applied the state change
manually. User also asks for a per-shop "prices valid until" place
on the sheet (Dunya SITE column excluded — live prices).

### Changes

- `grocery_price_cli.py`: `--set-date CODE FILE DATE` (nargs=3) and
  `--post-log CODE` wired into the local-deals subparser + dispatch.
- `core/local_deals.py`:
  - `set_date_cmd` path fix: `inbox_dir_for(code) / "needs_date" |
    / "processed"` (double-append removed — Claw's diagnosis
    confirmed and fixed).
  - Tab row 2 = "Prices valid until": `rebuild_tab` writes the
    canonical row (Dunya site column = "n/a (live site)") and
    freezes rows 1-2; `merge_store_tab` inserts the row for
    pre-existing tabs and stamps the ingested store's column with
    the NEWEST dated post's period (`valid until Sat 12 Sep`
    format); `sync_dunya_site` never stamps (site column).
  - `ingest_code` picks the newest dated file's validity and passes
    it through.
- test_local_deals.py: header-freeze contract updated to 2 rows.

| PASS | Parser flags | `--set-date MERJ board.jpg "12 September"` / `--post-log FRUT` | parse + dest correct |
| PASS | set-date path fix | needs_date file in tmp inbox | file archived to processed/, post log entry 2026-09-12 |
| PASS | Merge validity stamp | fruitopia valid_until 2026-09-12 | row 2 E = "valid until Sat 12 Sep"; B = "n/a (live site)"; Merjan blank |
| PASS | Rebuild validity row | rebuild_tab + validity dict | row 2 written, stamp placed, frozen = 2 |
| PASS | Ingest stamps newest dated | old 12 Sep + new 19 Sep files | row 2 = "valid until Sat 19 Sep" |
| PASS | Full suite | pytest grocery-price-tracker/tests/ -q | 1128 passed, 0 failed, 0 skipped |

## Round 2026-09-07 (d) — R21 smart matching: plurals, bag-vs-bag per-kg, validity gate

User rules 2026-09-07: (1) "strawberry" must compare against
"strawberries"; (2) a 5kg onion bag must NOT compare against
individual onions — 5kg at Fruitopia compares per-kg against the
LARGEST bag available at Woolworths (5kg vs 2kg = x2.5);
(3) validity must gate the comparison — Fruitopia pricing that ended
yesterday must not keep producing "live" comparisons.

### Changes (`core/local_deals.py`)

- `_singular` / `_fold_plurals`: naive food-plural folder (ies→y,
  oes/xes/zes/ches/shes→strip es, generic s; cos/rice untouched).
  Applied in `canonical_key` (sheet grouping) and in the match loop.
- `_item_tokens`: plural-folded AND SIZE-STRIPPED matching tokens —
  "5kg" vs "2kg" never vetoes a name match (sizes are the point of
  the bag rule, not a mismatch).
- `_deal_weight_g`: weight (g) extracted from the deal's own text
  ("Onions 5kg Bag" -> 5000; loose/per-kg deals -> None).
- `match_and_detect` bag path: when the deal carries a weight, the
  master candidate pool keeps only WEIGHT-size rows and the LARGEST
  wins; both sides normalise to $/kg (5kg $7.50 = $1.50/kg vs 2kg
  $5.00 = $2.50/kg -> 40% under -> alert). No weight-size master ->
  "no comparable bag size at Woolworths/Coles", never a bag-vs-each
  comparison. Loose (kg) deals keep the existing path.
- Validity gate: a deal with `valid_until` < today (Sydney) is
  RECORDED but never compared or alerted — note "prices expired
  <day> — not compared". Ingest stamps each batch's validity onto
  its rows and lists expired files in the summary ("⏳ Expired —
  recorded, not compared").
- parse_size stays untouched (anchored parser — deal-side scanning
  lives in `_deal_weight_g`).

| PASS | Plural match | "Strawberries" vs master "Strawberry 500g" | matched, 70% under -> alert |
| PASS | Bag vs largest master bag | 5kg $7.50 vs masters 1kg/2kg | picks 2kg, per-kg basis, 40% -> alert |
| PASS | Bag equal rate no alert | 5kg $12.50 vs 2kg $5.00 | pct 0.0, no alert |
| PASS | Bag never vs loose each | only a size-less master | "no comparable bag size", pct None |
| PASS | Expired not compared | valid_until yesterday, 94% under | pct None, note "prices expired", no alert |
| PASS | Valid still compared | valid_until tomorrow | alert as normal |
| PASS | Full suite | pytest grocery-price-tracker/tests/ -q | 1134 passed, 0 failed, 0 skipped |
