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
| `specials` | Per-shop (2026-09-12): bare "what's on special" asks WHICH SHOP first — Woolworths (`specials`), Aldi (`aldi-specials --force --no-telegram`, print-only on demand), or local shops (`specials --store local`, read-only from Local_Deals) | ≤10s |
| `batch <codes+verdicts>` | ONE call: `ABC done; DEF gone; GHI rename halal lamb shoulder; JKL remove; MNO ignore`. Per-code replies. The agent never pre-investigates | ≤10s |
| `ignored` | Reveals the hidden ignore list | ≤10s |
| `wednesday` | THE weekly run: Woolworths.docx → overwrite prices; specials docx → deal rates; parity check; specials message (topic 206) + the ONE list (topic 208). `--specials-only` skips the main pass | ≤30s |
| `local-deals …` | Local-shop machinery: twice-daily AUTO-INGESTING sweep (vision + merge + parity + ONE digest per window), watch-folder inbox ingest (image→vision / text→parser), open-question flow (undated boards / shop-less drops), Dunya site sync, expire sweep, set-permanent/special, resolve-shop | — |

Scheduled alongside these: `aldi-specials` (cron `8 * * * *`, self-gated
to Wed/Sat 05:xx Sydney, once per date) — posts the whole day's Aldi
Special Buys drop, theme-grouped, to the specials topic (206).

## The zero-step local flow (2026-09-11)

You save a shop's images into one folder; everything else happens
without you:

- **Sweep path**: the 05:00/15:00 detector downloads every new FB post
  itself (text-first, vision on the post's own images), ingests it
  (one vision call per post, all its images together), merges per
  shop (newest post's price wins), and posts ONE combined digest to
  the local-deals topic: per shop — items, prices, `min order …`
  pack terms, per-item validity, standout comparisons vs
  Woolworths, and any QUESTIONS (final prices only — user answer
  2026-09-11). Detector messages never say "done" and never ask you
  to save anything.
- **Instant path**: the PC watch-folder daemon
  (`tools/inbox_watcher.py`, auto-started at logon by
  `tools/install_inbox_watcher.ps1` — scheduled task with a
  Startup-folder fallback) watches `Desktop\shop-posts` —
  the four shop subfolders (Dunya / Merjan / Fruitopia / Abu Salim)
  are created for you; drop images/text into one and the digest
  arrives within minutes. A burst of files forms ONE post (90s settle window); the
  same file twice = one ingest (sha256 dedupe); network down = files
  queue until the push succeeds (60s retry); single-instance lock —
  never two writers.
- **Retention** (no image buildup): processed images auto-delete
  after 14 days on ALL three stores — the desktop `.sent\` folders,
  the VPS inbox code folders, and the sweep's downloaded post
  images. The data lives on the sheet + post log; images are only
  inputs. Pending needs_date evidence survives until its question is
  answered.
- **Questions** (the only thing you ever answer, repeated in every
  digest until answered): an undated board asks *reply with the date,
  or 'open' to leave it undated* (the set-date path re-stamps the
  sheet); a shop-less `AUTO…` drop asks *which shop?* —
  `local-deals --resolve-shop <CODE> <shop>` completes the ingest.
  Unreadable images write NOTHING and ask for a clearer version
  (never guesses); notice posts record as zero-item.
- **Ingest hardening (the three 2026-09-11 defects)**: /kg pack deals
  always write the per-kg rate in the special cell + the terms in the
  shop's Comments segment (`[MER] multi buy 3kg for $32.99` — one
  division, never the raw pack price, never per-ea); row reuse is
  plural-folded token matching that ignores unit markers and the
  source-based halal prefix (`Halal Sliced Lamb Neck /kg` reuses the
  existing `Halal Lamb Necks /kg` row + Item_Code; a 5kg pack and a
  /kg row stay separate BY DESIGN); comment merges are idempotent,
  strip-then-append per shop (no `[MER] [MER]`, untagged segments
  never crash).

## How the FB extraction works (and why the manual phase existed)

The sweep's Facebook fetch is two modules: `extractors/fb_flyer_fetch.py`
(the `STORES` list + the Scrape.do render) and
`extractors/fb_timeline_fetch.py` (post text + images out of the
render). What actually runs for each of the four shops:

- **Scrape.do renders the shop's PUBLIC Facebook page, logged out**
  (photos tab primary, root page fallback; the last-3 posts per shop
  are in scope; ≤40 render credits per run, shared with the Dunya
  catalogue). Direct scraping was ruled out early: Facebook blocks
  headless browsers and non-browser TLS outright (the same wall the
  Woolworths cookie investigation hit), and the logged-out timeline
  render exposes only the NEWEST post — two independent renders
  (plain + scrolled) on 2026-09-06 proved scrolling never surfaces
  older stories.
- **Text-first, vision second**: the render embeds each post as Comet
  JSON — post id, creation time, message text, and the post's own
  image urls. Post TEXT is parsed first (`extractors/deal_text.py`);
  vision runs only for image-only posts (one call, max 4 images, on
  the post's own images). Signed CDN urls are downloaded EXACTLY as
  captured — any param mutation → 403.
- **Optional logged-in route** (user-approved 2026-09-06): the user's
  own FB session pair (`FB_COOKIE_C_USER` + `FB_COOKIE_XS` — .env
  secrets, set by the user, never logged/committed) unlocks older
  posts; auto mode tries it first and falls back gracefully to the
  logged-out render.

**Why there was a manual "save the images" phase:** the failed first
build (2026-09-05) only DETECTED new FB posts — every post triggered
a "save the image into the inbox folder" round trip for the user, and
the ingest itself was fragile on top (the 2026-09-11 morning Merjan
board took 45+ minutes of manual rescue: duplicate rows, doubled
comments, wrong pack-deal maths). The 2026-09-11 zero-step redesign
retired that detector wording entirely — the sweep now auto-ingests
every new post, and the watch-folder (`Desktop\shop-posts`) is the
only manual path left, needing no commands either. The post-mortem
and the three ingest defects (ID-1/2/3) live in
`old md/auto-ingest-spec.md`.

### Adding a fifth FB shop

Yes — the fetcher handles any PUBLIC Facebook page, and each of the
current four was onboarded with the same one-store-at-a-time checklist
(Fruitopia first, end-to-end confirmed, then the rest). It is a small
project, not a config flip, because the shops are pinned in several
regression-tested places:

1. `extractors/fb_flyer_fetch.py` → `STORES`: key, name, fb_page_id,
   kind (`butchery` / `fruits`), 3-letter code. Text-post boards need
   nothing else; image-only boards go through the vision chain.
2. `core/local_deals.py` → `TAB_COLUMNS` (a `<shop>_perm` +
   `<shop>_sp` column pair), `SHOP_TAGS` + the comment-tag regex,
   `SHORT_SHOP_NAMES`, the domain-gate kind sets, and a one-time sheet
   migration adding the two columns (row parity is untouched: rows
   are items, not shops). A butchery-kind shop's items auto-carry the
   `halal` prefix; a fruit-shop's never do.
3. `tools/inbox_watcher.py` → `SHOP_SUBFOLDERS` (the watch-folder
   subfolder auto-created for the shop).
4. Every behavior above is pinned by tests — the suite stays fully
   green (v2 rule).

Cost note: each store adds Scrape.do renders to every sweep window;
the 40-credit per-run cap is shared across all stores + the Dunya
catalogue.

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

Both tabs carry the SAME item set, always — and, since the 2026-09-12
user ruling, they match ROW-FOR-ROW: same row count, same item at the
same row number, no blank lines. The Local_Deals tab is header + item
rows only (the old "Prices valid until" stamp row and the
BUTCHERY/FRUITS section titles are retired; per-cell ` (till …)`
stamps are the only validity display). A local-only item has a
master row with blank price + blank keyword and appears on the ONE
list. You fill the price + keyword in the sheet, say `done` (verify
only), and it leaves the list. If Woolies doesn't stock it, say `gone`
→ `GONE` written to the price cell, item leaves the list, row survives.
A Wool-only item's local line stays on the tab (name only, no prices)
so the row numbers keep matching. Inserts mirror on both tabs; a row
inserted in the MIDDLE is auto-repaired by Wednesday's sync (moved to
that tab's bottom); a break that isn't a single-row insert
(deletion/reorder) hard-alerts. Bottom-appends are auto-mirrored by
the next sync.

## Halal rules

Local butchery items are named `halal xxx` — the name prefix IS the
halal marker (fruit-shop items never carry it). Plain and halal meat
rows are always separate: local "beef mince" never matches Woolworths
"beef mince"; only "halal beef mince" pairs. Meat lookups show the
three-way answer (Woolworths non-halal vs local butcher vs Woolworths
halal) with local prices ALWAYS on the halal side.

## Search semantics (fixed, no surprises)

Sheet miss → answer from Local_Deals ("missing list [code]") or
"not tracked". Live search happens ONLY when you type `live` — on
every other phrasing, including "compare halal vs non halal X", the
sheet answer is relayed verbatim and the agent never touches the web
(user directive 2026-09-12: sheet-first, absolute). No classifier,
no fallback, no investigation.

**Lookup matching (hardened in the 2026-09-11/12 convergence loop —
2,000+ checks across three verification cycles):**

- The reply's `[code]` header always cites the row the query actually
  MATCHED — best token match, never "first row in sheet order" (the
  butchery sort exposed that accident class; `lamb necks` cites
  [YCQ], not the fillet row).
- Realistic forms just work: NL price fillers are stripped ("price
  of goat curry" → "goat curry", "how much is …" too); plurals,
  singulars, typos and even double-plural stress forms fold to the
  same stem ("Cauliflowers", "Choko" on "Chokos", "Tomatos" on
  "Tomatoes", "Strawberrie"); word order never matters.
- Naming the Woolworths product itself ("Woolworths Beef Mince 500g",
  brand word present) answers that row's own tracked price — never a
  locals dump. Generic brandless plain-meat names stay halal-scoped.
- The halal keyword gates the butcher search BY DESIGN (user ruling
  2026-09-11): bare protein queries answer Woolworths-scope; the
  halal cluster + missing-list answer is what "halal …" queries get.
- When nothing matches, the last-resort locals pool answers WITHOUT
  a code — never a false "missing list [XJA]" header on unrelated
  rows.

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
- Tests: `anaconda3/python.exe -m pytest tests/ -q` → **732 passed,
  0 skipped**. Every behavioral rule has a pinned regression test; the
  suite must stay fully green (no xfails, no skips).
- `tests/test_py311_syntax.py` guards every `core/` + `tools/` file
  against py3.12-only syntax (PEP 701 f-strings) — the VPS container
  runs Python 3.11 and a container-breaking syntax once shipped.
- Verification tooling: `tools/item_audit.py` (semantic sweep ·
  `--matrix --round N` — every item × every message format with
  round-invented variants · `--exec` — real CLI runs) +
  `tools/parity_audit.py`. The 2026-09-11/12 convergence loop (fix →
  check → fix, no user stops) ran three cycles over 2,000+ checks to
  a clean exit: evidence in `data/test_logs/cycle-2/` and
  `cycle-3/`, standing mechanism in `convergence-loop.md`, open
  items in `data/test_logs/open-fix-list.md`.

## Future projects (in order, each a fresh session)

1. **Amazon live search** — non-food items only.
2. **Weekly catalogue digest** — target the Coles/Woolworths catalogues
   directly and post the special items as one Telegram message.
3. **Longer arc** — location-aware specials ("oranges on special at
   Fruit World, 2 steps from Woolworths"): Google Places proximity +
   shop-site scrapes + LLM phrasing, all VPS-side.

## History

Everything from v1 (the full-complexity system), the 2026-09 quality
campaign (22 defects found & fixed), the v2 rebuild artifacts, and
the 2026-09-11/12 convergence-loop run documents live in `old md/`.
The living docs are only: this README, `PROJECT-MAP.md`,
`architecture-spec.md`, and `convergence-loop.md` (the standing
re-verification mechanism).
