# HANDOFF — Local_Deals perm/special columns (paused 2026-09-07)

> Resume point for the next session. Read THIS file first — it contains
> everything: objective, decisions, what is already coded, and the exact
> remaining steps. No need to re-read the whole codebase.

## 1. Objective (user request, 2026-09-07)

Rework the **Local_Deals** Google Sheet tab (the four Mt Druitt shops:
Dunya Butchery, Merjan Brothers, Fruitopia, Abu Salim):

1. **Two columns per shop** — PERMANENT pricing (no validity) and
   SPECIAL pricing (carries validity dates).
2. **Expiry sweep** — a special valid till 6-Sep must be REMOVED from
   the sheet on 7-Sep morning (automated, not manual).
3. **Comparison order** — special price first; fall back to the
   permanent price when no special exists.
4. **Shared Comments column fix** — when several shops share one
   product row, their multi-buy/bulk notes must not collide.
5. **A skill/CLI path for chat entries** like
   "update permanent pricing for fruitopia - carrots @ 6.50/kg".
6. **Dunya site prices are permanent** — manual Dunya updates are
   written as sent (user chose "just write what I send"; no site
   re-check on manual entry — the `--dunya-site` sync still overwrites
   as before).
7. **One-time job:** go through the sheet NOW and remove expired
   pricing (as of 2026-09-07 nothing was actually expired — Fruitopia
   posts run to 12/19 Sep).
8. Update README.md + PROJECT-MAP.md at the end.

### User's 4 decisions (via questions, 2026-09-07)

| Question | Decision |
|---|---|
| Scope | **Local_Deals tab only** — Products_Master untouched |
| Comments column | **ONE shared column, shop-tagged** notes (`[FRU] …; [MER] …`) |
| Dunya manual updates | **Write what the user sends** (no site compare on manual entry) |
| Fully-expired rows | **Keep the row, clear only the cell** (never delete rows in the sweep) |

## 2. Design (agreed + implemented shape)

New tab layout v2 — 10 columns (was 7):

```
A  Product
B  Dunya perm (site)        <- --dunya-site writes here (permanent, live site)
C  Dunya special (FB)       <- DUN ingest writes here
D  Merjan perm              <- manual entries only
E  Merjan special           <- MER ingest
F  Fruitopia perm           <- manual entries only
G  Fruitopia special        <- FRU ingest
H  Abu Salim perm           <- manual entries only
I  Abu Salim special        <- ABS ingest
J  Comments                 <- shared, shop-tagged: "[FRU] multi buy 2 for $1.50 — $0.75/ea"
```

Key rules baked into the code:

- **Special cells carry an inline validity stamp**: `0.75 (till 12 Sep)`
  or `[multi buy 2 for $1.50 — $0.75/ea] (till 12 Sep)`. The per-cell
  date is authoritative; tab row 2 keeps the per-shop summary stamp
  ("valid until Fri 12 Sep") for readability only.
- **Sweep removes only DATED cells** — ` (till d Mon)` in the past.
  Undated specials stay until the shop's next post replaces them
  (never guess). Rows are never deleted; row-2 expired stamps are
  cleared too.
- **Permanent cells are NEVER wiped** by rebuilds/ingests/subset runs.
- **rebuild_tab now preserves**: permanent columns, non-run shops'
  special columns (fetch-failure / `--stores` subset immunity), and
  other shops' comment segments. Only THIS run's shops' special
  columns are rebuilt (stale specials of a posted shop DO clear).
- **merge_store_tab (ingest)**: writes the shop's SPECIAL column
  (`dunya` key -> PERM column, `dunya_fb`/shop key -> SPECIAL),
  per-deal `valid_until` stamps each cell, comments merge per shop.
- **tab_store_price(row, shop)**: special first, skip expired, then
  permanent; non-numeric (bulk offer text) -> None.
- **set_store_prices(ws, shop, kind, entries, till)**: manual entry
  path; exact canonical-key row match (unit suffix ignored), appends
  a new row in the shop's domain section when no match; permanent =
  no stamp, special = ` (till d Mon)` stamp + row-2 update.

## 3. DONE — code already written (compiles clean)

All in `core/local_deals.py` (branch `feature/qrs-shop-multibuy`,
inner grocery-price-tracker repo, committed as WIP — see §7):

- `TAB_COLUMNS` v2 (9 keys), `SHOP_TAGS`, `_grid_col`,
  `_perm_column_for`, `_special_column_for`, `_target_column`,
  `_column_for` (legacy shim), `_comment_tag`, `_tag_note`,
  `_TAG_RE`, `_TAG_TO_SHOP`, `_shop_key_for_tag`,
  `_strip_shop_segments`, `_merge_comment_cell`.
- Validity stamp helpers: `_TILL_RE`, `_stamp_validity`, `_strip_till`,
  `_month_num`, `_cell_till_date`, `_special_expired`.
- `ensure_local_deals_tab` -> cols=10.
- `build_rows` -> 10-cell rows, stamps specials, tags comments.
- `rebuild_tab` -> preserve-semantics rewrite (see §2).
- `merge_store_tab` -> special column + per-deal stamps + comment
  merge (tag stripped before re-merge to avoid double `[FRU] [FRU]`).
- `_numeric_price` -> strips the till stamp before parsing.
- NEW `tab_store_price`, `sweep_expired_specials`,
  `set_store_prices` (appended right after `merge_store_tab`).

**Not yet wired (still referencing old behaviour):** CLI flags, halal
tier-3 reader, Friday/ingest call sites pass `valid_until` per deal
(ingest already has per-batch `valid_until` — needs attaching to each
deal dict before `merge_store_tab`; Friday `_process_store` needs the
post's date attached similarly).

## 4. TODO — remaining work (in order)

1. **Attach valid_until to deals**
   - `ingest_code` (~line 860): it builds `batches` with per-file
     `valid_until`; when building `all_vision_deals`, add
     `converted["valid_until"] = b["valid_until"]` per batch (today it
     only passes `newest_valid` as the row-2 stamp).
   - `_process_store_timeline` (~line 1990): attach the post's
     validity (`filter_recent_posts` returns `kept` as (post, end) —
     add `"valid_until": end` to each deal dict).
   - `_process_store` (photos path, ~line 2040): same with the
     payload's `valid_until`.
2. **Special-first readers**
   - `core/halal.py::query_local_butchers` (line ~384): pick price via
     `tab_store_price(row, shop_key)` per shop instead of
     "first non-empty cell"; include shop name in the result.
   - Check any other Local_Deals tab reader (grep
     `connect_worksheet("Local_Deals")` — halal is the only one found).
3. **CLI (`grocery_price_cli.py`, in the PARENT folder)**
   - Parser (local-deals block ~line 380): add
     `--set-permanent STORE ITEM PRICE [/kg|/ea] [--note ...]`,
     `--set-special STORE ITEM PRICE [--till "12 September"]
     [--note ...]`, `--expire-sweep`. Parse price+unit from one arg
     (accept "6.50/kg"); date via `extractors.deal_text.parse_validity_end`.
   - Dispatch `_cmd_local_deals` (~line 3821): handle the three flags
     (connect_spreadsheet -> ensure_local_deals_tab -> call
     `set_store_prices` / `sweep_expired_specials`, print lines).
   - **Morning hook**: in `run_daily_scan` (core/local_deals.py
     ~line 234), right after the window gate passes (05:00 window
     only), run `sweep_expired_specials` and include any removed
     lines in the heartbeat/first message. Keep it inside the
     once-per-window guard so it runs once.
4. **Tests** (`tests/test_local_deals.py` — FakeWorksheet already
   exists; TAB_COLUMNS-dependent assertions WILL FAIL until updated):
   - Update rebuild/merge/build_rows tests to the 10-col layout.
   - New tests: stamp parse/expire (`_cell_till_date`,
     `_special_expired`), sweep (dated expired cleared, undated kept,
     row kept, perm untouched, row-2 stamp cleared),
     `set_store_prices` (match vs new row, perm vs special stamp,
     comment tagging), `tab_store_price` (special-first, expired
     skip, permanent fallback), rebuild preservation (perm survives,
     non-run shop survives, comments merge both directions).
   - Run: `python -m pytest tests/ -x -q` (621 passing at last full run).
5. **Live tab migration (one-time)**
   - Current live tab is still 7-col, no row 2. Run a migration that:
     reads the tab, maps old cols (B dunya site->B perm, C dunya
     fb->C special, D merjan->E, E fruitopia->G, F abusalim->I,
     G comments->J), inserts the row-2 stamp row, writes A1:J.
     All existing prices are Fruitopia specials (12/19 Sep) + Dunya
     site perm; stamp Fruitopia cells with their post dates
     (12 Sep for the 5&6 Sep post items, 19 Sep for the new_post item
     — see `data/local_deals_post_log.json`; NOTE: the two Fruitopia
     board.txt/new_post.txt archives under data/local_deals_inbox
     were archived to processed/).
   - Then run the sweep once (expect 0 removed today).
6. **Skill + docs**
   - `claw-skills/local-deals/SKILL.md`: document the three new flags
     + the chat phrasing ("update permanent/special pricing for
     <shop> - <item> @ <price>/kg [till <date>]") -> CLI mapping.
   - REGENERATE `claw-skills/claw_skills_easy.md` (MANDATORY per
     AGENTS.md; one-shot: `.kilo/command/update-claw-skills-docs.md`).
   - README.md §"Local deals" + PROJECT-MAP.md §6 local-deals: layout
     v2, sweep, chat-entry flow.
7. **Three-way sync — CAREFUL**
   - **DO NOT scp `core/local_deals.py` to the VPS while the live tab
     is unmigrated / code unfinished** — the VPS bind-mount is LIVE
     and its ingest would break mid-state. Sync only after §4.5
     migration + tests pass.
   - Then: commit, push inner repo, scp core/local_deals.py +
     grocery_price_cli.py + skill files to
     `/home/ubuntu/openclaw/tasks/ai-tools/...`, checksum-verify.

## 5. Current sheet facts (read 2026-09-07)

- Local_Deals tab: 128 rows, 7 cols, NO "Prices valid until" row 2
  (old layout — merge path predates it). Rows 3-102 Dunya site
  (butchery perm), 103 one Merjan row (Lamb Curry 27.99), 105-125
  Fruitopia specials, Celery + Carrots have `[multi buy 2 for
  $1.50 — $0.75/ea]` comments.
- Nothing expired as of today (Fruitopia valid till 12/19 Sep).
- Post log (`data/local_deals_post_log.json`): only FRUT/FRU0709260907
  entries (board.txt till 12 Sep, new_post.txt till 19 Sep).

## 6. Gotchas discovered (save yourself the re-read)

- `TAB_COLUMNS` keys end in `_perm`/`_sp`; `_grid_col` returns a
  **1-based** column index that doubles as the row-list index (index 0
  = Product name). Sheet ranges are hard-written as `A1:J{n}`.
- `_merge_comment_cell(existing, shop_key, "")` removes that shop's
  segment — it's the merge primitive; `; ` separates segments.
- `MONTHS` in extractors/deal_text.py is full month names only —
  `_month_num` matches on 3-letter prefix ("Sep" works).
- `canonical_key` returns (base, variety) tuple; row matching in
  `set_store_prices` uses `canonical_key(_base_name(col_a))` —
  `_base_name` strips the ` /kg`/` /ea` suffix.
- `_store_kind("dunya")` -> "butchery"; `dunya_fb` maps to dunya.
- In tests, FakeWorksheet.update() sets rows directly — fine for the
  new code paths.
- Parent repo (`AI related/`) holds `grocery_price_cli.py` — CLI edits
  happen THERE (separate working tree from this inner repo).
- Pre-existing uncommitted changes in the inner repo (docx files,
  data/*.txt, recipe_resolver.py, architecture-spec.md) are the
  USER's in-flight work — do NOT commit or revert them.

## 7. Git state

- Inner repo `grocery-price-tracker/`, branch `feature/qrs-shop-multibuy`.
- WIP commit: ONLY `core/local_deals.py` + this handoff file
  (message starts "WIP: Local_Deals perm/special columns").
- Parent repo: untouched (no changes made there yet).
- VPS: UNTOUCHED (deliberately — see §4.7).
