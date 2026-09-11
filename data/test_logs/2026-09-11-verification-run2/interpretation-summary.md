# SESSION 2 (RUN 2) — RE-RUN + FULL FORMAT MATRIX — INTERPRETATION SUMMARY

> Executor session 2026-09-11, 15:03–16:30 AUSEST. Verification only —
> **nothing was fixed**; every defect below is recorded with evidence.
> This is the SECOND execution of the generalized session-2 prompt
> (commit `a8841d5`): run 1 (12:08–13:36,
> `../2026-09-11-verification/`) verified the same fix session, but the
> SHEET CHANGED AFTER IT — `3a95f13` (sort_butchery apply: butchery
> block sorted on both tabs) plus the Merjan chicken-breast-5kg row the
> morning ingest left — so fresh evidence was mandatory.
> Fix session under verification (newest report per the generalized
> prompt = run 1's interpretation-summary): commit `a820759` ("v2_read
> pack routing: name+size-token master match (SDB/KWM/PSB/HSZ + WZF
> fixed)"). Every claim treated as unproven.
> Baselines: `baseline_sheet_1503_pre-audit.json` (15:03, VERIFIED,
> Products_Master 144×13 / Local_Deals 147×11) and
> `post-audit_sheet_1603.json` (16:03).

## 1. Totals

- Sheet items (Products_Master): 144 (143 matrix-tested — 1 blank-name row skipped by the tool)
- Targeted re-run checks: 6 lookups over the fix session's 5 claimed rows — **5/5 claims FIXED** (§2)
- Standing regression spot-checks: 5 — **4 PASS, 1 FAIL** (§3; the FAIL is a NEW regression introduced after run 1)
- FULL FORMAT MATRIX: 545 checks — **348 PASS / 197 non-PASS**, all 197 classified (§4); **0 quota (429) failures, 0 errors** (rc=0 on all 545); no re-run needed
- Live gateway sample: **8/8 messages delivered and answered** — 6 PASS, 2 partial with observations (§5)
- Suite: **698 passed, 0 failed, 0 skipped** (37s, anaconda Python 3.13.9)
- Parity audit: **ALIGNED** (Products_Master ↔ Local_Deals, post-audit snapshot)
- Zero sheet writes from the audit: **PASS** — pre-audit 15:03 vs post-audit 16:03 backups **md5-identical** (`79e8814b2dd1bff739c013492831c5d5`), all 5 tabs
- Three-way sync: see §6

## 2. The targeted fixes — 5/5 claims FIXED (replies quoted verbatim)

### 2.1 Lebanese kofta (4kg) → [SDB] — FIXED

```
$ price --item "Lebanese kofta (4kg)"
Halal Lebanese kofta – (4kg)
  not tracked at Woolworths — missing list [SDB]
  🔪 Dunya (site)  $59.99 / 4kg pack = $15.00/kg
  🏆 Best local: $15.00/kg — Dunya (site)
  ⏱️ 2026-09-11 · [CODE] = sheet Item_Code
```

### 2.2 Turkish Kofta (5kg) → [KWM] — FIXED (both forms)

Sheet spelling AND the exact 11:06 failing form both route:

```
$ price --item "Turkish Kofta (5kg)"
Halal Turkish Kofta – (5kg)
  not tracked at Woolworths — missing list [KWM]
  🔪 Dunya (site)  $74.99 / 5kg pack = $15.00/kg
  🏆 Best local: $15.00/kg — Dunya (site)
```

```
$ price --item "halal turkish kofta 5kg"
Halal Turkish Kofta – (5kg)
  not tracked at Woolworths — missing list [KWM]
  🔪 Dunya (site)  $74.99 / 5kg pack = $15.00/kg
  🏆 Best local: $15.00/kg — Dunya (site)
```

(The "Kofte" spelling fold is STILL open — see D4/fix list #4; it was
never claimed fixed.)

### 2.3 Chicken Tenderloin (5kg) → [PSB] — FIXED

```
$ price --item "Chicken Tenderloin (5kg)"
Halal Chicken Tenderloin – (5kg)
  not tracked at Woolworths — missing list [PSB]
  🔪 Dunya (site)  $54.99 / 5kg pack = $11.00/kg
  🏆 Best local: $11.00/kg — Dunya (site)
```

### 2.4 premium chuck Mince (5kg) → [HSZ] — FIXED

```
$ price --item "premium chuck Mince (5kg)"
Halal premium chuck Mince – (5kg)
  not tracked at Woolworths — missing list [HSZ]
  🔪 Dunya (site)  $79.99 / 5kg pack = $16.00/kg
  🏆 Best local: $16.00/kg — Dunya (site)
```

### 2.5 Halal Lamb Tenderloin (5kg) → [WZF] — FIXED (claim never tested before; proven now)

Run 1 never ran this row; the fix commit's message claims it. Proven:

```
$ price --item "Halal Lamb Tenderloin (5kg)"
Halal Lamb Tenderloin – (5kg)
  not tracked at Woolworths — missing list [WZF]
  🔪 Dunya (site)  $134.99 / 5kg pack = $27.00/kg
  🏆 Best local: $27.00/kg — Dunya (site)
```

**Score: 5/5 FIXED** (SDB, KWM ×2 forms, PSB, HSZ, WZF). All against
the POST-SORT sheet — the pack-routing fix survives the butchery
reorder.

## 3. Standing regression spot-checks — 4 PASS, 1 FAIL

### 3.1 lamb necks → **FAIL (NEW REGRESSION)**: header code flipped [YCQ] → [YTB]

```
$ price --item "lamb necks"
Not tracked at Woolworths — missing list [YTB]
  🔪 Merjan Brothers Quality Meats  $15.00/kg (special) · min order 2kg for $29.99
  🔪 Dunya (site)                   $16.99/kg
  🔪 Dunya (site)                   $29.99/kg
  🏆 Best local: $15.00/kg — Merjan Brothers Quality Meats
  ⏱️ 2026-09-11 · [CODE] = sheet Item_Code
```

Expected (standing rule): merged row **[YCQ]** "Halal Sliced Lamb
Neck". Delivered: **[YTB]** — the Neck FILLET (BBQ) row. All required
CONTENT is present (Merjan $15/kg special + min-order terms + Dunya
$16.99), but the header cites the wrong row. Root cause: `3a95f13`
sorted the butchery block — [YTB] Fillet now sits at Products_Master
row 51, [YCQ] Sliced Neck at row 58, and the vocabulary-term path
("lamb necks") heads its answer with the FIRST cluster row in sheet
order instead of the matched row. Run 1 (12:13, pre-sort) cited
[YCQ]. The matrix's exact-name rows for [YCQ] still cite [YCQ]
correctly (all 4 formats PASS) — the flip is specific to the
free-text vocabulary path. Repro: `price --item "lamb necks"`
(evidence `reg_1.txt`). **Regression count this round: 1** (counted
separately from discoveries, per charter). Same root family as D3/O-1
below.

### 3.2 goat curry → both presentations + [PTU] — PASS

```
$ price --item "goat curry"
Not tracked at Woolworths — missing list [PTU]
  🔪 Merjan Brothers Quality Meats  $15.00/kg (special) · min order 2kg for $29.99
  🔪 Dunya (site)                   $89.99 / 5kg pack = $18.00/kg
  🏆 Best local: $15.00/kg — Merjan Brothers Quality Meats
```

### 3.3 beef mince → locals + non-halal twin line — PASS (twin line exact)

```
$ price --item "beef mince"
Not tracked at Woolworths — missing list [EPJ]
  🔪 Dunya (site)  $64.99 / 5kg pack = $13.00/kg
  🔪 Dunya (site)  $15.99/kg
  🔪 Dunya (site)  $17.99/kg
  🏆 Best local: $13.00/kg — Dunya (site)
also at Woolworths (non-halal): $13.54 · 500g = $27.08/kg — Woolworths Beef Mince 500g
```

Twin line byte-exact vs the standing expectation ($13.54 · 500g =
$27.08/kg — the WW display-discount engine's output, spec §18 A4).
The three unattributed Dunya lines are the known O-1 observation
(§4.1 D3).

### 3.4 chicken breast 5kg → [NTB], never the fillet — PASS

```
$ price --item "chicken breast 5kg"
Halal Chicken Breast – (5kg)
  not tracked at Woolworths — missing list [NTB]
  🔪 Merjan Brothers Quality Meats  $34.99 / 5kg pack = $7.00/kg (special) · min order 5kg for $34.99
  🔪 Dunya (site)                   $54.99 / 5kg pack = $11.00/kg
  🏆 Best local: $7.00/kg — Merjan Brothers Quality Meats
```

Routes to the 5kg row; fillet row absent. NOTE: the Merjan 5kg line is
NEW DATA since run 1 (this morning's Merjan board, ingested 08:06 +
sort apply) — data drift, not behavior change; it strengthens the
answer.

### 3.5 multibuy terms next to the shop's price — PASS

```
$ price --item "Halal Drumstick"
Halal Drumstick
  not tracked at Woolworths — missing list [VCK]
  🔪 Merjan Brothers Quality Meats  $4.00/kg (special) · min order 5kg for $19.99
  🔪 Dunya (site)                   $7.99/kg
  🏆 Best local: $4.00/kg — Merjan Brothers Quality Meats
```

"min order 5kg for $19.99" rendered next to Merjan's special per-kg
rate (the ID-1 contract). Also exercised by 3.1/3.2/3.4.

## 4. FULL FORMAT MATRIX — results

Command: `tools/item_audit.py --matrix`, run 15:10–16:02 AUSEST
(52 min). Evidence: `item_matrix_2026-09-11_1510.csv` (copied here),
stdout in `matrix_run_stdout.txt`, per-row classification in
`classification.json`.

**143 items · 545 checks · 348 PASS · 197 non-PASS · 0 quota (429)
failures · 0 errors** (rc=0 on every check). Per-format PASS: exact
142/143 · drift-shuffle 81/134 · drift-plural 50/143 ·
no-halal-prefix 75/105; code-as-query 0/14, nl-price-of 0/5,
with-halal-prefix 0/1 (by design / judged, below).

### 4.1 Classification of all 197 non-PASS

| Class | Checks | Verdict |
|---|---|---|
| PASS | 348 | healthy |
| By-design (code-as-query: codes are not lookup keys; every code query answers bare "Not tracked") | 14 | not defects |
| Generator-mangled queries (pluraliser corrupts tokens: "(5kg)s", "(4kg)s", "500gs", "eachs", "Bunchs", "R2E2 Mangoe", "Blueberrie", "Strawberrie", "Stirs Fry", "Beefs Rib Eye", "oregano leave", "Banana Kid 5", "plastics bag", "Celerys", "Gravys", "Diced Beefs", "Finely Diced Lambs", "Sweet Corns", "kitkats", "Whole chickens s9/s14", "Beef Minces") | 53 | judging artifacts — NOT defects |
| Judging ambiguity ("halal Woolworths Beef Mince 500g" — halal prefix on the non-halal WW-branded row is nonsensical; the halal-cluster answer is arguably correct) | 1 | not a defect |
| **D1 — realistic forms unfindable** (halal prefix load-bearing + realistic plural/singular + noun-first) | **117** (28 no-prefix + 50 shuffle + 39 plural) | REAL |
| **D2 — "price of …" / exact WW-row name full-sheet dump under a FALSE header** | **6** | REAL |
| **D3 — realistic drift query answered with a COUSIN's code** | **6** | REAL |
| **Total** | **197** | |

D1 detail (117): every no-halal-prefix bare miss (`Drumstick`,
`Wings`, `Spicy Wings`, `Greek Chops`, `Greek Lamb`, `Turkish
chicken/wings`, `Chicken Drumette`, `Whole chicken s9/s14`,
`Lebanese Chicken`, `Turkish Adana`, `Kofte skewer`, `Lebanese/
Turkish Kofte`, `Skin Off Drum`, `Beef Marrow Bones`, `Beef Rump`,
`Beef Stir Fry`, `Eye silverside`, `Beef Gravy`, `Beef/Osso Bucco`,
`Marylands Skin-Off`, `Povi Masima Bucket`, the /kg sausage rows) +
realistic plurals/singulars (`Cauliflowers`, `Eggplants`,
`Artichokes`, `Tomatos`, `brown onions`, `Jap Pumpkins`, `Cos
Lettuces`, `Choko`, `Packham Pear`, `Pink Lady Apple`, `Mangoes
R2E2`…) + noun-first shuffles. Per-row list: `classification.json`.

D2 detail (6): `price of …` (×5) and exact `Woolworths Beef Mince
500g` (×1) dump ~120 price lines under a false cluster header — the
false header is now **[XJA]** ("Halal chicken breast diced" — the
Merjan $4/kg row now sorts first in the matched dump; run 1 showed
[EPJ]). Live post-matrix confirmations were done in run 1 and the
behavior is unchanged apart from the header code; the CLI-side
contract (§8 tracked-class answer for GJZ never shown) persists.

D3 detail (6, per-row from `classification.json`):

```
AQZ "Thighs Halal Chicken"      → cited [SNA] (Halal Chicken Thigh – (5kg))
AQZ "Halal Chicken Thigh"       → cited [SNA]
AQZ "Chicken Thighs"            → cited [SNA]
AUG "Mince Halal Beef"          → cited [EPJ]
AUG "Beef Mince"                → cited [EPJ]
GJZ "500g Woolworths Beef Mince"→ cited [XJA]
```

(Run 1's lamb examples — Fillet/Lamb Mince/lamb Sausages citing
cousins — now PASS with the correct row codes; the D3 family shrank
9 → 6 but is not dead.) The §3.1 lamb-necks regression is the same
family surfacing in the vocabulary path.

**vs run 1**: non-PASS 202 → 197 (D1 129→117, D3 9→6, D2 6→6,
mangled-bucket 43→53 — larger bucket = stricter disclosed regex this
run, per-row evidence in classification.json). Net direction:
slightly better, no new matrix-level defect classes.

## 5. Live gateway sample — 8/8 delivered; 6 PASS, 2 partial

Real Telegram via `ssh myvps 'docker exec openclaw-core node
/app/openclaw.mjs agent --channel telegram --to 1594431983 --message
"…" --deliver'`, 16:12–16:24 AUSEST. Verbatim captures: `gw1…gw8_*.txt`.

**GW1 — "how much is halal lamb mince" → PASS** (min-order terms shown):

> Halal lamb mince right now (from the tracked sheet, verified just now):
> - **Merjan** — **$15.00/kg** special, valid till **Sun 13 Sep** (multi buy 2kg for $29.99)
> - **Dunya** — $15.99/kg (site price), or **5kg pack $69.99** (~$14/kg)
>
> Merjan's the better per-kg price while the special runs. …

**GW2 — "price of goat curry" → PASS** (both presentations, /kg special + 5kg-normalised):

> - **Merjan** — **$15.00/kg** special, valid till **Sun 13 Sep** (multi buy 2kg for $29.99)
> - **Dunya** — no per-kg price on the site right now, only a **5kg pack $89.99** (~$18/kg)

**GW3 — "compare beef mince halal and non halal" → PARTIAL** (twin
STRUCTURE present; price basis diverged): the reply quoted the
non-halal twin as

> - Beef Mince 500g — $15.00 = **$30.00/kg**

i.e. the RAW sheet price, not the CLI's canonical discount-engine twin
line `$13.54 · 500g = $27.08/kg` (which §3.3 proves renders correctly
at CLI level, byte-exact vs the standing expectation; run 1's GW3
delivered the discounted numbers). The agent bypassed/overrode the CLI
twin render this round. Recorded as gateway-layer variance — fix list
#5. (Run 1: PASS.)

**GW4 — "chicken breast 5kg" → PASS** (pack routing; both 5kg prices, fillet absent):

> - **Merjan** — **$34.99 for 5kg** special (≈ **$7/kg**), valid till **Sun 13 Sep** — this one's a standout
> - **Dunya** — $54.99 for 5kg (≈ $11/kg)

**GW5 — "lamb necks" → PARTIAL** (terms + fillet attribution correct;
one line dropped): Merjan $15/kg + "multi buy 2kg for $29.99" shown,
and the $29.99 line is explicitly attributed to the fillet cut
("different cut, pricier" — the agent compensates O-1), but the Dunya
**$16.99/kg same-cut** line from the CLI answer (§3.1) did not make
the delivered summary (run 1's GW5 delivered all three lines). Fix
list #5.

**GW6 — "list" → PASS with observation** (interpretation drift): the
agent delivered the FULL board this time (Merjan specials block +
Dunya catalogue + offer of the rest) instead of run 1's missing-list
framing. Both readings of the bare verb "list" are legitimate; the
missing-list contract itself is exercised by every matrix "missing
list [CODE]" reply. Verbatim capture: `gw6_list.txt`.

**GW7 — "specials" → PASS** — and an improvement on run 1: the agent
enumerated the LOCAL shops' specials with their multibuy terms (Merjan
board till Sun 13 Sep, per-cluster "2kg/$29.99"-style terms, cos
lettuce 99c across shops). The CLI `specials` verb remains
Woolworths-scoped per spec (col H empty → "no active specials"), so
run 1's fix-list #6 (product question: should `specials` cover local
specials?) is in practice answered YES at the agent layer; the spec
story should be updated to match (fix list #6).

**GW8 — "batch NTB done" → PASS** (verify-only contract exactly; writes nothing):

> `batch NTB done` came back with a block — `done` is verify-only and NTB (Halal Chicken Breast – 5kg) still has two blank cells in Products_Master:
> - **col D** — Woolworths price
> - **col G** — search keyword
> …
> 1. **Fill D + G in the sheet yourself**, then I re-run `batch NTB done` and it verifies ✅ …

## 6. Final gates

- **Suite**: 698 passed, 0 failed, 0 skipped (37s, anaconda Python 3.13.9).
- **Parity audit**: ALIGNED (`tools.parity_audit.audit` over the
  post-audit 16:03 snapshot — Products_Master ↔ Local_Deals).
- **Zero sheet writes**: PASS — `baseline_sheet_1503_pre-audit.json`
  and `post-audit_sheet_1603.json` md5-identical
  (`79e8814b2dd1bff739c013492831c5d5`), all 5 tabs; the hourly :07
  scans (15:07/16:07) also wrote nothing (post log's latest ingest
  still 08:09 MER1109260507).
- **Three-way sync**: local commit + GitHub push of this evidence dir;
  scp'd to
  `myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/data/test_logs/2026-09-11-verification-run2/`
  + md5-verified. **NAMED EXCEPTION (carried from run 1, still open —
  fix list #7):** the VPS container runs the bot's own 03:22 hot-patch
  of `core/v2_read.py` (adds `_note_text()`); git-HEAD's inline
  f-string at line ~511 is a SyntaxError on the container's Python
  3.11.2, so the canonical file is deliberately NOT synced to the VPS
  until the container-safe refactor lands upstream.

## 7. FIX LIST for the next fix session

1. **[D1] Halal prefix is load-bearing + realistic plural/singular +
   noun-first forms miss rows** (P1 — largest real-user impact,
   117 matrix rows, unchanged from run 1): `price --item
   "Drumstick"` → bare "Not tracked" while `price --item "Halal
   Drumstick"` answers [VCK] (§3.5). Fix direction: make the name
   matcher halal-optional, plural-folded, and order-free for ALL rows.
   Repro: any row in `classification.json` D1 list.
2. **[D2] "price of …" and the exact WW-row name trigger a full-sheet
   dump under a FALSE header** (P1, 6 rows): header code now cites
   [XJA] (Merjan chicken breast diced) for unrelated queries; the GJZ
   tracked-class answer (§8) is never shown. Repro:
   `price --item "price of goat curry"` / `price --item "Woolworths
   Beef Mince 500g"`.
3. **[REGRESSION — NEW] vocabulary-path answers cite the sorted-FIRST
   cluster row instead of the matched row** (P1): `price --item
   "lamb necks"` now heads with [YTB] (fillet) instead of [YCQ]
   (sliced neck) after the butchery sort — §3.1 with repro. Root fix
   is the same as D3/O-1: the header code must come from the MATCHED
   row, never from sheet order; add the lamb-necks case as a
   regression test that pins the CODE, not just the price lines.
4. **[D3] cousin-code citation on realistic drift queries** (P2, 6
   rows): AQZ→SNA ×3, AUG→EPJ ×2, GJZ→XJA ×1 (§4.1 D3). Same root as
   #3.
5. **[GW] gateway agent must relay the CLI's canonical lines** (P2):
   GW3 quoted the RAW Woolworths price ($15.00 = $30.00/kg) instead of
   the discount-engine twin line ($13.54 · 500g = $27.08/kg, proven
   correct at CLI level §3.3); GW5 dropped the Dunya $16.99 same-cut
   line. Agent-layer discipline: for compare/twin queries, quote the
   CLI render verbatim, don't re-derive from the raw sheet.
6. **[SPEC DOC] `specials` scope** (P3): the agent now surfaces
   local-shop specials (GW7) while the CLI verb is Woolworths-scoped
   (col H, per spec). Update the spec/README to describe the two
   layers, or scope the verb — user's call, carried from run 1 #6.
7. **[INFRA] Land the container-safe `_note_text()` refactor
   upstream** (P1 — sync blocker, carried from run 1 #5): git-HEAD
   `core/v2_read.py` is a SyntaxError on the VPS container's Python
   3.11.2; only the bot's in-container hot-patch works there. Commit
   the clean version + add a py3.11 syntax check so the class of break
   can't ship again. Until then local/GitHub/VPS cannot fully converge.

**Empty-fix-list goal NOT met** — items 1–5 are real and reproducible
(3 is a fresh regression); none blocks the daily user flow (the
gateway agent masks most CLI-layer gaps), but 1, 2, 3 and 7 should
land before the next full-matrix certification.
