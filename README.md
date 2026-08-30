# AI Development Environment — Project README

> **This folder (`grocery-price-tracker/`) is the ultimate canonical root for the entire project.** All project code should live here going forward. Any code currently living outside this folder (in the parent `AI related/` directory) is documented in [Code Currently Outside This Folder (Pending Migration)](#code-currently-outside-this-folder-pending-migration) and will be migrated into this folder later.

A unified, personal AI development environment built around **OpenClaw** ("Claw") — a Telegram-native AI assistant running on a VPS. Claw orchestrates a collection of Python tools (grocery price tracking, expense analysis, LLM pricing, web scraping, image generation, and more) that are exposed as OpenClaw *skills* and invoked conversationally via Telegram, the web UI, or the CLI.

The local machine (Windows + Anaconda) is the development workspace; the VPS (Docker) is the production runtime.

---

## Table of Contents

1. [What's Inside This Folder](#whats-inside-this-folder)
2. [Architecture at a Glance](#architecture-at-a-glance)
3. [Environments — Local, VPS, GitHub](#environments--local-vps-github)
4. [The OpenClaw Runtime (VPS)](#the-openclaw-runtime-vps)
5. [Grocery Price Tracker (flagship tool)](#grocery-price-tracker-flagship-tool)
6. [Telegram Gateway](#telegram-gateway)
7. [Claw Skills](#claw-skills)
8. [Other Tools](#other-tools)
9. [Code Currently Outside This Folder (Pending Migration)](#code-currently-outside-this-folder-pending-migration)
10. [Secrets & Environment Variables](#secrets--environment-variables)
11. [Common Workflows](#common-workflows)
12. [Quick Commands](#quick-commands)
13. [Project Conventions](#project-conventions)

---

## What's Inside This Folder

```
grocery-price-tracker/                      ← ULTIMATE PROJECT ROOT (this folder)
├── README.md                              ← this file
├── __init__.py                            ← package marker
├── app.py                                 ← Streamlit app (legacy UI, mostly superseded by headless CLI)
├── local_sync.py                           ← legacy rapidfuzz-based sync (superseded by lookup engine)
├── name_importer.py                        ← saved-list name import helper
├── Woolworths_Historical.py                ← historical Woolworths price export
├── requirements.txt                        ← Python deps (gspread, google-auth, python-docx, curl_cffi, etc.)
├── runtime.txt                             ← runtime version pin
├── packages.txt                            ← system packages
├── LEGACY_AUDIT.md                         ← audit of legacy/superseded modules
├── LICENSE
├── .gitignore
├── .git/                                   ← nested git repo (Phase 9 work)
├── .pytest_cache/  .streamlit/             ← caches (gitignored)
│
├── core/                                   ← core library (lookup, sheets, comparator)
├── extractors/                             ← Woolworths/Coles/Aldi live extractors + doc parser
├── components/                             ← (reserved, currently empty)
├── data/                                   ← runtime state (unmatched lists, progress, queues)
├── tests/                                  ← 137+ tests (lookup, live search, sync, comparator, cli)
│
├── Aldi.docx  Coles.docx  Woolworths.docx ← saved-list source files (pasted by user, parsed by doc_parser)
├── Woolworths_Specials.docx                ← specials source file
├── woolworths_master_comparison.csv        ← master comparison export
├── credentials.json                        ← local Google service-account (gitignored; VPS uses env var)
├── prompt to add woolworths savings button.txt
└── Telegram Commands.txt
```

---

## Architecture at a Glance

```
┌──────────────────────────────────────────────────────────────────┐
│  USER                                                             │
│  Telegram app ──── DMs @ClawArkindBot (chat 1594431983)            │
│                   Web UI (https://169-58-107-0.sslip.io)          │
│                   CLI (openclaw agent / openclaw message)         │
└──────────────────────────┬───────────────────────────────────────┘
                           │ Telegram long-poll (getUpdates)
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  VPS  169.58.107.0  (Ubuntu)   SSH alias: myvps                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Docker container: openclaw-core  (image openclaw-core:sketch)│ │
│  │  OpenClaw gateway 2026.6.34  (Node, /app/openclaw.mjs)       │ │
│  │   ├─ Telegram channel (@ClawArkindBot)                      │ │
│  │   ├─ Agent model: openrouter/qwen/qwen3.7-flash             │ │
│  │   ├─ Control API: port 18789 (in-container)                 │ │
│  │   └─ Skills loaded from /app/tasks/ai-tools/claw-skills/   │ │
│  │       (bind-mount ← /home/ubuntu/openclaw/tasks/ai-tools/)  │ │
│  └─────────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Docker: ai-studio-app (Next.js) + ai-studio-db (Postgres 16)│ │
│  └─────────────────────────────────────────────────────────────┘ │
│  /home/ubuntu/scripts/wednesday_reminder.py  (cron, every 5 min) │
└──────────────────────────┬───────────────────────────────────────┘
                           │ scp / tar sync (NOT git pull — branches diverged)
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  LOCAL  Windows + Anaconda Python                                 │
│  C:\Users\User.DESKTOP-R2G441H\Documents\AI related\             │
│   └── grocery-price-tracker\   ← THIS FOLDER (ultimate root)     │
│       (parent "AI related" also holds sibling tools — see below)  │
└──────────────────────────┬───────────────────────────────────────┘
                           │ git push
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  GITHUB  arkind13/AI-Development-Environment  (private)         │
│  main = local dev HEAD.  master = VPS HEAD (diverged).           │
└──────────────────────────────────────────────────────────────────┘
```

---

## Environments — Local, VPS, GitHub

### 1. Local Windows Machine (Development)

**Parent dir:** `C:\Users\User.DESKTOP-R2G441H\Documents\AI related\`
**This folder (ultimate root):** `...\AI related\grocery-price-tracker\`

Anaconda Python (`anaconda3\python.exe`) is the default interpreter. The local `.env` (in the parent dir) holds all secrets and is gitignored — never committed.

> **Note on layout:** The parent `AI related\` directory currently mirrors the VPS `tasks/ai-tools/` layout (the CLI entrypoint `grocery_price_cli.py`, `claw-skills/`, `telegram_gateway/`, and all sibling tools live as siblings of this folder). The plan is to migrate all of those into this `grocery-price-tracker/` folder so it becomes the single root. See [Code Currently Outside This Folder](#code-currently-outside-this-folder-pending-migration).

### 2. VPS (Production Runtime)

**Host:** `ubuntu@169.58.107.0` (SSH alias: `myvps`)
**Root:** `/home/ubuntu/openclaw/`

The VPS runs the OpenClaw gateway inside a Docker container (`openclaw-core`). The container's `/app/tasks` is a **live bind-mount** of the host's `/home/ubuntu/openclaw/tasks/ai-tools/` — so any file synced to the host repo is immediately visible inside the container (no rebuild needed, survives container restarts).

```
/home/ubuntu/openclaw/
├── openclaw.json                 — gateway config (providers, telegram, skills, tools)
├── docker-compose.yml             — openclaw-core service definition
├── Dockerfile.claw-render         — render image (Playwright + Chromium)
├── .env  → /home/ubuntu/.env      — secrets symlink (all env vars live here)
├── NEW_GATEWAY_TOKEN.txt          — gateway control-API token
├── pylibs/                        — Python packages (PYTHONPATH=/app/pylibs, Python 3.11)
├── pip-bootstrap/                 — minimal Python 3.12 venv
├── scp_staging/                   — deployment staging artifacts
├── tasks/
│   ├── ai-tools/                  — ← MIRRORS LOCAL "AI related" ROOT
│   │   ├── grocery_price_cli.py
│   │   ├── grocery-price-tracker/   ← THIS FOLDER (on VPS)
│   │   ├── claw-skills/
│   │   ├── telegram_gateway/
│   │   └── (all sibling tools)
│   ├── aistudio/                  — AI Studio task metadata
│   └── diag*.sh                   — diagnostic scripts
└── scripts/  (sibling, NOT in git — scp'd directly)
    ├── wednesday_reminder.py      — cron-fired grocery-sync reminder sender
    ├── .wednesday_reminder_state.json — idempotency state
    └── wednesday_reminder.log     — cron stdout/stderr
```

**Bind mounts (container → host):**

| Container path | Host path | Mode |
|----------------|-----------|------|
| `/app/tasks` | `/home/ubuntu/openclaw/tasks` | rw (live) |
| `/app/openclaw.json` | `/home/ubuntu/openclaw/openclaw.json` | rw |
| `/home/node/.openclaw/openclaw.json` | `/home/ubuntu/openclaw/openclaw.json` | rw |
| `/app/pylibs` | `/home/ubuntu/openclaw/pylibs` | ro |
| `/app/tasks/ai-tools/.env` | `/home/ubuntu/openclaw/.env` | ro |

### 3. GitHub

**Repo:** `arkind13/AI-Development-Environment` (private)
**URL:** `https://github.com/arkind13/AI-Development-Environment.git` (VPS uses `git@github.com:...`)

| Branch | Where | Notes |
|--------|-------|-------|
| `main` | Local working branch | Primary dev branch — Phase 9 work, lookup engine, no-login approach |
| `master` | VPS checkout | Diverged from `main`; has unpushed local commits. The VPS working tree is the source of truth for what the container runs (bind mount reads working tree, not HEAD). |

> **Syncing:** Local has uncommitted working-tree changes. Syncing to VPS is done via `scp`/tar, not `git pull`, because branches diverged. See [Common Workflows](#common-workflows).

---

## The OpenClaw Runtime (VPS)

### Container: `openclaw-core`

- **Image:** `openclaw-core:sketch`
- **Process:** tini → `openclaw` (Node, `/app/openclaw.mjs`) — the gateway
- **Version:** OpenClaw 2026.6.34
- **Gateway mode:** `local`
- **Control API port:** `18789` (in-container, not published to host — reached via `docker exec`)
- **Agent model:** `openrouter/qwen/qwen3.7-flash` (thinking=medium)
- **Telegram bot:** `@ClawArkindBot` (token in env `TELEGRAM_CLAW_BOT`)
- **Allowlisted DM chat:** `1594431983` (owner)
- **Skills dir:** `/app/tasks/ai-tools/claw-skills` (bind-mounted)

### Gateway config (`openclaw.json`)

| Config path | Value |
|-------------|-------|
| `gateway.mode` | `local` |
| `channels.telegram.enabled` | `true` |
| `channels.telegram.botToken` | `${TELEGRAM_CLAW_BOT}` (env reference) |
| `channels.telegram.dmPolicy` | `allowlist` |
| `channels.telegram.allowFrom` | `[1594431983]` |
| `commands.ownerAllowFrom` | `["telegram:1594431983"]` |
| `skills.load.extraDirs` | `["/app/tasks/ai-tools/claw-skills"]` |
| `agents.defaults.model.primary` | `openrouter/qwen/qwen3.7-flash` |

### State (inside container, `/home/node/.openclaw/`)

```
.openclaw/
├── openclaw.json              — effective config (mounted from host)
├── openclaw.json.last-good    — last known-good config snapshot
├── agents/main/sessions/sessions.json  — conversation session store
├── identity/                  — device pairing / identity keys
├── state/                     — gateway runtime state
├── workspace/                 — agent workspace (memory, .git)
├── plugin-skills/             — bundled plugin skills cache
└── telegram/                  — ingress spool (polling buffer)
```

### OpenClaw CLI (run inside container)

```bash
# Run an agent turn via the gateway (the faithful "Telegram test" path):
docker exec openclaw-core node /app/openclaw.mjs agent \
  --channel telegram --to 1594431983 \
  --message "compare green capsicum in woolworths and coles" --deliver

# Other useful subcommands:
docker exec openclaw-core node /app/openclaw.mjs status        # gateway/channel status
docker exec openclaw-core node /app/openclaw.mjs skills list   # loaded skills
docker exec openclaw-core node /app/openclaw.mjs sessions list # conversation sessions
docker exec openclaw-core node /app/openclaw.mjs health        # gateway health
docker logs openclaw-core --tail 50                            # recent logs
```

### Other VPS containers

| Container | Image | Purpose |
|-----------|-------|---------|
| `ai-studio-app` | ai-studio image | Next.js 16 AI Studio web app (chat studio) |
| `ai-studio-db` | postgres:16-alpine | AI Studio database |

---

## Grocery Price Tracker (flagship tool)

The most complex tool. Tracks Australian supermarket prices (Woolworths, Coles, Aldi) by maintaining a Google Sheet of canonical products and periodically syncing live prices.

### Entry point

**`grocery_price_cli.py`** — headless CLI (lives in the parent `AI related\` folder, see [migration section](#code-currently-outside-this-folder-pending-migration)). Subcommands:

| Subcommand | Args | What it does |
|------------|------|--------------|
| `compare` | `--items` (req) `[--mode auto\|sheet\|live]` `[--team-discount]` `[--extra-discount FLOAT]` | Basket comparison; `--mode auto` = sheet-first then live fallback. Both-live items pass the UOM 20% size gate; non-comparable items render as a found-block and are excluded from totals |
| `search` | `--product` (req) `[--expand]` `[--add-item N]` | Pure live search (Woolworths API + Coles Scrape.do recipe); no sheet, never writes. ≤3 ranked results per store (8 with `--expand`); `--add-item N` = explicit add of the Nth result (sheet row with EMPTY keyword col + searched-items queue) |
| `specials` | `[--store woolworths\|coles\|all]` | Active specials (sheet Mode B + Woolworths saved-list Mode A) |
| `rewards` | `[--store ...]` | Reads rewards column (O); prints "not populated" when empty |
| `recipe` | `--name` `--ingredients` | Wraps `compare_basket(mode="auto")` for recipe ingredients |
| `update` | `--product` `--store` `--price` `[--dry-run]` | Writes a single price to the sheet |
| `sync` | `[--force]` `[--dry-run]` | Extract → match → batch sheet write + queue summary |
| `specials-scan` | `[--min-savings INT]` `[--store woolworths]` | Tier 2 site-wide scan → Tier 1 saved-list |
| `unmapped` | — | Reads `data/unmapped_queue.json`; offline-safe |
| `map` | `unmatched\|wool\|coles\|status` + flags | One-item-at-a-time list resolution (non-interactive) |
| `add-to-list` | `show` / `done --items "1,2,3"` | Manual website-add queue: show pending items (Coles then Woolworths, continuous numbering) / mark items done (all-or-nothing, re-prints the remainder). Offline-safe. |
| `searched-items` | `show` / `remove --items "KAT,RUM"` / `clear` | Searched-items queue (explicit Wednesday adds): 3-letter codes (A–Z minus I/O, no repeated letter), all-or-nothing removal, 7-day code tombstones. Offline-safe. |
| `live-refresh` | `[--flush-only]` `[--fetch-only]` `[--recapture]` | **LOCAL WINDOWS MACHINE ONLY** (headed Chrome + AU residential IP): login once → flush both queues to the store "Price Compare" lists → fetch all list pages (30-page cap) → write snapshots. The agent never runs this. |
| `wednesday` | `[--source docx\|live]` (default docx) `[--dry-run]` `[--no-scp]` `[--no-telegram]` | Full pipeline. `docx` = previous behaviour byte-for-byte. `live` = VPS queue pull → live window (skipped when today's snapshots exist) → snapshot completeness gate (clean stop before any sheet write) → sync from snapshots → specials from the live Special-list snapshot |
| `backfill-keywords` | — | Backfill Col P keywords from existing data |

> **Routing rule (critical):** `compare X in/at woolworths and coles` must always route to `compare --items "X"` (sheet-first), NEVER `search` (live-only). The `grocery-price/SKILL.md` enforces this.

> **Weekly add-to-list loop:** a wool/coles `map --add` writes the price AND queues the item on `add_to_list`. Later, on the store website, add the queued items to your shopping list, then run `add-to-list done --items "1,2,3"` to clear them — the item resurfaces in the missing list (and eventually the unmatched report) until you do, so nothing is silently dropped.

> **Explicit-add-only + UOM gate (2026-08):** nothing is ever auto-queued. Plain `compare`/`search`/`expand` never write; the only live→sheet routes are `search --add-item N` and `map unmatched --add` (both leave the store keyword column EMPTY). A live item enters a comparison only via a UOM-passing pair (`core/uom.py`: same measurement family, within 20% size, no per-unit prices ever) or when the other store is unavailable (Woolworths-only answer + one ⚠️ line). Coles search runs through a credit-guard (3-attempt silent retry, 40/call-run cap, 10-min circuit breaker in `data/scrapedo_health.json`).

### Core library (`core/`)

| File | Purpose |
|------|---------|
| `lookup.py` | **Lookup engine** — query resolution chain: exact sheet match (Col A / store keywords I/J/K) → Col P alias two-pass → partial candidates → live search (ranked per store, UOM-gated pair selection, display-only). `LookupIndex` builds `_exact` and `_alias_exact` indices; `LookupEngine` orchestrates the chain; `rank_live_results` / `select_live_pair` implement the tolerant ranking + 20% size gate. |
| `uom.py` | **Unit-of-measure gate** — parses package sizes (25L → 25000 mL, multipacks to totals), compares within families only, 20% tolerance band. Pure stdlib; the sole gate on both-live comparisons. |
| `sheets_client.py` | Shared headless Google Sheets connection (via `GROCERY_SERVICE_ACCOUNT_JSON` + `GROCERY_SPREADSHEET_ID` env vars) |
| `sheets_sync.py` | Batch sync, `update_single_price`, `add_product_row`, range-width-aware row writes |
| `price_comparator.py` | Dual-mode basket comparator; in `auto` mode uses the lookup engine via `_gather_lookup_prices()`. Every store line carries identity + provenance (`— name size (sheet|live)`); non-comparable items render the found-block and are excluded from totals |
| `searched_items.py` | Queue-2 (explicit Wednesday adds): 3-letter codes (A–Z minus I/O, no repeated letter), dup-guarded adds, all-or-nothing code removal, 7-day code tombstones. Mirror of `add_to_list.py` |
| `name_matcher.py` | Exact keyword matcher for the sync path (Col I/J/K) |
| `recipe_resolver.py` | Sheet exact → partial → live search resolver for recipe ingredients |
| `specials_reporter.py` | Reads specials/rewards columns from the sheet |
| `missing_items_tracker.py` | Cross-store missing-items diff |
| `woolworths_discounts.py` | Always-on 5% Woolworths display discount + extra 5% home-brand engine; 32-brand home-brand list; monthly extra-discount tracker |
| `schema_upgrade.py` | Idempotent column audit (adds columns M/N/O/P if missing) |
| `list_names.py` | Pinned saved-list name constants |
| `env_probe.py` | Env var verification |
| `auth0_*.py`, `curl_cffi_*.py`, `scrapedo_*.py`, `scraping_login.py`, `stealth_login_test.py` | Auth/login experiments (Playwright, Auth0, Scrape.do, curl_cffi impersonation) — mostly legacy/superseded by the no-login approach |
| `check_scrapedo.py`, `check_settings.py`, `diagnose_cookie.py`, `extract_chrome_cookies.py`, `login_attempts.py`, `query_mylists.py`, `scan_*.py`, `test_search_noauth.py`, `trace_oidc.py` | Diagnostic/probe utilities |

### Extractors (`extractors/`)

| File | Purpose |
|------|---------|
| `woolworths_extractor.py` | Woolworths API client: saved lists (`/apis/ui/mylists`), list items, product detail, search (no-login via curl_cffi Chrome 131 impersonation in Phase 9.2) |
| `coles_extractor.py` | Coles client: Scrape.do GET → parse `__NEXT_DATA__` → `pageProps.searchResults.results`; credit-guarded search chain (3-attempt silent retry with fresh sessions, 40-call per-run cap, 10-min circuit breaker, never retries 401/403); `.docx` fallback for saved lists |
| `live_list_fetch.py` | Offline snapshot loader for the Wednesday live path: reads `data/live_snapshots/YYYY-MM-DD_*` files, converts to ProductItems (id dedup, multipage-safe), `validate_complete()` all-or-nothing gate. No network. |
| `session_refresh.py` | Live-window orchestrator (LOCAL only): Phase A login (headed Chrome + persistent profile + 2FA wait) → Phase B throttled queue flush (session-death abort, 3-strike park) → Phase C paginated list fetch (30-page cap) → snapshots. Plus API-discovery capture and the cookie-only heartbeat probe. Playwright imported lazily. |
| `doc_parser.py` | Parses `Woolworths.docx` / `Coles.docx` / `Aldi.docx` / `Woolworths_Specials.docx` into `ProductItem` lists (headless, via python-docx) |
| `session_manager.py` | Coles auth session management |
| `auth_manager.py` | Playwright auto-login auth manager (2FA, compulsory logout) — superseded by no-login approach |
| `hub.py` | Extractor hub/router |
| `models.py` | Shared data models (`ProductItem`, etc.) |
| `probe_supermarkets.py` | Supermarket endpoint probe utility |
| `probe_results.json`, `ww_full_export.json`, `ww_products_export.json` | Probe/export data snapshots |

### Data (`data/`)

Runtime state files (not in git; synced between local↔VPS):

| File | Purpose |
|------|---------|
| `unmatched.txt` / `coles_missing.txt` / `wool_missing.txt` | Items not matched during sync (resolved via `map`) |
| `unmapped_queue.json` | JSON queue for unmapped items |
| `list_action_progress.json` | `map` session progress (resume indices) |
| `ignored_items.txt` | Permanently-excluded junk items (`map --forget`) |
| `add_to_list.json` | Manual website-add queue (fed by wool/coles `map --add`; drained by `add-to-list done`) |
| `searched_items.json` / `searched_item_code_tombstones.json` | Queue-2 (explicit Wednesday adds via `search --add-item` / `map unmatched --add`; drained by the live-window flush; removed codes tombstoned 7 days) |
| `session_state.json` / `ww_coles_profile/` | **Secrets** — live-window cookies + browser profile (gitignored, never committed, never printed) |
| `live_snapshots/` | `YYYY-MM-DD_<store>_<list>.json` list snapshots written by the live window, read by `wednesday --source live` |
| `live_api_capture.json` | Discovered add-to-list API + pagination shape per store |
| `live_flush_log.json` | Per-item flush results (status/reason/attempts; rotated at ~1 MB) |
| `scrapedo_health.json` | Scrape.do circuit-breaker state |
| `session_heartbeat.log` | Cookie-only liveness probe log (alive/dead/unknown) |
| `sheets_manager.py` | Sheet-state management helper |
| `phase9_defect_log.json` | Phase 9 defect tracking |
| `woolworths_discount_usage.json` | Discount usage tracking |
| `diagnostics/` | Diagnostic snapshots |

### Tests (`tests/`)

| File | Scenarios |
|------|-----------|
| `test_lookup.py` | 15 GROUP A lookup state-machine scenarios |
| `test_lookup_uom.py` | 18 UOM-gate Step-5 tests: ranking, pair selection, single-store/unavailable routing, Steps 1–4 golden regression |
| `test_uom.py` | 24 size-parse + comparability gate tests |
| `test_searched_items.py` | 30 Queue-2 tests: codes, tombstones, atomic IO, render |
| `test_coles_recipe.py` | 19 Scrape.do credit-guard tests: params, retry chain, breaker, cap, probes |
| `test_live_window.py` | 30 live-window tests: snapshot loader (F), flush engine + pagination + heartbeat (W) |
| `test_live_search.py` | 13 GROUP B Woolworths+Coles mocked integration tests |
| `test_sheets_sync.py` | 29 tests: `add_product_row` (incl. `Home` Col G marker), `mark_not_available`, `set_store_keyword`, Col I/J/K |
| `test_name_matcher.py` | 25 Col P two-pass lookup tests |
| `test_comparator.py` | 42 live-search + always-on discount comparison + UOM report tests |
| `test_cli.py` | 96 search/map/compare/discount-surface/backfill/live-routing tests |
| `test_woolworths_discounts.py` | 24 always-on WW discount tests: 32-brand detection, compounding math, engine, tracker guard |
| `test_extractors.py` | Extractor unit tests |
| `test_sheets_conn.py` | Sheets connection tests |

**Total: 446 tests passing, 0 failed** (the 8 stale Phase-1 failures in
`test_extractors.py` were repaired by the 04 Checker on 2026-08-29 — see
`test.md`; the repaired test files were synced to the VPS on 2026-08-30.
Testing runs locally — the VPS/container has no pytest).

### Google Sheet schema

The tracker reads/writes a Google Sheet (`GROCERY_SPREADSHEET_ID = 16INuFvOUVUY37onpVhdC7_ShLr6bQYg4OGpFPXZT9oM`). Key columns:

| Col | Header | Purpose |
|-----|--------|---------|
| A | Generic Name | Canonical product name (exact-match target) |
| D/E/F | Woolworths/Coles/Aldi price | Stored **raw** prices (never discounted in the sheet) |
| G | Brand | Brand name; literal `Home` marks Woolworths home-brand rows (drives the extra home-brand discount) |
| I/J/K | Store keywords | Exact-match keywords for sync path (Wool/Coles/Aldi) |
| M/N/O | Specials/rewards flags | |
| P | Keywords | Alias list (delimiter-separated; two-pass lookup target) |

### Woolworths always-on display discounts

Every Woolworths price **shown to the user** (compare, search, recipe,
specials, specials-scan, rewards, map/lookup prints, Wednesday specials
report) is automatically discounted at display time:

- **5% off every Woolworths price**, plus an **additional 5% off Woolworths
  home-brand items** (compounds to ≈9.75%; discount math in
  `core/woolworths_discounts.py`, history note in
  [`architecture-spec.md`](architecture-spec.md) §"Replaces" — the original
  spec archive `architecture-spec-woolworths-discounts.md` is no longer on
  disk).
- Prices are printed PLAIN (e.g. `$3.61`) — the team discount is never
  shown as a "(was $x)" suffix. A `(was $x)` suffix appears ONLY when the
  store itself reports the item on special with a WasPrice.
- The Google Sheet always stores **raw** prices — discounts are display-only.
- Home-brand detection and the 32-brand list (Apollo, Balnea, … Woolworths)
  live in `core/woolworths_discounts.py`. The sheet's Col G `Home` marker is
  also recognised.
- When new rows are added (`add_product_row`), a home-brand item's Brand cell
  (Col G) is written as `Home` automatically. `backfill-home-brands` can
  normalise existing rows.
- Coles/Aldi prices are never discounted. The monthly `--extra-discount`
  flag is a separate, unchanged mechanism.

### Woolworths team discount — ONE-LINE on/off switch

The entire team discount is controlled by a single constant at the top of
`core/woolworths_discounts.py`:

```python
TEAM_DISCOUNT_ENABLED = True   # False = show original raw Woolworths prices
```

| Value | Behaviour |
|-------|-----------|
| `True` (default) | All WW prices **displayed** with the team discount (5% + 5% home-brand extra). |
| `False` | EVERY surface automatically reverts to the **original raw Woolworths price** — compare, search, recipe, specials, specials-scan, rewards, map/lookup, the Wednesday report, and cheapest-store math. No other code changes needed. |

Example for the same item (home-brand fetta, sheet price $4.00):

```
TEAM_DISCOUNT_ENABLED = True    🟢 Woolworths  $3.61
TEAM_DISCOUNT_ENABLED = False   🟢 Woolworths  $4.00
```

**How to toggle:**

1. Edit the one line in `grocery-price-tracker/core/woolworths_discounts.py`.
2. Local use: nothing more — every CLI run picks it up immediately.
3. Production (VPS): sync the one file — no Docker restart needed (the CLI
   runs fresh each call and the folder is a live bind-mount):

   ```powershell
   scp core\woolworths_discounts.py myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/core/woolworths_discounts.py
   ```

**Per-call override (works regardless of the switch):**
`compare`/`recipe` accept `--team-discount` / `--no-team-discount` to force
discounts on/off for a single call without touching the switch (their
default is to follow `TEAM_DISCOUNT_ENABLED`).

### Live APIs used

**Woolworths** (no login required in Phase 9.2):
- Lists: `GET /apis/ui/mylists`
- List items: `GET /apis/ui/mylists/{id}`
- Product detail: `GET /apis/ui/product/detail/{ArticleId}`
- Search: `GET /apis/ui/Search/products?searchTerm=X` (curl_cffi Chrome 131 impersonation)
- Key fields: `DisplayName`, `Price`, `IsOnSpecial`, `WasPrice`, `Brand`, `PackageSize`, `CupString`

**Coles** (Scrape.do bypass for Incapsula WAF):
- Search: Scrape.do GET search page → parse `__NEXT_DATA__` → `pageProps.searchResults.results`
- List: `Coles.docx` fallback (python-docx)
- Key fields: `name`, `brand`, `size`, `pricing.now`, `pricing.was`, `pricing.onlineSpecial`

**Aldi:** No live extractor — Aldi prices are sheet-only (`—` in compare tables).

---

## Telegram Gateway

**`telegram_gateway/`** — a Python Telegram bot framework (separate from the OpenClaw gateway). Lives in the parent folder (pending migration). Provides budget-sheets integration, command review, and the Wednesday grocery-sync reminder cron.

| File | Purpose |
|------|---------|
| `bot.py` | Bot initialization and main loop |
| `handlers.py` | Message handlers (incl. `handle_done` for the Wednesday reminder `done` reply) |
| `commands.py` | Command definitions/routing |
| `budget_sheets.py` | Budget Google Sheet tool (deployed as Claw `budget-sheets` skill) |
| `allowlist.py` | Allowed-user enforcement |
| `topics.py` | Telegram forum-topic routing (Claw Command Center supergroup) |
| `runner.py` | Bot runner entrypoint |
| `wednesday_reminder.py` | One-shot Wednesday grocery-sync reminder sender (deployed to `/home/ubuntu/scripts/` on VPS, cron every 5 min) |
| `health_check.py` | Bot health check |
| `command_review_registry.md` | Command review documentation |
| `.env.example` | Environment template |

### Wednesday Reminder (VPS cron)

Deployed outside the git tree (`/home/ubuntu/scripts/`) to avoid git-pull clobbering:

- **Cron:** `*/5 * * * * /usr/bin/python3 /home/ubuntu/scripts/wednesday_reminder.py >> .../wednesday_reminder.log 2>&1`
- **Self-gating:** Sydney time Wed 05:00–05:30 AEST/AEDT (DST-correct via `zoneinfo`; VPS host tz is Europe/Berlin but doesn't affect delivery)
- **Delivery:** user DM + `grocery-sync-sheet` topic (thread 151 in the Claw Command Center supergroup)
- **Test:** `ssh myvps 'python3 /home/ubuntu/scripts/wednesday_reminder.py --test'`
- **Status:** `... --status` (prints Sydney now, last sent, next fire)

---

## Claw Skills

Each tool has a `SKILL.md` that tells the OpenClaw agent how to invoke it. The skills directory (`claw-skills/`) lives in the parent folder (pending migration) and is bind-mounted into the container at `/app/tasks/ai-tools/claw-skills/`.

| Skill | SKILL.md | Description |
|-------|----------|-------------|
| `grocery-price` | `grocery-price/SKILL.md` | Supermarket prices, basket compare, specials, sync, resolve |
| `budget-sheets` | `budget-sheets/SKILL.md` | Budget Google Sheet updates (balance, allowance, pay) |
| `claude-pricing` | `claude-pricing/SKILL.md` | Claude model pricing |
| `gpt-pricing` | `gpt-pricing/SKILL.md` | GPT model pricing |
| `video-pricing` | `video-pricing/SKILL.md` | Video model pricing |
| `discounts` | `discounts/SKILL.md` | OpenRouter discounted/promo models |
| `free-models` | `free-models/SKILL.md` | Free-tier models on OpenRouter |
| `daily-digest` | `daily-digest/SKILL.md` | New AI model releases in last 24h |
| `openrouter-usage` | `openrouter-usage/SKILL.md` | OpenRouter spend history |
| `expenses-summary` | `expenses-summary/SKILL.md` | Expense totals + category breakdown |
| `expenses-view` | `expenses-view/SKILL.md` | Detailed expense view |
| `image-studio` | `image-studio/SKILL.md` | Image generation (Flux / Seedream) |
| `sketchnote` | `sketchnote/SKILL.md` | YouTube → sketchnote images |
| `web-scrape` | `web-scrape/SKILL.md` | Web page scraping (ZenRows → Scrape.do) |

The `grocery-price/SKILL.md` is the most detailed skill file — it defines subcommand→intent mappings, the NL routing table, multi-turn conversation flows (resolve sessions), degradation rules, and hard rules for the agent.

### Telegram message formatting (all skills)

All Claw skill output shown on Telegram uses the shared **Telegram Style Kit** (`core/telegram_format.py`): no markdown tables (they break in Telegram), list-style item blocks, fenced monospace totals, unicode dividers, and a shared icon vocabulary. SKILL.md files instruct the agent to relay CLI output verbatim. Spec: [`architecture-spec-telegram-formatting.md`](architecture-spec-telegram-formatting.md).

The kit is stdlib-only and imports nothing from siblings. Key API:

- `header(title, icon)` / `subheader(title, icon=None)` — CAPS title + heavy `━`×20 / light `─`×10 divider.
- `item_block(index, name, prices, home_brand=False)` / `store_line(store, price, was=None)` — list-style items with 🟢/🔴 aligned price lines.
- `fenced_table(headers, rows, box=False)` — padded ```-fenced table, equal-width lines, ≤ `MAX_BLOCK_WIDTH` (34) cells.
- `money(n)` / `kv(l, v)` / `tail(w, s, vs)` / `warn` / `ok` / `fail` / `footer(ts)` / `truncate(s, width)`.

Example:

```python
from core.telegram_format import header, fenced_table

print(header("Basket Comparison", "🛒"))
print(fenced_table(
    ["Store", "Raw", "Final"],
    [["Woolworths", "$23.40", "$21.75"], ["Coles", "$24.10", "$24.10"]],
    box=True,
))
```

Width budgets: `MAX_NAME_WIDTH = 24` (product names), `MAX_BLOCK_WIDTH = 34` (fenced blocks, phone-fit). Emoji count as 2 cells (`_cells()`).

---

## Other Tools

### Daily Models Digest (`daily-models-digest/`)
- `daily_digest.py` — scans OpenRouter for model releases in the last 24h, posts a digest. GitHub Actions workflow (`.github/workflows/daily_models.yml`).

### OpenRouter Model Costs (`openrouter model costs/`)
- `claude_pricing.py`, `gpt_pricing.py`, `Openroutervideo.py`, `free_api.py`, `cheapest_models.py`, `Discount_github.py` — per-token pricing, release dates, discounts, free models, cheapest models.

### OpenRouter Usage (`openrouter_usage/`)
- `Code_for_usage.py` — fetches OpenRouter usage, builds `OpenRouter_Usage_Summary.xlsx`. Stores historical CSV snapshots.

### Credit Card Tracking (`Credit_Card_Tracking/`)
- `category.py` — categorizes credit-card expenses, builds monthly summaries (`expense_summary.xlsx`).
- `visualize_expenses.py` — expense visualization.
- `expense_summary_wool.py` — Woolworths-specific expense summary.

### Scraping API (`scraping_api/`)
- `scrape.py` — shared web-fetch helper. ZenRows primary, Scrape.do fallback. Used by other tools.

### Image Generator (`Image Generator Code/`)
- `image_studio.py`, `app.py` — image generation via Flux 2 / Seedream 5 APIs.

### Sketchnote Generator (`Sketchnotes_ytube_video/`)
- `sketchnote_generator.py` — generates sketchnote images from YouTube videos.

### AI Studio (`ai-studio/`)
- Next.js 16 App Router app — a ChatGPT-like chat studio. Deployed as `ai-studio-app` container + `ai-studio-db` (Postgres). Specs in `MASTER_BUILD_SPEC.md`.

### My Budget Tracker (`my-budget-tracker/`)
- Streamlit personal budget app (git submodule, not deployed to Claw).

---

## Code Currently Outside This Folder (Pending Migration)

> The following code currently lives in the parent directory `C:\Users\User.DESKTOP-R2G441H\Documents\AI related\` (and mirrors VPS `/home/ubuntu/openclaw/tasks/ai-tools/`). The plan is to migrate all of these into this `grocery-price-tracker/` folder so it becomes the single ultimate root. On the VPS, the corresponding paths are under `/home/ubuntu/openclaw/tasks/ai-tools/`.

| Item (in parent dir) | VPS path | Type | Purpose | Migration priority |
|----------------------|----------|------|---------|--------------------|
| `grocery_price_cli.py` | `tasks/ai-tools/grocery_price_cli.py` | Python CLI | **Main entrypoint** for the grocery tracker (headless CLI with all subcommands) | **HIGH** — should move into this folder |
| `discounts_cli.py` | `tasks/ai-tools/discounts_cli.py` | Python CLI | Discounts CLI helper | Medium |
| `create_env.py` | `tasks/ai-tools/create_env.py` | Python script | `.env` generation helper | Low |
| `claw-skills/` | `tasks/ai-tools/claw-skills/` | Skill defs (14 `SKILL.md`) | OpenClaw skill definitions — `grocery-price/`, `budget-sheets/`, `claude-pricing/`, `gpt-pricing/`, `video-pricing/`, `discounts/`, `free-models/`, `daily-digest/`, `openrouter-usage/`, `expenses-summary/`, `expenses-view/`, `image-studio/`, `sketchnote/`, `web-scrape/` | **HIGH** — `grocery-price/SKILL.md` belongs with this folder |
| `telegram_gateway/` | `tasks/ai-tools/telegram_gateway/` | Python bot framework | Telegram bot: `bot.py`, `handlers.py`, `commands.py`, `budget_sheets.py`, `allowlist.py`, `topics.py`, `runner.py`, `wednesday_reminder.py`, `health_check.py` | Medium |
| `daily-models-digest/` | `tasks/ai-tools/daily-models-digest/` | Python tool | `daily_digest.py` + GitHub Actions workflow | Medium |
| `openrouter model costs/` | `tasks/ai-tools/openrouter model costs/` | Python tools | LLM pricing: `claude_pricing.py`, `gpt_pricing.py`, `Openroutervideo.py`, `free_api.py`, `cheapest_models.py`, `Discount_github.py` | Medium |
| `openrouter_usage/` | `tasks/ai-tools/openrouter_usage/` | Python tool | `Code_for_usage.py` + usage CSVs + summary xlsx | Medium |
| `Credit_Card_Tracking/` | `tasks/ai-tools/Credit_Card_Tracking/` | Python tool | `category.py`, `visualize_expenses.py`, `expense_summary_wool.py` + monthly CSVs | Medium |
| `scraping_api/` | `tasks/ai-tools/scraping_api/` | Python tool | `scrape.py` shared web-fetch helper | Medium |
| `Image Generator Code/` | `tasks/ai-tools/Image Generator Code/` | Python tool | `image_studio.py`, `app.py` (Flux / Seedream) | Low |
| `Sketchnotes_ytube_video/` | `tasks/ai-tools/Sketchnotes_ytube_video/` | Python tool | `sketchnote_generator.py` + sample images | Low |
| `ai-studio/` | `tasks/ai-tools/ai-studio/` | Next.js app | AI Studio specs (`MASTER_BUILD_SPEC.md`, `.tsx` components) — deployed as separate container | Low |
| `my-budget-tracker/` | `tasks/ai-tools/my-budget-tracker/` | Streamlit app | Personal budget app (git submodule, not deployed) | Low |
| `.env` | `tasks/ai-tools/.env` (ro mount) | Secrets | All environment variables — stays in parent (gitignored); do NOT migrate into a tracked folder | N/A (stays outside) |
| `pre.md` | `tasks/ai-tools/pre.md` | Markdown | VPS folder-structure map (canonical reference) | Low |
| `DIRECTORY_TREE.md`, `directory_tree.txt` | `tasks/ai-tools/` | Markdown/txt | Auto-generated directory trees | Low |

### Migration notes
- When migrating `grocery_price_cli.py` into this folder, update all `sys.path`/import bootstrap logic in the CLI (it currently resolves the tracker path relative to its own location) and update the `SKILL.md` run command paths.
- When migrating `claw-skills/grocery-price/SKILL.md`, update the run command paths (currently `cd /app/tasks/ai-tools && python3 grocery_price_cli.py`).
- `.env` must remain gitignored and outside any tracked folder — do not migrate it into this folder.

---

## Secrets & Environment Variables

**All secrets live in `.env`** (parent dir, gitignored). On VPS, `/home/ubuntu/openclaw/.env` is a symlink to `/home/ubuntu/.env`, mounted read-only into the container at `/app/tasks/ai-tools/.env`.

| Env var | Used by | Purpose |
|---------|---------|---------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | `sheets_client.py` | Google Sheets service-account credentials (JSON) |
| `GROCERY_SERVICE_ACCOUNT_JSON` | `sheets_client.py` | Grocery sheet service-account credentials |
| `GROCERY_SPREADSHEET_ID` | `sheets_client.py` | Google Sheet ID (`16INuFv...`) |
| `WOOLWORTHS_COOKIE` | `woolworths_extractor.py` | Woolworths auth cookie (live list/search) |
| `WOOLWORTHS_USER` / `WOOLWORTHS_PASS` | `auth_manager.py` | Woolworths login creds |
| `COLES_COOKIE` | `session_manager.py` | Coles auth cookie |
| `COLES_USER` / `COLES_PASS` | extractors | Coles login creds |
| `COLES_LIST_URL` | `coles_extractor.py` | Coles saved-list Scrape.do URL |
| `COLES_API_KEY` | `coles_extractor.py` | Coles search headers |
| `SCRAPEDO_API_KEY` | `coles_extractor.py`, `scraping_api/scrape.py` | Scrape.do API key |
| `ZENROWS_API_KEY` | `scraping_api/scrape.py` | ZenRows API key |
| `TELEGRAM_CLAW_BOT` | openclaw.json (`channels.telegram.botToken`) | OpenClaw bot token (@ClawArkindBot) |
| `TELEGRAM_TOKEN` | telegram_gateway | Telegram gateway bot token |
| `TELEGRAM_CHAT_ID` | telegram_gateway | Telegram chat ID for direct messages |
| `OPENROUTER_API_KEY` (+ variants) | openclaw.json, tools | OpenRouter API key(s) |
| `GEMINI_API_KEY` / `GEMINI_KEY_AI_STUDIO` | tools, ai-studio | Google Gemini keys |
| `OPENCLAW_GATEWAY_TOKEN` | gateway control API | Gateway control-API auth token |
| `BYTEPLUS` | tools | BytePlus API key |
| `YOUTUBE_API_KEY` | sketchnote generator | YouTube Data API key |
| `NTFY_TOPIC` | notifications | ntfy.sh push notification topic |
| `SUPABASE_JWT_TOKEN` | ai-studio | AI Studio Supabase JWT |
| `POSTGRES_PASSWORD` | ai-studio-db | Postgres password |
| `MASTER_APP_PASSWORD` | various | Master app password |
| `JWT_SECRET` / `NEXTAUTH_SECRET` | ai-studio | Auth secrets |

> **Security:** `.env` is in `.gitignore` and `.kiloignore`. Never print, log, or echo secret values. Never commit `credentials.json`. Service-account JSON is loaded as an env var, not a file, in production.

---

## Common Workflows

### Edit → test locally → sync to VPS

```powershell
# 1. Edit code locally in this folder (e.g., core/lookup.py)
# 2. Test locally with Anaconda Python:
$env:PYTHONIOENCODING="utf-8"
& "$env:USERPROFILE\anaconda3\python.exe" ..\grocery_price_cli.py compare --items "green capsicum"

# 3. Sync changed files to VPS (scp — branches diverged, so not git pull):
scp core\lookup.py myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/core/lookup.py

# 4. Verify md5 matches:
Get-FileHash core\lookup.py -Algorithm MD5
ssh myvps 'md5sum /home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/core/lookup.py'
```

### Bulk sync (tar, excludes data/secrets/cache)

```powershell
# Build archive (excludes data/, .git/, __pycache__, credentials.json):
tar -czf "$env:TEMP\kilo\sync.tar.gz" `
  --exclude="data" `
  --exclude=".git" `
  --exclude="*__pycache__*" `
  --exclude="credentials.json" `
  .

# Upload + extract on VPS:
scp "$env:TEMP\kilo\sync.tar.gz" myvps:/tmp/sync.tar.gz
ssh myvps 'cd /home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker && tar -xzf /tmp/sync.tar.gz && rm /tmp/sync.tar.gz'
```

> **PowerShell 5.1 quoting caveat:** PowerShell mangles adjacent quotes (`""`) and nested quotes in `ssh` commands. For any multi-word CLI arg inside the container, **base64-transfer a script file** instead of inline quoting:
> ```powershell
> $b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("$env:TEMP\kilo\script.sh"))
> ssh myvps "echo $b64 | base64 -d > /home/ubuntu/openclaw/tasks/ai-tools/.tmp.sh; docker exec openclaw-core bash /app/tasks/ai-tools/.tmp.sh; rm /home/ubuntu/openclaw/tasks/ai-tools/.tmp.sh"
> ```

### Restart the container (reload skills/config)

```bash
ssh myvps 'docker restart openclaw-core; sleep 30; docker ps --format "{{.Names}} {{.Status}}"'
```

### Run the full Telegram test (3 queries)

```bash
# Via the OpenClaw agent CLI (faithful end-to-end path, delivers reply to Telegram):
ssh myvps 'docker exec openclaw-core node /app/openclaw.mjs agent --channel telegram --to 1594431983 --message "compare green capsicum in woolworths and coles" --deliver'
```

### Wednesday grocery-sync pipeline (local)

```powershell
# After pasting lists into Woolworths.docx / Coles.docx / Woolworths_Specials.docx:
& "$env:USERPROFILE\anaconda3\python.exe" ..\grocery_price_cli.py wednesday
```
Does: parse .docx → match against sheet → batch sync → scp missing lists to VPS → post summary to Telegram → post specials report.

Flags: `--dry-run` (parse+match only), `--no-scp`, `--no-telegram`.

---

## Quick Commands

```
SSH:              ssh myvps   (= ssh ubuntu@169.58.107.0)
Live AI Studio:    https://169-58-107-0.sslip.io
Telegram bot:      @ClawArkindBot  (chat 1594431983)

Container status:  ssh myvps 'docker ps'
Gateway logs:      ssh myvps 'docker logs openclaw-core --tail 50'
Gateway status:    ssh myvps 'docker exec openclaw-core node /app/openclaw.mjs status'
Skills list:       ssh myvps 'docker exec openclaw-core node /app/openclaw.mjs skills list'

Local Python:      & "$env:USERPROFILE\anaconda3\python.exe" ..\grocery_price_cli.py --help

WW team discount:  ONE-LINE switch — TEAM_DISCOUNT_ENABLED in core/woolworths_discounts.py
                   True = discounted prices (default) / False = raw prices
                   Toggle on VPS: scp core\woolworths_discounts.py myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/core/
                   (no Docker restart needed; per-call override: --no-team-discount)

AI Studio (VPS):   cd /home/ubuntu/openclaw/tasks/aistudio/ai-studio && docker compose up -d
                  Rebuild: docker compose build ai-studio-app && docker compose up -d ai-studio-app
                  Logs:    docker logs ai-studio-app
```

---

## Project Conventions

- **Python:** 4-space indent, snake_case, 88-char max line, docstrings on all functions.
- **JS/TS/JSON/YAML:** 2-space indent.
- **Error handling:** Never bare `except: pass`; fail fast; validate inputs.
- **Secrets:** `.env` only — never hardcoded, never logged, never committed.
- **Testing:** TDD where practical; test boundaries (empty, null, invalid types).
- **Dependencies:** Pinned versions; minimize third-party deps.
- **Plain-language map:** [`PROJECT-MAP.md`](PROJECT-MAP.md) documents every list, command, and scenario in simple language. **Update it in the same change whenever a list, command, flag, or flow changes.**

---

## D23–D27 + B4/B5 completion (2026-08-30)

Completion of the remaining open decisions from the architecture spec.

### D23 — compare add-reminder

`format_report` (core/price_comparator.py) now ends with the same queue
reminder `search` prints — `💬 Reply 'add item N' to queue a result for
Wednesday.` — exactly once, and only when a DISPLAYED item (top 25) shows
a live product: a live-sourced price or a found-block. Sheet-only and
empty reports are unchanged.

### D24 — Wednesday Telegram topic split

Wednesday output no longer posts to the retired `grocery-sync-sheet`
topic (thread 151 — **no code may ever post to it again**):

- summary + resolve lists → `weekly-lists` topic (resolve lists chunked
  at ≤ 4000 chars/part with `(part N/M)` suffixes; empty lists post a
  single `📋 <title>: none`);
- Woolworths specials report → `specials-wool` topic;
- user DMs keep exactly the previous content.

Topic IDs are placeholders (`None`) until manual step M1; env overrides
`TELEGRAM_WEEKLY_TOPIC_ID` / `TELEGRAM_SPECIALS_TOPIC_ID` always win
(A8). With IDs unset, sends fall back to DM-only with a console note —
nothing crashes. The new read-only `topics-check` subcommand lists the
forum topic names → thread IDs visible to the bot (M1 helper, local
machine only). The Wednesday reminder also targets `weekly-lists` with
refreshed instructions.

### D25 — sheet specials vocabulary `no` / `discount` / `multi-buy`

Sheet specials columns M/N now hold exactly one of `no` / `discount` /
`multi-buy` (classifier: `classify_special` in
extractors/specials_parser.py; precedence: `Any N | $X` / `N for $X` →
multi-buy, then `Was $X` / `Save $X` / flag → discount, else `no`).
Coles docx markers `Was $X`, `Any N | $X` (below the price) and a bare
`SPECIAL` flag line (above the name) are parsed by
extractors/doc_parser.py; a below-line marker wins over an above-line
flag, and a bare Save/Was above a product is never attached to it (A7
guard). The specials reporter treats empty/`no` as not-on-special and
still reports legacy free-text cells. All live add paths (`search --add`,
`map --add`, Telegram adds) pass the specials flag/desc through.

### D26/D27 — real discovery recording + loud status

`_LocalDriver.capture_add_to_list` (extractors/session_refresh.py)
records the REAL add-to-list API call: the request listener attaches
before the prompt; the first same-origin non-GET request mentioning a
list wins; its JSON body shape is stored (P4c). Coles additionally
resolves and verifies `lists_url` in page context — an unverified
capture fails discovery instead of saving something broken (P4d).
Discovery is now automatic on a true first run (`live-refresh` prompts
when any store lacks a capture) and `--recapture` genuinely forces
re-training (P4b). Flush is per-store isolated: a missing capture fails
only that store, with a `reason` printed. Both `live-refresh` and the
Wednesday live window print `Discovery: captured` / `Discovery: failed —
run 'live-refresh --recapture' to train` per store, plus any flush
`reason`.

### B4 — Scrape.do retries on 5xx/timeout only

The Coles Scrape.do chain retries ONLY 5xx responses and network
exceptions (fresh session, sleep 3 then 6, exactly 3 attempts). Every
4xx (404, 429, …) fails immediately after ONE attempt — stderr note,
breaker failure recorded, store marked unavailable (Woolworths-only
+ ⚠️ line path). 401/403 keep their dedicated branch.

### B5 — never browse the store sites

SKILL.md hard rule: the agent NEVER uses `web_search`/`web_fetch` (or
any browsing tool) on `woolworths.com.au` / `coles.com.au` — all price,
special, and discount questions for these stores go through the grocery
CLI. Ordinary web search stays allowed for everything else.
