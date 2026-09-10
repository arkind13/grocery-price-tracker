# Pre-Arch — Phase 2: Localised Store Specials (Mt Druitt Butchers & Fruit Markets)

- **Date:** 2026-09-05 (all decisions confirmed by user in chat, 2026-09-05)
- **Author:** 00 Tester Agent
- **Supersedes:** nothing — this is a NEW, separate pipeline. The Phase-1
  live-lists spec moved to `old md/pre-arch-phase1-live-lists-2026-08-29.md`
  and is untouched by this project.
- **Sandbox evidence:** `grocery-price-tracker/sandbox_phase2_local_deals/`
  (test harnesses, findings JSON, downloaded real board photos,
  `vision_parse_result.json`). Keep this folder out of any production
  refactor; harnesses are evidence, not shipped code.

---

## Goal (plain language)

Every **Friday** (and on demand, any day), automatically:

1. Read the four local shops' **public Facebook pages** and grab the
   latest price-board photos.
2. Read the prices off the photos with a vision LLM (strict JSON).
3. Write ALL this week's deals into a dedicated **`Local_Deals`** tab
   (wiped and rebuilt weekly; `Products_Master` never touched).
4. Compare against the **cheaper of the sheet's Woolworths/Coles
   prices** and send a Friday Telegram alert for items **>20%
   cheaper**, grouped per store.
5. Bulk/multi-buy tier offers (5kg bags, boxes) are reported as notes
   only — they never enter the shopping list or the comparison math.

Target stores (all public FB pages, no login required today):

| Store | FB page id | Kind |
|---|---|---|
| Dunya Butchery | `100071472636159` | butchery |
| Merjan Brothers Quality Meats | `61578274311504` | butchery |
| Fruitopia Mt Druitt | `100092972080784` | fruits |
| Abu Salim Fruit Market | `61592534263358` | fruits |

---

# PART A — Test evidence (what was run and what happened)

## A1 — Test 1: getting the flyer image (harness: `test1_fb_flyer_fetch.py`)

| Approach | Result | Notes |
|---|---|---|
| `mbasic.facebook.com` (free, logged-out) | ❌ HTTP 400 | mbasic is retired. The free path is dead. |
| **Scrape.do** (`render=true`, `geoCode=au`, existing key) | ✅ **HTTP 200, no login wall**, 13 images (Dunya), 15 images (Fruitopia) | Works logged-out TODAY. ~1 credit per page. |
| ZenRows (`js_render=true`, `ZENROWS_API_KEY` from `.env`) | ❌ HTTP 400 `REQS001` — **"Requests to this domain are forbidden"** | Key is VALID (the error is a domain block, not auth). ZenRows forbids `facebook.com` **and** `m.facebook.com` as targets (both probed). **ZenRows is OUT as an FB fallback — provider-level restriction, not fixable with params.** |
| Local headed Chrome (Playwright, persistent profile) | Not run — user decision Q10 | Kept as documented fallback ONLY. User will create a separate FB login if strict login is ever enforced (never the personal account). |

**CDN rules discovered (must be respected by the implementation):**

1. FB image URLs are **signed** (`oh=` covers the exact query string).
   Modifying ANY param (e.g. stripping `stp=` to get a bigger photo)
   → HTTP 403. Download the URL **exactly as captured** (only
   HTML-unescape `&amp;`).
2. The same photo appears in **multiple renditions** in the page HTML.
   Rank by the `cstp=mx{W}x{H}` param and keep the LARGEST per photo id
   (dedupe key: the `NNNNNN_NNN_NNN_n.jpg` basename — note 9-digit ids
   exist, don't require 10+).
3. URLs **expire** (`oe=` timestamp, days). Download immediately at
   fetch time; store the FILE; never store-and-revisit the URL.
4. Some older posts only expose tiny renditions (11–160 KB thumbs, e.g.
   `s160x160`) — too small for OCR. Skip images under a size floor
   (~30 KB) or below ~400 px. ALSO capture `srcset` attributes — they
   hold larger renditions than `src` alone.
5. The stores post **photos of their in-shop price boards** (not PDFs
   or flyers) — one photo = the whole weekly list. This is ideal.
6. There is no reliable post timestamp in the logged-out HTML → "last
   3 posts" + validity-date filtering is the freshness mechanism
   (user decision, Part B4).

## A2 — Test 2: vision parsing (harness: `test2_vision_json.py`)

**Schema v2 (final, validated):**

```json
{
  "valid_until": "YYYY-MM-DD" | null,
  "validity_text": "raw wording from the board" | null,
  "deals": [{
    "item": str, "raw_text": str,
    "price": number > 0,
    "unit": "kg" | "ea" | "pack",
    "price_kind": "single" | "multibuy" | "bulk_pack",
    "multibuy_qty": int|null,        // >=2 only for multibuy
    "bulk_size": "10kg" | null,      // normalised, only for bulk_pack
    "category": "fruits" | "butchery" | "other",
    "notes": str
  }]
}
```

Validator + normaliser results (11/11 offline checks):

- bulk labelled `single` → REJECTED (the exact failure mode rule 5
  guards against)
- `bulk_size` without a kg/g token ("BIG BOX") → REJECTED
- **Normaliser:** "10kg BOX" → "10kg" (models echo flyer words into
  the size; strict-only validation breaks in the field — the
  normaliser is MANDATORY)
- multibuy qty<2, string prices, zero prices, bad units → all rejected
- prose-wrapped JSON rescued; prose without JSON → clean failure

**Model comparison on the REAL Abu Salim price-board photo
(12 items incl. three bulk traps: 5kg potato bag, 5kg onion bag, 2kg
cucumber bag):**

| Model | Route | Result | Cost/image |
|---|---|---|---|
| **`glm-5.3-flash`** | **user's `zlm_url` (Z.ai Coding Plan base `https://api.z.ai/api/coding/paas/v4/` + `/chat/completions`, key `zlm_claw`)** | **12/12 deals, 0 schema errors, bulk isolated, categories correct, `finish_reason=stop`** | **$0 — runs on the existing Coding Plan quota** |
| `google/gemini-2.5-flash` | OpenRouter | 12/12 deals, 0 schema errors, bulk isolated | $0.0025 |
| `z-ai/glm-5.3-flash` | OpenRouter | 12/12 deals, 0 schema errors, bulk isolated, AU-format validity date extracted (`11/09/2026` → `2026-09-11`) | $0.0006 |
| `deepseek/deepseek-v4-flash` | OpenRouter | ❌ **NO image support** ("No endpoints found that support image input") — RULED OUT | — |

**Z.ai coding endpoint gotchas (tested 2026-09-05):** `zlm_url` is a
BASE URL — a bare POST to it 404s; the client must append
`/chat/completions`. The pay-as-you-go endpoint
(`https://api.z.ai/api/paas/v4/chat/completions`) is a DIFFERENT
account balance and 429s ("Insufficient balance") — the Coding Plan
base is the one that works with `zlm_claw`.

**Token-cap + truncation hardening (observed live):** GLM writes
longer replies than Gemini (verbose `raw_text`) — at `max_tokens=1200`
the reply truncated mid-JSON on the 12-item board. Requirements:
`max_tokens >= 2200`, a **truncation-salvage parser** (cut back to the
last complete deal object, close `"deals"` + root — tested offline),
and `finish_reason` logged per call.

**Model decision (user correction 2026-09-05 + test evidence):
primary = `glm-5.3-flash` via the user's own `zlm_url` Coding Plan
endpoint (zero marginal cost); fallbacks = `z-ai/glm-5.3-flash`
(OpenRouter, $0.0006) then `google/gemini-2.5-flash` ($0.0025).
DeepSeek v4 flash has no vision — ruled out.**

**Model-variance edge case (real observation):** on the small Dunya
meat-board crop, Gemini parsed `Beef $22.99/kg`; GLM returned 0 deals
on the same file. Borderline/small images can diverge between models
AND runs. Architecture consequence: a store whose photos yield 0 deals
must print "no prices found this week" in the report — never silently
skip; and the size floor from A1.4 keeps sub-OCR images out.

**Weekly cost envelope:** 4 stores × (1 page fetch ≈ 1 Scrape.do
credit + 1–3 vision calls at $0 on the Coding Plan) → well under 10
credits and $0.00 vision spend per Friday (worst case, all calls
falling back to OpenRouter: ≈ $0.01). No new subscriptions.

## A3 — Test 3: >20% detection simulation (harness: `test3_discount_sim.py`)

Pure offline simulation against realistic `Products_Master` fixtures.
**11/11 checks passed**, covering:

- per-kg flyer price vs implied master $/kg → 25.8% off → **alert**
- 6.5% gap → no alert
- same-size multibuy ("2 for $15" of 500g packs) → effective rate
  $15.00/kg → comparison proceeds with the rate (consistent with the
  existing `core/multibuy.py` rules)
- bulk-only price → NEVER a comparison unit; exact tag emitted;
  basket default stays Woolworths/Coles
- per-kg deal vs litres row → unit-family gate blocks (mirrors
  `core/uom.py`)
- name drift ("Bananas" vs "Bananas 1kg") → matched, alerted
- unmatched flyer item → informational only
- $3.00 movement rule: 3 items = $4.55 → extra stop; 2 items = $2.30
  → one-trip default (mirrors `core/basket_optimizer.DEFAULT_SPLIT_THRESHOLD`
  semantics: strictly greater)

Extended with the review-response checks (RF1 canonical rows + EC2
variety guard): **18/18 total checks pass** (11 original + 7 new).

---

## A4 — Review-response tests (2026-09-05, evidence added post-review)

| Review point | Test | Result |
|---|---|---|
| RF2: root-page HTML truncation / pinned posts | Scrape.do fetch of `facebook.com/<page-id>/photos` | ✅ **HTTP 200 logged-out, 10 images, no login wall** — the photos tab is photo-purified (no text posts, no pinned announcements starving the fetch). ADOPTED as the primary fetch URL; root page stays as fallback (13 images, also worked). |
| RF3: sequential vision calls vs gateway timeout | `test4_concurrency.py`: 4 single-image calls, sequential vs `ThreadPoolExecutor(4)`; all on the user's Coding Plan | Measured: sequential **50.8s**, concurrent **18.6s (2.7× speedup, no throttling)**, single-call ceiling **25s**. A 12-image sequential worst case WOULD breach 90s — **concurrency is mandatory**. Also observed: one parallel run returned 11 deals + 1 schema error vs 12/0 sequential → run-to-run nondeterminism exists; the validator + "≤2 attempts per image" retry cap is REQUIRED (already in C.1). |
| EC1: multi-image carousel posts (split boards) | ONE vision call with 2 board images attached | ✅ **24 merged deals, zero duplicate items, correct categories (incl. "other" for Lebanese Bread), 31.4s** — passing a post's images TOGETHER works and cuts the call count to ~1–2 per store. ADOPTED: group images by post; one call per post. |
| RF1: row duplication without canonical grouping | `test3_discount_sim.py` review checks | ✅ Variety-aware `canonical_key`: "Beef Diced" + "Diced Beef" → ONE row with both stores side by side; "Royal Gala" vs "Pink Lady" → separate rows; bulk packs take no price row. 18/18 checks pass. |
| EC2: generic produce vs premium variety false alerts | `test3_discount_sim.py` review checks | ✅ Variety guard: generic "Apples" vs "Apples Royal Gala" master → conflict → alert suppressed (tagged "variety differs — verify"); same-variety pairs alert normally; non-variety items unaffected. |

## A5 — Channel & website coverage tests (user follow-ups, 2026-09-05)

| Question | Test | Result |
|---|---|---|
| Does Scrape.do work on ALL FOUR Facebook pages? | Probed Merjan + Abu Salim (Dunya + Fruitopia already proven) | ✅ **All four: HTTP 200, no login wall** — Dunya 13, Merjan 13, Fruitopia 15, Abu Salim 15 images. Facebook coverage is complete. |
| Can we also read Instagram (e.g. @merjanbrothers) and dedupe vs FB? | Scrape.do rendered fetch of the IG profile | ❌ **Login-walled** — HTTP 200 but only profile meta (follower counts); zero post captions, zero images. IG is an identity wall. Since the user expects FB and IG content to be identical, **FB-only coverage loses nothing**. No new subscriptions; IG stays out of scope (revisit only if the user ever provides a dedicated account — same rule as FB local-Chrome fallback). |
| Does any of the four shops have a usable website to build a normal-price catalogue? | Web-search + direct fetch + **user supplied `dunyabutchery.com.au` (missed by search)** | ✅ **DUNYA HAS A FULL SHOP SITE.** `https://www.dunyabutchery.com.au/` — WooCommerce (WordPress) with an **open Store API**: `GET /wp-json/wc/store/v1/products?per_page=50` → HTTP 200, clean JSON (name, price, regular_price, categories), per-kg/per-each units right in the product names ("Diced Beef (per kg) $18.99", "Chicken Skewer (each) $2.99"), plus dedicated **"Bulk Offers & Deals"** and **"Special Offers and Deals"** categories. Catalogue builder = a paginated JSON walk, no HTML parsing, no vision. ⚠️→✅ TLS note: the site's certificate chain fails verification when fetched directly from python — **workaround TESTED (2026-09-05): route the catalogue fetch through Scrape.do** (their proxy terminates TLS with a valid certificate; clean JSON returned, local verification never disabled; costs 1 credit per 4-weekly refresh). The shipped code MUST use the Scrape.do route for this host — never blanket-disable verification. Fruitopia's domain remains an empty shell; Merjan/Abu Salim have directory pages only. |

## A6 — Capacity statement (user question: "what is your capacity in scraping?")

Per shop per run the pipeline spends: **1 Scrape.do render (~1 credit) + 1–3 vision calls ($0 on the Coding Plan, worst case $0.0025 each on OpenRouter)**. Concretely:

| Scale | Credits/run | Vision wall time | Cost |
|---|---|---|---|
| 4 shops (today) | ~4–8 | ~20–30s | $0 |
| 20 shops | ~20–40 | ~1.5–2 min (4 workers) | $0 |
| 50 shops | ~50–100 | ~4–5 min (4 workers) | $0 (or a few cents if OpenRouter fallback) |

The binding constraints are (1) the Scrape.do credit plan — roughly 100–200 credits/month keeps a 20–50 shop weekly run comfortable; (2) runtime scales linearly but stays flat per batch thanks to the 4-worker pool (scale workers up for bigger lists); (3) one vision call per post keeps call count near shop count. **Adding shops is a config row (page id + name + category), not code.**

**Mall/shopping-centre project (DFO Eastern Creek etc.):** acknowledged as a FUTURE, SEPARATE project — same engine pattern (shop directory → per-shop channel → vision → catalogue) generalises to mixed site/IG/FB sources, but it runs on different days/channels and is NOT designed or tested here. Deliberately out of scope for this document.

# PART B — Binding decisions (user, 2026-09-05 — do not re-litigate)

1. **Comparison basis:** like-for-like unit — $/kg vs $/kg, per-piece
   vs per-piece (meat and produce are per-kg almost always).
   Bulk/tier offers (5kg bags, boxes) are **reported but never
   compared or added to the shopping list** — shown with the comment
   "multi buy Xkg for $Y" (supersedes the earlier "— switch?" tag
   wording; user format, 2026-09-05).
2. **Baseline = the cheaper of Woolworths/Coles sheet prices
   (columns D/E), as-is.** Nothing live on the Friday run unless the
   user specifically asks. (The sheet's own multibuy-rate handling is
   a Phase-1 concern; Friday compares against the plain sheet cell.)
3. **Alert boundary: strictly >20%** (exactly 20.0% → no alert), on
   the like-for-like unit basis. The `Local_Deals` tab itself holds NO
   discount data — discounts exist only in the Telegram report,
   computed against the master sheet when the product exists there.
4. **FB access chain: Scrape.do primary → local headed Chrome
   (last resort, separate FB login, never the personal one).**
   ZenRows is EXCLUDED — its standard plan forbids facebook.com as a
   target (REQS001, probed on both www. and m. hosts, 2026-09-05;
   the `ZENROWS_API_KEY` itself is valid and stays in use for the
   existing `scraping_api` Coles work). No local-Chrome testing now
   (user decision Q10) — all pages are public today. No new
   subscriptions.
5. **Freshness: take the last 3 posts** per store, extract the
   board's printed validity date, **drop expired boards**, parse the
   valid ones. If NO board carries a date → parse the last 3 images
   by default.
6. **Friday report is grouped per store** — "Abu Salim deals: 1…2…3…;
   Fruitopia deals: 1…2…3…" etc. Every deal/Note is tagged with its
   store.
7. **ALL parsed items are added to the `Local_Deals` tab** (matched or
   not). Layout: **Col A = product name; Cols B–E = one column per
   store** (Dunya, Merjan, Fruitopia, Abu Salim). Page classified
   into **Fruits and Butchery sections**. **Every Friday the tab is
   wiped and rebuilt from the current week's catalogues only** — new
   products get new lines; **no history kept anywhere**.
8. **Model: `glm-5.3-flash` via the user's own Z.ai Coding Plan
   endpoint (`zlm_url` + `zlm_claw` from `.env`), OpenRouter
   (`z-ai/glm-5.3-flash`, then `google/gemini-2.5-flash`) as
   fallbacks.** DeepSeek v4 flash has no vision (tested, ruled out).
9. **On-demand runs:** a Claw skill (e.g. `local-deals`) must let the
   user run the whole report ANY day ("run the local deals report"),
   not just Fridays. Friday stays the scheduled cadence.
10. **Friday = TWO Telegram posts (user, 2026-09-05):** Post 1 =
    STANDOUT items only — the >20%-cheaper-than-master-sheet alerts.
    Post 2 = the FULL catalogue of everything listed on the shops'
    boards that week, regardless of master-sheet matches.
11. **Comment discipline (user, 2026-09-05):** plain unit-price items
    carry NO note. The "normal price unavailable" note appears ONLY
    on multi-buy items. Every multi-buy item carries the comment
    "multi buy Xkg for $Y" (+ the same-store site price when a site
    catalogue exists in future).
12. **Local multi-buys NEVER enter the shopping-list maths (user,
    2026-09-05)** — deliberately the OPPOSITE of the Coles/Woolworths
    rule (a 2-for is buyable; a 5kg minimum is not, unless the user
    chooses it). The shopping list uses unit prices only and prints
    the note "this item is on multi buy offer at <store> — min
    purchase Xkg for $Y". The Friday POST shows the special multi-buy
    price.
13. **Price column (user delegates, tester decision, 2026-09-05):**
    show the FB board's per-unit price; for multi-buy rows show the
    multi-buy total in the price cell with the derived per-unit rate
    and terms in the comment ("multi buy 5kg for $54 — $10.80/kg").
    **Dunya rows additionally carry the same-store site unit price in
    the comment** ("normal site price $X/kg") whenever the item exists
    in the Dunya website catalogue — enabling the truest discount
    check: FB special vs the same shop's normal price.
14. **Website catalogues (user supplied Dunya's site, 2026-09-05):
    ACTIVE for Dunya only.** `dunyabutchery.com.au` (WooCommerce,
    open Store API at `/wp-json/wc/store/v1/products`, paginated JSON;
    includes "Bulk Offers & Deals" + "Special Offers and Deals"
    categories). Refresh **every 4 weeks** (user decision). The
    module is written generically so future shops with sites plug in
    as config. Fruitopia's shell site and the Westfield directory
    pages are not usable.
15. **Instagram: out of scope (tested, 2026-09-05)** — login-walled
    logged-out; FB content is expected to match IG, so FB-only
    coverage stands. No new subscriptions; revisit only if the user
    later provides a dedicated account (same policy as the FB
    local-Chrome fallback).

---

# PART C — Proposed architecture (for 01 Architect to plan)

## C.1 Friday pipeline (one command, e.g. `python grocery_price_cli.py local-deals`)

```
For each store (4):
  1. FETCH   Scrape.do render of the PHOTOS TAB
             https://www.facebook.com/<page-id>/photos
             (tested logged-out: 200, 10 images, no login wall —
             photo-purified, immune to pinned text posts; the root
             page is the fallback URL, also tested working).
             Collect scontent URLs + srcset.
  2. PICK    last 3 posts' images; dedupe by photo id; largest
             rendition per photo; drop sub-size-floor images;
             GROUP IMAGES BY POST (a carousel post's 2–3 images are
             one weekly board, EC1).
  3. VISION  glm-5.3-flash on the user's Coding Plan (zlm_url;
             fallbacks z-ai/glm-5.3-flash then gemini-2.5-flash on
             OpenRouter) with schema v2 prompt. ONE CALL PER POST
             with that post's images attached together (tested:
             2 images -> 24 merged deals, no duplicates, EC1),
             max_tokens >= 2200, truncation salvage on.
             Parse + validate (normaliser included). Boards with
             valid_until in the past are dropped; no dates anywhere
             → keep all 3.
  4. MERGE   all valid deals per store → this week's catalogue.
  4b. SITE   (Dunya only today) walk the WooCommerce Store API
             (`/wp-json/wc/store/v1/products`, paginated, every 4
             weeks or on run if stale) → normal-price catalogue used
             for the comment column and the same-store discount check.
             FETCHED VIA SCRAPE.DO (tested: the site's certificate
             chain fails direct python fetches; Scrape.do terminates
             TLS with a valid cert — clean JSON, nothing disabled).
Then:
  5. SHEET   wipe `Local_Deals`; rebuild: Fruits section, Butchery
             section, (Other if any); Col A = CANONICAL product names
             (variety-aware grouping, C.4 — equivalent items across
             stores share ONE row so B–E show the cross-store
             comparison), Cols B–E = store price cells (blank when
             that store doesn't have it; bulk cells carry the tag
             text).
  6. MATCH   each deal vs Products_Master (reuse name_matcher /
             lookup semantics; uom family gate; like-for-like basis;
             VARIETY GUARD on produce, C.4/EC2).
  7. ALERT   discount vs cheaper of D/E; strictly >20% → alert.
  8. NOTIFY  Telegram report (C.3), grouped per store, alerts
             highlighted, bulk notes tagged, $3.00 rule applied to
             any extra-stop recommendation.
```

**Concurrency (review RF3, measured):** stores are processed
CONCURRENTLY with `ThreadPoolExecutor(max_workers=4)`. Measured on
the Coding Plan: sequential 4 calls = 50.8s (a 12-image sequential
worst case would breach a 90–180s gateway timeout); concurrent =
**18.6s, 2.7× speedup, no provider throttling**; single-call ceiling
25–31s (multi-image). The whole vision stage therefore fits any
sane tool-call timeout. The skill (C.6) still documents ≥90 s
timeouts. Vision calls per Friday: ~4–8 (per POST, not per image).

Attempt caps (mirror Phase-1 discipline): page fetch ≤3 attempts with
fresh sessions (5xx/timeout only, never 401/403); vision ≤2 attempts
per POST (model fallback counts as attempt 2 — REQUIRED: one parallel
run returned 11 deals + 1 schema error vs 12/0 sequential, so
run-to-run nondeterminism is real and only validation+retry catches
it); no unlimited retries anywhere; per-run Scrape.do cap unchanged
(40) — Friday uses ≤8.

## C.2 `Local_Deals` tab layout (binding: B7)

```
        A                B (Dunya)   C (Merjan)  D (Fruitopia)  E (Abu Salim)
1   FRUITS
2   Apples Royal Gala /kg                         $3.20          $2.99
3   Bananas /kg                                                  $2.90
4   Potatoes 5kg bag  [note: bulk 5kg $2.99]                     $2.99
5   BUTCHERY
6   Beef Diced /kg    $12.99      $13.50
7   ...
```

- Row 1 of each section is the section header (FRUITS / BUTCHERY;
  add OTHER below if vision ever classifies outside the two).
- Store names header row above the columns (frozen row recommended).
- **Canonical rows (review RF1, tested):** Col A holds a CANONICAL
  product name; equivalent items across stores share ONE row —
  "Beef Diced" (Dunya) and "Diced Beef" (Merjan) must land on the
  same row so B–E show the comparison side by side. Grouping key is
  VARIETY-AWARE: "Royal Gala" and "Pink Lady" stay on separate rows;
  generic flyer items never merge with a varietied row. Canonical
  resolution reuses `core/name_matcher.py` semantics (with
  `core/subcategory.py` as the taxonomy reference); the sandbox
  token-overlap + variety-token key in `test3_discount_sim.py` is
  the reference behaviour. NEEDS_REVIEW-style rows (ambiguous merge)
  surface in the Telegram report rather than silently guessing.
- Bulk-only items appear as a row with the note text in that store's
  cell: `[Multi-buy: <Store> has 5kg for $2.99 — switch?]` and NEVER
  in the Telegram alerts/comparison.
- The whole tab is **rewritten every run** (idempotent; running
  Saturday just rebuilds the same view). No history columns, no
  discount columns, no Last_Updated columns.
- `Products_Master` is untouched (only READ for matching).

## C.3 Friday Telegram output (binding: B2, B3, B6, B10–B13)

**Two posts, per the user:**

**Post 1 — STANDOUT DEALS** (only items >20% below the master sheet):

```
🚨 LOCAL STANDOUTS — Fri 2026-09-11 (Mt Druitt)

DUNYA BUTCHERY
 • Beef Diced — $12.99/kg  (26% < Woolworths $17.50/kg)

FRUITOPIA MT DRUITT
 • Apples Royal Gala — $3.20/kg  (29% < Woolworths $4.50/kg)
```

**Post 2 — FULL BOARD** (every catalogue item that week, grouped per
store, master-sheet matches annotated, bulk items with comments):

```
🛒 LOCAL DEALS — Fri 2026-09-11 (Mt Druitt)

ABU SALIM FRUIT MARKET
 1. Pink Lady Apples — $2.99/kg  (also 21% < Coles)
 2. Tomatoes — $2.99/kg
 3. Washed Potato 5kg bag — $2.99
    [multi buy 5kg for $2.99 — normal price unavailable]

FRUITOPIA MT DRUITT
 1. Bananas — $2.90/kg
 2. ...

DUNYA BUTCHERY
 1. Beef Diced — $12.99/kg  (normal site price $18.99/kg — save 31%)
 2. Bulk Beef Box — $89.90
    [multi buy 10kg for $89.90 — approx $8.99/kg — normal price unavailable]

⚠️ No prices found this week: Merjan Brothers (no new board)
```

- Plain unit-price lines carry NO notes unless the same-store site
  catalogue adds the "normal site price $X — save Y%" comment
  (Dunya only today, user B14).
- Multi-buy lines: multi-buy total in the price position + derived
  per-unit and terms in the comment; "normal price unavailable"
  appended only when no site catalogue exists (today: always for the
  four shops).
- Alerts (>20% vs master) appear ONLY in Post 1; Post 2 may note the
  cross-store comparison inline but the standout list is Post 1's job.
- Stores with zero parseable prices get the ⚠️ line — never silence
  (model-variance edge case, A2).
- **Shopping-list rule (B12):** the local multi-buy minimum NEVER
  feeds the "is the extra stop worth it" maths; unit prices only,
  with the note "this item is on multi buy offer at <store> — min
  purchase Xkg for $Y". ($3.00 rule unchanged, strictly greater.)

**Telegram delivery & the 4096-character budget (review catch,
2026-09-05):** Telegram rejects any message over 4096 chars, and
Post 2 (full boards, 4 stores × 10–15 items + notes) WILL exceed it.
Delivery rules (architect must enforce):
1. **Post 2 is sent as ONE MESSAGE PER STORE** — four clean messages,
   each headed by the store name. Natural boundaries, no mid-block
   cuts (10–15 items ≈ 600–900 chars per store, far under budget).
2. Safety net: if any single store block ever exceeds 4000 chars
   (e.g. a 40-item board), split at LINE boundaries (never mid-line)
   with a "(continued)" marker — reuse the gateway's existing
   `send_chunked` plumbing (`telegram_gateway/handlers.py`,
   MAX_MESSAGE_CHARS = 4096) rather than inventing a new sender, but
   the store-first split is the primary strategy; the hard 4096
   slice is the last resort only.
3. Post 1 (standouts) is small by definition; single message.
4. Every chunk carries the store header when a store block splits,
   so no item floats without context.
5. The Friday run must NEVER let Telegram's API return 400
   (message too long): length-check every message before sending.

## C.4 Matching & normalisation (architect to spec, reuse over reinvent)

- Product-name matching against Products_Master: reuse
  `core/name_matcher.py` / `core/lookup.py` semantics (ranking only,
  no hard rejection — Phase-1 decision B2). Fallback token-overlap
  (the sandbox stand-in) must NOT ship.
- Unit basis: flyer `kg` vs master size via `core/uom.parse_size`
  (weight family), $/kg vs $/kg; `ea`/count only vs count rows; the
  20%-size UOM gate still applies where pack sizes are compared.
- Per-kg comparisons are ALLOWED here (scoped exception to Phase-1 B1,
  user-approved): both sides are per-kg — it is not the forbidden
  cross-basis derivation. Never cross weight↔volume↔count.
- Multibuy (same standard pack): effective rate total/qty — same
  math as `core/multibuy.py`; the Telegram line shows the rate + the
  2+ note.
- Cross-store product alignment inside `Local_Deals` (which flyer
  items share one row) uses the SAME variety-aware canonical key as
  the tab (C.2, review RF1 — tested): word-order-insensitive tokens,
  unit/stopword stripping, variety qualifiers REQUIRED in the key
  when present ("Beef Diced" == "Diced Beef"; "Royal Gala" never
  merges with "Pink Lady"). Over-merging different varieties is the
  forbidden failure; equivalent-item splitting defeats the B–E
  layout — both are covered by the 18/18 check matrix.
- **Variety guard (review EC2, tested):** before emitting a >20%
  alert, compare variety qualifiers between the flyer item and the
  master row. Generic flyer item ("Apples") vs varietied master row
  ("Apples Royal Gala") → conflict → NO alert; the line prints with
  a "variety differs — verify" tag instead. Same variety, both
  generic, or non-variety items (meat cuts) → alert logic unchanged.

## C.5 Secrets & config (all from `.env` — never hardcode/print)

| Variable | Use |
|---|---|
| `SCRAPEDO_API_KEY` | FB page fetch (primary) |
| `zlm_url` + `zlm_claw` | vision calls — Z.ai Coding Plan base URL + key (EXACT variable names; `zlm_url` is a BASE url, client appends `/chat/completions`) |
| `OPENROUTER_API_KEY` | vision fallbacks (`z-ai/glm-5.3-flash`, `google/gemini-2.5-flash`) |
| Telegram creds (existing) | Friday report (new topic/thread id needed — user creates a `local-deals` topic, supplies the thread id, same pattern as Phase-1 decision 24) |
| `ZENROWS_API_KEY` | NOT used for FB (domain-forbidden, REQS001) — untouched for existing Coles use |

Model names and the FB page-id table live as module constants, not
in `.env`.

## C.6 Skill + schedule (binding: B9)

- New Claw skill `claw-skills/local-deals/SKILL.md` mapping natural
  language ("local deals", "butcher specials", "fruit market deals")
  → `python grocery_price_cli.py local-deals`. Include ≥90 s
  tool-call timeout guidance (vision calls are slow) and the
  no-browsing rule (FB goes through the CLI chain only, never
  web_fetch on facebook.com).
- **MANDATORY (repo rule 04):** after ANY change to
  `claw-skills/`, regenerate `python skills_doc.py`, verify
  `python skills_doc.py --check` prints OK, commit BOTH
  `SKILL.md` and `claw-skills/claw_skills_easy.md`, and scp-sync
  BOTH to the VPS path with md5 verification. An unsynced skill is
  an incomplete change.
- Schedule: **Friday 05:00 Australia/Sydney** (user decision,
  2026-09-05 — report is ready when the user wakes up; implement as
  a cron in UTC on the VPS accounting for AEST/AEDT, i.e. Fri
  19:00/18:00 UTC respectively — the architect picks the exact cron
  expression and documents the DST behaviour). On-demand runs
  rebuild the same tab and re-send the report any day.

## C.7 File boundaries

**May create:**

| File | Purpose |
|---|---|
| `grocery-price-tracker/extractors/fb_flyer_fetch.py` | Scrape.do→local-Chrome chain; rendition selection; download (evidence: `test1_fb_flyer_fetch.py`) |
| `grocery-price-tracker/extractors/shop_site_catalogue.py` | generic shop-website catalogue walker (Dunya WooCommerce Store API today; **fetched via Scrape.do — tested, the direct TLS fetch fails**; paginated JSON; 4-weekly refresh; evidence: `probe_dunya_api.py`, `test6_dunya_via_scrapedo.py`) |
| `grocery-price-tracker/core/flyer_vision.py` | vision call + schema v2 validator + normaliser (evidence: `test2_vision_json.py`) |
| `grocery-price-tracker/core/local_deals.py` | merge, sheet rebuild (wipe+write), matching, >20% detection, $3.00 rule (evidence: `test3_discount_sim.py`) |
| `grocery-price-tracker/tests/test_fb_fetch.py`, `test_flyer_vision.py`, `test_local_deals.py` | offline tests mirroring the sandbox check matrices (mocked transports; NO network in tests) |
| `claw-skills/local-deals/SKILL.md` | on-demand skill (with mandatory doc-sync workflow, C.6) |

**May edit (surgical):**

| File | Change |
|---|---|
| `grocery_price_cli.py` | new `local-deals` subcommand (+ `--stores`, `--dry-run` flags) |
| `core/sheets_client.py` (tab-access helpers only) | add/`ensure` the `Local_Deals` tab — no changes to Products_Master paths |

**Must NOT touch:** `Products_Master` write paths, `core/uom.py`
(reuse as-is), `core/multibuy.py` (reuse as-is),
`core/basket_optimizer.py` constants (reuse `$3.00`),
`extractors/session_refresh.py` (Phase 1), the Wednesday pipeline,
`.env`, any `.docx`.

## C.8 Test plan skeleton (01 Plan expands; all offline/mocked)

1. Fetch chain: mocked Scrape.do 200 → URLs captured intact
   (target URL = `/photos` tab, root-page fallback);
   5xx → (retry, fresh session) → local-Chrome fallback marker;
   401/403 never retried; per-run caps.
2. Rendition picker: multi-rendition dedupe; 9-digit photo ids;
   size-floor skip; HTML-unescape only (signed-URL rule);
   **images grouped by post for the vision stage (EC1)**.
3. Vision validator: the 11 sandbox checks (bulk-labelled-single,
   normaliser, date format, category enum, prose handling) plus the
   truncation-salvage checks (test_salvage.py) and finish_reason
   logging.
4. Freshness: expired `valid_until` → dropped; all-null dates → all
   3 kept; >3 posts → exactly last 3.
5. Sheet rebuild: wipe+write idempotency; section headers; bulk
   note cells; Products_Master never written (assert-by-grep).
6. Detection: the 18-check matrix (11 original + RF1 canonical-row
   grouping + EC2 variety guard) incl. strictly->20% boundary
   (20.0 no / 20.1 yes) and $3.00 strictly-greater semantics.
7. Report: per-store grouping, per-item store tags, bulk tags exact
    wording, "no prices found" line, sub-$3 note, "variety differs —
    verify" tag on suppressed variety-conflict pairs. **Delivery
    sizing: Post 2 renders one message per store; a mocked oversized
    store block splits at LINE boundaries with the store header
    repeated; no message ever exceeds 4096 chars (test with a 40-item
    fixture); every message length-checked before send.**
8. Concurrency: ThreadPoolExecutor(4) processes stores in parallel;
   mocked-clock test asserts the vision stage wall time is bounded
   by the slowest POST (not the sum) and ≤4 workers are used.
9. Skill file exists; `skills_doc.py --check` OK (rule 04).
10. Site-catalogue fetch (Dunya) goes through the Scrape.do route
    (mocked transport test), and an assert-by-grep test proves NO
    shipped code disables certificate verification (`verify=False`
    exists only in sandbox evidence, never in `core/`/`extractors/`).

---

# PART D — Open items (user actions, none block planning)

1. **Telegram topic**: create a `local-deals` topic in the existing
   supergroup and give the thread id to the coder (Phase-1 pattern).
2. **ZenRows**: confirmed OUT for Facebook (REQS001 domain block on
   both www. and m. hosts; key valid — keep it for the existing
   `scraping_api` usage). FB fallback = local headed Chrome with a
   dedicated FB login if ever needed.
3. **Vision model routing** (binding, tested): primary
   `glm-5.3-flash` on the user's Z.ai Coding Plan (`zlm_url` +
   `zlm_claw`) — zero marginal cost; fallbacks via OpenRouter.
4. **Friday cron: 05:00 Australia/Sydney** (user decision) — VPS
   cron must be expressed in UTC with DST handling documented.
5. Local headed Chrome FB mode stays UNTESTED by design (user
   decision Q10) — document as last-resort fallback requiring a
   dedicated FB login.
6. **Mall/shopping-centre scraping (DFO Eastern Creek and similar):
   FUTURE SEPARATE PROJECT** — same engine, different shops/days/
   channels, mixed website/Instagram/Facebook sources; not designed,
   scoped, or tested in this document (user, 2026-09-05).
