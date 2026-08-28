# Test Results — "(was $x)" shown only for genuine specials (03 Code)

- **Date:** 2026-08-28
- **Executed by:** 03 Code Agent (direct edit mode — no plan/architect flow)
- **Environment:** Windows PowerShell 5.1, Anaconda Python (`$env:PYTHONIOENCODING="utf-8"` set for every run)
- **Defect (user report):** Telegram compare message showed `🟢 Woolworths $3.61 (was $4.00)` for a NON-special home-brand item. The always-on team discount (5% + 5% home-brand) was being annotated as a "(was $x)" price on every Woolworths line.

---

## Root cause

`core/woolworths_discounts.py::format_discounted_price()` always rendered
`"(5% off, was $X)"` / `"(Home 9.75% off, was $X)"`, and every display
surface (compare, search, lookup, specials, rewards, specials-scan,
Wednesday report) called it. The "was" therefore reflected the team
discount, not a real special.

## Fix

1. `format_discounted_price()` now returns ONLY the discounted price
   (e.g. `$3.61`). No team-discount "was" suffix anywhere.
2. New helper `was_price_from_special_desc()` extracts the GENUINE
   store WasPrice from specials text of the form `"Was $X.XX"` (both
   store extractors emit this). Free-text descs (`"Half Price"`,
   `"2 for $4.50"`) yield `None`.
3. `core/price_comparator.py::format_report()` — WW and Coles item lines
   append `(was $x)` ONLY when the store reports the item on special
   with a WasPrice.
4. `core/lookup.py` CLI print — same rule for the Woolworths segment.
5. All other surfaces (search 🏷️ suffix, specials `·` desc,
   specials-scan Regular column, Wednesday specials detail) already
   carry the genuine specials text and now show clean discounted
   prices.

Discount MATH is unchanged: 5% base + compounded 5% home-brand extra,
display-time only, sheet still stores raw prices.

---

## Test runs (all with `python -m unittest`)

| Run | Module(s) | Result |
|---|---|---|
| 1 | `tests.test_woolworths_discounts` + `tests.test_comparator` + `tests.test_telegram_format` | **PASS** — Ran 79 tests, OK |
| 2 | `tests.test_cli` + `tests.test_lookup` + `tests.test_name_matcher` + `tests.test_sheets_sync` | **PASS** — Ran 108 tests, OK |
| 3 | Full suite `unittest discover -s tests` | 229 tests: 8 pre-existing failures, all in `tests/test_extractors.py` |

### Pre-existing failure check (not caused by this change)

`git stash push` → clean HEAD → `unittest tests.test_extractors` →
**FAILED (failures=4, errors=4)** — identical 8 failures → `git stash pop`.
Same set documented in the previous test.md baseline (saved-cookie env
state + extractor/test drift). No NEW failures vs baseline.

### Updated / added test cases (all PASS)

- `test_format_discounted_price_plain_no_was` — formatted price is
  exactly `$4.51` / `$3.80`, no bracket (replaces
  `test_format_discounted_price_shows_both_prices`).
- `test_was_price_from_special_desc` — `"Was $4.50"`/`"was $24.50"`/
  `"WAS $3.00"` parse; `"Half Price"`, `"2 for $4.50"`, `""`, `None`
  → None.
- `test_format_report_was_only_for_genuine_specials` — REGRESSION test:
  special items show `(was $4.00)` / `(was $2.90)` (WW + Coles), regular
  item shows none; `(was $4.00)` occurs exactly once.
- `test_format_report_contains_discount_lines` — updated: no
  `(was $4.00)` / `(Home 9.75% off` on the item line; raw $4.00 only in
  the totals table.
- Specials-reporter tests — discounted price only, genuine desc
  ("Half Price"/"Special") rides along, no team "was".
- `test_search_cheapest_uses_discounted_ww`, rewards test, Wednesday
  specials test — clean discounted prices, no team "was".

---

## End-to-end smoke test (user's exact scenario)

File-based script (avoids PowerShell `$` interpolation), fake report
reproducing the Telegram example:

```
🛒 BASKET COMPARISON
━━━━━━━━━━━━━━━━━━━━

1. fetta cheese  🏠
   🟢 Woolworths  $3.61
   🔴 Coles       $2.50

2. bega fetta crumbled
   🟢 Woolworths  $2.85 (was $4.00)
   🔴 Coles       $2.50 (was $2.90)
...
🏆 Cheapest: Coles — you save $1.46 (vs Woolworths)
🏷️ WW discounts: −$0.54 (5% all $0.35 + 🏠 home extra $0.19)
----- assertions -----
SMOKE TEST PASS
```

- Non-special home-brand item: discounted price only — **no "(was $4.00)"** ✅
- Genuine special: store WasPrice shown ✅
- Discount math unchanged (4.00 → 3.80 → 3.61) ✅

Note: a first inline `python -c` smoke run misleadingly showed no
`(was $4.00)` — PowerShell double-quote `$`-interpolation/escaping had
mangled the input string (`Was \$4.00`). File-based rerun confirmed the
code correct. Lesson: never smoke-test `$`-containing strings via
PowerShell inline `-c`.

## Status: PASS (fix verified; deployment via scp + docker restart follows)

---

## Deployment & E2E verification (VPS)

**Sync (scp, branches diverged — no git pull on VPS):** md5-verified local↔VPS
for `core/woolworths_discounts.py`, `core/price_comparator.py`,
`core/lookup.py`, `core/specials_reporter.py`, `core/telegram_format.py`,
`grocery_price_cli.py` — all 6 match.

**Docker:** `openclaw-core` restarted (twice: after code sync and after
skill sync) — `Up (healthy)`, gateway health OK, Telegram configured.

**In-container CLI (bind-mount live, new code):**
- `compare --items "fetta cheese"` → `🟢 Woolworths  $3.61` — NO "(was $4.00)" ✅
- `compare --items "macro milk"` → `🟢 Woolworths  $4.65` — NO "(was $5.15)" ✅
- `compare --items "birds eye frozen peas"` → `🟢 Woolworths  $5.42` — NO was ✅

**Telegram E2E (`openclaw.mjs agent --deliver`):**
1. First test — agent re-worded CLI output and re-injected "(was $4.00)".
   Root causes found and fixed:
   - **`claw-skills/grocery-price/SKILL.md` itself documented the OLD
     bracket format** (`$4.51 (Home 9.75% off, was $5.00)`) — the agent
     imitated it. Section rewritten: prices are printed PLAIN, "was" is
     reserved for genuine specials. Also added: Raw column is NOT a "was"
     price; concrete good/bad relay example; price lines must be kept
     exactly as printed.
   - Session memory of pre-fix turns reinforced the pattern → verified
     with isolated sessions (`--session-id fresh-was-fix-test-*`).
2. Isolated-session tests after the skill fix:
   - Live-search path: clean relay, no fabricated was-annotations ✅
   - Sheet path (fetta cheese): `Woolworths: $3.61` with discount
     explained in prose — **no false "(was $x)" special price** ✅

Note: `claw-skills/` lives outside the git repo (parent dir is not a
repo) — it is scp-synced only, per the README deployment workflow.

## Final status: PASS — fixed, tested, deployed, verified on Telegram

---

# Run 2 — discount narration removed + TEAM_DISCOUNT_ENABLED master switch

- **Date:** 2026-08-28 (follow-up user request)
- **Requests:** (1) agent must stop narrating "5% team discount…" in every
  reply — it's known by default; (2) a central on/off switch so prices
  automatically revert to original Woolworths prices when someone without
  the team discount wants them.

## Changes

1. **`core/woolworths_discounts.py`** — new `TEAM_DISCOUNT_ENABLED = True`
   master switch (single on/off point, documented inline). When `False`:
   - `format_discounted_price()` returns the raw original price;
   - `apply_woolworths_discounts()` flags everything unapplied;
   - every surface (compare, search, recipe, specials, specials-scan,
     rewards, map/lookup, Wednesday report) auto-reverts with zero other
     code changes.
2. **`core/price_comparator.py`** — `compare_basket(team_discount=None)`
   now follows the switch; True/False still force per-call behaviour.
3. **`grocery_price_cli.py`** — `--team-discount` default changed True→None
   (None = follow switch; explicit flags override); recipe path follows the
   switch; `search` cheapest-store math switches between discounted and raw.
4. **`claw-skills/grocery-price/SKILL.md`** — new hard rule: NEVER narrate
   or explain the team discount in replies; prices are relayed as printed.
5. **`README.md`** — master switch documented.

## Answer to "how many changes to toggle?"

ONE line: set `TEAM_DISCOUNT_ENABLED = False` in
`grocery-price-tracker/core/woolworths_discounts.py` (then scp that one
file to the VPS if toggling in production). Everything reverts
automatically; flip back to `True` to re-enable. Per-call CLI flags
(`--no-team-discount` / `--team-discount`) work regardless.

## Test runs

| Run | Module(s) | Result |
|---|---|---|
| 1 | discount/comparator/cli/telegram_format/lookup/matcher/sync modules | **PASS — Ran 191 tests, OK** (incl. 4 new switch tests) |
| 2 | Smoke (file-based, patch switch): OFF → raw $4.00 everywhere, no discount blocks; ON → $3.61 + discount tail | **SMOKE TEST PASS** |

## Deployment

scp to VPS: `core/woolworths_discounts.py`, `core/price_comparator.py`,
`grocery_price_cli.py`, `claw-skills/grocery-price/SKILL.md` (md5-verified)
→ `docker restart openclaw-core` → E2E Telegram check that discount
narration is gone.

## Status: PASS

---

# Run 3 - restore TROPHY-style comparison emojis in Telegram replies

- Date: 2026-08-28 (follow-up user request)
- Observation: newest Telegram comparison replies lost the trophy emoji
  styling the user liked. NO icons were stripped from the code - the CLI
  still emits the full set (basket header, WW/Coles store icons, totals,
  discounts, cheapest-trophy, warnings; verified by grep + smoke output).
  The variation came from the OpenClaw agent re-wording replies.
- Fix: SKILL.md new rule "ALWAYS keep the comparison icon vocabulary":
  store icons on price lines, trophy NEVER dropped on the cheapest line
  (preferred form: trophy + "Coles is cheaper by" + amount), home-brand/
  specials/warning/totals icons kept; includes the exact preferred reply
  template. Also removed a duplicated bullet block left in the discount
  section by the previous edit.
- Deployed: SKILL.md scp'd to VPS, openclaw-core restarted.
- E2E verified (fresh session, delivered to Telegram):
  bullet WW .61 (home brand) / bullet Coles .50
  trophy line: Coles is cheaper by 1.11
- Status: PASS
