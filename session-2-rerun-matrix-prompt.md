# SESSION 2 — RE-RUN + FULL FORMAT MATRIX (paste into a fresh session)

---

You are the verification executor for the grocery-price-tracker v2
rebuild. A fix session just closed the 4 pack-presentation lookup gaps.
Your job: prove the fixes live with a targeted re-run, then execute the
FULL format matrix for every item on the sheet. Record everything.
**Fix nothing.** Any defect you find gets recorded with evidence, never
repaired.

## Read first
1. `grocery-price-tracker/sheet-item-tester.md` — the loop + judging rules.
2. `grocery-price-tracker/auto-ingest-spec.md` — the S1–S16 scenario matrix.
3. Latest evidence: `grocery-price-tracker/data/test_logs/item_exec_2026-09-11_1106.csv`
   (the 4 pack-presentation gaps are the rows: Lebanese kofta (4kg) [SDB],
   Turkish Kofte (5kg) [KWM], Chicken Tenderloin (5kg) [PSB],
   premium chuck Mince (5kg) [HSZ]).

## Environment
- Anaconda python: `C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe`
- Work from `C:\Users\User.DESKTOP-R2G441H\Documents\AI related\`
- **QUOTA LAW**: one session at a time on the sheet; ≥1.3s between
  commands; if a 429 appears, STOP the batch, wait 120s, resume.

## Execute (in order)
1. **Evidence dir**: `grocery-price-tracker/data/test_logs/<today>-verification/`
   (CSV + replies + report). Fresh sheet baselines first.
2. **Targeted re-run (the 4 fixes)** — each MUST answer with the missing
   list + local prices (never "Not tracked"):
   - `price --item "Lebanese kofta (4kg)"` → [SDB]
   - `price --item "Turkish Kofte (5kg)"` → [KWM]
   - `price --item "Chicken Tenderloin (5kg)"` → [PSB]
   - `price --item "premium chuck Mince (5kg)"` → [HSZ]
   Record each reply verbatim.
3. **Regression spot-checks** (previously-fixed behaviors must hold):
   - `lamb necks` → merged row [YCQ]: Merjan $15/kg special + Dunya $16.99
   - `goat curry` → BOTH presentations (Merjan $15/kg special + Dunya
     $18/kg 5kg-normalised) + missing list [PTU]
   - `beef mince` → locals + the non-halal twin line ($13.54 · 500g =
     $27.08/kg — Woolworths Beef Mince 500g)
   - `chicken breast 5kg` → missing list [NTB] (the 5kg row), NEVER the
     fillet row
4. **FULL FORMAT MATRIX**: `tools/item_audit.py --matrix` — every item ×
   every format (~500 real CLI runs, ~50 min). All 429s = quota
   failures: wait 120s and re-run ONLY the failed rows.
5. **Live gateway sample** (real Telegram, 8 messages): "how much is
   halal lamb mince" (min-order terms must show) · "price of goat
   curry" (both presentations) · "compare beef mince halal and non
   halal" (twin line) · "chicken breast 5kg" (routes to [NTB]) ·
   "lamb necks" · "list" · "specials" · one `batch` verify-only check.
   Quote every delivered reply.
6. **Final gates**: suite green (report count) · parity audit ALIGNED ·
   zero sheet writes from the audit · three-way sync line.

## Deliverable
`data/test_logs/<today>-verification/interpretation-summary.md`:
- totals (items, checks, PASS/FAIL per format)
- the 4 targeted fixes: FIXED / NOT FIXED each with the reply quoted
- every non-PASS classified: real defect / quota artifact / judging
  ambiguity — with the reproducing command
- a numbered FIX LIST for the next fix session (empty is a valid,
  excellent outcome)
Commit the evidence dir, push, scp to
`myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/`,
checksum-verify. Touch no code files.
