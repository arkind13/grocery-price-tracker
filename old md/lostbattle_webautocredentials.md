# Lost Battle — Automating the store "save to list" click (Plan A)

- **Date range:** 2026-08-24 (cookie war) + 2026-08-30 evening → 2026-08-31
  morning (~7 hours of automation attempts across M3 rounds 1–17)
- **Verdict:** LOST. The final automated click on "save to list" was
  never achieved reliably. Plan B (script opens the page, HUMAN does
  the one click) was adopted 2026-08-31 (round 17) and is the SETTLED
  execution model.
- **Purpose of this file:** the complete "what we tried and why it
  failed" record, so a future session NEVER re-walks these dead ends.

---

## 1. What we were trying to do (plain language)

Take the shopping list from the Google Sheet and add each item to the
Woolworths / Coles website shopping lists **fully automatically**:
script finds the product, opens its page, clicks "save to list", picks
the right list. No human in the loop. Everything else in the project
(prices, comparisons, queues, reports) already worked — this was the
last mile, and it was defended by bot protection on both stores.

**Plan A** = all the automated approaches below.
**Plan B** = the surrender that works: script resolves each item's
product page (stockcode URL, title-verified), opens it, asks the user
("add this, reply /done"), moves to the next. One human click per
item. Built in rounds 18–19 (`open_items()` in `visual_grocery.py`,
`price_unavailable.py`, pc_agent chat wiring).

## 2. Campaign 0 — the cookie/API war (2026-08-24)

Full log: `old md/COOKIE_INVESTIGATION.md` (archived from
`Development Workflow/`). Goal: get a valid Woolworths login cookie
programmatically so the saved-list APIs could be called directly.
Nine approaches, nine failures:

| # | Approach | Result |
|---|----------|--------|
| 1 | Direct API with existing `.env` cookie | 403 — cookie dead (Akamai) |
| 2 | `requests` + different headers | 403 — TLS fingerprint |
| 3 | Playwright headless | 403 — headless blocked outright |
| 4 | Playwright + stealth plugin | 403 — evasions insufficient (Akamai v2) |
| 5 | Playwright + real Chrome channel | 403 — IP+TLS still flagged |
| 6 | `curl_cffi` Chrome-131 impersonation | homepage OK, API 403 (cookie dead) |
| 7 | `curl_cffi` + Auth0 `/co/authenticate` | 400/403 — password grant blocked |
| 8 | Scrape.do JS rendering | Auth0 React widget fails; no POST on plan |
| 9 | ZenRows JS rendering | 400 — session_id mismatch; Auth0 JS won't run |

**Root cause:** WW login is Auth0 OIDC with a React Universal Login
widget (needs full browser: DOM, localStorage, WebCrypto). Akamai
blocks non-browser TLS/IP at the edge. No scraping proxy executes the
Auth0 app correctly. **Conclusion: programmatic cookie refresh is not
viable.** What DID work without login: product search via `curl_cffi`
impersonation (WW) and Scrape.do (Coles) — both still in daily use.

## 3. Campaign 1 — Playwright login-refresh (M3 rounds 1–4)

Code: `extractors/session_refresh.py` (tracker repo, commits
`62596a1`, `39fa82e`, `20c6123`, `f25465e`). Goal: keep store logins
alive in a local browser and capture the add-to-list API.

| Round | Attempt | Failure | Fix tried |
|-------|---------|---------|-----------|
| 1 | bundled Chromium launch | Akamai Access Denied on homepage | `channel="chrome"` (real Chrome) + denial-aware retry |
| 2 | drive the REAL daily profile | HANG — Chrome ≥136 ignores Playwright when `--user-data-dir` is the default profile | copy `Local State` + Cookies DB into a tool profile (login transplant) |
| 3 | transplant cookies | `/auth/login` denied — transplanted bot-manager cookies (`_abck` etc.) are device-bound | filtered transplant (store cookies only, bot cookies excluded) |
| 4 | full profile CLONE (1.31 GB robocopy) | browsing finally clean; WW login achieved (SMS MFA typed by user); but: Coles `.env` password REJECTED; watcher missed prompts (block-buffered stdout); "Create list" control not found in 6 s; cloned Chrome DIED mid-run | stopped by user at 22:50 |

**Kept from this campaign:** `--cdp-port 9222` attach mode, fixed
login checks (WW: mylists array non-empty; Coles: header DOM), the
profile clone at `data/ww_coles_profile_full/` (holds a live WW login).
**Lesson:** only the DAILY Chrome profile has the creds + seasoned
cookies Akamai accepts — and Chrome 136+ forbids automation on it.

## 4. Campaign 2 — chunked-typed-JS bridge (rounds 5–10)

Code: `grocery_live_driver.py`. Goal: drive the real daily Chrome with
NO automation protocol at all (nothing to fingerprint) — inject a JS
bridge by TYPING `javascript:` in the omnibox, read results via the
window title, click via real OS clicks.

Channel war (every failure + fix):
- DevTools console paste: never executed (focus/gate) → abandoned.
- Typed `javascript:` URL: works (Chrome strips pasted, runs typed).
- Fast typing corrupted 1.5 KB payloads → 140-char chunks @ 0.03 s.
- Read-back via title in 90-char chunks: works.
- Script-created blob download: silently blocked → real-click
  clipboard (user activation) works; gestureless clipboard does not.
- Background focus steal: silent fail → ALT-key unlock + verify.
- Login without typing passwords: JS-focus + ArrowDown+Enter accepts
  Chrome's saved-credential autofill (works; passwords never touched).

Result: technically WORKED — login, list enumeration, and the WW
add-API were all captured (`live_api_capture.json`: POST
`/apis/ui/mylists/<id>/Items` with `{Quantity, Source, StockCode}`).
But: **minutes of keyboard seizure per run**, Akamai HTML challenges
still broke the item API on fresh pages (9 s settle + 5/15/25/35 s
backoffs only partly helped), and every code fix cost a full manual
re-run. **User verdict (round 10): "too clunky to be the product" —
an architectural ceiling, not a bug list.**

## 5. Campaign 3 — Tampermonkey userscript + CDP (round 11)

`grocery_bridge.user.js` (complete, correct) + CDP attach in the
driver. Blocker: Chrome 136+ **forbids CDP on the default (daily)
profile**, and the clone profile has no saved creds + wrong
fingerprint → Akamai denies. Both pieces SHELVED, not deleted —
reusable the day Chrome lifts the default-profile CDP block or a
CDP-free delivery path (manual one-time paste/bookmarklet) is
accepted.

## 6. Campaign 4 — pyautogui + OpenCV image matching (rounds 11–12)

Goal: see the screen, click the buttons like a human.
- Every button template FAILED on live screens (confidence 0.11–0.37):
  templates captured in a different page state than the PDP;
  white-on-white buttons; near-full-screen crops.
- Hidden root cause found round 14: THREE-MONITOR setup — pyautogui
  captures the PRIMARY monitor only; Chrome lives on a secondary. Every
  failure screenshot was of a dark primary. Fixed with
  `ImageGrab.grab(all_screens=True)` + virtual-desktop clicks
  (`click_virtual`) — but by then the approach was already pivoting.
- Only stable image: the WW search box (later deleted by the
  zero-image flow — not needed at all).

## 7. Campaign 5 — Ctrl+F text-find + match cycling (rounds 12–14)

The user's idea: use Chrome's built-in find (Ctrl+F) instead of image
matching; products/buttons located by their TEXT.
- First run FALSELY reported "added": Ctrl+F match 1/2 = the search
  bar text / "N results found" label, not the product link. Fixed:
  skip 2 matches (Ctrl+G), then title-verify each click (window title
  contains product name = real PDP).
- Forget list added (`data/forget_list.json`) for never-found items.
- Reached the correct PDP reliably — but still had to click "save to
  list" afterwards, which led to Campaign 7.

## 8. Campaign 6 — stockcode direct PDP (round 15) — THE ONE REAL WIN

The search pipeline (`grocery_price_cli.py search --product X
--add-item 1`) resolves the WW **stockcode** (e.g. milk = 888140)
WITHOUT a browser. Pasting
`https://www.woolworths.com.au/shop/productdetails/<stockcode>` in the
omnibox (Ctrl+L + paste, autocomplete-immune) lands directly on the
PDP, verified by window title. **This deleted the entire "click the
right hyperlink" problem** and is the load-bearing rail of Plan B.

## 9. Campaign 7 — the final click war (rounds 15–17) — WHERE IT DIED

The only remaining step: click "save to list", type the list name,
press Enter. Attempts:

| Method | Result |
|--------|--------|
| Green-blob detection (HSV mask) | Found buttons — the RELATED-PRODUCTS row (would add the WRONG product) |
| Orange find-highlight targeting | VETOED by user pre-implementation: 5+ orange badges on every WW page |
| Diff-clicker (Ctrl+F highlight ON vs OFF screenshot diff) | FALSE POSITIVE: an animated carousel changed between shots → clicked the promo → WW Error 500 → list name typed into an error page |
| + yellow-tint filter (highlight must be yellow/orange in the diff) | Re-run hit ANOTHER 500 (suspected item-level rate-limiting after many milk searches); user stopped: "woolworths page is blocking, lets try again after a few hours" |
| Final attempt (bread, next morning) | Navigation + title-verify PERFECT; tint-filtered diff found NO highlight for the product name or "save to list" → no click attempted → honest failure |

**User decision (round 17, final):** stop investing in the automated
click. Plan B adopted. The failure was NOT one bug — it was the
compound of: no DOM access (no CDP), a moving-target UI (animations,
carousels, A/B states), vision methods that can't tell a button from a
promo, and a store that rate-limits rapid repeated automation.

## 10. Root causes (plain language, all in one place)

1. **Akamai bot manager** on both stores: blocks anything whose
   browser/TLS/IP/behavior fingerprint isn't a real daily-use browser.
2. **Chrome 136+ security**: the daily profile (the only one with
   saved logins + seasoned cookies) cannot be driven by Playwright/CDP.
3. **Every workaround profile** (transplants, clones) either lacks
   saved credentials or trips Akamai's device-bound cookie checks.
4. **Without DOM access, precise clicking is guesswork**: image
   templates break across page states; screenshot diffs break on
   animations; color targeting is ambiguous on orange-heavy pages.
5. **WW rate-limits/500s** under rapid repeated automation of the same
   item.

## 11. PROVEN and KEPT — do not rebuild these

- Stockcode → direct PDP URL → omnibox paste → title verification
  (`visual_grocery.py`; the heart of Plan B).
- Multi-monitor virtual capture + `click_virtual` (5760×1080).
- WW add-API capture format (`live_api_capture.json`) — the direct
  `POST /apis/ui/mylists/<id>/Items {Quantity, Source, StockCode}`
  call, usable any time a seasoned in-page context exists.
- `--cdp-port` attach mode + login-check fixes (`session_refresh.py`).
- Chunked-JS bridge rails + userscript (SHELVED, not deleted).
- Plan B stack: `open_items()` loop, `price_unavailable.py`,
  `manual_list.json`, pc_agent chat waiters, `pc_cmd.py` VPS bridge,
  `sheet_lookup.py`.
- Cookie-war survivors: WW search via `curl_cffi` impersonation; Coles
  search via Scrape.do.

## 12. If we ever revisit Plan A — read this first

- **Do NOT retry:** headless browsers, stealth plugins, programmatic
  cookie/login refresh, TLS impersonation for auth, scraping-proxy
  login, template-image buttons, diff-clicking, chunked typing.
- **Only lanes not yet closed:**
  1. A **resident userscript** with a CDP-FREE delivery (install-once
     Tampermonkey; the round-11 blocker was CDP delivery, not the
     script itself — a one-time manual paste of the bridge would
     revive it).
  2. An official/public list API (does not exist today).
  3. Mobile-app automation (never attempted; new battlefield).
- **Before ANY retry, check:** has Chrome lifted the default-profile
  CDP block; has WW changed its list API auth; is the 500 item-block
  gone; does the clone profile still hold a live login.

## 13. Detailed logs (where the evidence lives)

- Parent `test.md` (AI related root) — M3 records, rounds 1–19 + the
  M1/M3 manual-step records (full chronological narrative).
- `old md/COOKIE_INVESTIGATION.md` — the 2026-08-24 cookie war.
- Tracker commits `62596a1`/`39fa82e`/`20c6123`/`f25465e`
  (`session_refresh.py` saga); parent commits from 2026-08-30/31
  (driver, pc_agent, visual_grocery rounds).
- `data/ww_coles_profile_full/` — the 1.31 GB clone (live WW login).
- `MANUAL-STEPS-M2-M3.md` (workspace root) — outstanding manual steps.
