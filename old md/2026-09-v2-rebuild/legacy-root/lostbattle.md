# Lost Battle — Live Mode (automated store website writes)

> **Verdict:** LOST, RETIRED 2026-09-02. `wednesday --source live` and
> the live-window flush are retired from the reachable pipeline. The
> weekly run is docx-only. Code + tests are SHELVED, not deleted.

## What was the battle

Getting the local machine to do, fully automatically, the two things a
logged-in shopper does on the Woolworths/Coles websites:

1. Log in and stay logged in (a real browser session).
2. Push queued items onto the store "Price Compare" lists (the flush),
   then read all list pages back (the fetch).

Everything else in the project (search, compare, sync, queues, reports)
works without this. This was the "last mile" of the Wednesday live
pipeline.

## Effort

Over 16 hours across 2026-08-24 → 2026-09-02 (the 2026-08-24 cookie
war, the M3 rounds 1–17 automation war, and the live-window campaign).
Full blow-by-blow: [`old md/lostbattle_webautocredentials.md`](old%20md/lostbattle_webautocredentials.md)
— read it before EVER retrying anything in this space.

## Root cause (plain language)

1. **Akamai bot manager** on both stores rejects anything whose
   browser/TLS/IP/behaviour fingerprint is not a real daily-use
   browser. Every workaround profile (cookie transplants, full clones)
   either lacks saved logins or trips device-bound cookie checks.
2. **Chrome 136+ security** forbids automation (Playwright/CDP) on the
   daily profile — the only profile Akamai actually accepts.
3. **Without DOM access, precise clicking is guesswork:** image
   templates break across page states, screenshot diffs break on
   animations, colour targeting is ambiguous.
4. **Woolworths rate-limits/500s** under rapid repeated automation.

These are external, architectural blockers — not bugs in our code. No
amount of local rework fixes a store that refuses non-human traffic and
a browser that refuses automation on the profile the store trusts.

## Why the current approach is unviable

The live mode's core promise — "no human at the store websites" —
requires exactly the two capabilities the blockers remove (trusted
login + reliable in-page action). The workarounds that partially worked
(chunked-typed-JS bridge, vision clicking) were judged "too clunky to
be the product" and still failed on the final click. This is a
fundamental dead end, not a fixable defect list.

## The fallback that replaced it (working today)

The docx pause flow covers the whole need manually:

- Wednesday Step 0 prints both queues (to-do + searched) FIRST.
- The run pauses while you add those items to the store websites and
  paste the updated lists into `Woolworths.docx` / `Coles.docx`.
- Step 1b auto-clears queued items that now appear on the lists;
  Step 1c auto-links exact-name matches (keyword written, priced the
  same run); `add-to-list done` writes the store keyword immediately.

## What was retired vs kept

| Piece | Status |
|-------|--------|
| `wednesday --source live` | Refused at CLI dispatch (clear error + this file) |
| `extractors/session_refresh.py` (live window) | Shelved — unreachable from the pipeline, tests intact |
| `extractors/live_list_fetch.py` (snapshot loader) | Shelved with it |
| `live-refresh` CLI command | Retired (experimental standalone; do not rebuild) |
| `data/live_api_capture.json` (verified add-to-list API call) | Kept — proven artifact for any revival |
| WW search via curl_cffi, Coles search via Scrape.do | **Unaffected** — no login needed, daily use |

## Revival conditions (check ALL before reopening)

1. Chrome lifts the default-profile automation block, OR a CDP-free
   bridge delivery is accepted (one-time manual userscript install).
2. The add-to-list API accepts a seasoned in-page context again.
3. WW item-level 500 rate-limiting is gone under repeated calls.

Do NOT retry: headless browsers, stealth plugins, programmatic
cookie/login refresh, TLS impersonation for auth, scraping-proxy
login, template-image buttons, diff-clicking, chunked typing — all
proven dead (see the archived file §12).
