# ROUND A3 — FIXER PROMPT (fresh session; paste everything below the line)

---

You are implementing Round 3 — the final three small fixes — in the
grocery-price-tracker project. Rounds 1–2 are done and verified (22
defects fixed, 0 regressions). Your ONLY job is fixing R3-1…R3-3.
Verification is a separate session — do not attempt it.

## Read first
1. `grocery-price-tracker/fix-spec-round3-2026-09-08.md` — your COMPLETE
   work order (3 items, root causes named, including the exact gspread
   attribute mistake to correct). Nothing else is in scope.
2. `grocery-price-tracker/data/test_logs/2026-09-08-verification-2/verification-report-2-2026-09-08.md`
   — the evidence (see the R2-11 and "New problems" sections).

## Scope rules (same as round 2)
- Fix R3-1…R3-3 only. No refactors, no drive-by fixes. New observations
  go under "Deferred findings" in your report — do not fix them.
- Every fix ships its regression test; pytest baseline is **1301
  passed** — keep green; your report states final counts.
- R3-2's acceptance is special: the suite must stay green even when the
  user's REAL `data/scrapedo_health.json` is deliberately dirty — test
   with it dirty, then restore it.
- Offline only: no sheet writes, no verification batteries, no edits to
  defect logs / test.md / verification reports.
- One commit per item. Do not commit unrelated in-flight changes.

## Deliverable
`grocery-price-tracker/fix-round-report-3-<date>.md` — one line per R3
ID: `R3-<n> | DONE/PARTIAL | proof = <tests + result> | behavior
changes: <none or list>`, plus "Deferred findings" and final pytest
counts. Commit, push, scp changed files to
`myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/`.
