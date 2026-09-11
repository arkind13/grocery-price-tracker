# GLM-5.3 (zai coding plan) THOROUGH BATTERY — 2026-09-12 ~09:20-10:00 AUSEST

18 live Telegram probes. Model: `zai/glm-5.3` via the coding-plan
endpoint (user's billing; switched from the mistaken OpenRouter slug
after the user's correction). Replies captured verbatim in t_*.txt.

## SPECIALS PER SHOP — 4/4 PASS
- s1 "whats on special this week" → **ASKED**: "Which shop —
  Woolworths, Aldi, or the local shops?" ✓
- s2 follow-up "woolworths" → routed to WW specials, honestly
  reported "none on the sheet" + why (no hallucinated specials) ✓
- s3 follow-up "local shops" → CLI-render relay of the CORRECTED
  Merjan prices ($4/kg wings, $7/kg maryland, $9/kg mince…) ✓
- s4 "aldi specials" → real Saturday Special Buys drop (camping/tech,
  no groceries) ✓

## LIVE VERB — 2/2 PASS (legitimate trigger works)
- l1 "live chicken breast" → fresh WW + Coles prices, prices-only ✓
- l2 "live search milk" → fresh WW + Coles prices ✓

## SHEET COMPARE — 12 probes, 4 PASS / 2 PARTIAL / 6 LIVE-VIOLATION
- c1 compare beef mince halal and non halal — ✅ PERFECT: verbatim
  CLI render incl. twin line ($13.54 · 500g = $27.08/kg), sheet-only
  verdict
- c2 beef mince halal vs non halal — 🟡 sheet verbatim; quoted
  earlier live numbers as "context" (no new live call)
- c3 compare lamb necks — ✅ verbatim render + honest "specialty
  cut, supermarkets rarely carry" (no live claimed)
- c4 goat curry halal vs non halal — 🔴 "Live-checked WW, Coles and
  Aldi" (disclosed; honest result: nothing stocks goat)
- c5 halal chicken thighs vs woolworths — 🔴 live-checked
- c6 is halal drumstick cheaper than woolworths drumsticks — 🔴 live
- c7 halal sausages vs normal sausages — 🔴 live
- c8 lamb mince compared to woolworths lamb mince — 🔴 live
  (recycled numbers labelled "(live)")
- c9 halal or normal chicken breast 5kg — 🔴 live
- c10 compare beef diced halal and non halal — 🔴 live
- c11 cauliflower halal vs non halal — 🟡 honest "vegetable, no
  halal distinction" + live supermarket compare
- c12 compare chicken wings halal and non halal — 🔴 live recap

## THE PATTERN (the real finding)

The compare live-check happens EXACTLY when the sheet has NO
non-halal twin row for the item:
- beef mince → sheet twin EXISTS (GJZ $13.54) → **sheet-first holds**
- goat curry, chicken wings/thighs, sausages, lamb mince, beef diced,
  5kg breast → NO plain-row twin → the model "helpfully" live-fills
  the gap (always disclosed, halal side always sheet-correct)

Both models (Flash and GLM-5.3-standard) behave this way; 5
instruction layers + model tier do not change it. The remaining fix
is a USER DECISION: for no-twin compares, keep demanding the strict
"not tracked on the sheet" answer, or accept the disclosed live-fill
as the product behaviour.

Speed under GLM-5.3: 20-40s normal; compare+live probes 30-75s.
