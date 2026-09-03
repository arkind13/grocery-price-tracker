# test.md — `todo gone` quick fix (03 Code Agent, 2026-09-03)

Fix: reviewing the to-do list and asking for an item to be "marked GONE"
confused the agent (the only unavailable-verb was `map --na`, which
overwrites the store keyword). New rule implemented verbatim: **leave the
keyword, write `GONE` into the store's price cell, remove the item from
the to-do list.**

## Changes

- `core/sheets_sync.py` — new `mark_price_gone(product_name, store)`:
  writes literal `GONE` into Col D/E ONLY (keyword Col I/J untouched);
  same two-step row match as `update_single_price`.
- `grocery_price_cli.py` — `todo gone --items "N,CODE,…"`: same
  all-or-nothing selection as `todo done`; removes entries from the
  queues, stamps the store price cell GONE, never calls
  `set_store_keyword`. `show` footer now advertises the gone verb.
- `claw-skills/grocery-price/SKILL.md` — `todo` row + routing row:
  "mark 2 as GONE" → `todo gone --items "2"`; explicitly forbids
  `map --na` / `missed-pricing --purge` for this.
- `claw-skills/claw_skills_easy.md` — regenerated (`skills_doc.py`),
  `--check` = OK.
- `README.md` — `todo` row documents `gone`.
- Tests: `tests/test_todo_cmd.py` (+4 `TestTodoGone`),
  `tests/test_sheets_sync.py` (+3 `mark_price_gone`).

## Test log

[PASS] | mark_price_gone writes price cell only, keyword kept | `python -m pytest tests/test_sheets_sync.py -q` | 77 passed
[PASS] | mark_price_gone not found / unknown store | (same run) | included above
[PASS] | todo gone marks price cell, never touches keyword | `python -m pytest tests/test_todo_cmd.py -q` | 24 passed
[PASS] | todo gone all-or-nothing (bad code aborts, no mutation) | (same run) | included above
[PASS] | todo gone row-not-found still removes from queue | (same run) | included above
[PASS] | todo gone requires --items (stderr, exit 1) | (same run) | included above
[PASS] | affected suites regression | `python -m pytest tests/test_todo_cmd.py tests/test_sheets_sync.py tests/test_cli.py tests/test_add_to_list.py tests/test_lists_cmd.py -q` | 266 passed
[PASS] | full suite (excluding network-dependent conn file) | `python -m pytest tests -q -p no:cacheprovider --ignore=tests/test_sheets_conn.py` | 755 passed, 2 failed (pre-existing, below)
[PASS] | parser smoke | `python ..\grocery_price_cli.py todo gone` | `Error: 'todo gone' requires --items …` exit 1 (expected)
[PASS] | claw skills catalogue | `python skills_doc.py --check` | `OK: claw_skills_easy.md is current.`
[FAIL → PRE-EXISTING] | test_cell_weeks_prefers_ledger_then_falls_back | `python -m pytest tests/test_missed_pricing.py -q` | `AssertionError: '2 weeks' != '3 weeks'` — date-boundary flake; fails identically on the clean tree (verified via stash of my changes before any fix); unrelated to this change (missed-pricing week-aging math vs today's date)
[FAIL → PRE-EXISTING] | test_seeded_history_shows_two_weeks_immediately | (same run) | `AssertionError: '1 week' != '2 weeks'` — same root cause, same clean-tree verification

## Notes / incident during round

- A `git stash`/`git stash pop` cycle used to verify the pre-existing
  failures hit Windows CRLF noise (`pop` refused to merge). Recovery:
  `git checkout -- .` (discarded EOL-only noise) → `git stash pop`
  (tracked changes restored; untracked files had never left). All edits
  verified present afterwards and suites re-run green. Stash dropped.

## Verdict

All green except 2 documented pre-existing date-flaky failures in
`tests/test_missed_pricing.py` (fail without this change too).
