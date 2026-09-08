# DEFECT LOG — 2026-09-08 comprehensive live test round

> **STATUS 2026-09-09:** fixes are now SPECIFIED in
> `grocery-price-tracker/fix-spec-2026-09-09.md` (FIX-1…FIX-10, priority
> ordered — FIX-1/FIX-2 are P0, must land before the next Wednesday run).
> Re-verification plan: `grocery-price-tracker/retest-plan-2026-09-09.md`.
> User corrections applied: D14 RETRACTED (the flagged pairs are separate
> products); D11 extended — expired prices must clear their comments too;
> D5/D7 family extended with the user's sugar-vs-"V Sugarfree" case.

Evidence: `outputs/` (one file per command), `commands_log.csv` (every CLI
command with rc + timing), `t8_ops_log.csv` + `t8_items_manifest.csv`
(the 500-item battery), `baselines/` (pre-test state).

Severity: P1 = wrong data written / user-visible wrong answer ·
P2 = loophole or misleading output · P3 = cosmetic / robustness.

## P1 defects (wrong data / wrong answers)

### D1. Multi-buy rate double-division in local-deals text ingest
- `extractors/deal_text.py:91` already returns the per-unit rate
  ("2 for $2.99" → price 1.50, its own doc says "Price is per-unit").
- `core/local_deals.py::_cell_for` divides by qty AGAIN when
  price_kind == "multibuy" → cell written = 0.75 for a 2-for-$2.99 deal.
- Proven live: re-ingest of the real FRUT board printed
  "Celery — $1.50/ea (2 for $2.99)" but wrote `0.75 (till 6 Sep)` into
  the Fruitopia special cell (both Celery and Carrots rows).
- The multibuy NOTE is also wrong: "[multi buy 2 for $1.50 — $0.75/ea]"
  (bundle total shown as the per-unit rate, then halved again).

### D2. Freshness gate ignored on ingest — expired FB board fully written
- README/spec: "boards with a printed end date in the past are dropped".
- Live: re-ingesting FRUT (valid until Sun 06 Sep; today 08 Sep) wrote
  ALL 24 items with "(till 6 Sep)" stamps + row-2 stamp into the tab.
  Nothing dropped, no warning. (The sweep cleaned it up afterwards.)

### D3. Cross-store add in `map unmatched --add` (shop-flow defect #4 class, still live here)
- Debt entry `Yallamundi Farm Organic Free Range Eggs 12 Pack | 700g
  [coles]` resolved with `--add` while the Coles breaker was open →
  the CLI live-searched WOOLWORTHS, added the WW 800g Jumbo product
  ($15.70, WW price column) and queued a WOOLWORTHS to-do entry [SBM]
  for a COLES debt item. Store attribution silently swapped.
- Evidence: outputs/T4.U05_map_unmatched_--add_Byron_Bay… (actually
  item 2/2 = Yallamundi). Test artifact was fully undone (row deleted,
  SBM removed) — the defect itself is NOT fixed.

### D4. Word-order-insensitive dedup FAILS in Local_Deals ingest
- README: "Equivalent in-domain items share one row
  (word-order-insensitive, variety-aware)".
- Live: post said "5kg Bag Washed Potatoes" while the tab row was
  "Washed Potatoes 5kg Bag" → ingest APPENDED a second row (135)
  instead of merging into row 118.

### D5. `compare` silently prices a nonsense query from a one-word partial match
- `compare --items "xyzzy plugh quantum banana 999"` matched the sheet row
  "Banana Kids 5" (matched via the single word "banana") and presented it
  as the junk item's price. The partial-match chain is too loose — a query
  sharing ZERO meaningful words (or one generic word) must not be priced
  silently. Same family, user-reported 2026-09-08: a **sugar** query
  answered with the **V Sugarfree / Red Bull Sugar Free** drink rows
  (substring crossing — "sugar" ⊂ "sugarfree"; the boundary guard exists
  in the subcategory classifier but NOT in lookup candidate scoring).
- → FIX-6/FIX-7 in the spec.

### D6. UOM 20% size gate bypassed on a sheet+live pair (60g vs 110g)
- Row "Sunbites Sour 60g" (WW GONE → WW side live) was paired with the
  live "Sunbites Biscuit Crackers Share Pack Sour Cream & Chives 110g"
  and compared against the Coles 60g sheet price — 60g vs 110g is way
  outside the 20% band; the pair should have been rejected as
  non-comparable. Evidence: outputs/T1.V09.

### D7. Halal chain never engages on the compare path
- `compare --items "chicken breast"` (a raw-meat term) answered with
  "Jumpy's Chicken Multipack" (sub-category `chicken chips` — a potato
  snack). No halal-scoped sheet view, no live halal tier, no
  "not available this week". Zero halal-marked meat rows exist on the
  sheet, so a halal user gets potato chips as the chicken answer.

## P2 defects (loopholes / misleading)

### D8. `wednesday --dry-run` rewrites `data/unmatched.txt`
- Dry run prints "no sheet write, no scp, no Telegram" and preserves
  wool/coles missing files, but REPLACED unmatched.txt (accumulated
  39-line debt → this week's 2 lines; mtime = dry-run time). Mid-week
  dry runs destroy the debt list state (recoverable via git).
- Evidence: outputs/T3_wednesday_dryrun.txt + git diff.

### D9. Map work-lists are stale snapshots; `lists` computes live — counts disagree
- `map coles` resolves data/coles_missing.txt (8 items, file dated
  Sep 4) while `lists` reports "Coles missing — 23" from a live sheet
  read. 15 live-missing rows can never be resolved through the map
  flow until next Wednesday regenerates the file.

### D10. Mid-week to-do queue divergence local ↔ VPS (two queues)
- Local add_to_list.json = {ESQ, NJL, DSF, AVE}; VPS copy = {NLG, JKS,
  KSY, ELF, XTD, TPJ} (Sep 6-7 Telegram sessions). Step-0 union merge
  only runs at Wednesday, so Telegram answers and local answers show
  DIFFERENT to-do lists all week (proven live: TG to-do ≠ local to-do).
- Related: skipped map items make `--next` print "All N items resolved"
  although the debt file is untouched and nothing was resolved (wording).

### D11. Stale shop-tagged comments survive newer posts in Local_Deals
- Carrots row kept "[FRU] [multi buy 2 for $1.50 — $0.75/ea]" (from the
  expired post, itself double-divided per D1) after two newer posts
  re-priced the item without any promo. "Newest post wins" applies to
  the price cell but not to the comments segment.
- **USER REQUIREMENT (2026-09-09):** when a special price is removed or
  expires, its comment must be removed with it — comments are never
  allowed to outlive their prices. → FIX-4 in the spec.

### D12. Orphaned row-2 validity stamp
- Fruitopia row 2 said "valid until Sat 12 Sep" while ZERO Fruitopia
  special cells existed (all swept 6 Sep). A human reading the tab sees
  validity that no longer exists. (Cleaned incidentally by the D2
  re-ingest + sweep during this test round.)

### D13. Coles live search fails silently → breaker masks it
- T2: 13 Coles searches OK, then 3 consecutive silent failures
  (S15 tuna, S16 red bull, S17 200-char — no stderr diagnostics at
  all by design "3-attempt silent retry"); user-facing line is only
  "⚠️ Coles not checked (unavailable)" — no reason, no retry time.
  Breaker then open 10 min. data/scrapedo_health.json showed
  fail_streak 3 at 08:15.

### D14. ~~Pre-existing duplicate product rows on the master sheet~~ — RETRACTED by the user (2026-09-09)
- The user checked the flagged pairs (Organic Free Range Eggs / "Eggs Free
  Rage", the two Sunbites multipacks, the two V Watermelon rows) — they
  are SEPARATE products, not duplicates. Do NOT merge them; do not let any
  future matcher auto-merge them either (they survive as known-distinct).
- Remaining footnote only: confirm the `Home` brand flag on row 14 is
  intentional (it drives the home-brand display discount). No code change.

### D15. Multi-buy M/N vocabulary never upgraded on the sheet
- Every multi-buy row (11, 19, 21, 28, 31, 33, 34, 42, 44, 53, 67, 68,
  69, 75) still carries the bare legacy `multi-buy` marker, no
  "multi-buy 2/$X" terms → the deal-rate price-cell rule cannot do
  anything and compare shows no 🏷️ deal note. README says the next sync
  that sees the item refreshes bare markers — none has since Sep 4.

### D16. Add-path anomalies at volume: phantom "already tracked" refusals + rows that write anyway
- In the 387-add battery, 3 adds were refused with
  `already tracked (row N: 'ZZT8 0…')` where N was the very row the
  refused item itself should occupy — and the sheet ended with exactly
  387 rows for 384 successful adds, i.e. the refused adds' rows EXISTED
  anyway. Same pattern in run 3: "196/197 added" yet 198 rows found.
- A controlled probe (0001/0002 widget names, differing only by number)
  did NOT reproduce it — both added cleanly as separate rows — so the
  trigger is intermittent (suspect: add_product_row's exact-guard
  running against a sheet state that already contains the row being
  written, e.g. a re-entrant read inside the same call). Needs code
  inspection; this is the plausible class behind the user's
  "too many errors" when adding products.
- Refinement of the earlier numeric-collision theory: bare numbers do
  NOT merge (probe proven); the v2 refusals were exact-guard hits, not
  similarity merges.

### D17. Word-order/lowercase variants hit the exact-guard refusal, not the documented merge
- 30 variants of real rows (word-reorder / lowercase) added via
  add_product_row: ~13 merged correctly (price+alias, reverted in test),
  17 were REFUSED `wrote=False merged=False` (exact-guard treats the
  reorder as the same name) — no price update, no alias append. Safe
  (never a dup row) but the documented one-line-rule merge semantics
  don't fire for reorder forms; behavior depends on which guard sees
  the name first.

## P3 / robustness observations (added during T8)

- R1. Injection-style search string ("'; DROP TABLE products; --") →
  Woolworths API 403 after retry, 188.8s wall time, then everything
  WW-side down for subsequent calls; no crash, clean error. Slow-fail.
- R2. `specials --store coles` still prints the WOOLWORTHS specials
  section above the Coles view.
- R3. `map unmatched --next` live-searches obvious paste-junk BEFORE
  the user chooses forget — burns Coles credits + ~46s per junk item.
- R4. missed-pricing numbering has gaps inside store groups (1,2,4
  under WW when 3 belongs to Coles) — deterministic but confusing.
- R5. `--post-log <CODE>` resolves the code to the SHOP and prints the
  whole shop history ("81 post(s) on record") — the specific code is
  not isolated.
- R6. `--set-special` accepts a PAST `--till` date silently (wrote
  "till 5 Sep" on Sep 8); only the sweep cleans it up later.
- R7. Row deletion shifts all rows below (two-strike/purge/gone
  paths delete by index); any concurrent index-based state (map
  progress, .txt snapshots) goes stale — verified live during the
  purge/restore incident.
- R8. Empty `compare --items ""` prints an empty basket (rc=0) instead
  of a usage error; `search --product ""` correctly errors (rc=1).
- R9. `live-refresh` is NOT dead when invoked directly: it ran a full
  headed pipeline (opened Chrome, attempted WW login + queue flush of
  the real to-do entries, list fetch) for 191.5s before failing on
  missing credentials. Queue state was NOT mutated (login failed), but
  with valid session state it would act — the only guard is "the agent
  never runs this".
- R10. NA-marker subset: 3 of 33 `mark_not_available` calls reported
  wrote=True but the cell was not "NA" on read-back (30/33 verified).
  Intermittent, matches the D16 add-path anomaly family.
- R11. Stale shop session: `shop --status` resumes a run from
  2026-09-07 ("beef mince: ask_live") — 24h-window residue, no cleanup.
- R12. Google-Sheets quota fragility (found by the 500-item battery):
  no 429 retry/backoff anywhere in core; EVERY add/update re-reads the
  entire sheet (dup-guard/matching) → ~4s per op at 113 rows and a hard
  quota ceiling around 50 writes/min. Both battery crashes were 429s
  (write quota during concurrent batteries; read quota during subset
  verification). Bulk operations (week-scale ingests, backfills) will
  hit this as the sheet grows.

## Incident during testing (disclosed, restored)

- `missed-pricing --purge` (T4.M12) deleted the REAL delete-pending row
  112 "Mozzarella Cheese Sticks 235g 10 Pack". This was a test-command
  targeting error (the purge acts on ALL delete-pending rows; my ZZTEST
  fixture wasn't in the list yet). The row was RESTORED from
  deleted_rows.json within 3 minutes (insert at 112, values verified);
  the pipeline itself worked exactly as documented (archive → restore).
  Lesson recorded: never fire `--purge` outside a real user request.
- T4.X04 `map coles --na` stamped NA on real row 44 (Jumpy's Chicken
  Multipack) because the fake test line sat at the END of the file, not
  position 2. Restored (E44=4, J44 empty) immediately. H44 (timestamp)
  now shows 2026-09-08 — only residue.
