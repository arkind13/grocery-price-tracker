# ROUND A2 — FIXER PROMPT (fresh session; paste everything below the line)

---

You are implementing Round 2 bug fixes in the grocery-price-tracker
project. Round 1 is complete (all FIX-1…FIX-10 landed; 7 verified fixed
by an independent round). Your ONLY job is fixing the Round 2 scope.
Verification is a separate session — do not attempt it.

## Read first (in this order)
1. `grocery-price-tracker/fix-spec-round2-2026-09-08.md` — your COMPLETE
   work order: R2-1…R2-16 (the 11 verification findings + the 5
   Round-A-deferral fixes added on 2026-09-09; D10 and the quota note are
   deliberately excluded and documented in the spec). Nothing else is in
   scope. Note its HARD RULES section — especially: no undocumented
   behavior changes, and every update to an existing test must be named
   and justified in your report.
2. `grocery-price-tracker/data/test_logs/2026-09-08-verification/verification-report-2026-09-08.md`
   — the evidence behind each item (outputs/ references, proven root
   causes). Read the item's evidence before coding.
3. `grocery-price-tracker/data/test_logs/2026-09-08-verification/defects.md`
   — current defect baseline (D1–D22, R13–R17).

## Scope rules
- Fix R2-1…R2-16 only, in this order: P1s first (R2-1, R2-2, R2-3),
  then R2-4…R2-11, then the extension items R2-12…R2-16.
  The still-open no-FIX-ID items (D9, D12-scenario, D13, D15, R1–R8
  except where folded into R2-4) are awaiting user triage — DO NOT fix
  them. If you notice something new, record it under "Deferred
  findings", don't fix it.
- One commit per R2 item (or tightly grouped pairs the spec marks
  together), each with its regression tests.
- pytest baseline is 1250 passed — keep green; your report states final
  counts.
- Offline only: read-only CLI sanity is fine; do NOT run verification
  batteries; do NOT write to the Google Sheet; do NOT edit
  defects.md / test.md / verification reports / retest-plan (R2-9 is
  the one exception — it explicitly edits retest-plan §7).
- Google quota: single writer, ≥1.3s throttle if you must exercise a
  write path live; you shouldn't need to at all this round.

## Deliverable
`grocery-price-tracker/fix-round-report-2-<date>.md` — one line per R2
ID: `R2-<n> | DONE/PARTIAL/SKIPPED | proof = <tests + result> |
behavior changes: <none or list>`, plus "Deferred findings" and final
pytest counts. Commit, push, scp changed files to
`myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/`.
Honest PARTIAL/SKIPPED lines are acceptable; inflated DONE lines are not.
