# PROJECT-MAP — The Whole Grocery Tracker in Plain Language

> Last updated: 2026-08-30. This file is the plain-language map of every list,
> every command, and every scenario in the project.
> **Keep this file updated whenever any list, command, or flow changes.**

---

## 1. What this project is (30 seconds)

You do your grocery shopping at Woolworths, Coles (and a little Aldi). This
project keeps a **Google Sheet** of the products you buy, with each store's
price. During the week you ask **Claw** (your Telegram assistant) to check or
compare prices. Every **Wednesday** everything syncs up: your store website
lists are read, prices go into the sheet, and anything the system cannot
figure out lands on a short list for you to confirm in chat.

---

## 2. The three places things live

```
TELEGRAM (you) --> CLAW agent --> VPS (Docker) runs the CLI
                                         |
                                         v
LOCAL WINDOWS PC: Wednesday run, live browser window
                                         |
                                         v
GOOGLE SHEET "Products_Master": one row per product, prices per store
```

- **Telegram** — where you chat. Claw translates your words into CLI commands.
- **VPS** — the server that runs the CLI for day-to-day questions (compare, search, specials, map).
- **Local Windows PC** — the only place the Wednesday run and the browser login window happen.
- **Google Sheet** — the memory. Columns: A = product name, D/E/F = prices (Woolworths/Coles/Aldi), G = brand, H = updated, I/J/K = store keywords (how the system recognises a product on each store's list), M/N/O = specials/rewards, P = aliases (other names you might type).

---

## 3. The weekly cycle (the big picture)

```
        DURING THE WEEK (Telegram chat)                    WEDNESDAY (local PC)
  ┌──────────────────────────────────────┐      ┌─────────────────────────────────────┐
  │ "compare milk in woolworths+coles"   │      │ python grocery_price_cli.py         │
  │  -> sheet first, live fallback       │      │        wednesday --source live      │
  │ "search chocolate protein milk"      │      │  1. pull queues from VPS            │
  │  -> live websites, 3 per store       │      │  2. browser login (you, once)       │
  │ "add item 2"  -> ONE item saved:     │      │  3. FLUSH: queued items go ONTO     │
  │     new sheet row + queue entry [KAT]│ ───> │     the store website lists         │
  │ "remove KAT"  -> undo that one item  │      │  4. FETCH: read ALL list pages      │
  │ (do nothing -> NOTHING is saved)     │      │  5. match to sheet, write prices    │
  └──────────────────────────────────────┘      │  6. specials report                  │
                                                │  7. Telegram summary + lists         │
                                                └─────────────────────────────────────┘
```

Key rule (by design): **nothing is ever saved automatically.** A search or
compare only LOOKS. An item enters the system only when you explicitly say
"add item N".

---

## 4. All the lists (plain language)

| # | List (file) | Plain name | What puts things on it | What clears it |
|---|-------------|------------|------------------------|----------------|
| 1 | `data/unmatched.txt` (+ `unmapped_queue.json`) | **Unmatched** | Wednesday sync: items from your website lists the sheet does not recognise | You resolve them: reply with a number, `add`, `forget`, or `skip` in a map session |
| 2 | `data/wool_missing.txt` | **Wool missing** | Products known at Coles but with no Woolworths price/keyword yet | `map wool` sessions: `add`, `na`, exact name, or `skip` |
| 3 | `data/coles_missing.txt` | **Coles missing** | Products known at Woolworths but with no Coles price/keyword yet | `map coles` sessions (same replies) |
| 4 | `data/add_to_list.json` | **To-do list** (website-add reminder) | `map wool/coins --add` when a price is written | You add the item on the store website, then `add-to-list done --items "1,2"` |
| 5 | `data/searched_items.json` | **Searched list** (Wednesday queue) | ONLY an explicit "add item N" after a search/compare | Drained automatically by the Wednesday live window (items get added to your website lists); `searched-items remove/clear` also works |
| 6 | `data/ignored_items.txt` | **Ignored** (junk) | `map unmatched --forget` | Never (permanent exclusion) |

Notes:
- Every searched-list entry carries a **3-letter code** (letters only, no I/O,
  e.g. `KAT`). Codes exist ONLY on queued items — never on plain search or
  compare results. Removed codes are retired for 7 days so an old "remove X"
  message can never hit a new item.
- The to-do list (4) and the searched list (5) are slowly converging: once the
  live window is proven, everything can flow through the searched list and the
  manual to-do list can be retired (planned, not done yet).
- Supporting files (not lists you manage): `list_action_progress.json` (map
  session position), `live_snapshots/` (Wednesday website-list copies),
  `searched_item_code_tombstones.json` (retired codes),
  `live_api_capture.json` (one-time "training", see §7).

---

## 5. All the commands

Run locally as `python grocery_price_cli.py <command>` (on the VPS Claw runs
the same commands for you):

| Command | Plain meaning |
|---------|---------------|
| `compare --items "milk"` | Price battle between stores for things you name. Checks YOUR SHEET first; falls back to live websites. Only fair pairs count (same pack size within 20%). |
| `search --product "X"` | Live look at both store websites. Up to 3 results per store. Saves nothing. Ends with a reminder that you can reply "add item N". |
| `search --product "X" --add-item 2` | The explicit save: result 2 gets a new sheet row (store keyword left empty on purpose) + a searched-list entry with a 3-letter code. |
| `search --product "X" --expand` | Show up to 8 results per store instead of 3. Still saves nothing. |
| `specials` / `rewards` | What's on special / reward points, from the sheet + a live Woolworths scan. |
| `recipe --name --ingredients` | Compare a whole recipe's ingredients. |
| `update --product --store --price` | Write one price into the sheet. |
| `sync` | Match + batch-write prices from your lists to the sheet. |
| `specials-scan` | Site-wide scan for big savings. |
| `unmapped` | Show the unmatched queue (offline-safe). |
| `map unmatched / wool / coles / status` | The one-item-at-a-time resolve sessions. In-session replies: a number (pick), `add`, `na` (not stocked at this store — writes NA, never asked again), exact product name (save as keyword), `skip`, `stop`, `done`. |
| `map wool --na` | Mark a product permanently not-available at Woolworths (same for coles). |
| `add-to-list show / done --items "1,2"` | See / clear the manual website-add to-do list. |
| `searched-items show / remove --items "KAT,RUM" / clear` | See / remove / empty the searched list (Wednesday queue). |
| `live-refresh [--flush-only] [--fetch-only] [--recapture]` | LOCAL ONLY. The browser window: login, push queued items onto the store website lists, read all list pages into snapshots. `--recapture` redoes the one-time "training". |
| `wednesday [--source docx|live]` | The full Wednesday pipeline (see §6). Default `docx` = the old paste-from-Word flow. `live` = the new website-list flow. |
| `backfill-keywords` | Fill the alias column (P) from existing data. |

---

## 6. The scenarios

### A. Midweek chat (Telegram)
1. You ask for a comparison -> Claw runs `compare` -> you get the price battle.
2. You ask for a search -> Claw runs `search` -> you get up to 3 options per
   store + the reminder line "Reply 'add item N' to queue a result for
   Wednesday."
3. You reply "add item 2" -> ONE item is saved (sheet row + queue entry with
   code). You see: "Queued for Wednesday: '...' (Store) [KAT]".
4. You reply "remove KAT" any time (even many chats later) -> that item is
   dropped. Multiple: "remove KAT,RUM".
5. You never reply -> nothing was ever saved. Searches are look-only.

### B. Wednesday, old way (docx)
You paste your store lists into `Woolworths.docx` / `Coles.docx` /
`Woolworths_Specials.docx`, then run `python grocery_price_cli.py wednesday`.
It parses the Word files, updates the sheet, posts the summary + specials to
Telegram (DM + grocery-sync-sheet topic).

### C. Wednesday, new way (live) — every week, not just the first
`python grocery_price_cli.py wednesday --source live`
1. Pulls the queue files from the VPS.
2. Opens a real Chrome window; YOU log into Woolworths and Coles once
   (2FA included). The login is remembered until it expires.
3. Flush: everything in the to-do + searched lists is added to your
   "Price Compare" lists ON THE STORE WEBSITES (needs the one-time training, §7).
4. Fetch: reads ALL pages of both lists (30-page safety cap) into snapshots.
5. Gate: if the snapshots came back incomplete it STOPS before touching the sheet.
6. Sync: prices written to the sheet; unknown items -> Unmatched; one-store
   items -> Wool/Coles missing.
7. Specials report + summary posted to Telegram.

### D. Resolve sessions (map)
Claw shows one item at a time. You reply with a number (pick a candidate),
`add` (take the live-search result), an exact product name (save as that
store's keyword), `na` (never stocked there — stop asking), `forget` (junk —
never ask again), or `skip`. Each reply advances to the next item
automatically. `stop` pauses; the session resumes later.

### E. Specials today
`specials` reads the sheet's specials columns + scans your Woolworths list
live. Items the sheet knows are shown with plain prices (Woolworths display
prices always carry the 5% team discount; the sheet stores raw prices).

---

## 7. The one-time "training" (discovery capture)

Before the system can push items onto the store website lists (step C.3), it
must ONCE learn, per store, the exact website API call for "add to list" and
how list pages are numbered. That knowledge is saved in
`data/live_api_capture.json`. The code refuses to guess without it. It is
captured automatically during the first live-window run, and
`live-refresh --recapture` redoes it if a store changes its website.
Status today: **never run yet** (the file does not exist), so the flush step
cannot work until the first live run happens.

---

## 8. Planned but NOT built yet (do not assume these exist)

1. **Compare reminder line** — compare output does not yet end with the
   "Reply 'add item N'..." reminder (search already has it).
2. **Umbrella command** — one main grocery command with subcommands,
   including a `lists` subcommand that shows all lists (unmatched, wool
   missing, coles missing, to-do, searched) in one view.
3. **Telegram topic split** — specials -> a "specials-wool" topic; the three
   resolve lists -> a second topic. (Today everything goes to DM +
   grocery-sync-sheet.)
4. **Specials columns M/N populated** — Wednesday writing
   no / discount / multi-buy per store into the sheet's specials columns.
   Verified formats: Woolworths docx uses "Save $X" (discount) and
   "2 for $4.50" (multi-buy); Coles docx uses "Save $X"/"Was $X" (discount)
   and "Any 2 | $9" (multi-buy). The Coles "Any N" pattern is new and not
   parsed yet.
5. **Fallback-model relay fix** — on hold; the model will be replaced first.

All of the above (1, 3, 4) are user-approved decisions recorded in
`pre-arch.md` §C.9 (decisions 23-25, 2026-08-30) — approved but not yet built.

---

## 9. Maintenance

If any list, command, flag, or flow changes: update this file in the same
change. The README's "Project Conventions" section points here.
