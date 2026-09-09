# Implementation Plan — v2 Round 2: Sheet migration v2 + minimal v2 read path

- **Date:** 2026-09-09 · **Stage:** 02 Plan → 03 Code
- **Inputs:** `architecture-spec.md` (v2 + §18 A1–A3), `rebuild-plan.md`
  (Round 2 scope, step-0 gate, USER GATE rule), Round-1 close-out
  (tracker `933af6e` / parent `5342201`, checker PASS, 1319 green),
  live sheet probe 2026-09-09 (§0 below).
- **SCOPE GUARD:** Round 2 ONLY. No verb surface beyond `price`/`list`,
  no v1 module deletions (dispatch-disable only — deletion is Round 3),
  no Wednesday v2 (Round 4), no style kit (Round 3; style-lite here).
  **If reality contradicts the spec at any step: STOP and report —
  never adapt silently.**
- **Rule:** this file is overwritten in place each round.

## 0. Ground truth (live probe 2026-09-09) + design consequences

| Fact | Value | Consequence |
|------|-------|-------------|
| Products_Master | 113×19; 112 data rows, **all 112 already carry Item_Codes** | Migration assigns codes ONLY to new blank rows |
| Strict keep rule (Sub_Category ∈ `BUTCHERY_DOMAIN` ∪ `PRODUCE_SUBCATEGORIES`, both importable from `core.local_deals`) | **KEEP 10 / LEAVE 102** | Differs from the "~80 archived" estimate — NOT a spec contradiction: the G1 preview is authoritative, and 4 borderline labels (lettuce, coriander, greek salad ×2 — produce-adjacent but outside the sets) are surfaced as a BORDERLINE section for the user's one-time ruling at the gate |
| Local_Deals | 133 rows = header + validity row + 2 section titles + **129 item rows (105 with ≥1 shop price)** | Day-one missing list ≤ ~105 entries (spec §18/A1 accepted) |
| Backup system (Round-1 close) | local `backups/grocery-tracker-backup-2026-09-09.json` + VPS copy + daily 03:17 CEST cron; Google cloud-copy blocked for the SA (403 quota) | S0 verifies AND refreshes all three legs; the pre-migration JSON is the restore net |
| LD grid writers (`merge_store_tab`, `sweep_expired_specials`, `set_store_prices`, `repair_orphan_comments`, `rebuild_tab`) | all write range `A1:J{n}` and normalize width to `len(TAB_COLUMNS)+1` = 10 | **TRAP:** once col K (Item_Code) exists, every such write TRUNCATES it. Task S5w widens ALL writers to 11 cols / `A1:K{n}` FIRST, with a regression test per writer |
| Master writers post-migration | Wednesday v1, map/todo/update/sync reference dead columns → dispatch-disabled (S6); `sheets_sync.py` needs NO remap this round | Between R2 and R4 NOTHING writes master D except the user, manually in the sheet — exactly spec §4.2 |

**USER GATE protocol (binding):** each gate prints its complete preview,
then asks exactly `APPLY? (y/n)`. `y` proceeds; anything else aborts
with ZERO further sheet writes. Gates run in the coder session with the
user present; none may be skipped, reordered, or batched together.

## S0 — Backup freshness gate (STOP-gate; scripted; BEFORE any write)

**Local:**
```bash
cd "C:/Users/User.DESKTOP-R2G441H/Documents/AI related/grocery-price-tracker"
"$USERPROFILE/anaconda3/python.exe" tools/sheet_backup.py    # exit 0; today's JSON in backups/
```
**Remote VPS:**
```bash
ssh myvps 'docker exec openclaw-core python3 /app/tasks/ai-tools/grocery-price-tracker/tools/sheet_backup.py && ls /home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/backups/'
ssh myvps 'crontab -l | grep sheet_backup'                   # expect the 03:17 line
```
**STOP conditions (abort the session, report, no writes):** any exit
≠ 0; today's JSON absent locally or on the VPS; cron line missing.
Also confirm the pre-migration artifact
`grocery-tracker-backup-2026-09-09.json` still exists on both sides at
close (daily files never replace it).

## S1 — Migration tool, preview mode (code only; no writes)

**File:** `grocery-price-tracker/tools/migrate_v2.py` (NEW). Pure
grid-in/grid-out helpers (offline-testable); only `main()` touches the
sheet. CLI: `preview` · `apply-stay-leave` · `apply-columns` ·
`apply-parity` · `audit`.

```python
"""One-shot v2 sheet migration (Round 2). Subcommands:
  preview           — G1/G2/G3 previews (read-only)
  apply-stay-leave  — G1 outcome: Archive tab + retire rows
  apply-columns     — G2 outcome: drop E,F,J,K,L,N
  apply-parity      — G3 outcome: halal renames + blank master rows +
                      Local_Deals col K + positional alignment
  audit             — parity audit via tools/parity_audit.audit
"""
KEEP_SETS = (BUTCHERY_DOMAIN, PRODUCE_SUBCATEGORIES)   # core.local_deals
BORDERLINE = {"lettuce", "coriander", "greek salad"}   # user rules at G1

def stay_leave(master_grid: list[list]) -> dict:
    """{'keep': [...], 'leave': [...], 'borderline': [...]} (row dicts
    w/ row#, name, code, sub_category). Keep iff
    normalize_subcategory(grid[i][16]) ∈ a KEEP set; BORDERLINE labels
    listed separately (default: NOT kept unless the user moves them)."""

def build_archive_grid(master_grid: list[list]) -> list[list]:
    """Verbatim full 19-column copy incl. header (spec §3.4)."""

def drop_columns(master_grid: list[list]) -> list[list]:
    """Remove 0-based indices [4, 5, 9, 10, 11, 13] (E,F,J,K,L,N).
    Assert the result header == the 13 headers of spec §3.1 in order;
    raise (do not write) on any mismatch."""

def plan_halal_renames(ld_grid: list[list]) -> list[tuple[int, str, str]]:
    """BUTCHERY-section item rows whose base name lacks 'halal'
    (case-insensitive) → (row_idx, old_name, 'Halal ' + old_name).
    FRUITS/OTHER rows untouched (spec §5)."""

def plan_new_master_rows(ld_grid: list[list], master_grid_13: list[list],
                         ) -> list[dict]:
    """Unpaired LD item rows (no master row whose canonical base name
    matches — reuse core.local_deals.canonical_key + _base_name) →
    [{'name': …, 'code': …, 'subcategory': …}]. Name gets the 'Halal '
    prefix for BUTCHERY-section rows only; subcategory = the item's
    domain label ('fruit & veg' / the butchery label). Codes: 3 letters
    A–Z minus I/L/O, unique vs all existing master codes."""

def align_grids(master_grid_13, ld_grid_11) -> tuple[list, list]:
    """Positional alignment (spec §3.3). Unified order = LD item rows
    in tab order (LD section rows FRUITS/BUTCHERY/OTHER preserved on
    the LD side only), then Wool-only master rows appended at the END —
    each mirrored by a BLANK LD item row (Col A empty, code in col K).
    Master data row N ↔ LD row N+1; master carries NO section rows."""

def main() -> int    # argparse dispatch; apply-* ask nothing (the
                     # SESSION owns the gates); every apply verifies
                     # its own post-state and prints it
```

**Verify:**
```bash
"$USERPROFILE/anaconda3/python.exe" -m py_compile tools/migrate_v2.py
"$USERPROFILE/anaconda3/python.exe" -m pytest tests/test_migrate_v2.py -q
"$USERPROFILE/anaconda3/python.exe" tools/migrate_v2.py preview       # live, read-only
```

## G1 — Stay/leave (USER GATE) → `apply-stay-leave`

Preview: KEEP (~10, with codes + sub-categories), BORDERLINE (4 rows),
LEAVE (~102, names only + count). User moves rows between lists at the
gate; the ruling is recorded verbatim in the session report. **APPLY?
(y/n)** →
1. Create `Archive` tab; write the FULL current master grid (113×19).
2. Delete confirmed-LEAVE rows from Products_Master bottom-up
   (`delete_rows(i)` in DESCENDING row order so indices hold).
3. Verify + print: Archive 113×19; master = header + confirmed keeps.

## G2 — Column drop (USER GATE) → `apply-columns`

Preview: the spec §3.1 table mapped onto the live header (old→new
letters). **APPLY? (y/n)** → `delete_columns(i)` 1-based indices
**14, 12, 11, 10, 6, 5 — strictly descending (N, L, K, J, F, E)**.
Verify header equals EXACTLY:
`Product_Name, Category, Size, Woolworths_Price, Brand_Type,
Last_Updated, Search_Keyword_Woolworths, Woolworths_Specials,
Rewards_Points, Keywords, Sub_Category, Item_Code, Preferred`.

## G3 — Parity migration (USER GATE) → `apply-parity`

Preview prints ALL of: halal rename list; new blank master rows with
codes (~unpaired LD items); Local_Deals col-K append + backfill plan;
final aligned order (side-by-side counts + first/last 5 pairs).
**APPLY? (y/n)** → in order:
1. **S4** renames on Local_Deals (`Halal xxx`, BUTCHERY rows only).
2. Blank master rows APPENDED at the bottom (13-col row: name,
   Item_Code, Sub_Category only — D/G stay BLANK; spec §4.2).
3. LD col K: header `Item_Code` + the paired master code on every item
   row (existing code for matched rows, the new code for created rows;
   blank Wool-only LD rows carry their master code too).
4. **S7** alignment: rewrite both tabs via `align_grids` — one
   `clear()` + one `update()` per tab (`A1:M{n}` master / `A1:K{n}` LD).
5. `tools/migrate_v2.py audit` → must print ALIGNED.

## S5w — Widen ALL Local_Deals grid writers to 11 columns (code; run BEFORE any ingest/sweep can fire again)

**File:** `grocery-price-tracker/core/local_deals.py` — mechanical:
1. `TAB_COLUMNS` (~line 1062): append `("item_code", "Item_Code")` →
   `len(TAB_COLUMNS) == 10`; every width normalization
   (`len(TAB_COLUMNS) + 1`) becomes 11 automatically.
2. Every literal `range_name=f"A1:J{...}"` → `f"A1:K{...}"`
   (`grep -n 'A1:J' core/local_deals.py` must return ZERO at the end —
   expect ~5 sites: merge_store_tab, sweep_expired_specials,
   set_store_prices, repair_orphan_comments, rebuild_tab, plus any the
   grep finds).
3. Extend hardcoded blank-row literals (`"", "", …` of length 9/10) by
   one `""` (grep the 9-`""` literal; the inserted-rows code that uses
   `[""] * len(TAB_COLUMNS)` scales by itself — verify, don't touch).
4. `_load_master_rows` remap to the 13-col layout: name 0, category 1,
   size 2, wool_price 3, subcategory **10**; DROP `coles_price` from
   the returned dicts and delete the Coles arm of the standout compare
   (>20% vs raw D only — spec Q20). Grep `coles_price` and `r\[4\]` in
   the compare chain to catch every reader.

**Verify:**
```bash
"$USERPROFILE/anaconda3/python.exe" -m py_compile core/local_deals.py
grep -n "A1:J" core/local_deals.py          # MUST output nothing
"$USERPROFILE/anaconda3/python.exe" -m pytest tests/test_local_deals.py tests/test_cli.py -q
```

## S6 — Dispatch-disable retired v1 commands (one-line notice)

**File:** `grocery_price_cli.py` (parent root). One constant + one
intercept before the `args.func(args)` call in `main()` (locate the
dispatch anchor by grepping `args.func`):

```python
# v2 migration (Round 2): these paths read dead columns. Round 3
# deletes them; Round 4 rebuilds wednesday. Notice + exit 0.
RETIRED_V1 = {"compare", "optimize", "shop", "prefer", "recipe",
              "search", "rewards", "map", "todo", "add-to-list",
              "searched-items", "missed-pricing", "no-price",
              "lists", "unmapped", "specials-scan", "update",
              "sync", "wednesday", "backfill-keywords",
              "backfill-sizes", "backfill-subcategories",
              "backfill-codes", "backfill-home-brands",
              "subcategories", "live-refresh"}
# in main(), after parse_args, before args.func(args):
#   if getattr(args, "cmd", "") in RETIRED_V1:
#       print("[v2] retired by the migration — returns in Round 3/4; "
#             "the sheet is the source of truth until then")
#       return 0
```
Stays LIVE: `local-deals` (all flags), `specials`, `price`, `list`.
(Offline module tests of retired commands keep passing — modules are
untouched; only dispatch changes.)

**Verify:**
```bash
"$USERPROFILE/anaconda3/python.exe" grocery_price_cli.py compare --items "milk"   # notice, exit 0
"$USERPROFILE/anaconda3/python.exe" grocery_price_cli.py local-deals --help       # unchanged
"$USERPROFILE/anaconda3/python.exe" grocery_price_cli.py specials --store woolworths
```

## S7s — Keep `specials` alive (read-only remap)

**File:** `grocery-price-tracker/core/specials_reporter.py` — remap to
the 13-col layout: WW price D (3, unchanged), specials M(12) → **H(7)**,
rewards O(14) → **I(8)**; delete the Coles specials arm. Update its
tests' fixtures to the 13-col width (tests/test_specials_flags.py).

**Verify:** `pytest tests/test_specials_flags.py tests/test_telegram_format.py -q` + the live `specials` run above.

## S8 — Minimal v2 read path: `price` + `list`

**File:** `grocery-price-tracker/core/v2_read.py` (NEW):

```python
"""v2 sheet-only read path (spec §6/§8). ONE master read + ONE
Local_Deals read per command. Never writes. Never live-searches."""

def read_tabs() -> tuple[list[dict], list[dict]]:
    """master: {row, name, size, ww_raw, ww_num, keyword, specials,
    aliases, subcategory, code, gone (bool), na_marker (str|None)};
    ld: {row, name, prices: {shop_key: (float, 'special'|'permanent')},
    code} — special-first via core.local_deals.tab_store_price."""

def is_meat_query(query: str) -> bool          # core.halal.is_meat_term

def lookup_item(query: str, master_rows, ld_rows) -> dict:
    """Exact Col A / alias (col J) match, case-insensitive; a MEAT
    query resolves only through rows whose name contains 'halal'
    (spec §5); returns one result dict per the §8 table (tracked /
    gone / na_marker / missing-with-code / not-tracked / out-of-domain
    — lookup NEVER raises on a miss)."""

def missing_list(master_rows, ld_rows) -> list[dict]:
    """§6 rule: local side has ≥1 shop price AND D has no real price
    AND D != 'GONE' AND keyword col G empty → {code, name, best_local,
    shops}. Every entry carries its code."""

def render_lookup(result: dict) -> str    # style-LITE plain lines
def render_list(items: list[dict]) -> str  # '[CODE] name — best $X (shop)' lines + count
```

**File:** `grocery_price_cli.py` — two new subparsers (`price --item X`
required; `list`), thin handlers calling `v2_read` + printing the
render. One sheet read per tab per call (`list` budget ≤5s).

**Verify:**
```bash
"$USERPROFILE/anaconda3/python.exe" -m pytest tests/test_v2_read.py -q
"$USERPROFILE/anaconda3/python.exe" grocery_price_cli.py list
"$USERPROFILE/anaconda3/python.exe" grocery_price_cli.py price --item "halal beef mince"
```

## S9 — Parity audit utility (A2 semantics; Round 4 wires it into Wednesday)

**File:** `grocery-price-tracker/tools/parity_audit.py` (NEW):

```python
def audit(master_grid: list[list], ld_grid: list[list]) -> dict:
    """{'status': 'aligned' | 'bottom_append' | 'middle_insert',
    'misses': [row dicts], 'alert': str | None}.
    Pairs: master data row N (Item_Code col L, idx 11) ↔ LD row N+1
    (code col K, idx 10). Aligned → silence line. Extra rows at the END
    of either tab → 'bottom_append' + the rows (Round 4's Wednesday
    AUTO-MIRRORS those; this round only reports). A code break INSIDE
    the sequence → 'middle_insert' + alert VERBATIM (spec §18/A2):
    'row #N was inserted in the middle — move it to the bottom
    manually and run sync again to copy it over to the other sheet.'"""
```

**Verify:** `pytest tests/test_parity_audit.py -q` (all three statuses,
verbatim alert string) + live `tools/migrate_v2.py audit` → ALIGNED.

## S10 — Regression tests (mandatory, zero-skip, offline, grid fixtures)

1. `tests/test_migrate_v2.py` — stay/leave (incl. borderline +
   blank-subcategory rows), `drop_columns` exact header + index
   correctness, rename plan touches BUTCHERY only, new-row plan
   (prefix rule + code uniqueness, no I/L/O), `align_grids` (counts,
   per-position code pairing, blank-LD-row shape), `apply-*`
   idempotence on a FakeSheet (second run = zero changes).
2. `tests/test_local_deals.py` additions — **writer-width regression**
   (the col-K truncation trap): after EACH of `merge_store_tab`,
   `sweep_expired_specials`, `set_store_prices`,
   `repair_orphan_comments` writes, col-K codes survive intact (4
   tests minimum); standout is WW-only; `_load_master_rows` parses the
   13-col layout.
3. `tests/test_v2_read.py` — one test per §8 table row (9 cases) + §6
   list-rule cases (listed: blank D+G + local price; NOT listed: GONE,
   keyword-only, price-only, no-local-price) + meat-query halal
   scoping (plain non-halal meat row invisible to a meat query).
4. `tests/test_parity_audit.py` — as S9.

**Full suite:** expect **1319 + ~25 new, 0 failed, 0 skipped**:
```bash
"$USERPROFILE/anaconda3/python.exe" -m pytest tests/ -q
```

## S11 — Live acceptance + close-out

1. `tools/migrate_v2.py audit` → ALIGNED (print in the report).
2. `grocery_price_cli.py list` — eyeball vs the sheet; report the
   day-one count (expected ≤ ~105, spec §18/A1).
3. Three spot lookups: one meat term (e.g. `price --item "halal beef
   mince"`), one F&V, one archived name (expect the not-tracked /
   out-of-domain class of answer).
4. Final user eyeball of both tabs (gate-closing look — not a new gate).
5. Suite green → commits (tracker: tools/, core/, tests/, plan; parent:
   `grocery_price_cli.py`) → push → scp runtime files
   (`grocery_price_cli.py`, `core/local_deals.py`, `core/v2_read.py`,
   `core/specials_reporter.py`, `tools/migrate_v2.py`,
   `tools/parity_audit.py`) to the VPS mirror → md5-verify → report
   three-way sync status.

## Acceptance criteria (rebuild-plan Round 2)

1. Parity audit passes — row counts equal (offset +1), every
   Local_Deals row carries a resolvable code, every §6 list-rule case
   renders correctly.
2. Backup net untouched: pre-migration JSON present locally + VPS at
   close; S0 refreshed all three backup legs before any write.
3. User confirms G1/G2/G3 previews (rulings recorded in the report).
4. `price` + `list` answer from the live sheet (`list` ≤5s).
5. Full suite green, zero skips; three-way sync in sync.

## Rollback

The pre-migration JSON (complete 4-tab grid dump) is the restore
artifact. Restore is MANUAL by design (spec §3.4 philosophy — a wrong
automated restore is worse than a slow manual one): rewrite the tabs
from the JSON; the migration tool ships no `restore` subcommand.
