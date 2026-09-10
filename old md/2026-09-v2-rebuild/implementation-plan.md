# Implementation Plan — v2 Round 5 (FINAL): non-halal twin line + speed budget + FINAL TIDY

- **Date:** 2026-09-10 · **Stage:** 02 Plan → 03 Code → 04 Checker
- **Inputs (read in the mandated order):** `test.md` §"USER VERDICT on
  the three live phrasing tests (2026-09-10)" + the carry-forward
  block (USER'S BINDING VERDICTS — highest authority, quoted verbatim
  in the compliance table), `architecture-spec.md` (v2 + §18 A1–A4 +
  §16 CRITICAL INFRASTRUCTURE), `rebuild-plan.md` (Round 5 scope),
  Round-4 close (599 green / 0 skipped, 8 verbs, checker PASS, live
  Wednesday fire USER-DEFERRED at the freshness gate).
- **Divergence check (mandatory):** §18 A4 vs test.md — **no
  divergence found** on any binding point (fix location, display-only
  line + exact format, blank-halal independence, Q11, no-new-state,
  local-never-non-halal, "non halal" resolution, beef-mince fixture).
  ONE ambiguity flagged, not silent: test.md's example line shows the
  RAW `$15.00` for D=15, while spec §7/§14 discount EVERY Woolworths
  price displayed to the user (verdict 2's approved answer showed the
  discounted $12.34 for D=12.99). **Work order implements the twin
  line through the EXISTING display-discount engine** (consistency);
  if the user meant raw, it is a one-token change in `render_lookup` —
  ruled at approval, below.
- **SCOPE GUARD:** Round 5 ONLY — the FINAL round. No new verbs, no
  new state files, no live-search fallback, no sheet-structure
  changes, no provider additions (Aldi/Amazon is a FUTURE session per
  §15). M-items R5-M1…M5 are BINDING and may not be dropped, merged,
  weakened, deferred, or reinterpreted. **On any contradiction with
  the spec: STOP and report.**
- **Rule:** this file is overwritten in place each round (then
  archived by FT2 — the last act of this round).

## 0. Ground truth (R4 close + the live-proven gap)

| Fact | Consequence |
|------|-------------|
| `price --item "beef mince"`, `"halal beef mince"`, and the exact plain name ALL return the halal-scoped answer only; the priced plain row `Woolworths Beef Mince 500g` [GJZ] D=15 G=filled (master row 139) is unreachable — PROVEN live (test.md Evidence; root cause: `v2_read.lookup_item` meat gate + `halal.is_meat_term`) | The fix lives in `core/v2_read.lookup_item` (twin read) + `render_lookup` (display) — skill/routing alone is PROVEN insufficient (test.md fix-location note) |
| Fixture rows on the real sheet: row 92 `Halal Beef Mince` [AUG] D blank; row 139 `Woolworths Beef Mince 500g` [GJZ] D=15 | The mandatory regression test uses exactly this fixture; the live acceptance re-runs exactly these three queries |
| Verdict 2 approved pooling: ONE answer = WW halal + locals + winner; verdict 3 approved live search "keep exactly as is" | The twin line JOINS the approved answer shape (M3 three-way); `live` verb untouched |
| 599 tests green / 0 skipped; 8 verbs; parity ALIGNED; twin implementation is display-only read-side code | Suite grows by the twin tests only; parity/Q11 structurally unaffected (no writes exist on the lookup path) |
| R4's timed live Wednesday fire remains USER-DEFERRED (stale docx) | SB1 closes it in THIS round — Round 5 cannot close without the Wednesday budget measured |

## S0 — Backup + canary gate (STOP-gate; read-only; NEVER modifies)

```bash
cd "C:/Users/User.DESKTOP-R2G441H/Documents/AI related/grocery-price-tracker"
"$USERPROFILE/anaconda3/python.exe" tools/sheet_backup.py        # exit 0; today's JSON
ssh myvps 'crontab -l'   # 03:17 sheet-backup AND daily-scan present; NO wednesday_reminder
```
STOP on any failure. §16 CRITICAL INFRASTRUCTURE untouched throughout.

## TW1 — (R5-M1, R5-M3) Non-halal twin READ in `lookup_item`

**File:** `grocery-price-tracker/core/v2_read.py` — inside
`lookup_item(query, master_rows, ld_rows)`, AFTER the existing halal
resolution, add the twin read:

```python
def _non_halal_twin(query: str, master_rows: list) -> list[dict]:
    """Plain (non-halal) Woolworths master rows matching a MEAT query.

    Match rule (binding): strip the tokens 'halal'/'non'/'and' from
    the query; a plain DOMAIN row matches iff its normalized name
    contains EVERY remaining query token (word-boundary-safe — the
    subcategory.py discipline), its name does NOT contain 'halal',
    and it is not the halal row already answering. Returns [{'name',
    'state': 'priced'|'gone'|'na', 'value': float|str|None}] — the
    row set the RENDERER shows; no other consumer exists.
    """
```
- Result dict gains `result['non_halal_twins'] = _non_halal_twin(...)`
  — populated for EVERY meat-term query shape: the halal name, the
  plain meat term, AND the exact plain-row name (test.md: all three).
- **Independence (M1):** the twin read runs off `master_rows` only and
  does NOT consult the halal row's D — the twin line appears even when
  the halal row's price cell is blank (constraint 3 verbatim).
- Local_Deals is NEVER consulted by the twin read (M2 — structural:
  locals are always the halal side; §5/Q17).

## TW2 — (R5-M1, R5-M2, R5-M3) Twin DISPLAY in `render_lookup`

**File:** `grocery-price-tracker/core/v2_read.py` — `render_lookup`:
after the local-shop lines and before the footer, one line per twin:

- priced → `also at Woolworths (non-halal): $<price> — <row name>`
  (EXACT format from test.md; `<price>` through the EXISTING WW
  display-discount engine — flagged decision, header above).
- `GONE` → `also at Woolworths (non-halal): GONE — <row name>`.
- `N/A <date>` → `also at Woolworths (non-halal): unavailable
  (N/A <date>) — <row name>`.
- blank-D plain rows: omitted (no price state to show).
With a priced halal row present, the ONE answer carries all three
sides: 🟢 WW halal (discounted) + 🔪 local prices + 🏆 winner + the
twin line (M3; verdict-2 pooling + verdict-1 fix).
The "non halal" phrase needs NO routing change and NO new verb (M4):
the twin line IS the non-halal side of every meat answer — the skill
line (TW4) tells the agent that.

## TW3 — (all M-items) Regression tests — `tests/test_v2_read.py` additions

Mandatory fixture (test.md Evidence, verbatim rows):
`Halal Beef Mince` [AUG] D blank + `Woolworths Beef Mince 500g` [GJZ]
D=15 keyword filled (+ a local LD row for the butcher side).

1. `test_beef_mince_fixture_twin_line_all_three_sides` — **the
   mandatory M1 test.** With AUG D=12.99 (priced case): ONE rendered
   answer asserts 🟢 WW halal $12.34-equivalent (discounted) + local
   butcher lines + 🏆 + the twin line naming GJZ (M3).
2. `test_twin_line_when_halal_price_blank` — AUG D blank: twin line
   STILL present (constraint 3: "must work … when it does not").
3. `test_exact_plain_name_query_carries_twin` — query
   `"Woolworths Beef Mince 500g"` → halal-scoped answer + twin line.
4. `test_non_halal_side_never_local` (M2) — the twin list contains
   ONLY master-row names; every LD price appears only under the
   butcher/local (halal) labels; no local shop name in any twin line.
5. `test_twin_row_states` — GONE / N-A / blank-D plain rows render the
   state lines / are omitted per TW2.
6. `test_lookup_zero_writes_q11_intact` (M4) — deep-copy the fixture
   rows before, run `lookup_item`+`render_lookup`, assert rows
   byte-identical after; the twin path accepts no worksheet handle;
   `grep -n "v2_live" core/v2_read.py` = 0 (no live fallback).
Full suite expectation: **599 + 6 = 605 green, 0 skipped** (report).

## TW4 — (R5-M5) Skill line + doc sync

`claw-skills/grocery-price/SKILL.md`: ONE explanatory line —
"Meat lookups always carry the non-halal Woolworths twin line
(`also at Woolworths (non-halal): $… — <row>`); 'non halal' resolves
ONLY to plain Woolworths master rows — local shops are always the
halal side." Then regenerate `claw-skills/claw_skills_easy.md`
(`python skills_doc.py` + `--check` → OK) and VPS-sync all three
skill files.

## SB1 — Speed budget on LIVE paths (rebuild-plan R5 item 1; any miss = FIX before close)

Timed with elapsed seconds quoted per line (same style as R4):
1. `price --item "beef mince"` — **≤10s** (and must show the twin line).
2. `live --item "chicken breast"` — **≤20s**.
3. `batch --verdicts "<real-code> done"` (verify-only, zero writes) —
   **≤10s**.
4. `list` — **≤5s**.
5. **`wednesday` (the R4-deferred live fire) — ≤30s:** requires FRESH
   `Woolworths.docx` + `Woolworths_Specials.docx` (user pastes — same
   freshness question as R4 W4.1; if the user defers AGAIN, the round
   CANNOT close criterion 1: STOP and report, do not close without
   it). Quote elapsed + both post receipt lines + parity audit after.
A miss on any target is a wrong design choice — fix and re-measure
before close (not a note).

## RG1 — Full regression + live spot checks (rebuild-plan R5 item 2)

1. Offline suite: 605 green / 0 skipped (TW3 count; report actual).
2. Live spot checks: the three beef-mince query shapes from test.md
   Evidence re-run on the REAL sheet (twin line present in all three;
   replies quoted verbatim); `list`; `live`; `specials`; the SB1
   batch; the SB1 Wednesday run.
3. **One REAL inbox ingest** (rebuild-plan item): re-ingest the newest
   existing inbox code's file (`grocery_price_cli.py local-deals
   --ingest <CODE>` — merge is idempotent for the same post; if a
   pending code exists, use it) — verify: butchery items arrive
   `halal`-prefixed, any unmatched item auto-created a blank coded
   master row on BOTH tabs (bottom-append), parity audit ALIGNED
   after.
4. Zero-write proof for the lookup battery: `tools/migrate_v2.py
   audit` ALIGNED before AND after (M4).

## FT1 — (charter) FINAL TIDY — archive every rebuild artifact

1. First append the closed status rows to the round table in
   `rebuild-plan.md` (R5 DONE + line), so the archived copy carries
   the complete history.
2. Move to `old md/2026-09-v2-rebuild/`: `arch-prompt.md`,
   `rebuild-plan.md`, `implementation-plan.md`, and every other
   rebuild-round artifact still in the tracker root (inventory with
   `git status` + root listing; the state-archive/ from R3 already
   lives there).
3. Living docs updated to v2 reality (root keeps ONLY: `README.md`,
   `PROJECT-MAP.md`, `architecture-spec.md` + code/tests/tools/data):
   - `README.md`: v2 rewrite of the tracker sections (8 verbs, parity
     model, the ONE list, Wednesday v2, backup canary, future-provider
     note — which stays); delete v1-only command/queue descriptions.
   - `PROJECT-MAP.md`: same — the plain-language map of the 8 verbs,
     the one list, parity + GONE/done/rename/remove grammar, ingest
     flow, Wednesday rhythm.
   - `architecture-spec.md`: status line → "IMPLEMENTED + CLOSED
     (2026-09-…)"; pointer note to `old md/2026-09-v2-rebuild/`.
4. Root check (grep): no round artifacts left in the tracker root.

## FT2 — Three-way sync close (rebuild-plan R5 item 4)

Tracker commit (core/v2_read.py, tests, docs rewrites, archive moves)
+ push; parent commit (claw-skills ×3, test.md R5 log) + push; scp the
runtime files (`core/v2_read.py` + 3 skill docs) + md5 verify; canary
cron re-checked; final report line: three-way sync status.

## Acceptance criteria (rebuild-plan Round 5 + M-items)

1. Every budget target measured and MET (timed table; Wednesday fire
   included; any miss fixed pre-close).
2. R5-M1…M5 satisfied — verified row-by-row against the compliance
   table by the 04 checker.
3. Suite green, 0 skipped, twin tests present (incl. the mandatory
   beef-mince fixture test).
4. Tracker root holds ONLY living docs (v2-rewritten README +
   PROJECT-MAP + spec with close note); all artifacts archived.
5. Parity audit ALIGNED at close; zero lookup-path writes; three-way
   sync in sync.

## COMPLIANCE TABLE (mandatory — one row per M-item; quotes VERBATIM from test.md)

| M-item | Work-order task # | Regression test name | Verbatim quote from test.md verdicts |
|--------|-------------------|----------------------|---------------------------------------|
| R5-M1 — non-halal twin line (display-only) | TW1 + TW2 | `test_beef_mince_fixture_twin_line_all_three_sides` + `test_twin_line_when_halal_price_blank` + `test_exact_plain_name_query_carries_twin` + `test_twin_row_states` | "the reply must ALSO carry a DISPLAY-ONLY line for the plain (non-halal) Woolworths twin row, e.g. `also at Woolworths (non-halal): $15.00 — Woolworths Beef Mince 500g`"; "it must work both when the halal row already has a Wool price and when it does not (the non-halal side must show immediately — the user should not have to fill the halal row first to see it)" |
| R5-M2 — non-halal resolution rule | TW1 (structural: twin source = master rows only) + TW2 (labels) + TW4 (skill line) | `test_non_halal_side_never_local` | "The word 'non halal' (and the non-halal side of any meat comparison) resolves ONLY to plain non-halal Woolworths master rows — NEVER to Local_Deals rows (all four local shops are halal sources per §5/Q17; a local price is ALWAYS the halal side of a comparison)." |
| R5-M3 — three-way answer | TW2 | `test_beef_mince_fixture_twin_line_all_three_sides` | "With a priced halal row present, ONE answer carries all three: Wool halal, local prices + winner, Wool non-halal twin line." |
| R5-M4 — zero-write guarantee | TW1 (read of in-memory rows) + TW3 test 6 + RG1.4 | `test_lookup_zero_writes_q11_intact` | "No sheet writes introduced by the lookup path; Q11 separation intact; parity audit ALIGNED."; "The twin line is DISPLAY-ONLY: zero writes, no new state files, no new verb, no live-search fallback added." |
| R5-M5 — skill line | TW4 | (doc check: `skills_doc.py --check` OK + the line grep-present) | "with one explanatory line added to `claw-skills/grocery-price/SKILL.md` afterwards" |

## SELF-CHECK (performed before issuing)

Re-read test.md §"USER VERDICT…" against the table: verdict 1
(non-halal = WW sheet rows only) → M2/TW1+`test_non_halal_side_never_local`
✓; verdict 2 (pooling approved) → M3/TW2 + the all-three-sides test ✓;
verdict 3 (live search "keep exactly as is") → `live` verb untouched
(scope guard + TW tasks name no v2_live change) ✓; the twin-line
feature block → M1/TW1+TW2 + the mandatory beef-mince fixture test ✓;
constraints 1–5 → M4/Q11 test, display-only scope, blank-halal
independence test, suite-green criterion, local-never-non-halal test ✓;
checker acceptance bullets → acceptance criteria 1–5 ✓. No verdict
unenforced. One flagged ambiguity (twin-line discount vs raw example)
presented for the user's ruling at approval — nothing guessed.
