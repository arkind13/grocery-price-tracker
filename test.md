# test.md — missed-pricing GONE + grouped/coded lists (03 Code Agent, 2026-09-03)

Three user requests implemented on top of the morning's `todo gone` fix:

1. **GONE on missed pricing** — same rule as the to-do: leave the keyword,
   mark the price cell GONE, delete the item from the list.
   `missed-pricing gone --items "N,CODE"`.
2. **Lists separated into Woolworths / Coles / Both headers** — the
   missed-pricing report, `lists --full`, and the Wednesday Telegram
   weekly-lists post are now grouped under WOOLWORTHS / COLES /
   BOTH STORES headers.
3. **3-letter codes on missed-pricing items** — deterministic
   alphabetical codes (A–Z minus I/O, no repeated letters: ABC, ABD, …),
   allocated in report order (fixable then delete-pending), accepted by
   `gone --items` alongside numbers.

## Changes

- `grocery_price_cli.py`
  - `_mp_code_iter` / `_assign_mp_codes` / `_split_fixable_by_store` /
    `_numbered` / `_resolve_missed_items` — codes + grouping + selection.
  - `_format_missed_fix` / `_format_missed_dead` — `[CODE]` prefix.
  - `_archive_and_delete_rows` — shared purge/gone archive+delete path.
  - `_cmd_missed_pricing` — positional `show|gone` action (flags kept),
    grouped render, gone flow (fixable → one store stamped; delete-pending
    → both stores stamped + row deleted immediately, archived, ledger
    cleared).
  - `lists --full` — three grouped missed-pricing blocks with codes.
  - Wednesday Step 7 — Telegram post splits "No-price items" into
    ("Missed pricing — Woolworths" / "— Coles" / "— Both stores
    (delete-pending)") with coded lines.
  - `no-price` alias updated for the new action Namespace.
- `claw-skills/grocery-price/SKILL.md` — `missed-pricing` row (gone +
  codes + grouped headers), list-6 description, routing rows for
  "mark N GONE (missed pricing)" and "split lists by store".
- `claw-skills/claw_skills_easy.md` — regenerated, `--check` OK
  (content unchanged: catalogue embeds frontmatter only).
- `README.md` — missed-pricing row + Wednesday post description.
- Tests (`tests/test_missed_pricing.py`): +10 (codes determinism,
  store split, gone by code/number/mixed, requires-items,
  unknown-code abort, dead-row both-store stamp + immediate archive
  delete, grouped render) and 1 updated (`test_report_groups` — new
  summary counts).

## Test log

[PASS] | codes deterministic, unique, same-alphabet, no repeats | `python -m pytest tests/test_missed_pricing.py -q` | 31 passed, 2 failed (pre-existing, below)
[PASS] | split fixable by store | (same run) | included
[PASS] | gone by code → one store stamped, keyword untouched, no delete | (same run) | included
[PASS] | gone delete-pending by number → both stores stamped + row archived-deleted | (same run) | included
[PASS] | gone requires --items (exit 1) | (same run) | included
[PASS] | gone unknown code aborts, nothing written | (same run) | included
[PASS] | mixed number+code selection dedupes | (same run) | included
[PASS] | show renders WOOLWORTHS / COLES / BOTH headers with [CODE] lines | (same run) | included
[PASS] | purge still archives + clears ledger (existing suite) | (same run) | included
[PASS] | full suite | `python -m pytest tests -q --ignore=tests/test_sheets_conn.py` | 763 passed, 2 failed (pre-existing, below)
[PASS] | claw skills catalogue | `python skills_doc.py --check` | `OK: claw_skills_easy.md is current.`
[FAIL → PRE-EXISTING] | test_cell_weeks_prefers_ledger_then_falls_back | `tests/test_missed_pricing.py` | `'2 weeks' != '3 weeks'` — date-boundary flake, fails identically on the clean tree (verified this morning via stash before any change); unrelated to this work
[FAIL → PRE-EXISTING] | test_seeded_history_shows_two_weeks_immediately | (same file) | `'1 week' != '2 weeks'` — same root cause

## Verdict

All green except the 2 documented pre-existing date-flaky failures in
`tests/test_missed_pricing.py` (they fail without this change too; the
`_days_ago(21)`/`_days_ago(14)` seeds straddle the week-boundary
rounding on today's date). Deployment: scp of the 4 changed runtime
files to the VPS + md5 verification on both sides.
