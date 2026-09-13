# MALL-DEALS SETUP — accounts, keys & lessons (one-time, done 2026-09-14)

> Companion to the mall-deals architecture spec (workspace root,
> `../architecture-spec.md`). Written so NOBODY ever re-does this
> setup discovery — every account, every `.env` line, and every dead
> end we already walked, with dates and proof.
> Project = mall & area deals digest (pilot: Westfield Mt Druitt 2770).

## 1. The `.env` lines (workspace root `.env`) — FINAL state

| Line | Status | Notes |
|---|---|---|
| `APIFY_TOKEN` | ✅ working (verified HTTP 200, 2026-09-14) | Free plan: **$5 usage/month** — runs the FB Posts actor + Google Maps actor |
| `TAVILY_API_KEY` | ✅ working (live search verified 2026-09-14 — found Woolworths Mt Druitt's FB page first try) | Free: **1,000 searches/month**. **PRIMARY finder for shop FB pages + missing websites** |
| `SCRAPEDO_API_KEY` | ✅ existing subscription (runs the local-deals sweep already) | Mall-site renders (westfield.com.au 403s plain bots) + FB lane 1 |
| `ZENROWS_API_KEY` | ✅ free tier | First try for shop websites (plain fetch) |
| `GOOGLE_CSE_KEY` / `GOOGLE_CSE_CX` | ⚰️ dead — kept harmlessly | See §3. Do NOT retry |
| OpenRouter / zlm_* / TELEGRAM_* / GCP sheet keys | ✅ already in production | Reused as-is |

No further sign-ups exist or are needed. The postcode list (Job B)
downloads itself (github.com/matthewproctor/australianpostcodes CSV).

## 2. Working accounts & free-tier numbers (quick reference)

| Service | What it does here | Free allowance |
|---|---|---|
| Apify | FB posts reader (actor ~$2–8/1k posts) + Google Maps shops (~$1.50/1k places) + search overflow | $5/month credit (≈ 625–2,500 FB posts or ≈1,250 map results) |
| Tavily | Whole-web search: "shop name + suburb" → FB page / website; results cached forever in the shop registry | 1,000 searches/month |
| Scrape.do | Renders the mall's own site + FB public pages (lane 1) + blocked websites | per current subscription |
| ZenRows | Plain website fetches | free tier |

**Discovery cache rule (the cost trick):** once a shop's FB page /
website is found, it is stored in the shop registry FOREVER — search
only runs for never-resolved or previously-missed shops. Month 1 ≈
230 searches (first full mall); later months ≈ 5–20.

## 3. DEAD END — Google Custom Search (do not retry) ⚠️

Full record, so nobody burns another hour on it:

1. 2026-01-20: Google removed "Search the entire web" from new
   Programmable Search engines (50-domain cap instead). We adapted:
   engine scoped to `facebook.com` only — fine.
2. 2026-09-14: brand-new GCP project (`mall-deals`) + engine +
   API key, everything verified correct (API enabled + toggled
   off/on, fresh keys, right project, personal gmail) → **403
   "This project does not have the access to Custom Search JSON API"
   on every call.** Community + issue-tracker confirmed: **the API is
   closed to new projects** during the wind-down; service EOL
   2027-01-01.
3. Legacy-project lottery: retried on the OLD grocery GCP project
   (`grocerypriceapp-488202`) — key + enable done → **same 403.**
   The closure reaches this account's old projects too.

**Verdict: closed for us, permanently. Tavily replaced it (better:
whole-web, already proven).** The `GOOGLE_CSE_*` lines can be deleted
from `.env` whenever; they're inert.

(Aside: the only APIs that matter in the grocery project are the
Sheets/Drive ones the service account uses — untouched by any of
this.)

## 4. The three-lane Facebook strategy (design, user-set 2026-09-12)

Reading rule: **public pages only, logged out, never a personal FB
login; newest 3 posts / last 5 days per shop** (M14 in the spec).

| Lane | How | Runs |
|---|---|---|
| 1 | Scrape.do logged-out render (same as local-deals sweep) | automatic |
| 2 | Apify FB Posts Scraper actor (no login, proxies handled) | automatic |
| 3 | User's PC + real Chrome via the existing `pc-browser` skill | manual last resort |

## 5. Money ladder (if free tiers ever run out)

$0 (normal use) → Apify Starter $19/mo (heavy scanning) → + Scrape.do
Hobby $29/mo (render credits) → **ceiling ≈ $48/month.** No money
buys FB uptime — lanes + honest "FB unreadable this week" cover that.

## 6. Where the pipeline stands

Spec: workspace root `architecture-spec.md` (v6+). Exception flow:
arch-options (done) → **00 Tester pilot (running)** → arch round 2
(overwrites the spec, from the tester's `pre-arch.md`) → 02 Plan →
03 Code → 04 Checker.
