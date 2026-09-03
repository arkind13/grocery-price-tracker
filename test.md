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

## Round: Smart Basket optimizer (B2 / R17) — 2026-09-03

Spec: `architecture-spec.md` (workspace root). New:
`core/basket_optimizer.py` (+ `optimize` CLI subcommand + skill
routing). Baseline before the round: 641 passed (the spec's "621" was
stale — verified 2026-09-03).

### Matrix OPT — core/basket_optimizer.py + tests/test_optimizer.py (28 tests)

| ID | Case | Status |
|----|------|--------|
| G-1..G-5 | gate 0/2/4 items refused without comparator call; 5 proceeds; parsing parity | PASS |
| A-1 | split wins: assignment, subtotals, split_total, Σ gaps | PASS |
| A-2 | negation regression (user rule 2026-09-02): +$10/−$10 → savings $20, split | PASS |
| A-3 | sub-threshold movement → one_trip woolworths (even when Coles is the cheaper cart) | PASS |
| A-4 | boundary: Σ gaps == threshold → one_trip (strictly greater required) | PASS |
| A-5 | degenerate guard: all-WW assignment → one_trip despite Σ gaps 20 | PASS |
| A-6 | WW incomplete + sub-threshold → forced_split; single-store items add no gap | PASS |
| A-7 | min_saving override respected | PASS |
| A-8 | home-brand effective price = discounted_woolworths_price()["final"]; gaps on discounted prices | PASS |
| A-9..A-15 | raw basis off-switch; tie→WW; unpriceable; WW-prices-nothing→one Coles trip; none; warnings/not_available relay; 2dp rounding | PASS |
| F-1..F-4 | one_trip / split / forced_split / unpriceable+reminder output shapes (Style Kit, no markdown tables, no "(was") | PASS |
| F-5..F-8 | gate exit 2 on stderr; success exit 0; sheet-only has no 💬 reminder; constants pinned to CLI default | PASS |

### Full-suite gate

641 → 669 collected; 669 passed, 0 failed, 0 skipped.

### Deviation note (A-11, plan-internal bug — fixed by 03 Code)

The plan's S18 quoted test A-11 with `self.assertEqual(r.split_total,
2.00)` for a 1-priceable + 1-unpriceable basket. That contradicts the
plan's own locked design: §1.1 step 5's degenerate guard makes this a
`one_trip`, and §1.1 step 7 (and sibling test A-5, which pins
`split_total == 0.0` with a nonzero subtotal) mandate
`split_total = 0.0` for one_trip. The module code (S6–S9, verbatim) is
correct; the A-11 assertion was the bug. Fix: assert
`split_total == 0.0` AND `assignments[0].subtotal == 2.00` (ghost in
NO total — the test's stated intent, master-register §7 "excluded from
totals"). No production code was changed for this.

### Verification commands (local)

- `anaconda3\python.exe -m pytest grocery-price-tracker/tests/ -q` → 669 passed (baseline was 641 passed)
- `anaconda3\python.exe grocery_price_cli.py optimize --items "milk, eggs"` → exit 2 + refusal on stderr
- `anaconda3\python.exe -c "…optimize_basket('milk, eggs')…"` gate smoke → `False none` + refusal message
- `python skills_doc.py --check` → OK

### Local acceptance (S27, 2026-09-03)

| # | Command | Result |
|---|---------|--------|
| 1 | `optimize --items "milk, eggs, bread, beef mince, apples, rice"` | PASS — 🧠 header, ✅ SPLIT SHOP — SAVE $3.39, store blocks, 📊 PLAN fence, ⚠️ unpriceable block (bread, beef mince), 💬 reminder; exit 0 |
| 2 | `optimize --items "milk, eggs"` | PASS — refusal on stderr ("at least 5 items (got 2)… run: compare --items"), exit 2 |
| 3 | `pytest grocery-price-tracker/tests/ -q` | PASS — 669 passed, 0 failed, 0 skipped |
| 4 | `python skills_doc.py --check` | PASS — OK |

**Environment note:** local piped runs of the emoji CLI need the house
convention `$env:PYTHONIOENCODING="utf-8"` (workspace README §10) —
without it Python's charmap stdout raises
`UnicodeEncodeError: \U0001f9e0` on the 🧠 header (strict errors on
piped stdout). Interactive consoles are unaffected; no code change.

### VPS deploy (S28, 2026-09-03, after user confirmed S27 green)

- scp'd `grocery_price_cli.py`, `core/basket_optimizer.py`,
  `SKILL.md`, `claw_skills_easy.md` → `myvps:/home/ubuntu/openclaw/
  tasks/ai-tools/…` (live bind-mount, no container restart).
- MD5 verified identical on both sides for all four files.
- Container smoke 1: `optimize --items 'milk, eggs'` → refusal line +
  exit 2. PASS.
- Container smoke 2: `optimize --items 'milk, eggs, bread, beef mince,
  apples, rice'` → ⚠️ forced-split plan (a transient Sheets 503 on
  'milk' was degraded per design — item relayed as unpriceable, exit
  0). PASS.
- §6.3 Telegram agent turn (8-item list) prepared for the user; commit
  (§6.4) deferred until the user asks.

### Format revision (user-directed, 2026-09-03, same round)

User rules (2026-09-03): (1) sub-threshold one-trip plans show the
winning store only, with the savings note at the BOTTOM ("Splitting
would only save $2.50 — showing Woolworths only."); (2) split plans
show numbered buy-lists per store (`N. item — $price`, continuous
numbering, per-item price at the assigned store ONLY — no cross-store
per-item pricing) with 💵 subtotals and a `💰 Total savings this trip`
line; PLAN fenced box removed.

Changes: `core/basket_optimizer.py` only (StoreAssignment + item_prices
parallel list; _assign/_build_report fill it; _store_lines numbered
priced blocks; _one_trip_reason bottom-note phrasing; format_plan new
layout; _plan_rows + fenced_table import removed). Output docs
(SKILL.md row, README §5) remain accurate — no wording change needed,
no catalogue regen.

| Check | Result |
|-------|--------|
| optimizer tests (F-1..F-3 rewritten to pin new shapes) | PASS — 28/28 |
| full suite | PASS — 669 passed, 0 skipped |
| local live run (6 items, forced_split) | PASS — numbered blocks, 💵 subtotals, 💰 line, exit 0 |
| scp basket_optimizer.py + md5 both sides | PASS — `0BC39356…4B5` |
| container smoke (6 items, split) | PASS — new format, exit 0 |

### UX fix round (user feedback, 2026-09-03, same round)

User rules: (1) drop the 💬 'add item N' relay — buy-list numbers are
plan positions, not search-result numbers; (2) every buy-list line
shows the FULL matched product name (never cut down) + a
`(sheet)`/`(live)` source label, so the user can see where each price
came from.

Changes: `core/basket_optimizer.py` only — StoreAssignment +
item_labels/item_sources parallel lists (from
BasketItem.matched_names/sources); _store_lines renders
`N. Full Name — $price (source)`; _tail_blocks no longer relays the
comparator 💬 reminder. SKILL.md/README wording stays accurate — no
regen.

| Check | Result |
|-------|--------|
| full suite | PASS — 669 passed, 0 skipped (F-1..F-4, F-7 re-pinned) |
| scp + deploy + container smoke | PASS — full names + (sheet)/(live) labels in output, no 💬 line, exit 0 |

### Confirmation flow (user-directed, 2026-09-03, same round)

User rules: sheet prices first; NOTHING is live-searched or written
until the user confirms. Items with missing prices are presented as
A (Coles missing) / B (Woolworths missing) / C (no pricing) with
distinct 3-letter codes. Confirmed A/B items update their EXISTING
sheet row via the map writers (set_store_keyword + update_single_price
— they leave the wool/coles missing lists naturally; NO searched-list
entry, which would create a second line). Confirmed C items: no row →
new sheet row + searched-list entries (exact `search --add-item`
semantics: empty keyword cols + Col P alias; both store listings
queued when a gate-passing pair is found); legacy unpriced row →
updated in place. The final basket is rebuilt from the sheet after
the writes.

New: `core/basket_confirm.py` (pending state
`data/optimize_pending.json`, classification, code assignment,
execution, display block). Changed: `core/basket_optimizer.py`
(+ public `plan_from_items` — pipeline on pre-priced items),
`grocery_price_cli.py` (+ `--confirm CODES|all|none`, `--items` now
optional with explicit validation), SKILL.md row/mapping/pattern 7 +
example, README §5 + blockquote, PROJECT-MAP §5. Catalogue regen → OK.

| Check | Result |
|-------|--------|
| test_basket_confirm.py (12 tests: classification, codes, state IO, A/B write semantics + never-queues, C-new add+queue, C-row in-place, Coles-unavailable degradation, block format, CLI wiring ×2, hydration) | PASS |
| FULL GATE | PASS — 681 passed, 0 skipped |
| Local run 1 → confirmation block (B/C groups, codes, full row names) | PASS — exit 0 |
| Local `--confirm none` → no writes + rebuilt sheet-only plan (full names) | PASS — exit 0 |
| Deploy 5 files + md5 both sides | PASS — all identical |
| Container smoke: run 1 + `--confirm none` | PASS — same shapes, exit 0 |

Note: no REAL confirmation was executed (that writes to the user's
sheet/queues) — the user drives those from Telegram.

### Lookup live-fill fix (user-directed, 2026-09-03, same round)

User granted the file boundary ("fix it in lookup.py"). Defect: a
sheet row resolved by lookup steps 1-3 whose price cells are
unusable (unavailable / N-A / blank — e.g. legacy 🏠 bread / beef
mince rows) returned immediately, so Step 5 live search never fired
and the item showed "No comparable price".

Fix (core/lookup.py): Steps 1-3 resolutions are now finished by
`_finish_sheet_result()` — for NON-INTERACTIVE callers (compare
auto / optimize) the MISSING stores are live-searched and merged into
the result (`LookupStatus.SHEET_AND_LIVE` + per-store `sources`;
sheet prices never overwritten; UOM pair gate still applies to live
prices; nothing found → pure sheet answer). INTERACTIVE callers (the
map resolve flow) keep the pure sheet answer — list semantics
untouched. core/price_comparator.py: `_gather_lookup_prices` gained
the SHEET_AND_LIVE branch (per-store source tags). New tests:
tests/test_lookup_live_fill.py (7).

| Check | Result |
|-------|--------|
| FULL GATE | PASS — 688 passed, 0 skipped |
| Deploy lookup.py + price_comparator.py, md5 both sides | PASS — identical |
| Container `compare --items "beef mince"` (was: no comparable price) | PASS — both stores LIVE-priced ($13.54 / $14.50), (live) labels, exit 0 |

### Loophole fix: confirmation writes are PRICE-ONLY (user-directed, 2026-09-03)

User caught the loophole: writing the store KEYWORD during confirm
would make the row vanish from the wool/coles missing lists (those
lists are keyword-derived: I present + J empty = wool missing, and
vice versa) while the product is not actually on the store website
list — so Wednesday would never refresh the price and the staleness
would be invisible. User's own suggestion adopted: **write the price,
NOT the keyword.**

- A/B/C-row-exists confirms now call update_single_price ONLY (unit
  into blank Col C). set_store_keyword is never called by the
  confirmation flow — keywords stay the resolve flow's job (map), and
  the row stays flagged on the missing list until then.
- C-new items unchanged (new row + searched-list entries — the
  designed reminder loop).
- Robustness: `_compare_with_retry` (CLI, 3 tries) around the
  sheet reads on the confirm/auto paths — a transient Sheets 500/503
  mid-confirm no longer aborts after writes succeeded.
- Docs updated (SKILL.md row/mapping, README, PROJECT-MAP); catalogue
  regen → OK.

| Check | Result |
|-------|--------|
| test_basket_confirm.py updated (keyword never called; price-only; block wording) | PASS — 12/12 |
| FULL GATE | PASS — 688 passed, 0 skipped |
| Deploy basket_confirm.py + SKILL.md + catalogue + CLI, md5 both sides | PASS — identical |
| Container smoke: run 1 (new wording) + `--confirm none` rebuild | PASS — exit 0 |

### Plural matching fix + routing phrase (user-directed, 2026-09-03)

Real Telegram test exposed two questions: (1) "mince" displayed the
full matched row name "Woolworths Beef Mince 500g" — by design (full
names rule; shows exactly which row a confirm would price); (2)
"apples" was classified "(not on sheet)" although row 52 "Royal Gala
Apple 1 Kg" exists — the sheet matchers compare whole words only, so
plural "apples" never matched singular "apple" (alias "royal gala
apple").

Fix (core/lookup.py): `find_alias_token` + `find_candidates` now use
the same singular/plural `_token_variants` normalisation the live
search ranker already had. Deployed + verified on the real sheet:
"apples" → row 52 SHEET_AND_LIVE (WW $7.90 sheet + Coles $7.50 live);
"mince" → row 82 both-store live fill. Also this round: SKILL.md
routing + frontmatter gained "this week's shopping list" phrasings
(catalogue regen OK, deployed).

| Check | Result |
|-------|--------|
| test_lookup.py + plural class (6 new) + live_fill | PASS — 31/31 |
| FULL GATE | PASS — 693 passed, 0 skipped |
| Deploy lookup.py + SKILL.md + catalogue, md5 | PASS — identical |
| Real-sheet probes: apples → row 52 (sheet+live), mince → row 82 (live fill) | PASS |

### Round 2: RecipeResolver plurals + to-do awareness (2026-09-03)

The first Telegram test still classified "apples" as C "(not on
sheet)": the optimize SHEET pass uses RecipeResolver's SheetIndex —
a different matcher from the LookupIndex fixed above, with the same
missing plural handling. Fixed: SheetIndex.find_partial now applies
_token_variants (mirroring lookup.py).

Also answered the user's dedup question with code + a fix: C-new
confirms now check the to-do list (add_to_list.is_pending) before
queueing on searched-items and skip the entry if already pending
there; searched-items itself was always dup-guarded (store +
normalised name); A/B items never touch either queue (price-only
write); the sheet write is protected by the one-line rule merge.

| Check | Result |
|-------|--------|
| test_basket_confirm.py (+5: SheetIndex plural ×2, to-do awareness ×1, etc.) | PASS — 15/15 |
| FULL GATE | PASS — 696 passed, 0 skipped |
| Deploy recipe_resolver.py + basket_confirm.py, md5 both sides | PASS — identical |
| Container re-test, real 8-item list: apples → A.1 "Royal Gala Apple 1 Kg" (was C "not on sheet") | PASS — exit 0 |

### Final decision tree (user-directed, 2026-09-03)

The user specified the full classification tree; implemented verbatim
in `basket_confirm.classify_basket` + CLI:
1. fully sheet-priced → basket.
2. one side priced: keyword missing + already queued on searched/to-do
   → "already queued for Wednesday", NO action (queues carry no
   prices — user confirmed); pricing missing/error → closest sheet
   SUBSTITUTE first (read-only, source "sub", full name disclosed,
   never written) → else live search (price-only write into the
   existing row).
3. row exists, neither priced → same as 2 (sub both sides → live).
4. not on sheet → confirmable: compare-only by default (nothing
   written; live prices injected into the plan), `+add` opts in to
   new row + searched entries (chosen BEFORE the comparison, per
   user).

LookupIndex row dicts now carry raw ww_kw/coles_kw cells so the
classifier can tell a missing KEYWORD from a missing PRICE.
`parse_confirm` grammar: all / none / all+add / codes[+add].
CLI `_load_queues` (read-only) feeds both queues into classification.

| Check | Result |
|-------|--------|
| test_basket_confirm.py rewritten (20 tests: tree, substitutes, queued, compare-only, +add, parse grammar, inject_live, CLI) | PASS — 20/20 |
| FULL GATE | PASS — 712 passed, 0 skipped |
| Deploy CLI + basket_confirm + lookup + SKILL.md + catalogue, md5 both sides | PASS — identical |
| Container smoke, real 8-item list: eggs+apples auto-resolved via sheet subs; 3 gaps pending; `--confirm none` rebuild shows (sub) labels + savings | PASS — exit 0 |

Backlog note: substitute matching is token-based and can pick loose
subs (e.g. apple fruit straps for "apples"); tightening with the UOM
size gate is a candidate follow-up.

### Stale-keyword resync (user report from live test, 2026-09-03)

Live test: "royal gala apples" went through `search --add-item`
(agent routing) and created a DUPLICATE row, even though row 52
"Royal Gala Apple 1 Kg" exists with BOTH keywords and a Coles cell of
"N/A 2026-09-02". User semantics: keyword present + price N/A means
the product is SUPPOSED to be on that store's website list but never
matched — the correct action on a confirmed live price is: write the
price, RE-SYNC the stale keyword to the found product name, and add a
TO-DO reminder so the user verifies the website shopping list.

Fix (core/basket_confirm.py): classification carries `kw_present` per
gap (persisted in pending state); execute_confirmation re-syncs the
keyword + adds the to-do entry for sides with stale keywords (A/B and
C-row paths). Sides with no keyword stay price-only/stay-flagged as
before. Also flagged to the user: the agent's detour through
`search --add-item` was routing, not the confirm flow — the confirm
flow itself would have resolved "royal gala apples" → row 52 via the
plural alias fix.

| Check | Result |
|-------|--------|
| test_basket_confirm.py (+3 resync tests: A stale, A no-kw price-only, C-row stale ×2 sides) | PASS — 24/24 |
| FULL GATE | PASS — 717 passed, 0 skipped |
| Deploy CLI + basket_confirm + SKILL.md + catalogue, md5 both sides | PASS — identical |

User cleanup advised (sheet data, not code): duplicate row 100
("ROYAL GALA APPLES 1KG:…") should be deleted — the live price now
lives on row 52 via the resync path; searched-list entry [UFL] can be
removed with "remove UFL".

### Rule corrected + sheet/list repaired (user-directed, 2026-09-03)

User rejected the keyword OVERWRITE ("it becomes an issue if the item
is not added — the price would never change and the item would be
hidden"): the stale keyword is clearly WRONG, so the correct rule is
DELETE it, write the correct price, and queue the CORRECT keyword on
the TO-DO list.

Code (core/basket_confirm.py): `_clear_stale_keyword_and_todo`
replaces the overwrite attempt — set_store_keyword(row, store, "")
clears the wrong keyword, update_single_price writes the live price,
add_to_list.add_entry queues the correct product (dup-guarded).
Docs updated to match (SKILL.md row, README, PROJECT-MAP); catalogue
regen OK.

Sheet/list repaired via one-off container script (user-approved):
1. Row 52 "Royal Gala Apple 1 Kg": Coles price N/A -> $7.90 (found=True, wrote=True)
2. Row 52 stale Coles keyword cleared (wrote=True)
3. To-do list: "ROYAL GALA APPLES 1KG:ROYAL GALA:.:1 KG" queued (code BQW)
4. Duplicate row 100 deleted (Col A safety check passed first)
5. Searched list: stray entry UFL removed (15 entries remain)

| Check | Result |
|-------|--------|
| test_basket_confirm.py (stale = clear + todo; no-kw = price-only) | PASS — 23/23 |
| FULL GATE | PASS — 717 passed, 0 skipped |
| Deploy basket_confirm + SKILL.md + catalogue, md5 both sides | PASS — identical (CLI already current) |

### Round closed (2026-09-03)

Docs finalised: SKILL.md (row + mappings + pattern 7 + examples),
grocery-price-tracker README (§5 row + Smart Basket blockquote),
PROJECT-MAP (§0/§5/§8), future_roadmap (R17 → Realized with the
confirmation-flow + plural-fix additions), catalogue regenerated
(`skills_doc.py --check` OK). All code + SKILL.md + catalogue deployed
to myvps with matching md5s. Full gate at close: **712 passed,
0 skipped**. Pending: user's live Telegram test (no code work
outstanding).

### Telegram E2E test — SUCCESS (user-confirmed, 2026-09-03)

User ran the full flow: list message → 🔎 confirmation list (tomato =
B stale-keyword item) → confirmed the tomato code only → result line
reported price written + "wrong keyword cleared + correct one added
to your to-do list" — exactly as designed. User: "ok success".

TOPIC CLOSED. Final state: 717 passed / 0 skipped; all code + docs +
skill + catalogue deployed (md5-verified); sheet + queues repaired.
Uncommitted by design (user commits on request). Backlog candidates
logged above (substitute UOM tightening; agent routing for
post-result refine — mitigated via SKILL.md guidance).

### Backlog items raised (NOT built — outside 03 boundary / need design)

1. **Lookup-chain defect:** sheet rows with an UNUSABLE price
   (unavailable/N-A/blank, e.g. legacy 🏠 bread + beef mince rows) are
   treated as resolved by `_gather_lookup_prices` (Steps 1-3) and
   never reach Step 5 live search — they show "No comparable price"
   even though both stores are reachable. Fix belongs in
   `core/lookup.py`/`core/price_comparator.py` (FORBIDDEN to 03 Code
   by plan §0.3.1) → needs 02 Planner or explicit boundary grant.
2. **Pre-basket live-search confirmation flow (user request):** before
   live searching non-sheet items, present A (coles-missing) / B
   (wool-missing) / C (no pricing at all) groups with distinct
   3-letter codes; user confirms → confirmed items go to the
   searched-items queue AND the live search; then the basket is built.
   This REVERSES the spec-locked "optimize is look-only, never
   queues" rule and needs new state + CLI flags → 02 Planner scope.

### Live 7-list counts + mid-week resolution removal (2026-09-03, Checker)

User incident: "show me all 7 lists only their counts" reported
Unmatched 45 / Coles missing 10 AFTER everything was resolved, and
no-price 11 after a deletion (yesterday: 10). Investigation found the
reporting rule counted the Wednesday-run .txt snapshots — map
resolutions never rewrite them, so counts stay frozen at last
Wednesday. (No-price 11 was LIVE-correct: the Beef Mince --na
resolution joined it to the no-price list. Birkford deletion held.)

Fixes (user approved both):

1. New `lists` command — the 7 user-facing lists with LIVE counts:
   sheet-based for 1-3 + 7 (exact Wednesday semantics: keyword cols
   I/J, NA=populated, priceless = neither price > $0), Unmatched also
   drops debt entries whose keyword now exists (read-only auto-heal
   view) + ignored junk; live queue files for 4-6. `--full` prints
   names. Sheet failure degrades those lists to "unavailable" with
   the verbatim error (never stale substitutes), exit 0.
2. Mid-week removal: map --pick/--na/--keyword/--forget and the
   unmatched exact-link --add now remove the resolved line from its
   .txt work list immediately (header count decremented; progress
   stays at idx since the next item slides in). --skip and the
   price-only wool/coles --add intentionally keep the line.
   Shared `_noprice_sort_key` extracted (Wednesday/no-price/lists
   order identically). SKILL.md 7-list rule now runs `lists` and
   forbids counting the .txt snapshots.

Sandboxed tests (test_lists_cmd.py — tmp dirs only): 11 new. NOTE:
the pre-existing suite still writes fixtures into the REAL data/ (the
root cause of the local queue wipe found during investigation); the
user is enforcing sandboxed tests for future agents.

Also observed (NOT fixed, user decision pending): the VPS debt ledger
(unmapped_queue.json) contains old test-junk entries ("Totally
Unknown Product 999g [aldi]" etc.) mixed with real unresolved items
— live Unmatched on the VPS reads 18. Cleanup via map --forget or a
bulk purge on request.

| Check | Result |
|-------|--------|
| New tests test_lists_cmd.py | PASS — 11/11 |
| FULL GATE | PASS — 712 passed, 0 skipped |
| Local live run `lists` + `lists --full` | PASS — live sheet + queues |
| Deploy deploy_vps.py (CLI + SKILL.md), container restart + smoke | PASS — 24/24 scp OK |
| Catalogue regen + --check, scp + md5 both sides (CLI/SKILL/catalogue) | PASS — identical |
| Container `lists` / `lists --full` / `no-price` | PASS — live counts (18/0/7/8/15/12/11) |

### Unmatched purge + website-add handshake annotation (2026-09-03, Checker)

User-approved one-off: cleared ALL pending unmatched debt on the VPS
(34 entries — 18 visible + 16 already hidden) via tmp_purge script:
each entry appended to data/ignored_items.txt (permanent — the docx
junk re-parses every Wednesday and the ignore list is what keeps it
hidden) + marked resolved in unmapped_queue.json. Cleaned queue pulled
back to LOCAL (Wednesday Step 5 pushes local debt to the VPS — both
sides must agree or the cleanup un-does itself); same ignore lines
appended locally (33 new, dup-guarded). Live: Unmatched 0,
Forgotten 34.

`lists` now annotates the wool/coles-missing ↔ to-do overlap:
"(N pending website adds)" on the count line + "⏳ website add queued"
per item in --full. Rationale: `map --add` writes the price now but
the store keyword only lands on `add-to-list done` — writing it
earlier would make the next Wednesday sync stamp the fresh price
N/A (keyword exists, item not yet on the store list). The overlap is
the designed 2-step handshake, not a duplicate; unannotated missing
rows are the genuinely-open ones (live: Coles 7, of which 5 queued).

| Check | Result |
|-------|--------|
| Purge run in container (34 cleared), temp script removed both sides | PASS |
| Local mirror: cleaned unmapped_queue.json pulled, ignore lines appended | PASS |
| Annotation tests (+2, is_pending mocked to entry-or-None contract) | PASS |
| FULL GATE | PASS — 714 passed, 0 skipped |
| Redeploy (CLI + SKILL.md + catalogue), md5 both sides | PASS — identical |
| Container `lists --full`: Unmatched 0; "Coles missing — 7 (5 pending website adds)" | PASS |

### Missed pricing (list #7 redefined) + GONE word + two-strike auto-delete (2026-09-03, Checker)

User spec (after reviewing the one-price-missing populations): list #7
becomes MISSSED PRICING — (a) FIXABLE: store keyword present + that
price unusable + not GONE (covers keyword mismatches AND deliberate-NA
rows, which the user ruled must be reviewed too — a Coles home brand
can still exist for a WW item); no-keyword rows stay excluded (missing
lists own them). (b) DELETE-PENDING: both prices unusable (GONE
counts) — the old no-price population, now a deletion pipeline.

GONE (user decision): typed manually into a PRICE cell (D/E) =
"verified unavailable — never captured again". Marker writes (N/A /
unavailable) never stomp it (sync match loop + not-found pass guarded,
tested); a returning REAL price clears it (resurrection).

Auto-delete (two strikes, user-approved): Wednesday Step 3b — a
both-dead row is deleted only when a PREVIOUS run already saw it dead
(data/delete_candidates.json ledger; same-day rerun never deletes;
recovered rows leave the ledger). One bad paste can never wipe rows.
Every deletion archived to data/deleted_rows.json first. Manual exit:
`missed-pricing --purge` (explicit user request during review) deletes
all delete-pending rows now + archives + clears ledger strikes;
`--dry-run` previews. `delete_product_rows` (bottom-up, batch) added to
sheets_sync; sheets_sync added to the deploy manifest (was missing —
md5 mismatch caught during this deploy, hand-scp'd + manifest fixed).

no-price subcommand kept as the legacy both-dead view; skill rule now
points at lists/missed-pricing.

| Check | Result |
|-------|--------|
| test_missed_pricing.py (classification, two-strike, purge, GONE guards) | PASS — 16/16 |
| Full gate | PASS — 733 passed, 0 skipped |
| Local live `lists` + `missed-pricing --dry-run` | PASS — 33 (23 fixable · 10 delete-pending) |
| Deploy (CLI + SKILL + catalogue + sheets_sync), md5 both sides | PASS — identical |
| Container `lists` | PASS — 33 (23 fixable · 10 delete-pending) |

### Root cause of the 4:43 PM stale-list regression + merged todo queue (2026-09-03, Checker)

User re-tested at 4:43 PM and STILL got 45/10/old-format. Root cause:
the agent loads skills from the CONTAINER-tree copy —
openclaw.json: skills.load.extraDirs = ["/app/tasks/ai-tools/claw-
skills"] — and that copy was stale until 4:41 PM (deploy_vps.py only
pushed SKILL.md to /openclaw/skills/, a different path). The agent
process had started at the 4:25 PM restart and cached the old text;
the 4:43 reply followed the OLD rule (count Wednesday .txt snapshots)
and LLM-decorated the output (also a verbatim-rule violation).
Fix: container-tree copy synced (md5 identical on all copies),
deploy manifest now pushes SKILL.md to BOTH paths, agent restarted +
verified. If the bot still misbehaves inside an old Telegram thread,
a fresh thread is needed (per-conversation instruction cache).

User rule (same session): MERGE to-do + searched into ONE queue with
a uniform done that ALWAYS writes the keyword — no gaps:

- new `todo` subcommand: show = merged continuous-numbering view
  (Coles then Woolworths; add entries before searched; "· new row"
  marks searched); done --items "1,HUY,SRM" resolves merged numbers +
  codes, all-or-nothing (BOTH queues validated before EITHER mutates),
  removes entries AND writes the remembered exact store name as the
  row's store keyword for BOTH kinds (closes the "searched has no
  done" gap). Wednesday Step 1b list-presence auto-drain unchanged.
- Basmati gap fix: add_product_row merged result now reports
  store_keyword_empty; a merged search-add (price onto an existing
  keyword-less row) queues a to-do entry with the exact store name.
- `lists` renumbered 7 -> 6: #4 = merged To-do (N price-pending · M
  new rows), #5 Forgotten, #6 Missed pricing. add-to-list /
  searched-items kept as legacy views. Skill updated (6-list rule,
  todo routing); the parallel session's optimize-row edits preserved.

| Check | Result |
|-------|--------|
| test_todo_cmd.py (merged show, done both kinds, all-or-nothing, gap fix) | PASS — 9/9 |
| FULL GATE | PASS — 742 passed, 0 skipped |
| Live 503 degradation (transient Sheets outage mid-verify) | PASS — "unavailable" + verbatim error, offline lists still delivered |
| Deploy (CLI + SKILL.md both paths + sheets_sync + catalogue), md5 x4 | PASS — identical |
| Agent skill path (/app/tasks/ai-tools/claw-skills) post-restart | PASS — current md5 |
| Container `lists` + `todo show` | PASS — 6 lists live; 33 merged entries (10+23) |

### Legacy commands redirected to merged views (2026-09-03, Checker)

User escalation: the bot (old instructions cached in its Telegram
thread context) kept showing 7 lists, SEPARATE to-do/searched, and
no-price 10. Fix at the command layer so EVERY instruction version
produces the new truth:
- no-price -> full missed-pricing report (one-store failures included;
  the old both-dead-only view is gone)
- add-to-list show / searched-items show -> the merged ONE-queue view
  (same numbering as todo show)
- add-to-list done -> delegated to the todo done flow (merged numbers
  + codes; always writes the keyword)
Test updates: 8 assertions to the merged wording; _atl_ctx isolates
BOTH queues now (_CombinedPatch helper).
SECURITY NOTE: during gateway config recon a provider API key value
was accidentally printed in admin output (key-filter matched apiKey).
Not committed anywhere; user advised to rotate it.

| Check | Result |
|-------|--------|
| FULL GATE | PASS — 742 passed, 0 skipped |
| Container: add-to-list show / searched-items show / no-price | PASS — all print merged views (verified live) |
| Gateway headless chat probe (in-container /api/prompt) | 404 — no public chat API; agent verified via its command layer instead |
| Deploy (CLI + SKILL both paths + catalogue), smoke | PASS |

### Docs refresh + restart-safety proof (2026-09-03, Checker)

User confirmations requested and delivered:
1. ALL lists live irrespective of docker restart/recreate — PROVEN:
   compose-defined bind mounts carry every state file on the host;
   captured lists output, restarted the container, re-ran: IDENTICAL.
2. Format explanation delivered (bot thread narration vs command
   output; commands now print the new views regardless).
3. Docs updated: root README + tracker README (new commands table
   rows, data-file table, Wednesday row, 2026-09-03 note),
   DIRECTORY_TREE.md revision note, NEW PROJECT-MAP.md (consolidated
   architecture map: 6 lists, merged todo, missed pricing/GONE/
   two-strike, topology + restart safety, scenario matrix).

### Missed-pricing weeks-on-list ages ledger (2026-09-03, Code)

Fix for the "(new)" regression: every row showed (new) because the
2026-09-02 overwrite-semantics change re-stamped all price-cell
anchors (date-based aging restarted from zero). New first-fail ledger
data/missed_pricing_ages.json ({generic: first_seen YYYY-MM-DD}):
- Written ONLY by persist_ages=True callers (missed-pricing command,
  Wednesday Step 3b non-dry-run); lists stays read-only (hash-proven).
- _cell_weeks prefers the ledger date; anchor/Col-H fallback unchanged.
- Pruning drops entries no longer failing (price fixed, row deleted,
  or manual GONE verdict leaving the lists - re-ages if undeleted).
- OLDEST date kept on collision; delete_candidates.json untouched.
First live run recorded today, so current labels read (new) - correct;
ages grow from the ledger now and survive anchor resets. Self-heal
note stands: anchor preservation means 2026-09-09 still-failing rows
would show (1 week) either way; the ledger additionally survives
manual cell clears and is correct immediately.

| Check | Result |
|-------|--------|
| FULL GATE (pytest grocery-price-tracker/tests -q) | PASS - 750 passed (742 prior + 8 new ages-ledger tests) |
| Seeded history shows (2 weeks) on first run (tmp sandbox) | PASS |
| Genuinely-new failures (<7d) still show (new), record today | PASS |
| lists path never writes ledger (absent / byte-identical) | PASS |
| GONE row's ledger entry dropped; still-failing kept | PASS |
| delete_candidates.json untouched by ages write | PASS |
| Live missed-pricing local run creates ledger (32 rows, 2026-09-03) | PASS |
| Live lists run leaves ledger md5-identical | PASS |
| Deploy (deploy_vps.py: 26 files, container restart + smoke) | PASS |
| In-container missed-pricing verify | PASS - 22 fixable / 10 delete-pending |
| VPS ledger written (32 entries, all 2026-09-03) | PASS |
| md5 grocery_price_cli.py local vs VPS | PASS - BAEACD8E7EAF36B2905A28EF7D3AB08E both sides |

Windows note: local console cp1252 cannot decode the report emoji
(PYTHONIOENCODING=utf-8 workaround); deploy script's trailing
reader-thread UnicodeDecodeError is the same cosmetic artifact AFTER
"Deploy complete." - deployment itself fully green.
