# Architecture Spec — Unified Telegram Message Formatting (Claw Skills)

- **Date:** 2026-08-28
- **Stage:** 01 Architect (this doc) → 02 Plan → 03 Code → 04 Architect Checker
- **Status:** Confirmed by user (2026-08-28) — all §9 decisions approved:
  ① hybrid layout (list-style items + fenced totals block),
  ② store icons 🟢 Woolworths / 🔴 Coles,
  ③ moderate emoji density (headers + store lines only).
  Ready for 02 Plan.
- **Replaces:** previous spec archived as `architecture-spec-woolworths-discounts.md`
  (implemented feature; README reference updated).

---

## 1. Goal (plain language)

Every message the user receives on Telegram from any Claw skill must look
**professional, consistent, and correctly aligned** — today they are plain
markdown, and tables break completely (items and prices scattered across
lines). This is a **display-only** change: same data, same numbers, same
commands, same behavior.

Two concrete problems being fixed:

1. **Broken tables.** Tools print GitHub-flavoured markdown tables
   (`| # | Product | Woolworths | Coles |`). Telegram cannot render markdown
   tables, and its proportional (non-monospace) font breaks space-alignment.
   Result: raw pipes and misaligned columns.
2. **Plain look.** Output is bare `**bold**` markdown and
   `- name: $a -> $b` lines with no headers, dividers, or icons.

---

## 2. Core design decisions

### 2.1 Golden rule — never emit markdown tables

No tool may print a `| col | col |` pipe table to stdout that reaches
Telegram. Two replacements, both guaranteed to work on a phone:

- **List style** for item-by-item data. Each field gets its own line, so
  alignment never depends on the font. Used for compare items, search
  results, specials, discount line items, resolve candidates.
- **Fenced monospace block** for compact multi-column data (totals,
  status matrices). Wrapped in triple-backtick code fences — Telegram
  renders code in a monospace font, so manual padding aligns perfectly.
  Total block width ≤ 34 characters (phone-fit).

### 2.2 Zero-dependency styling (degrade gracefully)

Every visual element must survive **even if the gateway strips all
markdown**. Structure comes from unicode, not markdown:

- Heavy divider `━━━━━━━━━━` under main headers; light `──────────` for sub-blocks.
- Inline separator `·` between related fields.
- CAPS header words (TOTALS, SUMMARY) so sections are scannable without bold.
- Markdown `**bold**` is allowed on header lines only (renders bold when
  supported, harmless when stripped).

### 2.3 Icon language (shared vocabulary across ALL skills)

| Icon | Meaning |
|------|---------|
| 🛒 | grocery / basket comparison |
| 🔍 | search / lookup |
| 🏷️ | specials / discounts |
| 💰 | money / savings |
| 🏆 | cheapest / winner |
| 🏠 | Woolworths home brand |
| ⚠️ | warning |
| ✅ | success / confirmed |
| ❌ | not available / failed |
| 🟢 | Woolworths (green brand dot) |
| 🔴 | Coles (red brand dot) |
| 📊 | totals / report block |
| 🧾 | recipe |
| 🔄 | sync |
| 🤖 | model / LLM pricing skills |
| 📅 | daily digest |
| ⏱️ | timestamp footer |

Icon density: moderate — headers and store lines only, not every line.

### 2.4 Message skeleton (all skills)

```
<ICON> <TITLE IN CAPS>
━━━━━━━━━━━━━━━━━━━━
<body: list-style items and/or fenced totals block>
<TAIL: 🏆 result line, ⚠️ warnings>
⏱️ <optional timestamp footer>
```

---

## 3. The shared module — `core/telegram_format.py`

One canonical "Telegram Style Kit", stdlib-only, no new dependencies.

**Public API (draft):**

| Function | Purpose |
|----------|---------|
| `header(title, icon)` | `🛒 BASKET COMPARISON` + heavy divider |
| `subheader(title, icon=None)` | light divider sub-block label |
| `divider(char, width)` | raw divider line |
| `fenced_table(headers, rows)` | padded monospace table inside ``` fence; truncates to width budget |
| `item_block(index, name, prices, home_brand=False)` | numbered item + store price lines |
| `store_line(store, price, was=None, home=False)` | `🟢 Woolworths  $2.47 (was $2.90)` |
| `kv(label, value)` | `label · value` line |
| `money(n)` | consistent `$x.xx` / `—` formatting |
| `warn(text)` / `ok(text)` / `fail(text)` | ⚠️ / ✅ / ❌ lines |
| `tail(winner, savings, vs=None)` | 🏆 cheapest line |
| `footer(ts=None)` | ⏱️ timestamp line (optional per skill) |
| `truncate(s, width)` | `…`-ellipsis truncation |

**Width budget constants:** `MAX_NAME_WIDTH = 24`, `MAX_BLOCK_WIDTH = 34`
(fenced tables), derived from typical phone rendering of monospace text.

Location: `grocery-price-tracker/core/telegram_format.py`. It is importable
by `grocery_price_cli.py` via the existing bootstrap; sibling tools
(pricing, expenses, digest) add the same 3-line sys.path bootstrap.
After the pending migration collapses all tools into this folder, the
import becomes direct.

---

## 4. Affected surfaces (broad fix across claw skills)

### 4.1 Grocery tracker (flagship)

| File | Change |
|------|--------|
| `core/price_comparator.py` | `format_report()` → skeleton + item blocks + fenced totals + 🏆 tail. Remove both pipe tables. |
| `core/woolworths_discounts.py` | `format_discount_report()` → 🏷️ sub-blocks, `was/now` item lines; `format_discounted_price()` keeps `(was $x)` bracket form |
| `core/specials_reporter.py` | specials list → 🏷️ item blocks; rewards → ✅ lines |
| `grocery_price_cli.py` | `search`, `recipe` header, `lookup/map` candidate lists, `sync` report, `update`, `unmapped`, `wednesday` summary prints → style kit |
| Wednesday Telegram reports (DM + topic) | same kit; **no `parse_mode` needed** — zero-dependency styling works as plain text |

### 4.2 Sibling claw tools (style kit adopted via bootstrap)

| Tool | Files | Notes |
|------|-------|-------|
| claude-pricing / gpt-pricing | `openrouter model costs/claude_pricing.py`, `gpt_pricing.py` | 🤖 header + fenced price table (name / input / output $/M) |
| video-pricing | `Openroutervideo.py` | same |
| discounts / free-models | `Discount_github.py`, `free_api.py` | 🏷️ / 🤖 lists |
| daily-digest | `daily-models-digest/daily_digest.py` | 📅 digest cards |
| openrouter-usage | `openrouter_usage/Code_for_usage.py` | 📊 usage table |
| expenses-summary / expenses-view | `Credit_Card_Tracking/category.py` etc. | 💰 category lines |
| budget-sheets | `telegram_gateway/budget_sheets.py` | 💰 balance/allowance lines |
| web-scrape / sketchnote / image-studio | no tabular stdout | light touch: header/footer only if they print prose summaries |

### 4.3 Wednesday reminder (VPS cron)

`telegram_gateway/wednesday_reminder.py` — `send_message()` stays plain
text (no `parse_mode`); the reminder body is restyled with the kit's
unicode vocabulary so it renders identically everywhere.

### 4.4 SKILL.md instruction updates (all 14 skills)

Replace every instruction of the form *"return the Markdown table the
script prints"* with:

> The CLI output is **already Telegram-formatted**. Relay it **verbatim**.
> Never re-wrap it in your own tables, never reformat, never add markdown
> tables of your own.

`grocery-price/SKILL.md` §"How to answer"/§"Output" are the critical
edits; the other 13 get the same relay rule where they describe output.

---

## 5. Message format specs (per surface)

### 5.1 compare / recipe (basket)

```
🛒 BASKET COMPARISON          (recipe: 🧾 RECIPE — <NAME>)
━━━━━━━━━━━━━━━━━━━━

1. Green Capsicum
   🟢 Woolworths  $2.47 (was $2.90)
   🔴 Coles       $3.50

2. Full Cream Milk 2L               🏠
   🟢 Woolworths  $3.32 (was $3.68)
   🔴 Coles       $3.40

📊 TOTALS
╔══════════════════════════╗
║ Store        Raw    Final ║
║ Woolworths  $23.40  $21.75║
║ Coles       $24.10  $24.10║
╚══════════════════════════╝

🏆 Cheapest: Woolworths — you save $2.35
🏷️ WW discounts: −$1.65 (5% all + 🏠 home extra)
⚠️ 1 item missing at Coles
```

Rules: `—` when a store has no price; top-25 cap unchanged with
`… +N more items` line; discounts sub-block (from
`format_discount_report`) only lists home-brand and extra-discount
lines to stay compact — the base 5% is summarised in the 🏷️ tail line.

### 5.2 search / resolve live results

```
🔍 GREEN CAPSICUM — LIVE PRICES
━━━━━━━━━━━━━━━━━━━━
1. Green Capsicum 500g
   🟢 Woolworths  $2.90  🏷️ was $3.50
2. …
```

### 5.3 specials

```
🏷️ SPECIALS — WOOLWORTHS
━━━━━━━━━━━━━━━━━━━━
1. Coke 24-pack
   $19.00  (was $24.50 · save $5.50)
…
📊 12 active specials
```

### 5.4 resolve (map) session items

Numbered candidates list-style (name + score), the action-prompt line
from SKILL.md unchanged, prefixed ✳️.

### 5.5 sync / wednesday summary

Status lines with ✅/❌ per store, 📊 counts block, 📋 unmatched summary.

### 5.6 pricing / usage / digest tools

Same skeleton with their icons; fenced table for per-model rows
(name ≤ 24 chars, truncated).

---

## 6. File boundaries — allowed scope for 02 Plan / 03 Code

**May modify:**

- `grocery-price-tracker/core/telegram_format.py` (NEW)
- `grocery-price-tracker/core/price_comparator.py`
- `grocery-price-tracker/core/woolworths_discounts.py`
- `grocery-price-tracker/core/specials_reporter.py`
- `grocery-price-tracker/tests/` (new `test_telegram_format.py`; update
  tests asserting old pipe-table strings)
- `AI related/grocery_price_cli.py` (prints only — no flag/arg changes)
- `AI related/telegram_gateway/wednesday_reminder.py` (message body only)
- `AI related/telegram_gateway/budget_sheets.py` (output strings only)
- `AI related/openrouter model costs/*.py`, `openrouter_usage/Code_for_usage.py`,
  `daily-models-digest/daily_digest.py`, `Credit_Card_Tracking/category.py`
  (stdout formatting only)
- `AI related/claw-skills/*/SKILL.md` (output-relay instructions only)
- `README.md` (this feature's documentation + archived-spec link)

**Must NOT modify:** sheet schema/writes, discount math, lookup/sync
logic, extractor APIs, `.env` handling, `openclaw.json`, any CLI
subcommand names/flags/exit codes, any data file.

---

## 7. Testing & verification

1. **Unit (new `tests/test_telegram_format.py`):**
   - fenced tables align (equal row widths), width budget respected
   - truncation with ellipsis; empty-input edge cases
   - `money()` formats (`0` → `$0.00`, `None` → `—`)
2. **Regression:** all 191+ existing tests pass; tests that assert the
   old pipe-table strings are updated to the new format (assert content,
   not byte-equality, where practical).
3. **Invariant tests:** assert no emitted report contains `|---` or
   `| # |` (pipe-table ban).
4. **Local smoke:** `$env:PYTHONIOENCODING="utf-8"` then run
   `compare --items "green capsicum"`, `specials`, `search` and eyeball
   alignment.
5. **Faithful Telegram test (after VPS sync):**
   `docker exec openclaw-core node /app/openclaw.mjs agent --channel
   telegram --to 1594431983 --message "compare green capsicum in
   woolworths and coles" --deliver` — visually confirm on the phone,
   including with any markdown-stripping the gateway does.
6. **Windows console caveat:** emojis in local console need
   `PYTHONIOENCODING=utf-8` (already the documented workflow). VPS/Python
   3.11 default UTF-8 — unaffected.

---

## 8. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Gateway strips/alters markdown | Zero-dependency styling (§2.2) — layout survives plain-text rendering |
| Agent re-wraps output in its own tables | Hard rule added to all 14 SKILL.md files (§4.4) |
| Emojis break old terminals/tests | Tests assert content not bytes; console uses UTF-8 env var per workflow |
| Long product names break width budget | `truncate()` with ellipsis, name column ≤ 24 chars |
| Scope creep into behavior | §6 file boundaries; display-only rule enforced by 04 Checker |

---

## 9. Confirmed decisions (user, 2026-08-28)

1. **Hybrid layout** (list-style items + fenced totals block) — ✅ approved.
2. **Store icons** 🟢 Woolworths / 🔴 Coles — ✅ approved.
3. **Emoji density** moderate (headers + store lines only) — ✅ approved.
