# SESSION 2 — RE-RUN + FULL FORMAT MATRIX — INTERPRETATION SUMMARY

> Executor session 2026-09-11, 12:08–(ongoing) AUSEST. Verification only —
> **nothing was fixed**; every defect below is recorded with evidence.
> Fix session under verification: commit `a820759` ("v2_read pack
> routing: name+size-token master match (SDB/KWM/PSB/HSZ + WZF fixed)").
> Baselines: `baseline_sheet_1215_pre-audit.json` (pre-audit, VERIFIED,
> Products_Master 144×13 / Local_Deals 147×11) and the fix session's
> 09:00 snapshot (`baseline_sheet_0900_fix-session.json`).

## 1. Totals

- Sheet items (Products_Master): 144 (143 matrix-tested — 1 blank-name row skipped by the tool)
- Targeted re-run checks: 4 (+3 isolation probes)
- Regression spot-checks: 4 (all PASS on stated expectations)
- FULL FORMAT MATRIX: 545 checks — 343 PASS / 202 non-PASS, all 202 classified (§4); 0 quota failures
- Live gateway sample: 8/8 messages delivered and answered correctly (§5)
- Suite: **698 passed, 0 failed, 0 skipped** (was 690 at the fix session)
- Parity audit: **ALIGNED**
- Zero sheet writes from the audit: **PASS** (pre-audit 12:12 vs post-audit
  13:20 backups byte-identical, all 5 tabs verified)
- Three-way sync: local + GitHub committed & pushed; VPS evidence dir
  scp'd + md5-verified. ONE named exception: `core/v2_read.py` — see §6.

## 2. The 4 targeted fixes — verdicts (replies quoted verbatim)

### 2.1 Lebanese kofta (4kg) → [SDB] — **FIXED**

```
$ price --item "Lebanese kofta (4kg)"
Halal Lebanese kofta – (4kg)
  not tracked at Woolworths — missing list [SDB]
  🔪 Dunya (site)  $59.99 / 4kg pack = $15.00/kg
  🏆 Best local: $15.00/kg — Dunya (site)
  ⏱️ 2026-09-11 · [CODE] = sheet Item_Code
```

### 2.2 Turkish Kofte (5kg) → [KWM] — **NOT FIXED (spelling variant)**

The sheet spelling routes correctly (the 11:06 failure is dead):

```
$ price --item "Turkish Kofta (5kg)"
Halal Turkish Kofta – (5kg)
  not tracked at Woolworths — missing list [KWM]
  🔪 Dunya (site)  $74.99 / 5kg pack = $15.00/kg
  🏆 Best local: $15.00/kg — Dunya (site)
  ⏱️ 2026-09-11 · [CODE] = sheet Item_Code
```

```
$ price --item "halal turkish kofta 5kg"   ← exact 11:06 failing form
Halal Turkish Kofta – (5kg)
  not tracked at Woolworths — missing list [KWM]
  🔪 Dunya (site)  $74.99 / 5kg pack = $15.00/kg
  🏆 Best local: $15.00/kg — Dunya (site)
  ⏱️ 2026-09-11 · [CODE] = sheet Item_Code
```

But the "Kofte" spelling (as a real user writes it — the session prompt
itself spells it this way) still answers bare "Not tracked":

```
$ price --item "Turkish Kofte (5kg)"
Not tracked
$ price --item "halal turkish kofte 5kg"
Not tracked
```

→ **Fix list item #1**: fold the kofta/kofte spelling variant in the
name matcher (same family as plural-fold).

### 2.3 Chicken Tenderloin (5kg) → [PSB] — **FIXED**

```
$ price --item "Chicken Tenderloin (5kg)"
Halal Chicken Tenderloin – (5kg)
  not tracked at Woolworths — missing list [PSB]
  🔪 Dunya (site)  $54.99 / 5kg pack = $11.00/kg
  🏆 Best local: $11.00/kg — Dunya (site)
  ⏱️ 2026-09-11 · [CODE] = sheet Item_Code
```

### 2.4 premium chuck Mince (5kg) → [HSZ] — **FIXED**

```
$ price --item "premium chuck Mince (5kg)"
Halal premium chuck Mince – (5kg)
  not tracked at Woolworths — missing list [HSZ]
  🔪 Dunya (site)  $79.99 / 5kg pack = $16.00/kg
  🏆 Best local: $16.00/kg — Dunya (site)
  ⏱️ 2026-09-11 · [CODE] = sheet Item_Code
```

**Score: 3 FIXED, 1 NOT-FIXED-variant (routing itself proven fixed; the
miss is the kofte spelling, see #1).**

## 3. Regression spot-checks (all PASS on stated expectations)

### 3.1 lamb necks → merged row [YCQ] — PASS

```
$ price --item "lamb necks"
Not tracked at Woolworths — missing list [YCQ]
  🔪 Merjan Brothers Quality Meats  $15.00/kg (special) · min order 2kg for $29.99
  🔪 Dunya (site)                   $16.99/kg
  🔪 Dunya (site)                   $29.99/kg
  🏆 Best local: $15.00/kg — Merjan Brothers Quality Meats
  ⏱️ 2026-09-11 · [CODE] = sheet Item_Code
```

Required content present: [YCQ], Merjan $15/kg special + min-order
terms, Dunya $16.99. Observation O-1: the third line ($29.99/kg) is the
Lamb Neck Fillet (BBQ) [YTB] row pulled in by token match — rendered
with NO row attribution, so it reads as a second price for the same
product. Classification: presentation defect (see fix list #3).

### 3.2 goat curry → both presentations + [PTU] — PASS

```
$ price --item "goat curry"
Not tracked at Woolworths — missing list [PTU]
  🔪 Merjan Brothers Quality Meats  $15.00/kg (special) · min order 2kg for $29.99
  🔪 Dunya (site)                   $89.99 / 5kg pack = $18.00/kg
  🏆 Best local: $15.00/kg — Merjan Brothers Quality Meats
  ⏱️ 2026-09-11 · [CODE] = sheet Item_Code
```

Both presentations present (Merjan /kg special; Dunya 5kg pack
normalised to $18.00/kg) + missing list [PTU] — the S9 design works.

### 3.3 beef mince → locals + non-halal twin line — PASS

```
$ price --item "beef mince"
Not tracked at Woolworths — missing list [EPJ]
  🔪 Dunya (site)  $64.99 / 5kg pack = $13.00/kg
  🔪 Dunya (site)  $15.99/kg
  🔪 Dunya (site)  $17.99/kg
  🏆 Best local: $13.00/kg — Dunya (site)
also at Woolworths (non-halal): $13.54 · 500g = $27.08/kg — Woolworths Beef Mince 500g
  ⏱️ 2026-09-11 · [CODE] = sheet Item_Code
```

Twin line exact match ($13.54 · 500g = $27.08/kg — Woolworths Beef
Mince 500g). Observation O-1 again: three Dunya lines from three
different product lines (EPJ 5kg pack, AUG /kg, VFZ premium), none
attributed to their row.

### 3.4 chicken breast 5kg → [NTB], never the fillet — PASS

```
$ price --item "chicken breast 5kg"
Halal Chicken Breast – (5kg)
  not tracked at Woolworths — missing list [NTB]
  🔪 Dunya (site)  $54.99 / 5kg pack = $11.00/kg
  🏆 Best local: $11.00/kg — Dunya (site)
  ⏱️ 2026-09-11 · [CODE] = sheet Item_Code
```

Routed to the 5kg row; the fillet row does NOT appear.

## 4. FULL FORMAT MATRIX — results

Command: `tools/item_audit.py --matrix`, run 12:14–13:02 AUSEST.
Evidence: `item_matrix_2026-09-11_1214.csv` (copied here), stdout in
`matrix_run_stdout.txt`.

**143 items · 545 checks · 343 PASS · 202 non-PASS · 0 quota (429)
failures · 0 errors/timeouts** — no re-run needed; every non-PASS is
classified below. Per-format: exact 143 (1 FAIL) · drift-shuffle 134
(55) · drift-plural 143 (94) · no-halal-prefix 105 (32) ·
code-as-query 14 (14) · nl-price-of 5 (5) · with-halal-prefix 1 (1).

### 4.1 Classification of all 202 non-PASS

**By-design recorded — 14** (`code-as-query`, matrix FINDING-B):
v2 does not treat Item_Codes as lookup keys; every code query answers
bare "Not tracked" — an honest miss, no crash (e.g. `[DRW]`,
`[HSZ]`, `[UGZ]`). Not defects; the gateway agent resolves codes via
`list`/`batch`. (A code-lookup verb is a product decision, not a fix.)

**Generator-mangled queries — 43** (`drift-plural`): the matrix
pluraliser mangles unit/paren tokens ("Halal BBQ Sausages (4kg)s",
"… eachs", "Woolworths Beef Mince 500gs", "Raspberries Punnet 125gs",
"R2E2 Mangoe", "Blueberrie", "Halal Beef Stirs Fry", "Halal Beefs Rib
Eye", "Large Parsley Bunchs", "oregano leave", "Banana Kid 5"). No
matcher should be expected to answer these. Judging artifacts — NOT
defects.

**Judging ambiguity — 1** (`with-halal-prefix`): "halal Woolworths
Beef Mince 500g" — adding a halal prefix to the non-halal WW-branded
row is a nonsensical combination; the reply (halal cluster) is arguably
correct. Not a defect.

**REAL DEFECT D1 — halal prefix is load-bearing (28 bare misses in
`no-halal-prefix` + the same rows fail noun-first in
`drift-shuffle`)**: most Dunya/Merjan rows become UNFINDABLE when the
user omits "halal": `Drumstick`, `Wings`, `Spicy Wings`, `Greek Chops`,
`Greek Lamb`, `Turkish chicken`, `Turkish wings`, `Chicken Drumette`,
`Whole chicken s9/s14`, `Lebanese Chicken`, `Turkish Adana`, `Kofte
skewer`, `Lebanese Kofte`, `Skin Off Drum`, `Beef Marrow Bones`, `Beef
Rump`, `Beef Stir Fry`, `Eye silverside`, `Beef Gravy`, `Beef Osso
Bucco`, `BBQ Blade Steak /kg`, `Flavoured Sausages /kg`, `Sausages
/kg`, `Povi Masima Bucket`, `Marylands Skin-Off`, `Beef Ossobuco`,
plus produce plurals (`Cauliflowers`, `Eggplants`, `Artichokes`,
`Jap Pumpkins`, `Tomatos`, `Cos Lettuces`, `brown onions`…) all answer
bare "Not tracked" — confirmed live post-matrix:

```
$ price --item "Drumstick"
Not tracked
$ price --item "Halal Drumstick"
Halal Drumstick
  not tracked at Woolworths — missing list [VCK]
  🔪 Merjan Brothers Quality Meats  $4.00/kg (special) · min order 5kg for $19.99
  🔪 Dunya (site)                   $7.99/kg
  🏆 Best local: $4.00/kg — Merjan Brothers Quality Meats
```

Only the generic meat-vocabulary terms (lamb necks, goat curry, beef
mince…) and the newly fixed pack rows route without the prefix. This
is the matrix's headline finding: **51 realistic plural/singular
variants and 28 no-prefix forms miss rows real users will ask for.**

**REAL DEFECT D2 — "price of …" / wrong-cluster dump (5
`nl-price-of` + the 1 `exact` FAIL)**: a "price of" prefix or the
WW-row name "Woolworths Beef Mince 500g" makes the CLI dump ~120 price
lines (every local row on the sheet) under a FALSE missing-list header
[EPJ]. Confirmed live post-matrix:

```
$ price --item "price of goat curry"
Not tracked at Woolworths — missing list [EPJ]
  🔪 Merjan Brothers Quality Meats  $4.00/kg (special) · min order 5kg for $19.99
  🔪 Merjan Brothers Quality Meats  $4.00/kg (special) · min order 5kg for $19.99
  … (~120 lines — effectively the whole sheet) …
  🏆 Best local: $4.00/kg — Merjan Brothers Quality Meats
```

The goat-curry rows ARE in the dump but buried; the header code is
wrong; §8 expects a scoped answer. Same dump shape: exact query
"Woolworths Beef Mince 500g" (its own §8 tracked-class answer — WW
display price $13.54 — is never shown).

**REAL DEFECT D3 — cluster answers cite one cousin's code (5
`drift-shuffle` + 4 `no-halal-prefix` "wrong-code" rows)**: drift
queries that hit a multi-row cluster cite the winner's/cousin's code,
not the requested row's: `Fillet Halal Lamb` → [YTB] (neck fillet!)
not [SJG]; `Mince Halal Lamb` → [DSY] not [GVJ]; `Mince Halal Beef` →
[EPJ] not [AUG]; `Lamb Fillet` → [YTB]; `Lamb Mince` → [DSY]; `lamb
Sausages` → [DQP] not [ZRD]; `500g Woolworths Beef Mince` → [EPJ].
Related to observation O-1 (unattributed multi-row lines).

**REAL DEFECT D4 — kofte/kofte spelling fold (from §2.2)**: shows up
in the matrix too ("Halal Lebanese Koftes", "Halal Turkish Koftes"
both bare-miss).

### 4.2 Matrix totals by class

| Class | Checks | Verdict |
|---|---|---|
| PASS | 343 | healthy |
| By-design recorded (code-as-query) | 14 | not defects |
| Generator-mangled queries | 43 | judging artifacts |
| Judging ambiguity (halal+WW-row) | 1 | not a defect |
| D1 no-prefix / realistic-plural / noun-first misses | 129 | REAL |
| D2 price-of / WW-name full-sheet dump | 6 | REAL |
| D3 wrong-cousin code citation | 9 | REAL |
| **Total** | **545** | |

D4 (kofte spelling) overlaps inside the D1 rows. D1 = 50 noun-first
bare (shuffle) + 51 realistic plural fails + 28 no-halal bare.
D2 = 5 nl-price-of dumps + 1 exact (GJZ) dump. D3 = 5 shuffle + 4
no-halal wrong-code rows. Per-row evidence: the CSV.

## 5. Live gateway sample

8 real Telegram messages delivered via
`ssh myvps 'docker exec openclaw-core node /app/openclaw.mjs agent
--channel telegram --to 1594431983 --message "…" --deliver'`.
Verbatim captures: `gw1…gw8_*.txt` in this directory. **8/8 answered
correctly.**

**GW1 — "how much is halal lamb mince" → PASS** (min-order terms shown):

> **Halal Lamb Mince**
> - 🔪 Merjan Brothers — $15.00/kg (special) · min order 2kg for $29.99 · 🏆 best local
> - 🔪 Dunya (site) — $15.99/kg
> - Woolworths: not tracked — missing list [GVJ]
> - ⏱️ checked 2026-09-11
>
> 🔧 Heads up: the CLI had a broken edit in its code overnight (syntax
> error on this box's Python) — I patched it minimally, original saved
> to `/tmp/v2_read.py.bak`. Everything's answering normally again.

(The postscript is real and load-bearing — see §6 three-way sync.)

**GW2 — "price of goat curry" → PASS** (both presentations; the agent
strips the "price of" prefix before the CLI, so D2 does not surface at
the gateway for this phrasing):

> **Goat Curry** [PTU]
> - 🔪 Merjan Brothers — $15.00/kg (special) · min order 2kg for $29.99 · 🏆 best local
> - 🔪 Dunya (site) — $89.99 / 5kg pack = $18.00/kg
> - Woolworths: not tracked
> - ⏱️ checked 2026-09-11

**GW3 — "compare beef mince halal and non halal" → PASS** (twin line +
every halal cluster line attributed to its row — the agent layer
compensates for the CLI's unattributed lines, O-1):

> **Beef mince: halal vs non-halal**
>
> 🥩 **Halal (local)**
> - Dunya 5kg pack [EPJ] — $64.99 = **$13.00/kg** 🏆
> - Dunya regular [AUG] — $15.99/kg
> - Dunya Premium [VFZ] — $17.99/kg
>
> 🛒 **Non-halal (Woolworths)**
> - Beef Mince 500g — $13.54 = $27.08/kg
>
> **Verdict:** halal wins on value, no contest — the 5kg pack is less
> than half Woolworths' per-kg price ($13 vs $27/kg), and even the
> regular pack saves ~$11/kg.
>
> ⏱️ 2026-09-11

**GW4 — "chicken breast 5kg" → PASS** (routes to [NTB], not the fillet):

> **Halal Chicken Breast (5kg)** [NTB]
> - 🔪 Dunya (site) — $54.99 / 5kg pack = **$11.00/kg** · 🏆 best local
> - Woolworths: not tracked
> - ⏱️ checked 2026-09-11
>
> Solid price — cheaper per kg than their breast fillets ($13.99/kg).

**GW5 — "lamb necks" → PASS** (merged row [YCQ]; the agent even
attributes the extra cluster line — again covering O-1):

> **Lamb Necks** (matched: Halal Sliced Lamb Neck [YCQ])
> - 🔪 Merjan Brothers — $15.00/kg (special) · min order 2kg for $29.99 · 🏆 best local
> - 🔪 Dunya (site) — $16.99/kg
> - 🔪 Dunya (site) — $29.99/kg (likely the Neck Fillet BBQ cut)
> - Woolworths: not tracked
> - ⏱️ checked 2026-09-11

**GW6 — "list" → PASS** (110 items, all with codes, grouped per shop).
Full verbatim capture: `gw6_list.txt`. Framing lines:

> 📋 **Missing list** (110 items — all with local price, no Woolworths price yet)
> …
> 📊 110 items (was 105 yesterday — 6 new Merjan lines + Cos Lettuce;
> [ZGK] Halal Lamb Curry left the list)
> ⏱️ 2026-09-11 · [CODE] = sheet Item_Code

**GW7 — "specials" → PASS per spec** (Products_Master col H
"Woolworths_Specials" is empty for ALL 144 rows — verified against the
pre-audit baseline — so "no active specials" is the correct sheet
answer; the verb is scoped to Woolworths specials, not local shops'
"(special)" markers):

> 🏷️ **Specials**
>
> No active specials right now.
>
> (The Banana Kids $2.71 multi-buy from yesterday must have expired
> from the sheet.) Also noted: the Woolworths saved-list API is still
> bot-blocked from this runner — live saved-list checks only work from
> the local window; doesn't affect the sheet.

Note: the parenthetical speculation is agent noise (Banana Kids [PXQ]
is on the sheet at $3.00 with NO special marker — the $2.71 was a
shelf-price snapshot, never a sheet special). Cosmetic.

**GW8 — "batch NTB done" → PASS** (verify-only contract exactly:
names what is still blank, writes nothing):

> [NTB] ✗ not done — still blank: Woolworths price (col D) and search
> keyword (col G)
>
> Halal Chicken Breast 5kg has no Woolworths price/keyword on the
> sheet yet, so it can't be marked done. Give me the price if you've
> got it, or say "live search chicken breast 5kg" and I'll pull
> supermarket prices.

## 6. Final gates

- **Suite**: 698 passed, 0 failed, 0 skipped (39s, anaconda Python
  3.13.9).
- **Parity audit**: ALIGNED (Products_Master ↔ Local_Deals, live sheet).
- **Zero sheet writes**: PASS — post-audit backup 13:20 (`post-audit_sheet_1320.json`)
  is byte-identical to the pre-audit baseline 12:12
  (`baseline_sheet_1215_pre-audit.json`) across all 5 tabs.
- **Three-way sync**: local commit + GitHub push done (see commit);
  evidence dir scp'd to
  `myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/data/test_logs/`
  and md5-verified. **NAMED EXCEPTION — `core/v2_read.py`:** the VPS
  container runs the bot's own 03:22 hot-patch (md5 3cf8a87c…, adds
  `_note_text()`) because git-HEAD's inline f-string (md5 457d9b22…,
  line 511) is a SyntaxError on the container's Python 3.11.2 (local
  3.13.9 accepts it). The canonical file was deliberately NOT pushed —
  it would re-break the live bot. The next fix session must land the
  container-safe refactor upstream (fix list #5) so all three converge.

## 7. FIX LIST for the next fix session

1. **[D1] Halal prefix is load-bearing + realistic plural/singular +
   noun-first forms miss rows** (P1 — largest real-user impact):
   `price --item "Drumstick"` → bare "Not tracked" while
   `price --item "Halal Drumstick"` answers [VCK]. Same for Wings,
   Greek Chops/Lamb, Turkish chicken/wings, Chicken Drumette, Whole
   chicken s9/s14, Lebanese Chicken, Turkish Adana, Kofte skewer,
   Lebanese Kofte, Skin Off Drum, Beef Marrow Bones, Beef Rump, Beef
   Stir Fry, Eye silverside, Beef Gravy, Beef Osso Bucco, the /kg
   rows, Povi Masima Bucket, Marylands Skin-Off — plus realistic
   plurals/singulars on BOTH meat and produce (Cauliflowers,
   Eggplants, Artichokes, brown onions, Drumsticks…) and noun-first
   order (Pumpkin Jap, Lettuce Cos). ~129 matrix rows. Fix direction:
   make the name matcher truly halal-optional, plural-folded, and
   order-free for ALL rows (not just vocabulary terms + pack rows).
   Repro: any command in §4.1 D1 / the CSV.
2. **[D2] "price of …" and the exact WW-row name trigger a full-sheet
   dump with a false header** (P1): `price --item "price of goat
   curry"` → ~120 price lines headed "missing list [EPJ]" (§4.1 D2
   quote). Same dump for exact-name `Woolworths Beef Mince 500g`
   (GJZ) — its own §8 tracked-class answer (WW display price) is
   never shown. The gateway agent currently masks the "price of"
   case (GW2), the CLI must be fixed at its layer. Repro: the two
   commands above.
3. **[D4] kofta/kofte spelling fold** (P2): `price --item "Turkish
   Kofte (5kg)"` → bare "Not tracked" (sheet: "Halal Turkish Kofta –
   (5kg)" [KWM]); also "Lebanese Kofte(s)", "Kofte skewer(s)". Fix
   with the same fold family as plurals. Repro: `probe_kwm_halal-kofte.txt`.
4. **[D3/O-1] Cluster answers cite one cousin's code and render extra
   rows unattributed** (P2): drift queries cite the wrong row's code
   (Fillet Halal Lamb → [YTB] not [SJG]; Mince Halal Lamb → [DSY]
   not [GVJ]; lamb Sausages → [DQP] not [ZRD]); multi-row answers
   print sibling prices with no row attribution (lamb necks → extra
   $29.99 line; beef mince → three Dunya lines). The gateway agent
   compensates today (GW3/GW5) but the CLI output should attribute
   each line to its row/code. Repro: `reg_1_lamb_necks_reply.txt`,
   `reg_3_beef_mince_reply.txt`, matrix CSV D3 rows.
5. **[INFRA] Land the container-safe `_note_text()` refactor
   upstream** (P1 — sync blocker): git-HEAD `core/v2_read.py` line
   511 uses an f-string with nested same-type quotes — SyntaxError on
   the VPS container's Python 3.11.2. Only the bot's own 03:22
   hot-patch (in the container, original at `/tmp/v2_read.py.bak`)
   works there. Fix = commit the clean `_note_text()` version to
   GitHub + scp to the VPS so local/GitHub/VPS converge; add a
   CI-style syntax check under Python 3.11 so this class of break
   never ships again.
6. **[P3, product question — not a defect] `specials` verb ignores
   local shops' "(special)" markers**: GW7 answered "No active
   specials" while ~20 Merjan/Dunya/produce rows carry "(special)"
   on the sheet (verified: col H is empty, so the verb is per-spec).
   Ask the user whether `specials` should cover local-shop specials.

**Empty-fix-list goal NOT met this round** — items 1–5 above are real
and reproducible; none blocks the daily user flow (the gateway agent
masks most CLI-layer gaps), but items 1, 2 and 5 should land before
the next full-matrix certification.
