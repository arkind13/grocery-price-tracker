# SESSION 3 — INDEPENDENT CLOSE-OUT CHECKER (paste into a fresh session, different model if available)

---

You are the independent close-out checker for the grocery-price-tracker
v2 rebuild. Sessions 1 and 2 claim the system is complete and verified.
Your job: prove it or break it. **Fix nothing.** Record everything.

## Read first (in this order)
1. `grocery-price-tracker/architecture-spec.md` (v2 — the contract: §0
   design law, §3 schema, §4 parity, §5 halal, §6 the ONE list, §7
   command surface, §8 search semantics, §12 speed budget, §13 deletion
   manifest, §15 future clause, §16 boundaries + CRITICAL
   INFRASTRUCTURE, §18 amendments).
2. `grocery-price-tracker/data/test_logs/<latest>-verification/interpretation-summary.md`
   — session 2's claims. Treat as unproven.
3. `grocery-price-tracker/old md/2026-09-quality-round/` +
   `2026-09-v2-rebuild/` — the defect history (22+ fixed defects: their
   regression tests must all pass).
4. `AGENTS.md` — the STRICTNESS CHARTER governs you too.

## Environment
Anaconda python (`C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe`),
work from `C:\Users\User.DESKTOP-R2G441H\Documents\AI related\`,
single sheet writer, ≥1.3s throttle, 429 → wait 120s and resume.
Evidence dir: `grocery-price-tracker/data/test_logs/<today>-final-check/`.

## Verify (in order — every verdict on YOUR OWN evidence)
1. **Offline suite**: `anaconda3/python.exe -m pytest tests/ -q` — green,
   0 skipped. Report the count.
2. **The 4 pack-presentation fixes** (session 1's scope): live lookups
   for Lebanese kofta (4kg), Turkish Kofte (5kg), Chicken Tenderloin
   (5kg), premium chuck Mince (5kg) — each answers missing-list + local
   prices, never "Not tracked".
3. **Spot-check the S1–S16 scenario matrix** (minimum 8 rows chosen
   across different behaviours): per-item multibuy terms in replies,
   twin line on meat lookups, GONE badge, pack routing (5kg deals → 5kg
   rows), parity auto-mirror of bottom-appends, S5 unknown-expiry ask,
   comment idempotence on re-merge, freshness gate on ingest.
4. **Speed budget, measured live**: sheet lookup ≤10s · live search ≤20s
   · batch ≤10s · Wednesday ≤30s · list ≤5s. Any miss = a NOT-READY
   finding, not a note.
5. **Accuracy audit of the living docs**: README.md + PROJECT-MAP.md
   describe v2 reality (8 verbs, parity model, ONE list, backup canary,
   future clause) — flag every stale v1 statement.
6. **Three-way sync**: local ↔ GitHub ↔ VPS checksums on the runtime
   files.
7. **Close-out check**: root holds ONLY living docs (README,
   PROJECT-MAP, architecture-spec + runtime essentials); all round
   artifacts archived under `old md/`; the two GitHub repos and the GCP
   project `grocerypriceapp-488202` exist and are un-archived
   (CRITICAL INFRASTRUCTURE).

## Deliverable
`grocery-price-tracker/data/test_logs/<today>-final-check/FINAL-VERIFICATION-REPORT.md`:
- the verdict: **READY** or **NOT READY** (with the blocking list)
- regression audit: all previously-fixed defects re-verified (cite your
  own evidence)
- new defects numbered and evidenced
- the residual watch list (accepted-by-design items, future projects)
- close-out actions already done vs still owed (archives, doc updates,
  sync)
Commit, push, scp. Touch no code files. If NOT READY: the blocking list
is the next fix session's entire scope — write it so a fresh session
can execute it without asking questions.
