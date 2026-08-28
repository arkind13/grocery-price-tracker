# Implementation Plan — Unified Telegram Message Formatting (Claw Skills)

- **Date:** 2026-08-28
- **Pipeline stage:** 02 Plan (this doc) → 03 Code → 04 Architect Checker
- **Source spec:** `grocery-price-tracker/architecture-spec.md` (status: Confirmed — all §9 decisions approved by user)
- **Status:** Ready for the coding model. Every decision below is carried from the spec; nothing behavioral is invented.
- **Baseline measured 2026-08-28:** 199 tests collected via pytest (Anaconda Python). All 199 must still pass (with the specific assertion updates listed in §5) plus the new mandatory tests.

---

## 0. Execution contexts (label EVERY command)

| Label | What it is | Who runs it |
|---|---|---|
| `[LOCAL — VS Code]` | Kilo editing files (read/write/edit/grep tools) | Coding model |
| `[LOCAL — PowerShell]` | Windows PowerShell 5.1, cwd `C:\Users\User.DESKTOP-R2G441H\Documents\AI related`. Python = Anaconda: `& "$env:USERPROFILE\anaconda3\python.exe"` (plain `python` is NOT on PATH). Always set `$env:PYTHONIOENCODING="utf-8"` first — emojis crash console output otherwise | Coding model (tests, compile checks, smoke) |
| `[LOCAL — PowerShell]` **MANUAL** | git add/commit — **the coding model NEVER runs git write commands** | User |
| `[VPS — SSH]` **MANUAL** | `ssh myvps` (alias for `ubuntu@169.58.107.0`). VPS base path: `/home/ubuntu/openclaw/tasks/ai-tools/` (bind-mounted into the container at `/app/tasks/ai-tools`). **Sync is scp/tar, NOT `git pull`** — VPS checkout (`master`) has diverged from local `main`; container reads the working tree (README §Common Workflows) | User |
| `[Telegram — DM]` **MANUAL** | User observes messages from `@ClawArkindBot` on the phone | User |

Rules carried from project workflow: one command at a time for MANUAL steps (present it, wait for pasted output, then next). `grocery-price-tracker/` is a **separate nested git repo** — its commit is separate from the main `AI related` repo.

---

## 1. Locked decisions (spec §1–§5, §9 — every one is mandatory)

1. **Display-only.** Same data, same numbers, same commands, same flags, same exit codes, same sheet writes. Only stdout/stdout-string formatting changes.
2. **Golden rule — no markdown tables.** No tool output that can reach Telegram may contain pipe tables (`| col |` header + `|---|` separator). Replacements: **list-style item blocks** and **```-fenced monospace blocks** (Telegram renders fences in a monospace font, so manual padding aligns).
3. **Zero-dependency styling.** Layout survives even if the gateway strips all markdown: unicode heavy divider `━` ×20 under main headers, light `─` ×10 for sub-blocks, `·` inline separator, CAPS header words. `**bold**` allowed on header lines only. **No `parse_mode` is added anywhere** — everything is plain text.
4. **Icon vocabulary (spec §2.3):** 🛒 grocery/basket · 🔍 search · 🏷️ specials/discounts · 💰 money/savings · 🏆 cheapest · 🏠 WW home brand · ⚠️ warning · ✅ success · ❌ unavailable · 🟢 Woolworths · 🔴 Coles · 📊 totals/report · 🧾 recipe · 🔄 sync · 🤖 LLM pricing · 📅 daily digest · ⏱️ timestamp footer.
5. **Moderate emoji density:** headers + store lines only, not every line.
6. **Message skeleton (all skills):** `<ICON> <TITLE IN CAPS>` → `━━━━━━━━━━━━━━━━━━━━` → body (list items and/or fenced block) → tail (🏆 / ⚠️) → optional `⏱️` footer.
7. **Width budgets:** `MAX_NAME_WIDTH = 24`, `MAX_BLOCK_WIDTH = 34` (fenced blocks, phone-fit). Longer names truncate with `…`.
8. **Store icon lines:** 🟢 Woolworths / 🔴 Coles (user-approved §9).
9. **`format_discounted_price()` is NOT changed** — keeps the `(was $x)` bracket form (`$4.51 (Home 9.75% off, was $5.00)` / `$4.75 (5% off, was $5.00)`); tests asserting it stay green.
10. **`telegram_gateway/wednesday_reminder.py` must NOT import the kit.** It is intentionally self-contained for the VPS sparse checkout (see its docstring). Restyle `REMINDER_TEXT` with the kit's unicode vocabulary as a hardcoded string.

---

## 2. Work order — sequential phases

Execute in order. Each phase ends with its verification command before moving on.

### Phase 1 — `core/telegram_format.py` (NEW) + `tests/test_telegram_format.py` (NEW)

`[LOCAL — VS Code]` Create `grocery-price-tracker/core/telegram_format.py`. Stdlib-only (`unicodedata` allowed for width math; no new deps in `requirements.txt`). Module docstring documents the skeleton + icon table (spec §2.3–§2.4).

**Public API (exact signatures — spec §3):**

```python
MAX_NAME_WIDTH = 24    # product-name column budget
MAX_BLOCK_WIDTH = 34   # fenced-table visible width budget

def header(title: str, icon: str) -> str
    # "🛒 BASKET COMPARISON\n" + "━" * 20   (title uppercased by the function)

def subheader(title: str, icon: str | None = None) -> str
    # light divider block: "─" * 10 label line (icon optional)

def divider(char: str = "─", width: int = 10) -> str

def fenced_table(headers: list[str], rows: list[list[str]],
                 box: bool = False) -> str
    # Triple-backtick fence. Columns padded with spaces so EVERY content
    # line has identical character length. box=True draws ╔═╗/║/╚╝ borders
    # (used by the compare TOTALS block, spec §5.1). Left-align text
    # columns, right-align money columns. Truncate over-wide cells with …;
    # total visible width ≤ MAX_BLOCK_WIDTH. Empty rows list → fence with
    # just headers; empty headers → ValueError (fail fast).

def item_block(index: int, name: str, prices: list[str],
               home_brand: bool = False) -> str
    # "2. Full Cream Milk 2L  🏠" + indented store lines (prices are
    # pre-rendered store_line() strings). Name truncated to
    # MAX_NAME_WIDTH. home_brand appends "  🏠".

def store_line(store: str, price: str, was: str | None = None) -> str
    # "🟢 Woolworths  $2.47 (was $2.90)" / "🔴 Coles       $3.50".
    # Store label padded so the price column aligns across stores
    # (emoji counted as 2 cells). store accepts "woolworths"/"coles"
    # (case-insensitive); unknown store → no icon, label as-given.

def kv(label: str, value: str) -> str          # "label · value"

def money(n) -> str
    # 4.0 → "$4.00" · 0 → "$0.00" · None → "—" · negative → "−$x.xx"
    # (U+2212 minus, matching spec §5.1 "−$1.65")

def warn(text: str) -> str    # "⚠️ {text}"
def ok(text: str) -> str      # "✅ {text}"
def fail(text: str) -> str    # "❌ {text}"

def tail(winner: str, savings: float, vs: str | None = None) -> str
    # "🏆 Cheapest: Woolworths — you save $2.35" (+ " (vs Coles)" when vs)

def footer(ts=None) -> str    # "⏱️ 2026-08-28 14:05" (ts defaults to now)

def truncate(s: str, width: int) -> str       # "…"-ellipsis, never > width
```

Design notes for the coding model:
- All width math treats emoji as 2 cells (document a `_cells()` helper; tests may reuse it).
- No function may emit `"|---"` or a pipe-table header — enforced by tests (§5).

**`[LOCAL — VS Code]`** Then write `grocery-price-tracker/tests/test_telegram_format.py` (unittest style matching the existing suite) covering every function per the mandatory test matrix in §5.1. TDD: write tests first or together — either way both land in the same commit unit.

**Verify (Phase 1):**
```powershell
[LOCAL — PowerShell]  cwd: grocery-price-tracker
$env:PYTHONIOENCODING="utf-8"; & "$env:USERPROFILE\anaconda3\python.exe" -m pytest tests/test_telegram_format.py -q
```
Expected: all new tests pass, 0 errors.

### Phase 2 — Core formatter swaps (grocery tracker)

**2a. `core/price_comparator.py` — `format_report()` (lines 497–620).**
Signature and `ComparisonReport` unchanged. New output exactly per spec §5.1:

```
🛒 BASKET COMPARISON
━━━━━━━━━━━━━━━━━━━━

1. Green Capsicum
   🟢 Woolworths  $2.47 (was $2.90)
   🔴 Coles       $3.50

2. Full Cream Milk 2L  🏠
   🟢 Woolworths  $3.32 (was $3.68)
   🔴 Coles       $3.40

📊 TOTALS
```
followed by the fenced box table (`fenced_table(..., box=True)`; columns Store / Raw / Final; `—` when a store has no price), then:

```
🏆 Cheapest: Woolworths — you save $2.35
🏷️ WW discounts: −$1.65 (5% all + 🏠 home extra)
⚠️ 1 item missing at Coles
```

Rules carried from spec §5.1: top-25 cap unchanged, overflow renders `… +N more items`; the discounts sub-block (from `format_discount_report`) lists ONLY home-brand and extra-discount lines — base 5% is summarised in the 🏷️ tail line (compose the tail from `report.team_discount_savings + report.home_extra_savings + report.extra_discount_savings`); empty basket keeps a friendly "No items provided." line under the header; warnings become `warn()` lines; existing `**Cheapest store:**`/`**Max savings:**` markdown lines are replaced by `tail()`. Keep the two `from core.woolworths_discounts import …` local imports as-is (no import cycles; `telegram_format` imports nothing from siblings).

**2b. `core/woolworths_discounts.py` — `format_discount_report()` (lines 409–495).**
Signature unchanged. New output:
- `🏷️ HOME BRAND EXTRA` subheader; per home-brand item a `was/now` line (`name · $3.80 → $3.61` using `kv`-style or `→` arrow); total line `💰 Home extra: $0.19`.
- Extra discount line when applicable: `🏷️ Extra 10% · save $0.36`; the "not applied (already used this month)" branch keeps its meaning via `warn()`.
- Base 5%: NO per-item lines (dropped — that is the compaction); a single summary line `🏷️ 5% off all WW items · save $X` is emitted ONLY when the function is called standalone (i.e., when not being embedded — add keyword-only param `compact: bool = False`; `format_report` passes `compact=True` so the base line is omitted there because its tail already summarises it). When nothing applied: `No discounts applied.` (unchanged text, no pipe tables).
- `format_discounted_price()` and `discounted_woolworths_price()` untouched (spec §4.1).

**2c. `core/specials_reporter.py` — `format_specials_report()` (lines 217–265) + `__main__` rewards block (lines 289–296).**
New output per spec §5.3:
```
🏷️ SPECIALS — WOOLWORTHS
━━━━━━━━━━━━━━━━━━━━
1. Coke 24-pack
   $19.00  (was $24.50 · save $5.50)
…
📊 12 active specials
```
Item price strings still come from `format_discounted_price()` for WW rows (keeps `(5% off, was $x)` / `(Home 9.75% off, was $x)` — spec §9-approved bracket form) and raw `$x.xx` for Coles; `special_desc` rides along via `·` separators. Top-25 cap + `… +N more specials` line. The `__main__` rewards block becomes `✅ name · rewards` lines under a `💰 BONUS REWARDS` subheader with a count line.

**Verify (Phase 2):**
```powershell
[LOCAL — PowerShell]  cwd: grocery-price-tracker
$env:PYTHONIOENCODING="utf-8"; & "$env:USERPROFILE\anaconda3\python.exe" -m pytest tests -q
```
Expected: failures ONLY in the three test spots listed in §5.2 (update them in Phase 2, not later) — then full green.

### Phase 3 — `grocery_price_cli.py` (prints only — zero flag/arg changes)

`[LOCAL — VS Code]` Add near the existing bootstrap (after line 17):
```python
from core.telegram_format import (header, subheader, fenced_table,
    item_block, store_line, kv, money, warn, ok, fail, tail, truncate)
```
Restyle every stdout surface that currently prints pipe tables or bare markdown (line numbers are current; re-grep before editing):

| Function | Lines (approx) | New form |
|---|---|---|
| `_cmd_unmapped` | 170–182 | 📋 header + list-style rows (name/category per line), `… +N more items` |
| `_cmd_analyze` | 212–272 | 📊 header + fenced category-count table + list-style product rows |
| `_cmd_rewards` | 306–329 | 💰 header + `name · rewards · price` list lines, WW prices via `format_discounted_price` (unchanged logic) |
| `_cmd_recipe` | 407 | `🧾 RECIPE — <NAME>` header + divider, then the compare report |
| `_cmd_search` | 441–488 | spec §5.2: `🔍 <PRODUCT> — LIVE PRICES` header; numbered items `name` + `🟢 Woolworths  $x  🏷️ was $y` / `🔴 Coles  $x`; `🏆 Cheapest: …` tail; `❌ No results found` empty case |
| `_cmd_specials` (saved-list block) | 515–524 | 🏷️ subheader + list lines (no pipe table) |
| `_cmd_sync` | 532–607 | 🔄 header + ✅/❌ per-store status lines + 📊 fenced counts block + 📋 unmatched summary (spec §5.5) |
| `_cmd_specials_scan` | 615–708 | 🏷️ header + list-style discount rows (regular/sale/save%/store per line) |
| `_cmd_wednesday` | 887–940 | 📅 header + status lines; embedded `format_specials_report`/`format_report` text now arrives pre-styled from Phase 2 — relay, do not re-wrap |
| `_cmd_map` / `_cmd_map_noninteractive` | 1661–2140 | numbered candidates list-style (name + score per line); the SKILL.md action-prompt line is prefixed `✳️` and otherwise UNCHANGED; ✅ confirmations for pick/add/skip/na/forget |
| `_cmd_backfill_keywords` | 2179–2189 | 📋 header + list lines (row · product · existing → proposed) |
| `_cmd_backfill_home_brands` | 2282–2293 | 📋 header + list lines; `[DRY RUN]` marker preserved as a `warn()` line |

Hard constraints: no subcommand names/flags/exit-code changes; `EM_DASH`/`WARN`/`ARROW` module constants may stay (still used); every removed `|---` string must be gone from the file afterwards (verify with grep, §6).

**Verify (Phase 3):**
```powershell
[LOCAL — PowerShell]  cwd: grocery-price-tracker
$env:PYTHONIOENCODING="utf-8"; & "$env:USERPROFILE\anaconda3\python.exe" -m pytest tests -q
& "$env:USERPROFILE\anaconda3\python.exe" -m py_compile ..\grocery_price_cli.py
```

### Phase 4 — Gateway scripts (output strings only)

**4a. `telegram_gateway/wednesday_reminder.py`** — replace only `REMINDER_TEXT` (lines 68–76): `📅 WEDNESDAY GROCERY SYNC` + `━` divider + short numbered steps (copy lists → save docs → run the command) + closing line. Plain text, NO markdown, NO kit import (self-containment for the sparse VPS checkout — locked decision #10). `send_message()` stays plain (no `parse_mode`).

**4b. `telegram_gateway/budget_sheets.py`** — restyle stdout strings only: `summary` → `💰 BUDGET SUMMARY` + `━` divider + `kv`-style lines (keep the aligned values); `woolies` → `💰 WOOLIES PAY SUMMARY` same shape; `update` confirm `OK: field = value` → `✅ field · value`. Since this script is also deployed beyond the tracker folder, hardcode the small vocabulary (header line + divider + `·`) rather than importing the kit — 5 lines, zero coupling. The `__doc__` usage prints (lines 244–249) stay as-is.

**Verify (Phase 4):**
```powershell
[LOCAL — PowerShell]  cwd: AI related
& "$env:USERPROFILE\anaconda3\python.exe" -m py_compile telegram_gateway\wednesday_reminder.py telegram_gateway\budget_sheets.py
```

### Phase 5 — Sibling claw tools (stdout formatting only)

Pattern for each: add the 3-line bootstrap (file-relative, mirrors `grocery_price_cli.py` lines 14–17):
```python
from pathlib import Path
_TRACKER = Path(__file__).resolve().parent.parent / "grocery-price-tracker"
if str(_TRACKER) not in sys.path:
    sys.path.insert(0, str(_TRACKER))
```
Works locally (`AI related/`) and on the VPS (`/app/tasks/ai-tools/`) because the tracker folder is a sibling in both layouts.

| Tool file | New stdout form |
|---|---|
| `openrouter model costs/claude_pricing.py` | 🤖 CLAUDE PRICING header + fenced table (Model ≤24 chars / In $/M / Out $/M). Keep `MAX_ROWS`, sort order, and the `.txt` file write as-is — restyle ONLY the stdout block (lines 66–70) |
| `openrouter model costs/gpt_pricing.py` | same pattern |
| `openrouter model costs/Openroutervideo.py` | same (video models) |
| `openrouter model costs/Discount_github.py` | 🏷️ list-style discount rows |
| `openrouter model costs/free_api.py` | 🤖 list-style free-model rows |
| `openrouter_usage/Code_for_usage.py` | 📊 header + fenced usage table |
| `daily-models-digest/daily_digest.py` | 📅 digest cards (per-model sub-blocks, kit skeleton) |
| `Credit_Card_Tracking/category.py` | 💰 category lines (kv style) |

web-scrape / sketchnote / image-studio: no tabular stdout → no code changes (spec §4.2 "light touch" applies only if they print prose summaries — verified: they do not print tables; leave them).

**Verify (Phase 5):**
```powershell
[LOCAL — PowerShell]  cwd: AI related
& "$env:USERPROFILE\anaconda3\python.exe" -m py_compile "openrouter model costs\claude_pricing.py" "openrouter model costs\gpt_pricing.py" "openrouter model costs\Openroutervideo.py" "openrouter model costs\Discount_github.py" "openrouter model costs\free_api.py" openrouter_usage\Code_for_usage.py daily-models-digest\daily_digest.py Credit_Card_Tracking\category.py
```
(Network runs are NOT required for these — API-key live checks are best-effort and never block the phase.)

### Phase 6 — SKILL.md relay rules (all `claw-skills/*/SKILL.md`)

Replace every instruction of the form *"return the Markdown table the script prints"* with the spec §4.4 block:

> The CLI output is **already Telegram-formatted**. Relay it **verbatim**. Never re-wrap it in your own tables, never reformat, never add markdown tables of your own.

- `claw-skills/grocery-price/SKILL.md` is the critical edit: line 66 ("Run the command and return the Markdown table the script prints") and the §Output section (line 142: "Markdown tables to stdout (top-25 cap). Return the table in chat.") both get the relay rule.
- The other skills (budget-sheets, claude-pricing, daily-digest, discounts, expenses-summary, expenses-view, free-models, gpt-pricing, image-studio, openrouter-usage, sheet-analyst, sketchnote, video-pricing, web-scrape) get the same rule wherever they describe output. SKILL.md internal *documentation* tables (subcommand reference, env tables — e.g. grocery-price lines 31–44, 128–137) are read by the agent, not relayed to Telegram — leave them.
- No run-command, env, or routing changes.

### Phase 7 — README

`grocery-price-tracker/README.md`: the §"Telegram message formatting (all skills)" section (line 435) already announces the kit — update it to match the shipped API (one usage example of `header`/`fenced_table`), and make sure the archived-spec reference (`architecture-spec-woolworths-discounts.md`, referenced at line 352) resolves: if the file is absent, fix the reference to point to the current `architecture-spec.md` history note (do not fabricate archive content). No other README sections.

### Phase 8 — Full local verification (MANDATORY — no step may be skipped)

```powershell
[LOCAL — PowerShell]  cwd: grocery-price-tracker
# 8.1 Full suite (199 existing, updated where §5.2 says so, + new file):
$env:PYTHONIOENCODING="utf-8"; & "$env:USERPROFILE\anaconda3\python.exe" -m pytest tests -q
# Expected: ALL PASS, 0 failed, 0 errors. Skips allowed only where already skipped pre-change (compare skip counts to baseline).

# 8.2 Pipe-table ban grep (source):
# (use the Grep tool, pattern: `\|---|\| # \|`, include *.py over the whole AI related workspace)
# Expected: ZERO matches in any code path that prints to stdout.
# (SKILL.md documentation tables are excluded — restrict include to *.py.)

# 8.3 Smoke (needs .env + network; 10–30 s each, documented workflow):
$env:PYTHONIOENCODING="utf-8"; & "$env:USERPROFILE\anaconda3\python.exe" ..\grocery_price_cli.py compare --items "green capsicum"
$env:PYTHONIOENCODING="utf-8"; & "$env:USERPROFILE\anaconda3\python.exe" ..\grocery_price_cli.py specials
$env:PYTHONIOENCODING="utf-8"; & "$env:USERPROFILE\anaconda3\python.exe" ..\grocery_price_cli.py search --product "green capsicum"
# Eyeball: header+divider, item blocks with 🟢/🔴 lines, fenced totals aligned, 🏆 tail. No pipes anywhere.
```

### Phase 9 — MANUAL deployment & faithful Telegram test (User)

Present these one at a time:

1. **[LOCAL — PowerShell] MANUAL — commit nested repo** (`grocery-price-tracker/`): stage `core/telegram_format.py`, `core/price_comparator.py`, `core/woolworths_discounts.py`, `core/specials_reporter.py`, `tests/test_telegram_format.py`, updated test files, `README.md`, `implementation-plan.md`. Suggested message: `Add Telegram Style Kit; replace markdown tables with list + fenced blocks (display-only)`.
2. **[LOCAL — PowerShell] MANUAL — commit main repo** (`AI related/`): stage `grocery_price_cli.py`, `telegram_gateway/wednesday_reminder.py`, `telegram_gateway/budget_sheets.py`, the Phase-5 tool files, `claw-skills/*/SKILL.md`. Same message style. (Reminder: review `git diff --staged` for secrets first — standard rule.)
3. **[LOCAL — PowerShell] MANUAL — push both repos to GitHub** (backup; NOT the VPS deploy path): `git push origin main` in each repo. If push is rejected (remote ahead), stop and surface the divergence — do not force-push.
4. **[LOCAL — PowerShell] MANUAL — sync to VPS (scp/tar — NEVER `git pull`/`git clone` on the VPS: its `master` checkout has diverged and the container bind-mounts the working tree, README lines 550–551, 570–571).**
   - Tracker folder — documented tar bulk sync (excludes data/secrets/cache):
     ```powershell
     tar -czf "$env:TEMP\kilo\sync.tar.gz" --exclude="data" --exclude=".git" --exclude="*__pycache__*" --exclude="credentials.json" .
     scp "$env:TEMP\kilo\sync.tar.gz" myvps:/tmp/sync.tar.gz
     ssh myvps 'cd /home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker && tar -xzf /tmp/sync.tar.gz && rm /tmp/sync.tar.gz'
     ```
     (run the tar from inside `grocery-price-tracker/`)
   - Parent-level files (live at `ai-tools/` root on the VPS) — one scp per file:
     `grocery_price_cli.py`, `telegram_gateway/wednesday_reminder.py`, `telegram_gateway/budget_sheets.py`, `openrouter model costs/*.py` (5 files), `openrouter_usage/Code_for_usage.py`, `daily-models-digest/daily_digest.py`, `Credit_Card_Tracking/category.py`, every touched `claw-skills/*/SKILL.md` → `myvps:/home/ubuntu/openclaw/tasks/ai-tools/<same relative path>`
   - Reminder cron copy (outside the repo checkout):
     `scp telegram_gateway\wednesday_reminder.py myvps:/home/ubuntu/scripts/wednesday_reminder.py`
   - Verify at least the kit landed intact (documented md5 check):
     ```powershell
     Get-FileHash core\telegram_format.py -Algorithm MD5
     ssh myvps 'md5sum /home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/core/telegram_format.py'
     ```
5. **[VPS — SSH] MANUAL — restart container (REQUIRED this deploy):** SKILL.md instructions are read at agent startup, so the 14+ changed SKILL.md files need a restart (Python files alone would not). Documented form:
   ```bash
   ssh myvps 'docker restart openclaw-core; sleep 30; docker ps --format "{{.Names}} {{.Status}}"'
   ```
   Confirm the container reports `Up` before continuing.
6. **[VPS — container] MANUAL — faithful Telegram test** (spec §7.5; PowerShell 5.1 mangles nested quotes — use the ssh single-quote wrapper form):
   ```bash
   ssh myvps 'docker exec openclaw-core node /app/openclaw.mjs agent --channel telegram --to 1594431983 --message "compare green capsicum in woolworths and coles" --deliver'
   ```
   **[Telegram — DM] MANUAL** — confirm on the phone: item blocks aligned, totals box monospace-aligned, 🏆 tail present, no raw pipes, layout survives any gateway markdown-stripping. Optionally repeat with a `specials` query.
7. **Optional MANUAL — reminder test:** `ssh myvps 'python3 /home/ubuntu/scripts/wednesday_reminder.py --test'` (sends a real DM + topic post; state file is NOT advanced by `--test`). Otherwise the next Wednesday 05:00 Sydney cron exercises it.

---

## 3. Format contracts (canonical examples — coding model must match shapes)

Compare/recipe totals box (fenced, `box=True` — every line the same character length; store column left-aligned, money right-aligned):

```
📊 TOTALS
```
╔══════════════════════════╗
║ Store        Raw    Final ║
║ Woolworths  $23.40  $21.75║
║ Coles       $24.10  $24.10║
╚══════════════════════════╝
```
🏆 Cheapest: Woolworths — you save $2.35
🏷️ WW discounts: −$1.65 (5% all + 🏠 home extra)
⚠️ 1 item missing at Coles
```

(The fenced_table implementation must produce internally consistent padding — the spec's illustrative example has a typo in row 3; equal-length lines are the contract, enforced by tests.)

Search (spec §5.2):
```
🔍 GREEN CAPSICUM — LIVE PRICES
━━━━━━━━━━━━━━━━━━━━
1. Green Capsicum 500g
   🟢 Woolworths  $2.90  🏷️ was $3.50
2. …
```

Sync / Wednesday summary (spec §5.5): ✅/❌ per-store status lines, 📊 fenced counts block, 📋 unmatched summary.

Pricing tools (spec §5.6): 🤖 header + fenced table (name ≤ 24 chars truncated).

---

## 4. Prohibitions (spec §6 — the 04 Checker enforces these)

Must NOT modify: sheet schema/writes, discount math (`discounted_woolworths_price` et al.), lookup/sync logic, extractor APIs, `.env` handling, `openclaw.json`, any CLI subcommand names/flags/exit codes, any data file, `telegram_gateway/handlers.py` (not in the authorized list — the map-session replies it builds are out of scope this round).

---

## 5. Test plan (ALL mandatory — the coding model may NOT skip, weaken, or mark any of these skipped)

### 5.1 New `tests/test_telegram_format.py` — required matrix

| # | Test | Asserts |
|---|---|---|
| 1 | `test_header_caps_and_divider` | icon + UPPERCASED title + `━`×20 second line |
| 2 | `test_subheader_light_divider` | `─`×10 line, optional icon |
| 3 | `test_fenced_table_all_rows_equal_width` | strip fences → every line identical `len()` |
| 4 | `test_fenced_table_respects_width_budget` | max visible width ≤ `MAX_BLOCK_WIDTH` with long cells |
| 5 | `test_fenced_table_truncates_with_ellipsis` | over-wide cell ends in `…`, never exceeds budget |
| 6 | `test_fenced_table_box_borders` | `box=True` → first/last border lines `╔═…╗` / `╚═…╝` |
| 7 | `test_fenced_table_empty_rows` | headers-only renders; `headers=[]` raises `ValueError` |
| 8 | `test_money_formats` | `0→"$0.00"`, `None→"—"`, `4→"$4.00"`, `-1.5→"−$1.50"` |
| 9 | `test_truncate_short_unchanged` / `..._long_ellipsized` | `len` never exceeds width; `…` appended |
| 10 | `test_store_line_alignment` | Woolworths/Coles lines: price starts at the same cell offset (padding correct with 2-cell emoji) |
| 11 | `test_store_line_was_price` | `(was $2.90)` suffix present when `was` given |
| 12 | `test_item_block_home_brand_marker` | `🏠` appended when `home_brand=True`; name truncated at `MAX_NAME_WIDTH` |
| 13 | `test_kv_separator` | single `·` between label and value |
| 14 | `test_warn_ok_fail_icons` | ⚠️ / ✅ / ❌ prefixes |
| 15 | `test_tail_line` | 🏆 + winner + savings; `(vs X)` when `vs` given |
| 16 | `test_footer_timestamp` | ⏱️ prefix; deterministic when `ts` passed |
| 17 | `test_no_pipe_tables_ever` | for a representative composite message built from every function: `"|---"` not in output and `"| # |"` not in output |

### 5.2 Regression updates (assert content, not byte-equality)

| File : line (current) | Change |
|---|---|
| `tests/test_comparator.py` :: `test_format_report_contains_discount_lines` (519–563) | Keep asserting `3.61`, `4.00`, home-extra total `0.19`; replace `"5% off all"` → the 🏷️ tail summary (assert `"5%"` and `"0.20"`); replace `"Home Brand Extra"` → `🏠` home sub-block heading; replace `"Extra Discount"` → `🏷️` extra line; add: cheapest-store 🏆 line present; add pipe-ban asserts on the whole output |
| `tests/test_comparator.py` :: specials tests (462–484) | assertions are content-based (`"2.85"`, `"5% off"`, `"Home 9.75% off"`) and survive because `format_discounted_price` is unchanged — verify, and only loosen if the `·`-joined line ordering breaks an assert |
| `tests/test_woolworths_discounts.py` :: `TestFormatDiscountReport` (295–330) | update to new sub-block output: base summary line total, home `was → now` line, `No discounts applied.` case stays |
| `tests/test_cli.py:795` | `assertIn("| $5.00 |")` → assert Coles raw `$5.00` present AND `"| $5.00 |"` absent (pipe ban) |
| `tests/test_cli.py:853–859` | backfill dry-run pipe-row asserts → new list-line content asserts (row number + product + proposed `Home`); keep the `assertNotIn` skip checks (adapted to new row prefixes) |
| `tests/test_cli.py:527, 701` | these mock `format_report` — no change expected; verify only |

### 5.3 New invariant tests (add to `tests/test_telegram_format.py`)

Parametrize over the real formatters: build a small fixture report/specials/discount-items set and assert `format_report`, `format_specials_report`, `format_discount_report` outputs contain neither `"|---"` nor `"| # |"`, and (for compare) that the fenced TOTALS block lines are all equal length.

### 5.4 Suite-level gates

- Baseline before any edit: run the suite once, record pass/skip counts (expected ≈199 collected, all passing).
- After Phase 8.1: same or better. **A skip introduced to dodge a formatting failure is a defect**, not a pass. If a smoke command (8.3) cannot run for environment reasons (no network), report it explicitly in the final summary — never silently omit.

---

## 6. Final self-check for the coding model (before handing to 04 Checker)

1. `grep` the workspace for `\|---|\| # \|` in `*.py` → zero hits in stdout paths.
2. `grep` for `parse_mode` → no new occurrences added anywhere.
3. Diff review: no changes outside the §"May modify" list (spec §6); no flag/arg/exit-code diffs in any CLI; `handlers.py` untouched; sheet-write logic untouched; `format_discounted_price` byte-identical.
4. Full suite green (§5.4); new test file present and passing.
5. Every MANUAL step in Phase 9 listed for the user with exact commands; nothing git/docker executed by the coding model.
