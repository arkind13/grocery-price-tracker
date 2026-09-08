# Fix Round Report — 2026-09-09 (Round A, fix-only session)

Work order: `fix-spec-2026-09-09.md` (FIX-1…FIX-10). Evidence base:
`data/test_logs/2026-09-08-comprehensive/defects.md` (D14 retraction and
D11 comment-expiry requirement honoured). Offline suite green the whole
round; final counts at the bottom. Live verification belongs to the
Round B session per `retest-plan-2026-09-09.md` — nothing here was
verified against the live sheet beyond read-only CLI sanity
(`compare --mode sheet`, `lists`, `todo show`).

Repos touched (both on `feature/qrs-shop-multibuy`):
- parent (`AI related/`): `grocery_price_cli.py` (FIX-2, FIX-5)
- tracker (`grocery-price-tracker/`): core/extractors + all tests

| FIX | Status | Proof | Spec deviations |
|-----|--------|-------|-----------------|
| FIX-1 | DONE | `tests/test_lookup_live_fill.py::TestMixedPairUomGate` (5 tests: 60/110 rejected, 60/70 allowed, GONE same-product answers, GONE different-product never pairs, blank-cell fill still size-gated) — 12/12 in file pass | GONE semantics implemented as option (b): same-product per `is_same_product` AND UOM gate (spec allowed (a) or (b)) |
| FIX-2 | DONE | `tests/test_cli.py::TestWednesdayDryRunWritesNothing` — real temp data dir, byte-hash of every file unchanged across a dry run, would-write list printed, debt enrichment not called | none — audit found exactly two unguarded writes (`unmatched.txt` + `refresh_pending_prices` queue write); missed_pricing_ages/delete_candidates/queue files/scp were already gated |
| FIX-3 | DONE | `tests/test_deal_text.py::test_multibuy_bundle_total_with_note` + `tests/test_local_deals.py::TestMultibuySingleDivider` (FRUT text → cell 1.50, note "[multi buy 2 for $2.99 — $1.50/ea]"; "Any 2 \| $6.00" → 3.00; bulk 10kg/$55 → 55.00; scan-path bundle total) | Convention = spec's recommended one (parsers return BUNDLE TOTAL; `_cell_for` the only divider); parser also emits a display-only `unit_price` so the ingest print lines keep their "$1.50/ea" shape without re-division |
| FIX-4 | DONE | `tests/test_deal_text.py::test_expired_board_writes_nothing` + `test_plain_repricing_clears_stale_comment`; `tests/test_local_deals.py::test_expired_cell_cleared_comment_dies_with_it` | The Telegram summary no longer carries an "⏳ Expired — recorded, not compared" section (expired boards are refused at the gate; refusal prints locally and posts `expired: true` in the post log). One pre-existing sweep test updated from comment-kept to comment-dies (the new user rule) |
| FIX-5 | DONE | `tests/test_cli.py::test_tagged_add_broken_store_never_borrows` (mocked breaker-open Coles + healthy WW: no sheet write, no to-do, honest message, WW API never called) + `test_tagged_add_healthy_store_adds_same_store` (Col E price + coles to-do) | none for the tagged path. `--keyword` is RETIRED (prints the 2026-09-07 B2 notice, writes nothing) — "write that store's keyword column only" is vacuously satisfied; `map wool`/`map coles` verified already single-store |
| FIX-6 | DONE | `tests/test_comparator.py::TestLookupGuards` (chicken-breast → butcher line never Jumpy's; sugar with the real sheet-dump rows → Raw Sugar; drink-only sheet → no silent price; eggplant boundary) + `test_resolver_meat_term_routes_through_halal_chain` | Halal intercept existed in `find_product`; the real gap was Step-3 auto-pick short-circuiting it — fixed there + comparator/recipe unwrap `HalalResolution` (tier 3/0 render the butcher line / honest note via new `BasketItem.halal_note`). Optimizer inherits the wiring via compare. Trade-off: the negation guard also blocks e.g. "Lactose Free Milk" for query "milk" from AUTO-pick (interactive surfaces unaffected) |
| FIX-7 | DONE | `TestLookupGuards::test_junk_query_never_reaches_totals` (T1.V07 junk query: no_match marker, honest line, no totals) + `test_junk_query_live_results_also_refused` + `test_fuzzy_milkk_still_prices_above_floor` + `test_two_token_match_still_auto_priced` | `AUTO_PICK_MIN_SCORE = 2` in lookup.py plus two live-floor constants (`LIVE_MIN_TOKEN_FRACTION = 0.5`, `LIVE_MIN_SIMILARITY = 0.62`) — all tunable in one place; "milkk"-class fuzzy queries auto-answer via the similarity arm |
| FIX-8 | DONE | `tests/test_local_deals.py::TestTabDedupWordOrder` (5kg Bag Washed Potatoes merges w/ newest price; Royal Gala stays apart; /ea suffix rows merge) | none — `merge_store_tab` now matches rows by the SAME `canonical_key` build_rows/`--set-special` already use (token-set via name_matcher, variety-aware); no new matcher invented |
| FIX-9 | DONE | `tests/test_sheets_sync.py::TestAddPathVolumeIntegrity` — 387 unique adds: wrote=387, refused=0, merged=0, sheet rows=387, all unique (does NOT reproduce offline) + `test_corrupted_write_raises_loudly` | Per the spec's fallback: read-back verify added inside `add_product_row` (raises RuntimeError on name mismatch / unreadable row). No destructive rollback — the pre-write content of a mismatched row is unknowable; raising + never reporting wrote=True is the honest recovery |
| FIX-10 | DONE | `tests/test_sheets_sync.py::TestVariantBehaviorConsistent` — exact case-identical name refused; word-order variant MERGES (price+alias); lowercase variant MERGES (price+alias) | Spec's recommended behavior taken verbatim (exact = case-preserved, whitespace-collapsed only). One pre-existing test (`test_normalized_match_refused`) updated from the old case-folding refusal to the new merge contract |

## Retraction honoured

D14 — no merge logic anywhere treats the flagged pairs (Organic Free
Range Eggs / "Eggs Free Rage", the two Sunbites multipacks, the two V
Watermelon rows) as duplicates; FIX-8's variety-aware key and FIX-10's
one-line rule both keep distinct names/quantities apart (regression
tests included). No code change, as specified.

## Deferred findings (noticed, NOT fixed — outside FIX scope)

1. **R2** — `specials --store coles` still prints the Woolworths
   specials section above the Coles view (P3, no FIX ID).
2. **R3** — `map unmatched --next` live-searches paste-junk before the
   user can `--forget` (burns Coles credits; no FIX ID).
3. **R8** — empty `compare --items ""` prints an empty basket rc=0
   instead of a usage error (no FIX ID).
4. **D9/D10** — stale map work-list snapshots and the local↔VPS to-do
   queue divergence (Step-0 union only runs Wednesday; no FIX ID).
5. **D15** — multi-buy M/N vocabulary never upgraded on the sheet
   (bare legacy markers; no FIX ID).
6. **FIX-5 adjacent** — `_search_store_with_fallback` (wool/coles map
   lists) uses `fetch_coles_search` with no status channel, so a
   breaker-open Coles prints "No coles results found" exactly like
   not-listed. Store-scoped either way (no cross-store risk), so left
   alone.
7. **FIX-6 behaviour note for Round B** — the halal chain (now wired
   into compare/recipe) can AUTO-ADD one sheet row on a meat-term
   query when exactly one live candidate is LLM-confirmed (pre-existing
   D-H2 tier-2 behaviour; by design, but compare is now a path to it).
8. **FIX-9 quota note** — the read-back verify adds one single-row
   read per add (R12 pressure ~negligible vs the full-sheet re-reads
   the add path already does).

## Final pytest counts

`cd grocery-price-tracker && anaconda3/python.exe -m pytest tests/ -q`
→ **1250 passed, 0 failed** (baseline 1219 + 31 new regression tests;
net +24 tests, 7 existing tests updated to the new documented
contracts named above).
