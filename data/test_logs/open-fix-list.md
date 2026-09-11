# OPEN FIX LIST — standing (updated: cycle 2, 2026-09-11 late evening)

Carry-over rule: every cycle's CHECK appends its classified defects
here; the next FIX phase works EXACTLY this list, each item with a
regression test, then strikes the line with proof.

## OPEN (non-blocking)

1. **[GW] relay discipline re-verify (cycle-2 GW3)** — the
   grocery-price skill now bans raw col-D re-derivation and demands
   complete relays, but the cycle-2 gateway session (skills preload
   at session start) still quoted "$30/kg" raw and dropped one Dunya
   line. NEXT CYCLE: run the compare/twin phrasing FIRST in the
   battery; PASS = verbatim `$13.54 · 500g = $27.08/kg` twin line +
   all shop lines. If it repeats on a fresh session, escalate with
   captures.
2. **[USER DECISION] `specials` scope (carried from run 1/2)** —
   the gateway agent surfaces local-shop specials; the CLI verb is
   Woolworths-scoped per spec. Update the spec story (two layers) or
   scope the agent back. Not blocking the loop.
3. **[ENV] Drive backup quota** — `tools/sheet_backup.py` Drive copy
   403s (user's Drive storage full). Local fallback verified; zero-
   writes guard unaffected. Free quota or repoint.

## CLOSED this cycle (proof in `cycle-2/cycle-2-report.md`)

- ~~D1 halal-prefix load-bearing~~ → BY DESIGN per user ruling
  2026-09-11 (encoded in the audit judging); the REAL remainder
  (plurals/noun-first/typo forms) FIXED + tested.
- ~~D2 "price of …" / exact WW-name dump under false header~~ →
  filler-strip + GJZ §8 tracked-class + honest no-code pool.
- ~~D3 cousin codes (6 rows)~~ → `_best_token_row` matched-row
  citation (also `_pack_master_hit` ranking, cycle-2 matrix).
- ~~lamb-necks header flip [YCQ]→[YTB]~~ → same root fix, pinned.
- ~~run-2 fix list 7: v2_read py3.11 sync blocker~~ → container-parity
  `_note_text` upstream + on-container py3.11 parse proof + guard
  test; the named sync exception is retired.
- ~~run-2 fix list 5: GW relay discipline (skill text)~~ → landed;
  behavior re-verify is item 1 above.
- ~~cycle-2 matrix families: GWY/CHZ taxonomy gap, -ies mangles,
  BMR pack-family bias~~ → fixed + re-proven 33/33.
