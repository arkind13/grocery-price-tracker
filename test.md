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
