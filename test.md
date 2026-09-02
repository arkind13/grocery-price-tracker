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

---

# 03 Code — closeout session (2026-08-31)

State on entry: the entire `implementation-plan.md` (WP1–WP5, M1 fill
with `specials-wool = 206` / `weekly-lists = 208`, docs, VPS deploy +
gateway restart) was already committed (`058ee96`, `c468720`) and the
root `test.md` records the full per-step log. Remaining work this
session: live verification of the two D24 Telegram topics, the visual
architecture chart for README.md / read.me, and stale-doc fixes.

## Telegram live topic test (weekly-lists 208 + specials-wool 206)

Script: temp `tg_topic_test.py` — raw Bot API `sendMessage` per topic
(definitive ok + message_id), the production Wednesday helpers
(`_post_weekly_summary` / `_post_specials_report` with env unset so the
filled constants route), and resolver consistency checks. Bot token
loaded from `.env` via `core.sheets_client._load_env`; never printed.

| Result | Test | Command | Output / Error logs |
|--------|------|---------|---------------------|
| PASS | raw sendMessage specials-wool | `anaconda3\python.exe tg_topic_test.py` | `ok=True message_id=229` (thread 206) |
| PASS | raw sendMessage weekly-lists | same | `ok=True message_id=230` (thread 208) |
| PASS | production weekly path | same (`_post_weekly_summary`) | helper printed `Weekly-lists topic: OK`, `DM: OK` |
| PASS | production specials path | same (`_post_specials_report`) | helper printed `Specials Topic: OK`, `DM: OK` |
| PASS | resolver consistency | inline `thread_id_for` / `weekly_thread_id` | `206 / 208 / 208` |
| PASS | full suite re-run (post-doc changes) | `& "$env:USERPROFILE\anaconda3\python.exe" -m pytest grocery-price-tracker/tests/ -q` | `504 passed in 9.71s` |

Note: first script run hit a cosmetic `UnicodeEncodeError` (cp1252
console) printing the helper output's `→` char — after all checks had
already passed; resolvers were re-verified inline. No product code
involved.

Conclusion: **both channel groups are live and correctly routed.**
Nothing posts to retired thread 151.

## Docs — visual architecture chart + stale-fact fixes

- `README.md`: new section "How everything works — visual map
  (2026-08-31)" — colour-coded mermaid flowchart (user / Telegram
  topics / VPS / local / sheet / stores / GitHub) + a Wednesday
  sequence diagram. Also fixed stale facts: Wednesday-reminder delivery
  now documents `weekly-lists` (208) instead of retired 151; test total
  updated 446 → 504; folder listing test count updated.
- `read.me`: same two diagrams mirrored under "How the current system
  works — visual map (2026-08-31)", per user request.
- No product code touched; suite re-run green (504/0/0, see table).

---

# 04 Architect Checker — sync audit (2026-08-31, light check)

No arch/plan modes; scope: verify test.md claims + local/git/VPS sync.
No product code changed; suite green.

1. **test.md claims** — independent full-suite run: `504 passed in
   7.86s` (0 failed, 0 skipped). Matches the closeout record.
2. **Sync gaps found and fixed (tracker repo, 2 commits, pushed
   `b4dc191..5696ee5`)**:
   - `core/add_to_list.py` + `tests/test_add_to_list.py` were
     UNTRACKED while tracked code (`extractors/session_refresh.py`,
     `tests/test_cli.py`) imports the module — a fresh clone was
     broken. Now committed (d6be422).
   - Finish-line spec/plan (D23–D27+B4/B5), `pre-arch.md`,
     `PROJECT-MAP.md`, `old md/` archive, token xlsx v10 committed;
     `LEGACY_AUDIT.md` deletion committed with the stale README tree
     line removed (5696ee5).
   - `.gitignore` hardened: `data/ww_coles_profile_full/` (~1 GB
     browser profile with cookies — secret, never commit),
     `data/forget_list.json`, `data/price_unavailable.json` (runtime
     state from parent-repo Plan B modules).
3. **Parent repo** — M3 Plan B session (rounds 18–19: pc_agent chat
   waiters, visual_grocery open CLI, price_unavailable tracker,
   driver CDP refactor, userscript, README rewrite) + housekeeping
   committed (2 commits) and pushed (`6124b58..b1a0c39`), 25
   pre-existing unpushed commits included. `kilo.jsonc` (contains a
   live API key) gitignored, never committed.
4. **VPS** — MD5 comparison of all 24 deploy-manifest files found 5
   stale: `grocery_price_cli.py`, `SKILL.md`,
   `extractors/session_refresh.py`, tracker `README.md`, `.gitignore`.
   `deploy_vps.py` run: 24/24 scp OK, ONE `docker restart
   openclaw-core` (required — container code changed), smoke
   `searched-items show` OK. Re-verify: **ALL 24 FILES IN SYNC**;
   container Up.
5. **No lostbattle.md** — no unresolved failures; nothing to record
   there.

---

# 04 Architect Checker — lostbattle.md created (2026-08-31, user request)

The Plan A failure history IS a lost battle (user: "7 hours trying to
automate but was unsuccessful"). Recorded in
`grocery-price-tracker/lostbattle.md`:

- Campaign 0: cookie/API war (9 approaches, 2026-08-24 —
  `old md/COOKIE_INVESTIGATION.md`, archived from Development
  Workflow).
- Campaigns 1–7: Playwright login-refresh, chunked-typed-JS bridge,
  Tampermonkey+CDP, pyautogui/OpenCV, Ctrl+F match-cycling, stockcode
  direct PDP (the win), and the final click war (diff-clicker →
  false positives → WW 500s → round-17 surrender).
- Plan B (open-pages, human clicks) documented as the settled model.
- `create_env.py` (one-time conda helper, command-registry REMOVED)
  archived to `old md/` alongside it.

---

# 04 Architect Checker — Wednesday-run incident fixed (2026-09-02)

## Reported symptoms

1. "Step 8: Woolworths_Specials.docx not found — skipping specials
   report" although the docx existed and was freshly updated.
2. Searched-items queue showed 1 item (GDP milk) instead of the 3
   queued the day before (DAC/TXY/XCL); GDP itself "already in the
   sheet".
3. The expected Wednesday opening step — show the queued items so the
   user can add them to the store lists — never appeared.
4. User concern: docker restart/recreate wipes the queues (model
   changes in Claw trigger recreates).

## Root-cause findings (evidence-based)

1. **Stray nested CLI copy.** A copy of the CLI at
   `grocery-price-tracker/grocery_price_cli.py` (created 2026-09-01
   10:24 AM) made `_TRACKER` resolve to the phantom
   `grocery-price-tracker/grocery-price-tracker/`. The 2026-09-01
   20:52 UTC Wednesday run used that copy: Step 8 looked for the
   specials docx in the phantom folder (false "not found"; the real
   docx sat in the real folder, updated 20:50), Steps 4/6 wrote the
   list files into the phantom `data/` (files found there, 6:52 AM),
   Step 5 scp'd them on to the VPS (VPS mtimes 22:52 CEST match), and
   the six-list Telegram post read the LOCAL queue.
2. **Queue divergence, no wipe.** Docker recreate at 06:37 UTC did
   NOT wipe anything: all 3 VPS items were added AFTER the recreate
   and were still present on the VPS. GDP was added on the LOCAL
   machine 2026-08-31 08:31 UTC (local file creation time matches) and
   never reached the VPS — docx-mode Wednesday never pulled the VPS
   queues, and live-mode's old pull OVERWROTE local-only entries
   (latent data-loss bug). The bind-mounted `data/` survives
   container recreates by design.
3. **GDP "already in sheet"**: `search --add-item` had no
   duplicate guard — `add_product_row` appended blindly.

## Fixes

| Fix | File | What |
|-----|------|------|
| `_TRACKER` self-location guard | `grocery_price_cli.py` | a CLI copy inside the tracker folder resolves `_TRACKER` to the tracker itself (core/+extractors/ detection) |
| Step 8 error now prints the checked path | `grocery_price_cli.py` | future path mismatches diagnosable at a glance |
| Step 0 queue sync for BOTH modes | `grocery_price_cli.py` + new `core/queue_sync.py` | pull VPS queues → tombstone-aware UNION merge (nothing lost on either side, Claw-side removals respected) → push back so both sides are identical |
| Queues printed up front | `grocery_price_cli.py` | Step 0 shows searched/to-do queues + manual-add instruction (docx) / auto-flush note (live) — restores the expected "add items first, then doc sync" flow |
| Step 9 end-of-run mirror push | `grocery_price_cli.py` | live-window flush consumption propagates to the VPS (no resurrection at next merge) |
| Duplicate guard | `core/sheets_sync.py` | `add_product_row` refuses an exact Col A name match ("already tracked (row N) — use update/map") |
| Stray copies removed | local + VPS | nested CLI + phantom folder deleted; run outputs restored to the real `data/` |

## Tests

- New `tests/test_queue_sync.py` — 17 tests (union, earliest-identity,
  backfill, code-collision regeneration, tombstone union/drop,
  removal-not-resurrected, file IO round-trip, missing-remote side).
- New `tests/test_sheets_sync.py::TestAddProductRowDuplicateGuard` —
  3 tests (exact refusal, normalized refusal, new-name still appends).
- **Full suite: 575 passed, 0 failed** (local, Python 3.13).

## Verification (real, not mocked)

- `_sync_queues_with_vps` live run: local 1 + VPS 3 → merged 4 pushed
  both sides; md5 of `searched_items.json` identical local↔VPS
  (`a3c4d173…`); no `.vpspull` leftovers.
- `wednesday --dry-run --no-scp --no-telegram`: Step 0 shows all 4
  items + instruction; Step 8 parses **12 specials** from the docx
  (original error gone).
- Container: `python3 -m py_compile` OK (3.11) +
  `searched-items show` lists all 4 items from the merged queue.
- 5 files synced to the VPS, md5-verified on both sides.

## No lostbattle.md for this round

All defects fixed and verified; nothing unresolvable. (The earlier
`lostbattle.md` from 2026-08-31 is unrelated to this incident.)

---

# 04 Architect Checker — one-line rule + Wednesday workflow reorder (2026-09-02, round 2)

## User requirements

1. **One line per product.** Explicit adds kept creating duplicate
   sheet rows when names differed slightly (WW vs Coles wording,
   store-brand prefixes, word order). Default = 1 line; a second line
   only when the user explicitly says the items are different.
2. **Wednesday workflow.** First show the searched list and WAIT while
   the user adds those items to the store website lists and re-pastes
   the docx lists; only after "done" on the terminal: sync the docs,
   build the lists, auto-clear any searched items that now appear on
   the parsed lists, then specials.

## Fixes

| Fix | Where | What |
|-----|------|------|
| Similarity engine | `core/name_matcher.py` | `similarity_tokens` (lowercase tokens, apostrophes collapsed, store-brand words dropped) + `token_set_ratio` (order-insensitive Jaccard); `DUP_SIMILARITY_THRESHOLD = 0.9` |
| One-line rule | `core/sheets_sync.py::add_product_row` | similar existing row (ratio >= 0.9) gets the price UPDATED (via `update_single_price`) + alias appended to its Col P (`_append_alias`, pipe-delimited, deduped) — NO second row; returns `merged: True`. `allow_duplicate=True` forces a separate row; exact-name duplicates always refused |
| CLI surfaces | `grocery_price_cli.py` | `search --allow-duplicate` flag; both add paths (`_search_add_item`, `_add_from_live_search`) print "1 line kept, not queued" on merge and queue ONLY genuinely new rows |
| Workflow pause | `grocery_price_cli.py::_wait_for_manual_adds` | docx-mode TTY-only input() gate: "add the searched items → paste the lists → type done"; `--no-prompt` flag; auto-skips for Claw/CI (no TTY) and live mode |
| Step 1b drain | `core/searched_items.py::drain_from_parsed` | after the lists are parsed, queued items whose store list now contains them (exact-normalized or ratio >= 0.75) are consumed + tombstoned; skipped on dry-run |

## Tests

- 17 new: merge behaviour (7 in `TestAddProductRowOneLineRule`),
  similarity helpers (5), drain (6 in `DrainFromParsedTestCase`
  incl. different-size NOT drained + other-store NOT drained).
- Fixed: CLI-9 harness mock now returns a realistic
  `{"wrote": True, "merged": False}` dict (the merged-first branch
  misread the old MagicMock); one test seed row had 15 cols (put
  "hommus" in Col O) — now 16.
- **Full suite: 592 passed, 0 failed.**

## Verification

- Dry-run of `wednesday`: Step 0 shows the 3 queued items + the
  manual-add instruction; Step 1b reported skipped (dry-run) ✓.
- Read-only drain preview against today's docx: all 3 queued items
  correctly "not on list yet" (user has not added them yet) — no
  false positives from the 0.75 threshold.
- 7 files synced to VPS, md5-identical, container py_compile OK.

## No lostbattle.md for this round

Both requirements implemented and verified.

---

# 04 Architect Checker — one-line rule v2 + no-price list (2026-09-02, round 3)

## User refinements

1. **5-pack vs 70g was the SAME product** (stores word it differently).
   Rule v2: same product = ONE line ALWAYS; the ONLY keep-apart reason
   is the same unit with a different amount (200g vs 400g, 1L vs 2L).
   The built-in 20% size tolerance stays: 33g vs 35g still matches.
2. **Drop the confusing docx instruction line** ("remove their codes
   …") — Step 1b auto-clears matched items; unmatched simply stay.
3. **No-price list** (requested 2026-09-01, never built — no trace in
   any session or the codebase; built now): a 7th weekly-lists post
   tracking rows with no usable price and for how many weeks.

## Implementation

| Change | Where | What |
|--------|-------|------|
| `split_name_size` + `is_same_product` | `core/name_matcher.py` | splits a name into body tokens + last parseable size (uom.parse_size, multipacks totalled); SAME product iff body ratio >= 0.9 AND NOT (both sizes same family AND beyond 20%) — pack-vs-weight, g-vs-mL, and missing-size all merge; A2-vs-store-brand body tokens stay apart |
| `add_product_row` + `drain_from_parsed` | core | both use `is_same_product` (one canonical rule) |
| Step 0 output | CLI | docx branch prints only the queue (no manual-steps line — the pause prompt right after explains them) |
| `_is_priceless_cell` | CLI | a cell HAS a price only when it parses to a number > 0; blank / 0 / $0 / "price unavailable" / "N/A" / any non-number text = price-less |
| `_weeks_without_price` | CLI | whole weeks since Col H stamp ("new" < 1w, "?" unparseable) |
| Step 4d | CLI | no-price rows collected during the existing sheet scan; count line in the summary + ("No-price items", …) resolve list → weekly-lists topic (7 lists now) |

## Tests

- 13 new: `TestIsSameProduct` (7: pack-vs-weight merge, same-unit-
  different-amount apart, 33g/35g within-20% merge, brand apart,
  missing-size merge, blank, g-vs-mL merge), pack-vs-weight add merge
  (Carman's incident), drain pack-vs-weight + same-unit-apart
  rewrite, `TestNoPriceHelpers` (price-less cells, priced cells,
  week buckets).
- **Full suite: 605 passed, 0 failed.**

## Verification

- Dry-run: Step 0 shows only the queue (confusing line gone).
- Live sheet preview with the real logic: **0 no-price rows** (all 85
  rows carry at least one price) — tonight's post shows
  "No-price items: none" until a real candidate appears.
- Sheet spot-check: Carman's = ONE row (both prices + both keywords),
  falafel = one row — no duplicate cleanup needed.
- 7 files synced to VPS, md5-identical, container py_compile OK.

## No lostbattle.md for this round

All three refinements implemented and verified.

---

# 04 Architect Checker — sync overwrite semantics (2026-09-02, round 4)

## User spec (confirmed via Q&A before implementing)

1. Full lists are always pasted (Wool + Coles; Aldi out of scope) →
   absence from a list = not found.
2. Cell markers: not found → `N/A 2026-09-02`; listed but site shows
   no price/blank → `unavailable 2026-09-02`; listed at $0 → `0`;
   returning real price overwrites any marker.
3. No new Telegram lists; one-store drops are visible only in the
   sheet (ad-hoc Claw questions). No-price report shows ONLY rows
   where NEITHER store has a usable price, categorized: N/A /
   Unavailable / $0 / Blank / Other, each with human week count
   ("3 weeks"), oldest first. Weeks start from the first marking run.

## Implementation

| Change | Where | What |
|--------|-------|------|
| Listed-but-priceless | `sync_prices` item loop | price 0/None → cell `unavailable <date>` (stale price never kept) |
| Not-found pass | `sync_prices` after the loop | per PROVIDED store: mapped row (keyword present, not literal "NA") absent from the list → cell `N/A <date>` |
| Safety | `sync_prices` | a store with zero parsed items (parse failure / not pasted) is "not provided" — no marking for it, warning recorded |
| Anchor preservation | `_build_marker` | an existing embedded date is kept across marker rewrites — week aging never resets while price-less |
| Report | `SyncReport` + CLI Step 3/7 | `unavailable_written` / `notfound_written` counts + names, summary kv lines |
| No-price categorization | CLI `_cell_price_category` + `_noprice_line` + sort | severity N/A > Unavailable > $0 > Other > Blank; oldest embedded date wins; "(3 weeks)"/"(1 week)"/"(new)" human labels |

## Tests

- 16 new: `TestSyncOverwriteSemantics` (9 — marking, stale-price
  replacement, NA/blank-kw immunity, store-not-provided immunity,
  anchor preservation, returning price, one-store drop) +
  `TestNoPriceReportLines` (7 — categories, severity, singular/plural
  weeks, Col H fallback, new marker).
- **Full suite: 621 passed, 0 failed.**

## Verification

- Real dry-run against today's pasted lists + live sheet:
  matched=98, would mark unavailable=0, **not-found N/A=50** — the
  stale prices from long-removed items, exactly what the user
  reported; tonight's first run anchors them all at 2026-09-02.
- 4 files synced to VPS, md5-identical, container py_compile OK.

## No lostbattle.md for this round

Implemented and verified per the confirmed spec.

---

# 04 Architect Checker — map-session + unmatched-debt fixes (2026-09-02, round 5)

## User-reported symptoms (real Telegram session)

1. Session started at Item 2/45 — item 1 vanished; first call failed.
2. "Woolworths Beef Mince 500g [coles]" sat in unmatched although the
   sheet HAS that exact row (83) with a Coles price — then `add`
   failed ("already tracked") and the agent spent 7 messages on
   archaeology. Item 2 alone took ~10 minutes of 45.
3. Junk lines in the list ("Totally Unknown Product 999g [aldi]",
   "Ends 7 Jul.", "Add to cart", "Freezer").
4. "Why didn't 650g pair with 500g?" — 30% apart, correctly outside
   the 20% band (user's own rule); candidates shown for their pick.

## Root causes found (evidence-based)

| # | Cause | Evidence |
|---|-------|----------|
| 1 | **Unmatched is a PERSISTENT debt queue** (`unmapped_queue.json`), accumulating every week's misses; only manual resolving shrank it | `get_pending_mappings` reads the queue; upsert-increment on every weekly miss |
| 2 | **Keyword-only matching**: explicit adds write prices with EMPTY keywords by design; rows with exact Col A names re-queue forever | row 83: price present, Col J empty |
| 3 | **Aldi items garbage-searched** in the resolver (no aldi live search exists) | item 1 live-search returned lip balm/scent booster matches |
| 4 | Junk lines are paste pollution, ALREADY filtered by doc_parser (`_is_ignore_line` covers "ends ", "add to cart") — they only linger via the debt queue | parse of real docx now yields zero junk |
| 5 | The debt queue was never synced to the VPS — Claw's view stayed stale after local runs resolved debt | Step 5 scped only the 3 rendered lists |

## Fixes

| Fix | Where |
|-----|------|
| **Step 1c auto-heal** — parsed item whose name EXACTLY matches a Col A row with an empty store keyword gets the keyword SET before matching; Step 2 then matches + syncs it normally (never becomes manual work) | `_autoheal_exact_keywords` + Wednesday Step 1c |
| **Debt auto-clear** — queue entries whose keyword now exists are auto-resolved at Step 4a (idempotent, dry-run-safe) | Step 4a-i using `load_keyword_index().lookup` + `clear_resolved` |
| **One-step exact link** — map `--add` on an exact/alias hit sets the store keyword and advances (no more "already tracked" dead-end); the resolver prints "reply 'add' to link the {store} keyword" with the row number | `_resolve_and_print_unmatched` + `--add` path |
| **Aldi guard** — non-wool/coles items print "cannot be live-searched; --pick / --forget / --skip" instead of garbage searches | `_resolve_and_print_unmatched` |
| **Debt queue synced** — `unmapped_queue.json` scps to the VPS with the lists so Claw's sessions see resolved debt | Step 5 file set |

## Verification (real, not mocked)

- **625 unit tests pass** (+4 auto-heal tests).
- Real dry-run against the live sheet + tonight's pasted lists:
  Step 1c found **2 genuine auto-heals** (Yumi's Herb Falafel 200g,
  Woolworths Greek Style Fetta 200g — both keyword-less rows that
  would have re-queued) and Step 4a auto-cleared **1 debt item**
  (beef mince, keyword set by Claw at 9:01) — 45 → 44 with 2 more
  heals pending in dry-run form.
- Real `map unmatched --next`: aldi junk item now prints the clean
  guidance block (no garbage live search).
- Container: py_compile OK, `map status` works; CLI + tests md5-matched
  on both sides.

## Expected effect on the next real run

45 → ~30s: junk (4 forgotten tonight) excluded via the updated ignored
file, 2+ auto-heals, resolved debt cleared. Remaining items are
genuinely new products needing one reply each (exact-hit items now
resolve with a single `add`).

## No lostbattle.md for this round

All five root causes fixed and verified against real data.

---

# 04 Architect Checker — specials name cutoff + one-reply picks (2026-09-02, round 6)

## User reports

1. **"add" on a pick left prices unwritten** — old debt entries carry no
   price, and the debt queue file never existed on the VPS, so VPS picks
   could never write prices (Twisted row 64: keywords saved, price not).
2. **Specials list names cut off** ("Tamar Valley Dairy Yoghurt Ma…")
   — every list render truncated names to 30 chars.

## Fixes

- `map --pick` is now a COMPLETE resolution: alias + store keyword +
  price written immediately (from the debt entry's stored price) + debt
  entry cleared, all in one reply.
- Debt queue carries prices: new entries store them at queue time
  (append + increment both refresh), and Wednesday Step 4a enriches
  every remaining debt entry with tonight's parsed prices
  (`refresh_pending_prices`) before pushing the queue to the VPS with
  the lists (Step 5 file set extended).
- Immediate relief for the live session: 32 debt entries enriched from
  tonight's parse and pushed to the VPS (verified: 31 of 45 pending
  carry prices in the container).
- Row 64 price verified correct ($9.50 — tonight's WW price equalled
  the old one; the N/A the user saw is the Coles cell, resolved when
  the pending Coles item at line 31 is picked, price $8.50 now stored).
- All product-name truncations removed (specials live scan, savings,
  only-at, rewards, unmapped render, search results, backfill plans,
  specials-scan) + a "+N more" notice for the live-scan 25 cap. During
  the edit a PowerShell regex rewrite corrupted the CLI's UTF-8
  (mojibake) — restored from the VPS copy and re-applied the edits with
  the encoding-safe editor; suite green after.

## Verification

- **625 tests pass** (twice, plus the idempotency test in isolation —
  one flaky temp-dir run).
- Specials re-run in the container with FULL names and delivered to the
  user's Telegram DM (message part 1 OK; the container's live
  saved-list scan is 403-blocked by site bot protection as documented —
  the sheet-based specials with tonight's flags is what posted).
- CLI deployed + hash-verified on both machines; container compiles.

## No lostbattle.md for this round

Both user-visible defects fixed and verified live.
