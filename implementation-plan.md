# Implementation Plan — Always-On Woolworths Display Discounts + Home-Brand Classification

- **Date:** 2026-08-27
- **Pipeline stage:** 02 Plan (this doc) → 03 Code → 04 Architect Checker
- **Source spec:** `grocery-price-tracker/architecture-spec.md` (250 lines — locked contract)
- **Status:** Ready for the coding model. All decisions below are carried verbatim from the spec; nothing is invented.

---

## 0. Execution contexts (label EVERY command)

| Label | What it is | Who runs it |
|---|---|---|
| `[LOCAL — VS Code]` | Kilo editing files (read/write/edit/grep tools) | Coding model |
| `[LOCAL — PowerShell]` | Windows PowerShell, workspace root `C:\Users\User.DESKTOP-R2G441H\Documents\AI related`. Python = Anaconda: `& "$env:USERPROFILE\anaconda3\python.exe"` | Coding model (tests, compile, smoke) |
| `[LOCAL — PowerShell]` **MANUAL** | git commit/push — **Kilo NEVER runs git** | User |
| `[VPS — SSH]` **MANUAL** | `ssh ubuntu@169.58.107.0` — scp files, docker restart | User |
| `[VPS — container]` **MANUAL** | `sudo docker exec -w /app/tasks/ai-tools openclaw-core …` | User |
| `[Telegram — DM]` **MANUAL** | User sends a test query to `@ClawArkindBot` | User |

Rules carried from project workflow: **one command at a time** for MANUAL steps (present, wait for pasted output, then next). The `grocery-price-tracker/` folder is a **separate nested git repo** — its commits are separate from the main repo.

---

## 1. Locked decisions (from spec §1–§5 — the coding model must honour every one)

1. **Every displayed Woolworths price gets 5% off; home-brand WW items get an additional 5% on top (compounding ⇒ ≈9.75%).**
2. **The Google Sheet always stores RAW prices.** Discounts are display-time only. `sync_prices`, `update_single_price`, `add_product_row` price values stay raw.
3. **Coles and Aldi prices are never discounted by this feature.**
4. **New-row writes:** when the item's brand is a WW home brand, `add_product_row` writes the literal `Home` (capital H) into Col G instead of the raw brand name.
5. **Canonical 32-entry brand list** (spec §3) lives in `core/woolworths_discounts.py` — single source of truth. `"gold"` and `"free from"` are DROPPED. `"macro"` is kept as short-form alias for "Macro Wholefoods Market".
6. **Detection rules** (spec §4): normalize (lowercase, strip punctuation/apostrophes, collapse whitespace); brand-field match by exact equality / `Home` marker / `woolworths` prefix / `macro` alias; product-name fallback ONLY when brand is empty (leading word-boundary match). No free substring search.
7. **`--team-discount/--no-team-discount` stays** as the escape hatch (default ON = base + home extra; OFF = raw). The monthly `--extra-discount` tracker mechanism is UNCHANGED.
8. **`apply_team_discount` is REPLACED** by `apply_woolworths_discounts(items, store="woolworths")`; per-item result dict gains `"home_extra_applied"`. Update all callers + tests.
9. **43/0 registry invariant, extractors, `coles_extractor.py:58` (R-S1), name matching, recipe resolver, schema_upgrade, telegram_gateway — ALL untouched** (spec §7/§8 "out of scope").

### ⚠ SPEC DISCREPANCY — READ BEFORE WRITING TEST MATH

Spec §5 (normative formula, locked default = **compounding**):
`home final = round(round(price * 0.95, 2) * 0.95, 2)` → **$5.00 → $4.51**.

Spec §10's illustration "compounding home (e.g. $5.00 → $4.50)" is **arithmetically wrong for compounding** ($4.50 is flat 10%, the rejected alternative in §12). The plan resolves this in favour of the **§5 formula** (the locked decision). Tests MUST assert **$5.00 → $4.51**. If the user later prefers flat 10%, it is a one-constant change (§12) — do NOT pre-empt it.

**Half-cent warning:** avoid raw prices whose intermediates land on a `.xx5` boundary (e.g. $3.00 → 2.85 → 2.7075) in hand-computed assertions — binary float rounding is ambiguous there. Use the safe values given in §6 of this plan.

---

## 2. Current-state map (verified by the plan agent — line numbers as of 2026-08-27)

| File | Relevant code today |
|---|---|
| `core/woolworths_discounts.py` (297 ln) | `TEAM_DISCOUNT_RATE` L12; legacy `HOME_BRAND_LABELS` substring tuple L15–17; `is_woolworths_home_brand` L31–55 (substring on `name+brand`); `apply_team_discount` L63–103 (5% home-only); `apply_extra_discount` L111–129 (keep); monthly tracker L137–237 (keep); `format_discount_report` L245–297 |
| `core/price_comparator.py` (611 ln) | `BasketItem` L25–45 (has `is_woolworths_home_brand` field); `ComparisonReport` L53–86; `compare_basket` L94–275 (discount block L184–231, imports L118–124); `format_report` L468–569 (item rows RAW; inline `* 0.95` recompute at L531) |
| `core/specials_reporter.py` (245 ln) | `get_active_specials` L21–95 (result dict L87–93, no brand); `get_bonus_rewards` L103–171 (no store/brand in dict L164–169); `format_specials_report` L179–210 (raw prices) |
| `core/sheets_sync.py` (813 ln) | `add_product_row` L660–764; `new_row[6] = brand` at **L745** (the ONLY line region to change) |
| `grocery_price_cli.py` (2095 ln, main repo) | `build_parser` L31–139; `_cmd_rewards` L280–305; `_cmd_search` L388–448 (raw + cheapest on raw); `_cmd_specials` L455–487 (Mode A raw); `_cmd_specials_scan` L566–663; `_cmd_wednesday` Step 8 L1095–1151; `_map_unmatched_item` L1298–1377 (Prices: L1315/1321/1356; live lines L1359–1362); `_format_prices` L1524–1530; `_resolve_and_print_unmatched` L1627–1672; `_resolve_and_print_store` L1675–1704; backfill pattern `_cmd_backfill_keywords` L2006–2074 (`_BRAND_TYPE_COL` L1970) |
| `core/lookup.py` | `__main__` L640–679 (`Prices:` print L674–679) |
| `core/sheet_analyst.py` | brand col via `_find_col(header, "Brand_Type") or 6` at L117/166/203 — positional fallback 6 already covers a "Brand"-titled header ⇒ **NO CHANGE** |
| Tests | `test_comparator.py`: `FakeWorksheet` L25–50, `_make_header` L74–83, team tests L180–218, labels test L308–333, reporter tests L423–455, `test_format_report_contains_discount_lines` L456+. `test_sheets_sync.py`: add_product_row tests L674–750 (asserts Col G `"TestBrand"` at L705). `test_cli.py`: FakeWorksheet L32, search/rewards/specials tests L486–704. `test_lookup.py`: NO price-string assertions (verified) |

---

## 3. Stage-by-stage execution (dependency order; TDD where marked)

### Stage 0 — Preflight + baseline `[LOCAL — VS Code]` / `[LOCAL — PowerShell]`

1. Read (do NOT edit): `core/woolworths_discounts.py`, `core/price_comparator.py`, `core/specials_reporter.py`, `core/sheets_sync.py` (add_product_row region), `grocery_price_cli.py` (sections in §2), `claw-skills/grocery-price/SKILL.md`, tracker `README.md`, the four test files.
2. **Baseline suite (MANDATORY, before any edit):**
   ```powershell
   [LOCAL — PowerShell]  workdir: grocery-price-tracker
   & "$env:USERPROFILE\anaconda3\python.exe" -m pytest tests -q
   ```
   Record the pass count (expect 137+ passing, 0 failed). If the baseline is NOT green, STOP and report — do not start edits on a red baseline.

### Stage 1 — New module core: `tests/test_woolworths_discounts.py` FIRST, then `core/woolworths_discounts.py` `[LOCAL — VS Code]`

**1a. Write the new test file first (TDD — it will fail red until 1b).** Full case list in §6.1.

**1b. Rewrite `core/woolworths_discounts.py`:**

- Replace `HOME_BRAND_LABELS` with:
  ```python
  WOOLWORTHS_HOME_BRANDS = frozenset({
      "apollo", "balnea", "baxters", "bell farms", "clean", "essentials",
      "farmer's own"→normalized "farmers own", "help at hand", "hillview",
      "inspire", "la gina", "la meida", "la mesita", "lantern alley",
      "little ones", "little wishes", "lolly go round",
      "macro wholefoods market", "market value", "plantitude", "ready chef",
      "smiling tums", "smitten", "strength meals co", "strike", "sushi izu",
      "the odd bunch", "thomas dux", "voeu", "woolworths bbq",
      "woolworths cook", "woolworths", "macro",
  })
  ```
  (store entries pre-normalized; 32 canonical names + the `macro` alias).
- New constants: `WOOLWORTHS_BASE_DISCOUNT = 0.05`, `HOME_BRAND_EXTRA_DISCOUNT = 0.05`. Keep `TEAM_DISCOUNT_RATE` as a deprecated alias `= WOOLWORTHS_BASE_DISCOUNT` only if some caller still imports it after Stage 2 — otherwise delete.
- `_normalize_brand_text(s)`: lowercase, strip punctuation/apostrophes (`Farmer's Own` → `farmers own`), collapse whitespace.
- Reimplement **`is_woolworths_home_brand(product_name, brand)`** (same name/signature) per spec §4, in this order:
  1. both empty → False;
  2. normalized brand `== "home"` → True;
  3. normalized brand `in WOOLWORTHS_HOME_BRANDS` (exact equality) → True;
  4. normalized brand starts with `"woolworths"` → True;
  5. brand field empty → normalized **product name starts with** a list label at a word boundary (name == label OR name startswith `label + " "`) → True;
  6. else False.
- New **`discounted_woolworths_price(price: float, is_home: bool) -> dict`** → `{"original", "final", "savings", "is_home"}`; `final = round(round(price*0.95, 2)*0.95, 2)` when `is_home` else `round(price*0.95, 2)`.
- New **`format_discounted_price(price: float, is_home: bool) -> str`** — must show the discounted price prominently + the raw price + which discounts applied (e.g. `$4.51 (Home 9.75% off, was $5.00)` / `$4.75 (5% off, was $5.00)`). Exact wording finalized in this stage; tests assert the two dollar figures + a marker, NOT exact phrasing.
- Replace **`apply_team_discount`** with **`apply_woolworths_discounts(items, store="woolworths")`**: base 5% on ALL items when store == woolworths; extra 5% (compounded) on home brands. Per-item dict: `{name, brand, original_price, discounted_price, applied, home_extra_applied, is_home}`. Non-woolworths store → unchanged prices, `applied=False, home_extra_applied=False`.
- Update **`format_discount_report`**: base line covers ALL WW items (5% off every Woolworths price), plus a separate home-brand extra line. Extend signature with keyword defaults `home_extra_total: float = 0.0, home_brand_count: int = 0` (backward compatible). Show base total and home-extra total.
- Monthly tracker (Section E) and `apply_extra_discount`: **byte-for-byte unchanged**.

**1c. Run the new test file — must be green before Stage 2:**
```powershell
& "$env:USERPROFILE\anaconda3\python.exe" -m pytest tests/test_woolworths_discounts.py -q
```

### Stage 2 — `core/price_comparator.py` `[LOCAL — VS Code]`

1. `ComparisonReport`: add fields `home_extra_savings: float = 0.0`, `home_brand_count: int = 0`. Redefine `team_discount_savings` = **base 5% savings summed over ALL WW items** (update docstring).
2. `compare_basket` L184–231: call `apply_woolworths_discounts` instead of `apply_team_discount`. Compute:
   - `team_discount_savings` = Σ(price − round(price·0.95, 2)) over all WW items;
   - `home_extra_savings` = Σ over home items of (round(price·0.95,2) − final);
   - `home_brand_count` = # home-brand WW items;
   - WW final total = Σ per-item finals (round per item, then sum — spec §5);
   - monthly extra discount still applies ON TOP of the post-discount WW total (unchanged position).
3. `format_report`:
   - Item table WW cell shows the **discounted** price with raw in parens (use `format_discounted_price`); when `team_discount` was OFF (report not applied) show raw only. Coles cell unchanged.
   - **Delete the inline `* 0.95` recompute at L531** — the discount section now consumes the per-item result dicts from the new engine and shows BOTH lines (base for all WW items + home extra).
4. Update `tests/test_comparator.py` (see §6.2), run:
```powershell
& "$env:USERPROFILE\anaconda3\python.exe" -m pytest tests/test_comparator.py -q
```

### Stage 3 — `core/specials_reporter.py` `[LOCAL — VS Code]`

1. `get_active_specials`: resolve brand col via `_find_col(header, "Brand") or _find_col(header, "Brand_Type") or 6`; add `"brand"` to each result dict.
2. `format_specials_report`: for rows with `store == "woolworths"` and a parseable price, display the discounted price (home extra when `is_woolworths_home_brand(name, brand)`); Coles rows raw. Keep top-25 cap.
3. `get_bonus_rewards`: record which store's price column supplied the parsed price → add `"store"` and `"brand"` to each result dict.
4. Update the reporter tests in `test_comparator.py` (§6.2); re-run that file.

### Stage 4 — `core/sheets_sync.py` — `add_product_row` ONLY `[LOCAL — VS Code]`

At L745 replace `new_row[6] = brand` with:
```python
from core.woolworths_discounts import is_woolworths_home_brand  # (module top or local import)
new_row[6] = "Home" if is_woolworths_home_brand(generic_name, brand) else brand
```
**No other write-path changes.** `sync_prices` / `update_single_price` / `mark_not_available` / `set_store_keyword` untouched. Price cells stay raw. Update `tests/test_sheets_sync.py` (§6.3); run it.

### Stage 5 — `grocery_price_cli.py` (main repo) + `core/lookup.py` `__main__` `[LOCAL — VS Code]`

All edits display-only; shared logic comes from `core.woolworths_discounts` helpers — no duplicated math.

1. **`_format_prices(prices, brand="")`** — gains brand param. When `"woolworths" in prices` and a WW discount context applies: show discounted WW (+raw); home extra when `is_woolworths_home_brand("", brand)`… careful: use the name/brand pair available at the call site — pass the product name too where known (signature: `_format_prices(prices, brand="", name="")`). Update call sites: `_map_unmatched_item` (L1315/1321/1356 — `result.brand`), `_resolve_and_print_unmatched` (L1657/1665).
2. **Live-item print loops** (L1359–1362 in `_map_unmatched_item`, L1666–1668 in `_resolve_and_print_unmatched`, L1700–1702 in `_resolve_and_print_store`, `_map_store_item` L1455–1457): each WW line uses the item's OWN `item.brand` → discounted price + raw.
3. **`_cmd_search`**: each WW row discounted via `format_discounted_price(item.price, is_home(item.raw_name, item.brand))`; **cheapest-store calc uses discounted WW values** vs raw Coles. Coles rows unchanged.
4. **`_cmd_specials` Mode A** (L464–485): live saved-list rows discounted per item brand.
5. **`_cmd_specials_scan`**: WW sale prices discounted (5% + home extra via each item's brand). "Regular/Was" column and store savings-% stay as-is.
6. **`_cmd_wednesday` Step 8** (L1116–1131): display-only discount on the specials table. Docx items carry no brand ⇒ use the product-name fallback `is_woolworths_home_brand(item["name"], "")` (leading-label match); base 5% for everything else.
7. **`_cmd_rewards`**: discount the price cell ONLY when `r.get("store") == "woolworths"` (price attributable to Col D), using `r.get("brand")`; other rows raw.
8. **New subcommand `backfill-home-brands [--dry-run] [--overwrite]`** — patterned exactly on `_cmd_backfill_keywords` (L2006–2074), registered in `build_parser`:
   - Read sheet once; per row: brand cell = Col G (`_find_col(header, "Brand") or _find_col(header, "Brand_Type") or 6`).
   - Candidate when: (Col G empty AND leading Col A name matches §3 list) OR (Col G non-empty AND its value matches the list) OR Col G already `Home` (skip — idempotent).
   - `--overwrite`: ALSO rewrite rows whose Col G is non-empty and non-matching when the leading Col A name matches (trust the name over the brand cell). Without it, non-empty non-matching cells are skipped (spec §9 default).
   - `--dry-run`: print the planned-writes table (Row | Col A | Current Col G | Proposed). Live: ONE `ws.batch_update([{"range": f"G{row}", "values": [["Home"]]}, …])`.
9. **`core/lookup.py` `__main__`** (L674–679): route the `Prices:` line through the same shared formatting (discount WW entry using `result.brand`). No chain-logic changes.
10. Update `tests/test_cli.py` (§6.4); check `tests/test_lookup.py` — expected NO changes (no price-string assertions); only touch if an assertion actually breaks.

### Stage 6 — Documentation `[LOCAL — VS Code]`

1. **`claw-skills/grocery-price/SKILL.md`** (main repo): add a short "Woolworths discounts (always on)" section — displayed WW prices include 5% (+ extra 5% home brands ≈9.75% compounded); sheet always stores raw; new home-brand rows get Col G `Home`; `--no-team-discount` shows raw. Update the `compare` row note (default ON) and the `backfill-home-brands` subcommand row in the intent table.
2. **`grocery-price-tracker/README.md`**: new subsection under Grocery Price Tracker describing the feature; update the Col G row in the schema table (literal `Home` for home brands); add `test_woolworths_discounts.py` + updated counts to the tests table.

### Stage 7 — Full local verification `[LOCAL — PowerShell]` (one command at a time)

```powershell
& "$env:USERPROFILE\anaconda3\python.exe" -m py_compile grocery_price_cli.py grocery-price-tracker\core\woolworths_discounts.py grocery-price-tracker\core\price_comparator.py grocery-price-tracker\core\specials_reporter.py grocery-price-tracker\core\sheets_sync.py grocery-price-tracker\core\lookup.py
```
```powershell
[workdir: grocery-price-tracker]
& "$env:USERPROFILE\anaconda3\python.exe" -m pytest tests -q
```
**Gate: FULL suite green — 0 failed, 0 errors. This gate is pass/fail for the whole task.**

Optional sheet-mode smoke (uses local parent `.env`; never print secrets):
```powershell
[workdir: grocery-price-tracker]
& "$env:USERPROFILE\anaconda3\python.exe" ..\grocery_price_cli.py compare --items "milk" --mode sheet
```
Expect WW column discounted + raw in parens; Coles raw.

### Stage 8 — Deploy `[MANUAL — flagged: git, scp, container lifecycle]`

**Kilo must NOT run git/scp/ssh/docker.** Present these to the user ONE AT A TIME and wait for each output. No secrets appear in any of these files — verify diffs before committing.

**8.1 Git — tracker repo (USER, `[LOCAL — PowerShell]`):**
```powershell
cd "C:\Users\User.DESKTOP-R2G441H\Documents\AI related\grocery-price-tracker"
git status   # confirm ONLY: core/{woolworths_discounts,price_comparator,specials_reporter,sheets_sync,lookup}.py, tests/, README.md, implementation-plan.md
git add core/woolworths_discounts.py core/price_comparator.py core/specials_reporter.py core/sheets_sync.py core/lookup.py tests/ README.md
git commit -m "feat(discounts): always-on WW display discounts (5% + 5% home-brand) + Home brand classification"
git push
```

**8.2 Git — main repo (USER, `[LOCAL — PowerShell]`):**
```powershell
cd "C:\Users\User.DESKTOP-R2G441H\Documents\AI related"
git status   # confirm ONLY: grocery_price_cli.py, claw-skills/grocery-price/SKILL.md
git add grocery_price_cli.py claw-skills/grocery-price/SKILL.md
git commit -m "feat(grocery): display-time WW discounts on all price surfaces + backfill-home-brands"
git push origin master
```

**8.3 scp BOTH roots to the VPS (USER, `[VPS — SSH]` from workspace root, one command at a time):**
```
scp grocery_price_cli.py ubuntu@169.58.107.0:/home/ubuntu/openclaw/tasks/ai-tools/
scp grocery-price-tracker/core/woolworths_discounts.py grocery-price-tracker/core/price_comparator.py grocery-price-tracker/core/specials_reporter.py grocery-price-tracker/core/sheets_sync.py grocery-price-tracker/core/lookup.py ubuntu@169.58.107.0:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/core/
scp grocery-price-tracker/tests/test_woolworths_discounts.py ubuntu@169.58.107.0:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/tests/
scp claw-skills/grocery-price/SKILL.md ubuntu@169.58.107.0:/home/ubuntu/openclaw/tasks/ai-tools/claw-skills/grocery-price/
```

**8.4 Container restart (USER, `[VPS — SSH]`) — container lifecycle action:**
```
sudo docker restart openclaw-core
sudo docker ps | grep openclaw-core    # confirm Up
```

### Stage 9 — Post-deploy verification `[MANUAL]`

1. **Telegram test query (USER, `[Telegram — DM]` to `@ClawArkindBot`):** *"Compare prices for milk between Woolworths and Coles"* — Claw's reply must show the WW price discounted (with raw visible) and Coles raw. Also run one specials query.
2. **Backfill dry-run → review → live (USER, `[VPS — container]`):**
   ```
   sudo docker exec -w /app/tasks/ai-tools openclaw-core python3 grocery_price_cli.py backfill-home-brands --dry-run
   ```
   User reviews the planned writes, then re-runs WITHOUT `--dry-run` (add `--overwrite` only if the name-vs-brand-cell override is wanted).

---

## 4. Files NOT to touch (regression guard)

- `grocery-price-tracker/extractors/**` — **especially `coles_extractor.py:58` (R-S1, permanently closed)**
- `core/name_matcher.py`, `core/recipe_resolver.py`, `core/schema_upgrade.py`, `core/missing_items_tracker.py`, `core/sheet_analyst.py`, `core/sheets_client.py`
- `telegram_gateway/**`, `app.py`, `local_sync.py`, `name_importer.py`, `Woolworths_Historical.py`
- Monthly tracker code (Section E of `woolworths_discounts.py`) and `data/woolworths_discount_usage.json`
- All other claw-skills, `ai-studio/`

## 5. Final `git status` expectation (Stage 8 gates)

- Tracker repo: only the §8.1 list. Main repo: only the §8.2 list. Anything else modified ⇒ STOP and revert the stray change.

---

## 6. MANDATORY TEST PLAN — no test may be skipped, filtered away, or marked xfail/skip by the coding agent

**Rules:** (a) full suite must run and pass (`0 failed, 0 errors`) at Stage 7 — no `-k` filtering to dodge failures; (b) every case below must exist and assert concrete values; (c) use the safe numeric fixtures given (they avoid float half-cent boundaries); (d) TDD: `test_woolworths_discounts.py` is written BEFORE the module rewrite.

### 6.1 NEW `tests/test_woolworths_discounts.py` (unittest, mirrors existing FakeWorksheet/mock conventions)

**Detection — positives (all 32 labels via the brand field, exact equality):**
1. `test_all_32_brand_labels_match` — parametrised loop over the canonical list (incl. `"Farmer's Own"`, `"La Meida"`, `"La Mesita"`, `"Macro Wholefoods Market"`, `"Woolworths BBQ"`, `"Woolworths Cook"`, plain `"Woolworths"`, `"The Odd Bunch"`) asserting `is_woolworths_home_brand("anything", label)` is True.
2. `test_home_marker_matches` — brand `"Home"` → True.
3. `test_woolworths_prefix_variants` — `"Woolworths"`, `"woolworths bbq"`, `"WOOLWORTHS COOK"` → True.
4. `test_macro_short_alias` — brand `"Macro"` → True.
5. `test_normalization_apostrophe_whitespace` — `"  Farmer's   OWN "` → True; `"macro wholefoods  market"` → True.
6. `test_name_fallback_leading_label` — brand empty: `"Macro Rolled Oats 1kg"` → True; `"The Odd Bunch Apples"` → True.
7. `test_name_fallback_word_boundary` — `"Essentials"` alone → True; `"Coles Milk"` with brand `""` → False.

**Detection — negatives:**
8. `test_golden_circle_is_not_home_brand` — name `"Golden Circle Pineapple"`, brand `"Golden Circle"` → False (gold dropped).
9. `test_mr_clean_not_home_brand` — `"Mr Clean Magic Eraser"`, brand `"Mr Clean"` → False.
10. `test_mid_name_occurrence_no_match` — brand empty, name `"Juice Gold Blend"` → False; name `"Dairy Farmers Bell Farms Yogurt"` (label mid-name, brand empty) → False — leading position only.
11. `test_coles_and_third_party_brands` — `"Coles"`, `"Bega"`, `"Oatly"` → False.
12. `test_empty_inputs` — `("", "")` → False.
13. `test_brand_field_beats_name` — name `"Woolworths Milk"`, brand `"Bega"` → False (non-empty non-matching brand disables name fallback).

**Math:**
14. `test_regular_item_base_5pct` — `discounted_woolworths_price(5.00, False)` → final 4.75, savings 0.25.
15. `test_home_brand_compounding` — `discounted_woolworths_price(5.00, True)` → **final 4.51** (per §5 formula — see §1 discrepancy note), savings 0.49.
16. `test_home_brand_safe_value` — `(8.00, True)` → 7.60 → final **7.22**.
17. `test_round_per_item_then_sum` — items 5.00 + 8.00 home, 4.00 regular → per-item finals 4.51 + 7.22 + 3.80 = **15.53** (sum of rounded per-item values, not round of the sum).
18. `test_format_discounted_price_shows_both_prices` — output for `(5.00, True)` contains `"4.51"` and `"5.00"` and a home marker; `(4.00, False)` contains `"3.80"` and `"4.00"` (no exact-phrasing lock).

**apply_woolworths_discounts:**
19. `test_base_applies_to_all_ww_items` — mixed basket: every WW item discounted ≥5%; per-item `applied=True` for all, `home_extra_applied=True` only for home.
20. `test_non_woolworths_store_noop` — `store="coles"` → prices unchanged, all flags False.
21. `test_object_and_dict_inputs` — duck-typed ProductItem objects AND plain dicts both work (mirror old `apply_team_discount` contract).

**Tracker regression guard:**
22. `test_monthly_tracker_unchanged` — `can_use_monthly_discount` / `mark_monthly_discount_used` / `monthly_discount_summary` still behave as in `test_monthly_tracker_can_use_then_block` (temp-file patch).

### 6.2 UPDATE `tests/test_comparator.py`

- **Rewrite** `test_team_discount_only_on_home_brands` → `test_base_discount_all_items_plus_home_extra`: fixtures priced **$4.00** (brand `Woolworths`, home) and **$5.00** (brand `Bega`): base savings 0.20 + 0.25 = **0.45**; home-extra 3.80→3.61 = **0.19**; `home_brand_count == 1`; WW final total **3.61 + 4.75 = 7.36**; Coles raw.
- `test_team_discount_toggle_off` — expectations unchanged (raw 3.00 / no flags) but assert `home_extra_savings == 0.0` too.
- **Rewrite** `test_is_woolworths_home_brand_labels` (L308–333): `"Gold Coffee"`/`""` → now **False**; `"Free From Bread"` → now **False** (labels dropped — spec §3); keep True cases: Woolworths brand, `Macro Free Range Eggs` (leading name), `"The Odd Bunch"` brand; `Bega`/empty stay False.
- `test_format_report_contains_discount_lines` — assert BOTH lines (base-5%-all-items line + home-extra line) and that the WW item cell shows the discounted value with the raw price visible; cheapest store still computed on finals.
- Extra-discount tests (L220–285): expectations still hold (10% on post-discount WW total) — recompute: fixture `$3.00` no-brand → base 2.85 → extra 10% of 2.85 = 0.285 → round 0.29… **avoid** the half-cent trap: change fixture price to `$4.00` → base 3.80 → extra savings 0.38; assert accordingly.
- Reporter tests (L423–455): add brand to fixtures; WW row price shows discounted value; `get_bonus_rewards` dicts now carry `store` + `brand`.

### 6.3 UPDATE `tests/test_sheets_sync.py`

- `test_add_product_row_appends_correctly` — `TestBrand` is NOT a home brand ⇒ Col G stays `"TestBrand"` (unchanged) AND add: price cell raw (3.50).
- **NEW** `test_add_product_row_writes_home_literal` — `brand="Macro Wholefoods Market"` (or `"Woolworths"`) ⇒ Col G == `"Home"`; price cell still raw.
- **NEW** `test_add_product_row_home_via_name_fallback` — `brand=""`, `generic_name="Essentials Milk 2L"` ⇒ Col G == `"Home"`.
- Dry-run + validation tests: no changes expected — verify they still pass.

### 6.4 UPDATE `tests/test_cli.py`

- `test_search_with_results_cheapest` (+specials variant): WW rows show discounted price (+raw); **cheapest computed on discounted WW** — construct a case where discounting flips the cheapest store (e.g. WW 3.00 home-brand vs Coles 2.90 → WW final 2.70 wins); Coles assertions unchanged.
- `test_search_woolworths_exception_fallback` — degradation path unaffected.
- `test_rewards_empty_column_o` + populated-rewards test: price shown discounted only when the reward's store == woolworths; otherwise raw.
- `test_compare_sheet_mode_cheapest_store` — mock `compare_basket`/`format_report` are patched ⇒ likely unaffected; verify, adjust only if report-field names changed.
- **NEW** `test_backfill_home_brands_dry_run_and_write` — FakeWorksheet + patched `connect_worksheet`: dry-run plans only matching rows (empty-G name match OR matching-G value; skips `Home` idempotent; skips non-matching non-empty G by default; `--overwrite` applies name-match override); live mode issues ONE `batch_update` of G-cells with `Home`.
- **NEW** `test_wednesday_step8_discounts_display` (light): patch `_extract_woolworths_specials` + `_send_telegram`; assert the specials table lines contain discounted values (name-fallback brands get 9.75%).

### 6.5 `tests/test_lookup.py`

Expected NO changes (no price-string assertions exist — verified). Run and confirm green; only touch if an assertion actually breaks, and record why.

### 6.6 Suite-level gate

```
pytest tests -q  →  0 failed, 0 errors, 0 skipped-beyond-baseline   (baseline skips recorded in Stage 0)
```

---

## 7. Verification matrix (definition of done)

| # | Check | Where | Pass criterion |
|---|---|---|---|
| V1 | Baseline suite recorded | Stage 0 | 137+ pass, 0 fail before edits |
| V2 | New module tests green | Stage 1c | §6.1 all pass |
| V3 | Comparator/specials tests green | Stages 2–3 | §6.2 pass |
| V4 | Sheets-sync tests green | Stage 4 | §6.3 pass |
| V5 | CLI tests green | Stage 5 | §6.4 pass; lookup suite unaffected |
| V6 | py_compile all touched files | Stage 7 | exit 0 |
| V7 | FULL suite green | Stage 7 | 0 failed / 0 errors — **hard gate** |
| V8 | Sheet stays raw | tests | add_product_row/sync/update price cells raw; only Col G `Home` write added |
| V9 | Coles/Aldi untouched | tests + grep | no discount code on coles/aldi paths |
| V10 | Monthly tracker untouched | diff | Section E + usage JSON unchanged |
| V11 | Forbidden files untouched | Stage 8 git status | only §8.1/§8.2 lists modified |
| V12 | Deployed | Stage 8 | scp OK; container Up after restart |
| V13 | Telegram live check | Stage 9.1 | WW price discounted in Claw's reply |
| V14 | Backfill dry-run reviewed then run | Stage 9.2 | dry-run output reviewed by user before live write |
| V15 | No secrets in diffs/output | all | no cookie/key/JSON anywhere |

## 8. Rollback

Any red gate ⇒ stop, fix, re-run. Deployed regression ⇒ re-scp the previous file versions (both git repos have the pre-change commits) and `sudo docker restart openclaw-core`. The sheet needs no rollback — nothing written by this feature ever changes stored prices (only Col G `Home` cells from the explicitly-run backfill, reversible by re-writing the prior brand values from the dry-run table).
