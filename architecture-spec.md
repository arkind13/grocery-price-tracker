# Architecture Spec — Always-On Woolworths Display Discounts + Home-Brand Classification

- **Date:** 2026-08-27
- **Stage:** 01 Architect (this doc) → 02 Plan → 03 Code → 04 Architect Checker
- **Status:** Ready for planning. User confirmed all clarifying questions (see §2).

---

## 1. Goal (plain language)

Whenever a **Woolworths price is shown to the user** — in any basket comparison,
any standalone live search, any lookup that reads prices from the Google Sheet,
specials reports, or the Wednesday Telegram specials report — the displayed
price must be discounted:

- **5% off every Woolworths price** (no brand requirement), PLUS
- **an additional 5% off Woolworths home-brand items** (applied on top of the
  base 5%).

The Google Sheet always keeps **raw** prices. Discounts are applied **at
display time only**.

Additionally, when **new items are written to the sheet**, if the item's brand
is a Woolworths home brand, the **Brand cell (Col G) must contain the literal
text `Home`** (capital H).

Coles and Aldi prices are never discounted by this feature.

---

## 2. Confirmed decisions (from user)

| # | Question | Answer |
|---|----------|--------|
| 1 | Extra home-brand discount amount | Additional 5% (on top of the base 5%) |
| 2 | Always on? | Yes — automatic on every displayed Woolworths price, incl. specials |
| 3 | Brand list | "Clean" and "Essentials" are two separate names; "La Meida" and "La Mesita" spellings confirmed; plain "Woolworths" brand included |
| 4 | Brand cell | Sheet column titled "Brand" (Col G, 0-based index 6) gets literal `Home` |
| 5 | Storage | Sheet stores raw prices only; discount only when showing prices |

**Default choice flagged for review (§5):** the two 5% discounts compound
(5% then 5% on the reduced price ⇒ 9.75% total), consistent with how the
existing `apply_extra_discount` already compounds on the post-Team-Discount
total. If a flat 10% is preferred, change is one constant (§5).

---

## 3. Canonical home-brand list (32 entries)

Single source of truth: `core/woolworths_discounts.py` (replaces the legacy
`HOME_BRAND_LABELS` tuple).

```
Apollo             Balnea             Baxters
Bell Farms         Clean              Essentials
Farmer's Own       Help at Hand       Hillview
Inspire            La Gina            La Meida
La Mesita          Lantern Alley      Little Ones
Little Wishes      Lolly Go Round     Macro Wholefoods Market
Market Value       Plantitude         Ready Chef
Smiling Tums       Smitten            Strength Meals Co
Strike             Sushi Izu          The Odd Bunch
Thomas Dux         Voeu               Woolworths BBQ
Woolworths Cook    Woolworths (plain brand itself)
```

- The legacy substring labels `"gold"` and `"free from"` are **dropped** (not
  in the user's list; `"gold"` as a substring also false-positives on
  third-party brands like "Golden Circle").
- `"macro"` is kept as a short-form alias for "Macro Wholefoods Market" (the
  live API often returns just `Macro`).

---

## 4. Detection rules (`is_woolworths_home_brand`)

Keep the existing function name and signature
`is_woolworths_home_brand(product_name: str, brand: str) -> bool` (imported by
`price_comparator` and `sheet_analyst`) but reimplement the matching:

1. **Normalize** both inputs: lowercase, strip punctuation/apostrophes
   (`Farmer's Own` → `farmers own`), collapse whitespace.
2. **Brand-field match (primary):**
   - normalized brand `== "home"` (the sheet Col G marker) → home brand;
   - normalized brand `in` the normalized list (exact equality, NOT substring)
     → home brand;
   - normalized brand starts with `"woolworths"` → home brand (covers plain
     `Woolworths`, `Woolworths BBQ`, `Woolworths Cook`);
   - normalized brand `== "macro"` → home brand (short-form alias).
3. **Product-name fallback (only when the brand field is empty):** the
   normalized product name **starts with** a label from the list (word
   boundary), e.g. "Macro Rolled Oats 1kg", "The Odd Bunch Apples". This
   rescues old sheet rows whose Col G is blank but Col A leads with the brand.
   Leading-position matching avoids the old false positives (`Golden Circle…`,
   `Mr Clean…` no longer match anything).

Exact/word-boundary matching everywhere — no free substring search.

---

## 5. Discount math

New constants in `core/woolworths_discounts.py`:

```python
WOOLWORTHS_BASE_DISCOUNT = 0.05      # every Woolworths price
HOME_BRAND_EXTRA_DISCOUNT = 0.05     # additional, home-brand items only
```

- Regular item: `final = round(price * 0.95, 2)`
- Home-brand item: `final = round(round(price * 0.95, 2) * 0.95, 2)`
  (⇒ ≈ 9.75% total — **compounding default, see §2**; flat 10% would be
  `round(price * 0.90, 2)` — one-line change if user prefers).
- Round per item to 2 dp, then sum for totals (same convention as the
  existing `apply_team_discount`).
- Applies to whatever price is displayed — shelf price or promo/special price.
- The monthly `--extra-discount` flag and its usage tracker are a **separate,
  unchanged** mechanism.

New public helpers (single source of truth for every display site):

```python
discounted_woolworths_price(price: float, is_home: bool) -> dict
# {"original", "final", "savings", "is_home"}

format_discounted_price(price: float, is_home: bool) -> str
# "$4.28 (Home 9.75% off, was $4.75)"  /  "$4.75 (5% off, was $5.00)"
# exact wording finalised in code stage; must show discounted price
# prominently + raw price + which discounts applied
```

`apply_team_discount(items, store)` is **replaced** by
`apply_woolworths_discounts(items, store="woolworths")` with the new
semantics (base 5% on ALL items, extra 5% on home brands); per-item result
dict gains `"home_extra_applied"`. Update all callers + tests.

---

## 6. Where discounts apply (display surfaces — ALL of them)

| # | Surface | File / function | Notes |
|---|---------|-----------------|-------|
| 1 | Basket compare item table + totals + discount summary | `core/price_comparator.py` `compare_basket`, `format_report` | Woolworths column shows discounted price; Raw Total column stays raw; Final Total = discounted; cheapest store computed on finals (already is) |
| 2 | `search` live table + "Cheapest" line | `grocery_price_cli.py` `_cmd_search` | Each WW row discounted using its own `item.brand`; cheapest calc uses discounted values |
| 3 | `recipe` | goes through `compare_basket` | Covered by #1 |
| 4 | `specials` Mode B (sheet) | `core/specials_reporter.py` `get_active_specials` (+ return brand from Col G), `format_specials_report` | WW rows discounted |
| 5 | `specials` Mode A (live saved-list) | `grocery_price_cli.py` `_cmd_specials` | Discounted per item brand |
| 6 | `specials-scan` | `grocery_price_cli.py` `_cmd_specials_scan` | WW sale prices discounted (5% + home extra via brand) |
| 7 | Wednesday specials Telegram report | `grocery_price_cli.py` `_cmd_wednesday` Step 8 | Display-only discount |
| 8 | `map` / lookup price prints ("Prices:" lines, live item lists) | `grocery_price_cli.py` `_format_prices`, `_map_unmatched_item`, `_resolve_and_print_unmatched`, `_resolve_and_print_store`; `core/lookup.py` `__main__` | `_format_prices` gains a brand param; per-live-item prints use each item's own brand |
| 9 | `rewards` price column | `grocery_price_cli.py` `_cmd_rewards` + `get_bonus_rewards` | Only when the price is attributable to Woolworths (Col D); add store + brand to reward dicts |
| 10 | `analyze` | `core/sheet_analyst.py` | **Unchanged** — explicitly labeled "(pre-discount)"; only the home-brands count improves automatically via the new matcher |

The `--team-discount/--no-team-discount` flag stays as the escape hatch
(default ON = base + home extra; OFF shows raw prices). SKILL.md documents it
as always-on by default.

---

## 7. What does NOT change

- **Sheet writes stay raw:** `sync_prices`, `update_single_price`,
  `add_product_row` price values — raw prices, always.
- **Extractors** (`woolworths_extractor.py`, `coles_extractor.py`,
  `doc_parser.py`) — no changes; they already return raw prices + `brand`.
- Coles / Aldi pricing paths.
- Monthly extra-discount tracker (`--extra-discount`) and
  `data/woolworths_discount_usage.json`.
- Lookup/matching logic (`lookup.py` chain, `name_matcher.py`) — brand already
  flows through `LookupResult.brand` / row dicts.
- `recipe_resolver.py`, `schema_upgrade.py`, `telegram_gateway/`, legacy
  `app.py` / `local_sync.py`.

---

## 8. File-by-file change plan + boundaries

**IN SCOPE (only these files may be modified):**

| File | Change |
|------|--------|
| `grocery-price-tracker/core/woolworths_discounts.py` | §3 list, §4 matcher, §5 math + helpers; update `format_discount_report` (base line for all items + home-extra line); keep monthly tracker untouched |
| `grocery-price-tracker/core/price_comparator.py` | `compare_basket` → `apply_woolworths_discounts`; report fields (`team_discount_savings` = base savings on all WW items, new `home_extra_savings`, `home_brand_count`); `format_report` item rows discounted (remove the inline `* 0.95` recompute), discount section shows both lines |
| `grocery-price-tracker/core/specials_reporter.py` | `get_active_specials` returns `brand`; `format_specials_report` discounts WW rows; `get_bonus_rewards` returns `store` + `brand` |
| `grocery-price-tracker/core/sheets_sync.py` | **`add_product_row` only:** before writing Col G, map brand via `is_woolworths_home_brand` → write literal `"Home"` instead of the raw brand name. No other write-path changes |
| `grocery-price-tracker/core/sheet_analyst.py` | No code change required (new matcher flows in). Only touch if brand-column resolution needs the "Brand" header name |
| `grocery_price_cli.py` (parent folder) | `_cmd_search`, `_cmd_specials` (Mode A), `_cmd_specials_scan`, `_cmd_wednesday` (Step 8), `_format_prices` (+brand param) and its call sites, `_cmd_rewards`; new `backfill-home-brands` subcommand (§9) |
| `grocery-price-tracker/core/lookup.py` | `__main__` display only (optional, via shared helper). No chain logic changes |
| `claw-skills/grocery-price/SKILL.md` | Document always-on WW discounts, that displayed WW prices are discounted, the `Home` brand-cell rule, and that `--no-team-discount` shows raw |
| `grocery-price-tracker/README.md` | New subsection under Grocery Price Tracker + Col G row in schema table (done with this spec) |
| Tests: `tests/test_woolworths_discounts.py` (new), `test_comparator.py`, `test_cli.py`, `test_sheets_sync.py`, `test_lookup.py` (only if price-print assertions change) | §10 |

**OUT OF SCOPE:** everything else — extractors/, name_matcher.py,
recipe_resolver.py, schema_upgrade.py, missing_items_tracker.py,
telegram_gateway/, ai-studio/, all other claw-skills, `.env` handling.

---

## 9. One-time backfill (small, recommended)

New CLI subcommand `backfill-home-brands [--dry-run] [--overwrite]`
(patterned on `backfill-keywords`): rewrite Col G to `Home` for existing rows
whose current brand (or leading Col A name, when Col G is blank) matches the
§3 list. Idempotent; default skips non-empty non-matching cells. This
normalises old rows so the Brand cell is a reliable home-brand marker.
Detection works even without backfill (brand names still match), so this is a
data-hygiene step, not a functional dependency.

---

## 10. Test plan

New `test_woolworths_discounts.py`:
- All 32 list entries match (plus `Woolworths` prefix variants, `Macro`
  short form, `Home` marker, apostrophe/whitespace normalization).
- Negatives: `Golden Circle`, `Mr Clean`, `Coles` brand, empty inputs,
  mid-name occurrences ("Juice Gold Blend"), non-WW stores.
- Math: 5% regular, compounding home (e.g. $5.00 → $4.50), rounding per item
  then sum.

Update:
- `test_comparator.py` — new totals/savings semantics (5% on all WW items +
  extra on home), per-row discounted strings, cheapest-store on finals.
- `test_cli.py` — `search`/`specials` outputs show discounted WW prices +
  raw; Coles rows unchanged.
- `test_sheets_sync.py` — `add_product_row` writes `Home` for home brands,
  raw brand otherwise; price cell stays raw.
- `test_lookup.py` — only if "Prices:" output assertions change.

Full suite (`137+` tests) must pass before deploy.

---

## 11. Deployment notes

1. Test locally with Anaconda Python (README "Edit → test locally" workflow).
2. `scp` BOTH roots to the VPS: `grocery_price_cli.py` →
   `/home/ubuntu/openclaw/tasks/ai-tools/` and the changed
   `grocery-price-tracker/core|tests` files + `claw-skills/grocery-price/SKILL.md`
   → their mirrored paths.
3. `docker restart openclaw-core` (skills reload), then run the Telegram test
   query from the README.
4. Optionally run `backfill-home-brands --dry-run`, review, then run live.

---

## 12. Open item (non-blocking)

- §5 compounding (9.75%) vs flat 10% for home brands. Default: compounding.
  One-constant change if the user prefers flat 10%.
