# OPEN FIX LIST — standing (updated: cycle 3, 2026-09-12 early morning)

Carry-over rule: every cycle's CHECK appends its classified defects
here; the next FIX phase works EXACTLY this list, each item with a
regression test, then strikes the line with proof.

## OPEN

0. **[INGEST, P1 — new 2026-09-12] "N KG <item> $X" board tiles can
   write the PACK TOTAL into /kg special cells.** The 2026-09-11
   08:06 Merjan ingest polluted 14 cells (e.g. "2 KG LAMB MINCE
   $29.99" → cell 29.99 instead of 15.00/kg + terms) and invented 2
   tile-less specials (diced 34.99, lamb curry 27.99). DATA
   corrected by hand 2026-09-12 against the archived boards (proof:
   `cycle-3/merjan-corrections.md`) — but the PARSER defect remains:
   next weekend's board will re-pollute. FIX: repro the tile text
   through the deal-text/vision parse chain, normalise "N kg … $X"
   to per-kg + terms before the cell write, regression-test all three
   board layouts (combined grid / chicken view / meat view).

1. **[GW agent-layer — CLOSED by user decision 2026-09-12]** On
   compare phrasings where the sheet has NO non-halal twin row, the
   gateway live-fills the supermarket side (disclosed every time; the
   halal/sheet side is always correct). Root cause found by the
   user's own experiments: the sheet has exactly ONE plain twin row,
   and with a twin present the compare relay is perfectly sheet-first
   ("no live search" magic words also force strict sheet-only).
   The user ACCEPTED the live-fill on twin gaps (declined creating
   twin rows — the two tabs stay exact row-to-row mirrors by design),
   and keeps the "no live search" magic words as the strictness
   tool. No further action.
2. **[USER DECISION] `specials` scope (carried from run 1/2)** —
   the gateway agent surfaces local-shop specials; the CLI verb is
   Woolworths-scoped per spec. Update the spec story (two layers) or
   scope the agent back. Not blocking the loop.
3. **[ENV] Drive backup quota** — `tools/sheet_backup.py` Drive copy
   403s (user's Drive storage full). Local fallback verified; zero-
   writes guard unaffected. Free quota or repoint.

## NEXT STEP (per convergence-loop.md)

A cycle-3 clean exit was declared (cycle-3-report.md §4). Run the
INDEPENDENT close-out session (`session-3-checker-prompt.md`) to
re-verify and archive before final sign-off.

## CLOSED (proof in the cycle reports)

- Cycle 2 closed: D1-by-design judging + D1 real remainder, D2
  (filler-strip + GJZ tracked-class + honest pool), D3 + lamb-necks
  matched-row citation, py3.11 sync blocker (exception retired), GW
  skill relay rules, GWY/CHZ taxonomy, -ies forms, pack-family
  ranking. Proof: `cycle-2/cycle-2-report.md`.
- Cycle 3 closed: round-3 stress hardening (double-plural stem
  candidates + short-token strip guard; blade 1.3 [KFM] re-proven),
  full clean exit. Proof: `cycle-3/cycle-3-report.md`.
