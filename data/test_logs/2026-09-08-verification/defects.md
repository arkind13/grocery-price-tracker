# DEFECT LOG — 2026-09-08 verification round (Round B, retest of the 09-09 fixes)

Verification-only round: NOTHING was fixed. Every verdict below is backed
by a receipt in `outputs/` (S1.* = §1 per-defect checks; T1/T2/T3/T4 =
battery re-runs; t8 logs = the 500-item battery).

Baseline: `baselines/` (sheet_snapshot.json = Products_Master grid taken
14:41…13:41 local, local_deals_tab.json, 28 data state files + hashes).
Live pre-round state: 113 product rows; to-do 4; unmatched 2 debt lines
(both [coles]); missed-pricing 5 (4 fixable · 1 delete-pending).

## New defects (D19+, continuing the baseline numbering; D18 = Round A's
## registered suspicion, judged below)

### D19. `compare --items "sugar"` still auto-answers a ZERO-SUGAR energy drink — via the Col P alias path, which bypasses the new guards entirely
- Live: `compare --items "sugar"` → priced "V Zero 250 Ml" $2.52/$2.65
  in TOTALS (outputs/S1.V04). The sheet also holds "Raw Sugar 3Kg"
  (row 47) + "RAW SUGAR 2KG" (row 90) — the right answers.
- Mechanism (reproduced offline): `LookupEngine.find_product('sugar',
  interactive=False)` → status KEYWORD_ALIAS, row_index 30
  ("V Zero 250 Ml"), note "Col P token match". Row 30's Col P alias is
  "V Energy Zero Sugar Original | 250mL" — the FULL TOKEN "sugar"
  lives in the alias. The keyword/alias short-circuit fires BEFORE
  candidate scoring, so FIX-6's AUTO_PICK_MIN_SCORE floor and the
  substring boundary guard ("sugar" ⊂ "sugarfree") never engage. The
  guard as shipped cannot catch "Zero Sugar" (token is whole, negation
  is a different word).
- The FIX-6 acceptance ("sugar → RAW SUGAR rows or a question — NEVER
  Red Bull Sugar Free / V Sugarfree [class]") is violated; the fixer's
  regression test used the literal row names "V Sugarfree 4*250" /
  "Red Bull Sugar Free" and missed the alias-token route.
- Severity P1 (wrong answer, user-confirmed class).

### D20. Blank-cell live fill pairs a DIFFERENT product when sizes are within 20% — same-product check applied to GONE cells only
- Live: `compare --items "Lindt Hot Choc Flakes Tin 210g"` (row 114:
  Coles $14.00 sheet, WW cell BLANK — not GONE) → WW side live-filled
  with "Lindt Lindor Assorted Chocolate Gift Box 235g" $17.10 (was
  $30.00) and the pair was presented as a normal comparison with
  totals + "Cheapest: Coles — you save $3.10" (outputs/S1.V02).
- `name_matcher.is_same_product("Lindt Hot Choc Flakes Tin 210g",
  "Lindt Lindor Assorted Chocolate Gift Box 235g")` → **False**
  (verified offline), i.e. the project's own matcher says DIFFERENT
  product; only the 210g-vs-235g size gate (11.9% < 20%) passed.
- FIX-1 shipped GONE=strict (same-product required) but blank-cell
  fill = size-gate only (fixer's own test list: "blank-cell fill still
  size-gated"). Spec intent ("never silently substitute a different
  size/product") + retest-plan regression row (same-product live hit
  expected) imply blank cells need the same-product rule too.
- Severity P1 (silent wrong-product pricing; D6/D5 family).

### D21. `--expire-sweep` deletes the store's row-2 validity stamp even when LIVE specials of that store remain
- Live: baseline held a real, future-dated Merjan special (row 104
  "Lamb Curry", col E "27.99 (till 11 Sep)") + row-2 stamp "valid until
  Fri 11 Sep". After `local-deals --set-special merjan "beef mince"
  8.99/kg --till "5 September"` + `--expire-sweep`: the expired crafted
  pair (price+comment) was correctly removed, but the Merjan row-2
  stamp was ALSO removed while row 104's live special survived
  (outputs/S1.F04, S1.F05; cell reads R2C5 and R104C5).
- A human reading row 2 now sees NO Merjan validity while a live
  Merjan special exists — D12's orphan-stamp rule inverted (stamp is
  now the thing missing). Sweep should re-derive the stamp from the
  store's remaining live specials (or leave it untouched).
- Severity P2 (misleading metadata on the tab; restored in this round).

## R-observations (R13+, continuing R1–R12)

### R13. The OFFLINE pytest suite writes to REAL state files (test-isolation leak)
- Proven by controlled runs: `pytest tests/ -q` (1250 passed) mutated:
  - `data/unmapped_queue.json` — fixture entries ("Anything At All",
    "Totally Unknown Product 999g", "Woolworths Beef Mince 500g",
    "Some Random New Product 200g") re-bumped (count +1, new
    last_seen). mtime changed during BOTH full-suite runs; single-module
    `tests/test_cli.py` run did NOT touch it.
  - `data/local_deals_post_log.json` — +10 fixture post entries
    (FRUT/FRU0709260907, files board.txt/new_post.txt/old_post.txt)
    stamped at pytest-run time.
  - `data/item_code_registry.json` — +8 item codes (BXZ, AUJ, MWF, ADZ,
    …) burned with `row: 2, sheet: ''` at pytest-run times.
- Mechanism: `NameMatcher.match` (core/name_matcher.py:298) calls
  `append_unmatched` on every miss; several test_name_matcher tests
  (5/6/11/12) match unknown items without patching QUEUE_PATH; post-log
  and code-registry writes have the same non-isolated callers.
- Consequence: every full-suite run pollutes live debt-queue counts,
  burns item codes, and adds fake post-log rows the user sees via
  `local-deals --post-log`. All three files were restored from baseline.

### R14. `local-deals --set-special --note` mangles `$<digit>` in the note
- `--note "multi buy 2 for $15"` wrote cell comment "[MER] multi buy 2
  for 5" — "$1" consumed as a replacement-group reference (outputs/
  S1.F04). Likely `re.sub`-style substitution on the note string.
- The 09-08 round's T7.P02 receipt did not capture the cell, so
  pre-existing-vs-new is UNDETERMINED (the FIX-4 commits touch
  comment-expiry, probably not the note writer).

### R15. add_product_row hits the sheet GRID CEILING at volume with an opaque crash (T8 run 1)
- The Products_Master grid was capped at **381 rows**. T8 run 1 wrote
  380/387 synthetic adds, then died on add #381:
  `APIError: [400]: Range (Products_Master!A382:S382) exceeds grid
  limits. Max rows: 381` (t8_run.crashed-run1.log). No graceful
  message/handling — a bulk ingest of ~270 new products in one week
  would hit the same wall mid-write.
- The 500-item battery was only possible after expanding the grid
  (530 rows) for the run; grid size restored to 381 at teardown.
- Stranded rows of the crashed run were cleaned (267 contiguous
  ZZT8V rows deleted; 0-drift re-verified).

### R16. retest-plan §7's gspread delete_rows formula is STALE for gspread 6.2.1
- Plan says: 1-based inclusive a..b = `ws.delete_rows(a - 1, b)`
  ("0-based half-open"). Installed gspread is 6.2.1, whose
  `delete_rows(start_index, end_index=None)` doc reads "Delete rows 5
  to 10 (inclusive)".
- INCIDENT during FIX-5 cleanup (disclosed, repaired): deleting the
  Yallamundi test row 115 with `delete_rows(114, 115)` (the plan's
  formula for a=b=115) deleted rows 114 AND 115 — i.e. the REAL row 114
  "Lindt Hot Choc Flakes Tin 210g" went with it. Repaired within
  minutes from baselines/sheet_snapshot.json (7 cells rewritten + E114
  number-format re-pinned); Products_Master re-verified 0 drift vs
  baseline. Same class as the 09-08 round's R7 watch (index-based ops
  vs shifting rows).

### D22. Word-order variant STILL appends instead of merging when the reorder breaks the size-suffix pattern (D17 family residue)
- T8 run 3 Phase B: variant "pack Evamay Pads With Wings Super 14"
  (word-reorder of real row 23 "Evamay Pads With Wings Super 14 pack")
  → wrote=True, merged=None → a NEW row 115 was appended with the
  Coles price 10.0 (ops log line `B | pack Evamay… | EXPECTED merge |
  wrote=True merged=None`; cell reads in t8_run3.log window).
- The other 29 variants behaved per contract: 18 true reorders/
  lowercases MERGED (price+alias, reverted), 11 identity-shaped
  variants (whitespace no-ops / single-word "reorders") were correctly
  refused by the exact-guard (exact means exact).
- Likely cause: the merge key is size/variety-aware and the reorder
  moves "pack" away from "14", so the size parse ("14 Pk") no longer
  matches and the row counts as a different product. Token-set equality
  alone is not sufficient in the add path.
- Artifact deleted; 0 drift re-verified. Severity P2 (silent dup rows —
  the exact user complaint class).

## D18 / D13-R / Round-B watch — judged

- **D18 (compare writes on meat terms) — CONFIRMED 2026-09-08 14:39.**
  Round A's suspicion is REAL and reproduced live:
  `compare --items "halal chicken mince"` (T1.V10, a READ-only-surface
  command) AUTO-ADDED sheet row 115 "Zwan Luncheon Meat Halal Chicken
  850g" — WW price $10.70 captured, aliases "chicken breast|halal",
  timestamp col H = 14:39:xx = exactly the T1.V10 run window (grid was
  0-drift at 13:57 and the row existed by 14:41). No to-do entry was
  queued (row-only add). This contradicts the documented compare
  contract "compare | Never writes" (PROJECT-MAP §commands).
  First probe (`compare --items "chicken breast"`, S1.V03) did NOT add
  (two live candidates, no unique LLM-confirmed add) — the tier-2
  auto-add fires only on a unique confirmed candidate; "halal chicken
  mince" had one (Zwan). Artifacts fully undone (row deleted,
  registry/queue files restored; 0 drift re-verified).
  → USER DECISION NEEDED: accept + document, or make compare's halal
  chain render-only (report the candidate, never auto-add).
- **D13-R (silent Coles failure in map flows) — CONFIRMED, and now
  proven on the `map unmatched --add` path too:** with the Scrape.do
  breaker forced open, `map unmatched --add` printed "No live search
  results found for 'Yallamundi…'. Use --skip or --forget." on stdout
  — indistinguishable from genuinely-not-listed — with the breaker
  line only on STDERR (outputs/S1.M03). The FIX-5 spec message
  ("⚠️ Coles unavailable right now — item left on the list…") is absent
  → this is why FIX-5 is judged PARTIAL.
- **Round-B watch (negation guard over-blocking):** `compare --items
  "milk"` still auto-prices "Full Cream Milk 3L" both stores
  (outputs/S1.V08) — no over-blocking on the plain query. Not tested
  exhaustively beyond that.

## FIX-9 volume battery / FIX-10 — see t8 logs (§7) — results recorded in
## the verification report.
