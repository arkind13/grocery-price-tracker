# THE CONVERGENCE LOOP — standing mechanism (v2 sheet, post-rebuild)

> User mandate 2026-09-11: "run the whole loop, complete checklist, fix
> it, then again run the whole loop and fix it, continue till everything
> comes clean — no matter if it has to run for days and days." This file
> is the STANDING mechanism. It never needs rewriting — every cycle
> invents its own commands.

## The rules

1. **Every cycle invents NEW commands.** The matrix tool takes
   `--round N` — each round generates different query variants
   (word-order rotations, plural toggles, qualifier phrasings) for
   every item, plus the standing formats. The model additionally
   invents its own phrasings each cycle: new word orders, new
   qualifiers ("near me", "today", "at the butcher"), new drift
   patterns, typos, plural forms — never repeat a previous cycle's
   exact query list.
2. **Every item is checked one by one, every cycle.** No sampling down.
   The audit is read-only on the sheet.
3. **Every check's answer is recorded** to the evidence dir
   (`data/test_logs/cycle-<N>/`) — CSV + rendered replies. No
   "probably fine".
4. **Fixes come from the checker's fix list only**, in a SEPARATE fix
   session, each with a regression test.
5. **Exit criterion**: one full cycle where every check passes AND the
   previously-failing checks from all earlier cycles re-pass. Then the
   independent close-out session signs off and the artifacts are
   archived.
6. **Quota discipline**: single writer, ≥1.3s throttle, 429 → wait
   120s and resume. Never run two sheet sessions at once.

## THE LOOP IS AUTONOMOUS — DO NOT STOP UNTIL CLEAN

**Model assignment (user directive 2026-09-11):**
- FIX phase: **GLM-5.3** (the stronger model)
- CHECK phase: **GLM-5.3-Flash** (the fast model — the tool's
  computed verdicts are the arbiter, so self-grading risk is low)

**THE LOOP DOES NOT STOP between cycles. No assumptions. No "probably
fine." No skipping. EVERY line, EVERY scenario, EVERY item — checked
each and every cycle. The ONLY exit is: a full cycle where every
check passes AND all previously-failing checks re-pass.**

### CYCLE N — CHECK phase (GLM-5.3-Flash)
1. `tools/item_audit.py` — the fast semantic sweep (all items).
2. `tools/item_audit.py --matrix --round N` — every item × the format
   matrix + this round's invented variants.
3. `tools/item_audit.py --exec --items "<cycle-(N-1) failures>"` —
   re-run the previous cycle's fixed items with real CLI commands.
4. The live gateway battery: 8 real Telegram messages (invent the
   phrasings fresh this cycle).
5. Parity audit + zero-writes check (md5 the tabs before/after) +
   suite count.
6. **Deliverable**: `cycle-N-report.md` — totals, every non-PASS
   classified, the numbered FIX LIST.

### CYCLE N — FIX phase (GLM-5.3)
1. Read the cycle-N FIX LIST. Fix ONLY the numbered items, each with a
   regression test.
2. Suite green. Commit, push, sync.
3. Deliverable: the fix report with per-item proof.

### Then CYCLE N+1: CHECK phase again (new invented commands,
--round N+1). Repeat until a full cycle comes back with ZERO failures
and ZERO new findings. Only then is the loop DONE.

## Current state (the loop's starting point)

- **Cycle 1 (CHECK) has run** — the run-2 verification found:
  - FIXED+verified: the 4 pack-presentation rows, lamb necks merge,
    goat curry both-presentations, beef mince twin line, multibuy
    terms, chicken breast 5kg routing
  - OPEN (was): D2 (price-of dump, 6) · D3 cousin codes (6) ·
    lamb-necks header flip (1) · GW relay discipline (agent layer) ·
    the v2_read VPS sync blocker (py3.11 refactor) · the specials
    scope question (user decision)
- **Cycle 2 (FIX then CHECK) — 2026-09-11 evening:** the whole open
  list above is FIXED (commits `8014417`, `6cf5b13`, `a4b0241`):
  matched-row citation (best token match, never sheet order), NL
  filler strip + GJZ §8 tracked-class + honest no-code unfiltered
  pool, plural/stem-folded realistic forms, D1 design ruling encoded
  in the audit judging, container-parity `_note_text` refactor +
  py3.11 guard test (sync blocker CLOSED — the named exception is
  retired), gateway relay discipline in the grocery-price skill,
  GWY/CHZ taxonomy labels, -ies forms, pack-family ranking. Goat-
  curry standing pin updates: bare "goat curry" cites the matched
  /kg row [NZH] (the same principle that fixed AUG/AQZ); [PTU]
  remains the 5kg pack row.
- **Cycle 3 (CHECK, round 3) — 2026-09-12 early morning: CLEAN EXIT
  declared.** Sweep 143/143 · matrix 688 checks (672 PASS + 14
  by-design RECORDED; 2 fails = 1 fixed mid-cycle + re-proven, 1
  quota retry — post-fix re-run 10/10, zero unexpected FAILs stand) ·
  exec 17/17 · spots 7/7 (twin byte-exact) · gateway 8/8 delivered
  (7 clean + 1 PASS-with-observations) · suite 732/0 · parity
  ALIGNED · zero sheet writes (md5-identical). Every previously-
  failing check from runs 1–2 + cycle 2 re-passed. Next step per the
  loop: the INDEPENDENT close-out session (`session-3-checker-
  prompt.md`) re-verifies and archives before final sign-off.
  Residual (non-blocking, disclosed in cycle-3-report.md §5): the
  gateway agent's compare-query live-enrichment preference; the
  `specials` scope user decision; the Drive backup quota.
- **D1 reclassified BY DESIGN** (user ruling 2026-09-11): the halal
  keyword gates the BUTCHER search — without it, butchers are not
  searched, and that is correct. The audit's meat judging must treat
  bare protein queries as Woolworths-scope answers (halal-scoped
  cluster + missing-list answers are only expected for "halal …"
  queries). Produce plural/noun-first misses remain REAL defects.
  (Encoded in `tools/item_audit.py` judge_matrix, 2026-09-11.)

## The standing prompts

- CHECK session: paste `session-2-rerun-matrix-prompt.md` (generalized —
  it discovers the latest claims itself) + add: "this is cycle N; use
  --matrix --round N; invent fresh query phrasings".
- FIX session: paste the cycle's FIX LIST + the strict charter rules
  (regression tests per fix, suite green, STOP on conflict).
- FINAL close-out: paste `session-3-checker-prompt.md` once a cycle
  comes back fully clean.
