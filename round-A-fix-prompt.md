# ROUND A — FIXER PROMPT (paste into a fresh session)

Copy everything below the line into the new model. Do not add session
context; this prompt is self-contained.

---

You are implementing pre-written bug fixes in the grocery-price-tracker
project. Your ONLY job is fixing. Verification against the live system is
a SEPARATE round done by a different session — do not attempt it.

## Read first (in this order)
1. `grocery-price-tracker/fix-spec-2026-09-09.md` — your complete work
   order. Follow it top to bottom. P0 fixes (FIX-1, FIX-2) FIRST — they
   must land before the next Wednesday run.
2. `grocery-price-tracker/data/test_logs/2026-09-08-comprehensive/defects.md`
   — background evidence for each defect. Note the header: D14 is
   RETRACTED by the user (those rows are separate products — never merge
   them); D11 carries a user requirement (comments expire with prices).
3. If a spec reference is unclear, read the actual code at the cited
   file/function before changing anything. The spec's line numbers were
   verified on 2026-09-08 but the file may have moved — trust the
   function names.

## Scope rules (violations waste the round)
- Fix ONLY what FIX-1…FIX-10 describe. No refactors, no "improvements",
  no rewording of user-facing text beyond what a fix requires, no new
  features. If you believe something adjacent is broken, DO NOT fix it —
  add one line to your report under "Deferred findings".
- Every fix ships with the regression tests named in its acceptance
  criteria, in the same commit.
- Keep `cd grocery-price-tracker && anaconda3/python.exe -m pytest tests/ -q`
  green (baseline 1219 passed + your new tests, 0 failed).
- You may run the CLI read-only for sanity (compare/lists/todo show), but
  you must NOT run live verification batteries, must NOT write to the
  Google Sheet outside what the code-under-test needs, and must NOT
  repair/clean existing sheet data.
- Never run two sheet-writing processes at once; if you must exercise a
  write path live, throttle writes ≥1.25s (Google quota — see defects.md
  R12).
- Do not edit `defects.md`, `test.md`, or anything in
  `data/test_logs/2026-09-08-comprehensive/` — those belong to the
  verification round.
- Git: work on the current tracker branch. Commit per the spec's
  suggested order with clear messages. Do not commit unrelated in-flight
  changes in the working tree.

## Deliverable (required)
Write `grocery-price-tracker/fix-round-report-<date>.md` containing one
line per FIX ID:
`FIX-<n> | DONE or PARTIAL or SKIPPED | proof = <test name(s) + one-line result> | spec deviations: <none or what>`
plus the "Deferred findings" section and the final pytest counts. Commit
it with the last code commit, push, and scp the changed runtime files to
`myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/` per
the repo's sync convention.

You are finished when every FIX ID has an honest status line. PARTIAL and
SKIPPED are acceptable outcomes — dishonest DONE lines are not.
