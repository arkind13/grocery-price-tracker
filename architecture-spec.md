# Architecture Spec — Units Always Visible (Col C = the single unit source)

- **Date:** 2026-09-01
- **Stage:** 01 Architect (this doc) → 02 Plan → 03 Code → 04 Architect Checker
- **Status:** CONFIRMED by user (chat 2026-08-31/09-01) — both binding
  rules and all four architect decisions D-U1…D-U4 approved
  ("confirmed", 2026-09-01). Ready for 02 Plan.
- **Inputs:** user chat 2026-08-31 ("units everywhere, force Col C on every
  add") + full code inspection 2026-09-01 (files listed in §7) +
  `read.me` roadmap + `PROJECT-MAP.md`.
- **Replaces:** the previous spec at this path (D23–D27 + B4/B5 finish line,
  2026-08-30 — that cycle is implemented and verified per `test.md`; its
  spec/plan remain in git history).

---

## 1. Goal (plain language)

The Google Sheet **already has a unit column: Col C** ("size" — e.g.
`1L`, `250g`, `6 x 170g`). The system reads it (`core/lookup.py:203`) and
even carries it through lookups (`matched_sizes`). But today:

1. **Display:** every renderer silently DROPS the unit when it is missing
   (`_size_suffix` in the CLI returns `""`; `_identity_suffix` in the
   comparator omits the size segment; found-blocks never show size).
2. **Writes:** every add path accepts an empty size (`add_product_row`
   has `size: str = ""` optional) — so rows enter the sheet with a blank
   Col C and stay that way forever.

This spec makes two binding rules true everywhere:

- **Rule A (display):** wherever a product is mentioned — search, compare,
  recipe, specials, queues, Wednesday lists — the unit is ALWAYS shown;
  when unknown, an explicit note **"unit unavailable"** is shown instead.
  Silent omission is banned.
- **Rule B (writes):** every path that adds a product to the sheet or a
  queue must resolve the unit first (live listing → name-parse → ask the
  user) and fills Col C; if genuinely unknown, the canonical marker
  `unit unavailable` is written so the row is never silently blank.

Result: next time the user asks anything, the answer reads the unit from
Col C — known or explicitly marked unknown.

---

## 2. Data contract (single source of truth)

| Item | Value |
|---|---|
| Canonical marker (Col C + display) | `unit unavailable` (exact lowercase phrase — the user's own words) |
| Display helper | NEW `core/telegram_format.py : unit_tag(size) -> str` — returns the trimmed size, or `unit unavailable` when empty/blank/marker. ONE helper, every renderer calls it (DRY) |
| Col C states | real size (`1L`, `250g`, `5 pack`) = known; `unit unavailable` = assessed, unknown; blank = legacy, not yet assessed. Marker and blank display identically |
| Queue entries (`searched_items.json`, `add_to_list.json`, missing-queues) | every NEW entry carries `"size"` (real value or marker). Old entries without the key read as blank → display the note |
| UOM gate | UNCHANGED. `core/uom.py : parse_size("unit unavailable")` → `None` → existing `missing_size` → NOT_COMPARABLE. No gate logic touched |

---

## 3. Rule A — Display surfaces (file : anchor → change)

| # | Surface | Anchor (current behaviour) | Change |
|---|---|---|---|
| A1 | Search result lines | `grocery_price_cli.py:616-617` `_size_suffix` returns `""` when missing | call `unit_tag`; render ` · 1L` or ` · ⚠️ unit unavailable` |
| A2 | Compare store lines (provenance) | `core/price_comparator.py:615-635` `_identity_suffix` omits size segment when empty | size segment ALWAYS present: ` — <name> <unit_tag> (<source>)` |
| A3 | Compare item title | `core/telegram_format.py:291-316` `item_block` — name truncated to 24 cells, no unit slot | `item_block` gains `unit` param; tag appended AFTER truncation so the unit is NEVER cut off; comparator passes `item.matched_sizes` (WW/Coles may differ → show the store's own on store lines A2; title shows Woolworths' if present, else Coles') |
| A4 | Compare found-blocks | `core/price_comparator.py:644-664` shows name only; `closest[store]["size"]` exists unused | append ` · <unit_tag(size)>` per store line |
| A5 | Lookup Step 3 candidates | `core/lookup.py` `CandidateRow.size` populated; rendered by CLI | candidate lines show ` · <unit_tag(size)>` |
| A6 | Step 5 confirm + queue ack | `grocery_price_cli.py:536-543` `_print_queue_confirmation` shows keyword only | show ` · <unit_tag(entry["size"])>`; `Queued for Wednesday: 'X' · 200g (Coles) [KAT]` |
| A7 | Specials report | `core/specials_reporter.py:224` `format_specials_report` | each item line appends ` · <unit_tag(row size)>` (sheet rows and live WW items both carry size) |
| A8 | Queue shows | `core/searched_items.py` show; `core/add_to_list.py` show; CLI `_cmd_add_to_list` / `_cmd_searched_items` | entry lines show ` · <unit_tag(entry size)>` |
| A9 | Wednesday summary lists | CLI `_cmd_wednesday` + `core/missing_items_tracker.py` (wool/coles missing) + unmatched queue display | every product line in unmatched / wool-missing / coles-missing / price-unavailable lists shows ` · <unit_tag(size)>` |
| A10 | Recipe answers | flows through `format_report` | covered by A2–A4 |

Formatting rule for all surfaces: known unit → ` · 1L`; unknown →
` · ⚠️ unit unavailable`. No markdown tables; stays inside the Telegram
Style Kit skeleton.

---

## 4. Rule B — Force-fill on every add path

**Unit resolution chain (in order), applied by every add path:**
1. live listing size field (`ProductItem.size` from WW/Coles extractors);
2. parse from the product name (`core/name_matcher.py:229` `_SIZE_PATTERN`
   — already extracts `1L`, `500g`, `pk/pack`);
3. **ask the user** (interactive map sessions and the `--add-item` chat
   flow — Claw is conversational): "What unit is <product>? e.g. 1L /
   250g / 5 pack — reply, or 'unknown'";
4. still unknown (user replies 'unknown' / non-interactive Wednesday
   auto-add) → canonical marker `unit unavailable`.

**Paths and required behaviour:**

| # | Path | Anchor | Change |
|---|---|---|---|
| B1 | `search --add-item N` (Step 5 auto-add) | `grocery_price_cli.py:695-735`; `core/sheets_sync.py:678` `add_product_row` | resolve chain BEFORE writing; `add_product_row` `size` param becomes REQUIRED (fail-fast error `unit is required: pass a size or the marker`); queue entry always carries `"size"` |
| B2 | `map unmatched --add` (incl. live route) | `grocery_price_cli.py:2289-2323`; same | same chain; unmatched queue entries carry `"size"` |
| B3 | `map wool` / `map coles` (add / keyword / exact name) | `grocery_price_cli.py:2379+` | same chain; row write + `add_to_list` entry carry `"size"` |
| B4 | To-do list (`add_to_list.json`) | `core/add_to_list.py` (entry shape, line 11-14) | `"size"` key added to entry schema + `add_entry` signature |
| B5 | Searched list (`searched_items.json`) | `core/searched_items.py` (size already optional, line 26) | `"size"` always present on new entries (marker allowed) |
| B6 | Wool/Coles missing queues | `core/missing_items_tracker.py:160-186` | entries copy `"size"` from the source store's sheet row (Col C) |
| B7 | Wednesday sync new rows | `sync_prices` path | any row created during sync gets size via steps 1-2 of the chain, else marker |

---

## 5. Rule C — Heal the ~existing legacy rows

1. **Backfill on write:** `core/sheets_sync.py : update_single_price` and
   `sync_prices` — when writing a price to a row whose Col C is BLANK and
   a size is parseable from the matched store name → include Col C in the
   same row write (one extra cell, atomic, no extra API call).
2. **One-time command** `backfill-sizes` (mirror of existing
   `backfill-keywords`, CLI :3006): parse Col A / Col I / Col J names for
   sizes via `_SIZE_PATTERN`, fill blank Col C cells, report the count
   filled vs. left blank. Left-blank cells keep showing the note — the
   user can fill them by hand over time.
3. No bulk overwrites: a non-empty Col C is NEVER modified by any
   automated path.

---

## 6. Frozen / explicitly unchanged

- `core/uom.py` — verdict semantics, 20% gate, families. Zero changes.
- `core/extractors/` — scrapers already return `ProductItem.size`; no
  extractor changes.
- Google Sheet schema — NO new columns. Col C exists; header untouched.
- `telegram_gateway/` (separate repo), `app.py` (legacy Streamlit),
  `local_sync.py` (legacy).
- Queue file formats stay JSON lists; only additive `"size"` keys
  (backwards-compatible reads everywhere — old entries read as blank).

---

## 7. File boundaries — allowed scope for 02 Plan / 03 Code

**NOTE:** `grocery_price_cli.py` lives OUTSIDE the repo root, at
`C:\Users\User.DESKTOP-R2G441H\Documents\AI related\grocery_price_cli.py`
(README §9 "pending migration" zone; `deploy_vps.py:45` expects it in the
repo root). Planning must treat it as in-scope at its current path and
flag the copy-to-root mismatch in the plan.

MAY modify:
- `grocery_price_cli.py` — A1, A5, A6, A9; B1-B3 ask-unit step;
  `backfill-sizes` command (B/C)
- `core/telegram_format.py` — `unit_tag()`; `item_block` unit param (A3)
- `core/price_comparator.py` — `_identity_suffix`, `_found_block_lines`,
  `format_report` title tags (A2-A4)
- `core/sheets_sync.py` — `add_product_row` required size; backfill in
  `update_single_price` / `sync_prices`; `backfill_sizes()` function
- `core/searched_items.py`, `core/add_to_list.py` — size always on new
  entries; show rendering (A8, B4-B5)
- `core/missing_items_tracker.py` — size in entries (B6, A9)
- `core/specials_reporter.py` — unit tags (A7)
- `PROJECT-MAP.md`, `README.md` — already updated by architect (2026-09-01);
  planner keeps them in sync if behaviour shifts
- Tests: `test_telegram_format.py`, `test_comparator.py`, `test_cli.py`,
  `test_searched_items.py`, `test_add_to_list.py`, `test_sheets_sync.py`
  (+ `test_specials_flags.py` if A7 needs it)

MUST NOT modify: `core/uom.py`, `core/lookup.py` (verify-only — size data
already flows; rendering lives elsewhere), `core/extractors/*`,
`core/name_matcher.py` (optional multipack pattern improvement explicitly
OUT of this cycle), sheet schema, `.env` handling, gateway repo.

---

## 8. Verification plan (for 04 Checker)

1. `unit_tag` unit tests: real size / blank / None / marker / whitespace.
2. Search display test: item with size → ` · 200g`; item without →
   ` · ⚠️ unit unavailable` (exact string).
3. Compare tests: title tag survives 24-cell truncation; `_identity_suffix`
   no longer has a no-size branch; found-block shows size from `closest`.
4. `add_product_row` rejects empty size (fail-fast) and accepts marker.
5. Queue round-trip: add via `--add-item` → entry JSON has `"size"`;
   `show` prints the tag; legacy entry without `"size"` prints the note.
6. `update_single_price` backfills a blank Col C exactly once (second run
   writes nothing to C).
7. Full suite: `python -m pytest tests/ -x -q` green.

---

## 9. Risks / open items

- R1: The `--add-item` and map flows become interactive when size is
  missing (one extra chat question). Claw relays it; one-shot CLI runs
  without size fail fast with the required-unit error (deliberate —
  matches "forced").
- R2: Size strings are display-only text; slight format drift between
  stores (`1L` vs `1 L`) is acceptable — the UOM gate normalises via
  `parse_size` where comparability matters.
- R3: Col A names that already embed the unit (`Milk 2L`) plus a Col C
  unit will show the unit twice on titles. Accepted: correctness beats
  dedup elegance this cycle; note for a later polish pass.

---

## 10. Decision log

Confirmed by user (2026-08-31):
- U-YES-1: units shown EVERYWHERE a product is mentioned (not just
  search/compare).
- U-YES-2: Col C is the unit column; every add path (unmatched, wool/coles
  missing, to-do, searched) is FORCED to fill it.
- U-YES-3: unknown unit → explicit "unit unavailable" note, never silence.

Architect decisions — CONFIRMED by user ("confirmed", 2026-09-01):
- **D-U1:** when unknown after the ask-step, write the literal marker
  `unit unavailable` INTO Col C (blank stays reserved for never-assessed
  legacy rows). Both display identically.
- **D-U2:** display format ` · 1L` vs ` · ⚠️ unit unavailable`; the tag is
  appended after name truncation so it can never be cut off.
- **D-U3:** `backfill-sizes` command fills only parseable legacy rows;
  the rest stay blank (and show the note) — no guessed sizes, no bulk
  marker write.
- **D-U4:** interactive ask happens ONCE per add; replying `unknown`
  writes the marker and never blocks the add.

---

**Status footer:** LOCKED — user-confirmed 2026-09-01. Hand-off to
02 Plan with file boundaries §7 and verification plan §8 as binding.
