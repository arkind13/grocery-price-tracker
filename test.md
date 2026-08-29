# test.md — UOM + live-window implementation (03 Code Agent, 2026-08-29)

Result log for every test matrix in `implementation-plan.md` (§7), plus
the full-suite gate, deploy evidence, and the documented pre-existing
failures. All tests run offline (mocked stores, temp files, no browser).

## Environment

- Python: 3.13.9 (local); container/VPS target: 3.11.2 (multiline
  f-string incompatibility found and fixed, see Deployment)
- Run command: `C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe -m
  pytest grocery-price-tracker/tests/ -q` (from `AI related\`)
- Baseline (pre-change, tag `pre-live-trial`): 274 collected — 266
  passed, 8 failed (pre-existing Phase-1 drift, see "Pre-existing
  failures" below)
- Final: **446 collected — 438 passed, 8 failed (same pre-existing 8),
  0 skips. 172 new tests, all green.**

## Matrix U — core/uom.py + tests/test_uom.py (24 tests)

| ID | Case | Status |
|----|------|--------|
| U-1 | 25L → 25000 mL, volume | PASS |
| U-2 | 600mL case/space variants | PASS |
| U-3 | 180g weight | PASS |
| U-4 | 1.2kg → 1200 g | PASS |
| U-5 | 10m / 50cm lengths | PASS |
| U-6 | "1 each" count | PASS |
| U-7 | "6 x 170g" multipack → 1020 g | PASS |
| U-8 | "2 x 1L" multipack → 2000 mL | PASS |
| U-9 | unparseable → None | PASS |
| U-10 | family matching incl. None | PASS |
| U-11 | exactly 20% passes | PASS |
| U-12 | 20.1% fails | PASS |
| U-13 | identical sizes SAME | PASS |
| U-14 | within tolerance TOLERANT | PASS |
| U-15 | beyond → beyond_20pct | PASS |
| U-16 | family mismatch | PASS |
| U-17 | missing size → missing_size | PASS |
| U-18 | multipack vs single tolerant | PASS |
| U-19 | count vs volume mismatch | PASS |
| U-20 | parse idempotent on canonical | PASS |
| U-21 | 0.75L → 750 mL | PASS |
| U-22 | family constants + Verdict strings | PASS |
| U-23 | compare symmetric | PASS |
| U-24 | 20 curated real sizes sweep | PASS |

File: `tests/test_uom.py` — **24/24 PASS**

## Matrix S — core/searched_items.py + tests/test_searched_items.py (30 tests)

| ID | Case | Status |
|----|------|--------|
| S-1 | missing file → [] | PASS |
| S-2 | corrupt JSON → [] | PASS |
| S-3 | exact entry fields + UTC added_at | PASS |
| S-4 | dup guard (normalised) | PASS |
| S-5 | same generic other store appends | PASS |
| S-6 | invalid inputs raise, file untouched | PASS |
| S-7 | 3-letter code, A–Z minus I/O | PASS |
| S-8 | no repeated letter (200 codes) | PASS |
| S-9 | unique vs queue | PASS |
| S-10 | unique vs live tombstones | PASS |
| S-11 | expired tombstone reusable | PASS |
| S-12 | remove by code | PASS |
| S-13 | comma-separated removal | PASS |
| S-14 | case-insensitive codes | PASS |
| S-15 | unknown code exact error | PASS |
| S-16 | all-or-nothing removal | PASS |
| S-17 | tombstones written | PASS |
| S-18 | clear_all empties + tombstones | PASS |
| S-19 | render format + empty line | PASS |
| S-20 | Coles-first ordering | PASS |
| S-21 | consume_entries flush path | PASS |
| S-22 | atomic temp cleanup on failure | PASS |
| S-23 | since_label | PASS |
| S-24 | deterministic rng | PASS |
| S-25 | remove→re-add new code | PASS |
| S-26 | corrupt tombstones → [] | PASS |
| S-27 | queue readable encoding/indent | PASS |
| S-28 | insertion order preserved | PASS |
| S-29 | parse_codes_arg | PASS |
| S-30 | no env/network import side effects | PASS |

File: `tests/test_searched_items.py` — **30/30 PASS**

## Matrix C — Coles Scrape.do credit guard + tests/test_coles_recipe.py (19 tests)

| ID | Case | Status |
|----|------|--------|
| C-1 | params super/geoCode/session/token | PASS |
| C-2 | no render/country/wait | PASS |
| C-3 | unique sessions per call | PASS |
| C-4 | 5xx → new-session retry → success | PASS |
| C-5 | backoff exactly [3, 6] | PASS |
| C-6 | 3 attempts → unavailable | PASS |
| C-7 | 401 never retried | PASS |
| C-8 | 403 never retried | PASS |
| C-9 | RequestException retries like 5xx | PASS |
| C-10 | breaker opens after 3 failed chains; 0 HTTP after | PASS |
| C-11 | breaker closes after cooldown (601 s) | PASS |
| C-12 | success resets streak | PASS |
| C-13 | per-run cap → cap_exceeded + message, no HTTP | PASS |
| C-14 | __NEXT_DATA__ fixture parse (price/special/size/id) | PASS |
| C-15 | legacy fetch_coles_search plain list | PASS |
| C-15b | empty result set → "empty" (IN-1) | PASS |
| C-16 | corrupt health file treated healthy | PASS |
| +  | WW Stockcode/ArticleId probe (IN-6) | PASS |
| +  | Coles id/productId/_id probe variants | PASS |

File: `tests/test_coles_recipe.py` — **19/19 PASS**

## Matrix L — lookup Step 5 + tests/test_lookup_uom.py (18 tests)

| ID | Case | Status |
|----|------|--------|
| L-1 | ranking deterministic (shuffles) | PASS |
| L-2 | ranking never rejects | PASS |
| L-3 | singular/plural normalised | PASS |
| L-4 | difflib typo tolerance | PASS |
| L-5 | top-ranked pair when UOM passes | PASS |
| L-6 | next-ranked used when top fails | PASS |
| L-7 | no pair → closest + reason | PASS |
| L-8 | 10× sanity ceiling preferred | PASS |
| L-9 | no 10× pair → first passing | PASS |
| L-10 | Seasol regression: no prices, found-block | PASS |
| L-11 | 25L vs 30L pair chosen | PASS |
| L-12 | store empty → no prices, closest (IN-1) | PASS |
| L-13 | coles unavailable → WW-only + store_unavailable | PASS |
| L-14 | breaker/cap behave like unavailable | PASS |
| L-15 | chosen pair prepended to live_items (IN-4) | PASS |
| L-16 | matched_names/sizes from chosen pair | PASS |
| L-17 | sheet hits populate matched fields | PASS |
| L-18 | Steps 1–4 golden regression | PASS |

File: `tests/test_lookup_uom.py` — **18/18 PASS**
(`tests/test_lookup.py` scenarios 9–11 edited per guardrail 11 — spec
B2/IN-5; `tests/test_live_search.py` untouched and green.)

## Matrix P — comparator + tests/test_comparator.py additions (14 tests)

| ID | Case | Status |
|----|------|--------|
| P-1 | live line " — name size (live)" | PASS |
| P-2 | sheet line "(sheet)" tag | PASS |
| P-3 | found-block EXACT §3.3 wording | PASS |
| P-4 | non-comparable excluded from totals | PASS |
| P-5 | non-comparable never wins 🏆 | PASS |
| P-6 | WW-only + "⚠️ Coles not checked (unavailable)" | PASS |
| P-7 | sheet-vs-sheet golden (never gated) | PASS |
| P-8 | sheet-vs-live mix not gated | PASS |
| P-9 | both-live gated in auto | PASS |
| P-10 | --mode live routes through gate | PASS |
| P-11 | home-brand rebuild carries new fields | PASS |
| P-12 | totals math golden | PASS |
| P-13 | no prices + no closest → existing rendering | PASS |
| P-14 | no per-unit strings anywhere | PASS |

File: `tests/test_comparator.py` (class TestUomReportMatrix) —
**14/14 PASS** (28 pre-existing comparator tests: 6 edited under
guardrail 11, clause IN-1/IN-3/IN-5 — listed in the final report.)

## Matrices CLI — tests/test_cli.py additions (16 + 12 tests)

CLI-1..CLI-16 (search display/add-item, searched-items management,
Queue-1 vs Queue-2 separation) and WC-1..WC-12 (wednesday docx golden,
live routing, clean stop, Step-0 scp pull/pull-failure, window skip,
dry-run flush skip, live specials, Telegram live summary + flush
failures): **28/28 PASS**. Files: `tests/test_cli.py` (classes
`TestCLIPartB`, `TestWednesdayLiveRouting`). 5 pre-existing search
tests updated under guardrail 11 (clause IN-5/§4.8-2 — patch target
swapped to `fetch_coles_search_status`; 1 fixture given sizes per
IN-3; 2 converted to found-block assertions per IN-1).

## Matrix F+W+D — tests/test_live_window.py (38 tests)

F-1..F-10 (snapshot conversion, specials semantics, dedup, quantity,
offline, validate_complete naming files): **10/10 PASS**
W-1..W-20 (pagination walker, flush grouping/success/failure/3-strike/
session-death/retry/throttle/log+rotation, exact list match, phase
independence + flags, heartbeat, no-scrapedo grep, lazy playwright,
discovery capture): **20/20 PASS**
D-1..D-7 (manifest purity, scp→restart→smoke order, failure retry
hint, git-mode fallback, heartbeat entry exits 0, compare-lists
mismatch/pass, arg-list-only subprocess): **8/8 PASS** (D-3 split into
D-3/D-3b)

## Full-suite gate (Task 12)

Command: `C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe -m pytest
grocery-price-tracker/tests/ -q`
Result: **8 failed, 438 passed** (446 total; same 8 pre-existing
failures as baseline; 0 new failures; 0 skips)

## Deployment evidence (Task 12b)

- `python scripts/deploy_vps.py` — **24/24 files OK** (prep of remote
  dirs via ssh sudo mkdir/chown/u+w, then per-file scp, then ONE
  `ssh … docker restart openclaw-core` = OK)
- Container smoke: `docker exec openclaw-core python3
  /app/tasks/ai-tools/grocery_price_cli.py searched-items show` →
  `searched_items is empty ✅`, exit 0
- schtasks registered: `grocery-session-heartbeat` (every 6 h per plan
  A-4 — 04 Checker re-registered; 03 had used hourly, Ready,
  command = anaconda python + scripts/session_heartbeat_entry.py)
- Heartbeat live run: `woolworths: alive`, `coles: unknown`, exit 0

## Pre-existing failures (resolved by 04 Checker — see bottom section)

All 8 were stale Phase-1 tests in `tests/test_extractors.py`, failing
identically at baseline (both files unchanged since commit `0942f81`):

1. `TestSessionManager::test_get_headers_no_cookie` — environment-
   dependent: passes only when no local cookie file exists; the session
   manager loads real cookies from disk.
2. `TestWoolworthsExtractor::test_parse_api_item` (+ alternate_keys,
   empty_name, no_price) — imports `_parse_api_item`, which no longer
   exists (refactored to `_parse_product_detail` in Phase 1).
3. `TestColesExtractor::test_parse_search_result` (+ no_product_wrapper,
   with_badges) — fixtures wrap payloads in `{"product": ...}` and use
   keys the parser never unwrapped; current `_parse_search_result`
   (and its committed callers) consume raw product dicts.

Per the plan ("do NOT fix, do NOT skip — record"), 03 Code left them
untouched and handed them to 04 Checker with this note.

## 04 Architect Checker audit (2026-08-29)

**Verdict: PASS.** All spec §8 acceptance criteria verified; the 8
handed-over failures were repaired and the suite is now fully green.

Audit performed:

1. **Independent full-suite run** — confirmed the 03 Code result
   (438 passed / 8 failed) before any checker changes.
2. **File boundaries (spec §6, plan §2)** — `git diff pre-live-trial..HEAD`:
   23 files, all within the authorised create/edit lists (+ the two
   flagged micro-exceptions IN-6 `models.py` 4 lines / WW probe 4 lines,
   IN-7 new test file). No frozen file touched: `core/sheets_sync.py`,
   `core/name_matcher.py`, `core/add_to_list.py`,
   `core/missing_items_tracker.py`, docx parsers, `telegram_gateway/`,
   `core/woolworths_discounts.py`, `core/telegram_format.py`, `.env`,
   no `.docx` — all absent from the diff. Parent repo touched only
   `grocery_price_cli.py` + `claw-skills/grocery-price/SKILL.md`.
3. **Guardrail greps** — no `scrape.do` reference in
   `session_refresh.py` / `live_list_fetch.py` (guardrail 5); no
   per-unit price strings in `price_comparator.py` (guardrail 1);
   `store_keyword=""` on both new add paths (guardrail 2 / 0.4); the
   only `set_store_keyword` caller is the pre-existing `map --keyword`
   flow (unchanged).
4. **Automation evidence** — `pre-live-trial` tag present; 14-task
   commit cadence in both repos; `schtasks /Query` shows
   `grocery-session-heartbeat` Ready; deploy table + container smoke
   recorded above.
5. **Exact-wording tests** — found-block §3.3, B4.3 line, §3.4
   management phrases, S-15 unknown-code error, WC-4 §5.2 stop message
   (exit 1 + `sync_prices` never called + manual docx steps) all
   asserted in the suite.

**Defects found and fixed by 04 Checker:**

1. **The 8 stale `test_extractors.py` tests** (handed over above) —
   tests were asserting a Phase-1-era API; the shipped code is proven
   by 438 passing tests and was NOT changed. Fixes:
   - `test_get_headers_no_cookie` made hermetic (temporarily clears
     `WOOLWORTHS_COOKIE`, same save/restore pattern as the sibling
     `test_get_headers_with_cookie`).
   - WW tests rewritten against `_parse_product_detail` (current keys
     `IsOnSpecial`/`WasPrice`/`PackageSize`/`IsAvailable`; the old
     `productName`/`sellPrice` alternate-key test became a
     DisplayName/unavailable-price test matching the current contract).
   - Coles tests rewritten against raw product dicts (no
     `{"product": ...}` wrapper; `pricing.was`/`promotionType` specials
     detection; `product_id` probe now asserted).
2. **SKILL.md missing the ≥90 s tool-call timeout rule** (spec §3.5.6 /
   plan §7.10 first bullet) — the file still said "10–30 s" from before
   the Scrape.do recipe landed. Replaced with the mandated ≥ 90 s rule
   for `compare` / `search` / `recipe`.

3. **`deploy_vps.py` smoke path bug** — `CLI_IN_CONTAINER` pointed at
   the VPS host path (`/home/ubuntu/openclaw/tasks/ai-tools/…`) but the
   smoke runs `docker exec` INSIDE openclaw-core, which mounts the tree
   at `/app/tasks/ai-tools/`. First checker re-deploy failed the smoke
   with "No such file or directory". Fixed the constant to
   `/app/tasks/ai-tools/grocery_price_cli.py`; matrix D (8/8) still
   green; re-deploy verified end-to-end: restart OK, container smoke
   `searched_items is empty ✅`, exit 0.

**Final suite (after checker fixes):**
`446 passed, 0 failed, 0 skipped` —
`C:\Users\USER~1.DES\anaconda3\python.exe -m pytest grocery-price-tracker/tests/ -q`
