# Test Results — Unified Telegram Message Formatting (03 Code)

- **Date:** 2026-08-28
- **Executed by:** 03 Code Agent (per `implementation-plan.md`, all phases 1–8)
- **Environment:** Windows PowerShell 5.1, Anaconda Python (`$env:PYTHONIOENCODING="utf-8"` set for every run)

---

## Baseline (recorded before ANY edit)

`pytest tests -q` → **8 failed, 191 passed** — NOT the all-green state the plan
assumed. All 8 failures are in `tests/test_extractors.py`:

| Failure | Cause | In scope? |
|---|---|---|
| `TestSessionManager::test_get_headers_no_cookie` | A saved Woolworths cookie file exists on this machine; test expects none | No (env state; extractor files are §4-prohibited) |
| `TestWoolworthsExtractor::test_parse_api_item*` (4) | ImportError — tests import `_parse_api_item`, which no longer exists in `extractors/woolworths_extractor.py` (test/code drift, pre-existing) | No (extractor APIs + their tests are §4-prohibited) |
| `TestColesExtractor::test_parse_search_result*` (3) | Same drift for `_parse_search_result` in `coles_extractor.py` | No |

Gate applied instead of the plan's "all 199 pass": **no NEW failures vs this
baseline; all formatting-related tests pass.** Baseline and final skip count: 0
(no skips introduced).

One transient flake observed during Phase 2 verification:
`test_name_matcher.py::test_append_unmatched_is_idempotent` failed once in a
combined run, then passed in isolation, in the full module (25/25), and in
three consecutive full-suite runs. Shared `data/` file contention — unrelated
to formatting (name_matcher logic untouched).

---

## Phase results

| Phase | Verification | Result |
|---|---|---|
| 1 — `core/telegram_format.py` + `tests/test_telegram_format.py` | `pytest tests/test_telegram_format.py -q` | **PASS** — 23/25 immediately; the 2 §5.3 invariant tests were intentionally red (TDD, they assert the NEW core formatters) until Phase 2 landed. Final: **25/25 PASS** |
| 2 — core formatter swaps + §5.2 updates | `pytest tests -q` | **PASS** — 8 pre-existing failures only, 219 passed |
| 3 — `grocery_price_cli.py` restyle | `pytest tests -q` + `py_compile ..\grocery_price_cli.py` | **PASS** — one name-shadowing bug caught and fixed (local `header = all_values[0]` shadowed the imported `header()` in `_cmd_backfill_home_brands`; renamed to `sheet_header`). Compile OK |
| 4 — gateway scripts | `py_compile` both files | **PASS** |
| 5 — 8 sibling tools | `py_compile` all 8 | **PASS** |
| 6 — SKILL.md relay rules | grep for remaining "Markdown table" instructions | **PASS** — zero remaining; internal documentation tables left intact per plan |
| 7 — README | archive reference check | **PASS** — `architecture-spec-woolworths-discounts.md` confirmed absent; reference now points to `architecture-spec.md` with a note; kit section documents the shipped API |
| 8.1 — full suite | `pytest tests -q` | **PASS** — **219 passed, 8 failed (all pre-existing extractor), 0 skipped** |
| 8.2 — pipe-table ban grep | `\|---\|\| # \|` over `*.py`, whole workspace | **PASS — ZERO matches** |
| 8.2b — `parse_mode` grep | whole workspace `*.py` | **PASS** — only pre-existing occurrences (`daily_digest.py` HTML pipeline, untouched `handlers.py`, a comment). Zero added |
| 8.3 — smoke `compare --items "green capsicum"` | live | **PASS** (rendered; that exact query has no sheet/live price → empty-prices render, still correctly styled) |
| 8.3 — smoke `compare --items "milk"` | live | **PASS** — full render: 🛒 header, 🏠 item block, aligned 🟢/🔴 lines, fenced box TOTALS (equal-length lines), 🏷️ HOME BRAND EXTRA sub-block, 🏆 + 🏷️ tails |
| 8.3 — smoke `specials` | live | **PASS** — 🏷️ header, numbered list, `·` separators, 📊 count |
| 8.3 — smoke `search --product "green capsicum"` | live | **PASS** — 🔍 header, item blocks, bracket-form WW discounts, 🏷️ special suffix, `…` truncation, 🏆 tail |

### Scope audit (plan §6)

- `git diff` hunk ranges verified: changes in `core/` are confined to
  `format_report` (+ its new helper), `format_discount_report`, and
  `format_specials_report` + the `__main__` rewards block.
  `discounted_woolworths_price` / `format_discounted_price` byte-identical
  (no hunks before line 415 of `woolworths_discounts.py`).
- `telegram_gateway/handlers.py` untouched. No sheet-write, lookup/sync, or
  extractor logic touched. No flag/arg/exit-code changes in any CLI.
- Files changed = exactly the §"May modify" list. Pre-existing dirty files
  (`.kilo/agent/*`, `Development Workflow/*` deletions, xlsx/docx/data files,
  main-repo `README.md`, `tests/test_name_matcher.py`, `architecture-spec.md`,
  `implementation-plan.md`) were NOT touched by this agent.

---

## Test-matrix coverage (plan §5.1 — all 17 + §5.3 invariants)

All 17 required tests implemented in `tests/test_telegram_format.py` plus
`test_divider_default_and_custom`, `test_store_line_unknown_store`,
`test_item_block_numbered_lines_indented`, `test_fenced_table_money_columns_right_aligned`,
and the three §5.3 real-formatter invariant tests. **25/25 pass.**

---

## Deviations from the plan (all documented, none behavioral)

1. **Baseline gate adjusted.** Plan expected 199/199 passing; measured baseline
   is 8 failed / 191 passed (extractor test drift + local cookie file). Gate
   applied: no new failures; formatting tests all green. Extractor files are
   §4-prohibited, so not fixed here.
2. **Three test spots updated beyond §5.2's list** (necessary consequence of
   the approved format contracts; assert content, not byte-equality):
   - `tests/test_cli.py:181` — `"Total:"` → `"pending unmapped item(s)"`
     (unmapped count line is now `📊 N pending unmapped item(s)`).
   - `tests/test_cli.py:770` — `"**Cheapest:** Woolworths at $3.61"` →
     `"Cheapest: Woolworths at $3.61"` (search tail is now `🏆 Cheapest: …`;
     bold markup dropped from the assert). Line 768 was kept green by design:
     the search WW line intentionally keeps `format_discounted_price`'s
     §9-approved bracket form.
   - `tests/test_cli.py:903` — `"**Total:** 2 specials"` → `"2 specials"`
     (Wednesday Step-8 count line is now `📊 2 specials`; pipe table removed
     per the golden rule — this builder must not emit tables to Telegram).
3. **`_build_ww_specials_lines` restyled.** Not in the Phase-3 table, but it
   printed a pipe table to Telegram, which violates locked decision #2.
   Now list-style + 📊 count.
4. **`Discount_github.py` NOT changed.** It is a Streamlit stub (browser UI,
   no stdout rows exist to restyle). py_compile gate passes.
5. **`Code_for_usage.py` gained a 📊 stdout block** (grand totals + fenced
   per-model table). The file had no tabular stdout before (data went to
   Excel only); plan asked for "📊 header + fenced usage table", so the block
   was added — display-only, Excel output unchanged. `--query` single-value
   outputs are deliberately untouched (machine-readable contract).
6. **`daily_digest.py` minimal touch.** It already used the kit skeleton
   (heavy separators, per-model cards); only the digest header was retitled to
   the 📅 vocabulary. Its HTML parse_mode pipeline is pre-existing and was NOT
   extended.
7. **`fenced_table` `box=True` includes the ``` fences** around the ╔═╗ box
   (plan §3's sample is ambiguous); equal-length lines contract enforced by
   tests.
8. **🏷️ WW-discounts tail line includes per-component amounts** —
   `🏷️ WW discounts: −$0.75 (5% all $0.20 + 🏠 home extra $0.19 + extra 10%
   $0.36)` — because §5.2 requires asserting `"5%"` AND `"0.20"` while §2a
   requires composing the total from team+home+extra. Shape preserved
   (`🏷️ WW discounts: −$X (…)`).

---

## Status

Phases 1–8 COMPLETE. Phase 9 (git commits, GitHub push, VPS tar/scp sync,
docker restart, faithful Telegram test) is MANUAL — handed to the user below.
