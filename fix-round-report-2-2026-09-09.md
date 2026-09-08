# FIX ROUND 2 REPORT — 2026-09-09 — R2-1…R2-16

Work order: `fix-spec-round2-2026-09-08.md` (as extended 2026-09-09).
All 16 items fixed in order (P1s first). One commit per item (CLI-side
changes are parent-repo commits — see Environment note; core/test
changes are tracker commits). Offline only: no sheet writes, no
verification batteries, no edits to defects.md / test.md /
verification reports (the one exception: R2-9 edited retest-plan §7,
explicitly allowed).

**Final pytest: 1301 passed, 0 failed** (baseline 1250 + 51 new
regression tests). Isolation proof (R2-8): a full run leaves all four
real state files sha256-identical (unmapped_queue.json,
local_deals_post_log.json, item_code_registry.json,
search_last_results.json).

## Environment note (read this first)

The LIVE CLI is the parent-repo file `AI related/grocery_price_cli.py`
(285 KB — has `_cmd_lists`, `_load_sheet_rows_safe`, …). The
tracker-root `grocery_price_cli.py` tracked at HEAD (commit 6ef7bc5)
is a STALE 137 KB duplicate whose presence breaks the suite (it
shadow-imports); its deletion in the working tree is deliberate and
load-bearing. I initially restored it from HEAD (broke 162 tests),
diagnosed it, and removed it again — the pre-session state is
preserved. Recommendation (deferred, out of scope): commit the
deletion of the stale tracker-root copy. CLI-side fixes (R2-4, R2-5
CLI half, R2-7 CLI half, R2-12, R2-13 CLI half, R2-14, R2-15 summary,
R2-16) are commits in the PARENT repo; engine/core/test fixes are
commits in the TRACKER repo — same arrangement as round 1 (parent
commits f8fbf9a/6136395 carried FIX-2/FIX-5).

## Status lines

| ID | Status | Proof (tests, all passing in the 1301) | Behavior changes |
|----|--------|----------------------------------------|------------------|
| R2-1 (D19, P1) | DONE | tests/test_lookup.py `TestAliasNegationGuardR2_1` — 6 tests: sugar never auto-answers V Zero (auto→RAW SUGAR row, interactive→candidates), directionality (zero-sugar/diet-coke queries still match their own alias), diet-qualifier refusal | Shared `_NEGATION_TOKENS` extended with `diet`, `lactosefree` (spec-directed ONE list) — plain "coke"/"milk" now also refuse Diet/Lactose-Free candidates in Step-3/live guards; `_negation_crossed` folds singular/plural variants |
| R2-2 (D20, P1) | DONE | tests/test_lookup_live_fill.py `TestBlankCellSameProductGateR2_2` — parametrized over blank AND GONE cells (different-product refused / same-product fills) | Blank/unavailable-cell live fills now require `is_same_product` (spec contract change). **2 existing tests updated (sanctioned):** `_live_ww` "WW Beef Mince 500g"→"Woolworths Beef Mince 500g"; one-sided fill test "Coles Bakery White 650g"→"Coles Tip Top Bread 650g" — both filled a DIFFERENT product (the exact D20 class) |
| R2-3 (D22, P1) | DONE | tests/test_sheets_sync.py `TestSizeTokenReorderMergeR2_3` — D22 variant merges, 5-variant reorder battery, exact-dup refused, 200g-vs-400g still appends | none (pack words + bare numbers drop from the body when a pack word survives the adjacency pass — order-independent bodies) |
| R2-4 (D3/D13) | DONE | tests/test_cli.py `TestStoreUnavailableReasonR2_4` — 8 tests: reason+retry-time formatting, honest line both branches, all 3 surfaces (search line, batch resolver honest-not-no-results + healthy back-compat, tagged --add forced-live rc=1) | Unavailable-store messages now carry the breaker reason ("breaker open until HH:MM" / "N failed attempts") + "nothing written, item left on the list"; healthy stores keep the not-listed wording; reasonless line keeps FIX-5's "right now" wording |
| R2-5 (D8-residue) | DONE | tests/test_name_matcher.py `TestRecordMissesR2_5` (2) + full-data-TREE-hash dry-run test running the REAL matcher (round-1's mocked the matcher and could not see the leak); re-audited every write in the wednesday flow — all others already gated | `NameMatcher(record_misses=…)` ctor kwarg (default True = old behavior). **1 existing test updated (sanctioned ctor change):** `TestWednesdayDryRunWritesNothing._FakeMatcher` (×2 occurrences) now accepts the kwarg |
| R2-6 (D21) | DONE | tests/test_local_deals.py `TestSweepStampReDerivationR2_6` (3: keep/re-derive/zero-lose) + undated-survival test | Row-2 stamps re-derived AFTER the cell sweep (max remaining till); deleted only when zero live specials AND expired; blank stamp cells stay blank. **1 existing test updated (sanctioned contract change):** `test_expired_row2_summary_stamp_cleared` fixture now has zero fruitopia specials; the undated-live-special case moved to a new test asserting the stamp now SURVIVES |
| R2-7 (D18) | DONE | test_halal.py render-only (add_product_row never called, note names candidate + flag-forwarding) + test_comparator.py D18 end-to-end (unique confirmed Zwan candidate: sheet rows + updates byte-identical, note rendered) | compare/recipe pass `allow_auto_add=False` → halal tier-2 renders, never writes. ⚠️ **USER CAN FLIP** to "accept + document" by removing the two flags in `_cmd_compare`/`_cmd_recipe`. Needed sub-change: price_comparator clears `halal_note` only when the result is actually PRICED (3 sites) — an unpriced found-block keeps its note so the resolution renders |
| R2-8 (R13) | DONE | tests/conftest.py session fixture (autouse): 4 state paths → temp dir + teardown assert; proof = full run 1301 passed with all 4 real files sha256-identical | **5 existing test blocks updated (they WERE the leak, sanctioned):** test_name_matcher.py manual capture/set/finally-restore QUEUE_PATH blocks (×5) → `patch.object` contexts (the finally restored the import-time REAL path, un-patching isolation for every later test) |
| R2-9 (R16) | DONE | Doc-only: retest-plan §7 item 4 corrected to gspread 6.2.1 (1-based inclusive-inclusive; `delete_rows(a, b)`, single `delete_rows(a)`/`(a, a)`), old 0-based formula struck through with the row-114 incident recorded | none (documentation) |
| R2-10 (R14) | DONE (no code defect existed) | tests/test_local_deals.py verbatim pin ("$15" and "$2x" round-trip through the Comments cell); offline repro + exhaustive scan of all 24 `re.sub` sites: user text never feeds a replacement string | none. **Misdiagnosis documented:** the S1.F04 receipt shows the note ALREADY mangled on the verifier's own command line — their unquoted `$15` was shell-expanded before the CLI ran; the code writes notes verbatim |
| R2-11 (R17) | DONE | tests/test_sheets_sync.py `TestGridCeilingGuardR2_11` (3: expand-at-limit with 100-row headroom, no-op with headroom, failed-expansion → clear actionable error, no raw APIError) | `add_product_row` expands the sheet grid first when the append row would pass it (GRID_EXPAND_HEADROOM=100); read-only fakes without `.rows` skip the guard (old behavior) |
| R2-12 (T1.A03) | DONE | tests/test_cli.py `TestSpecialsStoreFilterR2_12` (3: coles hides the WW report, woolworths/all show it) | `specials --store coles` no longer prints the saved Wednesday WW report; other flags unchanged |
| R2-13 (R3) | DONE | tests/test_lookup.py `TestSheetOnlyPassR2_13` (3, sentinel extractors) + tests/test_cli.py `TestUnmatchedLazyLiveR2_13` (2: --next on junk never calls the stores, --skip never calls) | `find_product(sheet_only=True)` kwarg; the map-unmatched DISPLAY pass is store-lazy (Steps 1-3 only); no-sheet-match line + both action prompts say live search runs when an action is chosen; --add/--pick still search live |
| R2-14 (R8) | DONE | tests/test_cli.py `TestCompareEmptyItemsR2_14` (empty + whitespace-only) | Empty `compare --items` → rc=2 "provide --items" on stderr, no basket header (was rc=0 empty basket) |
| R2-15 (D15) | DONE | tests/test_sheets_sync.py `TestBareMultibuyMarkerR2_15` (3: payload-with-terms upgrades cell + rate lands, no-terms leaves marker + reports it, stale discount/encoded still clear) | D25 not-found pass leaves BARE multi-buy markers untouched (they stay awaiting terms; stale "discount"/encoded-terms still clear to "no"); `SyncReport.multibuy_awaiting_terms` + a Wednesday summary section "Multi-buy rows awaiting deal terms" |
| R2-16 (D9) | DONE | tests/test_cli.py `TestLiveMapWorklistR2_16` (4: live count ≠ stale file count, --na removes from file + session with a second start showing the reduced set, legacy int progress migrates by identity, sheet-unreachable falls back to the file) | `map wool|coles` sessions rebuild the work list from the LIVE sheet (the `lists` rule); wool/coles progress becomes name-anchored `{"resolved": [...]}` (legacy ints migrated at session start; Wednesday's wholesale progress reset keeps the weekly cycle); `map status` shows live remaining for those lists; .txt files remain the offline record and still shrink on resolve |

## Deferred findings (recorded, NOT fixed — outside scope)

1. **Stale tracker-root `grocery_price_cli.py`** (see Environment
   note): recommend committing its deletion; it broke 162 tests the
   moment it existed. Not done here (working-tree state predates this
   round and is not mine to commit).
2. **Parent-repo in-flight changes untouched**: test.md, deleted
   .pre-commit-config.yaml / FIX_MISSED_PRICING_WEEKS.md / pc_cmd.py,
   and the untracked `old md/` moves — the user's own work; my parent
   commits stage only `grocery_price_cli.py`. (Parent pre-commit hook
   fails on its deleted config — my commits ran with
   PRE_COMMIT_ALLOW_NO_CONFIG=1.)
3. **R2-7 sub-change**: halal notes now render on UNPRICED found-block
   results (previously silently cleared) — visible e.g. for the
   multi-candidate tier-2 note. Mandated by the render-only contract;
   flagging for the verifier.
4. **R2-1 spillover**: "diet"/"lactosefree" in the shared negation
   list also gate Step-3 auto-pick and live auto-selection (ONE list,
   per spec) — plain "milk" will no longer auto-price "Lactose Free
   Milk"-class candidates anywhere; they still appear interactively.
5. **add_to_list / searched_items state paths** are NOT in the
   conftest isolation set (R13 named only the four proven leakers;
   these two are per-test isolated in the CLI tests). No pollution
   observed in the proof runs.

## Commits

- tracker `feature/qrs-shop-multibuy`: 7161518 (R2-1), 257c05c
  (R2-2), fa1d0cd (R2-3), 4cace40 (R2-4 tests), 1fc7297 (R2-5),
  0753a02 (R2-6, amended), bcbc61f (R2-7), 6d8856d (R2-8), 8a8c691
  (R2-9), fea0137 (R2-10), aec4464 (R2-11), d36021a (R2-12 tests),
  3d01622 (R2-13), 1298368 (R2-14 test), 99f0eef (R2-15), 0a9bd5e
  (R2-16 tests) + this report.
- parent (same branch name): 644cc63 (R2-4), 44fc6e1 (R2-5),
  2fac6df (R2-7), 0d29f53 (R2-12), b72fc99 (R2-13), a7eabc5 (R2-14),
  63959c1 (R2-15), f167a17 (R2-16).

Live verification belongs to the next Round B — nothing here was
exercised against the real sheet or the live stores.
