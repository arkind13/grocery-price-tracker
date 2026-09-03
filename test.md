# test.md — Wednesday restructure: to-do-first flow, searched retired,
# forgotten count-only (03 Code Agent, 2026-09-03)

User-defined Wednesday flow implemented verbatim:

1. **Start:** the run OPENS with the to-do list (items pending to add on
   the store websites) → user adds them on the sites → copies the
   updated lists into the Word docs → types `done`.
2. **After `done`:** the sync runs (auto-heal → match → price sync →
   two-strike dead-row delete) and the report gives unmatched,
   Woolworths/Coles missing, missed pricing (updated week counts via
   the first-fail ledger).
3. **Step 3c TALLY:** to-do entries whose sheet row now carries the
   store keyword are cleared; the UPDATED to-do list prints and posts
   FIRST in Telegram.
4. **Searched items queue: DELETED completely** from the pipeline
   (command now a retired stub; todo = add_to_list only; Step 1b drain
   removed; Step 0/9 converge add_to_list only; search --add-item and
   map unmatched --add and optimize +add now queue on the TO-DO list).
5. **Forgotten items: COUNT only** unless asked (`lists --full` shows
   names; the Telegram post and plain `lists` show counts).

## Changes

- `grocery_price_cli.py`
  - `_print_queue_snapshot` — Wednesday opens with the coded to-do list.
  - `_wait_for_manual_adds` — pause wording now references the to-do.
  - `_tally_todo_with_sheet` (NEW, Step 3c) — sheet keyword check per
    entry, all-or-nothing code removal, prints the updated to-do list.
  - Step 1b searched drain REMOVED; Step 0/Step 9 queue sync converges
    add_to_list.json + its tombstones only.
  - `searched-items` command → retired stub (prints pointer, exit 0).
  - `_todo_merged_entries`/`_cmd_todo` — add-only (searched branches
    removed); `add-to-list` alias simplified.
  - `_queue_searched_item` removed; `search --add-item` + `map
    unmatched --add` queue on the TO-DO list via `_queue_add_to_list`.
  - `_load_queues` (optimize) → to-do only; confirm ack `[todo: CODE]`.
  - `_weekly_queue_lists` — To-do (with codes, posted FIRST) +
    Forgotten count-only; Searched tuple removed.
  - `lists` — list 4 = to-do only; forgotten count-only in the summary.
- `core/basket_confirm.py` — `_queued_somewhere` checks the to-do list
  (legacy "searched" key tolerated); `_add_new_product` queues via
  `add_to_list.add_entry` instead of searched_items.
- `core/searched_items.py` — kept as dormant legacy (no CLI imports it
  anymore); its unit tests still pass in isolation.
- `claw-skills/grocery-price/SKILL.md` — wednesday flow, todo/lists/
  add-to-list/searched-items rows, routing rows (incl. retired
  searched), queue phrases; catalogue regenerated, `--check` OK.
- `README.md` — todo/lists/wednesday/add-to-list/searched-items rows +
  no-gaps note updated.
- Tests: test_todo_cmd rewritten (add-only); test_cli CLI-11..14 →
  retirement stub test; cli6/7/9/16, wc7, queue-confirmation, weekly-
  lists, lists-cmd, basket-confirm tests updated to the new rules.
  Net: 10 new/updated in this round (todo rewrite + tally coverage via
  rerouted suites).

## Test log

[PASS] | todo view: add-only, coded, Coles→Woolworths | `python -m pytest tests/test_todo_cmd.py tests/test_add_to_list.py -q` | 40 passed
[PASS] | done writes keywords + removes; gone marks GONE, keyword kept | (same run) | included
[PASS] | searched-items retired stub routes to todo show | `python -m pytest tests/test_cli.py -q` | 126 passed
[PASS] | search --add-item queues on the TO-DO list (not searched) | (same run) | included
[PASS] | map unmatched --add queues on the TO-DO list | (same run) | included
[PASS] | Step 0 pulls add_to_list + tombstones only (no searched) | (same run) | included
[PASS] | weekly-lists: To-do FIRST + Forgotten count-only, no Searched | (same run) | included
[PASS] | lists counts: #4 = to-do only, forgotten count in summary | `python -m pytest tests/test_lists_cmd.py -q` | included in full run
[PASS] | optimize classification + confirm queue via add_to_list | `python -m pytest tests/test_basket_confirm.py -q` | included in full run
[PASS] | full suite | `python -m pytest tests -q --ignore=tests/test_sheets_conn.py` | 759 passed, 2 failed (pre-existing date flakes, below)
[PASS] | claw skills catalogue | `python skills_doc.py --check` | `OK: claw_skills_easy.md is current.`
[FAIL → PRE-EXISTING] | test_cell_weeks_prefers_ledger_then_falls_back | `tests/test_missed_pricing.py` | `'2 weeks' != '3 weeks'` — date-boundary flake, fails identically on the clean tree (verified earlier today via stash); unrelated
[FAIL → PRE-EXISTING] | test_seeded_history_shows_two_weeks_immediately | (same file) | `'1 week' != '2 weeks'` — same root cause

## Verdict

All green except the 2 documented pre-existing date-flaky failures.
Deployment: CLI + skill files scp'd to the VPS, md5 verified on both
sides (bind-mounted — live for the next Wednesday run).
