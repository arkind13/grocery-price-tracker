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
