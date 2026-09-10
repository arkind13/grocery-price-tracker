# Pre-Arch — Single Input Document for 01 Architect

- **Date:** 2026-08-29 (rev 2 — user feedback applied, live-lists spec merged)
- **Author:** 00 Tester Agent
- **Contents:**
  - **Part A** — Diagnosis evidence (compare failures, 2026-08-28)
  - **Part B** — The fixes (final form, per user decisions 2026-08-29)
  - **Part C** — Live-lists pipeline spec (full content of the former
    `architecture-spec-live-lists.md`, merged here, with three marked
    DELTAS from the user)
- **Original spec file:** moved to `old md/architecture-spec-live-lists.md`
  — this document supersedes it. Nothing else may be lost: every section,
  table, and binding decision from that spec exists in Part C.

---

# PART A — Diagnosis (what happened on 2026-08-28, 21:51–21:57 UTC)

Source: Claw session `3bb9638f-2a9e-402d-a653-3e8fb4248305` on
myvps + live re-testing inside openclaw-core on 2026-08-29.

### Exchange 1 — user: "Is garden soil on discount anywhere"

The agent never ran the grocery CLI. It called `web_search` (provider
error), then `web_fetch` on woolworths.com.au (Akamai 403) and
coles.com.au (empty), then told the user it could not pull data. The
CLI (`compare --items "garden soil"`) succeeded two minutes later.
→ Routing gap: that phrase is not in the SKILL.md mapping table and no
hard rule forbids browsing store sites for prices.

### Exchange 2 — user: "Can you compare coles vs woolworths pricing"

- First CLI attempt died at the agent's 30 s tool timeout (the call
  needs ~34 s with current Scrape.do settings — see B4).
- Second attempt returned:
  `Woolworths $20.90 / Coles $6.60 (was $13.20)` and declared Coles
  cheaper by $14.30.
- Verified identities (by re-running the store searches):
  - Woolworths "$20.90 garden soil" = **3x Gardenmaster hand-tool set**
    (raw $22.00 → 5% = $20.90, matches the report exactly).
  - Coles "$6.60 (was $13.20) garden soil" = **Seasol 1.2L liquid
    garden treatment**.
  - Neither is soil; the tool set was "compared" against a fertiliser
    bottle.
- The agent also labelled the WW price "(sheet price)" — both prices
  were live (no garden-soil row exists in the sheet); compare output
  does not label sources, so provenance was invented.
- Root cause: lookup Step 5 takes the **first live result per store**
  with no name/size vetting; the report shows only the query name.

### Exchange 3 — user: "Can you give me the name of product in coles"

- `search --product "garden soil"` → `[coles_extractor] Scrape.do
  returned HTTP 502` (three 502s in a row, 21:55–21:57).
- The agent then claimed the $6.60 price was "on the sheet" (false)
  and speculated product names.
- Key validity: the Scrape.do key is VALID (live call → HTTP 200 the
  next day); the failure window was transient. Errors print to stderr
  only, so the outage never appeared in what the user saw.

### Extractor facts verified on 2026-08-29

- Coles search results carry `size` (`1.2L`, `600mL`, `180g`,
  `1 each`) and sometimes a comparable price (`$30.56/ 1kg`).
- WW results carry `PackageSize` + `CupString`.
- → UOM data ALREADY EXISTS; the comparator discards it.

---

# PART B — The fixes (user-approved final form)

## B1 — UOM comparison rule (user decision, binding)

**No per-unit price comparisons anywhere.** The rule is:

1. Both stores stocked the **same item** (same normalised size) →
   compare, show 🏆 winner normally.
2. Sizes differ but are **within 20%** (|a−b|/min(a,b) ≤ 0.20, same
   unit family: volume↔volume, weight↔weight, count↔count) → compare,
   show both sizes on the line, 🏆 allowed.
3. Sizes differ by **more than 20%**, or unit families differ, or a
   size is missing on either side → **NOT comparable.** The item must
   print, in the user's own wording pattern:

```
1. aluminium foil
   ⚠️ No matching product — sizes don't compare.
      Woolworths: Aluminium Foil 10m
      Coles:      Aluminium Foil 150m
```

   - The item is excluded from totals and can never win a 🏆.
   - NO $/L, $/kg, $/100mL lines. The comparison "does not stand", so
     no derived unit price is shown either.
   - Multipacks parse to totals (`6 x 170g` → 1020 g) before the rule
     is applied.
   - `1 each` / count items compare only count-vs-count.

Implementation: new pure module `core/uom.py`
(`parse_size`, `size_families_match`, `within_20pct`, verdict enum)
+ tests. No extractor changes needed — the fields already exist.

## B2 — Result selection (user decision, 2026-08-29: NO hard name filter)

**The B1 UOM rule is the ONLY gate.** There is no hard name-token
rejection — the user rejected that: it could discard genuine matches
or fail on spelling errors in the query.

- **Ranking only:** among a store's results, relevance (word overlap
  between query and product name, tolerant to singular/plural and
  small typos) decides which result is shown FIRST — it never
  disqualifies a result.
- **Gate:** the top-ranked result is used only if B1 passes (same
  size or within 20%). If it fails, try the next-ranked result; the
  first one that passes B1 is the price shown. If none passes, the
  store gets no price and the B1 "No matching product" block prints
  the closest found product (1 per store, expandable — B3).
- Spelling errors in the query are absorbed by the store's own search
  engine (fuzzy) plus the tolerant ranking; the 20% size rule remains
  the real protection against wrong-product comparisons.
- Sanity ceiling stays as a tiebreaker only: among B1-passing
  results, prefer ones within 10× of the other store's per-item
  price.

## B3 — Show what was actually priced + queue removal option

1. Every compare/search line shows the matched product, size, and
   source:

```
1. garden soil
   🟢 Woolworths  $20.90 — Debco 25L Garden Soil (live)
   🔴 Coles       $8.40  — Coles 30L Garden Soil (live)
```

   - `(sheet)` / `(live)` tag on every store line; SKILL.md relays it
     verbatim and never calls anything a "sheet price" unless the tag
     says so. Never guess names when live search is down.
2. **"No matching product" block shows exactly 1 closest product per
   store (user decision, 2026-08-29) plus an expand option:**

```
1. aluminium foil
   ⚠️ No matching product — sizes don't compare.
      Woolworths: Aluminium Foil 10m
      Coles:      Aluminium Foil 150m
   💬 Reply 'expand' to see more results.
```

   - `expand` re-runs the search and shows more results per store —
     **display-only.** Expanded results are NEVER auto-added to the
     sheet or the searched-items queue.
3. **Nothing is ever auto-queued (user decision, 2026-08-29).**
   `compare` / `search` / `expand` results are display-only by
   default. A product reaches the sheet AND the `searched_items`
   queue only when the user explicitly points at it — "add item 2",
   "add the Debco one" → CLI: `search --product "X" --add-item 2`
   (writes via the existing `add_product_row` path, which feeds
   Queue 2). This removes the "I forgot to exclude and everything
   got added" failure mode entirely.
 4. **Commands are always printed in the output (user request: "make
    sure those commands are in the output I might not remember").**
    Every reply that queues something ends with the exact words to
    undo it, and every queue view ends with the exact words to manage
    it.

 5. **Removal by unique 5-letter code, not position numbers (user
    decision, 2026-08-29).** Positional "remove 1" breaks in a long
    Telegram chat — after 5 messages, or after another search, nobody
    can be sure which "1" was meant, and two searches' numbers can be
    mixed up. Instead:

    - Every queued item gets a **unique 5-letter code** (e.g.
      `APCH`, `MIVOS`), generated consonant-vowel alternating for
      pronounceability, alphabet A–Z only (no digits, no look-alike
      letters — exclude `I`, `O` to avoid 1/0 confusion).
    - **Uniqueness is enforced against the whole queue file**, plus a
      small tombstone set of codes removed in the last 7 days (so a
      stale "remove X" can never hit a freshly re-issued code). Each
      code appears exactly once in the list at any time.
    - The code is printed **at the end of the product line** wherever
      the item appears — in the queue confirmation, in
      `searched-items show`, and in every queued-add confirmation:
      ```
      Queued for Wednesday: 'Debco 25L Garden Soil' (Woolworths) [APCH]
      💬 Reply 'remove APCH' if this isn't the right product.
      💬 'show searched items' any time to review the queue.
      ```
    - Removal works **no matter how many chats have passed** — 10
      chats later, "remove APCH" still removes that exact item:
      ```
      searched-items show                    → list with codes (store, name, size [CODE])
      searched-items remove --items "APCH"   → removes that item
      searched-items remove --items "APCH,MIVOS,ROKAD"   → multiple, comma-separated
      searched-items clear                   → empties the whole queue
      ```
    - Codes are case-insensitive (`apch` = `APCH`), spaces around
      commas are trimmed.
    - Unknown code → clear error that lists the CURRENT valid codes
      (so a typo is self-correcting), e.g.
      `⚠️ Code 'APC' not found. Current queue codes: APCH, MIVOS.`
    - Codes are stable for the life of the queue entry: shown once at
      queue time, re-shown by `show`, never changed until removal or
      the Wednesday flush consumes the entry.

    Removal works any time before Wednesday's flush.

## B4 — Scrape.do: the proper fix (two test rounds, 13/13 success)

**Design goal (user-mandated): the user never sees errors.** Failures
are absorbed invisibly by a tested call chain; a visible failure
requires a total Scrape.do outage.

### Round 1 (2026-08-29, 7 calls)

| Test | Settings | Result | Latency |
|---|---|---|---|
| T1 | **current code** (`country=au`, fixed session `coles_extractor`, render) | 200, 4 results | **35.4 s** |
| T2–T6 | `geoCode=au` variants, fresh/no session | 200 ×6, 4 results each | 5.5–12 s |

### Round 2 (2026-08-29, 5 calls)

| Test | Settings | Result | Latency |
|---|---|---|---|
| M1 | **NO JS render** (`super=true`, `geoCode=au`, fresh session) | 200, full `__NEXT_DATA__`, 4 results | 7.0 s |
| M2 | render + `waitForSelector=#__NEXT_DATA__` | 200, 4 results | 5.6 s |
| M3–M5 | 3 back-to-back calls, fresh session each | 200 ×3, 4 results | 8.3 / 19.7 / 23.8 s |

**Key discovery (M1): Coles embeds the full search results in the
server-rendered HTML — the JS-render step is unnecessary.** Dropping
`render=true` removes the slowest, most failure-prone stage of the
call (and the most expensive per credit).

### The binding call recipe (evidence-based)

1. **Parameters:** `super=true`, `geoCode=au`, **no `render`**, no
   fixed `wait`, fresh `session=coles_<utcepoch>_<n>` per call, no
   `country=` param, client timeout 60 s.
2. **Silent retry chain:** on 5xx/timeout only → retry with a NEW
   session id, backoff 3 s then 6 s — **3 attempts total, all
   invisible to the user.** Three consecutive failures across three
   different exit IPs is a Scrape.do-wide outage, nothing the client
   can fix by retrying more. Never retry 401/403.
3. **If all 3 attempts fail (last resort only):** show the
   **Woolworths-only answer** (user decision, Q2, 2026-08-29) with
   one line `⚠️ Coles not checked (unavailable)`. No retry loops, no
   error dumps, no partial Coles data.
4. **Circuit breaker** `data/scrapedo_health.json` (credit guard, not
   user-facing): opens after 3 consecutive failed CHAINS in 10 min →
   skip Coles calls entirely for 10 min (fail fast to Woolworths-only
   mode), reset on first success.
5. **Per-run cap** 40 Scrape.do calls (module constant) per
   architecture-spec §4.4.
6. SKILL.md: tool-call timeouts for `compare`/`search`/`recipe` ≥90 s.

With 13/13 observed success and 3 rotating-IP attempts per query, the
expected user-visible failure rate is effectively zero outside a
provider-wide outage.

## B5 — Web search is NOT being turned off (clarification)

The rule is narrow: **questions about Woolworths/Coles prices,
specials, or discounts must go through the grocery CLI** — never
`web_search`/`web_fetch` on the store sites (they block bots; the CLI
has proper channels).

- Items **not on the sheet** are exactly what the CLI's live search
  handles: Woolworths public API + Coles via Scrape.do (that is how
  "garden soil" got live prices at all). Nothing changes for them.
- Ordinary web search stays ON for everything else (news, recipes,
  "who delivers…", non-grocery questions).
- SKILL.md adds the NL mapping "is X on special/discount/cheap
  anywhere" → `compare --items "X"` and the hard no-browsing rule.

## B6 — Products genuinely not stocked at one store (existing NA commands — preserved)

The mechanism the user asked about **already exists and stays
unchanged** (verified in `grocery_price_cli.py` lines 115–116,
2043–2056 + `core/sheets_sync.mark_not_available`):

- During a **resolve wool / resolve coles** session, when an item on
  the missing list genuinely doesn't exist at that store (e.g. a
  Woolworths-only product line), reply **`na`**.
- The agent runs `map wool --na` (or `map coles --na`), which writes
  literal **`NA`** into the store's keyword column (I/J) AND price
  column (E/D) for that row.
- `NA` counts as populated → the row is **permanently excluded from
  that store's missing list** — it never reappears on future
  Wednesdays.
- The session auto-advances to the next missing item.
- Also available outside a session:
  `python3 grocery_price_cli.py map coles --na` (applies to the
  current list position).

This project must NOT alter that behaviour; the missing-list
generation logic and `--na` path are explicitly out of scope
(Part C.6 "Must NOT touch"). SKILL.md keeps the "na" NL mapping and
the session hint text ("Reply `add` …, `na` if not available at this
store …").

---

# PART C — Live-lists pipeline spec (merged from architecture-spec-live-lists.md)

All content below is the former spec, kept intact. Three user-mandated
changes are integrated at their natural places and marked
**DELTA-1/2/3 (user, 2026-08-29)**. Where no DELTA appears, the
original text stands unchanged.

## C.1 Goal (plain language)

Today's Wednesday run depends on two manual steps: copy-pasting saved
lists from Woolworths and Coles into Word documents, and manually
adding missing items to the store websites. Both exist because the
stores block scripts from logged-in areas.

New reality (verified by hands-on testing 2026-08-28):

- A **visible, real Chrome window** on the user's local PC passes both
  stores' robot checks (headless is blocked; headed is not).
- Woolworths' list APIs answer plain script calls fine — the only
  missing piece is a **live session cookie** (fresh cookie = works;
  stale cookie = 403; no cookie = 200 but empty).
- The user reports both stores log them out almost daily. The plan
  therefore assumes **nothing about session lifetime**: everything
  that needs login happens inside one short "live window", and
  everything else queues.

**One live window per Wednesday (plus optional urgent windows) does:**

1. Log in to both stores once (user present, 2FA once each).
2. Fetch all three saved lists with live prices:
   - Woolworths: **"Price Compare"** and **"Special list (28)"**
   - Coles: **"Price Compare"**
3. Sync the sheet, generate the three lists (unmatched / wool missing /
   coles missing) — exactly as today.
4. Flush both website-add queues in one batch:
   - `add_to_list.json` (fed by wool/coles missing "add" actions)
   - `searched_items.json` (fed by any midweek live-search add)

**Midweek:** searches keep working as today; new items auto-queue on
`searched_items`. An urgent flush command can run any day (opens a live
window, user does 2FA if needed, drains both queues at once).

**DELTA-1 (user, 2026-08-29) — Wednesday order is ADD FIRST, THEN
COPY.** Inside the Wednesday live window, the flush (step 4) must run
**before** the fetch (step 2): midweek-searched items must already be
on the store "Price Compare" lists, so the fetched/copied lists include
them and the sheet sync prices them in the same run. Phase order in
C.3.1 below is updated accordingly; the phases remain independently
fault-tolerant (a failed flush does not stop the fetch, and vice versa).

## C.2 Verified technical foundation (from 2026-08-28 hands-on tests)

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
Chrome on the user's local machine. All authenticated work must
therefore happen inside that window (page-context API calls inherit
the session and all security tokens automatically — safer than
replaying cookies in external tools).

## C.3 Components

### C.3.1 `session_refresh.py` (NEW — the live window driver)

One script, three phases, run in a visible Chrome window using a
**dedicated persistent Playwright profile** (survives restarts; keeps
"remember this device" trust; never used for daily browsing):

```
python grocery_price_cli.py live-refresh [--flush-only] [--fetch-only]
```

**Phase A — establish session (skipped automatically if still valid):**
1. Launch headed Chrome with the persistent profile; inject last saved
   cookies if present.
2. Open Woolworths → detect login state (call `/apis/ui/mylists` from
   page context; non-empty `Response` = logged in). If not logged in:
   fill email/password from `.env` (Chrome may also offer saved
   passwords), pause with a console message "Complete 2FA in the
   window…", wait for the redirect, verify.
3. Same for Coles (login state check via the customer/list API; exact
   check endpoint captured in discovery, C.3.4).
4. Export all cookies + the login timestamp to
   `data/session_state.json` (never printed, never committed).

**Phase B — flush queues (DELTA-1 order: flush BEFORE fetch; see
C.3.3).** `--fetch-only` skips this phase.

**Phase C — fetch lists.** `--flush-only` skips this phase.
5. Woolworths: enumerate `/apis/ui/mylists` from page context;
   exact-match names "Price Compare" and "Special list (28)" (list
   available names on mismatch). Fetch items per list via the
   list-items API; batch product details where the API requires it.
   Save raw snapshots to `data/live_snapshots/YYYY-MM-DD_ww_<list>.json`.
6. Coles: navigate to the saved-list URL (existing `COLES_LIST_URL`)
   OR call the list API from page context — whichever discovery
   (C.3.4) confirms; capture the product JSON (Next.js data or API
   response). Snapshot to
   `data/live_snapshots/YYYY-MM-DD_coles_PriceCompare.json`.
7. Convert snapshots to `ProductItem` lists (WW specials data is
   richer than the docx markers: `IsOnSpecial` / `WasPrice` /
   `SavingsAmount` come straight from the API).

**DELTA-2 (user, 2026-08-29) — Pagination: fetch ALL pages of every
list, both stores.** Lists longer than one page must be walked to the
end before the snapshot is considered complete:

- **Woolworths:** the list-items API is paged (page offset / hasMore
  cursor — exact shape confirmed during first-run discovery). Loop
  `while hasMore` (or until a page returns fewer items than the page
  size), appending every page's items to the same snapshot. Safety
  cap: 30 pages per list; hitting the cap logs a loud warning with
  the item count fetched so far.
- **Coles:** the saved-list page/API paginates similarly (Next.js
  query param or API cursor — capture during discovery). Same loop,
  same 30-page cap.
- After fetch, log per list: `WW 'Price Compare': 4 pages, 118 items`
  so short counts are visible immediately.
- The snapshot converter must deduplicate by product id across pages
  (stores sometimes repeat boundary items).

Then close the browser. Phase order (A → flush → fetch) guarantees the
fetched lists include everything the flush just added, while each
phase remains independently fault-tolerant; one failing phase never
aborts the others.

### C.3.2 Wednesday wiring — `wednesday --source live` (NEW flag)

`grocery_price_cli.py wednesday` gains `--source live|docx`
(**default `docx` — the current method stays the default**):

- `--source live`: instead of parsing `.docx` files, steps 1–2 read
  the snapshots produced by `live-refresh` (which `wednesday --source
  live` invokes first, unless snapshots from today already exist).
  Everything after step 2 — match, sync, unmatched/missing generation,
  scp, Telegram — is the existing, unchanged pipeline.
- The specials Telegram report (step 8) uses the live "Special list
  (28)" snapshot instead of `Woolworths_Specials.docx` (richer, no
  paste step).
- `--source docx`: byte-for-byte today's behaviour. **Revert = simply
  not passing the flag.**

### C.3.3 Website-add queues and the flush

**Queue 1 — `add_to_list.json` (EXISTS, behaviour unchanged):**
fed by wool/coles missing `add` actions; price written immediately,
keyword intentionally left empty (user's deliberate loop — the item
must resurface in next week's unmatched list; **this loop is preserved
exactly**).

**Queue 2 — `searched_items.json` (NEW):**
- Fed automatically wherever a live-search result becomes a new sheet
  row (the `add_product_row` path used by `map unmatched --add` and
  live-search adds). Entry:
  ```json
  {"store": "woolworths", "keyword": "<exact store product name>",
   "store_product_id": "<WW ArticleId / Coles product id, captured at
                         search time — makes the flush immune to re-search
                         drift>", "generic_name": "<Col A>",
   "code": "<unique 5-letter removal code, e.g. APCH — see B3.5>",
   "added_at": "..."}
  ```
- Dup guard: store + normalized generic name (same rule as
  add_to_list).
- Code assignment at queue time: unique vs the whole file + the
  7-day tombstone set (B3.5).
- File lives beside add_to_list.json; same atomic-write pattern.

**DELTA-3 (user, 2026-08-29) — queue is reviewable/removable before
Wednesday; NOTHING is ever auto-queued; removal is by unique
5-letter code.** New subcommand (see B3):

```
searched-items show
searched-items remove --items "APCH"           (or "APCH,MIVOS" — comma-separated)
searched-items clear
```

- `show` prints the queue: store · exact product name · size ·
  `[CODE]`. Offline-safe.
- Every queued item carries a unique 5-letter code (B3.5) — removal
  works after any number of intervening chats and can never be mixed
  up between searches. Unknown codes produce a self-correcting error
  listing current codes.
- `remove` deletes the given code(s) (validated all-or-nothing, same
  UX as `add-to-list done`), then re-prints the remainder.
- `clear` empties the queue (asks the Claw agent to confirm first per
  SKILL.md confirm-before-mutate rule).
- **Explicit-add-only (user decision, 2026-08-29):** the queue is fed
  ONLY by an explicit user action — `map --add` during a resolve
  session, or the new `search --product "X" --add-item N` after a
  compare/search/expand. Plain `compare`/`search`/`expand` results
  are display-only and never touch the sheet or the queue. This
  removes the "I forgot to exclude and everything got added" failure
  mode.
- Every output that queues or lists queue items prints the exact
  management words ("Reply 'remove APCH' …", "'show searched
  items'"), so the user never has to remember commands (user
  request).
- Removal works any time before the Wednesday flush; after a
  successful flush the entry is gone anyway.

**The flush (`live-refresh` Phase B, also runnable alone):**
1. Load both queues; group by store; target list = the store's
   **"Price Compare"** list (never the Specials list).
2. Add each item via the captured add-to-list API, called **from the
   logged-in page context** (tokens/CSRF come along automatically).
   Throttle: ~1 item per 1.5 s + small jitter (a 40-item burst must
   look human, not machine-gun).
3. Per-item result is logged to `data/live_flush_log.json`. Successes
   are removed from the queue; failures stay with a retry count and a
   human-readable reason.
4. `add-to-list show/done` keeps working unchanged (manual fallback
   and confirmation view).
5. **No keyword (Col I/J) writes, ever, from the flush** — the item
   resurfaces via next week's fetch → unmatched → user maps it.
   Exactly the user's designed loop, minus the website clicking.

**Urgent midweek flush:** `python grocery_price_cli.py live-refresh
--flush-only` — opens a live window; if the saved session is still
valid it flushes with zero prompts, otherwise one 2FA per store.
Drains BOTH queues at once (per user: "all added at once if more than
1 items").

### C.3.4 One-time discovery (built into the first run)

The add-to-list API calls for both stores and the exact Coles
list-data path are not publicly documented. First run of
`live-refresh` therefore includes a guided discovery mode (also
re-runnable via `live-refresh --recapture`):

- The script turns on network recording, prints "Add ONE item to your
  Price Compare list in the open window…", watches the network call
  the browser makes, and saves the method/URL/body shape to
  `data/live_api_capture.json`.
- Repeat once per store (WW + Coles). Two minutes, once ever. WW's
  endpoint shape is partially known from public reverse-engineering;
  the capture confirms or corrects it. Coles is captured fresh.
- **DELTA-2 addition:** discovery ALSO captures the pagination shape
  of each list endpoint (page param name, page size, hasMore/nextPage
  field, total-count field) for both stores, so C.3.1 Phase C can
  walk every page from week one.

### C.3.5 Session heartbeat (measurement only, no behaviour)

After each refresh, a tiny background check (curl_cffi with saved
cookies; 1 request per store, a few times a day via the same cron
that already exists for reminders) logs "session alive/dead" to
`data/session_heartbeat.log`. Purpose: replace guesswork about session
lifetime with data (the open question from this week's discussion). It
never triggers logins or purchases of anything; it only informs the
user via the Wednesday report ("WW session lasted 6 days this week").

## C.4 Failure handling & budget guards (user-mandated)

**Prime rule: nothing ever retries unlimited.** Every network action
has a hard attempt cap, every failure produces exact names + a manual
path forward, and no failure can silently consume scraping credits.

### C.4.1 Attempt caps per run

| Action | Max attempts per run | On exhaustion |
|---|---|---|
| Page load (login page, list page) | 2 | Store marked failed |
| Login wait (2FA pause) | No retries — waits up to 3 min for the user, then aborts | Store marked failed |
| List fetch API call (in-page) | 1 per **page**, pages walked in order (DELTA-2) | Store marked failed |
| Add-to-list item (flush) | 1 (+1 extra ONLY for a transient network error, never for 401/403) | Item stays queued |
| Scrape.do search (existing search/map flows) | 3 total attempts, fresh session each, 3 s/6 s backoff, silent (B4); global per-run cap below | Woolworths-only display + one ⚠️ line |

### C.4.2 Wednesday fetch failure → clean stop + manual instructions

- **All-or-nothing:** if ANY store's fetch fails (login refused, page
  blocked, no data), live mode aborts **before any sheet write** — the
  sync never runs on partial data.
- The stop message names the failed store and reason, then prints the
  exact manual steps: *"Live fetch failed for <store> (<reason>).
  Manual method: paste your lists into the Word docs as before and run
  `wednesday` (no flag) — everything else is unchanged."*
- The manual (docx) method is permanently available: it is the DEFAULT
  mode and is never modified or removed by this project.
- Any snapshots that DID succeed stay on disk — nothing is lost, and
  the manual run is not affected by them.
- Non-zero exit code; the Telegram summary (if sent) states
  "LIVE FETCH FAILED — manual method required".

### C.4.3 Flush failure → exact names + user's choice

- Flush processes items one by one; **one item's failure never stops
  the others** (except session death, below).
- After the flush, the report prints **the exact store product names**
  of every failed item, grouped by store, with the failure reason.
- Failed items stay queued automatically ("add them back to try
  another time" is the default behaviour — no action needed).
- **3-strike rule:** an item that fails 3 flushes is parked — still
  listed in every future flush report as "needs manual attention",
  never auto-dropped, never retried forever.
- **Session death mid-flush** (401/403 on any add): abort the
  remaining flush immediately (no hammering a dead session), report
  which items were added and which remain queued.

### C.4.4 Scrape.do credit guards

- The authenticated paths — list fetch, flush, heartbeat — **never use
  Scrape.do**. They run in the user's own browser or via curl_cffi
  with saved cookies: zero credits by design. **No Scrape.do fallback
  may ever be added to these paths** (binding).
- Heartbeat Coles check is curl_cffi best-effort; if blocked, it logs
  "unknown" — it must NOT fall back to Scrape.do.
- Defensive global cap on the existing Scrape.do search flows: a
  per-run request limit (module constant, default 40) — exceeding it
  stops the flow with a clear message instead of burning credits in a
  loop.
- **B4 addition (2026-08-29, tested):** `geoCode=au`, **no JS
  render**, fresh session per request, silent 3-attempt retry chain +
  circuit breaker (`data/scrapedo_health.json`) + per-run cap; on
  total failure show Woolworths-only with one ⚠️ line.

## C.5 The user's Wednesday, before vs after

| Step | Today | After |
|---|---|---|
| Copy lists into Word docs | Manual, both stores | **Gone** |
| Run pipeline | `wednesday` (reads docx) | `wednesday --source live` (opens Chrome; 2FA ×1–2) |
| Review unmatched (forget/add) | Telegram/local map flow | Unchanged |
| Review wool/coles missing (add) | Unchanged + remember website items | Unchanged; items queue on add_to_list |
| Add queued items to store websites | Manual clicking on both sites | `live-refresh --flush-only` (usually no 2FA); on Wednesdays the flush runs FIRST, then lists are copied (DELTA-1) |
| Midweek "I want item X now" | Search only; item never reaches store list | Search auto-queues (reviewable via `searched-items show/remove`, DELTA-3); optional urgent flush |

## C.6 File boundaries (allowed scope for 01 Plan / 02/03)

**May create:**

| File | Purpose |
|---|---|
| `grocery-price-tracker/extractors/session_refresh.py` | Live-window driver: login, cookie export, in-page fetch (all pages), discovery capture |
| `grocery-price-tracker/extractors/live_list_fetch.py` | Snapshot → ProductItem conversion (WW + Coles, dedup across pages) |
| `grocery-price-tracker/core/searched_items.py` | Queue 2 module (mirror of `add_to_list.py`: atomic IO, dup guard, render, remove-by-code/clear, 5-letter code generator with uniqueness + tombstones) |
| `grocery-price-tracker/core/uom.py` | Size parser + 20% rule verdicts (B1) |
| `grocery-price-tracker/tests/test_searched_items.py` | Queue module tests (incl. remove/clear) |
| `grocery-price-tracker/tests/test_uom.py` | UOM parser + verdict tests |
| `grocery-price-tracker/tests/test_lookup_uom.py` | Selection/ranking + UOM-gate tests (no network) |
| `grocery-price-tracker/data/live_api_capture.json` | Discovery output incl. pagination shapes (runtime, gitignored) |
| `grocery-price-tracker/data/live_snapshots/` | Weekly raw list snapshots (runtime, gitignored) |
| `grocery-price-tracker/data/scrapedo_health.json` | Circuit-breaker state (runtime, gitignored) |

**May edit (surgical only):**

| File | Change |
|---|---|
| `grocery_price_cli.py` | ① `live-refresh` subcommand (flags `--flush-only` / `--fetch-only` / `--recapture`). ② `wednesday --source live\|docx` (default docx) — input swap in steps 1–2 + specials source in step 8 ONLY. ③ One hook: queue-on-add in the `add_product_row` live-search path (explicit adds only). ④ `searched-items` subcommand (show/remove/clear). ⑤ Compare report: identity/provenance/UOM verdict lines + 1-per-store found-block + expand (B1–B3). ⑥ `search --add-item N` explicit-add flag |
| `grocery-price-tracker/core/lookup.py` | Step 5 candidate selection: tolerant ranking + UOM gate (B2) — Steps 1–4 matching semantics unchanged |
| `grocery-price-tracker/core/price_comparator.py` | `BasketItem` matched name/size/source fields + report changes (B1/B3); non-comparable items excluded from totals |
| `grocery-price-tracker/extractors/coles_extractor.py` | Scrape.do recipe: `geoCode=au`, NO render, fresh session per call, silent 3-attempt retry chain, circuit breaker, per-run cap (B4) — search path only |
| `grocery-price-tracker/tests/test_cli.py`, `test_comparator.py`, `test_lookup.py` | Tests for all the above (mocked, no network) |
| `claw-skills/grocery-price/SKILL.md` | New command rows + NL routing (live refresh, flush, searched-items, remove; "on discount anywhere"; ≥90 s timeouts; no-browsing hard rule; relay provenance tags verbatim) |
| `grocery-price-tracker/README.md` | Document live mode, searched-items queue, revert instructions |

**Must NOT touch:** `core/sheets_sync.py`, `core/lookup.py` Steps 1–4
matching semantics (only Step 5 selection changes), `core/name_matcher.py`,
`core/add_to_list.py` behaviour, `core/missing_items_tracker.py`,
the docx parsers (they remain the default path), `telegram_gateway/`,
any `.docx` file, `.env`, the missing-list generation logic, and the
add_to_list keyword-Empty design.

**Revert guarantee:** default `docx` mode; all new code in new files;
`--source live` is opt-in; deleting/ignoring new files restores today's
behaviour byte-for-byte. Git tag before implementation marks the
pre-trial state.

## C.7 Trial-week protocol (user-mandated safety)

1. **Day 0:** implementation lands; git tag `pre-live-trial`. First
   `live-refresh` run WITH the user present (discovery capture happens
   here, incl. pagination shapes).
2. **Wednesday 1:** run `wednesday --source live` (flush runs FIRST —
   DELTA-1; verify the freshly flushed items appear in the fetched
   lists). Then run the old docx flow in parallel (paste as usual, run
   plain `wednesday`) and compare the two sync reports — item counts
   and prices must match.
3. **During the week:** normal searches; verify searched_items queue
   accumulates; remove a wrong item via `searched-items remove`; run
   one urgent `live-refresh --flush-only`; verify items appear on the
   actual store lists (next fetch / store website).
4. **Wednesday 2:** repeat live run; check heartbeat log for real
   session lifetimes; confirm multi-page lists fetch completely
   (DELTA-2 — compare item counts against the store website's list
   count).
5. **Decision:** keep live mode (flip default via one config line) or
   revert (stop passing the flag). Either way nothing is lost.

**Failure criteria (auto-revert):** live fetch returns unusable data
twice, or the flush damages a store list (wrong items) once. The
queues and docx mode make any failure non-destructive.

## C.8 Test plan (01 Plan will expand)

1. `searched_items` module: mirror of the shipped add_to_list test
   matrix (atomic IO, dup guard, render, remove-on-flush semantics)
   **plus remove-by-code/clear tests (DELTA-3)** and code-generator
   tests: 5 letters, A–Z minus I/O, uniqueness against queue +
   tombstones, tombstone expiry at 7 days, case-insensitive removal,
   comma-separated multi-remove, unknown-code error listing current
   codes.
2. `uom.py`: parse (`25L`, `600mL`, `180g`, `1 each`, `6 x 170g`),
   family matching, 20% boundary (exactly 20% = comparable; 20.1% =
   not), verdicts.
3. Lookup Step 5 selection: **ranking only, no name rejection**
   (B2) — top-ranked result used when UOM rule passes; next-ranked
   tried on UOM failure; "none passes" path prints the 1-per-store
   found-block — all mocked, no network. (The Seasol/hand-tool cases
   must be caught by the UOM gate or shown in the found-block, never
   silently priced.)
4. Comparator: identity/provenance lines render; non-comparable items
   excluded from totals and 🏆; the B1 wording block prints exactly.
5. `--source` flag routing: docx default untouched; live mode reads
   snapshots; missing snapshots → clear error, docx NOT silently used.
6. Queue hook: live-search add → exactly one queued entry; non-live
   adds and wool/coles missing adds do NOT feed searched_items.
7. Flush logic (mocked API): success removal, failure retention +
   retry count, throttling pace, per-store grouping, "Price
   Compare"-only targeting.
8. Snapshot conversion: WW specials fields → ProductItem specials
   semantics (IsOnSpecial/WasPrice/SavingsAmount); Coles JSON →
   ProductItem (reuse existing `_parse_search_result` shape);
   **multi-page dedup (DELTA-2)**.
9. Pagination walker (mocked APIs): loops until hasMore=false; stops
   at 30-page cap with warning; boundary-item dedup.
10. No test may hit the network or real stores.
11. Failure modes (mocked): any store's fetch failure aborts live mode
    BEFORE any sheet write; stop message names the store/reason and
    the manual docx instructions; successful snapshots preserved.
12. Flush failure handling: failed items retained with reason +
    attempt count; exact names in the report; 3-strike park;
    session-death abort leaves remaining items queued; one failure
    never blocks other items.
13. Credit guard: per-run Scrape.do cap stops the flow with a
    message; circuit breaker opens after 3 consecutive failures and
    fails fast; fetch/flush/heartbeat code paths contain no Scrape.do
    calls (assert-by-grep test).
14. Scrape.do request builder unit test: asserts `geoCode=au`, **no
    `render` param**, unique session id per call, no `country=` param;
    retry chain issues exactly 3 attempts with 3 fresh session ids on
    5xx, stops after 3, never retries 401/403 (mocked transport).
15. Explicit-add-only: plain `compare`/`search`/`expand` never call
    `add_product_row` or touch searched_items; `search --add-item 2`
    and `map --add` do (mocked sheet).
16. Found-block rendering: exactly 1 closest product per store, the
    "Reply 'expand'" line, and queue-management words printed in
    every queueing output (including the `[CODE]` at the end of
    every queued product line).

## C.9 Decisions already made (binding — do not re-litigate)

1. Batch-over-interactive: weekly (plus urgent) one-shot flushes; no
   daily login attempts. (User decision, 2026-08-28.)
2. Old method stays default; live mode is opt-in via flag for the
   whole trial week. (User-mandated revert capability.)
3. Two queues, one flush: `add_to_list.json` (unchanged) +
   `searched_items.json` (new); flush drains both; targets each
   store's "Price Compare" list only.
4. **No Col I/J keyword writes from the flush** — the
   resurface-through-unmatched loop is intentional and preserved.
5. Adds run from the logged-in page context (not replayed cookies) for
   maximum token compatibility.
6. WW lists: "Price Compare" + "Special list (28)"; Coles: "Price
   Compare". Exact names confirmed at runtime by enumeration; mismatch
   prints available names instead of guessing.
7. Session lifetime is treated as unknown; heartbeat measures it; no
   behaviour depends on it.
8. Cost target: $0/month new spend. Scrape.do unchanged (search only);
   no ZenRows role.
9. **No unlimited retries anywhere** (C.4.1 attempt caps). Wednesday
   fetch failure = clean stop before any sheet write + exact manual
   docx instructions; the manual method is permanently the default and
   is never removed. (User-mandated, 2026-08-28.)
10. **Flush failures report exact item names**; failed items stay
    queued for a later flush by default, or the user adds them
    manually and clears them; 3-strike park rule; session death aborts
    immediately. (User-mandated, 2026-08-28.)
11. **Authenticated paths are Scrape.do-free** — list fetch, flush, and
    heartbeat can never consume credits; global per-run cap protects
    the existing search flows.
12. **UOM rule (user-mandated, 2026-08-29):** same size or within 20%
    → comparable; anything else → "No matching product" block with the
    two found products named; NO per-unit price comparisons, ever.
13. **Wednesday order (user-mandated, 2026-08-29):** flush queues
    FIRST, then fetch/copy the lists, so searched items are on the
    store lists before they are read.
14. **Pagination (user-mandated, 2026-08-29):** every list is fetched
    from ALL pages on both stores, never just the first page.
15. **Searched-items queue is reviewable (user-mandated, 2026-08-29):**
    `searched-items show/remove/clear` lets the user drop wrong
    products any time before Wednesday.
16. **Scrape.do recipe (tested, 2026-08-29, 13/13 success):**
    `geoCode=au`, **no JS render** (results are server-rendered),
    fresh session id per call, silent 3-attempt retry chain with fresh
    sessions + 3 s/6 s backoff on 5xx/timeout, per-run cap of 40,
    circuit breaker as credit guard, ≥90 s tool timeouts in SKILL.md.
    User-visible failure only on a total Scrape.do outage → then
    Woolworths-only display with one ⚠️ line (user decision, Q2).
17. **No hard name filter (user decision, 2026-08-29):** the UOM 20%
    rule is the ONLY comparability gate; name relevance ranks results
    (typo-tolerant) and never rejects them.
18. **Found-block: 1 closest product per store + `expand` (user
    decision, 2026-08-29):** expanded results are display-only;
    NOTHING from compare/search/expand is auto-queued — a product
    joins the sheet + searched_items queue ONLY on an explicit
    "add item N" / `map --add`.
19. **Commands are always printed in the output (user decision,
    2026-08-29):** every queueing output and queue view prints the
    exact undo/management phrases so nothing must be remembered.
21. **Removal by unique 5-letter code (user decision, 2026-08-29):**
    every queued item carries a unique 5-letter code (A–Z, no I/O,
    unique across the queue + 7-day tombstones), shown at the end of
    the product line; "remove APCH" / "remove APCH,MIVOS" works after
    any number of intervening chats and can never be mixed up between
    searches; unknown codes produce a self-correcting error listing
    current codes.
 20. **NA commands preserved (verified existing):** during resolve
     wool/coles sessions, replying `na` (`map wool|coles --na`) writes
     `NA` to the store keyword + price columns and permanently removes
     the item from that store's missing list. Behaviour unchanged,
     out of scope for modification (B6).
 22. **Correction to decision 21 (user, 2026-08-30):** queue codes are
     **3 letters** (as built: A-Z minus I/O, no repeated letter, 7-day
     tombstones). The "5-letter" wording in decision 21 is superseded —
     do NOT change the implemented 3-letter codes.
 23. **Compare must print the add reminder too (user decision,
     2026-08-30):** every `compare` result that displays a live product
     ends with the same reminder line `search` already prints
     ("💬 Reply 'add item N' to queue a result for Wednesday.") — the
     user will forget the keywords otherwise. Decision 18 (nothing
     auto-queues) is unchanged; this is display-only.
 24. **Telegram topic split for Wednesday output (user decision,
     2026-08-30):** two NEW topics in the existing Claw Command Centre
     supergroup: `specials-wool` (receives the Wednesday specials
     report) and one further topic (name at implementation, e.g.
     `weekly-lists`) receiving the three resolve lists (unmatched,
     wool missing, coles missing). The USER creates both topics
     manually in Telegram and supplies the thread IDs to the coder —
     no automated topic creation. The existing `grocery-sync-sheet`
     topic (thread 151) is RETIRED: code stops posting to it.
     MANUAL ITEM (user does after cutover): delete the "Grocery: Sync
     & Sheet" topic in Telegram. Thread IDs land in
     `telegram_gateway/topics.py`, `TELEGRAM_TOPICS.md`, and the CLI
     `_TELEGRAM_THREAD_ID` routing constants.
 25. **Specials flags in sheet columns M/N (user decision, 2026-08-30):**
     every Wednesday sync populates the specials columns — M
     (Woolworths) and N (Coles) — with exactly three values, never
     prices: `no` (not on specials), `discount` (price reduction),
     `multi-buy`. Items added through the resolve flows (map --add,
     search --add-item, missing-list adds) get the same flag written
     alongside the price. Verified marker formats (probed from the
     real docx files, 2026-08-30):
     - Woolworths: `Save $X` → discount; `2 for $X` → multi-buy
       (both already handled by `specials_parser`).
     - Coles: `Save $X` or `Was $X` → discount; `Any 2 | $9` →
       multi-buy — **NEW pattern, not parsed anywhere yet** (Coles
       also prints a `SPECIAL` flag line above the product).
     Precedence rule: an `Any N | $X` marker wins → multi-buy; else
     Save/Was → discount; else → no.
 26. **Discovery recording must be finished (verified gap, 2026-08-30):**
     the one-time training is scaffolded (prompt "Add ONE item to your
     Price Compare list in the open window ({store})…", hard refusal
     to flush without a capture — error names `live-refresh
     --recapture` — and `--recapture` to re-train), BUT the real
     browser driver (`_LocalDriver`) has NO `capture_add_to_list`
     implementation — only injected test drivers do, so a real
     discovery run currently records `discovery: failed`. The coder
     MUST implement the real recording: a network listener in the page
     context that captures the add-to-list request (method, URL, body
     shape) while the user adds ONE item manually. Pagination needs
     NO training and NO user input — the fetch walks all pages
     automatically (30-page cap; binding decision 14).
 27. **User-facing discovery status (follows from 26):** the live-window
     summary must clearly print per store whether discovery was
     `captured` (trained) or `failed` (not trained, flush impossible
     until retrained), and the flush-failure message must keep naming
     the exact recovery command (`live-refresh --recapture`). The user
     never has to remember training state — the system always says
     what is missing and what to run.

### PROPOSED — awaiting user confirmation (NOT binding yet)

- **Umbrella command:** one main grocery command with subcommands
  (e.g. `grocery compare`, `grocery search`, …) plus a `lists`
  subcommand showing all queues in one view (unmatched, wool missing,
  coles missing, to-do/add_to_list, searched). Mentioned 2026-08-30;
  the user has NOT yet confirmed — confirm before the architect
  plans it.
