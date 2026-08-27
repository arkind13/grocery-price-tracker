# Test Log — Always-On Woolworths Display Discounts + Home-Brand Classification

- **Date:** 2026-08-27
- **Plan:** `grocery-price-tracker/implementation-plan.md` (Stages 0–9)
- **Commits:** tracker repo `a9215d8` (main) · main repo `db40415` (main)
- **Deploy target:** VPS 169.58.107.0 → `/home/ubuntu/openclaw/tasks/ai-tools` (live mount of `openclaw-core`)

## Automated results

| # | Check | Command / scope | Result |
|---|-------|-----------------|--------|
| T1 | Baseline suite (Stage 0, pre-edit) | `pytest tests -q` | **8 failed / 158 passed** — all 8 pre-existing in `tests/test_extractors.py` (out-of-scope, spec-locked files). Gate adjusted to "no NEW failures". |
| T2 | New module tests red-first (TDD, Stage 1a) | `pytest tests/test_woolworths_discounts.py -q` | 16 failed / 8 passed — expected before module rewrite |
| T3 | New module tests green (Stage 1c) | same file after rewrite | **24 passed** ✅ |
| T4 | Comparator + discounts gate (Stage 2/§6.2) | `pytest tests/test_comparator.py tests/test_woolworths_discounts.py` | First run 1 failure — plan's own arithmetic slip ($3.61+$4.75=7.36 → corrected to **8.36**); re-run **49 passed** ✅ |
| T5 | Sheets-sync gate incl. new Home-literal tests (Stage 4) | `pytest tests/test_sheets_sync.py -q` | **29 passed** ✅ |
| T6 | CLI + lookup suites (Stage 5/§6.4) | `pytest tests/test_cli.py tests/test_lookup.py -q` | 1 test-side assertion bug fixed (gspread `values=[["Home"]]` shape); final full-suite run below |
| T7 | FULL suite gate (Stage 7 / V7 adjusted) | `pytest tests -q` | **191 passed / 0 errors / exactly the 8 known extractors failures — zero new failures** ✅ |
| T8 | py_compile all touched files | `py_compile …cli woolworths_discounts price_comparator specials_reporter sheets_sync lookup` | exit 0 ✅ |
| T9 | Secrets scan pre-commit | diff scan (`ai_user/_abck/wow-auth/dtCookie/private keys`) + repo pre-commit hook | CLEAN / Passed ✅ |

## Math spot-checks (spec §5 compounding)

| Input | Expected | Actual |
|-------|----------|--------|
| `$5.00` home brand | $4.51 | $4.51 ✅ |
| `$5.00` regular | $4.75 | $4.75 ✅ |
| `$8.00` home brand | $7.22 | $7.22 ✅ |
| `$4.00` home brand | $3.61 | $3.61 ✅ |
| Per-item rounded sum (4.51+7.22+3.80) | 15.53 | 15.53 ✅ |

## Deployment verification (VPS)

| # | Check | Result |
|---|-------|--------|
| D1 | scp of `grocery_price_cli.py`, 5 nested core modules, 1 test file, SKILL.md | All uploaded (1 retry via `/tmp`+sudo for root-owned `tests/`) ✅ |
| D2 | SHA256 host ↔ VPS for all 6 runtime files | Identical ✅ |
| D3 | Container restart `openclaw-core` | Up (healthy) ✅ |
| D4 | In-container smoke: `format_discounted_price(5.00, home)` | `$4.51 (Home 9.75% off, was $5.00)` ✅ |
| D5 | In-container parser: `backfill-home-brands --dry-run` against LIVE sheet | Runs read-only: 82 rows, **2 planned writes**, 26 already `Home`, 40 safely skipped ✅ |
| D6 | Cron interference incident | VPS crontab runs `git pull --autostash` every 5 min on ai-tools clone; raw-scp copies of git-tracked files were reverted mid-deploy by a failing pull (root-owned/read-only `claw-skills/grocery-price`). **Fixed**: perms repaired, clone hard-reset onto `origin/main` (=`db40415`), stash clutter cleared, all hashes re-verified post-reset, container restarted clean ✅ |

## Final state (post-repair, re-verified)

```
VPS container : openclaw-core Up (healthy)
clone HEAD    : db40415 feat(grocery): display-time WW discounts …
cli hash      : d6e7a0ef…  == local working copy
core/*.py ×5  : 49c2d97c / 78254528 / 8539628f / a8aea64c / 53d19184  == local
backfill dry-run planned writes:
  Row 48 | Hillview Cheese Slice      | Hillview   -> Home
  Row 83 | Woolworths Beef Mince 500g | Woolworths -> Home
```

## Pending MANUAL items (user, per plan §9) — ✅ COMPLETED by user 2026-08-27

1. **Telegram DM to @ClawArkindBot:** *"Compare prices for milk between Woolworths and Coles"* — **PASS** (user-confirmed; WW discounted + raw Coles as expected).
2. **Backfill live run** — **PASS** (user-executed `python3 grocery_price_cli.py backfill-home-brands` inside container; sheet Col G corrected).

Both final verification-matrix items (V13, V14) now closed. Definition of done reached.

## Known non-blocking issues

- `tests/test_extractors.py`: 8 failures pre-date this task (`_parse_api_item` missing from `woolworths_extractor`; Coles `_parse_search_result` signature drift; a cookie-loaded SessionManager header case). Files are spec-locked (`extractors/**`) so they were NOT touched here — needs a separate dedicated fix session.
- Tracker repo carries unrelated uncommitted WIP from a prior session (README body, `tests/test_name_matcher.py`, data/*.txt, docx/xlsx binaries, `tests/test_live_search.py`, `architecture-spec.md`). Untouched by design.
