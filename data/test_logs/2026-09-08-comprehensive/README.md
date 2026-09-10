# 2026-09-08 comprehensive test round — READ BEFORE RE-RUNNING TESTS

This folder is the FULL test evidence of the 2026-09-08 quality campaign
(the big round: every user-facing command + the 500-item sheet battery).
**Check `commands_log.csv` first — if the test you're about to run is
already listed there with a PASS, do not blindly re-run it; start from
these receipts and test only the delta.**

## What was covered (all receipts in commands_log.csv, full outputs in outputs/)
- T1 (57 cmds): compare sheet-mode over ALL 113 sheet rows in batches,
  12 compare variants (auto/discounts/halal/misspelled/quotes/empty),
  20 analysis cmds (specials, rewards, analyze, recipe, optimize,
  lists, missed-pricing, todo, unmapped)
- T2 (20 cmds): live searches on real Woolworths API + Coles/Scrape.do —
  junk, unicode, injection string, 200-char, --expand, breaker behavior
- T3: wednesday --dry-run full pipeline
- T4 (~40 cmds): to-do done/gone lifecycle, missed-pricing gone →
  delete-pending → row delete + archive, map unmatched/wool/coles
  (--next/--skip/--add/--forget/--na error paths), all-or-nothing rules
- T5 (20 cmds): error paths + dry-runs (update bad-store/unknown,
  retired commands, backfills, prefer/shop/analyze invalid inputs)
- T6/T7 (11 cmds): local-deals ingest, freshness gate, expire-sweep,
  set-permanent/special, post-log, friday-gate, daily-scan off-window
- T8: 500-item battery (113 real + 387 synthetic; t8_items_manifest.csv
  + t8_ops_log.csv) — add/update/alias/keyword/NA/GONE-resurrect/
  merge-rule/dup-guard/teardown with per-op pass-fail

## How to re-run any of it
`harness.py run <id> <label> -- <args>` or
`harness.py batch <batch_file.json>` (batches: batch_t1_*.json,
batch_t2.json, batch_t4*.json, batch_t5.json, batch_t67.json).
Interpreter: anaconda3 python (not the default python3.13).
Known harness bugs to avoid repeating are listed in the verification
rounds' reports (see old md/2026-09-quality-round/).

## After this round, these defects were found and later FIXED (22) —
see defects.md here + old md/2026-09-quality-round/round-2 and round-3
verification reports. Re-run a fix's regression check before trusting it.
