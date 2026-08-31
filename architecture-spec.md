# Architecture Spec — Finish Line: D23–D27 + B4/B5 Completion

- **Date:** 2026-08-30
- **Stage:** 01 Architect (this doc) → 02 Plan → 03 Code → 04 Architect Checker
- **Status:** CONFIRMED by user (chat 2026-08-29/30) — scope, dropped umbrella
  command, manual thread-ID step, and full-codebase verification all approved.
  Ready for 02 Plan.
- **Inputs:** `pre-arch.md` rev 2 (00 Tester) + `README.md`
  + full code inspection (architect, 2026-08-30) + an independent verification
  sweep of every pre-arch decision against the live code (2026-08-30).
- **Replaces:** the previous spec at this path (UOM gate + live-lists
  pipeline, 2026-08-29). That work SHIPPED and is verified below; this spec
  supersedes it and covers only the remaining gap set. Nothing from the
  shipped set is re-opened.

---

## 1. Goal (plain language)

The big rebuild (correct-product comparison, live lists, queues, Scrape.do
recipe) is done and verified in code. Five small user decisions from
2026-08-30 plus two binding rules that slipped through unimplemented remain.
This project finishes them:

1. **D23** — `compare` forgets to tell the user they can queue a result;
   `search` already does. Add the same reminder line.
2. **D24** — Wednesday output crowds one Telegram topic. Split into two new
   topics (`specials-wool`, `weekly-lists`), retire thread 151 everywhere.
3. **D25** — the sheet's specials columns M/N hold messy free text. Replace
   with exactly three values (`no` / `discount` / `multi-buy`), including new
   Coles marker parsing (`Any 2 | $9` etc.) nobody parses today.
4. **D26/D27** — the one-time discovery "training" was scaffolded but never
   actually records anything on a real run, and its status is invisible.
   Implement the real network recording + make status loud.
5. **B4/B5 completion** — two binding rules from the tester's pre-arch that
   verification found unimplemented: Scrape.do must retry 5xx/timeout ONLY,
   and SKILL.md must carry the hard "never browse the store sites" rule.

**Explicitly REJECTED (user, 2026-08-29):** the proposed umbrella
`grocery` command and the combined `lists` view. The user does not want it —
the existing per-list commands (`searched-items show`, `add-to-list show`,
`map status`) already give per-list views and nothing should be added to
every search. 02 Plan must NOT plan it.

---

## 2. Verified shipped inventory — DO NOT TOUCH (regression-protect only)

Independently verified in code on 2026-08-30 (architect reads + verification
sweep; evidence file:line in the sweep report):

| Area | Verdict | Key evidence |
|---|---|---|
| B1 UOM gate (`core/uom.py`, lookup Step 5, comparator, found-block, totals/🏆 exclusion) | IMPLEMENTED | uom.py:111-193; lookup.py:496-525; price_comparator.py:448-473, 644-664 |
| B2 tolerant ranking, no name rejection, 10× tiebreaker | IMPLEMENTED | lookup.py:395-454, 493-525 |
| B3 explicit-add-only, `--expand`, `--add-item N`, queue phrases, 3-letter codes (D22 form), show/remove/clear, tombstones | IMPLEMENTED | grocery_price_cli.py:528-559, 562-716; searched_items.py:49-51, 253-283, 389-412 |
| B4 Scrape.do recipe | IMPLEMENTED except one tightening (WP2) | coles_extractor.py:64-74, 186-319 |
| B6 `na` commands | IMPLEMENTED | grocery_price_cli.py:2465-2485; sheets_sync.py:558-560 |
| Live window Phases A/B/C, flags, 30-page cap, dedup | IMPLEMENTED except D26/D27 gaps | session_refresh.py |
| `live_list_fetch` snapshots + all-or-nothing gate | IMPLEMENTED | live_list_fetch.py:289-321 |
| `wednesday --source live\|docx` (default docx) | IMPLEMENTED | grocery_price_cli.py:104-106, 1186-1256 |
| Queue hook (explicit adds only) | IMPLEMENTED | grocery_price_cli.py:689-717, 2109-2127 |
| Heartbeat (cookie-only, Scrape.do-free) | IMPLEMENTED | session_refresh.py:486-542 |
| B5 NL mapping "on special/discount anywhere" → compare | IMPLEMENTED | SKILL.md:146 |

**Accepted deviations (no work, recorded so nobody "fixes" them):**
- `search` store lines carry no `(live)` tag — search is live-only by
  definition; provenance tags exist exactly where sources mix (compare).
- `FLUSH_TARGET_LIST` constant in session_refresh.py is unused (targeting is
  enforced by the discovery capture URL). Leave as documentation.

---

## 3. Architect resolutions (small calls made to remove ambiguity)

Consistent with the user's binding decisions; 02 Plan follows these as-is.

| # | Call | Resolution |
|---|------|------------|
| A1 | Where does the D23 line live? | In `price_comparator.format_report` — one place covers `compare` AND `recipe` (both print it verbatim; decision 23 says "the same reminder line search already prints"). |
| A2 | When does it show? | Once, at the end of the report, when ANY displayed item carries a live-sourced price OR a found-block (both "display a live product"). Sheet-only reports show nothing. |
| A3 | Second topic name | Pinned: `weekly-lists` (the pre-arch's own example). |
| A4 | What goes to `weekly-lists`? | Wednesday summary + the FULL three resolve lists (unmatched, wool missing, coles missing) — each list its own message, chunked ≤4000 chars with "(part N/M)" suffixes. The lists are files today; posting them to the topic is the new behavior decision 24 asks for. DMs keep receiving exactly what they get today (summary + specials). |
| A5 | Reminder cron target | `wednesday_reminder.py` posts to `weekly-lists` (the Wednesday workflow topic), DMs unchanged. Its body text is refreshed to describe the live-mode run (docx stays the documented fallback). |
| A6 | M/N back-compat | `specials_reporter` treats empty/`no` as not-special, `multi-buy` as multi-buy, and ANY other non-empty cell as discount — legacy free-text cells keep reporting correctly until the next Wednesday overwrites them. No sheet migration. |
| A7 | Coles marker placement | Below-line check extended to `Was $X` + `Any N | $X`; the ABOVE-line check accepts ONLY a bare `SPECIAL` flag line. Rationale: a bare Save/Was above a product is the PREVIOUS product's marker in the WW layout — checking it would attach the wrong special (misfire guard). |
| A8 | Thread ID plumbing | Constants in code (filled from the user's reported IDs) + env overrides `TELEGRAM_SPECIALS_TOPIC_ID` / `TELEGRAM_WEEKLY_TOPIC_ID` (same pattern as `TELEGRAM_USER_IDS`). Tests inject values; nothing ships with fake IDs — until the user reports the IDs, senders fall back to DM-only with a console note (never crash, never post to 151). |

---

## 4. Work packages

Order below is the recommended build order (small/independent first; WP5's
constant-fill is last because it is blocked on the user's manual topic step).

### WP1 — D23: compare add-reminder (small)

**Gap:** `format_report` (price_comparator.py:667-832) never prints the
reminder; only `search` does (grocery_price_cli.py:656-657). PROJECT-MAP.md
lists it as "Planned but NOT built yet".

**Change (1 file):**
- `core/price_comparator.py` — in `format_report`, after totals/🏆/warnings:
  if any `BasketItem` has a `sources` value `"live"` or a non-empty
  `closest` dict, append exactly:
  `💬 Reply 'add item N' to queue a result for Wednesday.`
  (verbatim, same words as search; once per report, never per item).
  No other output changes.

**Tests (test_comparator.py):** live-price report ends with the line;
found-block-only report ends with the line; pure-sheet report does NOT;
recipe path (same function) covered implicitly.

### WP2 — B4 retry tightening + B5 hard rule (small)

**Gap 1 (B4):** the retry chain re-fires on ANY non-200 except 401/403
(e.g. 404/429 retried). Binding B4: retry on **5xx/timeout only**.

**Change:** `extractors/coles_extractor.py` — in the retry decision: retry
only when the failure is a transport timeout or an HTTP status ≥ 500 (and
not 401/403, unchanged). All 4xx (incl. 404/429) → no retry, store marked
unavailable for the run (existing Woolworths-only + ⚠️ line path). Search
path only; do not touch the legacy list path.

**Gap 2 (B5):** SKILL.md has the NL mapping but NO hard no-browsing rule.

**Change:** `claw-skills/grocery-price/SKILL.md` — add to the Hard rules
section: never use `web_search`/`web_fetch` (or any browsing tool) on
`woolworths.com.au` / `coles.com.au` — they block bots; ALL price, special,
and discount questions about these stores go through the grocery CLI.
Ordinary web search stays allowed for everything else (B5 wording).

**Tests:** test_coles_recipe.py — 404 and 429 are NOT retried (exactly one
attempt); 502/timeout retry with fresh session ids (existing tests tighten).

### WP3 — D25: specials flags `no`/`discount`/`multi-buy` in M/N (medium)

**Gap:** M/N are written as free-text `special_desc` or `""`
(sheets_sync.py:233-236); Coles docx markers `Was $X` and `Any 2 | $9` are
parsed nowhere; the Coles `SPECIAL` flag line is ignored; resolve-flow adds
write no specials cell at all; `specials_reporter` treats any non-empty
cell as on-special.

**Changes:**

1. `extractors/specials_parser.py` — add regexes + one pure classifier:
   - `WAS_RE` (`was $X`, same style as SAVE_RE), `ANY_RE`
     (`any N | $X`, tolerant to spacing/case), `SPECIAL_FLAG_RE`
     (bare `SPECIAL` line).
   - `classify_special(is_special: bool, special_desc: str) -> str`
     returning `"multi-buy"` | `"discount"` | `"no"`.
     Precedence (decision 25, binding): `Any N | $X` (or `N for $X`) in
     desc → multi-buy; else Save/Was in desc or `is_special` → discount;
     else `no`. Pure stdlib; unit-testable.
2. `extractors/doc_parser.py` — in `parse_docx` specials detection
   (currently lines 264-290, both stores share it):
   - Below the price (`i+2`): additionally accept `WAS_RE` and `ANY_RE`
     (desc kept as found, e.g. `"Was $13.20"`, `"Any 2 | $9"`).
   - Above the name (`i-1`): accept ONLY a bare `SPECIAL` flag line
     (`SPECIAL_FLAG_RE`) → `is_special=True`, `desc="SPECIAL"` (A7 guard).
   - Name/price matching semantics, ignore-list, dedup: unchanged.
3. `core/sheets_sync.py`:
   - `sync_prices`: replace the specials cell write with
     `classify_special(item.is_special, item.special_desc)` — every MATCHED
     row gets one of the three values (so `no` overwrites stale text).
     Unmatched rows keep their old cells (same staleness semantics as
     prices today).
   - `add_product_row`: new keyword-only params `is_special: bool = False`,
     `special_desc: str = ""`; when the store's specials header resolves,
     write `classify_special(...)` into that cell; extend `target_width`
     accordingly.
   - `update_single_price`: same two params; when provided and the store's
     specials header resolves, write the flag and widen `target_width`
     past M/N (currently truncated at H, lines 439-446).
4. Callers pass the live item's specials data (they all have the item):
   - `grocery_price_cli.py`: `_search_add_item` (→ add_product_row),
     `map unmatched --add` path, wool/coles missing `--add` paths
     (→ update_single_price).
   - `telegram_gateway/handlers.py`: the map-session add paths
     (add_product_row at ~:652, update_single_price at ~:925) pass the
     same two params — logic lives in sheets_sync, so this is args-only.
5. `core/specials_reporter.py` — `get_active_specials`: on-special iff the
   cell is non-empty AND not `no`; report `multi-buy` cells as multi-buy;
   any other non-empty cell (incl. legacy free text) → discount
   (A6 back-compat). `special_desc` shown = the cell value. Wednesday
   step-8 specials report (Mode A: docx/live snapshot) is NOT touched.

**Tests (new `tests/test_specials_flags.py` + additions):**
classifier precedence matrix (Any beats Save; Was → discount; empty → no;
case/spacing tolerance; `6 for $10` → multi-buy); doc_parser Coles layout
(`SPECIAL` above; `Was $X` below; `Any 2 | $9` below) + the A7 misfire case
(WW `save` line above the NEXT product must NOT attach); sync_prices writes
the vocabulary on a mocked worksheet; add_product_row / update_single_price
flag writes; reporter: `no`/empty excluded, flags included, legacy text →
discount; live snapshot items classify correctly (WW IsOnSpecial+WasPrice →
discount; Coles pricing.was → discount; promotionType MULTI... → check
actual value, else discount).

### WP4 — D26/D27: real discovery recording + loud status (medium)

**Gap (verified):** `_LocalDriver` (session_refresh.py:567-624) has NO
`capture_add_to_list`; `_run_discovery` silently yields `None` → real runs
always record `failed`. Additionally (found in inspection): discovery only
runs with `--recapture` — a true FIRST run never prompts, flush fails
wholesale (one RuntimeError aborts both stores, run():993-1000), and the
Coles fetch also depends on the capture (`lists_url`, :896, :923-924).
`summary["discovery"]` is never printed by the CLI (grocery_price_cli.py:
1686-1718).

**Changes:**

1. `extractors/session_refresh.py` — implement
   `_LocalDriver.capture_add_to_list(store)`:
   - Before prompting: attach a Playwright request listener
     (`page.on("request")`) on the store's page, buffering JSON-request
     candidates (method != GET, same origin, body or URL mentions a list).
   - Print the existing prompt (unchanged wording); poll up to 3 minutes
     (reuse the 2FA wait pattern); take the FIRST candidate → capture
     `{method, url, body_shape}` (body_shape = the observed JSON body
     as-is — flush overrides `name`/`productId`, `_make_add_item` :817-839).
   - Coles only: also capture `lists_url` — the last observed GET to a
     saved-lists page during the session (the user is on that page to add
     the item); verify it by enumerating from page context; on success also
     record `check_url`. If enumeration fails → discovery FAILED for coles
     (do not save a broken capture).
   - Remove the `hasattr` fallback in `_run_discovery` — the real driver
     now always has the method (test drivers keep injecting fakes).
2. Same file — auto-discovery on first run: in `run()`, run
   `_run_discovery` when `recapture` OR any store `_needs_capture` (both
   phases consume captures). `--recapture` still forces re-training.
3. Same file — per-store flush isolation: `_phase_b_flush` wraps each
   store's `_make_add_item`/flush in try/except so a missing capture for
   ONE store yields `flush={"added": [], "failed": <its queue>, "reason":
   "no API capture — run live-refresh --recapture"}` for that store only;
   the other store proceeds.
4. `grocery_price_cli.py` — D27: in `_cmd_live_refresh`'s summary loop AND
   the `wednesday --source live` window block (:1219-1248), print per store:
   `Discovery: captured` / `Discovery: failed — run 'live-refresh
   --recapture' to train`. The flush-failure reason already names the
   recovery command (keep).

**Tests (test_live_window.py + test_cli.py):** capture via a fake page
emulating `on()` + request objects (first-candidate wins, 3-min timeout →
failed, coles lists_url verified/enumerated); auto-discovery triggers only
when a capture is missing; per-store isolation (one store untrained → other
store still flushes); CLI prints captured/failed; no network, no Playwright
import in tests.

### WP5 — D24: Telegram topic split + manual ID step (medium)

**Gap (verified):** `specials-wool`/`weekly-lists` exist nowhere; thread 151
is posted to from `grocery_price_cli.py` (:977, :1544-1547 summary,
:1620-1623 specials), `telegram_gateway/topics.py` (:26),
`wednesday_reminder.py` (:46, :282-283), `handlers.py` (:263-269, plus
stale texts :243, :261); `Development Workflow\TELEGRAM_TOPICS.md` does not
list 151 at all.

**Changes:**

1. `telegram_gateway/topics.py` — add `"specials-wool": <ID>` and
   `"weekly-lists": <ID>` (user-supplied); replace the
   `"grocery-sync-sheet"` entry with a RETIRED comment (no code may post
   to 151).
2. `grocery_price_cli.py`:
   - Replace `_TELEGRAM_THREAD_ID = 151` with `_SPECIALS_THREAD_ID` and
     `_WEEKLY_THREAD_ID` (+ env overrides, A8; unset → DM-only + console
     note, never post to 151).
   - Step 7: summary → DM + `weekly-lists`; NEW: post the three resolve
     lists to `weekly-lists` (A4 chunking); specials report → DM +
     `specials-wool`.
   - NEW tiny subcommand `topics-check`: reads `TELEGRAM_CLAW_BOT` from
     env/.env, calls `getUpdates`, prints every forum topic name →
     `message_thread_id` it can see (this is how IDs 2-12 were verified on
     2026-08-09). Local-only, read-only, never posts.
3. `telegram_gateway/wednesday_reminder.py` — `GROCERY_THREAD_ID = 151` →
   weekly-lists ID (+ env override, keep the self-contained mirror
   pattern); refresh `REMINDER_TEXT` to the current flow: run
   `wednesday --source live` locally (one Chrome window, 2FA once);
   docx paste + plain `wednesday` stays the fallback. Keep the "no need to
   reply 'done'" line.
4. `telegram_gateway/handlers.py` — `handle_done`: route the topic post to
   `weekly-lists`; replace the stale `name_importer → local_sync` texts
   (both the DM ack and the topic notice) with current wording
   (Wednesday live pipeline). No handler removal.
5. `Development Workflow\TELEGRAM_TOPICS.md` — add both new topics + IDs;
   record 151 as RETIRED (deleted by the user after cutover).

**Tests (test_cli.py):** constants/routing (mock `_send_telegram`: summary +
lists → weekly ID, specials → specials ID, never 151); unset-ID fallback →
DM-only, no crash; `topics-check` parses a mocked getUpdates payload;
reminder: patchable constant routes to the weekly ID (the reminder script
itself stays deployment-only, tested by import where feasible).

**MANUAL STEP (user) — click-by-click, included verbatim in §6.**

---

## 5. File boundaries (allowed scope for 02 Plan / 03 Code)

**May create:**

| File | Purpose |
|---|---|
| `grocery-price-tracker/tests/test_specials_flags.py` | D25 classifier, Coles markers, sheet writes, reporter re-base |

**May edit (surgical only):**

| File | Changes |
|---|---|
| `grocery_price_cli.py` | WP5 constants + routing + lists posting + `topics-check`; WP4 discovery status prints; WP3 specials params at the three add call-sites |
| `grocery-price-tracker/core/price_comparator.py` | WP1: the reminder line in `format_report` ONLY |
| `grocery-price-tracker/extractors/specials_parser.py` | WP3: WAS_RE / ANY_RE / SPECIAL_FLAG_RE + `classify_special` |
| `grocery-price-tracker/extractors/doc_parser.py` | WP3: marker detection in `parse_docx` (below: Was/Any; above: SPECIAL flag only) — name/price semantics unchanged |
| `grocery-price-tracker/core/sheets_sync.py` | WP3: `sync_prices` flag write; `add_product_row` + `update_single_price` optional specials params |
| `grocery-price-tracker/core/specials_reporter.py` | WP3: on-special filter + display per A6 |
| `grocery-price-tracker/extractors/session_refresh.py` | WP4: `capture_add_to_list`, auto-discovery, per-store flush isolation |
| `grocery-price-tracker/extractors/coles_extractor.py` | WP2: retry on 5xx/timeout only (search path) |
| `telegram_gateway/topics.py` | WP5: two new IDs, retire 151 |
| `telegram_gateway/wednesday_reminder.py` | WP5: weekly ID + refreshed text |
| `telegram_gateway/handlers.py` | WP5: `handle_done` routing + texts; WP3: pass specials params at the two add call-sites |
| `Development Workflow\TELEGRAM_TOPICS.md` | WP5: new topics, retire 151 |
| `claw-skills/grocery-price/SKILL.md` | WP2: hard no-browsing rule; WP5: `topics-check` row; note the specials-column vocabulary |
| `grocery-price-tracker/tests/test_comparator.py`, `test_coles_recipe.py`, `test_live_window.py`, `test_cli.py`, `test_sheets_sync.py` | Tests for the above (mocked, no network) |
| `grocery-price-tracker/README.md` | Document D23–D27 + this spec's changes (note: `PROJECT-MAP.md` referenced by the README conventions section does not exist — do not create or update it for this project) |

**Must NOT touch:** `core/lookup.py` (any step), `core/uom.py`,
`core/searched_items.py`, `core/add_to_list.py`,
`core/missing_items_tracker.py`, `core/name_matcher.py`,
`core/telegram_format.py`, `core/woolworths_discounts.py`,
`core/schema_upgrade.py` (M/N already exist), `extractors/woolworths_extractor.py`,
`extractors/live_list_fetch.py`, `extractors/models.py`, any `.docx` file,
`.env`, `telegram_gateway/bot.py` / `commands.py` / `budget_sheets.py` /
`allowlist.py`, `scripts/session_heartbeat_entry.py`, the docx-parsers'
name/price matching semantics, and everything in §2.

**Revert guarantee:** every WP is additive or constant-level; WP5's routing
reverts by restoring the single 151 constant; WP3's cell vocabulary reverts
by reverting the `classify_special` call sites. No data migrations.

---

## 6. Manual user steps (click-by-click)

**M1 — Create the two topics (before WP5 constant-fill):**

1. Open **Telegram Desktop** → the **Claw Command Center** group.
2. In the topic list on the left, click the **⊕ (Create Topic)** button
   (Desktop: also reachable via the ⋮ menu → "Create Topic"; Android/iOS:
   open the group → tap the topic list → tap **＋**).
3. Topic name: type exactly **`specials-wool`** → tap **Create**.
4. Repeat steps 2-3 with the name exactly **`weekly-lists`**.
5. Open the `specials-wool` topic and send one message:
   **`@ClawArkindBot id`** (mentioning the bot guarantees delivery even
   with privacy mode on).
6. Repeat in `weekly-lists`.
7. On the local machine, run:
   `python grocery_price_cli.py topics-check`
   → it prints each topic name with its thread ID, e.g.
   `specials-wool → 543`.
8. Tell the coder the two numbers. The coder fills them into
   `topics.py`, `grocery_price_cli.py`, `wednesday_reminder.py`, and
   `TELEGRAM_TOPICS.md`.

**M2 — After cutover (user, once):** delete the old "Grocery: Sync & Sheet"
topic in Telegram (the system no longer posts to it).

**M3 — D26 acceptance (user present, once):** run
`python grocery_price_cli.py live-refresh --recapture` locally; add ONE
item to the "Price Compare" list in the open window per store; the summary
must print `Discovery: captured` for both stores, and the next flush must
succeed. If any store prints `failed`, the recovery command is printed with
it.

---

## 7. Test plan summary (02 Plan expands; no test may hit the network)

1. WP1: reminder presence/absence matrix (live price / found-block /
   sheet-only).
2. WP2: 404+429 → exactly one attempt; 5xx/timeout → 3 fresh sessions;
   401/403 never retried (existing tests tightened).
3. WP3: full classifier matrix; Coles docx layouts incl. the A7 misfire
   guard; sheet writes on mocked worksheet; reporter vocabulary + legacy
   back-compat; live-snapshot classification.
4. WP4: capture listener (fake page), first-candidate wins, timeout →
   failed, coles lists_url verification; auto-discovery gating; per-store
   isolation; CLI status prints.
5. WP5: routing matrix (never 151; correct targets; chunking at 4000
   chars); unset-ID DM-only fallback; `topics-check` against a mocked
   getUpdates payload.
6. Regression: existing suites stay green — the bar is the FULL suite at
   446 passed / 0 failed. The 8 old `test_extractors.py` failures were
   repaired by the 04 Checker on 2026-08-29 (test.md), and the repaired
   test files were synced to the VPS on 2026-08-30 (housekeeping §9).
   There is no documented-failure carve-out anymore: any new failure is a
   regression that must be fixed.

**Acceptance:** all suites pass locally with Anaconda Python; M1/M3 manual
steps succeed; first live Wednesday after cutover posts summary+lists to
`weekly-lists` and specials to `specials-wool`, nothing to 151.

---

## 8. Handoff to 02 Plan

Plan the five work packages in the order WP1 → WP2 → WP3 → WP4 → WP5.
WP5's code can be written against placeholder constants + env overrides,
but the constant-fill and Telegram verification are gated on manual step M1.
Respect §5 boundaries exactly; the §2 inventory is regression-protect only.
All user decisions cited here are binding (pre-arch.md C.9 #16-27 and the
rejection of the umbrella command, user chat 2026-08-29/30).

---

## 9. Housekeeping completed by 01 Architect (2026-08-30, pre-plan)

The user reported still seeing "8 existing errors" after every test run.
Investigation and resolution (all done, no code changes):

1. **The 8 failures were already fixed.** The 04 Checker repaired the
   stale Phase-1 `test_extractors.py` tests on 2026-08-29 (documented in
   `test.md`): local full suite verified green — **446 passed, 0 failed**.
2. **VPS test copies were stale** (the checker's test-file repairs and one
   new test file were never deployed). Synced local → VPS:
   `test_extractors.py`, `test_name_matcher.py`, `test_telegram_format.py`,
   `test_woolworths_discounts.py`, `test_add_to_list.py` (was missing).
   md5-verified identical after sync. Note: neither the VPS host nor the
   container has pytest — testing stays a local-machine activity; the sync
   exists so the deployed tree is not a stale trap.
3. **README's stale claim fixed** — it said "430+ passing, 8 pre-existing
   failures, not touched"; now states 446/0 with the repair + sync history.
4. **`PROJECT-MAP.md` does not exist** anywhere in the workspace (the
   README conventions section references it aspirationally, and the
   verification sweep cited it in error). This spec does not require it;
   02/03 must not invent citations to it.

**Regression bar for this project: full suite green, 446/0. No carve-outs.**
