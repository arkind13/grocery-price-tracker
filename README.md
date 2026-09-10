# grocery-price-tracker v2 — local shops vs Woolworths

One Google Sheet, one Telegram bot, one list. This project compares the
prices of four local Mt Druitt shops (two halal butcheries, two fruit &
veg stores) against Woolworths for **mutton, chicken, fruits &
vegetables** — and tells you, in under 10 seconds, where to buy.

Everything that made v1 slow (Coles/Aldi tracking, auto-keywords,
queues, ledgers, resolve sessions, 30-minute agent investigations) was
deleted in the v2 rebuild. What remains is measured: **price lookup
5s · live search 17s · batch correction 5s · list 4.5s · Wednesday run
14s** — all inside their hard budgets.

## The 9 commands

| Command | What it does | Budget |
|---------|--------------|--------|
| `<item>` / "price of X" | Sheet-only lookup: Woolworths display price (5% team discount + home-brand extra) + every local shop's price + 🏆 winner. Meat lookups also carry the non-halal Woolworths twin line | ≤10s |
| `live <item>` | Direct web search Woolworths + Coles + Aldi (Amazon future). ≤3 prices per store. PRICES ONLY — never adds items, never codes. Sheet row shown as a side note if tracked | ≤20s |
| `list` | The ONE list: local items whose Woolworths side is blank (no price + no keyword). Fresh from the sheet, every entry coded | ≤5s |
| `specials` | Woolworths specials from the sheet (multi-buy deal rates + discounts) | ≤10s |
| `batch <codes+verdicts>` | ONE call: `ABC done; DEF gone; GHI rename halal lamb shoulder; JKL remove; MNO ignore`. Per-code replies. The agent never pre-investigates | ≤10s |
| `ignored` | Reveals the hidden ignore list | ≤10s |
| `wednesday` | THE weekly run: Woolworths.docx → overwrite prices; specials docx → deal rates; parity check; specials message (topic 206) + the ONE list (topic 208). `--specials-only` skips the main pass | ≤30s |
| `local-deals …` | Local-shop machinery: twice-daily FB post detector, inbox ingest (image→vision / text→parser), Dunya site sync, expire sweep, set-permanent/special | — |

Scheduled alongside these: `aldi-specials` (cron `8 * * * *`, self-gated
to Wed/Sat 05:xx Sydney, once per date) — posts the whole day's Aldi
Special Buys drop, theme-grouped, to the specials topic (206).

## The sheet

- **Products_Master** (13 cols, Woolworths-only): name, category, size,
  WW price (D), brand, last-updated, **WW keyword (G — the sync key,
  filled only by you)**, specials terms, rewards, aliases, sub-category,
  Item_Code, preferred.
- **Local_Deals** (11 cols): product + per-shop permanent/special price
  columns with validity stamps + comments + **Item_Code** — the parity
  key pairing it to master.
- **Archive** tab: every row retired in the v2 migration, full copy.
  Plus untouched `User_Shopping_Lists` and `Price_History`.

## The row-parity model (the core invariant)

Both tabs carry the SAME item set, always. A local-only item has a
master row with blank price + blank keyword and appears on the ONE
list. You fill the price + keyword in the sheet, say `done` (verify
only), and it leaves the list. If Woolies doesn't stock it, say `gone`
→ `GONE` written to the price cell, item leaves the list, row survives.
A Wool-only item's local line is simply blanked — never listed.
Inserts mirror on both tabs; a row inserted in the MIDDLE triggers a
hard alert (move it to the bottom and re-run); bottom-appends are
auto-mirrored by the next sync.

## Halal rules

Local butchery items are named `halal xxx` — the name prefix IS the
halal marker (fruit-shop items never carry it). Plain and halal meat
rows are always separate: local "beef mince" never matches Woolworths
"beef mince"; only "halal beef mince" pairs. Meat lookups show the
three-way answer (Woolworths non-halal vs local butcher vs Woolworths
halal) with local prices ALWAYS on the halal side.

## Search semantics (fixed, no surprises)

Sheet miss → answer from Local_Deals ("missing list [code]") or
"not tracked". Live search happens ONLY when you type `live`. No
classifier, no fallback, no investigation.

## Wednesday

Paste your Woolworths list + specials into the two .docx files, run
`wednesday`, get: prices overwritten, specials posted (topic 206), the
ONE coded list (topic 208), a parity line. 14s measured. No pause, no
reminders, no ceremony.

## Backups — and the canary

`tools/sheet_backup.py` writes a full JSON snapshot (every tab,
verified by read-back). Copies live LOCAL + on the VPS, refreshed by a
**03:17 daily cron that doubles as the health canary**: if the Google
API access or the sheet breaks, that cron fails the next morning.
Google Drive cloud copies are impossible for the service account
(zero quota) — the local + VPS JSON pair is the backup.

## ⚠️ CRITICAL INFRASTRUCTURE — never delete/archive/pause

- **GCP project `grocerypriceapp-488202`** — hosts the service account
  that is the ONLY reader/writer of the sheet. Deleting it killed all
  access within seconds once (restored via Google's 30-day window).
- **GitHub repos** `arkind13/grocery-price-tracker` +
  `arkind13/AI-Development-Environment` (archiving blocks pushes).
- **VPS `myvps`** + the 03:17 backup cron.

## Development

- Anaconda python (`anaconda3/python.exe`) — the default python3.13
  lacks curl_cffi.
- Tests: `anaconda3/python.exe -m pytest tests/ -q` → **646 passed,
  0 skipped**. Every behavioral rule has a pinned regression test; the
  suite must stay fully green (no xfails, no skips).

## Future projects (in order, each a fresh session)

1. **Amazon live search** — non-food items only.
2. **Weekly catalogue digest** — target the Coles/Woolworths catalogues
   directly and post the special items as one Telegram message.
3. **Longer arc** — location-aware specials ("oranges on special at
   Fruit World, 2 steps from Woolworths"): Google Places proximity +
   shop-site scrapes + LLM phrasing, all VPS-side.

## History

Everything from v1 (the full-complexity system), the 2026-09 quality
campaign (22 defects found & fixed), and the v2 rebuild artifacts lives
in `old md/`. The living docs are only: this README, `PROJECT-MAP.md`,
and `architecture-spec.md`.
