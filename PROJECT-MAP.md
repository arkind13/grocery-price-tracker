# PROJECT-MAP — The Grocery Tracker v2 in Plain Language

*Updated 2026-09-10 (v2 rebuild closed, Round 5). Plain language on
purpose: if code reality and this map ever disagree, fix this map in
the same change.*

## 0. Start here — the cheat sheet

### The ONE list and what it is FOR

There is exactly ONE user-facing list: **the missing list** (`list`).
It answers a single question — *"what should I buy locally this week
because Woolworths doesn't have it (tracked)?"*

An item is ON the list when:
- its local side has at least one shop price, AND
- the Woolworths price cell (D) has no real price, AND
- the search keyword (G) is empty.

An item is NOT on the list when: D has a price, or G has a keyword
(tracked — the Wednesday run refreshes it), the row says `GONE`, the
local side is blank, or the code was `ignore`d (hidden; `ignored`
reveals them). `N/A <date>` WITH a keyword = tracked-but-unavailable
this week — not missing.

### The 8 commands — what they do, in one table

| You say / want | Command | What happens (budget) |
|----------------|---------|------------------------|
| "how much is X" / any price question | `price --item "X"` | Sheet-only answer (≤10s): 🟢 Woolworths price + every local shop price + 🏆 best local. Never searches the web, never writes. |
| "the list" / "what am I missing" | `list` | The ONE missing list, fresh from the sheet (≤5s), `[CODE]` per entry. |
| "live search X" (must say **live**) | `live --item "X"` | Real web search of Woolworths + Coles (≤20s), ≤3 prices each, prices only. Never adds or writes anything. |
| "ABC done; DEF gone; GHI rename …" | `batch --verdicts "…"` | Every verdict in ONE call (≤10s), one reply per code. |
| "what did I ignore" | `ignored` | Reveals the hidden ignore list. |
| "what's on special" | `specials` | Active specials from the sheet + the latest Wednesday report. |
| (local shops machinery) | `local-deals …` | FB-post detector, inbox ingest, Dunya site sync, expire sweep, manual entries. |
| (weekly Woolworths run) | `wednesday` | The docx → sheet → Telegram run (≤30s). |

**Nothing else exists.** The old compare / optimize / search / sync /
map / todo / shop / prefer / recipe / rewards / update / lists /
missed-pricing / add-to-list / no-price / live-refresh commands are
RETIRED — asking for them gets an honest "that command is gone".

### How a product gets onto (and off) the ONE list

- **ON:** a local shop prices it (FB post ingest or manual entry) and
  Woolworths has neither a price nor a keyword for the row.
- **OFF:** the Wednesday run writes a Woolworths price (col D) or you
  fill D/G by hand in the Sheet; or the item is `gone`/`remove`d via
  batch; or `ignore` hides it.

## 1. What this project is (30 seconds)

One Google Sheet tracks the true price of groceries: Woolworths in
`Products_Master`, four local Mt Druitt shops (Dunya Butchery, Merjan
Brothers, Fruitopia, Abu Salim) in `Local_Deals`. A tiny 8-verb CLI
answers price questions from the sheet, keeps ONE missing list, runs
the weekly Woolworths docx update, and talks to Telegram. The sheet is
the source of truth — the CLI reads it and writes it only through the
defined verbs.

## 2. The three places things live

1. **The Google Sheet** — the truth. Two tabs that matter:
   `Products_Master` (13 cols: A name · D Woolworths price · G
   keyword · H specials · L Item_Code …) and `Local_Deals` (11 cols:
   A name · permanent + special price column per shop · K Item_Code).
2. **This folder (the PC)** — the code (`core/`, `extractors/`,
   `tests/`, `tools/`), the two Woolworths docx pastes, and the
   runtime data (`data/local_deals_inbox/`, scan state, ignore list).
   Runs the CLI locally and is mirrored to the VPS.
3. **The VPS (`myvps`, docker `openclaw-core`)** — where the Telegram
   bot lives. The Claw agent runs the same CLI files there
   (bind-mounted). Two crons: the 03:17 sheet backup (the health
   canary) and the hourly local-deals daily-scan.

## 3. Parity — the two tabs always agree

Every master row has a `Local_Deals` twin row under the SAME permanent
3-letter code. The audit (`tools/migrate_v2.py audit`) says one of
three things:

1. **ALIGNED** — silence, all good.
2. **Bottom-append miss** — you added a row at the BOTTOM of one tab
   only; the run auto-mirrors it to the other tab (blank fields, code
   stamped on both sides). Nothing for you to do.
3. **Middle-insert** — a row appeared BETWEEN existing rows. The run
   ABORTS loudly, writes nothing, and tells you: move that row to the
   BOTTOM of its tab in the Sheet, then re-run. (Never insert in the
   middle — new rows always go at the bottom.)

## 4. The verdict grammar (batch)

`batch --verdicts "ABC done; DEF gone; GHI rename halal lamb
shoulder; JKL remove; MNO ignore"` — one reply per code:

- **done** — VERIFY-ONLY. Confirms the row is complete, or names
  exactly what is still blank (e.g. "[AUG] ✗ not done — still blank:
  Woolworths price (col D) and search keyword (col G)"). Writes
  nothing.
- **gone** — the item is gone from Woolworths: the literal `GONE`
  goes into col D, the row and its local prices stay.
- **rename X** — new name on BOTH tabs; code and prices untouched.
- **remove** — permanent but archived: both rows are copied to
  `data/deleted_rows.json`, then deleted from both tabs.
- **ignore** — hides the item from the ONE list (reveal: `ignored`).

An unknown code gets `[CODE] ✗ unknown code`; the other verdicts in
the same call still run. Q11: halal and non-halal rows stay SEPARATE
forever — no code path pairs, merges, or renames one into the other.

## 5. Meat, halal, and the non-halal twin line

- Meat questions ("beef mince", "chicken breast", the halal name, even
  the exact plain-row name) resolve through **halal-named rows only**,
  and the four local shops are always the HALAL side of any
  comparison.
- Every meat answer ALSO carries the plain (non-halal) Woolworths row
  as a display-only line:
  `also at Woolworths (non-halal): $13.54 — Woolworths Beef Mince 500g`
  — priced, GONE, or "unavailable"; shown immediately even when the
  halal row has no price yet; NEVER a local shop; writes nothing.
  Asking "non halal X" needs no special command — the twin line IS
  the non-halal side.
- Meat terms are detected by protein+cut words ("chicken salt" and
  "beef stock" are never meat).

## 6. The scenarios

### A. Midweek chat (Telegram)

You ask "how much is halal beef mince" → the agent runs
`price --item "halal beef mince"` → one styled answer: the item name,
🟢 Woolworths (if priced, display-discounted), 🔪 each local shop's
price (special first), 🏆 best local, the non-halal twin line, the
`[CODE]`, and the date legend. A miss answers from the sheet only —
the web is touched ONLY when you say "live".

### B. Wednesday — the weekly Woolworths run

1. You paste the week's `Woolworths.docx` + `Woolworths_Specials.docx`
   into the tracker folder (on the PC).
2. `wednesday` (≤30s) parses them, matches each line to the sheet's
   keyword column (G), and writes the price column (D): found → price;
   absent → `N/A <date>`; GONE survives; multi-buy deal rates go into
   D with the terms in H; when a deal ends H is cleared and D reverts.
3. The parity step runs (ALIGNED / auto-mirror / loud abort — §3).
4. Exactly TWO Telegram messages: specials → topic 206, the ONE
   missing list → topic 208 (long lists arrive as several chunks, all
   in 208).
`--dry-run` does the whole plan and writes nothing.

### C. Local deals (the four shops)

- The VPS detector checks the shops' Facebook boards twice a day
  (05:00 + 15:00 Sydney) and announces new posts with an inbox code
  (`MER0709260507`-style).
- You save the post (text preferred, or the photo) into
  `data/local_deals_inbox/<CODE>/` and run
  `local-deals --ingest CODE`. Text parses directly; photos go through
  the vision chain. Butchery items land `halal`-prefixed; a brand-new
  item is auto-created as a blank coded row at the BOTTOM of both
  tabs; re-ingesting the same post changes nothing (idempotent).
- Manual: `--set-permanent fruitopia carrots 6.50/kg`,
  `--set-special merjan 'beef mince' 8.99/kg --till "12 September"`.
- Expired special stamps are swept automatically; permanent cells
  never expire; the Dunya column can be synced straight from the shop
  website (`--dunya-site`).

### D. Specials today

`specials` reads the sheet's specials column (H) and deal-rate prices
(D) — multi-buy items show the mandatory "must purchase 2+" note —
plus the latest Wednesday report when fresh.

## 7. Protection rails (so the sheet stays true)

- The 03:17 VPS backup cron saves every tab to JSON and doubles as the
  health canary — if it fails one morning, the Google Cloud project
  that owns sheet access has probably died again: treat it as a page.
- Never touch: the GCP project, the GitHub repos, the VPS, `.env` /
  any secret. Sheet writes happen ONLY through the verbs (and your own
  manual edits — always at the BOTTOM).
- Every round of change ends with the system working and the three
  places (PC, GitHub, VPS) in sync.

## 8. Planned but NOT built yet (do not assume these exist)

A future session may add ALDI first, then AMAZON (non-food only) as
extra `live` search providers — see the design note at the end of
`README.md` and spec §15. Nothing else is planned; there is no hidden
queue, no pending list, no dormant feature.
