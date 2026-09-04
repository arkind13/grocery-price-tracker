# Architecture Spec — Sub-Categories (Q), Item-Codes (R), Preferred (S), Multi-Buy Pricing & Full-Name Display

- **Date:** 2026-09-04
- **Stage:** 01 Architect (this doc) → 02 Plan → 03 Code → 04 Architect Checker
- **Status:** DRAFT for user confirmation. Decisions & Trade-offs in §11
  require sign-off before 02 Plan.
- **Inputs:** user brief 2026-09-04 (columns Q/R/S, ingestion pipeline,
  preference state machine, multi-buy logic, name-truncation fix) + full
  workspace inspection 2026-09-04: `README.md`, `PROJECT-MAP.md`, prior
  `architecture-spec.md` (Col C cycle), `core/sheets_sync.py`,
  `core/sheets_client.py`, `core/schema_upgrade.py`, `core/searched_items.py`,
  `core/telegram_format.py`, `core/price_comparator.py`, `core/uom.py`,
  `core/lookup.py` (structure), `extractors/models.py`,
  `extractors/specials_parser.py`, `extractors/woolworths_extractor.py`,
  `grocery_price_cli.py` (search/map/lists surfaces),
  `claw-skills/grocery-price/SKILL.md`, `woolworths_master_comparison.csv`,
  and a **read-only live header read of Products_Master** (16 cols A–P,
  104 data rows — verified 2026-09-04).
- **Not read (per role rules):** `pre-arch.md` (no tester involvement
  stated), `lostbattle.md` (not prompted).
- **Replaces:** the previous spec at this path (Units Always Visible /
  Col C cycle, 2026-09-01 — implemented and verified per `test.md`;
  its history stays in git).

---

## 1. Goal (plain language)

Today, when you say "compare eggs", the system hunts for a product whose
*name* looks like "eggs" — it cannot tell that you mean the *category* of
all egg products, and it has no memory of which egg product you actually
buy. Multi-buy deals ("2 for $6.00") are detected and filed, but they
never change comparison math. And long product names get chopped to
24 characters in search replies ("AJI CRISPY FRY BREADING…").

This spec adds four things:

1. **Three new sheet columns** — Sub-Category (Q), Item-Code (R),
   Preferred (S) — so every row knows its granular cluster, carries a
   short unique ID you can type in chat, and can be marked as your
   default pick for that cluster.
2. **Ingestion wiring** — every path that creates a row (search add,
   map add, optimize +add, Wednesday auto-link) fills Q/R/S at creation.
3. **A shopping-list flow** — "eggs, apples, bread" resolves each item
   to its sub-category, auto-picks your preferred product, asks you
   ONE question when no preferred exists, and warns you when you
   deliberately ask for a non-preferred variant.
4. **Multi-buy pricing** — "2 for $6.00" is parsed, its per-unit rate
   ($3.00) is stored, used in comparisons, and always flagged with a
   "must buy 2+" note. Plus: search results stop cutting names off.

---

## 2. Verified current state (facts the design rests on)

| Fact | Evidence |
|---|---|
| Sheet `Products_Master` has exactly 16 columns, A–P; Q/R/S are free | live read 2026-09-04: header = Product_Name, Category, Size, Woolworths_Price, Coles_Price, Aldi_Price, Brand_Type, Last_Updated, Search_Keyword_Woolworths, Search_Keyword_Coles, Search_Keyword_Aldi, Aldi Refresh, Woolworths_Specials, Coles_Specials, Rewards_Points, Keywords |
| 104 data rows; Col B "Category" filled on 77 (coarse: Drinks, Dairy, Vegetables…); Col P aliases filled on all 104 | live read |
| Existing 3-letter code system (queues only): alphabet A–Z **minus I/O**, no repeated letter, 7-day tombstones | `core/searched_items.py:52-55` |
| Multi-buy already *detected* (docx path): `2 for $4.50` / `Any 2 \| $9` → M/N cell vocabulary `multi-buy` | `extractors/specials_parser.py` (FOR_RE/ANY_RE, `classify_special`) |
| Multi-buy NOT captured on live paths: WW search maps only IsOnSpecial/IsHalfPrice/WasPrice/SavingsAmount; Coles maps pricing.now/was/onlineSpecial | `extractors/woolworths_extractor.py:240-251` |
| Name truncation in search results: `item_block` truncates to `MAX_NAME_WIDTH = 24` cells | `core/telegram_format.py:47,355`; user example 2026-09-04 |
| Comparator provenance lines already show FULL matched names (no truncation) | `core/price_comparator.py:635-658` |
| All sheet writes are explicit-range `worksheet.update(values, range_name)` — a short range never clobbers columns outside it | `core/sheets_sync.py` (`_update_with_backoff`) |
| Row creation funnels through ONE function: `add_product_row` (dup guard + one-line-rule merge live there) | `core/sheets_sync.py:~1040-1227` |
| The conversational LLM in the loop is the OpenClaw agent (qwen3.7-flash) driven by `claw-skills/grocery-price/SKILL.md`; the CLI itself is deterministic and LLM-free | README §4, SKILL.md |
| UOM gate semantics (families, 20% band, no per-unit price math) are frozen | `core/uom.py` docstring |

---

## 3. Schema — Columns Q, R, S

| Col | Header (exact) | 0-based idx | Content contract |
|---|---|---|---|
| Q | `Sub_Category` | 16 | Granular cluster name, lowercase, spaces allowed: `bread`, `apples`, `shredded cheese`, `cheese slice`, `eggs`. Normalisation for matching: lowercase, trim, collapse whitespace/underscores/hyphens→space. Literal marker `needs review` = classifier could not confidently place the row (surfaced by `lists`, never silently re-guessed). |
| R | `Item_Code` | 17 | Exactly 3 uppercase letters from `ABCDEFGHJKMNPQRSTUVWXYZ` (A–Z minus **I, L, O** — case-insensitive exclusion), **no repeated letter** within a code. Unique across all rows, permanent for the life of the row, never reused after row deletion. |
| S | `Preferred` | 18 | Empty (default) or the literal `P`. **Invariant: at most ONE `P` per distinct non-empty Sub_Category value.** |

Headers are appended by extending `core/schema_upgrade.py`
(`NEW_COLUMNS += ["Sub_Category", "Item_Code", "Preferred"]`); the
command stays idempotent and must be run once at deploy (manual step M1).

**Relationship to Col B:** Col B stays the coarse category (Drinks,
Dairy…). Col Q is the minute cluster *below* B. Nothing reads B for
preference logic; backfill may use B as a weak hint only.

**Namespace separation:** Item-Codes (Col R, permanent row identity) are
a DIFFERENT namespace from the queue codes (`searched_items` /
`add_to_list`, ephemeral, A–Z minus I/O, tombstoned). They may collide
by coincidence; contexts never overlap (`prefer ABC` vs `todo done ABC`).
Accepted risk — see §11 D-IC4.

---

## 4. New core modules

| Module | Responsibility |
|---|---|
| `core/subcategory.py` (NEW) | Canonical taxonomy (ordered regex→label rules), `classify_subcategory(name, category_hint="") -> (label, confidence)`, `normalize_subcategory(s)`, `SUBCATEGORY_HEADER` constant. Specific-before-generic precedence (e.g. `cheese slice` before `cheese`; `breading`/`breadcrumbs` must NOT match `bread`). |
| `core/item_codes.py` (NEW) | `CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ"` (23 letters), `generate_codes(existing: set, n=1, rng=None) -> list[str]`, registry cache `data/item_code_registry.json`, `ensure_codes(worksheet) -> dict` (backfill), reserve-verify loop (§8). |
| `core/preferences.py` (NEW) | Read Q/R/S columns; `get_preferred(subcategory) -> row \| None`; `set_preferred(code) -> dict` (clear-then-set, one range write, §8); `list_subcategory_options(subcategory) -> [(row_index, name, code)]`; renders the disambiguation prompt + warning lines (exact texts §6). |
| `core/multibuy.py` (NEW) | `parse_multibuy(desc) -> (qty, bundle_total) \| None` (reuses FOR_RE/ANY_RE from `extractors/specials_parser.py`), `effective_unit_rate(qty, total) -> float`, `format_multibuy_note(qty, total) -> str`, sheet cell codec `encode_multibuy_cell(qty, total) -> "multi-buy 2/$6.00"` and `decode_multibuy_cell(cell)`. Display+math only — never touches `core/uom.py`. |

`extractors/models.py`: `ProductItem` gains optional
`multi_buy_qty: int = 0`, `multi_buy_total: float = 0.0` (0 = none).
Backwards-compatible for every existing caller and JSON snapshot.

---

## 5. Ingestion & pre-processing pipeline (Requirement B)

Every row-creation path funnels through `add_product_row` — the hook is
there (single choke point, verified):

```
add_product_row(...)                        # core/sheets_sync.py
  ├─ existing validation (store, name, price, size)      — unchanged
  ├─ NEW: subcategory = classify_subcategory(generic_name, category_hint)
  │        · confidence ≥ threshold → label
  │        · below threshold      → literal "needs review"
  │        · caller may pass --subcategory to override (CLI flags below)
  ├─ NEW: code = item_codes.reserve_code(worksheet)      # §8 algorithm
  ├─ row build: new_row[16]=subcategory  new_row[17]=code  new_row[18]="" (P empty)
  │        target_width now also ≥ 19 when the header has Q/R/S
  └─ single range write A{row}:S{row} (one API call, atomic row)
```

Paths that must pass through this hook (all verified to call
`add_product_row` today): `search --add-item N`, `map unmatched --add`,
`map wool/coles --add`, `optimize --confirm <code>+add`, Wednesday
Step 1c auto-link row creation. The one-line-rule MERGE path
(`update_single_price` on an existing row) assigns NOTHING — the row
already owns its code/sub-category; only the price updates.

New CLI flags: `search --add-item N [--subcategory TEXT]`,
`map … --add [--subcategory TEXT]` — the agent (LLM) may pass its
classification when it is confident; otherwise the deterministic
classifier decides. `--subcategory` normalises through
`normalize_subcategory`.

**Legacy rows (104):** two one-time commands (mirror `backfill-sizes`):
- `backfill-subcategories [--dry-run]` — fills Col Q only where the
  classifier is confident; others get `needs review`; NEVER overwrites
  a non-empty Q; prints filled/review/failed counts.
- `backfill-codes [--dry-run]` — reads Col R once, generates the full
  unique set in memory, ONE batched column write R2:R{last}; prints the
  count; idempotent (rows that already have a code keep it).

---

## 6. Shopping-list intake, disambiguation & preference machine (Requirement C)

### 6.1 Where the LLM stage lives

The LLM extraction stage is the **OpenClaw agent**, not the CLI. The CLI
stays deterministic. Contract (encoded in SKILL.md, §C7):

1. User sends a shopping list ("eggs, apples, bread, milk, cheese slice").
2. Agent normalises each item to either a **sub-category name** (from the
   taxonomy printed by `subcategories`) or a **specific product request**
   (when the wording names a variant: "free range eggs").
3. Agent calls `shop --items "<i1>, <i2>, …"` passing its normalised
   text verbatim.
4. CLI independently re-classifies each item deterministically
   (exact sub-category name → category mode; else product mode via the
   existing lookup chain). Agreement needs no chat; disagreement is
   impossible to detect from the CLI side (it only sees its own reading)
   — the agent's normalisation simply produces cleaner inputs.

`compare` and `optimize` keep their current contracts; the new `shop`
subcommand wraps `compare_basket` with the preference state machine.

### 6.2 Data flow & sequence diagram

```
 USER (Telegram)          Claw agent (LLM)              VPS CLI (deterministic)                Google Sheet
 ─────┬────────────────────────┬──────────────────────────────┬──────────────────────────────┬──────────
      │ "eggs, apples,         │                              │                              │
      │  free range eggs"      │                              │                              │
      ├───────────────────────>│ 1. normalise items           │                              │
      │                       │  (taxonomy ref: `subcategories`)                             │
      │                       ├── shop --items "eggs, apples, free range eggs" ───────────────>│
      │                       │                              │ 2. read Q/R/S + prices        │
      │                       │                              │    (one get_all_values)       │
      │                       │                              │ 3. per item:                  │
      │                       │                              │    a. sub-cat match? ──yes──> mode=category
      │                       │                              │    b. else lookup chain ────> mode=product
      │                       │                              │ 4. mode=category:             │
      │                       │                              │    P flagged? ──yes──> [S4] use that row
      │                       │                              │    no P, rows>0 ─────> [S1] HALT + prompt
      │                       │                              │    no rows at all ────> [S0] live-search offer
      │                       │                              │ 5. mode=product:              │
      │                       │                              │    resolved row's sub-cat has │
      │                       │                              │    different P? ──────> [S5] compare + WARN
      │                       │                              │ 6. compare selected rows      │
      │<────── table, or prompt, or warning ────────────────┤                               │
      │ "ABC" (reply)         │                              │                               │
      ├───────────────────────>│ prefer --code ABC ──────────>│ 7. clear sibling P, set P     │
      │                       │                              │    (ONE range write S-range) ─>│
      │                       │                              │ 8. resume: complete the       │
      │                       │                              │    halted comparison          │
      │<────── final table ───┤                              │                               │
```

Wednesday ingestion runs the same Q/R/S assignment inline (§5) — no
preference logic there (Wednesday never writes P).

### 6.3 State machine & branching logic matrix

| State | Name | Entry condition | Trigger → Action → Next |
|---|---|---|---|
| S0 | COLD_NO_ROWS | requested sub-category has zero sheet rows | live keyword offered → user gives keyword → `search` flow (`--add-item` → row created with Q/R/S via §5) → back to S1 on next `shop` run. • user cancels → item dropped from run. |
| S1 | NO_P (halt) | ≥1 row in sub-category, none flagged P | print disambiguation prompt (§6.4) → AWAIT (S2). |
| S2 | AWAIT_USER | prompt printed; pending state saved to `data/shop_pending.json` | user replies code/number → `prefer --code X` or `prefer --pick N` → SET_P (S3). • user replies keyword → S0 live-search path. • user cancels → item dropped, rest of list continues. |
| S3 | SET_P | selection received | clear sibling `P` in same sub-category + set `P` on chosen row (§8 write) → resume comparison with chosen row → P_SET (S4). |
| S4 | P_SET | sub-category has a `P` row | auto-select that row for the comparison table. If the preferred row lacks a price at one store → existing behaviour (single-store answer + ⚠️ line / found-block); NEVER silently substitutes a non-preferred row. |
| S5 | OVERRIDE_SPECIFIC | mode=product; resolved row's sub-category has a different (or no) `P` | compare the REQUESTED row + print warning (§6.5) → user replies "switch" → SET_P (S3) on the requested row. • user replies "keep"/silence → comparison already delivered; sheet untouched. |
| S6 | LIVE_SEARCH_ADD | new product added via S0 | row created with S empty → next `shop` hits S1 → one question sets P. (Deliberate: ingestion NEVER auto-sets P.) |

Pending-run persistence: `data/shop_pending.json`
`{started_at, items: [...], halted: [{item, subcategory, options: [{row, name, code}]}]}`
— same atomic-JSON pattern as the queues. `prefer` consumes it, then
finishes the run (prints the completed table). Stale pending runs (>24h)
are reported and discarded with a pointer to re-run `shop`.

### 6.4 Disambiguation prompt (Scenario 2 — exact format)

```text
Sub-Category: eggs - Which one would you like to make your preferred item?
1 - Woolworths 12 Extra Large Free Range Eggs 700g - ABC
2 - Coles 700g Free Range Eggs XL - DEF
Or: Not in list? Provide another keyword for live search.
```

Full product titles (Col A, never truncated — §10), then the row code.
Selection accepts the code (`ABC`) or the number (`2`).

### 6.5 Override warning (Scenario 3 — exact format)

```text
⚠️ Warning: [Product Name] is not your preferred item for sub-category [Sub-Category].
Would you like to switch your preferred item in the sheet?
Reply 'switch' to make it preferred, or 'keep' to continue without switching.
```

`keep` is write-free; `switch` routes to SET_P (S3).

### 6.6 New CLI surface

| Command | Behaviour |
|---|---|
| `shop --items "…"` | §6.2 flow; wraps `compare_basket`; halted items render the §6.4 prompt instead of a table row; completed items render normally. |
| `prefer --code ABC` / `prefer --pick N` (with a pending run) | S3 write + resume; without a pending run, still writes P and confirms (standalone use). |
| `subcategories` | prints taxonomy labels + live per-label row counts (agent reference for normalisation; also user-browsable). |
| `backfill-subcategories` / `backfill-codes` | §5 one-time commands. |

---

## 7. Multi-buy promotion & pricing logic (Requirement D)

### 7.1 Detection & parsing

- Source strings: docx specials lines (`2 for $4.50`, `Any 2 | $9`),
  live `special_desc` when extractors manage to capture one, and the
  M/N sheet cell. Parser: `core/multibuy.parse_multibuy` built on the
  EXISTING regexes (`FOR_RE`, `ANY_RE` — no duplicate patterns).
- Live capture: WW/Coles search extractors gain best-effort fields
  (`multi_buy_qty`, `multi_buy_total` on `ProductItem`). **The live APIs'
  multi-buy payload shape is NOT verified** — implementation starts with
  a read-only probe of real search responses; if the payload carries no
  multi-buy data, live paths degrade to normal pricing (never invented)
  and only the docx/sheet paths carry multi-buy. See §11 D-MB2.

### 7.2 Storage

- M/N cells keep the D25 vocabulary as a PREFIX and gain structured
  terms: `multi-buy 2/$6.00` (flag + qty + bundle total, parseable,
  human-readable). Readers treat any cell starting `multi-buy` as the
  multi-buy state (backwards compatible with bare `multi-buy` cells).
- The effective unit rate is NOT stored — it is derived on read
  (`rate = total / qty`) so there is exactly one source of truth and no
  stale derived numbers. (Trade-off §11 D-MB1 vs. the brief's "store
  effective unit rate" — the rate is materialised in every output and
  in comparison math, just not persisted redundantly.)

### 7.3 Comparison algorithm

```
for each store price of an item:
    if multi-buy (qty N, total $X):
        effective_unit = X / N                       # e.g. 6.00/2 = $3.00
    else:
        effective_unit = price
compare stores on effective_unit                      # winner + totals
display:
    WW line:  $3.00/u  🏷️ 2 for $6.00  [Note: must purchase 2+ units to receive this price]
    Coles line unchanged
```

Rules (binding):
1. Effective unit rate participates in winner math, totals, and
   `optimize` savings EXACTLY like a normal price.
2. Every surface that shows a multi-buy-derived price MUST carry the
   note `[Note: must purchase 2+ units to receive this price]`
   (compare items, totals table footnote, search result lines that show
   a multi-buy special, specials report, shop output).
3. `Any N | $X` promotions that span MIXED products (cross-range "any
   2") do NOT yield a per-product rate: the item is priced normally and
   the promotion is shown as informational text only (§11 D-MB3).
4. Woolworths display discounts (5% / +5% home-brand) apply AFTER the
   rate computation, display-only, exactly as today; the sheet keeps
   raw values.
5. UOM gate is untouched: multi-buy never relaxes size comparability;
   the bundle multiplies PACK COUNT, not pack size.
6. Search results already print `🏷️ <special_desc>`; when the parsed
   multi-buy applies, the cheapest-store math uses the effective rate
   and the result block carries the mandatory note.

---

## 8. Spreadsheet synchronization & concurrency model

### 8.1 Write primitives (no race conditions, no range corruption)

| Operation | Mechanism |
|---|---|
| Row create (Q/R/S) | Single range write `A{row}:S{row}` inside `add_product_row` (atomic per row; existing explicit-range discipline means NO other write can clobber Q/R/S — ranges are always explicit). |
| Set P | ① read Q+S columns → ② compute the full new S-vector for that sub-category's row span (clears + the one set) → ③ ONE range write `S{top}:S{bottom}` → ④ re-read verify (one `P` max). Failure at any step aborts with the sheet untouched except a possible no-op clear (clears of empty cells are idempotent). |
| Code assign (new row) | reserve-verify loop, §8.2. |
| Batch backfill | ONE column write per column (Q, R) after computing all values in memory. |
| Rate limiting | existing `_update_with_backoff` (429 exponential backoff) reused everywhere. |

### 8.2 Item-Code generation algorithm (deterministic uniqueness)

```
alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ"        # 23 letters: A–Z minus I, L, O
shape    = 3 distinct letters               # 23×22×21 = 10,626 codes
taken    = set(Col R values) ∪ registry codes ∪ codes of rows deleted ever
                                                # deleted-row codes are NEVER reused
rng      = random.Random(seed = f"{spreadsheet_id}:{attempt}")
loop (≤ 200):
    candidate = 3 distinct rng.choice(alphabet) letters
    if candidate not in taken: break
else: deterministic sequential scan of the sorted permutation space
reserve:  write code to R{row} (single cell)
verify:   re-read Col R; if another row now holds the same code
          (concurrent writer), regenerate and retry  ← optimistic concurrency
persist:  registry[data/item_code_registry.json] = {code, row, assigned_at}
```

- Seed is stable per attempt (attempt increments on each retry), so
  runs are reproducible; uniqueness is guaranteed by check-then-write-
  then-verify, not by the seed.
- Local advisory file lock `data/.item_code_lock` serialises code
  generation between concurrent LOCAL processes; VPS-vs-local races are
  handled by the verify step (regenerate + retry). This matches the
  system's existing tolerance for cross-machine last-writer-writes
  (queue convergence solves queues; codes self-heal via retry).
- Capacity note: 10,626 codes vs ~104 rows today → 100× headroom; if the
  sheet ever approaches ~10,000 rows the shape widens to 4 letters
  (explicit future decision, out of scope now).

### 8.3 Preferred invariant maintenance

Every `P` write goes through `preferences.set_preferred` (single
writer function). The Wednesday sync NEVER touches column S. `prefer`
is the only command that writes S. Sheet-side manual edits are
repaired opportunistically: `shop`/`lists` detect >1 P in a
sub-category → ⚠️ line + the FIRST P (topmost) wins until
`prefer --code` fixes it (never auto-delete user data).

---

## 9. Read model

One `get_all_values()` per command run (existing pattern — `lists`
already does this). `LookupIndex` gains three additive parsed fields
per row (`subcategory`, `item_code`, `preferred`) exposed on
`CandidateRow`/result dicts. No change to the resolution chain order
(exact → alias → partial → live); Q/R/S ride along as metadata.

---

## 10. Name-truncation fix (user report 2026-09-04)

- `core/telegram_format.py`: `MAX_NAME_WIDTH` 24 → **60** cells.
  `item_block` keeps calling `truncate(name, MAX_NAME_WIDTH)` — now a
  60-cell safety valve instead of a 24-cell chop. Telegram wraps long
  plain-text lines; search results, compare titles, queue acks all show
  full names ("AJI CRISPY FRY BREADING MIX ORIGINAL WITH GRAVY MIX 62G"
  = 52 chars → fits untouched).
- `MAX_BLOCK_WIDTH` (34) for fenced monospace tables is UNCHANGED —
  those are the phone-fit totals tables; names inside them stay
  abbreviated by design.
- The disambiguation prompt (§6.4) and provenance lines already use
  full names; §6.4 mandates it.
- Telegram 4096-char message cap: existing chunking (Wednesday ≤4000
  parts) is reused; longer names only marginally affect part counts.

---

## 11. Decisions & Trade-offs (require explicit user confirmation)

| # | Decision | Rationale | Alternative rejected |
|---|---|---|---|
| D-SC1 | Sub-category values are free-text lowercase labels from a code-maintained ordered rule list (`core/subcategory.py`), NOT a closed enum | 104-row personal sheet; rules are auditable and testable; new clusters are one line of code | Closed enum (rigid) / pure LLM classification (non-deterministic, unverifiable in CI) |
| D-SC2 | Unconfident classification writes literal `needs review` (never a guess) and `lists` surfaces the count | Mirrors the proven `backfill-sizes` honesty pattern | Best-guess writes (silent mis-clustering breaks preference selection) |
| D-IC1 | Item-Code = LETTERS ONLY (no digits) from A–Z minus I/L/O, no repeated letter | Matches the established queue-code convention; voice/chat-friendly; the brief says "alphanumeric" but its own examples (ABC/DEF) are letters; digits would collide with the I/1-O/0 confusion the rule exists to prevent | Alphanumeric with digits (larger space, new confusion class) |
| D-IC2 | Codes are permanent; deleted-row codes are never reused (registry keeps them retired) | "Remove XYZ" style stale-chat safety, same reasoning as queue tombstones but permanent | Reuse after deletion (stale references could point at new rows) |
| D-IC3 | Row codes and queue codes are separate namespaces (both may contain e.g. `KAT`) | Contexts never mix (`prefer` vs `todo done`); zero migration cost | Shared namespace (forces re-coding 104 rows + queue collisions) |
| D-IC4 | Cross-machine (VPS+local) code races resolved by optimistic verify-and-regenerate, not a global lock | No shared lock infrastructure exists; failure mode is a retry, not corruption | Distributed lock (over-engineering for a single-user system) |
| D-P1 | New `shop` command instead of extending `compare` | Keeps `compare`'s look-only contract intact; SKILL.md routes list-intents to `shop` | Retrofit compare (changes behaviour of an established command) |
| D-P2 | Ingestion NEVER auto-sets P; the first `shop` run prompts once | Matches the "nothing is ever saved automatically" project rule | Auto-prefer the first/cheapest row (surprising, unreviewable) |
| D-P3 | Pending halted runs persist in `data/shop_pending.json` (24h staleness window) | Claw is conversational across turns; mirrors map-session progress pattern | In-memory only (dies between CLI invocations) |
| D-MB1 | Store raw terms `multi-buy 2/$6.00` in M/N; DERIVE the rate at read time | Single source of truth; no stale computed values; D25 readers stay compatible via prefix match | Persist the rate (a second number that can drift from the terms) |
| D-MB2 | Live multi-buy capture is best-effort: probe the real payloads first; degrade to normal pricing when absent | WW/Coles live payloads' multi-buy shape is UNVERIFIED (only docx markers are proven); never invent promos | Assume availability (risks hallucinated promos — violates the project's core rule) |
| D-MB3 | Mixed-product "Any N" promos are informational only (no rate in math) | A cross-product bundle has no true per-product price | Pro-rate across products (unsound for a 2-item comparison) |
| D-MB4 | Effective rate counts in winner/totals even if the user buys just 1 unit | The brief mandates it; the mandatory note discloses the assumption | Compare at single-unit price (ignores the deal the user asked to model) |
| D-T1 | `MAX_NAME_WIDTH` 24 → 60 (global single constant) | One-line fix, one width policy, full names everywhere; 60 keeps a sane guard | Per-surface widths (fragmented policy) / unlimited (formatting risk in odd clients) |
| D-X1 | `schema_upgrade.py` is the ONLY schema mutator; deploy runs it once (manual step M1) | Proven idempotent audit+append path from the M/N/O/P cycle | Ad-hoc column adds from every writer |

**Open items needing the user (blocking 02 Plan):**
1. Confirm D-IC1 (letters-only codes) — the brief says "alphanumeric".
2. Confirm D-P1 (`shop` as a new command) or insist on retrofitting
   `compare`.
3. Seed taxonomy sign-off: the initial rule list (~50 labels) will be
   drafted from the 104 live Col A names during 02 Plan and appended to
   this spec §12 before coding.

---

## 12. File boundaries — allowed scope for 02 Plan / 03 Code

**NOTE:** `grocery_price_cli.py` lives OUTSIDE the repo root at
`C:\Users\User.DESKTOP-R2G441H\Documents\AI related\grocery_price_cli.py`
(same binding note as the prior cycle — plan treats it as in-scope at
its current path).

MAY modify:
- `grocery_price_cli.py` — `shop`/`prefer`/`subcategories`/
  `backfill-subcategories`/`backfill-codes` commands; search rendering
  (nothing — width fix is in telegram_format); `--subcategory` flags on
  add paths; multi-buy note surfaces
- `core/telegram_format.py` — `MAX_NAME_WIDTH = 60`; multi-buy note
  helper (optional, small)
- `core/schema_upgrade.py` — Q/R/S in `NEW_COLUMNS`
- `core/sheets_sync.py` — `add_product_row` Q/R/S hook; multi-buy M/N
  cell encoding on sync/add paths
- `core/lookup.py` — ADDITIVE row metadata only (subcategory/item_code/
  preferred on `CandidateRow` + index build); chain order untouched
- `core/price_comparator.py` — multi-buy effective rates in winner/
  totals; mandatory notes; shop-mode row selection support
- `extractors/specials_parser.py` — expose `parse_multibuy` reexport for
  `core/multibuy.py` (no regex duplication)
- `extractors/models.py` — `ProductItem.multi_buy_qty/total` (defaults 0)
- `extractors/woolworths_extractor.py`, `extractors/coles_extractor.py`
  — best-effort multi-buy capture AFTER the D-MB2 probe
- NEW `core/subcategory.py`, `core/item_codes.py`, `core/preferences.py`,
  `core/multibuy.py`
- `claw-skills/grocery-price/SKILL.md` — LLM intake contract (§6.1),
  `shop`/`prefer` routing, verbatim prompt/warning relay rules
- Tests: NEW `test_subcategory.py`, `test_item_codes.py`,
  `test_preferences.py`, `test_multibuy.py`; UPDATE `test_cli.py`,
  `test_telegram_format.py`, `test_comparator.py`, `test_sheets_sync.py`,
  `test_lookup.py` (metadata only)
- `README.md`, `PROJECT-MAP.md` — per §C7 instructions

MUST NOT modify: `core/uom.py` (frozen), `core/name_matcher.py`
(read-only reuse), `telegram_gateway/`, `app.py`, `local_sync.py`,
`.env` handling, the queues' code/tombstone systems
(`searched_items.py`/`add_to_list.py` — Item-Code lives in its own
module), sheet columns A–P semantics.

---

## 13. Verification plan (for 04 Architect Checker)

1. Schema: `schema_upgrade` dry-run → adds exactly Q/R/S; re-run →
   "up to date"; existing A–P data byte-identical.
2. Codes: 200-row synthetic fixture → all codes unique, 3 letters,
   alphabet excludes I/L/O (case-insensitive), no repeated letter;
   registry matches sheet; concurrent-writer simulation → verify-retry
   path regenerates (injected collision).
3. Preferences: set P → sibling cleared, one write-range observed;
   two-P corruption fixture → ⚠️ detection, topmost wins, no deletion.
4. State machine: S0/S1/S4/S5 golden output tests (prompt text EXACT
   §6.4; warning text EXACT §6.5; pending-run round-trip; 24h staleness).
5. Multi-buy: parse cases (`2 for $6.00`, `Any 2 | $9`, bare
   `multi-buy` legacy cell, negative: `Cream For Men`); rate math;
   winner flips only via effective rate; mandatory note present on every
   multi-buy surface; mixed-product Any-N informational-only.
6. Ingestion: every add path (search/map/optimize) yields Q/R/S on the
   new row; merge path (one-line rule) leaves Q/R/S untouched; P empty.
7. Truncation: 52-char name renders fully in search; fenced tables
   still ≤34 wide; queue acks full-name.
8. Full suite green (baseline 621) with the new files included.

---

## 14. Coding model implementation instructions (README / PROJECT-MAP)

03 Code MUST, in the same change as the code:

1. **README.md** — Google Sheet schema table: add rows
   `| Q | Sub_Category | Granular cluster (bread, shredded cheese, eggs); "needs review" marker |`,
   `| R | Item_Code | Permanent 3-letter row ID, A–Z minus I/L/O, no repeats |`,
   `| S | Preferred | "P" flag; at most one per sub-category; set only via prefer |`;
   CLI table: add `shop`, `prefer`, `subcategories`,
   `backfill-subcategories`, `backfill-codes` rows; Telegram Style Kit
   section: `MAX_NAME_WIDTH = 60` note; new "Multi-buy pricing" section
   (rate math + mandatory note + D-MB2 degradation); new "Shopping list
   & preferences" section pointing at PROJECT-MAP §6F.
2. **PROJECT-MAP.md** — add §6F "Shopping-list flow (shop)": the plain-
   language walk of §6.2–§6.5 (cold start → prompt → prefer → warning);
   commands table rows for the five new commands; "the 7 lists" note
   that `needs review` sub-categories surface in `lists`; update the
   sheet column description (§2) with Q/R/S; note Item-Code ≠ queue
   codes.
3. **SKILL.md** — the §6.1 LLM intake contract: normalise lists against
   `subcategories` output, call `shop`, relay prompts/warnings VERBATIM
   (never rephrase codes), route "make X my usual/preferred" to
   `prefer --code`, keep the B5 never-browse rule.
4. Update `test.md` execution log per round, as every cycle does.

---

**Status footer:** DRAFT — awaiting user confirmation of §11 open items
1–3 (letters-only codes; `shop` command; taxonomy seed). Then LOCKED
for hand-off to 02 Plan with §12 boundaries and §13 verification as
binding.

---

## 15. Revision 2026-09-05 — user-directed overrides (post-deployment)

The user reviewed the deployed Q/R/S + multi-buy round and directed
three binding changes to §7/§11. Implemented and verified 2026-09-05
(925 tests green); the original D-numbers remain for history.

| # | Override | Detail |
|---|---|---|
| R1 (supersedes D-MB1's raw-price clause) | **Multi-buy deal rates live IN the price cells.** D/E for a multi-buy item holds the per-unit deal rate ("2 for $7.00" on $4.00 → 3.50) so the saving is evident in sheet comparisons. The M/N cell keeps the encoded terms (`multi-buy 2/$7.00`) as the deal's source of truth; when the deal ends the next sync overwrites the price normally (self-healing). | All three write paths (sync_prices, update_single_price, add_product_row) via `_multibuy_price`. |
| R2 (supersedes D-MB3) | **"Any N \| $X" promos are rate-eligible multi-buy deals** — in-store they mean any N units from the same range/brand, so they encode terms and drive rate math like "N for $X". `is_mixed_promo` removed. | Coles live capture now also composes `Any N | $X` as the specials desc when no other promo desc exists. |
| R3 (extends §8.3/D-SC2) | **Sub-categories: never guess.** Classifier hardened with word boundaries (V Sugarfree ≠ sugar, V Watermelon ≠ water, eggplant ≠ eggs, pineapple ≠ apples); unsure rows land in Col Q `needs review` and surface as **Sub-category reviews** (list 7 in `lists` + the weekly post). The agent MUST ask the user for the label when unsure (SKILL.md contract). | New `_sheet_multibuy_keys`/`_todo_is_multibuy` markers: `(m)` + legend `(m) - multi buy discount` on to-do/list views. |
