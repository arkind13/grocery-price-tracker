# PROJECT-MAP — The Whole Grocery Tracker in Plain Language

> Last updated: 2026-09-02. This file is the plain-language map of every list,
> every command, and every scenario in the project.
> **Keep this file updated whenever any list, command, or flow changes.**

---

## 0. Start here — the cheat sheet

### The 7 lists and what each is FOR

| List | What it is telling you |
|------|------------------------|
| **Unmatched** | "This line was on your store list, but I don't know which sheet row it is." A to-do list for you — but it heals itself: anything the system can fix (exact name match, keyword already saved) leaves on its own each Wednesday. |
| **Wool missing / Coles missing** | "You track this product, but it has no keyword for that store yet, so that store can never price it." Fix = one map session reply. |
| **To-do (add-to-list)** | "This product was just mapped — now add it to that store's website list yourself." You clear it after adding it on the website. |
| **Searched** | "These are waiting to go ONTO your store website lists." Cleared automatically the moment they appear on a Wednesday list. |
| **Ignored** | Junk you said "forget" to. Never shown again. |
| **No-price report** | "Neither store has a real price for this row for N weeks." Your cue to delete dead products from the sheet. |

> **Sub-categories (2026-09-04, reviews list 2026-09-05):** rows whose
> sub-category is `needs review` — the classifier was NOT confident,
> nothing was guessed — surface on the **Sub-category reviews** list
> (list 7 in `lists` and in the weekly Telegram post). The agent asks
> the user for the right label before writing one; the classifier is
> word-boundary safe (V Sugarfree is not sugar, V Watermelon is not
> water, eggplant is not eggs — such names go to review, never a
> guess).

> **Multi-buy prices (2026-09-05):** a multi-buy item's price cell
> holds the per-unit deal rate ("2 for $7.00" on $4.00 → 3.50;
> "Any 2 | $X" deals count too — same-range bundles). To-do/list views
> mark those items `(m)` with the legend `(m) - multi buy discount`.

> **Not a 7th list:** "Pending links" (`unmapped_queue.json`, shown by
> the `unmapped` command) is the STORAGE LEDGER BEHIND the Unmatched
> list — the same items at their storage stage, plus ignored junk that
> never displays again. It is NOT a separate to-do and NOT the
> missing-price lists (those are Wool/Coles missing above).

### How a product gets onto a list (the rules)

- **Wednesday reads your store lists.** A line that matches a sheet keyword → price updated, no list. A line with no matching keyword → **Unmatched**. A sheet row whose keyword exists but the line is missing → price cell gets `N/A <date>` (and the no-price report counts its weeks).
- **You say "add item 2" in chat** → genuinely new product: **one sheet row + the Searched list**. Same product already on the sheet (wording/pack differences ignored)? → price updated on that row instead, **nothing queued**.
- **A map session writes a price** (`add`) → the product also goes on the **To-do list**.
- **Paste junk** ("Add to cart", "Ends 7 Jul.") → filtered before any list. Junk you confirm with `forget` → **Ignored** forever.

### The commands — what they do, in one table

| Command | Its job | Writes to the sheet? | What happens next |
|---------|---------|----------------------|-------------------|
| `compare` | Price battle for things you name (sheet first, live websites as backup) | Never | Nothing — look only |
| `optimize` | Weekly-basket planner: one Woolworths trip vs a split Woolworths/Coles plan (5+ items only — smaller lists use `compare`) | Never | Nothing — look only |
| `search` | Live look at both store websites (3 results per store) | Never | Nothing — look only |
| `search --add-item N` | Save result N | Yes — price, and a new row ONLY if the product is genuinely new (one-line rule) | Goes on the **Searched** list → you add it on the store website → clears automatically next Wednesday |
| `update` | Write one price by hand | Yes — one price cell | Nothing further |
| `wednesday` (or `sync`) | The weekly engine: shows your queue first and waits, then reads your lists and overwrites EVERY price (found → price; missing → `N/A <date>`; unpriced → `unavailable <date>`) | Yes — all prices | Unmatched/missing lists rebuilt + self-healed, no-price report posted, queues pushed to Telegram's side |
| `map unmatched/wool/coles` | Fixes the resolve lists, one item per reply | Yes — a **pick** saves keyword + alias + price in one go; an **add** creates a new row | Picked items never return; added ones go on the To-do list |
| `searched-items` / `add-to-list` | See or clear those two queues by hand | No | — |
| `live-refresh` | The browser window: pushes queued items onto the store websites, reads the lists | No (indirect) | Pushed items appear on next Wednesday's list |
| `backfill-keywords` / `backfill-sizes` | Repairs: fills empty alias / unit cells | Yes — fills blanks only | Better matching + units shown everywhere |
| `specials` / `rewards` / `recipe` / `specials-scan` | Questions and reports | Never | Nothing — look only |

*(Full details for all of the above: §4 lists, §5 commands, §6 scenarios.)*

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
- **Google Sheet** — the memory. Columns: A = product name, C = unit/size (e.g. `1L`, `250g`, `5 pack` — every product mention shows this, or says `unit unavailable` when unknown), D/E/F = prices (Woolworths/Coles/Aldi). A price cell can also hold a marker: `N/A 2026-09-02` (not in that store's list) or `unavailable 2026-09-02` (listed but no usable price) — the date is how the no-price list counts weeks. G = brand, H = updated, I/J/K = store keywords (how the system recognises a product on each store's list), M/N/O = specials/rewards, P = aliases (other names you might type), Q = Sub_Category (granular cluster like `eggs`, `bread`; `needs review` when unsure), R = Item_Code (permanent 3-letter row ID), S = Preferred (the "P" flag — at most one per sub-category).

---

## 3. The weekly cycle (the big picture)

```
        DURING THE WEEK (Telegram chat)                    WEDNESDAY (local PC)
  ┌──────────────────────────────┐      ┌──────────────────────────────────────────┐
  │ "compare milk in woolworths+coles"   │      │ python grocery_price_cli.py         │
  │  -> sheet first, live fallback       │      │        wednesday                    │
  │ "search chocolate protein milk"      │      │  1. pull + merge queues (VPS/local) │
  │  -> live websites, 3 per store       │      │  2. PAUSE: you add the queued items │
  │ "add item 2"  -> ONE item saved:     │      │     on the store websites, paste    │
  │     new row if new, else price       │ ───> │     the updated lists into the      │
  │     on the existing line + queue     │      │     .docx files, type done          │
  │     entry [KAT] (one-line rule)      │      │  3. auto-link exact names, match,   │
  │ "remove KAT"  -> undo that one item  │      │     OVERWRITE all prices            │
  │ (do nothing -> NOTHING is saved)     │      │  4. specials report                 │
  └──────────────────────────────────────┘      │  5. Telegram summary + 7 lists      │
                                                └──────────────────────────────────────┘
```

Key rule (by design): **nothing is ever saved automatically.** A search or
compare only LOOKS. An item enters the system only when you explicitly say
"add item N".

---

## 4. All the lists (plain language)

| # | List (file) | Plain name | What puts things on it | What clears it |
|---|-------------|------------|------------------------|----------------|
| 1 | `data/unmatched.txt` (+ `unmapped_queue.json` = its storage ledger, "Pending Links") | **Unmatched** (a persistent debt list) | Wednesday sync: list items whose store keyword doesn't match any sheet row. Entries ACCUMULATE week after week (each week's miss bumps a counter) and carry the last-seen price. Paste junk (button labels like "Add to cart", "Ends 7 Jul.") is filtered at parse time | You resolve them (see §6D: one reply per item); Wednesday also auto-heals: exact sheet-name items get their keyword linked automatically (Step 1c), entries whose keyword now exists leave the debt automatically, and the resolved debt is pushed to the VPS |
| 2 | `data/wool_missing.txt` | **Wool missing** | Products known at Coles but with no Woolworths price/keyword yet | `map wool` sessions: `add`, `na`, exact name, or `skip` |
| 3 | `data/coles_missing.txt` | **Coles missing** | Products known at Woolworths but with no Coles price/keyword yet | `map coles` sessions (same replies) |
| 4 | `data/add_to_list.json` | **To-do list** (website-add reminder) | `map wool/coles --add` when a price is written (the entry remembers the EXACT store name + a 3-letter code) | You add the item on the store website, then `add-to-list done` (by number or code) — **done also saves the exact store name as the row's keyword**, so next Wednesday it matches + price-syncs straight away |
| 5 | `data/searched_items.json` | **Searched list** (Wednesday queue) | ONLY an explicit "add item N" after a search/compare — and only when the product is genuinely NEW (the one-line rule updates existing rows instead, without queueing) | Wednesday Step 1b clears each item the moment it appears on its store's list; the live window flush also adds + clears; `searched-items remove/clear` works too |
| 6 | `data/ignored_items.txt` | **Ignored** (junk) | `map unmatched --forget` | Never (permanent exclusion; pulled from the VPS each Wednesday so Telegram forgets count everywhere) |
| 7 | *(generated report, no file)* | **No-price list** | The Wednesday run itself: sheet rows where NEITHER store price is a real number above zero — `N/A <date>`, `unavailable <date>`, `$0`, blank, or any text — grouped by category with weeks counts, oldest first | You: delete genuinely dead products from the sheet (ask Claw to show you them any time) |

**Where you see them:** every Wednesday, ALL seven lists are posted to the
**weekly-lists** Telegram topic with the sync summary — the three resolve
lists (1–3), the no-price list (7), the to-do list (4), searched list (5),
and ignored list (6). Empty lists post as "none" (proof the queues were
drained). One-store drops (e.g. Coles `N/A` while Woolworths still prices
the item) are NOT posted anywhere — they live in the sheet; ask Claw to
list them any time.

Notes:
- Every searched-list entry carries a **3-letter code** (letters only, no I/O,
  e.g. `KAT`). Codes exist ONLY on queued items — never on plain search or
  compare results. Removed codes are retired for 7 days so an old "remove X"
  message can never hit a new item.
- The to-do list (4) and the searched list (5) were planned to converge
  via the live window (auto-add on the store websites). With live mode
  retired (2026-09-02), the to-do list stays: the Wednesday docx pause
  is the manual flush, and `add-to-list done` (which also saves the
  store keyword) is the drain.
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
| `optimize --items "milk, eggs, …"` | The weekly-shop planner (needs 5+ items). Prices from YOUR SHEET first, then classifies the rest: items already queued on the searched/to-do lists = no action needed (Wednesday handles them); close substitutes on the sheet are used read-only (labelled); the remaining gaps are listed for your confirmation (A = Coles missing, B = Woolworths missing, C = no pricing — each with a 3-letter code) before any live search. Confirming writes only PRICES into existing rows — and if a side still carries a stale keyword (price was N/A), the wrong keyword is CLEARED and the correct product goes on the to-do list so you verify the website list; sides with no keyword stay on the wool/coles missing lists until resolved via map (that writes the keyword); not-on-sheet items are compared only unless you add `+add` (then new row + searched-list entry). Then it says either "one Woolworths trip" or exactly which items at which store as numbered buy lists with 💵 subtotals and the item-vs-item savings (every per-item gap adds — a $10 win can't be cancelled by a $10 loss). Under $3 of movement → one trip; ties go to Woolworths. |
| `search --product "X"` | Live look at both store websites. Up to 3 results per store. Saves nothing. Ends with a reminder that you can reply "add item N". |
| `search --product "X" --add-item 2` | The explicit save: result 2 becomes a sheet row (store keyword left empty on purpose). **One-line rule:** if the SAME product is already on the sheet (word order / store-brand wording / pack wording ignored — `5 pack` and `70g` of the same item are ONE product), the price is updated on that existing row instead and nothing is queued. Only a same-unit different-size (200g vs 400g, beyond 20%) keeps lines apart; 33g vs 35g match. Add `--allow-duplicate` when you really want a second line. |
| `search --product "X" --expand` | Show up to 8 results per store instead of 3. Still saves nothing. |
| `specials` / `rewards` | What's on special / reward points, from the sheet + a live Woolworths scan. |
| `recipe --name --ingredients` | Compare a whole recipe's ingredients. |
| `update --product --store --price` | Write one price into the sheet. |
| `sync` | Match + batch-write prices from your lists to the sheet. |
| `specials-scan` | Site-wide scan for big savings. |
| `unmapped` | Show the unmatched queue (offline-safe). |
| `map unmatched / wool / coles / status` | The one-item-at-a-time resolve sessions. In-session replies: a number (pick — see §6D, it does the FULL job), `add` (link an exact hit, or add a genuinely new product), `na` (not stocked at this store — writes NA, never asked again), exact product name (save as keyword), `skip`, `stop`, `done`. Aldi-tagged junk items say so and offer pick/forget/skip — they cannot be live-searched. |
| `map wool --na` | Mark a product permanently not-available at Woolworths (same for coles). |
| `add-to-list show / done --items "1,KAT"` | See / clear the manual website-add to-do list (entries carry the exact store names + 3-letter codes). **`done` = "I added it on the website"** — it clears the reminder AND saves the exact store name as the row's keyword, so the next Wednesday sync matches the item immediately. `done` accepts numbers and codes mixed. |
| `searched-items show / remove --items "KAT,RUM" / clear` | See / remove / empty the searched list (Wednesday queue). Items also clear by themselves the moment they show up on your store lists (Wednesday Step 1b). |
| `live-refresh [--flush-only] [--fetch-only] [--recapture]` | **RETIRED (2026-09-02), shelved not deleted.** Was the browser window: login, push queued items onto the store website lists, read all list pages into snapshots. Its job is now done by hand during the Wednesday docx pause. Code kept for a future breakthrough — see `lostbattle.md` before touching it. |
| `wednesday [--source docx] [--no-prompt]` | The full Wednesday pipeline (see §6). **Docx is the ONLY mode now** — it shows the queue first, waits while you add those items on the store websites and paste the updated lists, then syncs on `done`. ~~Live mode~~ RETIRED 2026-09-02 (the browser-window war was lost — see `lostbattle.md`). |
| `backfill-keywords` | Fill the alias column (P) from existing data. |
| `backfill-sizes` | Fill empty unit cells (C) by parsing sizes out of product names. Never overwrites a filled cell; unparseable cells stay blank and show "unit unavailable" in answers. |
| `shop --items "eggs, apples"` | Shopping-list compare (see §6F): auto-picks your preferred row per sub-category; asks one question when it can't. |
| `prefer --code ABC` / `prefer --pick N` | Make that row your preferred (P) item for its sub-category, then finish any pending shop run. |
| `subcategories` | List the sub-category labels and how many sheet rows each has. |
| `backfill-subcategories` | One-time fill of empty sub-category cells (Q) using the classifier; unsure rows get the literal "needs review" — never a guess, never overwrites. |
| `backfill-codes` | One-time fill of empty item-code cells (R) with unique permanent 3-letter codes. |

**Unit rule (everywhere):** any time a product is mentioned — search,
compare, recipe, specials, the queues, the Wednesday lists — its unit
(column C) is shown next to it (` · 1L`). If the unit is unknown, you get
a clear note (` · ⚠️ unit unavailable`) instead of silence. Every path that
adds a product (search `add item N`, map unmatched/wool/coles, to-do list,
searched list) must fill column C first; it asks you for the unit if it
can't find one, and writes `unit unavailable` if you reply "unknown".

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

### B. Wednesday, docx way (default)
1. Run `python grocery_price_cli.py wednesday`.
2. **It shows the searched + to-do queues FIRST and waits.** You add
   those items to your store website lists, paste the updated lists into
   `Woolworths.docx` / `Coles.docx` (specials into
   `Woolworths_Specials.docx`), then type `done`.
3. It parses the lists and **auto-links exact matches** (Step 1c): any
   list item whose name exactly matches a sheet row with an empty store
   keyword gets the keyword set right there — matched + priced in the
   same run, never becoming manual work.
4. It syncs: every price is OVERWRITTEN — found items get today's price;
   items missing from a list get `N/A <today>` in that store's cell;
   listed-but-unpriced items get `unavailable <today>` (old prices never
   linger).
5. Queued items that now appear on the pasted lists clear automatically;
   the debt list is healed the same way (entries whose keyword now
   exists leave automatically, and every remaining entry gets this
   week's price attached so map picks can write prices immediately).
6. Telegram gets the summary + all seven lists (incl. the no-price list
   with weeks counts) in the weekly-lists topic, plus the specials
   report in the specials-wool topic. The healed lists + debt queue are
   pushed to the VPS so Telegram sessions see exactly the same state.

### C. Wednesday, live way — RETIRED (2026-09-02)
> The browser-window flow (`wednesday --source live`) is **retired**:
> the fight to automate store logins and the "add to list" click was
> lost after ~16 hours (Akamai bot manager + Chrome 136 profile
> security). The CLI refuses `--source live` with a pointer to
> `lostbattle.md`. Everything this flow did is now covered by the
> docx way (§B): the pause is your flush (you add the queued items on
> the store websites), the pasted lists are your fetch. The code and
> tests are shelved, not deleted — the revival conditions are listed
> in `lostbattle.md`.

### D. Resolve sessions (map) — one reply per item
Claw shows one item at a time with the system's best information:

- **Recommendations ("Which did you mean? 1) … 2) …")** = sheet rows
  whose names look similar (ranked by matching words; the size is shown
  so you can judge). A recommendation means the product is PROBABLY
  already tracked — the store list just words it differently.
- **Reply a number (pick)** — the COMPLETE fix, one reply: saves the
  long name as a chat alias, sets the store keyword on that row (so
  Wednesday recognises it forever), writes the item's price immediately
  (when the debt entry carries one — items not in any current list get
  their price at the next Wednesday sync), and clears the debt entry.
- **"Already on the sheet" with a row number** — the exact case: reply
  `add` and it links the store keyword in one step.
- **`add`** — for genuinely NEW products only: creates a row with
  today's live price (and queues it for your store website list).
  The one-line rule keeps it to one line per product.
- **`na`** (wool/coles lists) — never stocked there, stop asking.
- **`forget`** — junk (paste garbage), never asked again.
- **`skip`** / **`stop`** — move on / pause (resumes later).

Aldi-tagged items cannot be live-searched (sheet-only store) — the
session says so and offers pick/forget/skip instead of garbage results.

### E. Specials today
`specials` reads the sheet's specials columns + scans your Woolworths list
live. Items the sheet knows are shown with plain prices (Woolworths display
prices always carry the 5% team discount; the sheet stores raw prices).

### Local deals (Friday + twice-daily detector)

`local-deals` reads the Facebook price boards of four local shops
(Dunya Butchery, Merjan Brothers, Fruitopia, Abu Salim), parses them
with a vision model, rebuilds the `Local_Deals` tab (wiped weekly —
B7), compares in-domain items against Woolworths/Coles sheet prices
(>20% = standout), and posts TWO Telegram messages: standouts, then
every shop's full board. Butcheries only compare against raw meat;
fruit shops only against produce — everything else is shown but never
compared. The Friday cron (05:00-05:59 Sydney, once per Friday) uses
`--friday-gate`; any-day manual runs are fine. Failures degrade to
"⚠️ No prices found this week: …" lines — never silence.

Twice-daily detector (2026-09-06; cookies for Facebook are banned):
`--daily-scan` (cron tick hourly; the scan fires only 05:00-05:59 and
15:00-15:59 Sydney, once per window) renders each public page logged
out and notifies every post since the previous alert (up to 3 per
store) in the local-deals topic — timestamped inbox codes (user rule
2026-09-07): 3-letter shop FRU/MER/DUN/ABS + ddmmyy + HHMM of the
ALERT (e.g. FRU0709260507; `_2`/`_3` on same-minute collisions;
legacy FRUT/MERJ/DUNY/ABSA still resolve), posted time and validity
date included. `--ingest CODE` processes the
file dropped into `data/local_deals_inbox/<CODE>/` (image → vision,
text → `extractors/deal_text.py` parser) and MERGES the results into
the tab for that store only (`merge_store_tab` — other stores are
never wiped; newest post's price wins; row 2 "Prices valid until" is
stamped per shop, Dunya site column n/a) and the summary includes
the >20% standout check vs Products_Master. PC-saved files are
ingested by the LOCAL agent (the Windows inbox path is in the
alert); the VPS inbox only receives topic-forwarded files.
`--ignore CODE` retires a post. Dunya's own website
(dunyabutchery.com.au WooCommerce API) syncs the Dunya column via
`--dunya-site` and reports on-offer items plus price changes since
the previous sync.

### Halal resolution chain

Raw meat/chicken queries are halal-by-default. Tier 1: the sheet's
halal-visible rows (non-marked meat rows are invisible; prepared
foods like "chicken salt" never count as meat). Tier 2: a live halal
search where each top candidate is verified by an LLM web check
(>= 0.8 confidence auto-adds the row with a `halal` Col P marker +
Preferred; <= 20 checks/run, 90-day cache). Tier 3: the Local_Deals
butchery tab ("🔪 Local butcher (halal): …" — domain-only, prepared
items never answer). Nothing found -> a clean "not available this
week". Negatives live ONLY in `data/halal_status.json`, never on the
sheet. `shop`/`optimize` run a halal gate: non-marked auto-scope rows
are excluded ("excluded (non-halal — database only)"), unverified
ones fail safe. `backfill-halal-check` sweeps unknown rows through
the same LLM check.

### F. Shopping list (shop) — the preference flow

1. You send a list ("eggs, apples, bread"). The agent normalises each
   item to a sub-category (or a specific product) and calls
   `shop --items "…"`.
2. Each sub-category with a Preferred (P) row is compared
   automatically using that row.
3. No P yet? The CLI asks ONE question (the numbered prompt with
   full names + codes). Reply with a code or number → `prefer` sets
   P and finishes the comparison.
4. Not tracked at all? Offer a keyword → normal `search --add-item`
   flow; the new row arrives with Q/R/S filled and S empty — the
   next `shop` asks the one question (nothing is ever auto-preferred).
5. Asked for a specific variant that is NOT your preferred? You get
   the comparison plus the switch/keep warning. "keep" writes
   nothing.
Item-Code (Col R) is a DIFFERENT namespace from queue codes: `prefer
ABC` vs `todo done ABC` never collide.

---

## 7. The one-time "training" (discovery capture) — SHELVED with live mode

The capture file (`data/live_api_capture.json`) holds the exact website
API call for "add to list" per store, learned during the live-window
experiments. With live mode retired (2026-09-02) nothing reads it —
it stays as a proven artifact for any future revival (the API call
itself was verified correct; delivery was the lost battle). See
`lostbattle.md`.

---

## 8. Planned but NOT built yet (do not assume these exist)

1. **Umbrella command** — one main grocery command with subcommands,
   including a `lists` subcommand that shows all lists in one view.
2. **Fallback-model relay fix** — on hold; the model will be replaced first.

(Built since the 2026-08-30 list: compare add-reminder, Telegram topic
split, specials columns M/N, queue sync, the Wednesday pause + auto-clear,
the one-line rule, sync overwrite semantics, the no-price list, Wednesday
exact-name auto-linking, debt auto-heal + price enrichment, one-reply map
picks, the aldi guard, and the smart-basket optimizer (optimize) — see
`test.md` for every round.)

---

## 9. Maintenance

If any list, command, flag, or flow changes: update this file in the same
change. The README's "Project Conventions" section points here.
