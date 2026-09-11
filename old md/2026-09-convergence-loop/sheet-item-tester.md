# SHEET ITEM TESTER — per-item audit + interpret/fix/re-run loop

> The standing test procedure for the v2 sheet: every item, one by one,
> through the real lookup path, with every entry recorded. Run this any
> time something looks wrong — the evidence tells you exactly what
> broke and the fix list writes itself.

## The three commands

All run from the tracker root with anaconda python. The audit is
READ-ONLY (never writes the sheet).

```bash
# 0. FULL FORMAT MATRIX — every item x every real-world message format
#    (exact / word-order drift / plural drift / halal-prefix on-off /
#    code-as-query / NL sample). ~500 real CLI runs, ~50 min.
#    MUST run when NO ingest is active (shared Google quota).
anaconda3/python.exe tools/item_audit.py --matrix

# 1. FULL audit — every item on the sheet, one lookup each
anaconda3/python.exe tools/item_audit.py

# 2. RE-RUN failures only (after fixes land)
anaconda3/python.exe tools/item_audit.py --items "Halal Lamb Mince, Woolworths Beef Mince 500g, …"

# 3. LIVE gateway sample (separate, costs nothing on the sheet):
#    fire 5–10 of the CSV's queries as real Telegram messages via
#    openclaw.mjs agent --deliver and compare with the CSV renders.
```

## Evidence (every run, timestamped)

- `data/test_logs/item_audit_<stamp>.csv` — one row per item:
  item, code, sheet row, query, **expected**, **actual**, verdict,
  full rendered reply
- `data/test_logs/item_audit_<stamp>_replies.txt` — the complete
  rendered reply per item (the human-readable receipts)

## What "correct" means (the judging rules baked into the driver)

| Item state (from the sheet) | Expected reply |
|---|---|
| WW price filled | WW display price (team discount + per-kg if pack known) + every local shop's price + 🏆 winner |
| WW price = GONE | "GONE at Woolworths" + local prices still shown |
| WW price = N/A <date> | "unavailable this week" + local prices |
| WW price blank + keyword filled | tracked-but-unavailable class |
| WW price blank + keyword blank + local prices | "not tracked at Woolworths — **missing list [CODE]**" + local prices |
| Nothing anywhere | "not tracked" |
| MEAT query (any of the above) | halal-scoped answer **+ the non-halal Woolworths twin line** ("also at Woolworths (non-halal): $… — …") whenever a plain meat row shares a content token |
| Any multibuy special in a quoted shop's Comments | the terms line ("min order 2kg for $29.99") rendered next to that shop's price |

The driver encodes these rules — verdicts are computed, not eyeballed.
The interpretation session still READS the rendered replies: automated
verdicts catch the mechanical breaks; human/AI review catches the
"technically correct but reads wrong" cases.

## The loop (run it in this order, in fresh sessions)

1. **EXECUTE** (this can be any session — it's one command): run the
   full audit. Commit the evidence dir.
2. **INTERPRET** (fresh session): read `item_audit_*.csv` +
   `*_replies.txt`. Classify every FAIL (and skim PASSes): real defect
   / judging-rule gap / data issue. Produce a numbered FIX LIST with
   reproducing commands. Fix nothing.
3. **FIX** (fresh coder session): strict prompt — "fix ONLY the numbered
   list; every fix ships a regression test; suite stays green."
4. **RE-RUN**: the full audit again — but the fix session must prove
   its own items via `--items "<the failed names>"` first.
5. Repeat 2→4 until the audit reports 0 FAIL. Then close out: move the
   round's evidence to `old md/`, update README/PROJECT-MAP if behavior
   changed, three-way sync.

## Regression rule (so fixes never rot)

Every fix from the interpret step adds its case to the audit's
expectations (or a unit test) — the next full run re-proves it
automatically. This is how the sheet stays trustworthy without weekly
battles.
