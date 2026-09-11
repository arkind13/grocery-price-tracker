# SESSION 2 — RE-RUN + FULL FORMAT MATRIX (paste into a fresh session)

---

You are the verification executor for the grocery-price-tracker v2
rebuild. The latest fix session claims its fixes are live. Your job:
prove them with a targeted re-run, then execute the FULL format matrix
for every item on the sheet. Record everything. **Fix nothing.** Any
defect you find gets recorded with evidence, never repaired.

## Read first
1. `grocery-price-tracker/sheet-item-tester.md` — the loop + judging rules.
2. `grocery-price-tracker/auto-ingest-spec.md` — the S1–S16 scenario matrix.
3. **The latest fix session's report** — find the newest
   `fix-report-*.md` / `interpretation-summary.md` under
   `grocery-price-tracker/data/test_logs/` and the tracker root. The
   items it claims fixed are your targeted re-run list. Treat every
   claim as unproven.

## Environment
- Anaconda python: `C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe`
- Work from `C:\Users\User.DESKTOP-R2G441H\Documents\AI related\`
- **QUOTA LAW**: one session at a time on the sheet; ≥1.3s between
  commands; if a 429 appears, STOP the batch, wait 120s, resume.

## Execute (in order)
1. **Evidence dir**: `grocery-price-tracker/data/test_logs/<today>-verification/`
   (CSV + replies + report). Fresh sheet baselines first.
2. **Targeted re-run (the latest fixes)**: for every item the latest
   fix session claims fixed, run the real lookup and verify the exact
   behavior its fix promised (routing target, prices, terms, codes).
   Quote each reply verbatim. A fix that doesn't reproduce = a FAIL
   with the reproducing command.
3. **Standing regression spot-checks** (these must ALWAYS hold):
   - `lamb necks` → merged row [YCQ]: Merjan $15/kg special + "min
     order 2kg for $29.99" + Dunya $16.99
   - `goat curry` → BOTH presentations (Merjan $15/kg special + Dunya
     $18/kg 5kg-normalised) + missing list [PTU]
   - `beef mince` → locals + the non-halal twin line ("also at
     Woolworths (non-halal): $13.54 · 500g = $27.08/kg — Woolworths
     Beef Mince 500g")
   - `chicken breast 5kg` → missing list [NTB] (the 5kg row), NEVER
     the fillet row
   - any multibuy special → the "min order …" terms rendered next to
     that shop's price
4. **FULL FORMAT MATRIX**: `tools/item_audit.py --matrix` — every item ×
   every format (~500 real CLI runs, ~50 min). All 429s = quota
   failures: wait 120s and re-run ONLY the failed rows.
5. **Live gateway sample** (real Telegram, 8 messages): one multibuy
   item (min-order terms must show) · one two-presentation item · one
   twin-line compare · one pack-routing query · `lamb necks` · `list` ·
   `specials` · one `batch` verify-only check. Quote every delivered
   reply.
6. **Final gates**: suite green (report count) · parity audit ALIGNED ·
   zero sheet writes from the audit · three-way sync line.

## Deliverable
`data/test_logs/<today>-verification/interpretation-summary.md`:
- totals (items, checks, PASS/FAIL per format)
- the targeted fixes: FIXED / NOT FIXED each with the reply quoted
- every non-PASS classified: real defect / quota artifact / judging
  ambiguity — with the reproducing command
- a numbered FIX LIST for the next fix session (empty is a valid,
  excellent outcome)
Commit the evidence dir, push, scp to
`myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/`,
checksum-verify. Touch no code files.
