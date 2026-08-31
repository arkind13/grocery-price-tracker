# Architecture Spec — Live-Session Grocery Pipeline (fetch lists + batch website-adds)

- **Date:** 2026-08-28
- **Stage:** 01 Architect (this doc) → 02 Plan → 03 Code → 04 Architect Checker
- **Status:** Draft for user confirmation
- **Trial rule (user-mandated):** new capability runs alongside the current
  Word-document method for one week. The old method stays fully intact and
  is the default. Reverting must require zero code deletion.
- **Sibling spec:** `architecture-spec.md` (add_to_list queue — shipped,
  committed `46e9254`). This spec builds on that queue.

---

## 1. Goal (plain language)

Today's Wednesday run depends on two manual steps: copy-pasting saved lists
from Woolworths and Coles into Word documents, and manually adding missing
items to the store websites. Both exist because the stores block scripts
from logged-in areas.

New reality (verified by hands-on testing 2026-08-28):

- A **visible, real Chrome window** on the user's local PC passes both
  stores' robot checks (headless is blocked; headed is not).
- Woolworths' list APIs answer plain script calls fine — the only missing
  piece is a **live session cookie** (fresh cookie = works; stale cookie =
  403; no cookie = 200 but empty).
- The user reports both stores log them out almost daily. The plan therefore
  assumes **nothing about session lifetime**: everything that needs login
  happens inside one short "live window", and everything else queues.

**One live window per Wednesday (plus optional urgent windows) does:**

1. Log in to both stores once (user present, 2FA once each).
2. Fetch all three saved lists with live prices:
   - Woolworths: **"Price Compare"** and **"Special list (28)"**
   - Coles: **"Price Compare"**
3. Sync the sheet, generate the three lists (unmatched / wool missing /
   coles missing) — exactly as today.
4. Flush both website-add queues in one batch:
   - `add_to_list.json` (fed by wool/coles missing "add" actions)
   - `searched_items.json` (NEW — fed by any midweek live-search add)

**Midweek:** searches keep working as today; new items auto-queue on
`searched_items`. An urgent flush command can run any day (opens a live
window, user does 2FA if needed, drains both queues at once).

---

## 2. Verified technical foundation (from 2026-08-28 hands-on tests)

| Test | Result |
|---|---|
| WW search API via curl_cffi, no login | ✅ HTTP 200 (already in use) |
| WW `/apis/ui/mylists` + stale cookie | ❌ 403 (Akamai blacklists stale cookies) |
| WW `/apis/ui/mylists` + no cookie | ✅ 200 with empty list — **Akamai is not the wall; identity is** |
| Coles search via Scrape.do (`super=true`, `geoCode=au`) | ✅ works |
| Coles saved-list page rendered via Scrape.do / ZenRows (not logged in) | ⚠️ page renders, no data — list is private; login required |
| WW + Coles pages in **headless** Chrome | ❌ blocked / empty shells |
| WW + Coles pages in **headed** real Chrome, local residential AU IP | ✅ **HTTP 200 both** |
| Scrape.do `setCookies` forwarding syntax | ✅ validated via echo test |

**Conclusion:** the only reliable login environment is a visible real
Chrome on the user's local machine. All authenticated work must therefore
happen inside that window (page-context API calls inherit the session and
all security tokens automatically — safer than replaying cookies in
external tools).

---

## 3. Components

### 3.1 `session_refresh.py` (NEW — the live window driver)

One script, three phases, run in a visible Chrome window using a
**dedicated persistent Playwright profile** (survives restarts; keeps
"remember this device" trust; never used for daily browsing):

```
python grocery_price_cli.py live-refresh [--flush-only] [--fetch-only]
```

**Phase A — establish session (skipped automatically if still valid):**
1. Launch headed Chrome with the persistent profile; inject last saved
   cookies if present.
2. Open Woolworths → detect login state (call `/apis/ui/mylists` from page
   context; non-empty `Response` = logged in). If not logged in: fill
   email/password from `.env` (Chrome may also offer saved passwords),
   pause with a console message "Complete 2FA in the window…", wait for
   the redirect, verify.
3. Same for Coles (login state check via the customer/list API; exact
   check endpoint captured in discovery, §3.4).
4. Export all cookies + the login timestamp to
   `data/session_state.json` (never printed, never committed).

**Phase B — fetch lists (default; `--flush-only` skips):**
5. Woolworths: enumerate `/apis/ui/mylists` from page context; exact-match
   names "Price Compare" and "Special list (28)" (list available names on
   mismatch). Fetch items per list via the list-items API; batch product
   details where the API requires it. Save raw snapshots to
   `data/live_snapshots/YYYY-MM-DD_ww_<list>.json`.
6. Coles: navigate to the saved-list URL (existing `COLES_LIST_URL`) OR
   call the list API from page context — whichever discovery (§3.4)
   confirms; capture the product JSON (Next.js data or API response).
   Snapshot to `data/live_snapshots/YYYY-MM-DD_coles_PriceCompare.json`.
7. Convert snapshots to `ProductItem` lists (WW specials data is richer
   than the docx markers: `IsOnSpecial` / `WasPrice` / `SavingsAmount`
   come straight from the API).

**Phase C — flush queues (default; `--fetch-only` skips):** see §3.3.

Then close the browser. Phase order guarantees the fetch happens even if
the flush fails, and vice-versa (each phase is independently fault-tolerant;
one failing phase never aborts the others).

### 3.2 Wednesday wiring — `wednesday --source live` (NEW flag)

`grocery_price_cli.py wednesday` gains `--source live|docx`
(**default `docx` — the current method stays the default**):

- `--source live`: instead of parsing `.docx` files, steps 1–2 read the
  snapshots produced by `live-refresh` (which `wednesday --source live`
  invokes first, unless snapshots from today already exist). Everything
  after step 2 — match, sync, unmatched/missing generation, scp, Telegram
  — is the existing, unchanged pipeline.
- The specials Telegram report (step 8) uses the live "Special list (28)"
  snapshot instead of `Woolworths_Specials.docx` (richer, no paste step).
- `--source docx`: byte-for-byte today's behaviour. **Revert = simply not
  passing the flag.**

### 3.3 Website-add queues and the flush

**Queue 1 — `add_to_list.json` (EXISTS, behaviour unchanged):**
fed by wool/coles missing `add` actions; price written immediately,
keyword intentionally left empty (user's deliberate loop — the item must
resurface in next week's unmatched list; **this loop is preserved
exactly**).

**Queue 2 — `searched_items.json` (NEW):**
- Fed automatically wherever a live-search result becomes a new sheet row
  (the `add_product_row` path used by `map unmatched --add` and
  live-search adds). Entry:
  ```json
  {"store": "woolworths", "keyword": "<exact store product name>",
   "store_product_id": "<WW ArticleId / Coles product id, captured at
                        search time — makes the flush immune to re-search
                        drift>", "generic_name": "<Col A>", "added_at": "..."}
  ```
- Dup guard: store + normalized generic name (same rule as add_to_list).
- File lives beside add_to_list.json; same atomic-write pattern.

**The flush (`live-refresh` Phase C, also runnable alone):**
1. Load both queues; group by store; target list = the store's
   **"Price Compare"** list (never the Specials list).
2. Add each item via the captured add-to-list API, called **from the
   logged-in page context** (tokens/CSRF come along automatically).
   Throttle: ~1 item per 1.5 s + small jitter (a 40-item burst must look
   human, not machine-gun).
3. Per-item result is logged to `data/live_flush_log.json`. Successes are
   removed from the queue; failures stay with a retry count and a
   human-readable reason.
4. `add-to-list show/done` keeps working unchanged (manual fallback and
   confirmation view).
5. **No keyword (Col I/J) writes, ever, from the flush** — the item
   resurfaces via next week's fetch → unmatched → user maps it. Exactly
   the user's designed loop, minus the website clicking.

**Urgent midweek flush:** `python grocery_price_cli.py live-refresh
--flush-only` — opens a live window; if the saved session is still valid
it flushes with zero prompts, otherwise one 2FA per store. Drains BOTH
queues at once (per user: "all added at once if more than 1 items").

### 3.4 One-time discovery (built into the first run)

The add-to-list API calls for both stores and the exact Coles list-data
path are not publicly documented. First run of `live-refresh` therefore
includes a guided discovery mode (also re-runnable via
`live-refresh --recapture`):

- The script turns on network recording, prints "Add ONE item to your
  Price Compare list in the open window…", watches the network call the
  browser makes, and saves the method/URL/body shape to
  `data/live_api_capture.json`.
- Repeat once per store (WW + Coles). Two minutes, once ever. WW's
  endpoint shape is partially known from public reverse-engineering; the
  capture confirms or corrects it. Coles is captured fresh.

### 3.5 Session heartbeat (measurement only, no behaviour)

After each refresh, a tiny background check (curl_cffi with saved cookies;
1 request per store, a few times a day via the same cron that already
exists for reminders) logs "session alive/dead" to
`data/session_heartbeat.log`. Purpose: replace guesswork about session
lifetime with data (the open question from this week's discussion). It
never triggers logins or purchases of anything; it only informs the user
via the Wednesday report ("WW session lasted 6 days this week").

---

## 4. Failure handling & budget guards (user-mandated)

**Prime rule: nothing ever retries unlimited.** Every network action has a
hard attempt cap, every failure produces exact names + a manual path
forward, and no failure can silently consume scraping credits.

### 4.1 Attempt caps per run

| Action | Max attempts per run | On exhaustion |
|---|---|---|
| Page load (login page, list page) | 2 | Store marked failed |
| Login wait (2FA pause) | No retries — waits up to 3 min for the user, then aborts | Store marked failed |
| List fetch API call (in-page) | 1 | Store marked failed |
| Add-to-list item (flush) | 1 (+1 extra ONLY for a transient network error, never for 401/403) | Item stays queued |
| Scrape.do search (existing search/map flows) | Unchanged today + global per-run cap (§4.4) | Stop with a clear message |

### 4.2 Wednesday fetch failure → clean stop + manual instructions

- **All-or-nothing:** if ANY store's fetch fails (login refused, page
  blocked, no data), live mode aborts **before any sheet write** — the
  sync never runs on partial data.
- The stop message names the failed store and reason, then prints the
  exact manual steps: *"Live fetch failed for <store> (<reason>).
  Manual method: paste your lists into the Word docs as before and run
  `wednesday` (no flag) — everything else is unchanged."*
- The manual (docx) method is permanently available: it is the DEFAULT
  mode and is never modified or removed by this project.
- Any snapshots that DID succeed stay on disk — nothing is lost, and the
  manual run is not affected by them.
- Non-zero exit code; the Telegram summary (if sent) states
  "LIVE FETCH FAILED — manual method required".

### 4.3 Flush failure → exact names + user's choice

- Flush processes items one by one; **one item's failure never stops the
  others** (except session death, below).
- After the flush, the report prints **the exact store product names** of
  every failed item, grouped by store, with the failure reason, e.g.:
  *"Failed at Coles (2): 'Oak Chocolate Milk 750ml' (404 not found),
  'V Energy Watermelon Candy 500ml' (timeout). They remain on the queue
  — they will be retried at the next flush, or add them manually on the
  website and clear them with `add-to-list done`."*
- Failed items stay queued automatically ("add them back to try another
  time" is the default behaviour — no action needed).
- **3-strike rule:** an item that fails 3 flushes is parked — still
  listed in every future flush report as "needs manual attention", never
  auto-dropped, never retried forever.
- **Session death mid-flush** (401/403 on any add): abort the remaining
  flush immediately (no hammering a dead session), report which items
  were added and which remain queued.

### 4.4 Scrape.do credit guards

- The authenticated paths — list fetch, flush, heartbeat — **never use
  Scrape.do**. They run in the user's own browser or via curl_cffi with
  saved cookies: zero credits by design. **No Scrape.do fallback may ever
  be added to these paths** (binding).
- Heartbeat Coles check is curl_cffi best-effort; if blocked, it logs
  "unknown" — it must NOT fall back to Scrape.do.
- Defensive global cap on the existing Scrape.do search flows: a per-run
  request limit (module constant, default 40) — exceeding it stops the
  flow with a clear message instead of burning credits in a loop.

---

## 5. The user's Wednesday, before vs after

| Step | Today | After |
|---|---|---|
| Copy lists into Word docs | Manual, both stores | **Gone** |
| Run pipeline | `wednesday` (reads docx) | `wednesday --source live` (opens Chrome; 2FA ×1–2) |
| Review unmatched (forget/add) | Telegram/local map flow | Unchanged |
| Review wool/coles missing (add) | Unchanged + remember website items | Unchanged; items queue on add_to_list |
| Add queued items to store websites | Manual clicking on both sites | `live-refresh --flush-only` (usually no 2FA) |
| Midweek "I want item X now" | Search only; item never reaches store list | Search auto-queues; optional urgent flush |

---

## 6. File boundaries (allowed scope for 02 Plan / 03 Code)

**May create:**

| File | Purpose |
|---|---|
| `grocery-price-tracker/extractors/session_refresh.py` | Live-window driver: login, cookie export, in-page fetch, discovery capture |
| `grocery-price-tracker/extractors/live_list_fetch.py` | Snapshot → ProductItem conversion (WW + Coles) |
| `grocery-price-tracker/core/searched_items.py` | Queue 2 module (mirror of `add_to_list.py`: atomic IO, dup guard, render) |
| `grocery-price-tracker/tests/test_searched_items.py` | Queue module tests |
| `grocery-price-tracker/data/live_api_capture.json` | Discovery output (runtime, gitignored) |
| `grocery-price-tracker/data/live_snapshots/` | Weekly raw list snapshots (runtime, gitignored) |

**May edit (surgical only):**

| File | Change |
|---|---|
| `grocery_price_cli.py` | ① `live-refresh` subcommand (flags `--flush-only` / `--fetch-only` / `--recapture`). ② `wednesday --source live\|docx` (default docx) — input swap in steps 1–2 + specials source in step 8 ONLY. ③ One hook: queue-on-add in the `add_product_row` live-search path |
| `grocery-price-tracker/tests/test_cli.py` | Tests for the flag routing + queue hook (mocked, no network) |
| `claw-skills/grocery-price/SKILL.md` | New command rows + NL routing ("run live refresh", "flush my lists") |
| `grocery-price-tracker/README.md` | Document the live mode + revert instructions |

**Must NOT touch:** `core/sheets_sync.py` (except nothing), `core/lookup.py`,
`core/name_matcher.py`, `core/add_to_list.py` behaviour, `core/missing_items_tracker.py`,
the docx parsers (they remain the default path), `telegram_gateway/`,
any `.docx` file, `.env`, the missing-list generation logic, and the
add_to_list keyword-Empty design.

**Revert guarantee:** default `docx` mode; all new code in new files;
`--source live` is opt-in; deleting/ignoring new files restores today's
behaviour byte-for-byte. Git tag before implementation marks the
pre-trial state.

---

## 7. Trial-week protocol (user-mandated safety)

1. **Day 0:** implementation lands; git tag `pre-live-trial`. First
   `live-refresh` run WITH the user present (discovery capture happens
   here).
2. **Wednesday 1:** run `wednesday --source live`. Then run the old docx
   flow in parallel (paste as usual, run plain `wednesday`) and compare
   the two sync reports — item counts and prices must match.
3. **During the week:** normal searches; verify searched_items queue
   accumulates; run one urgent `live-refresh --flush-only`; verify items
   appear on the actual store lists (next fetch / store website).
4. **Wednesday 2:** repeat live run; check heartbeat log for real session
   lifetimes.
5. **Decision:** keep live mode (flip default via one config line) or
   revert (stop passing the flag). Either way nothing is lost.

**Failure criteria (auto-revert):** live fetch returns unusable data
twice, or the flush damages a store list (wrong items) once. The queues
and docx mode make any failure non-destructive.

---

## 8. Test plan (02 Plan will expand)

1. `searched_items` module: mirror of the shipped add_to_list test matrix
   (atomic IO, dup guard, render, remove-on-flush semantics).
2. `--source` flag routing: docx default untouched; live mode reads
   snapshots; missing snapshots → clear error, docx NOT silently used.
3. Queue hook: live-search add → exactly one queued entry; non-live adds
   and wool/coles missing adds do NOT feed searched_items.
4. Flush logic (mocked API): success removal, failure retention + retry
   count, throttling pace, per-store grouping, "Price Compare"-only
   targeting.
5. Snapshot conversion: WW specials fields → ProductItem specials
   semantics (IsOnSpecial/WasPrice/SavingsAmount); Coles JSON →
   ProductItem (reuse existing `_parse_search_result` shape).
6. No test may hit the network or real stores.
7. Failure modes (mocked): any store's fetch failure aborts live mode
   BEFORE any sheet write; stop message names the store/reason and the
   manual docx instructions; successful snapshots preserved on disk.
8. Flush failure handling: failed items retained with reason + attempt
   count; exact names in the report; 3-strike park; session-death abort
   leaves remaining items queued; one failure never blocks other items.
9. Credit guard: per-run Scrape.do cap stops the flow with a message;
   fetch/flush/heartbeat code paths contain no Scrape.do calls
   (assert-by-grep test).

---

## 9. Decisions already made (binding — do not re-litigate)

1. Batch-over-interactive: weekly (plus urgent) one-shot flushes; no daily
   login attempts. (User decision, 2026-08-28.)
2. Old method stays default; live mode is opt-in via flag for the whole
   trial week. (User-mandated revert capability.)
3. Two queues, one flush: `add_to_list.json` (unchanged) +
   `searched_items.json` (new); flush drains both; targets each store's
   "Price Compare" list only.
4. **No Col I/J keyword writes from the flush** — the resurface-through-
   unmatched loop is intentional and preserved.
5. Adds run from the logged-in page context (not replayed cookies) for
   maximum token compatibility.
6. WW lists: "Price Compare" + "Special list (28)"; Coles: "Price
   Compare". Exact names confirmed at runtime by enumeration; mismatch
   prints available names instead of guessing.
7. Session lifetime is treated as unknown; heartbeat measures it; no
   behaviour depends on it.
8. Cost target: $0/month new spend. Scrape.do unchanged (search only);
   no ZenRows role.
9. **No unlimited retries anywhere** (§4.1 attempt caps). Wednesday fetch
   failure = clean stop before any sheet write + exact manual docx
   instructions; the manual method is permanently the default and is
   never removed. (User-mandated, 2026-08-28.)
10. **Flush failures report exact item names**; failed items stay queued
    for a later flush by default, or the user adds them manually and
    clears them; 3-strike park rule; session death aborts immediately.
    (User-mandated, 2026-08-28.)
11. **Authenticated paths are Scrape.do-free** — list fetch, flush, and
    heartbeat can never consume credits; global per-run cap protects the
    existing search flows.
