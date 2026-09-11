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

1. **[GW agent-layer, observed-not-failing]** On open "compare …"
   phrasings the gateway agent prefers live web enrichment over the
   sheet's canonical twin line and editorialises about sheet
   freshness ("mis-entered" — it isn't). Local-shop relays are now
   complete and the raw-quote-as-twin fault did NOT recur in cycle 3.
   Deterministic CLI contract re-proven byte-exact. Documented
   behaviour; revisit only if the user wants the twin line forced.
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
