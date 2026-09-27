# OPEN FIX LIST — standing (updated: cycle 3, 2026-09-12 early morning)

Carry-over rule: every cycle's CHECK appends its classified defects
here; the next FIX phase works EXACTLY this list, each item with a
regression test, then strikes the line with proof.

## CLOSED 2026-09-27

0. **[INGEST, P1 — opened 2026-09-12, CLOSED 2026-09-27] "N KG
   <item> $X" board tiles wrote the PACK TOTAL into /kg special
   cells.** Re-polluted live exactly as predicted (Merjan weekend
   boards 2026-09-26/27 — the SAME cells as 2026-09-11: beef curry
   49.99-instead-of-10.00/kg, thigh fillet 21.99, plus 18 more).
   Root causes found (three, stacked):
   (a) the vision model FLIP-FLOPS between runs on the same image
   (single vs multibuy) and sometimes drops the printed quantity from
   raw_text entirely — fixed by temperature 0 + a deterministic
   pack-guard (extractors.deal_text.normalise_pack_deals) that
   re-derives bundle semantics from the verbatim tile text, plus a
   transcription re-read pass (core.flyer_vision.verify_board_parse:
   the model only COPIES the lines, code judges);
   (b) THE WIRING BUG: ingest/sweep pushed vision-schema deals
   through _to_vision_deal's TEXT branch — price_kind overwritten to
   single, multibuy_qty dropped, raw_text replaced by the bare item
   name — so even CORRECT model parses landed as pack totals
   (_to_vision_deal is now schema-aware);
   (c) bulk_pack deals with a pack word ('bucket') were silently
   DROPPED by validation (now downgraded to single with the word in
   notes — the Povi Masima $49.99 line survived for the first time).
   Guard rails added: every payload logged
   (data/diagnostics/vision_payloads, last 50), digest ⚠ flags on
   verify corrections, MAX_TOKENS 4500 (truncation observed).
   Pinned: tests/test_pack_guard.py (29 tests on the real boards —
   Sep-11 user-verified table + Sep-26/27 board + no-op pins).
   DATA corrected the same day by re-ingesting the real board
   through the fixed pipeline (21/21 lines, live on VPS; correction
   digest posted; tools/replay_boards.py replays every surviving
   board).

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
