# Architecture Spec — v2 Rebuild: Local Shops vs Woolworths

- **Date:** 2026-09-09
- **Stage:** 01 Architect (this doc) → 02 Plan → 03 Code → 04 Architect Checker
- **Status:** Interview COMPLETE — 27 questions across 7 themed batches, all
  answered by the user (decision log §2). READY FOR 02 PLAN. Coding is
  forbidden until the user approves `rebuild-plan.md`.
- **Inputs:** `arch-prompt.md` (the work order — supersedes fuzzy-matching
  assumptions), `README.md`, `PROJECT-MAP.md`,
  `old md/2026-09-quality-round/` (22-defect history), live sheet probe
  2026-09-09 (112 master rows; Local_Deals 133×10; orphan `[FRU]` comments
  confirmed on rows 115/116).
- **Supersedes:** this file overwrites the 2026-09-05 Local_Deals + halal
  spec (preserved in git history; the v1 phase docs move to
  `old md/2026-09-v2-rebuild/` at close-out).

---

## §0 The overriding design law

**Reduce time-to-answer.** Every command, file, list, and code path must
either make the user's answer faster or be deleted. New local shops must be
absorbable WITHOUT re-growing state sprawl: no new ledgers, no new queues,
no new per-shop cross-checks. The speed budget (§12) is binding — if a
design choice risks a budget, it is the wrong choice.

## §1 What the project is (v2 scope)

Compare LOCAL SHOP prices against Woolworths for **mutton, chicken, fruits
& vegetables**. Everything else the v1 system did (Coles/Aldi sheet
tracking, basket optimisation, shopping-list flows, preferences, resolve
sessions, queue convergence) is retired. Coles exists ONLY as a live-search
result inside the `live` verb — no Coles data ever lands in the sheet.

## §2 Decision log (interview 2026-09-09 — 27/27 answered)

| # | Theme | Decision |
|---|-------|----------|
| Q1 | Kept rows | Sub-category rule: rows whose Sub_Category is raw meat/chicken or fruit/veg stay; coder prints stay/leave list for one-time user confirm |
| Q2 | Archive | New `Archive` tab, full-row copy with ALL current columns; rows deleted from master; code never reads it; recovery = manual copy |
| Q3 | Dead columns | Drop E, F, J, K, L, N (all Coles/Aldi); new layout §3.1 |
| Q4 | Other tabs | `User_Shopping_Lists` + `Price_History` untouched |
| Q5 | Blank rows | Ingest auto-creates the blank master counterpart row (+Item_Code); writes NO prices, NO keywords |
| Q6 | Pairing key | NEW Item_Code column on Local_Deals; pairing by code; names may drift |
| Q7 | Board rotation | Rows survive; deletion is manual only; GONE removes from lists, never deletes rows |
| Q8 | Shared items | One Local_Deals row (many shop columns) ↔ ONE master row; count = unique items |
| Q9 | F&V prefix | No halal prefix on fruit-shop items |
| Q10 | Rename sides | Both sides get the prefix; local side automated in migration; master side matched/renamed manually BY THE USER for existing rows |
| Q11 | Non-halal twin | Always separate rows — plain non-halal master row stays with blank local side forever |
| Q12 | Halal marker | The name prefix IS the marker; Keywords col stays aliases-only |
| Q13 | GONE write | Literal `GONE` into the WW price cell (row kept; real price overwrites it on return) |
| Q14 | done | Verify-only: re-reads the row; confirms removal or reports what is still blank; writes nothing |
| Q15 | rename | Renames the item on BOTH tabs; code + prices unchanged |
| Q16 | remove | Deletes the row on BOTH tabs after an archive copy (the manual row-deletion mechanism) |
| Q17 | Ingest prefix | ALL items posted by a butchery get the `halal` prefix (regardless of item type); fruit shops never |
| Q18 | Parity sources | FULL parity — every line incl. Dunya's full website catalogue (row-for-row); new rows going forward come from FB posts + manual entries only |
| Q19 | Round-1 scope | Delegated to architect → comment-lifecycle fix only (see §17) |
| Q20 | Standout maths | Local vs RAW WW sheet price, >20% threshold; 5% team discount stays display-only |
| Q21 | Wednesday reads | Woolworths.docx + Woolworths_Specials.docx ONLY; no pause, no Coles.docx, no scp/queue ceremony |
| Q22 | List render | Live sheet read on demand (`list` verb) + Wednesday post; no cached snapshot files |
| Q23 | Lookup reply | Compact block: WW price + all local shop prices + winner; STYLISH (§11) |
| Q24 | live results | ≤3 compact lines per store (name, price, pack size); tracked-price side note; never writes |
| Q25 | Verb surface | 6 Telegram verbs + local machinery; everything else deleted (§13) |
| Q26 | Migration rows | Migration auto-creates blank master rows + codes (preview first); user manually matches/renames existing master rows |
| Q27 | Alignment | Tabs stay POSITIONALLY aligned: row N on master = row N on Local_Deals (§3.3); Item_Code is the durable key |

## §3 Sheet schema v2

### 3.1 Products_Master (Woolworths-only, 13 columns)

| New col | Header | Was | Notes |
|---------|--------|-----|-------|
| A | Product_Name | A | canonical name; `halal xxx` for butchery-sourced meat rows |
| B | Category | B | |
| C | Size | C | unit column (unchanged contract) |
| D | Woolworths_Price | D | real price, `N/A <date>` / `unavailable <date>` markers, or `GONE` |
| E | Brand_Type | G | `Home` marker kept (home-brand display discount) |
| F | Last_Updated | H | |
| G | Search_Keyword_Woolworths | I | THE sync keyword; filled only by the user (or `done`-verified) |
| H | Woolworths_Specials | M | specials terms incl. `multi-buy 2/$6.00` vocabulary |
| I | Rewards_Points | O | kept (column survives; no dedicated verb) |
| J | Keywords | P | aliases only — halal marking lives in the NAME now |
| K | Sub_Category | Q | drives domain gating + the kept-row rule |
| L | Item_Code | R | permanent 3-letter ID (A–Z minus I/L/O, unique) — parity key |
| M | Preferred | S | column survives; `prefer` command dies (no writer; manual only) |

Dropped: E Coles_Price, F Aldi_Price, J/K Coles+Aldi keywords, L Aldi
Refresh, N Coles_Specials. Column deletion renumbers everything — every
code reference to old letters G–S must be remapped in the rebuild.

### 3.2 Local_Deals (layout v2.1 — 10 existing columns + 1 new)

A Product · B–I per-shop perm/special columns (unchanged) · J Comments
(unchanged lifecycle — see Round 1) · **K Item_Code (NEW)** — the master
code of the paired row. The new column is APPENDED (not inserted) so all
existing column references stay valid. Shop columns keep the
permanent/special + validity-stamp + expire-sweep mechanics exactly as-is.

### 3.3 Row alignment (Q27)

Master data row N (N ≥ 2) ↔ Local_Deals row N+1 (Local_Deals row 2 is the
"Prices valid until" stamp row and is exempt). EVERY insert or removal
mirrors on both tabs in the same operation. `Item_Code` remains the
durable key: Wednesday's parity check (§10) verifies alignment from the
same two reads it already does and reports drift as a warning line —
repairs are NEVER automatic.

### 3.4 Archive tab

Created at migration: full copy of the pre-migration Products_Master (all
19 columns, all 112 rows) — this is the on-sheet archive of the ~80
retired rows and their Coles/Aldi data. Code never reads it.

## §4 Row-parity model (the core invariant)

1. The two tabs carry the SAME item set, ALWAYS — even one-sided items: a
   local-only item has a master row with BLANK D + BLANK G; a Wool-only
   item has a Local_Deals row with all shop cells blank.
2. **Who creates rows:** FB-post ingests and manual local entries
   auto-create the blank master counterpart (name copied with the source
   prefix rule §5, code assigned) and route the item to the missing list.
   The Dunya website catalogue was absorbed ONCE at migration; later site
   items do NOT auto-create rows. NO code path ever writes prices or
   keywords to the Wool side — the user fills those manually in the sheet.
3. **GONE** writes `GONE` into D: item leaves the list, row survives on
   both tabs, local prices still shown. A returning real price simply
   overwrites the marker.
4. **remove** deletes the row on both tabs after copying it to the
   archive. **rename** renames on both tabs. **Board rotation never
   deletes anything** — permanent cells persist, special cells die at
   their stamped expiry (existing sweep).
5. Same item at several shops = ONE row (several shop columns) ↔ ONE
   master row. "Same item count" = unique items.

## §5 Halal rules v2

- **Prefix rule (source-based, Q17):** every item ingested from a
  BUTCHERY source (Dunya FB/site, Merjan) is named `halal xxx`, whatever
  the item type. Fruit-shop items (Fruitopia, Abu Salim) never carry the
  prefix. Future shops get the rule by source type at registration.
- **The marker IS the name prefix** (Q12): a master meat row is halal iff
  its name contains `halal`. The Keywords column is aliases only.
- **Matching across tabs** is by Item_Code — but a plain (non-halal)
  master row NEVER pairs with a butchery item (Q11): they are different
  items, always separate rows. Plain non-halal meat rows stay forever
  with a blank local side.
- **Meat-term lookups** resolve through halal-named rows only (v1's
  halal-scoped view, simplified to the name test). The LLM live halal
  verification, auto-add, and verdict cache are DELETED (§13).
- Migration (Q10): the LOCAL side renames to `halal xxx` automatically
  (preview printed); the USER manually matches current master rows worth
  keeping and names them identically; unmatched local items get
  auto-created blank `halal xxx` master rows + codes (Q26).

## §6 The ONE list

**Definition (computed live from the sheet, never cached):** every row
where the Local_Deals side has at least one shop price AND the master side
has no real WW price (D) AND no WW keyword (G) AND D ≠ `GONE`. Each entry
carries its Item_Code. Wool-only items never appear (their local side is
blank by definition).

**Exits:** user fills D + G in the sheet and says `done` (verify-only) —
or `GONE` — or `remove` — or `ignore` (hidden). The ignore list exists but
is HIDDEN unless requested via the `ignored` verb.

**Render:** the `list` verb (Telegram) and the Wednesday post produce the
same styled list; both are fresh sheet reads (≤5s budget).

## §7 Command surface (6 Telegram verbs + local machinery)

| Verb | Does | Budget |
|------|------|--------|
| `<item>` / "price of X" (NL default) | Sheet-only lookup: WW display price (5% + home-brand extra) + every local shop's price (special-first) + winner (§11 format) | ≤10s |
| `live <item>` | Direct web search Woolworths + Coles. ≤3 compact lines per store: name, price, pack size. PRICES ONLY — never adds items, never assigns codes, never queues. If a sheet row exists → one side-note line with the tracked WW price. No classifier, no fallback, no investigation turns | ≤20s |
| `list` | The ONE missing list (§6), fresh from the sheet, styled, coded | ≤5s |
| `specials` | WW specials from the sheet (col H + D deal rates); Wednesday posts it automatically | ≤10s |
| `batch <codes+verdicts>` | ONE call: `ABC done; DEF gone; GHI rename halal lamb shoulder; JKL remove; MNO ignore`. Executes all verdicts (§4 semantics), replies per code. The agent is FORBIDDEN from pre-investigation turns — with one sheet and one list there is nothing to investigate | ≤10s |
| `ignored` | Reveals the hidden ignore list | ≤10s |

**Local machinery (not Telegram verbs):** `wednesday` (§10), the
`local-deals` family (FB detector, inbox ingest, vision chain, Dunya site
sync, expire sweep, set-permanent/special, ignore), and the one-time
migration/parity utilities. Nothing else exists — §13 deletes the rest,
including `update` (manual price writes happen directly in the sheet).

**NL routing rule for the skill:** any price question → the default
lookup; the word "live"/"search" → `live`; codes with verdicts → `batch`;
"the list" → `list`. A sheet miss answers from Local_Deals or "not
tracked / on the missing list [code]" — live search happens ONLY when the
user types the live verb. No auto-live-fallback anywhere.

## §8 Search semantics table

| Query state | Default lookup answer |
|---|---|
| Tracked (D real) | WW display price + local per-shop prices + winner |
| Meat term, halal row exists | Same, through halal-named rows only |
| Meat term, no halal row | Local butcher prices + "not tracked at Woolworths — missing list [code]" |
| Not tracked, local has it | Local prices + missing-list line with code |
| Not tracked, local blank too | "not tracked" (no live search) |
| D = `GONE` | "GONE at Woolworths" + local prices still shown |
| Tracked, `N/A <date>` marker | "unavailable this week (N/A <date>)" + local prices |
| Out of domain (not meat/F&V) | "not tracked — outside local-shop domains" (lookup only, never errors) |
| `live <item>` | ≤3/store prices only; sheet side note if tracked |

## §9 Ingest pipeline (what stays, what changes)

STAYS as-is: twice-daily FB post detector (05:00/15:00 Sydney windows),
inbox codes, image→vision / text→parser chain, per-shop merge
(`merge_store_tab`), validity stamps + expire sweep, shop-tagged Comments
(with the Round-1 lifecycle fix), Dunya WooCommerce site sync + catalogue
cache, manual set-permanent/set-special, >20% standout maths vs raw WW
price (Q20).

CHANGES: ingest pairs by Item_Code; a butchery post's items are
auto-prefixed `halal xxx` (Q17); an item with no master row auto-creates
the blank counterpart row + code and routes to the missing list (§4.2);
new shop columns are added by editing the existing STORES constant — no
new state per shop.

## §10 Wednesday run v2 (local machine)

1. Parse `Woolworths.docx` → match by col G keyword → overwrite D prices
   (markers `N/A`/`unavailable` + multi-buy deal-rate rule unchanged).
2. Parse `Woolworths_Specials.docx` → update H + D deal rates.
3. Parity check (from the same reads): counts + code alignment — one
   warning line if drift, never auto-repair.
4. Post: specials message (specials-wool topic 206) + the ONE missing
   list (weekly-lists topic 208). No interactive pause, no reminders, no
   scp/queue convergence, no 7-list ceremony. Target ≤30s end-to-end.

The Wednesday reminder cron and topic 151 are deleted (§13).

## §11 Telegram style kit (Q23 — "wow" requirement)

Every user-facing message uses one consistent styled template: emoji
section headers (🟢 Woolworths · 🔪 butchery · 🍎 fruit shop), bold item
names, aligned price columns, 🏆 winner badge, GONE/multi-buy badges, and
a compact footer (date + code legend). Telegram messages cannot animate —
"lively" is achieved with emoji + structure + consistent layout, never
with extra characters of prose. Max 4000 chars/message; the style kit is
tested (v1's `test_telegram_format.py` carries forward, restyled).

## §12 Speed budget (binding)

| Operation | Hard target | Design consequence |
|---|---|---|
| Sheet lookup reply | ≤10s | ONE master read + ONE Local_Deals read; no queue files, no convergence |
| Live search reply | ≤20s | Existing WW curl_cffi + Coles Scrape.do credit-guarded chain; ≤3/store |
| Batch correction | ≤10s | One read, writes per verdict, one reply |
| Wednesday run | ≤30s | Two docx parses + one batch write + two posts |
| One-list render | ≤5s | Pure read of the two tabs |

## §13 DELETION MANIFEST (explicit charter deliverable)

**Commands (parent `grocery_price_cli.py` + their code paths):**
`optimize`, `shop`, `prefer`, `recipe`, `rewards`, `map`, `todo`,
`add-to-list`, `searched-items`, `missed-pricing`, `no-price`, `lists`,
`unmapped`, `specials-scan`, `update`, `compare` (absorbed by the default
lookup), `search` (replaced by `live`), standalone `sync` (folded into
`wednesday`), `live-refresh` remnants, all `backfill-*` one-timers
(replaced by the migration utilities), `subcategories`.

**Core modules:** `basket_optimizer.py`, `shop` flow, `prefer`/
`set_preferred` writer, `searched_items.py`, `add_to_list.py` (queue),
`queue_sync.py`, `missing_items_tracker.py`, halal tier-2 LLM chain +
`halal_status.json`, the lookup engine's live-fallback/auto-add/ranked-
pair arms (the engine slims to sheet exact + alias match + UOM-free
display), `recipe_resolver.py`, `woolworths_discount_usage.json` tracker
(the DISPLAY discount engine itself STAYS).

**State files (archive copy, then delete):** `add_to_list.json`,
`searched_items.json`, `searched_item_code_tombstones.json`,
`unmapped_queue.json`, `delete_candidates.json`,
`list_action_progress.json`, `unmatched.txt`, `coles_missing.txt`,
`wool_missing.txt`, `live_api_capture.json`, `live_flush_log.json`,
`live_snapshots/`, `session_heartbeat.log`, probe/export JSONs in
`extractors/`. KEPT: `ignored_items.txt` (hidden list),
`deleted_rows.json` (row archive), `data/local_deals_inbox/`, the Dunya
catalogue cache, `scrapedo_health.json` (live machinery). Secrets
(`session_state.json`, `ww_coles_profile/`) are untouched — not part of
this charter.

**VPS/Telegram:** `/home/ubuntu/scripts/wednesday_reminder.py` + its cron
+ state file; local source `telegram_gateway/wednesday_reminder.py`;
topic 151 (stays dead — never re-provisioned); the 7-list posting
ceremony code paths. The local-deals daily-scan cron STAYS.

**Sheet:** Coles/Aldi columns (§3.1); ~80 retired rows → Archive tab.

**Docs (final tidy):** all v2 rebuild artifacts (arch-prompt, plan,
reports) → `old md/2026-09-v2-rebuild/` at close-out; living docs
(README, PROJECT-MAP, architecture-spec, parent test.md) updated instead.

Nothing user-owned is deleted without an archive copy (Archive tab,
`deleted_rows.json`, or `old md/`).

## §14 Explicitly KEPT (do not over-delete)

WW display discount engine (5% + home-brand) · multi-buy rate maths
(ingest + specials) · Local_Deals machinery in full (§9) · halal
domain gating by name prefix · sub-category data (col K) for domain
gating · expire sweep + validity stamps · Scrape.do credit guard ·
gspread client · UOM module only if still referenced after Round 3
(else it goes in the final tidy) · `User_Shopping_Lists` +
`Price_History` tabs · all 1250 passing tests that cover kept code
(tests of deleted code are deleted with it).

## §15 Future-provider clause (verbatim, per the work order)

"Once the v2 rebuild is fixed, verified, and running, a NEW separate
session will extend live search to ALDI first, then AMAZON (non-food
only). The v2 architecture must make this a provider-list addition
only — no changes to lookup logic, no new state."

Implementation consequence: `live` iterates a provider list
(`[woolworths, coles]`); adding Aldi/Amazon = one constant + one
extractor entry. Nothing else may change.

## §16 File boundaries & allowed scopes (for the planning model)

ALLOWED: `grocery_price_cli.py` (parent root) ·
`grocery-price-tracker/{core,extractors,tests}/` ·
`grocery-price-tracker/data/` (deletions per §13, archive copies first) ·
`grocery-price-tracker/{architecture-spec.md,rebuild-plan.md,README.md,PROJECT-MAP.md,test.md}`
· `old md/2026-09-v2-rebuild/` (archive) ·
`claw-skills/grocery-price/SKILL.md`, `claw-skills/local-deals/SKILL.md`,
`claw-skills/claw_skills_easy.md` (regenerate + sync per the standing
doc-sync rule) · `telegram_gateway/wednesday_reminder.py` (deletion) ·
VPS sync targets under `/home/ubuntu/openclaw/tasks/ai-tools/` + the
reminder-cron removal on the VPS.

FORBIDDEN: `.env` and any secret (never print, never commit) ·
`pc-agent/` · `Lost Battle/` · all sibling tools (budget, pricing,
digest, image, sketchnote, ai-studio) · `openrouterdiscount/`,
`my-budget-tracker/` (independent repos) · `.kilo/` (retired) ·
Google Sheet writes outside the spec'd migration/verbs (full backup
first — §rebuild-plan Round 1).

## §17 Architect decisions on delegated/open items

1. **Round-1 scope (Q19 delegation):** comment-lifecycle fix ONLY. It
   lives entirely in Local_Deals machinery that survives the rebuild, so
   nothing fixed there is later deleted; every round leaves the system
   functional (the user's stated rule).
2. **Doc naming:** this file IS the v2 spec (single living doc, always
   overwritten — never a second `-v2` file in the root). The plan's
   artifacts archive at close-out.
3. **`ignore` as a batch verdict**, not a 7th verb (batch accepts
   done/gone/rename/remove/ignore in one call).
4. **Wednesday posting targets:** specials → topic 206, list → topic 208
   (current working setup, minimal ceremony; DM copy optional).
5. **`update` command dies** — all manual sheet edits happen directly in
   the Google Sheet UI (the user's stated workflow).
6. **List rule detail:** `N/A <date>` markers with a keyword present =
   tracked-but-unavailable, NOT missing (the keyword is the tracked
   signal); marker-only cells without a keyword cannot occur (markers
   are only written for keyword-matched rows).
