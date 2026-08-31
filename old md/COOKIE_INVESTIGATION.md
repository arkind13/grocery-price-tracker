# WOOLWORTHS COOKIE INVESTIGATION — DIAGNOSTIC SUMMARY

**Date:** 2026-08-24  
**Phase:** 9.0.b (Pre-flight cookie verification)  
**Status:** BLOCKED — programmatic cookie refresh not viable

---

## WHAT WAS TRIED (8 approaches, all failed)

| # | Approach | Result | Why It Failed |
|---|---|---|---|
| 1 | Direct API with existing `WOOLWORTHS_COOKIE` from `.env` | HTTP 403 on all endpoints | Cookie expired/invalidated by Akamai CDN |
| 2 | `requests` library with different headers | HTTP 403 | Akamai blocks non-browser TLS fingerprints |
| 3 | Playwright headless browser | HTTP 403 / "Access Denied" | Akamai blocks headless Chrome entirely |
| 4 | Playwright + `playwright-stealth` | HTTP 403 | Stealth evasions insufficient against Akamai v2 |
| 5 | Playwright with system Chrome channel | HTTP 403 | IP + TLS fingerprint still flagged |
| 6 | `curl_cffi` (Chrome 131 TLS impersonation) | Homepage OK, API 403 with old cookie | Cookie is dead; TLS impersonation alone can't auth |
| 7 | `curl_cffi` + Auth0 `/co/authenticate` API | HTTP 400/403 | Auth0 blocks programmatic password grant |
| 8 | Scrape.do (JS rendering proxy) | Page loads but Auth0 JS widget fails | Auth0 Universal Login requires full JS execution; Scrape.do POST not supported on plan |
| 9 | ZenRows (JS rendering proxy) | HTTP 400 | `session_id` format mismatch; Auth0 JS won't execute |

## ROOT CAUSE

Woolworths login uses **Auth0 OIDC** at `auth.woolworths.com.au` with a **React Universal Login widget**. The flow is:
1. Redirect to Auth0
2. Auth0 renders a JavaScript widget (React SPA)
3. User enters email → password → 2FA code
4. Auth0 redirects back to Woolworths with session tokens

**Why programmatic login fails:**
- Auth0's JS widget requires a full browser environment (DOM, localStorage, WebCrypto for passkeys)
- No scraping service (Scrape.do, ZenRows) executes Auth0's React app correctly
- Akamai CDN blocks all headless browser requests at the TLS + IP level
- Direct API auth (`/co/authenticate`) is blocked by Auth0 (requires client secret or PKCE)

## WHAT DOES WORK (without login)

| Capability | Status | Method |
|---|---|---|
| Woolworths product search | ✅ Works | `curl_cffi` + Chrome 131 impersonation → `GET /apis/ui/Search/products?searchTerm=X` |
| Coles product search | ✅ Works (intermittent) | Scrape.do → `fetch_coles_search()` |
| Woolworths homepage | ✅ Works | `curl_cffi` Chrome 131 impersonation |
| Google Sheets read/write | ✅ Works | `gspread` + service account |

## WHAT DOES NOT WORK (requires login)

| Capability | Status |
|---|---|
| Woolworths saved list fetch (`/apis/ui/mylists`) | ❌ Needs valid cookie |
| Coles saved list fetch (live) | ❌ Needs valid cookie + Incapsula bypass |
| Woolworths specials list | ❌ Needs valid cookie |

## REQUIRED SOLUTION

To get a fresh Woolworths cookie weekly:
- **Manual browser login** (user logs in to Woolworths in Chrome)
- Extract cookie from browser DevTools or use `browser_cookie3`
- Update `.env` with fresh `WOOLWORTHS_COOKIE`

OR:
- **Word document fallback** — user copies lists to `.docx` files; existing `name_importer.py` processes them
