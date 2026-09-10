# Grocery Tracker — Pending Change Requirements

> This file is a **planning doc only**. No code has been changed yet. It captures
> five requested future enhancements to be implemented in a later session:
>
> 1. Populate category/size/brand when adding unmapped items (Q3 gap).
> 2. Remove Aldi completely from every comparison.
> 3. Always apply the Woolworths discount (5% every item + extra 5% home brand).
> 4. New "sheet-analyst" skill: sheet-only analysis with a special trigger
>    keyword (biggest savings, home-brand counts, category breakdown, etc.).
> 5. Carry Woolworths specials/multi-buy pricing into the sheet when syncing
>    the woolworths.docx list (re-use the `Woolworths_Specials.docx` SAVE/FOR
>    parsing logic so Col M reflects real specials instead of being cleared).

All file paths below are relative to the ultimate project root
`grocery-price-tracker/`, unless they live in the parent `AI related/` folder
(marked **PARENT**) — see the README "Code Currently Outside This Folder" section.

---

## 1. Unmapped-add → also populate category / size / brand

### Current behavior (verified)
- **`core/sheets_sync.py :: add_product_row`** *can* write Col B (category),
  Col C (size), Col G (brand), Col I/J/K (store keyword), Col P (alias) — but
  only when the caller passes them.
- **`grocery_price_cli.py :: _add_from_live_search`** (line ~1454) calls
  `add_product_row(generic_name, store, price, brand=best.brand, size=best.size,
  store_keyword=best.raw_name, alias=original_query)` — **`category` is NOT
  passed**, so Col B is left blank on every auto-add.
- **`core/sheets_sync.py :: sync_prices`** (matched-item path) only writes
  price (D/E/F), specials (M/N), rewards (O), timestamp (H). It never touches
  brand/size/category for existing rows.
- **`core/name_matcher.py :: classify_product`** computes a best-effort
  `classification` (brand/size/category/generic_name) and stores it in
  `data/unmapped_queue.json`, but the auto-add path does **not** use it.

### Requirement
When an unmapped item is resolved/added to the sheet, populate **category (Col B),
size (Col C), and brand (Col G)** reliably — not just brand/size.

### Target files / code
- `grocery_price_cli.py :: _add_from_live_search` — pass `category=best.category`
  (and ensure `ProductItem` carries a `category` field sourced from the live
  extractor).
- `extractors/models.py :: ProductItem` — add a `category` attribute if missing;
  populate it from the Woolworths API category breadcrumbs and Coles category
  fields during extraction.
- `extractors/woolworths_extractor.py` — map the Woolworths response category
  (e.g. `Departments`/`aisle`) onto `ProductItem.category`.
- `extractors/coles_extractor.py` — map the Coles `category`/department field
  onto `ProductItem.category`.
- `core/name_matcher.py :: classify_product` — keep as a fallback only (used
  when live data has no category). Optionally feed `classification["category"]`
  into `_add_from_live_search` as the fallback value.
- `core/sheets_sync.py :: add_product_row` — already supports `category`; no
  change needed, just ensure callers pass it.

### Notes / caveats
- Prefer the **live extractor's structured category** over the heuristic
  `classify_product` result (which defaults to "General").
- `sync_prices` should remain untouched for matched items (do not overwrite
  existing brand/size/category during a normal price sync).

---

## 2. Remove Aldi completely from every comparison

### Scope
Remove Aldi from the comparison engine, the sync/match path, the docx parser,
the CLI, and the skill definition. The Google Sheet columns F (Aldi price) and
K (Aldi keyword) can be left in place (harmless) — code simply stops reading/
writing them. `Aldi.docx` can be deleted or left unparsed.

### Target files + specific symbols

| File | Hits | What to change |
|------|------|----------------|
| `core/price_comparator.py` | 12 | `STORES = ("woolworths","coles","aldi")` (L16) → drop `"aldi"`; drop the `LIVE_STORES` aldi comment (L17); remove the Aldi warning block (L261-265); remove the Aldi column from `format_report` table header/rows (L487-504) and totals loop (L520-532); update docstrings. |
| `core/sheets_sync.py` | 9 | `PRICE_COL = {"woolworths":3,"coles":4,"aldi":5}` (L36) → drop `"aldi"`; `STORE_KEYWORD_COL = {...,"aldi":10}` (L654) → drop `"aldi"`; update `update_single_price` / `mark_not_available` / `set_store_keyword` / `add_product_row` docstrings that list aldi. |
| `core/name_matcher.py` | 7 | `_COL_KW_ALDI = 10` (L64) → remove; `_STORE_COL_MAP` (L66-70) → drop aldi entry; remove the `_aldi` dict (L83) and its use in `_index_store_keywords` (L93-97) and `__len__` (L134). |
| `core/lookup.py` | 2 | `COL_KW_ALDI = 10` (L47) → remove; drop `COL_KW_ALDI` from the keyword-index loop (L239-243). |
| `extractors/doc_parser.py` | 5 | Remove `Aldi.docx` parsing branch (the `parse_docx` / `parse_docx_cache` aldi path). |
| `extractors/hub.py` | 6 | Remove the Aldi routing branch. |
| `extractors/models.py` | 7 | Remove Aldi from the `store` allowed-values/comments on `ProductItem`. |
| `core/specials_reporter.py` | 3 | Remove Aldi specials references. |
| `core/schema_upgrade.py` | 2 | Remove Aldi from the column audit (Col F/K). |
| `core/recipe_resolver.py` | 1 | Remove the Aldi reference. |
| `grocery_price_cli.py` (PARENT) | 4 | Remove Aldi from the compare/recipe/specials/unmapped flows and help text. |
| `claw-skills/grocery-price/SKILL.md` (PARENT) | 5 | Remove Aldi from store list, NL routing table, compare output description, and help text. |
| `app.py`, `local_sync.py`, `name_importer.py` | — | Legacy modules; optional cleanup (they are superseded per `LEGACY_AUDIT.md`). |
| `Aldi.docx` | — | Delete or leave unparsed (parser change above makes it inert). |
| Google Sheet | — | Col F (Aldi price) + Col K (Aldi keyword): no code action required; optionally clear later. |

### Verification after the change
- Run the test suite: `& "$env:USERPROFILE\anaconda3\python.exe" -m pytest tests/`
  (expect to update Aldi-specific assertions in `test_comparator.py`,
  `test_name_matcher.py`, `test_sheets_sync.py`, `test_lookup.py`).
- Smoke test: `grocery_price_cli.py compare --items "milk, bread"` — output
  table must show only Woolworths + Coles columns.

### What to commit to git
Commit on the `main` branch (local dev HEAD) — do **not** commit secrets:
- Modified: `core/price_comparator.py`, `core/sheets_sync.py`,
  `core/name_matcher.py`, `core/lookup.py`, `core/specials_reporter.py`,
  `core/schema_upgrade.py`, `core/recipe_resolver.py`,
  `extractors/doc_parser.py`, `extractors/hub.py`, `extractors/models.py`.
- Modified (PARENT, tracked in the same repo): `grocery_price_cli.py`,
  `claw-skills/grocery-price/SKILL.md`.
- Optional: deletion of `Aldi.docx` (or add to `.gitignore`).
- Updated tests under `grocery-price-tracker/tests/`.
- **Never** commit: `.env`, `credentials.json`, `data/`, `__pycache__/`.
- Suggested commit message:
  `refactor(tracker): remove Aldi from comparison, sync, parser, and skill`.

### What to copy to the VPS
Sync via `scp`/tar (branches diverged — do **not** `git pull` on the VPS).
Target host: `myvps` = `ubuntu@169.58.107.0`.
- Core + extractors →
  `/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/core/` and
  `.../extractors/`:
  ```powershell
  scp core\price_comparator.py core\sheets_sync.py core\name_matcher.py `
      core\lookup.py core\specials_reporter.py core\schema_upgrade.py `
      core\recipe_resolver.py `
      myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/core/
  scp extractors\doc_parser.py extractors\hub.py extractors\models.py `
      myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/extractors/
  ```
- CLI (PARENT) →
  `/home/ubuntu/openclaw/tasks/ai-tools/grocery_price_cli.py`:
  ```powershell
  scp ..\grocery_price_cli.py myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery_price_cli.py
  ```
- Skill (PARENT) →
  `/home/ubuntu/openclaw/tasks/ai-tools/claw-skills/grocery-price/SKILL.md`:
  ```powershell
  scp ..\claw-skills\grocery-price\SKILL.md `
      myvps:/home/ubuntu/openclaw/tasks/ai-tools/claw-skills/grocery-price/SKILL.md
  ```
- Verify md5 matches on both sides (`Get-FileHash` local vs `md5sum` on VPS).
- Reload skills/config: `ssh myvps 'docker restart openclaw-core; sleep 30; docker ps --format "{{.Names}} {{.Status}}"'`.

### Skills updates
- Edit `claw-skills/grocery-price/SKILL.md`: drop Aldi from the store list,
  the NL routing table, the compare output description, and any examples/help
  text. Re-run the Telegram end-to-end test:
  ```bash
  ssh myvps 'docker exec openclaw-core node /app/openclaw.mjs agent --channel telegram --to 1594431983 --message "compare milk in woolworths and coles" --deliver'
  ```

---

## 3. Always apply Woolworths discount (5% every item + extra 5% home brand)

### Requirement
**Every** Woolworths comparison — whether sourced from the sheet **or** live —
must apply, with no flag and no monthly gate:
1. **5% off every Woolworths item** (price × 0.95), and
2. an **additional 5% off home-brand** Woolworths items (the already-discounted
   home-brand price × 0.95 again → effective ×0.9025, i.e. 5% + 5% stacked).

This must be the default for `compare`, `recipe`, and any Coles-vs-Woolworths
comparison the agent sends.

### Current behavior (verified) — what changes
- `core/woolworths_discounts.py`:
  - `TEAM_DISCOUNT_RATE = 0.05` is applied **only to home-brand items**
    (`apply_team_discount` checks `is_woolworths_home_brand`).
  - `apply_extra_discount` applies X% to the whole basket but is gated by the
    monthly usage tracker (`can_use_monthly_discount`, one use/month).
- `core/price_comparator.py :: compare_basket`:
  - `team_discount=True` by default, `extra_discount_pct=0.0` by default.
  - Discounts only affect the Woolworths basket total line; per-item displayed
    prices in `format_report` are **not** discounted in the item rows.

### Required changes (later session — do NOT change now)
- `core/woolworths_discounts.py`:
  - Introduce `BASE_WOOL_DISCOUNT_RATE = 0.05` applied to **all** Woolworths items.
  - Introduce `HOME_BRAND_EXTRA_RATE = 0.05` applied **in addition** to
    home-brand items (stacked on top of the base 5%).
  - Replace/augment `apply_team_discount` with a function that returns
    per-item `original_price`, `discounted_price`, `applied` for ALL items
    (base discount always applied; extra home-brand discount where detected).
  - The monthly gate (`can_use_monthly_discount`) must NOT block this — this
    discount is always-on, independent of the monthly extra-discount tracker.
- `core/price_comparator.py`:
  - `compare_basket`: always call the new discount function for the Woolworths
    basket; remove the need for `team_discount`/`extra_discount_pct` flags to
    enable it (flags can stay for the *additional* monthly extra discount only).
  - `format_report`: show the **discounted** Woolworths price in the item rows
    (and keep a note/discount block showing original → discounted + savings).
- `grocery_price_cli.py` (PARENT):
  - `compare` / `recipe` commands: pass the always-on discount through; ensure
    `--mode sheet` and `--mode live` and `--mode auto` all apply it.
- `claw-skills/grocery-price/SKILL.md` (PARENT):
  - Document that every Woolworths price shown is post-discount (5% all items,
    +5% home brand), so the agent's replies reflect it.

### Notes / caveats
- Home-brand detection already exists via `is_woolworths_home_brand`
  (`HOME_BRAND_LABELS = "woolworths","macro","the odd bunch","gold","free from"`)
  — reuse it for the additional 5%.
- The Coles side is unaffected (no Coles discount).
- Update tests in `tests/test_comparator.py` to assert the new default
  (5% all items, +5% home brand) for Woolworths totals and item prices.

---

## 4. New skill: "sheet-analyst" (sheet-only Claw analyst)

### Goal / scope
Add a **new OpenClaw skill** that turns Claw into a **read-only analyst over the
`Products_Master` Google Sheet** — no live search, no sync, no write ops, no
extra detail. It answers aggregate/comparison questions purely from stored
prices (Col D = Woolworths, Col E = Coles), brand (Col G), size (Col C),
category (Col B), specials (Col M/N), rewards (Col O), and keywords (Col P).

A **special trigger keyword** routes the user's natural-language query to this
skill and guarantees a sheet-only answer (never live fallback, never the
`grocery-price` compare/search path).

### The trigger keyword (routing rule)
The user prefixes or phrases the question with one of these keywords so Claw
selects this skill:

- **`analyze sheet`** / **`sheet analysis`** / **`from the sheet`** — primary triggers.
- Shorthand: prefix the query with **`sheet:`** (e.g. `sheet: biggest woolworths savings top 5`).

If the phrase contains "analyze the sheet", "sheet analysis", "from the sheet",
or starts with "sheet:", the agent MUST route to `sheet-analyst` and MUST NOT
invoke `grocery-price` `compare`/`search`/`recipe`. This is a hard rule mirroring
the existing `compare` vs `search` routing rule in `grocery-price/SKILL.md`.

### Example questions this skill must answer (all sheet-only)
- "which item has the biggest $ saving in woolworths over coles, give me top 5"
  → top-N items where Woolworths price < Coles price, sorted by absolute $ saved.
- "how many home brand items are there" → count of rows where
  `is_woolworths_home_brand(name, brand)` is True.
- "how many home brand items are in dairy" → same, filtered by Col B category.
- "biggest coles savings over woolworths top 10" → top-N where Coles cheaper.
- "which items are only available at woolworths" → items with a Woolworths
  price but no Coles price.
- "total basket savings shopping at woolworths vs coles" → sum of per-item
  differences for items priced at both stores.
- "category breakdown of the sheet" → item count per Col B category.
- "how many items on special at coles" → count of non-empty Col N cells.
- "items with bonus rewards" → non-empty Col O.

### Architecture (reuse existing patterns)
Model on `core/specials_reporter.py` — a single `get_all_values()` read,
read-only, returns `list[dict]`, Markdown table formatter. No live extractor,
no writes.

### Target files / code to create

| File (new) | Purpose |
|------------|---------|
| `core/sheet_analyst.py` | Read-only analytics engine. Functions: `top_savings(cheaper_store, pricier_store, limit=5)`, `count_home_brands(category=None)`, `store_only_availability(store)`, `total_basket_savings(store_a, store_b)`, `category_breakdown()`, `count_specials(store)`, `count_rewards()`. Reuse `PRICE_COL`, `_find_col`, `_price_re` parsing from `sheets_sync.py`; reuse `is_woolworths_home_brand` from `woolworths_discounts.py`. ONE `get_all_values()` per call. |
| `claw-skills/sheet-analyst/SKILL.md` (PARENT) | New skill definition with front matter (`name: sheet-analyst`), the trigger-keyword routing rule, the subcommand table, NL mappings, and hard rules (sheet-only, never live, never mutate). |

### Target files / code to modify

| File (existing) | Change |
|------------------|--------|
| `grocery_price_cli.py` (PARENT) | Add a new `analyze` subcommand that dispatches to `core/sheet_analyst.py` functions. Args: `--query TYPE` (one of `savings`, `home-brands`, `only-at`, `basket-savings`, `categories`, `specials`, `rewards`) `[--store woolworths\|coles]` `[--limit N]` `[--category STR]`. Add it to the argparse subparsers and the `--help`. |
| `claw-skills/grocery-price/SKILL.md` (PARENT) | Add a disambiguation rule: queries containing the trigger keyword (`analyze sheet`, `sheet analysis`, `from the sheet`, or `sheet:` prefix) route to the `sheet-analyst` skill, NOT `grocery-price`. |
| `openclaw.json` (VPS) | No change needed — `skills.load.extraDirs` already loads `/app/tasks/ai-tools/claw-skills`, so the new `sheet-analyst/` folder is picked up automatically after container restart. |

### `sheet-analyst/SKILL.md` — outline
- Front matter: `name: sheet-analyst`, description listing the example
  questions and the trigger keyword.
- Run command:
  `docker exec openclaw-core python3 /app/tasks/ai-tools/grocery_price_cli.py analyze ...`
- Subcommand table mapping each `--query TYPE` to its NL phrase.
- NL → subcommand mappings (the example questions above).
- Hard rules:
  - Sheet-only. NEVER call `compare`/`search`/`recipe`/`sync`/`update`.
  - NEVER trigger live extractor calls.
  - Read-only — never writes to the sheet.
  - Apply the Section-3 Woolworths discount (5% all items + extra 5% home
    brand) to Woolworths prices in savings calculations once Section 3 is
    implemented (so savings reflect the discounted Woolworths price). Until
    then, use raw Col D prices and note "pre-discount".
  - Never dump raw JSON; return a Markdown summary table + count.

### `core/sheet_analyst.py` — function contracts (planning)
- `top_savings(cheaper_store, pricier_store, limit=5) -> list[dict]`:
  rows priced at BOTH stores where `prices[cheaper] < prices[pricier]`,
  sorted by `prices[pricier] - prices[cheaper]` desc, top `limit`.
  Each dict: `{name, brand, category, cheaper_price, pricier_price, saving}`.
- `count_home_brands(category=None) -> dict`:
  `{total, by_category: {...}}` using `is_woolworths_home_brand(name, brand)`.
  Optional Col B filter.
- `store_only_availability(store) -> list[dict]`:
  rows with a price at `store` but not at the other store.
- `total_basket_savings(store_a, store_b) -> dict`:
  `{items_compared, total_at_a, total_at_b, saving}` for items priced at both.
- `category_breakdown() -> list[dict]`: `{category, count}` sorted desc.
- `count_specials(store=None) -> int`, `count_rewards() -> int`.

### What to commit to git
Commit on `main` (local dev HEAD) — do **not** commit secrets:
- New: `core/sheet_analyst.py`, `claw-skills/sheet-analyst/SKILL.md`.
- Modified (PARENT): `grocery_price_cli.py` (new `analyze` subcommand),
  `claw-skills/grocery-price/SKILL.md` (routing disambiguation).
- New tests: `tests/test_sheet_analyst.py` (top_savings, home-brand count,
  only-at, basket savings, category breakdown, specials/rewards counts).
- **Never** commit: `.env`, `credentials.json`, `data/`, `__pycache__/`.
- Suggested commit message:
  `feat(tracker): add sheet-analyst skill (sheet-only analysis, trigger keyword)`.

### What to copy to the VPS
Sync via `scp` (branches diverged — do **not** `git pull`). Host: `myvps`.
- New core module →
  `/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/core/sheet_analyst.py`:
  ```powershell
  scp core\sheet_analyst.py `
      myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/core/sheet_analyst.py
  ```
- CLI (PARENT) →
  `/home/ubuntu/openclaw/tasks/ai-tools/grocery_price_cli.py`:
  ```powershell
  scp ..\grocery_price_cli.py myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery_price_cli.py
  ```
- New skill (PARENT) →
  `/home/ubuntu/openclaw/tasks/ai-tools/claw-skills/sheet-analyst/SKILL.md`
  (create the `sheet-analyst/` folder on the VPS first):
  ```powershell
  ssh myvps 'mkdir -p /home/ubuntu/openclaw/tasks/ai-tools/claw-skills/sheet-analyst'
  scp ..\claw-skills\sheet-analyst\SKILL.md `
      myvps:/home/ubuntu/openclaw/tasks/ai-tools/claw-skills/sheet-analyst/SKILL.md
  ```
- Modified grocery-price skill (PARENT):
  ```powershell
  scp ..\claw-skills\grocery-price\SKILL.md `
      myvps:/home/ubuntu/openclaw/tasks/ai-tools/claw-skills/grocery-price/SKILL.md
  ```
- Verify md5 matches (`Get-FileHash` vs `md5sum`).
- Reload skills (new `sheet-analyst/` folder is auto-discovered via
  `skills.load.extraDirs`):
  `ssh myvps 'docker restart openclaw-core; sleep 30; docker exec openclaw-core node /app/openclaw.mjs skills list'`.
  Confirm `sheet-analyst` appears in the loaded-skills list.

### Skills updates
- End-to-end test via the Telegram path:
  ```bash
  ssh myvps 'docker exec openclaw-core node /app/openclaw.mjs agent --channel telegram --to 1594431983 --message "analyze sheet: biggest woolworths savings over coles top 5" --deliver'
  ```
  The reply must be a sheet-only Markdown table (top 5 items by $ saved),
  with NO live-search fallback and NO `compare` table.

### Notes / caveats
- Read-only: this skill must never call `sync_prices`, `update_single_price`,
  `add_product_row`, or any extractor.
- The trigger keyword is the only routing signal — without it, "biggest
  savings" type phrasing could be misrouted to `grocery-price` `compare`. The
  disambiguation rule in `grocery-price/SKILL.md` prevents that.
- Once Section 3 (always-on Woolworths discount) is implemented, the
  `top_savings` and `total_basket_savings` functions should use the
  discounted Woolworths price so "savings" reflect what you'd actually pay.
  Until then, return raw prices and label the output "pre-discount".

---

## 5. Carry Woolworths specials / multi-buy pricing into the sheet on sync

### Requirement
When the regular **`Woolworths.docx`** list is parsed and synced to the sheet
(the `wednesday` command Step 1 → Step 3 path), the **specials pricing** —
including dollar-off **`SAVE $X.XX`** specials and **multi-buy** `N FOR $XXX`
bundle specials — must be detected and written to the Woolworths specials
column **(Col M)** so the sheet reflects real special pricing instead of being
blanked.

The detection must re-use the **same dual-logic** that already lives in
`grocery_price_cli.py :: _extract_woolworths_specials` (the function that parses
`Woolworths_Specials.docx`):
- **SAVE marker** appears *before* the product name+price → look forward
  (`_find_name_price_after`) and compute `discount_pct = save / (price + save)`.
- **`N FOR $XXX` multi-buy marker** appears *after* the product name+price →
  look backward (`_find_name_price_before`); `discount_pct` is `None` for bundles.

### Current behavior (verified — the gap)
The two Woolworths paths are completely disconnected today:

1. **Regular list → sheet** (`wednesday` Step 1 + Step 3):
   - `extractors/doc_parser.py :: parse_docx` (lines 208-275) builds a
     `ProductItem` with only `store, raw_name, price, category, size, brand`.
     It **never** inspects the line *below* a price for a `SAVE`/`FOR` marker,
     so `is_special` stays at its default `False` and `special_desc` stays `""`
     (`extractors/models.py` lines 42-43).
   - `core/sheets_sync.py :: sync_prices` (lines 233-236) writes
     `item.special_desc if item.is_special else ""` to Col M. Because
     `is_special` is always `False` here, **Col M is written as `""` for every
     matched Woolworths row** — the sync actively *clears* any specials text
     that was there before, rather than updating it.

2. **Specials doc → Telegram only** (`wednesday` Step 8):
   - `grocery_price_cli.py :: _extract_woolworths_specials` (lines 633-759) parses
     `Woolworths_Specials.docx` with the dual forward/backward logic above, but
     the resulting `{name, price, detail, discount_pct}` dicts are used **only**
     to build the Telegram specials report (Step 8, lines 1045-1101). They are
     **never** passed to `sync_prices` and **never** written to the sheet.

Net effect: specials pricing discovered in the savings list never reaches the
sheet, and the regular sync wipes Col M for matched items.

### Target files / code

| File | What to change |
|------|----------------|
| `extractors/doc_parser.py` | Extend `parse_docx` so the two-line (or three-line) layout is scanned for `SAVE $X.XX` / `N FOR $XXX` markers *adjacent* to each name+price pair. When a marker is found, set `ProductItem.is_special = True` and populate `special_desc` (e.g. `"save $1.53 (35% off)"` / `"2 for $4.50"`). Re-use the regexes + `_find_name_price_after` / `_find_name_price_before` helpers currently inlined in `_extract_woolworths_specials` — extract them into a shared helper module (see below) so both call sites use one implementation. |
| `grocery_price_cli.py` (PARENT) | Extract the `save_re` / `for_re` / `clean_price_re` patterns and the `_find_name_price_after` / `_find_name_price_before` helpers out of `_extract_woolworths_specials` into a shared module (e.g. `extractors/specials_parser.py`) and import them in *both* `parse_docx` and `_extract_woolworths_specials`. This removes the duplicated parsing logic and guarantees the sheet-sync path and the Telegram-report path stay in lockstep. |
| `core/sheets_sync.py` | No change required — `sync_prices` already writes `item.special_desc` to Col M when `item.is_special` is True (lines 233-236). Once `parse_docx` populates the fields, specials will flow through automatically. Confirm `SPECIALS_HEADER_BY_STORE["woolworths"]` ("Woolworths_Specials" → Col M) resolves (already verified to exist). |
| `extractors/models.py` | No change — `ProductItem.is_special` / `special_desc` already exist with correct defaults; they simply start being populated by `parse_docx`. |

### Suggested approach (minimal, surgical)
1. Create `extractors/specials_parser.py` containing: `SAVE_RE`, `FOR_RE`,
   `CLEAN_PRICE_RE`, `find_name_price_after(lines, start, end)`, and
   `find_name_price_before(lines, start, end)` (moved verbatim from
   `_extract_woolworths_specials`), plus a single
   `detect_special(lines, idx) -> tuple[str|None, float|None, str|None, float|None]`
   helper returning `(name, price, detail, discount_pct)` for a given line.
2. In `parse_docx`, after matching a name+price pair, call `detect_special`
   against the surrounding lines; if it returns a marker, set the
   `ProductItem.is_special` / `special_desc` fields before appending.
3. Refactor `_extract_woolworths_specials` to call the same shared helpers
   (behaviour-preserving — its Telegram output must stay identical).

### Notes / caveats
- **Do not** route `Woolworths_Specials.docx` through the sheet-sync path: that
  doc is special-only and its items are not part of the regular basket. The goal
  here is to detect specials that already appear *inside* `Woolworths.docx`
  (the saved shopping list), using the same marker logic the specials doc uses.
- The multi-buy `N FOR $XXX` detail has `discount_pct = None` (bundle, not a
  %-off). `sync_prices` only writes `special_desc` text to Col M, so the column
  will read e.g. `"2 for $4.50"` — acceptable for now. If a numeric discount %
  is later needed in the sheet, extend the column schema separately.
- Preserve the existing `IGNORE_TERMS` filtering in `parse_docx` so lines like
  `"you'll save up to"` / `"you save"` UI noise are not false-matched as SAVE
  specials (note: `"save "` is already in `IGNORE_TERMS`, so the marker scan
  must run on the *detail line directly below the price*, not on the product
  name line itself).
- `sync_prices` writes the whole sheet range in one batch, so populating Col M
  via the item fields adds no extra API calls.

### Verification after the change
- Add a fixture `Woolworths.docx` (or unit-test lines) containing one `SAVE`
  marker and one `N FOR $XXX` marker in the saved-list three-line layout, then
  assert `parse_docx` returns `ProductItem`s with `is_special=True` and the
  expected `special_desc`.
- Run `wednesday --dry-run` and confirm the planned Col M writes show the
  specials text (not `""`) for the two fixture rows.
- Regression: run `_extract_woolworths_specials` against the real
  `Woolworths_Specials.docx` and confirm the Telegram report is byte-identical
  to before the refactor.
- Test suite:
  `& "$env:USERPROFILE\anaconda3\python.exe" -m pytest tests/ -k "doc_parser or specials or sync"`.

### What to commit to git
Commit on `main` (local dev HEAD) — do **not** commit secrets:
- New: `extractors/specials_parser.py` (shared marker helpers).
- Modified: `extractors/doc_parser.py` (populate `is_special`/`special_desc`).
- Modified (PARENT): `grocery_price_cli.py` (refactor `_extract_woolworths_specials`
  to use the shared helpers — behaviour-preserving).
- New tests under `grocery-price-tracker/tests/` (specials detection in
  `parse_docx`, regression on `_extract_woolworths_specials`).
- **Never** commit: `.env`, `credentials.json`, `data/`, `__pycache__/`.
- Suggested commit message:
  `feat(tracker): carry woolworths SAVE/multi-buy specials into sheet sync (Col M)`.

### What to copy to the VPS
Sync via `scp` (branches diverged — do **not** `git pull`). Host: `myvps`.
- Extractors →
  `/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/extractors/`:
  ```powershell
  scp extractors\specials_parser.py extractors\doc_parser.py `
      myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/extractors/
  ```
- CLI (PARENT) →
  `/home/ubuntu/openclaw/tasks/ai-tools/grocery_price_cli.py`:
  ```powershell
  scp ..\grocery_price_cli.py myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery_price_cli.py
  ```
- Verify md5 matches (`Get-FileHash` vs `md5sum`).
- Reload: `ssh myvps 'docker restart openclaw-core; sleep 30; docker ps --format "{{.Names}} {{.Status}}"'`.
