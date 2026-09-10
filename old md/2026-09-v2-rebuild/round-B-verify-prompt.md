# ROUND B — VERIFIER PROMPT (paste into a FRESH session, different model if possible)

Copy everything below the line. This session must never be the same
session that wrote the fixes.

---

You are an independent verifier for the grocery-price-tracker project. A
fixing session claims to have implemented the fixes in
`grocery-price-tracker/fix-spec-2026-09-09.md`. Your job is to find out
what is ACTUALLY fixed, what fell through, and what is newly broken. Your
ONLY job is testing and recording. **Fix nothing.** A defect you can
reproduce gets written down exactly as reproduced — no repairs, no
workarounds, no "small" fixes on the side.

## Read first
1. `grocery-price-tracker/fix-spec-2026-09-09.md` — what was SUPPOSED to
   be built (acceptance criteria per FIX ID).
2. `grocery-price-tracker/fix-round-report-*.md` — what the fixer CLAIMS.
   Treat every claim as unproven.
3. `grocery-price-tracker/data/test_logs/2026-09-08-comprehensive/defects.md`
   — the 2026-09-08 defect baseline (D1–D17 defects, R1–R12 observations)
   you will compare against. Mind the header: D14 is retracted by the user
   (separate products — if a matcher merges them, that is a NEW defect).
4. `grocery-price-tracker/retest-plan-2026-09-09.md` — the test procedure
   you will execute (§0–§8).

## Interpreter / environment
- Python: `C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe`
  (default python lacks curl_cffi). Work from
  `C:\Users\User.DESKTOP-R2G441H\Documents\AI related\`.
- Test harness + command batches from the previous round live in
  `grocery-price-tracker/data/test_logs/2026-09-08-comprehensive/`
  (harness.py, batch_*.json, t8_driver*.py). Copy harness.py into YOUR
  new log dir so receipts stay separate.
- Google Sheets quota: ~50 writes/min, ~300 reads/min. Never run two
  sheet-writing processes at once; throttle ≥1.25s per write in drivers.
  Known driver bugs to fix in your copies before T8 (see retest-plan §7).

## Procedure
1. New evidence dir:
   `grocery-price-tracker/data/test_logs/<today>-verification/` with the
   same structure as the 09-08 round (commands_log.csv, outputs/,
   defects.md, t8 logs, baselines/). Snapshot fresh baselines (sheet grid
   via the recon pattern + copies of `data/*.txt|*.json` state files).
2. Run retest-plan §0 (preconditions + offline pytest baseline).
3. Run retest-plan **§1 — the per-defect table — this is the core of the
   round.** For each FIX ID: run the listed command(s) against the live
   sheet and judge ONLY by the EXPECTED column. One output file per check.
4. Then §2–§6 batteries (compare/live-search/dry-run/list-mechanics/
   local-deals) and §7 the T8 battery, in that order. Restore state after
   every destructive step (restore scripts/patterns are in the 09-08
   round; final state must be byte-identical to your baseline — verify).
5. Do NOT run a real `wednesday` (only `--dry-run`), never `--purge`
   while real delete-pending rows exist, and put fake test entries at the
   END of list files.

## Deliverable — `verification-report-<date>.md` in your evidence dir
A status matrix with one row per defect ID from the 09-08 baseline
(D1–D17, R1–R12, minus retracted D14):

`D<n> | FIXED / STILL BROKEN / PARTIAL / NOT RETESTED | evidence = <command + one-line observed output vs required output>`

Rules for the verdicts:
- FIXED requires live evidence from YOUR OWN run, never the fixer's
  report.
- STILL BROKEN requires the reproducing command + the observed (wrong)
  output, saved in outputs/ and referenced.
- Anything new (not in the baseline) gets a NEW id continuing the
  sequence (D18+, R13+) with the same evidence discipline.
- End the report with: total fixed / still broken / partial / new, and
  the exact list of IDs for the NEXT fix round (still broken + partial +
  new) — that list is the next fix round's entire scope.

Finally: record a short round entry in `test.md` (parent folder), commit
your evidence dir + report, push, scp the evidence dir to
`myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/data/test_logs/`,
checksum-verify. Do not touch any code file.
