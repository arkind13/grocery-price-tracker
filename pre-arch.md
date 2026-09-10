# Pre-Arch — Aldi: live search + Wed/Sat specials

> Written by the 00 Tester agent, 2026-09-11. Everything below was
> tested live against the real Aldi systems today. No repo code was
> changed — this document is the only artifact. Next step: invoke the
> **01 Architect agent** with this file.

## 0. What the user asked for (verbatim)

1. "I'm now ready to add Aldi to the live comparison … whenever I live
   search a product it should also check alsi sites along with wool and
   coles. No addition of items."
2. "Aldi site should be easier to navigate and fight than wool and
   coles. If not, pleae use zenrows or scrape.do. Test on a few items
   and see if it is working."
3. "Aldi has 2 special days - Wed and Sat - I need the list of specials
   on both these days but only on those days. Even though Aldi releases
   its cataloge well in advance - I would only need the list of specials
   on Wed and Sat morning - we can combine it with the exsiting cron for
   checking fb pages for those 4 shops on those 2 days 5 am schedule."
4. "Catalogues are available on their site both in list format and also
   in pdf format to download. pdf is weekly so one pdf might have the
   list for wed and saturday. So you test and decide which one you want."
5. "AT this stage I only want you to test various methods and record
   your findings in pre arch model for the arch model to then make the
   arch for this project."

## 1. Executive summary — the two answers

**Live search: YES, and it is genuinely easy.** Aldi's website runs on
a clean public JSON API (`api.aldi.com.au`). Plain requests get blocked
by Akamai (the same bot protection Woolworths uses), but the
**curl_cffi Chrome-131 impersonation already in the project beats it** —
the exact same trick `fetch_woolworths_search_noauth` uses. **No ZenRows,
no Scrape.do, zero credits** — cheaper than the Coles chain. Verified
10/10 queries from the local PC (240–350 ms each) and 4/4 from the VPS
container's datacenter IP (0.5–1.2 s), which matters because live search
runs on the VPS.

**Specials: use the list format (the API), NOT the PDF.** The PDF is a
6.1 MB, 20-page file that is **pure images — zero selectable text**
(confirmed with a real download + extraction attempt). Getting items out
of it means vision-OCR on 20 pages every week — the expensive FB-flyer
treatment. The API instead hands over every special as structured data
(name, brand, size, exact price) keyed by drop date, in ~1.2 s for the
whole Wednesday list (94 items). One PDF does contain both Wed and Sat
(confirmed — page 12 says "Available Saturday 12th September"), but the
API splits by day natively, which is exactly what the "only on Wed and
Sat" requirement needs. Decision per user delegation ("you test and
decide"): **API list format**.

## 2. Requirements → test compliance table

| # | Requirement (verbatim anchor) | Test performed | Result |
|---|-------------------------------|----------------|--------|
| M1 | Aldi checked "along with wool and coles" on live search | Located the provider plug point `core/v2_live.py` (`LIVE_PROVIDERS` + `_PROVIDER_FN`); ran a would-be Aldi extractor **through the real `_search_provider`/ranker code path** for beef mince / chicken breast / milk / bananas | ✅ ≤3 priced lines per query, 243–331 ms; output in §4.3 |
| M2 | "No addition of items" | v2_live is PRICES ONLY by module contract (never receives a worksheet handle); Aldi extractor returns ProductItems only | ✅ nothing to add — no sheet interaction exists in this path |
| M3 | "easier to navigate and fight than wool and coles. If not, use zenrows or scrape.do" | Tried plain curl → Akamai Access Denied; curl_cffi chrome131 → HTTP 200 JSON. Measured reliability local (10/10) and from VPS container (4/4) | ✅ easier than both (one endpoint, no cookie, no credits); fallback services NOT needed |
| M4 | specials "on both these days but only on those days" | `promotion-tree` API returns drops keyed by exact date (2026-09-09 Wed, 2026-09-12 Sat, …); each day fetched individually via `promotionKey=<date>` | ✅ day-exact filtering is native; gate = "promotion key == today" |
| M5 | "combine it with the exsiting cron … 5 am schedule" | Read the VPS crontab + `core/local_deals.py:daily_scan_window` (hourly cron, self-gated 05:00–05:59 / 15:00–15:59 Sydney, once-per-window key) | ✅ same idiom extends to "hour 5 AND weekday in {Wed, Sat}" — verified mechanism, wiring is arch work |
| M6 | catalogue "list format and also in pdf … you test and decide" | Downloaded the real Week 37 PDF via the site's viewer Download button (6.1 MB); text extraction = 0 chars on every page; page images confirmed content. API route fetched Wed (94 items / 1.2 s) + Sat (26+ items) | ✅ **decided: API list format** — evidence in §5.4 |

## 3. How Aldi's site actually works (map)

- The storefront (`www.aldi.com.au`) is a Nuxt app; product data comes
  from **`https://api.aldi.com.au`** (v2/v3 JSON, GET-only, no login).
- The site auto-locates you (it showed "Current store: 2770, Mount
  Druitt") and pins `servicePoint=G406` (an Mt Druitt-area store).
- Catalogue flipbook (`catalogues.aldi.com.au`) is a separate Angular
  app fed by `sbmos-dcm-prod.azureedge.net` manifests + page JPGs; its
  Download button produces the image-only PDF.

## 4. Part A — live search findings

### 4.1 The endpoint

```
GET https://api.aldi.com.au/v3/product-search
    ?serviceType=walk-in&limit=30&offset=0&sort=relevance
    &q=<term>&servicePoint=G406
Headers: Accept: application/json
         Origin: https://www.aldi.com.au
         Referer: https://www.aldi.com.au/
Via curl_cffi impersonate="chrome131"   (plain requests → Akamai 403)
```

Response `data` = list of 30 products/page, each with: `name`,
`brandName`, `sellingSize` ("0.5 kg"), `sku`, `categories`, `badges`,
and `price` = `{amount: 699 (cents), amountRelevantDisplay: "$6.99",
wasPriceDisplay, savingsDisplay, comparisonDisplay: "$2.38 per 100 g"}`.
Maps 1:1 onto `extractors/models.py:ProductItem` — see the proof below.

### 4.2 Measured behaviour (2026-09-11)

| Probe | Result |
|---|---|
| Reliability, local PC | 10/10 queries HTTP 200 (milk, beef mince, chicken breast, lamb shoulder, onions, bananas, tomatoes, rice, eggs, bread) |
| Latency, local PC | 240–350 ms per query |
| Reliability, VPS container (`docker exec openclaw-core`) | 4/4 HTTP 200 — **Aldi's Akamai does NOT block the datacenter IP** (unlike Woolworths' intermittent 403s) |
| Latency, VPS | 486–1150 ms |
| `limit=10` | **HTTP 400** — limit is validated; `limit=30` (the site's own page size) works. Pin it. |
| `servicePoint` omitted | 200, but one milk variant missing from results; `G406` restores it → **pin `servicePoint=G406`** (Mt Druitt). Prices themselves never differed. |
| `currency` param | optional |
| Relevance quality | "beef mince" → real beef mince first; generic single words ("milk") can surface odd hits (Milk Frother) — same as the site's own search; the existing `_ranked()` handles it fine |

### 4.3 End-to-end proof (real `core/v2_live.py` ranker + would-be extractor)

```
=== live aldi 'beef mince' (331ms)
   3 Star Beef Mince — $11.89 · approx. 1.9 kg per package
   2 Star Beef Mince 500g — $6.49 · 0.5 kg
   Regular Beef Mince 500g — $6.99 · 0.5 kg
=== live aldi 'chicken breast' (316ms)
   Chicken Breast Chips 1kg — $8.49 · 1 kg
   Chicken Breast Tenders 400g — $3.99 · 0.4 kg
   Shredded Chicken Breast 500g — $6.99 · 0.5 kg
=== live aldi 'milk' (273ms)
   Oat Milk 1L — $1.65 · 1 L
   Soy Milk 1L — $4.49 · 1 L
   Milk Frother — $31.99
=== live aldi 'bananas' (243ms)
   Banana Chips 300g — $2.99 · 0.3 kg
   Frozen Banana 500g — $2.99 · 0.5 kg
   Cavendish Bananas Loose — $4.49 · approx. 0.18 kg per piece
```

The extractor that produced this is ~40 lines — the exact contract the
architect needs: `fetch_aldi_search(search_term, page_size) ->
list[ProductItem]` with `price=amount/100`, `size=sellingSize`,
`brand=brandName`, `unit_price=comparisonDisplay`,
`product_id=sku`, `is_special` from `wasPriceDisplay/savingsDisplay`.

### 4.4 Comparison with the other two providers

| | Woolworths | Coles | Aldi |
|---|---|---|---|
| Access | curl_cffi no-auth API (Akamai; intermittent 403 retries) | Scrape.do JS-render (credits, breaker, 3-attempt chain) | **curl_cffi, one GET, no retries needed in 20+ calls** |
| Cost | free | Scrape.do credits per search | **free** |
| Auth | none | none | none |

The user's guess was right: Aldi is the easiest of the three.

## 5. Part B — Wed/Sat specials findings

### 5.1 The day-keyed promotion API (this is the core discovery)

```
GET https://api.aldi.com.au/v2/promotion-tree
    ?serviceType=walk-in&servicePoint=G406      (same curl_cffi headers)
```

Returns upcoming drops weeks in advance, each with the date as its key:

```json
{"promotions": [
  {"key": "2026-09-09", "title": "Available from Wed 9th September",
   "themes": [Grocery Specials, Limited Time Only Meat, ...]},
  {"key": "2026-09-12", "title": "Available from Sat 12th September",
   "themes": [Camping, Technology and Entertainment]},
  {"key": "2026-09-16", "title": "Available from Wed 16th September", ...}]}
```

Then the items for one day:

```
GET https://api.aldi.com.au/v3/product-search
    ?serviceType=walk-in&limit=30&offset=<N>&sort=relevance
    &promotionKey=2026-09-09&servicePoint=G406
```

Paginate `offset` by 30 until a short page. Same rich product objects
as live search.

### 5.2 Measured

- Wed 2026-09-09: **94 items, 4 pages, 1198 ms total**.
- Sat 2026-09-12 (drop is tomorrow): **already fetchable today** — 26+
  items on page 1. This is why the gate must be **date equality**
  (`key == today` in Sydney), never "newest promotion" — otherwise it
  would fire early.
- Special Buys carry **no was-price** (they are one-off deals, not
  discounts) → the specials message should be a plain priced list, not
  the Woolworths-style 💰 discount grouping.
- `promotionTheme` param exists but appeared inert with
  `sort=relevance` (first page identical). If grouping by theme is
  wanted, group client-side from each item's `categories` /
  the promotion-tree themes.
- Site page URL shape for reference: `/special-buys/2026-09-09?theme=…`.

### 5.3 Saturday note

Saturday drops are typically non-grocery (this week: camping gear,
tech). That's the real content — no filtering decision was made here;
the user asked for "the list of specials", so the default is the whole
day's list. Flagged as an open decision below.

### 5.4 The PDF investigation (why it lost)

- Downloaded for real via the viewer's Download button (headless
  download event): 6.1 MB, **20 pages**, `%PDF-1.3`.
- `pypdf` text extraction: **0 characters on every page** — each page
  is one flattened image. Page images (same content, straight from the
  Aldi CDN as JPG) confirmed: cover = Week 37 Special Buys; page 12
  carries "Available Saturday 12th September" banners → the weekly PDF
  does bundle Wed + Sat.
- Turning that into a list = vision-OCR × 20 pages/week — the FB-flyer
  treatment with all its failure modes, for data the API already gives
  exact and free.
- The flipbook's data manifest (`published.<date>.json`, gzip) contains
  page JPG links only — no text, no PDF URLs. PDF route is strictly
  worse; keep it only as a documented emergency fallback.

## 6. Integration points (verified in code, not modified)

1. **Live search plug** — `core/v2_live.py`: add `"aldi"` to
   `LIVE_PROVIDERS` and `_PROVIDER_FN` → new
   `extractors/aldi_extractor.py::fetch_aldi_search`. Nothing else in
   the live path changes (spec §15 holds: one entry + one extractor).
   `render_live` needs an Aldi icon (currently 🟢 Woolworths / 🔴 Coles).
2. **Specials cron** — VPS hourly cron
   `7 * * * * … local-deals --daily-scan` self-gates via
   `core/local_deals.py:daily_scan_window()` (Sydney hour in
   `(5, 15)`, once-per-window state key). An Aldi specials job reuses
   the same idiom with a stricter gate: **hour == 5 AND weekday in
   {Wed, Sat} AND own once-key** — fires only Wed/Sat ~05:07 Sydney,
   exactly the "5 am schedule" the user described. (Whether it lives
   inside `run_daily_scan` or as a sibling subcommand is an arch
   choice.)
3. **Sheet** — no changes. Special buys are posted to Telegram only;
   nothing enters Products_Master/Local_Deals (consistent with
   "no addition of items" and the live-verb PRICES ONLY rule).

## 7. Edge cases & risks found

- **Akamai intermittent 403** — never observed on Aldi (0/20+ calls,
  including datacenter IP), but one Woolworths-style retry (2 s pause)
  is cheap insurance for a 7-days-a-week bot.
- **`limit` validation** — anything but 30 (and presumably its allowed
  set) 400s. Pin `limit=30`; don't make it configurable.
- **`notForSale: true` items** exist in results (e.g. some
  age-restricted/dropship). They still carry prices; decide to keep or
  filter (recommendation: keep — prices are real).
- **servicePoint pinning** — omitting it drops an occasional product;
   pin `G406` (matches the site's own choice for Mt Druitt).
- **Timezone/DST** — the promotion date must be compared in
  **Australia/Sydney** (the repo already has `core/sydney_time.py`).
- **Advance release** — drops are visible ~1–2 weeks early; only the
  date-equality gate protects the "only on those days" rule.
- **Theme filter inert** (§5.2) — group client-side if grouping at all.

## 8. Recommendations (summary for the architect)

1. New `extractors/aldi_extractor.py`: `fetch_aldi_search()` +
   `fetch_aldi_specials(date)` sharing one curl_cffi session helper;
   pin `limit=30`, `servicePoint=G406`, browser headers, 1 retry.
2. `LIVE_PROVIDERS = ["woolworths", "coles", "aldi"]` + mapping entry +
   an icon (suggest 🔵) — nothing else in the live path.
3. Specials job: `promotion-tree` → find `key == today(Sydney)` →
   paginate `promotionKey` fetch → render plain priced list (with brand
   + size) → Telegram post. Gate Wed/Sat 05:00–05:59 Sydney on the
   existing hourly cron idiom, own state key (e.g.
   `data/aldi_specials_state.json`), idempotent per day.
4. PDF route: document as emergency fallback only; do not build.

## 9. Open decisions for the Architect session (with recommendations)

1. **Where does the Aldi specials post land?** New dedicated topic
   (e.g. an "aldi-specials" topic) vs reuse specials topic 206.
   *Recommend: new topic — 206 is Woolworths specials by convention.*
2. **Whole day's list or grocery-relevant themes only?** Wed carries
   grocery + meat themes; Sat is often non-grocery.
   *Recommend: full list (user asked for "the list of specials"),
   theme-labelled groups; revisit if messages feel noisy.*
3. **Message truncation** — 94 items > one Telegram message (4096
   chars). *Recommend: split at ~3500 chars, "1/N" suffixes, same as
   other long posts in the repo.*
4. **`notForSale` items** — keep (recommend) or filter.

## 10. Test artifacts

All probes were run ad-hoc (no repo changes). Scratch files
(`tmp_aldi_*`, downloaded PDF) were session-only and removed. Evidence
outputs are quoted inline above.
