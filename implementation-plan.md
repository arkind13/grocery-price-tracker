# Implementation Plan — v2 Round 3: Command surface v2 + DELETION MANIFEST

- **Date:** 2026-09-10 · **Stage:** 02 Plan → 03 Code
- **Inputs:** `architecture-spec.md` (v2 + §18 A1–A3), `rebuild-plan.md`
  (Round 3 scope), Round-2 close-out (tracker `dd3d8dd`/`5bda9ae`,
  parent `b19fe74`, checker PASS — 139/139 parity ALIGNED, 1361 green
  0 skipped, `list` = 105 entries).
- **SCOPE GUARD:** Round 3 ONLY. No Wednesday v2 (Round 4 — Wednesday
  stays absent exactly as at R2 close: no functional regression), no
  speed-budget measurement campaign (Round 5), no final tidy (Round 5),
  no skill polish beyond the interim accuracy rewrite (Round 4).
  Build verbs FIRST, delete v1 AFTER their replacements pass tests.
  **If reality contradicts the spec at any step: STOP and report.**
- **Rule:** this file is overwritten in place each round.

## 0. Ground truth (R2 close, checker-verified) + consequences

| Fact | Consequence for Round 3 |
|------|------------------------|
| Master 140×13 (139 coded data rows, Item_Code col L idx 11); LD 143×11 (139 items + 2 section rows, code col K idx 10); Archive 113×19; parity ALIGNED | Every write path must PRESERVE positional parity — batch `remove` deletes the same row index on both tabs; ingest appends on BOTH tabs in one operation |
| Live commands: `local-deals` (all flags), `specials`, `price`, `list`; everything else behind the `RETIRED_V1` intercept (`grocery_price_cli.py:7135`) | D2 removes the intercept together with the retired parsers/handlers |
| `v2_read.py` (286 lines): parse/read_tabs/lookup_item/missing_list/render_* ; `core/telegram_format.py` = the existing Style Kit (32 tests) | Batch/live/ignored build ON TOP of v2_read; the style kit is EXTENDED, not reinvented |
| `merge_store_tab` inserts new rows INSIDE section blocks (`core/local_deals.py:2605`), `set_store_prices` likewise (`:2929`) | **Must change to bottom-append on BOTH tabs in one operation** (Q27 alignment + §18/A2 append-only). Mid-tab inserts would make every new local item a parity "middle_insert" hard alert |
| `item_code_registry.json` (R2) guarantees code uniqueness | New-row code assignment (ingest + batch paths) reuses THIS registry — no new state |
| Day-one missing list = 105 entries | No batch dry-run against real codes except verify-only `done` (writes nothing) |

**No USER GATES this round** (nothing destructive touches the sheet's
structure; deletions are git-reversible and archived-first). STOP
conditions instead: parity audit ≠ ALIGNED after any write verb; any
grep-clean hit; any suite failure after pruning.

## B1 — `live` verb (spec §7/§8; ≤20s)

**Files:** `grocery-price-tracker/core/v2_live.py` (NEW) + `grocery_price_cli.py` (subparser).

```python
"""v2 live search (spec §7 'live', §15 future clause). PRICES ONLY.
This module NEVER receives a worksheet handle — it cannot write."""

LIVE_PROVIDERS = ["woolworths", "coles"]
# §15: adding ALDI/AMAZON later = one entry here + one extractor
# mapping in _PROVIDER_FN. Nothing else may change.

def live_search(query: str) -> dict:
    """{provider: [≤3 × {'name','price','size'}], 'errors': {...}}.
    Woolworths: extractors.woolworths_extractor no-auth search.
    Coles: extractors.coles_extractor Scrape.do credit-guarded search
    (existing chain, unchanged). ≤3 ranked results per store; price =
    numeric now-price; size = package size or ''."""

def render_live(results: dict, tracked_note: str | None) -> str:
    """Styled block: per-store compact lines +, when the item is
    tracked, ONE side-note line with the sheet WW price (from
    v2_read.lookup_item — callers fetch it, this module stays
    sheet-free)."""
```

CLI: `live --item X` (required) → prints render; exit 0 even on a
store error (error line per store, never silence).
**Tests (T-set 1):** no-write guarantee (module imports no sheets
client; test asserts no worksheet arg exists in signatures), ≤3/store
cap, provider-list iteration order, side-note presence when tracked,
store-error degradation line.

## B2 — `batch` engine (spec §4/§7; ≤10s)

**Files:** `grocery-price-tracker/core/v2_batch.py` (NEW) + `grocery_price_cli.py` (subparser) + one `v2_read` edit.

```python
"""v2 batch corrections (spec §4/§7): ONE call, every verdict, one
per-code reply. No pre-investigation — with one sheet and one list
there is nothing to investigate."""

def parse_verdicts(text: str) -> list[dict]:
    """'ABC done; DEF gone; GHI rename halal lamb shoulder; JKL
    remove; MNO ignore' -> [{'code','verb','arg'}]. rename's arg =
    free text to the ';' / end. Unknown verbs -> {'code','verb':'?'}."""

def apply_verdicts(verdicts: list[dict]) -> list[str]:
    """ONE read of both tabs, then per verdict:
    done   -> VERIFY-ONLY (Q14): master D real price AND keyword G
              present -> '[CODE] ✓ done — off the list'; else names
              exactly what is still blank. WRITES NOTHING.
    gone   -> master D = 'GONE' (Q13). Row kept everywhere.
    rename -> master A = new name AND LD A = new name when the LD row
              is named (Q15). Codes/prices untouched.
    remove -> ARCHIVE FIRST: append both rows to data/deleted_rows.json
              (source 'v2-batch-remove'), then delete the SAME row
              index on both tabs (parity preserved, Q16).
    ignore -> append '[CODE] name' line to data/ignored_items.txt.
    Unknown code -> '[CODE] ✗ unknown code' — remaining verdicts still
    execute. One clear+update per tab max; tools/parity_audit.audit
    after → must be ALIGNED (else raise + report, no partial silent
    state)."""
```

`v2_read.missing_list` edit (1 file): load `data/ignored_items.txt`
codes; exclude ignored codes from the list (hidden per spec §6).

CLI: `batch --verdicts "..."` → prints per-code reply lines.
**Tests (T-set 2):** each verdict on FakeSheet pairs (incl. GONE
overwritten by a later real price, rename lands on both tabs, remove
archives BEFORE deleting, done reports the blank side), unknown code
isolation, ignored exclusion from `missing_list`, post-batch audit
ALIGNED, mixed-verdict single call.

## B3 — `ignored` verb

CLI subcommand only: prints `data/ignored_items.txt` (count + lines),
exit 0 on empty ("ignore list is empty"). No module — one handler.

## B4 — Telegram style kit v2 (spec §11)

**Files:** `core/telegram_format.py` (extend) + restyled renders in
`core/v2_read.py` (render_lookup/render_list — logic unchanged) and
the B1/B2 renderers + `tests/test_telegram_format.py` (extend),
`tests/test_v2_read.py` (update render assertions).

Kit elements (binding): emoji section headers (🟢 Woolworths · 🔪
butchery · 🍎 fruit shop), bold item names, aligned price columns,
🏆 winner badge, GONE / 🏷️ multi-buy badges, compact footer (date +
code legend), hard cap 4000 chars with clean chunk splitting. No
animation claims — structure + emoji carry the "wow" (§11 constraint).
`specials` output restyled through the same kit.

## B5 — Ingest pipeline: prefix + parity auto-create (spec §9 changes)

**File:** `grocery-price-tracker/core/local_deals.py` (+ callers in
`ingest_code`/`_process_store`/`sync_dunya_site`).

1. **Halal prefix (Q17):** at deal normalization, EVERY item from a
   butchery-source store gets `halal ` (display casing `Halal `) on
   its name — regardless of item type; fruit shops never prefixed.
   One helper `_prefix_butcher_deals(store_key, deals)`.
2. **Bottom-append parity (Q27 + §18/A2):** `merge_store_tab` and
   `set_store_prices` new-row inserts (anchors `core/local_deals.py`
   ~2605 and ~2929) change from section-block insert to APPEND AT GRID
   END. Signature change:
   `merge_store_tab(worksheet, store_key, deals, valid_until=None,
   master_ws=None) -> tuple[int, list[str]]` — when `master_ws` is
   given, the SAME operation appends a blank 13-col master row (name,
   Item_Code from `item_code_registry.json`, Sub_Category by domain;
   D/G blank per §4.2) and writes the code into the LD row's col K;
   returns (rows, new-row report lines). `None` (tests/legacy) skips
   the master mirror and still reports the rows that WOULD mirror.
3. **Ingest wiring:** `ingest_code`/`_process_store` pass
   `master_ws=connect_spreadsheet().worksheet("Products_Master")`.
   Missing-list routing needs NO code — a blank master row + priced LD
   row IS a §6 list entry (pure computation, zero new state).
4. **Dunya site = no new rows (§18/A1):** `sync_dunya_site` unmatched
   site items are SKIPPED + reported ("not tracked — add via an FB
   post or a manual entry"), never appended.
**Tests (T-set 3):** prefix applies to all butchery-post items (incl.
a non-meat one) and never to fruit shops; bottom-append on both tabs
in one op (parity ALIGNED after); master row blank on D/G + coded;
dunya-site unmatched skip + report; matched-row updates unchanged.

## B6 — Interim skill docs (accuracy now; polish is Round 4)

**Files:** `claw-skills/grocery-price/SKILL.md` (rewrite to the 6-verb
surface: NL routing table — any price question → `price`; "live"/
"search" → `live`; codes+verdicts → `batch`; "the list" → `list`;
specials → `specials`; ignore reveal → `ignored`; the
no-pre-investigation rule verbatim; `local-deals` machinery note);
`claw-skills/local-deals/SKILL.md` (touch ONLY the halal-prefix rule
wording); regenerate `claw-skills/claw_skills_easy.md` per the
standing AGENTS.md doc-sync rule. VPS-sync the three files.

## D1 — Archive copies BEFORE any deletion (state files)

```bash
cd "C:/Users/User.DESKTOP-R2G441H/Documents/AI related/grocery-price-tracker"
mkdir -p "old md/2026-09-v2-rebuild/state-archive/data" "old md/2026-09-v2-rebuild/state-archive/extractors"
cp data/{add_to_list.json,add_to_list_code_tombstones.json,searched_items.json,searched_item_code_tombstones.json,unmapped_queue.json,delete_candidates.json,list_action_progress.json,unmatched.txt,coles_missing.txt,coles_missing_items.json,wool_missing.txt,missed_pricing_ages.json,live_api_capture.json,live_flush_log.json,session_heartbeat.log,forget_list.json,price_unavailable.json,halal_status.json,search_last_results.json,phase9_defect_log.json} "old md/2026-09-v2-rebuild/state-archive/data/" 2>/dev/null
cp -r data/live_snapshots "old md/2026-09-v2-rebuild/state-archive/data/"
cp extractors/{probe_results.json,ww_full_export.json,ww_products_export.json} "old md/2026-09-v2-rebuild/state-archive/extractors/" 2>/dev/null
# plus any probe_*.json the coder's grep finds in extractors/
cd "old md/2026-09-v2-rebuild/state-archive" && find . -type f -exec sha256sum {} \; > SHA256SUMS.manifest
```
("if present" semantics: `2>/dev/null` skips already-absent names; the
manifest is the deletion checklist — a file is deleted ONLY if it is
in the manifest.)

## D2 — Delete retired commands (`grocery_price_cli.py`)

Remove the subparsers + handlers + private helpers for: `compare`,
`optimize`, `shop`, `prefer`, `recipe`, `search`, `rewards`, `map`,
`todo`, `add-to-list`, `searched-items`, `missed-pricing`,
`no-price`, `lists`, `unmapped`, `specials-scan`, `update`, `sync`,
`wednesday`, `backfill-keywords`, `backfill-sizes`,
`backfill-subcategories`, `backfill-codes`, `backfill-home-brands`,
`subcategories`, `live-refresh` — plus the now-dead `RETIRED_V1`
intercept. Remaining CLI surface: `price`, `list`, `live`, `batch`,
`specials`, `ignored`, `local-deals`. Verify `--help` lists exactly
those seven.

## D3 — Delete retired core modules (spec §13 + zero-caller consequences)

DELETE files: `core/basket_optimizer.py`, `core/shop_flow.py`,
`core/preferences.py`, `core/searched_items.py`, `core/add_to_list.py`
(queue module), `core/queue_sync.py`, `core/missing_items_tracker.py`,
`core/recipe_resolver.py`, `core/price_comparator.py`,
`core/lookup.py`, `core/sheets_sync.py`.
SLIM `core/halal.py`: delete the tier-2 LLM chain
(`HALAL_CHECK_MODEL_CHAIN`, the live-verify functions, verdict-cache
IO); KEEP `is_meat_term`, `HALAL_CHECK_CATEGORIES`, domain sets.
Manifest-adjacent deletions (justified, flag in the report for the 04
checker): `price_comparator`/`lookup`/`sheets_sync` have zero callers
once D2 lands — §13's "slimmed lookup" intent already lives in
`v2_read` (exact Col A + alias col J).
KEEP (do not over-delete): `name_matcher.py` (canonical_key used by
local_deals + migrate_v2), `uom.py` (fate decided Round 5 per §14),
`extractors/doc_parser.py` (Round-4 dependency), all live extractors,
`specials_reporter.py`, `telegram_format.py`, `woolworths_discounts.py`
(display engine), `subcategory.py`, `sheets_client.py`, `v2_read.py`,
data/{ignored_items.txt, deleted_rows.json, item_code_registry.json,
local_deals_*, scrapedo_health.json, fb_flyers/, local_deals_inbox/}.

## D4 — Delete the archived state files (only AFTER D1 manifest verifies)

Delete every data/ + extractors/ file present in SHA256SUMS.manifest.
`data/` keeps: `__init__.py`, `deleted_rows.json`, `ignored_items.txt`,
`item_code_registry.json`, `local_deals_cron_state.json`,
`local_deals_first_fire.json`, `local_deals_inbox/`,
`local_deals_post_log.json`, `local_deals_scan_state.json`,
`scrapedo_health.json`, `fb_flyers/`, `diagnostics/`,
`sheets_manager.py`, `session_state.json`, `ww_coles_profile/`
(secrets — untouched), `test_logs/` (evidence).

## D5 — VPS/Telegram retirement (spec §13)

**Remote VPS:**
```bash
ssh myvps 'crontab -l | grep -v wednesday_reminder | crontab -'
ssh myvps 'rm -f /home/ubuntu/scripts/wednesday_reminder.py /home/ubuntu/scripts/.wednesday_reminder_state.json /home/ubuntu/scripts/wednesday_reminder.log; crontab -l'
```
(the report records the removed line verbatim for the audit trail).
**Local parent repo:** `git rm telegram_gateway/wednesday_reminder.py`.
Topic 151 stays dead — documented, no action. The daily-scan cron AND
the 03:17 backup cron STAY.

## T — Tests: add + prune (mandatory, zero-skip)

ADD (T-sets 1–3 above +): style-kit tests (~6: header emojis, winner
badge, GONE badge, 4000-char split, footer legend, specials restyle);
`ignored` verb smoke; `batch` mixed-run reply ordering.
PRUNE (deleted code — files removed wholesale unless noted):
`tests/test_lookup.py`, `tests/test_lookup_uom.py`,
`tests/test_sheets_sync.py`, `tests/test_comparator.py`,
`tests/test_searched_items.py`, `tests/test_add_to_list.py`,
`tests/test_queue_sync.py`, `tests/test_shop_flow.py` (if present —
grep), `tests/test_cli.py` **prune in place** (drop retired-command
tests; keep local-deals/specials/price/list/live/batch/ignored cases).
Full suite must be green with 0 skipped; the coder REPORTS the final
count (pruning makes a fixed prediction meaningless — green + zero
skip + reported count is the criterion).

## V — Verification battery (all scripted)

1. **grep-clean (zero dead references):**
```bash
cd "C:/Users/User.DESKTOP-R2G441H/Documents/AI related"
grep -rnE "basket_optimizer|shop_flow|preferences|set_preferred|searched_items|add_to_list|queue_sync|missing_items_tracker|recipe_resolver|price_comparator|sheets_sync|RETIRED_V1|from core import lookup|from core.lookup|coles_price|Search_Keyword_Coles|wednesday_reminder|specials-scan|missed-pricing|add-to-list|searched-items|backfill-" \
  grocery_price_cli.py grocery-price-tracker/core/ grocery-price-tracker/extractors/ grocery-price-tracker/tests/ claw-skills/ | grep -v "old md/" | grep -v "\.pyc"
# MUST return zero lines (tools/migrate_v2.py doc mentions are allowed ONLY in comments — if any hit is code, fix it; if it is a false positive, list it in the report)
```
2. `python grocery_price_cli.py --help` → exactly 7 subcommands.
3. Parity: `grocery-price-tracker/tools/migrate_v2.py audit` → ALIGNED.
4. Live verb battery (timed — budgets: lookup ≤10s, live ≤20s, batch
   ≤10s, list ≤5s): `price --item "halal beef mince"` · `list` ·
   `specials --store woolworths` · `live --item "chicken breast"` ·
   `batch --verdicts "<real-code> done"` (verify-only — writes
   nothing; pick a code from `list` output) · `ignored`.
5. Full suite green 0 skipped.

## A — Close-out + sync

Suite green → tracker commit (core/v2_live.py, core/v2_batch.py,
core/v2_read.py, core/local_deals.py, core/telegram_format.py,
core/halal.py, deletions, tests, plan, state-archive) + push; parent
commit (`grocery_price_cli.py`, `telegram_gateway/wednesday_reminder.py`
removal, test.md entry) + push; scp runtime files to the VPS mirror
(grocery_price_cli.py, core/{v2_live,v2_batch,v2_read,local_deals,
telegram_format,halal}.py, the three claw-skills files) + md5 verify;
report three-way sync.

## Acceptance criteria (rebuild-plan Round 3)

1. Every verb answers within budget on the live sheet (timed proof in
   the report).
2. `batch` executes mixed verdicts in ONE call with per-code replies
   (live proof: the verify-only `done` run + the offline mixed test).
3. Zero dead references remain (grep-clean output — empty or
   itemized false positives only).
4. `claw-skills` docs regenerated + synced (claw_skills_easy.md
   updated; md5s match VPS).
5. Deletions archived-first (SHA256SUMS.manifest committed); suite
   green, 0 skipped; three-way sync in sync.

## Rollback

Code: git revert (both repos). State files: restore from
`old md/2026-09-v2-rebuild/state-archive/` (sha256-verified). VPS cron:
re-add the recorded crontab line. No sheet-structure changes occur
this round — the parity audit after every write verb is the tripwire.
