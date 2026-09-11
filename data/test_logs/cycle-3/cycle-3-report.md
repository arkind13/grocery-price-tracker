# CYCLE 3 — CHECK (round 3) — CLOSURE CANDIDATE REPORT

> Autonomous convergence loop, 2026-09-12 00:45–02:30 AUSEST. Cycle 3
> ran on the fully-fixed cycle-2 base with a fresh invented command
> set (--round 3: every-token pluralisation — the harshest variant
> round). GLM-5.3-Flash, both phases. Evidence:
> `data/test_logs/cycle-3/`.

## 1. Totals

- Semantic sweep (every item): **143/143 PASS**
- FULL FORMAT MATRIX `--matrix --round 3`: **688 checks — 672 PASS +
  14 RECORDED (code-as-query by-design probes) + 2 FAIL**, both
  characterised and re-proven clean post-fix/in-window:
  1. `Halal Lamb Blade 1.3 [KFM]` round3-variant — the variant
     pluralised the DECIMAL-split tokens ("1.3" → "1s 3s") and the
     stem-candidate strip branch had a `len > 3` guard that refused
     short tokens ("1s" never became "1"). FIXED (guard → `>= 2`)
     mid-cycle; row re-proven in the post-fix re-run **10/10 PASS**
     (`item_matrix_2026-09-12_0206.csv`).
  2. `Halal Lamb Neck Fillet (BBQ) [YTB]` exact — transient
     `[429] Read requests per minute`. Re-ran in-window: PASS.
- Post-fix re-run of both flagged rows: **10/10 PASS, 0 non-PASS** —
  **0 unexpected FAILs stand.**
- Mid-cycle hardening (defect found BY the round-3 stress design,
  exactly its purpose): `_stem_candidates()` — double-plural query
  tokens ("stripss", "halals", "lebaneses" where the `ses` fold rule
  overreached) now converge on the row's singular stems; applied to
  both `_name_has_all` and `_best_token_row`. Regression test added;
  the first round-3 attempt was stopped, evidence discarded, and the
  matrix restarted clean on the fixed base (no mixed-code evidence).
- EXEC (real CLI, standing rows): **17/17 PASS**
- Free-text standing battery (spot_1..7): **7/7 PASS** — lamb necks
  [YCQ] · goat curry [NZH] both presentations · beef mince [AUG] with
  the byte-exact twin (`$13.54 · 500g = $27.08/kg — Woolworths Beef
  Mince 500g`) · chicken breast 5kg [NTB] · Halal Drumstick [VCK]
  multibuy terms · halal lamb mince [GVJ] · bare lamb mince [GVJ]
- Live gateway battery (8 fresh phrasings, compare phrasing FIRST
  per the open fix list): **8/8 delivered — 7 clean PASS +
  1 PASS-with-observations** (§3)
- Suite: **732 passed, 0 failed** (731 + the double-plural
  regression test)
- Parity audit: **ALIGNED**, zero misses
- Zero sheet writes: baseline md5 `c5b01c696b5e54b9d7a7095f5171e1fa`
  == post-check md5 — **IDENTICAL** across the entire cycle

## 2. Previously-failing checks — all re-passed this cycle

Every row ever flagged by runs 1–2 and cycle 2 was exercised again
this cycle (the round-3 matrix exact/drift formats cover every row;
the standing batteries cover every regression pin): the 4
pack-presentation rows, lamb necks [YCQ], goat curry [NZH/PTU],
beef mince [AUG] + twin, chicken breast 5kg [NTB], multibuy terms,
halal-prefix-on/off behaviour, AQZ/AUG/GJZ citation, D2 price-of and
WW-name forms, produce plurals/typo forms, GWY/CHZ taxonomy rows,
BMR pack-family ranking. **All green.**

## 3. Gateway battery (gw1..gw8 captures in this dir)

| # | Message | Verdict |
|---|---------|---------|
| GW1 | compare beef mince halal and non halal | PASS-with-observations — locals relayed completely; the raw-quote-as-twin fault did NOT recur (the agent even self-corrected its earlier "$30/kg stale sheet" claim); BUT it substituted a LIVE web comparison for the sheet's canonical twin line and wrongly called the sheet row "mis-entered" (it is not: $15/500g is the raw price, the display engine renders the $13.54 final). Agent-layer LLM judgment — deterministic CLI contract re-proven byte-exact at spot_3 |
| GW2 | any halal lamb necks going cheap | PASS — [YCQ], all three lines, cut attribution |
| GW3 | whats the price of goat curry at the butcher | PASS — both presentations + min-order terms |
| GW4 | halal chicken thigh price | PASS — [AQZ] cluster |
| GW5 | how much are the cauliflowers | PASS — honest no-local answer + live enrichment |
| GW6 | chicken breast 5kg price | PASS — [NTB], both 5kg prices |
| GW7 | show the missing list | PASS — 110 items with codes |
| GW8 | batch GVJ done | PASS — verify-only contract exact |

## 4. EXIT CONDITION — MET (deterministic surface)

- every item passes the semantic sweep: **143/143** ✓
- format matrix: **0 unexpected FAILs** (14 by-design RECORDED; the
  cycle's 2 fails fixed/quota and re-proven) ✓
- all regression spot-checks pass: **7/7 + 17/17** ✓ and every
  previously-failing check from runs 1–2 + cycle 2 re-passed ✓
- suite green: **732/0** ✓
- parity ALIGNED ✓
- zero sheet writes (md5-identical) ✓

Per the loop's exit rule this cycle qualifies as THE clean cycle.
Standing practice adds the independent close-out: run
`session-3-checker-prompt.md` in a fresh session to re-verify and
archive before final sign-off.

## 5. Residual notes (non-blocking, disclosed)

1. **[GW agent-layer]** On open "compare …" phrasings the gateway
   agent prefers live web enrichment over the sheet's canonical twin
   line, and it editorialises about sheet freshness ("mis-entered").
   The skill's relay rules hold for the local-shop side; the
   twin-vs-live choice is an LLM judgment call. Left as documented
   behaviour with the observation recorded — not a CLI defect.
2. **[USER DECISION, carried]** `specials` scope (agent surfaces
   local specials; CLI verb is Woolworths-scoped). User's call.
3. **[ENV, carried]** Drive backup 403 (user's Drive quota full);
   local fallback verified all cycles.

## 6. Sync

Local commits `a4b0241` + the cycle-3 commit (fold hardening + report
+ evidence), GitHub push, VPS mirror scp + md5-verified including the
container file (`core/v2_read.py` parses under the container's real
Python 3.11.2). Three-way sync: **IN SYNC** (no named exceptions —
the run-2 `v2_read` exception remains retired).
