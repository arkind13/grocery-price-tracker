# PROJECT-MAP — grocery tracker v2 in plain language

> v2 reality, 2026-09-10. The v1 map (Coles/Aldi, queues, 7 lists) is
> archived in `old md/`.

## The 30-second version

Four local shops post prices on Facebook, and Nazar Butchery lists
its whole catalogue (permanent prices, no deals) on its own website.
You
buy mutton, chicken and fruit & veg. Woolworths is your fallback store
(your team discount usually wins). This project keeps ONE sheet with
both sides and tells you where each item is cheaper — in seconds, from
Telegram.

## What you can say in Telegram (the 8 commands)

| You type | You get |
|----------|---------|
| "price of halal beef mince" (or just the item) | Woolworths price + every local shop's price + 🏆 winner. Meat items also show the non-halal Woolworths twin ("also at Woolworths (non-halal): $13.54 — …"). Messy wording is fine: "price of X", "how much is X", plurals and typos all find the same row, and the answer's [code] always names the row you actually asked about |
| "live beef mince" | Fresh web search, Woolworths + Coles + Aldi, 3 prices each. Prices only — nothing is ever added |
| "list" | The ONE list: local items you haven't tracked at Woolies yet, each with a code |
| "what's on special" | Asks you WHICH SHOP first (Woolworths / Aldi / local shops), then shows that shop's specials. Name the shop in the question ("aldi specials") and it skips the ask |
| "specials" | Woolworths specials from the sheet |
| "AUG done; EPJ gone; XYZ rename halal lamb shoulder" | One call, all verdicts executed, per-code replies |
| "ignored" | The hidden ignore list |
| Wednesday (on your PC) | Prices synced from your pasted Woolworths docs + specials posted + the list. ~14 seconds |

Nothing else exists. If a command isn't in this table, it was deleted
on purpose.

## The one rule that runs everything — row parity

Both sheet tabs always hold the SAME items:

- **Local shop has it, Woolies side blank** → it's on your Telegram
  list. You add the price + keyword in the sheet yourself, say `done`,
  it leaves the list.
- **Woolies doesn't stock it** → say `gone` → the row is marked GONE
  and leaves the list. That GONE is the truth: Woolies doesn't sell it.
- **Woolies has it, local doesn't** → never listed; the local line just
  stays blank.
- **You add a row at the bottom** → the next sync mirrors it to the
  other tab automatically.
- **You insert a row in the middle** → the sync alerts you to move it
  to the bottom first. (Bottom-appends only — that keeps the two tabs
  perfectly aligned.)

## Halal

The local butcheries are halal, so every butchery item is named
`halal …` — in both tabs. Woolworths' ordinary "beef mince" is a
different product from "halal beef mince" and never mixes with it.
Meat questions show both sides: the halal answer AND the plain
Woolworths twin.

## The sheets

- **Products_Master** — your Woolworths tab: name, size, price
  (or `GONE`), brand, keyword (the magic word that matches your pasted
  list — you maintain it), specials, sub-category, item code.
- **Local_Deals** — the local shops tab: one row per item, a Category
column, one column pair per shop (permanent + special price, stamped
with validity), comments, item code. Nazar has a permanent column
only — no specials. Filled automatically from the shops' Facebook
posts and the Dunya + Nazar websites. Both tabs are arranged in
category blocks (chicken → goat → lamb → beef → butchery misc →
unclassified → vegetables → fruits → unclassified → Non food);
Wednesday re-sorts them every run.
- **Archive** — the 100-ish rows that left the project in the v2
  migration. Nothing is ever hard-deleted.

## The weekly rhythm

1. During the week — **zero steps**: the 05:00/15:00 sweep finds every
   new FB post and AUTO-INGESTS it (vision + merge + parity), then
   posts ONE combined digest to the local-deals topic: items, prices,
   "min order …" pack terms, per-item validity, standout comparisons
   vs Woolworths, and any QUESTIONS (an undated board asks for its
   end date — reply with the date or `open`; a shop-less watch-folder
   drop asks which shop). Same-day re-posts: the newest price simply
   wins (final prices only). Outside the sweep windows, save a
   post's images/text into the PC watch-folder (`Desktop\shop-posts`)
   — the four shop subfolders are created for you (Dunya / Merjan /
   Fruitopia / Abu Salim); the watcher pushes them to the VPS and
   the digest arrives within minutes. The digest IS the action;
   questions are the only thing you ever answer.
2. Wednesday: paste your Woolworths list into `Woolworths.docx` and
   the specials into `Woolworths_Specials.docx`, run `wednesday`.
3. 14 seconds later: prices synced, specials in topic 206, the ONE
   list in topic 208. Anything you didn't match shows up with a code
   so you can fix it in one message.
4. Wednesdays + Saturdays at ~5 AM (Sydney): the VPS cron posts the
   whole day's Aldi Special Buys drop, theme-grouped, to topic 206 —
   no human step.

## Where things live

- **Google Sheet** — the memory (Products_Master + Local_Deals +
  Archive + history tabs).
- **Local PC** — runs Wednesday (reads the .docx files), the test
  suite (732 green), and the watch-folder daemon
  (`tools/inbox_watcher.py` — auto-starts at logon via the
  `tools/install_inbox_watcher.ps1` scheduled task; pushes
  `Desktop\shop-posts` drops to the VPS and triggers the ingest).
- **VPS** — runs the Telegram bot (sheet lookups, live search, batch),
  the twice-daily auto-ingesting sweep + the 03:17 backup canary, and
  the Wed/Sat 5 AM Aldi Special Buys cron.
- **`old md/`** — the entire v1 system, the quality campaign (22
  defects found & fixed), the v2 rebuild artifacts, and the
  2026-09-11/12 convergence-loop run documents (3 verification
  cycles, 2,000+ checks, clean exit). History only.

## ⚠️ Do not delete

The GCP project `grocerypriceapp-488202` (it IS the sheet access), the
two GitHub repos, the VPS, and the 03:17 backup cron. The backup cron
failing is your smoke alarm — check it the same day.

## Future (each a small, separate project)

1. **Amazon** in the live search (non-food only).
2. **Weekly catalogue digest** — Coles/Woolworths catalogues parsed
   into one Telegram specials message.
4. **Location-flavoured specials** — "oranges on special at Fruit
   World, 2 steps from Woolworths" (Google Places + shop scrapes + LLM
   phrasing, all on the VPS).
