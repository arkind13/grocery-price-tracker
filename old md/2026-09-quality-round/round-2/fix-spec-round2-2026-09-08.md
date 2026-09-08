# FIX SPEC — ROUND 2 — 2026-09-08 — scope: exactly the verification round's 11 items

Source of truth: `data/test_logs/2026-09-08-verification/verification-report-2026-09-08.md`
(evidence per item) and `data/test_logs/2026-09-08-verification/defects.md`.
Round 1 spec (`fix-spec-2026-09-09.md`) is DONE — do not reopen it.

## Hard rules (stricter than round 1 — these stop the loop)
1. **Scope = R2-1…R2-11 below. Nothing else.** No refactors, no drive-by
   fixes, no touching still-open no-FIX-ID items (D9, D12-scenario, D15,
   R1–R8 etc.) — those are awaiting user triage, not code.
2. **No undocumented behavior changes.** If a fix unavoidably changes a
   documented contract (e.g. "compare never writes"), you must either (a)
   implement the option this spec names, or (b) STOP and list it under
   BEHAVIOR CHANGES in your report. Do not update an existing test to a
   new contract unless this spec says that contract changed — and then
   list it. Round 1 quietly updated 7 tests; this round every such edit
   must be named and justified.
3. Every fix ships its regression test; keep pytest green
   (baseline now 1250).
4. Live sheet discipline: single writer, ≥1.3s throttle, no bulk runs
   without the grid headroom check (see R2-11), restore state after any
   destructive step. But remember: **live verification belongs to the
   next Round B** — you only need offline tests + read-only sanity.
5. Deliverable: `fix-round-report-2-<date>.md`, one line per R2 ID:
   `R2-<n> | DONE/PARTIAL/SKIPPED | proof = <tests + result> | behavior changes: <none or list>`.

---

## R2-1 (D19, P1): Col P alias path bypasses the new guards — "sugar" answers "V Zero"
**Root cause (proven in verification):** the KEYWORD_ALIAS short-circuit
in the lookup engine fires on a full-token alias match ("…Zero **Sugar**
Original…" contains the token "sugar") BEFORE the round-1
AUTO_PICK_MIN_SCORE / negation / boundary guards, which only catch
substring crossings. Evidence: outputs/S1.V04; offline repro
find_product('sugar') → row 30 via "Col P token match"; RAW SUGAR rows 47
and 90 exist and should win or the query should ask.

**Fix:** route the alias path through the same guards as partial matches:
an alias may auto-answer only if it does not contain a negation/qualifier
token that the query lacks ("sugarfree", "zero", "no sugar", "sugar
free", "diet", "lactose free", …) — reuse/extend the round-1 negation
list so it is ONE list in one place. Substring guard stays.
**Accept:** `compare --items "sugar"` never prices V Zero / Red Bull
Sugar Free; RAW SUGAR rows or an interactive ask. Regression: alias-path
test with the real sheet names; "coke zero" for query "zero sugar coke"
must STILL match (negation on the QUERY side must not block its own
product — think through directionality).

## R2-2 (D20, P1): blank-cell live fill pairs a different product within the size band
**Root cause:** live fill for an EMPTY price cell only ran the 20% size
gate; `is_same_product` was made mandatory for GONE cells (round 1) but
not blank cells. Evidence: outputs/S1.V02 — "Lindt Hot Choc Flakes Tin
210g" (WW blank) live-filled "Lindt Lindor Assorted Gift Box 235g" and
declared "save $3.10".

**Fix:** blank-cell live fill requires `is_same_product` == True AND the
UOM gate — identical rule to GONE cells. One shared helper so the two
paths cannot drift again.
**Accept:** the Lindt scenario renders no live pair (honest missing-at-WW
block); a genuine same-product fill still works. Regression tests for
both cells states via one parametrized test.

## R2-3 (D22, P1): reorder that moves the size token defeats the merge key
**Root cause:** the one-line-rule size parse assumes the size suffix
pattern; moving it ("Super 14 Pack" → "Pack … Super 14") breaks the parse
so `is_same_product` says False and `add_product_row` appended a
duplicate row. Evidence: t8 run 3, 1 of 18 variants (outputs in
t8_ops_log.csv).

**Fix:** make the size extraction order-independent (scan tokens for a
size pattern anywhere in the name), not suffix-position-based. Keep the
20% same-unit rule and the exact-refusal behavior unchanged.
**Accept:** "Pack Evamay Pads With Wings Super 14" merges into the
canonical row; exact-dup still refused; round-1's 18-variant battery
still merges 18/18 in the offline test.

## R2-4 (D3-residue + D13-R + D13): honest unavailable-store messaging, all paths
**Root cause (three proven surfaces):** (a) `map unmatched --add` with a
breaker-open store prints "No live search results found … Use --skip or
--forget" — indistinguishable from not-listed (correct refusal, wrong
message); (b) `_search_store_with_fallback` (map wool/coles) prints "No
coles results found" for breaker-open too; (c) plain `search` shows only
"Coles not checked (unavailable)" with no reason or retry time.
**Fix:** one helper that turns scrapedo_health / HTTP failure state into a
stdout line: "⚠️ Coles unavailable (breaker open until HH:MM / N failed
attempts) — nothing written, item left on the list." Use it in all three
surfaces. Never print "no results" when the store was unreachable.
**Accept:** force the breaker (craft scrapedo_health.json), run each
surface, see the reason + retry time on stdout; healthy-store behavior
unchanged. Regression tests with a fake health file.

## R2-5 (D8-residue): the dry run still writes `data/unmapped_queue.json`
**Root cause:** `NameMatcher.match → append_unmatched`
(core/name_matcher.py:298) is called during the parse step regardless of
dry_run; the round-1 gate covered unmatched.txt but not the queue file.
Proven: it was the ONLY file that changed in the clean dry-run pass
(count/last_seen bumps on debt + docx-junk entries).
**Fix:** thread dry_run into append_unmatched (or buffer and discard);
then AUDIT the whole wednesday parse→sync path for any other state write
not gated (round 1's audit missed this one — do it by grepping every
open/write call under the wednesday flow, and add a test that runs the
dry run against a temp data dir and asserts the FULL directory hash is
unchanged — round 1's test only hashed some files).
**Accept:** dry run leaves every byte of `data/` untouched (the §4 hash
check becomes the regression test).

## R2-6 (D21, P2): expire-sweep deletes a store's row-2 stamp while live specials remain
**Root cause:** the sweep removes expired special cells and unconditionally
clears the store's row-2 "valid until" summary stamp, even when that store
still has unexpired specials elsewhere (Merjan: row 104 till 11 Sep
survived, stamp deleted).
**Fix:** after removing expired cells, RE-DERIVE row 2 from the store's
remaining live special cells (max remaining till date); delete the stamp
only when NO live specials remain.
**Accept:** Merjan scenario keeps "valid until Fri 11 Sep" after sweeping
an unrelated expired cell; a store with zero remaining specials loses its
stamp. Regression tests for both.

## R2-7 (D18 — implement the DEFAULT; user decision pending)
**Contract conflict:** compare now auto-adds a row via the halal tier-2
(LLM-confirmed single candidate) — proven live (Zwan row written by
`compare "halal chicken mince"`), violating "compare | Never writes".
**Default fix (contract wins):** compare/recipe paths get the halal chain
RENDER-ONLY — display the resolution (butcher line / honest note / sheet
answer) but never auto-add; auto-add remains exclusive to explicit flows
(shop, search --add-item, map --add). Implement by passing a
`allow_auto_add=False` flag down the halal resolution when invoked from
compare/recipe.
**Accept:** `compare --items "halal chicken mince"` writes NOTHING (sheet
row count + queue byte-identical), still renders the butcher/honest
line. Regression test asserts no write. Flag prominently in your report
that the user can flip this to "accept + document" later.

## R2-8 (R13, P2): pytest pollutes real state files
**Root cause:** several tests call NameMatcher.match → append_unmatched,
local-deals post-log, and item_code_registry against the REAL data dir;
a full suite run bumps live files (proven by controlled runs).
**Fix:** a conftest fixture that points every state path (unmapped_queue,
post log, item code registry, search_last_results) at a tmp dir for the
whole suite; assert in teardown that the real data dir is untouched.
**Accept:** run the full suite, then verify the 4 named files are
byte-identical to pre-run.

## R2-9 (R16, P2): stale gspread guidance in the retest plan
**Fix:** update retest-plan §7 to gspread 6.2.1 semantics (delete_rows is
1-based INCLUSIVE-INCLUSIVE per the verification round's calibration;
single-row `delete_rows(115, 115)` and `delete_rows(115)` both correct).
Doc-only change.

## R2-10 (R14, P3): `--set-special --note` eats `$<digit>`
**Root cause:** the note is passed through `re.sub` as a replacement
string, so `$1`-style groups are interpreted ("multi buy 2 for $15" →
"…2 for 5").
**Fix:** escape the replacement (`re.sub(..., note.replace("\\", "\\\\")
... )` or use a lambda replacement) everywhere user text feeds re.sub.
**Accept:** the note lands verbatim; regression test with "$15" and "$2x".

## R2-11 (R17, P2): opaque grid-ceiling crash on bulk adds
**Root cause:** Products_Master's grid maxes at its last row; the 381st
add threw `APIError [400] exceeds grid limits` mid-bulk with no handler.
**Fix:** in add_product_row, when the append row would reach the sheet's
grid limit, expand the grid first (or pre-flight the remaining headroom
and raise a clear, actionable error naming the limit) — never a raw 400
mid-run. Both acceptable; expanding silently is friendlier for bulk
ingests.
**Accept:** offline test with a maxed fake grid → clean expansion or the
clear error; no raw APIError escapes.

---

## ROUND-2 EXTENSION (added 2026-09-09, user request): the 8 Round-A deferrals

The first fixer listed 8 findings as out of scope. Coverage now: two were
already folded in (D13-R → R2-4, D18 → R2-7). The remaining fixable six
become R2-12…R2-16 below. One item (D10, the local↔VPS to-do queue
divergence) is deliberately NOT a code fix: the queues converge by design
at Wednesday Step 0 — it stays documented. The negligible quota note
(read-back adds one read per add) needs no action.

### R2-12 (R2-observation, P3): `specials --store coles` leaks the Woolworths section
**Evidence:** outputs/T1.A03 — the WW specials report prints above the
Coles sheet view even with `--store coles`.
**Fix:** apply the store filter to every section of the specials output
(the saved Wednesday report section included).
**Accept:** `--store coles` shows only Coles content; `--store
woolworths` only Woolworths; no store flag = both as today. Regression
test on the renderer.

### R2-13 (R3, P2): `map unmatched --next` live-searches junk before the user can `--forget`
**Impact:** every junk debt line burns Coles credits + ~46s before the
user even answers (outputs/T4.F01: 46.1s for obvious paste junk).
**Fix:** make the live search LAZY in the unmatched session: `--next`
shows the sheet recommendations + the debt line WITHOUT hitting the
stores; live search runs only when the chosen action needs it
(`--add`, or `--pick` when the debt carries no price). Interactive
prompt updated to say "live search runs when you choose an action".
Aldi-tagged lines already skip live search — keep that.
**Accept:** with the breaker forced open, `--next` still renders
recommendations and `--forget`/`--skip` cost ~0s and 0 credits; `--add`
on a healthy store works exactly as R2-4 specifies. Regression tests on
the session flow with a fake store client.

### R2-14 (R8, P3): empty `compare --items ""` returns rc=0 with an empty basket
**Fix:** usage error rc=2 with "provide --items" (mirroring `search
--product ""` which already errors cleanly).
**Accept:** rc=2, no basket header printed. Regression test.

### R2-15 (D15, P2): bare legacy `multi-buy` markers are never upgraded to terms
**Evidence:** every multi-buy row on the sheet (14 rows) still carries
the bare `multi-buy` marker with no "2/$X" terms, so no deal-rate or
🏷️ note can ever render (verification T1.V09).
**Fix:** when a sync/specials pass sees a keyword-matched row whose
specials cell is the BARE `multi-buy` marker AND the store payload
carries deal terms for it, write the full terms form (`multi-buy 2/$6.00`
— `encode_multibuy_cell` already exists in core/multibuy.py). When no
terms are known, leave the bare marker but list the row once in the
Wednesday summary under "multi-buy rows awaiting deal terms" so the gap
is visible instead of silent.
**Accept:** offline test: row with bare marker + payload with terms →
cell upgraded, deal rate applies on the next price write; no terms →
summary line, marker untouched. Existing specials-vocabulary tests stay
green.

### R2-16 (D9, P2): map sessions resolve a stale snapshot while `lists` reports live
**Evidence:** verification T4.X01 — `map coles --next` walks an 8-item
Sep-4 file while live `lists` reports 24; the other 16 can never be
resolved via map until a Wednesday rebuild.
**Fix:** when a `map wool|coles` session starts, REBUILD the work list
from the live sheet state (rows whose opposite-store keyword is missing,
same rule `lists` uses) instead of trusting the .txt file — or merge
file + live and de-duplicate, preserving session progress by item
identity, not line number. Wednesday continues to write the files as
the offline record.
**Accept:** start a map coles session → its item count equals the live
`lists` count; resolving an item removes it from BOTH the session and
the file; a second session start shows the reduced set. Regression test
with a stale fixture file + a sheet that has more missing-keyword rows.
