# Implementation Plan — Finish Line: D23–D27 + B4/B5 Completion

- **Date:** 2026-08-30
- **Pipeline stage:** 02 Plan (this doc) → 03 Code → 04 Architect Checker
- **Source spec:** `grocery-price-tracker/architecture-spec.md` (CONFIRMED by
  user 2026-08-29/30). Every decision below is carried from the spec §3/§4.
  Do not re-litigate binding decisions D23–D27, B4/B5, A1–A8, or the REJECTED
  umbrella command (§1). 03 Code executes this plan literally.
- **Baseline:** full suite **446 passed / 0 failed** (2026-08-29 repair,
  verified by 01 Architect §9). Regression bar for this project: full suite
  green, 0 failed, count ≥ 446 + new tests. No carve-outs.
- **Python:** Anaconda interpreter only. `python` is NOT on PATH — always:
  `& "$env:USERPROFILE\anaconda3\python.exe"` (PowerShell). **Never `pip install`**
  (no new dependencies; stdlib + existing only).
- **Working directory for ALL commands:** `C:\Users\User.DESKTOP-R2G441H\Documents\AI related`
  (the workspace root; referred to below as `<ROOT>`). pytest resolves the
  tracker package because the test files bootstrap `sys.path` themselves.
- **Repos:** `grocery-price-tracker/` is its own git repo; `grocery_price_cli.py`,
  `telegram_gateway/`, `claw-skills/`, `Development Workflow/` are siblings in
  `<ROOT>` (mirroring the VPS `tasks/ai-tools/` layout).
- **Build order (fixed):** WP1 → WP2 → WP3 → WP4 → WP5 → docs → deploy.
  WP5 ships with placeholder `None` constants + env overrides; the constant
  fill is gated on manual step M1 (§8).

---

## 0. Plan-level resolutions (where the spec was silent; binding for 03 Code)

| # | Question | Resolution |
|---|----------|------------|
| P1a | D23 condition scope | Reminder computed over the **displayed** items only (`report.items[:25]`, A2 "ANY displayed item"), checking `"live" in item.sources.values()` OR non-empty `item.closest`. |
| P1b | Reminder formatting | Mirrors `search`: one blank line, then the verbatim reminder as the final line of the report. |
| P2a | 4xx breaker semantics | The new 4xx no-retry branch mirrors the existing 401/403 branch exactly: stderr note + `_breaker_record_failure()` + `return [], "unavailable"` (a 4xx chain is a failed chain; consistent with the breaker's "consecutive failed chains" definition). |
| P3a | `update_single_price` optional specials | `is_special: Optional[bool] = None` — `None` = caller provided nothing → specials cell untouched (existing callers unaffected); `True`/`False` → write `classify_special(...)` and widen `target_width` past M/N. (`add_product_row` uses `is_special: bool = False` per the spec and ALWAYS writes one of the three values on a new row.) |
| P3b | Below-line vs above-line tie | When both a below-line marker (`Was`/`Any`/`Save`/`For`) and an above-line bare `SPECIAL` exist, the **below-line desc wins** (richer data); the above-line flag applies only when nothing was found below. |
| P3c | Coles `promotionType` classification | Actual value produced today is `promotion_type.replace("_", " ").title()` → e.g. `"Multi Buy"` (coles_extractor.py:427-429). It matches none of the D25 desc patterns → classifies `"discount"` (spec §4 WP3 test line sanctions "else discount"). Recorded; no extra pattern invented. |
| P4a | Prompt ownership | The "Add ONE item…" prompt moves from `_run_discovery` INTO `_LocalDriver.capture_add_to_list` (listener attached BEFORE the print so no request is missed). Wording unchanged. Fake drivers replace the whole method, so no double print. |
| P4b | `--recapture` force | `_run_discovery(driver, summary, force=recapture)` — `force=True` bypasses the `_needs_capture` skip (today `--recapture` is a no-op when captures exist, contradicting "forces re-training"). |
| P4c | 4xx body shape | `body_shape` = the observed request JSON body parsed as a dict; `{}` when missing/invalid (flush overrides `name`/`productId` anyway, `_make_add_item` :817-839). |
| P4d | Coles `lists_url` candidates | Candidates = observed same-origin GETs containing `list` (most recent first), then the current `page.url` if it contains `list`. Each is verified in page context (`fetch` → ok AND JSON array); first pass wins; none → discovery FAILED for coles (no capture saved). `check_url` := `lists_url`. |
| P5a | Topic-ID plumbing | Placeholders are `None` (never a fake integer — "nothing ships with fake IDs"). Helper `_int_env(env_var, fallback)` reads `TELEGRAM_SPECIALS_TOPIC_ID` / `TELEGRAM_WEEKLY_TOPIC_ID`; unset/invalid → fallback; `None` → DM-only + console note. No code path can post to 151 (constant deleted everywhere). |
| P5b | Resolve-list messages | Empty lists post a single `📋 <title>: none` message (the topic stays informative); non-empty lists are chunked at ≤ 4000 chars with `(part N/M)` suffix when > 1 part. Lists go to the topic ONLY (DMs keep exactly today's content: summary + specials). |
| P5c | Reminder skipped-topic shape | `fire()` records `results["topic"] = {"thread_id": None, "ok": True, "skipped": True}` when the weekly ID is unset (DM-only, no crash; `all_ok` unaffected). |

---

## 1. WP1 — D23: compare add-reminder (1 code file + 1 test file)

### Step 1.1 — `format_report` reminder (core/price_comparator.py)

**File:** `<ROOT>\grocery-price-tracker\core\price_comparator.py`
(current anchor: lines 829-832, the tail of `format_report`).

**Search anchor (exact):**
```python
    for w in report.warnings:
        lines.append(warn(w))

    return "\n".join(lines)
```

**Replace with (exact):**
```python
    for w in report.warnings:
        lines.append(warn(w))

    # D23: queue reminder — same line `search` prints (grocery_price_cli
    # :656-657), once per report, only when a DISPLAYED item shows a live
    # product (live-sourced price or a found-block). Sheet-only reports
    # show nothing (A1/A2).
    has_live_product = any(
        "live" in item.sources.values() or item.closest
        for item in report.items[:25]
    )
    if has_live_product:
        lines.append("")
        lines.append(
            "💬 Reply 'add item N' to queue a result for Wednesday."
        )

    return "\n".join(lines)
```

**Error boundaries:** none needed — pure formatting over dataclass fields;
`item.sources` / `item.closest` are always dicts (dataclass defaults). The
early-return branch for empty reports (line 680-681) is untouched.

**No other output changes.** Do not touch `compare_basket`, totals, 🏆 logic.

### Step 1.2 — WP1 tests (tests/test_comparator.py)

**File:** `<ROOT>\grocery-price-tracker\tests\test_comparator.py`
(append one new test class at end of file; reuse existing imports — the file
already imports `compare_basket`, `format_report`; add
`from core.price_comparator import BasketItem, ComparisonReport` to the
existing import line 19).

```python
class TestCompareAddReminder(unittest.TestCase):
    """D23 (WP1): the queue reminder in format_report — presence matrix."""

    REMINDER = "💬 Reply 'add item N' to queue a result for Wednesday."

    def _report(self, items):
        return ComparisonReport(items=items)

    def test_live_price_report_ends_with_reminder(self):
        item = BasketItem(
            name="milk",
            prices={"woolworths": 4.5, "coles": 4.2},
            sources={"woolworths": "live", "coles": "live"},
        )
        out = format_report(self._report([item]))
        self.assertTrue(out.rstrip().endswith(self.REMINDER))

    def test_found_block_only_report_ends_with_reminder(self):
        item = BasketItem(
            name="flour",
            closest={"woolworths": {"name": "WW Flour 2kg"}},
        )
        out = format_report(self._report([item]))
        self.assertTrue(out.rstrip().endswith(self.REMINDER))

    def test_sheet_only_report_has_no_reminder(self):
        item = BasketItem(
            name="milk",
            prices={"woolworths": 4.5, "coles": 4.2},
            sources={"woolworths": "sheet", "coles": "sheet"},
        )
        out = format_report(self._report([item]))
        self.assertNotIn(self.REMINDER, out)

    def test_mixed_report_reminder_appears_exactly_once(self):
        sheet_item = BasketItem(
            name="bread",
            prices={"woolworths": 3.0, "coles": 3.2},
            sources={"woolworths": "sheet", "coles": "sheet"},
        )
        live_item = BasketItem(
            name="milk",
            prices={"woolworths": 4.5},
            sources={"woolworths": "live"},
        )
        out = format_report(self._report([sheet_item, live_item]))
        self.assertEqual(out.count(self.REMINDER), 1)

    def test_empty_report_unchanged(self):
        out = format_report(ComparisonReport(items=[]))
        self.assertIn("No items provided.", out)
        self.assertNotIn(self.REMINDER, out)
```

**Verification (mandatory, Local Terminal):**
```powershell
& "$env:USERPROFILE\anaconda3\python.exe" -m py_compile grocery-price-tracker\core\price_comparator.py
& "$env:USERPROFILE\anaconda3\python.exe" -m pytest grocery-price-tracker\tests\test_comparator.py -q
& "$env:USERPROFILE\anaconda3\python.exe" -m pytest grocery-price-tracker\tests\test_comparator.py -k TestCompareAddReminder -q
```
All green, zero skipped. If any existing comparator test breaks, the change
left its surgical boundary — fix the change, not the tests.

---

## 2. WP2 — B4 retry tightening + B5 hard rule (1 code file, 1 doc file, 1 test file)

### Step 2.1 — Retry on 5xx/timeout only (extractors/coles_extractor.py)

**File:** `<ROOT>\grocery-price-tracker\extractors\coles_extractor.py`

**Anchor A — docstring chain semantics (current lines 255-262).**
Replace the two bullet lines:
```python
        - 5xx / RequestException -> silent retry with a NEW session,
          sleep(3) then sleep(6), exactly SCRAPEDO_MAX_ATTEMPTS attempts
        - 401/403 -> NEVER retried (fail immediately)
```
with:
```python
        - 5xx / RequestException -> silent retry with a NEW session,
          sleep(3) then sleep(6), exactly SCRAPEDO_MAX_ATTEMPTS attempts
        - 401/403 AND every other 4xx (404, 429, ...) -> NEVER retred
          (fail immediately; B4: retry on 5xx/timeout ONLY)
```
(typo guard: write `NEVER retried` — correct spelling.)

**Anchor B — the retry decision (current lines 318-320).**
**Search anchor (exact):**
```python
        if resp.status_code != 200:
            _backoff_sleep(attempt)
            continue
```
**Replace with (exact):**
```python
        if resp.status_code != 200:
            if resp.status_code >= 500:
                # B4: retry on 5xx/timeout ONLY — fresh session, backoff.
                _backoff_sleep(attempt)
                continue
            # 4xx (incl. 404/429): permanent for this run — no retry,
            # store marked unavailable (Woolworths-only + ⚠️ line path).
            print(
                f"[coles_extractor] Scrape.do returned HTTP "
                f"{resp.status_code} — not retrying",
                file=sys.stderr,
            )
            _breaker_record_failure()
            return [], "unavailable"
```
(P2a: mirrors the 401/403 branch above it. 401/403 keep their existing
dedicated branch — do not merge.) Search path only; the legacy
`_search_via_scrapedo` wrapper and list path are untouched.

### Step 2.2 — B5 hard rule (claw-skills/grocery-price/SKILL.md)

**File:** `<ROOT>\claw-skills\grocery-price\SKILL.md`

**Anchor — "## Hard rules" section (current line 223).** Append one bullet at
the END of the bullet list (after the "**Nothing is auto-queued.**" bullet,
line 231):
```markdown
- **Never browse the store sites (B5).** NEVER use `web_search`/`web_fetch`
  (or any browsing tool) on `woolworths.com.au` / `coles.com.au` — they block
  bots. ALL price, special, and discount questions about these stores go
  through the grocery CLI. Ordinary web search stays allowed for everything
  else.
```

### Step 2.3 — WP2 tests (tests/test_coles_recipe.py)

**File:** `<ROOT>\grocery-price-tracker\tests\test_coles_recipe.py`
(append a new class; reuse `FakeResponse`, `next_data_html`, and the
`ColesRecipeTestCase` isolation base).

```python
class TestB4RetryTightening(ColesRecipeTestCase):
    """B4/WP2: retry on 5xx/timeout ONLY; 4xx fails after ONE attempt."""

    def _run_status(self, responses):
        seq = iter(responses)
        with patch.object(
            ce.requests, "get",
            side_effect=lambda *a, **k: next(seq),
        ):
            return ce._search_via_scrapedo_status("milk")

    def test_404_not_retried(self):
        status = self._run_status([FakeResponse(404, "")])
        self.assertEqual(status, "unavailable")
        self.assertEqual(ce._calls_this_run, 1)
        self.assertEqual(self.sleeps, [])

    def test_429_not_retried(self):
        status = self._run_status([FakeResponse(429, "")])
        self.assertEqual(status, "unavailable")
        self.assertEqual(ce._calls_this_run, 1)
        self.assertEqual(self.sleeps, [])

    def test_502_retries_three_times(self):
        status = self._run_status([FakeResponse(502, "")] * 3)
        self.assertEqual(status, "unavailable")
        self.assertEqual(ce._calls_this_run, 3)
        self.assertEqual(self.sleeps, [3, 6])

    def test_timeout_retries_three_times(self):
        import requests as _rq
        with patch.object(
            ce.requests, "get",
            side_effect=_rq.RequestException("timeout"),
        ):
            status = ce._search_via_scrapedo_status("milk")
        self.assertEqual(status, "unavailable")
        self.assertEqual(ce._calls_this_run, 3)
```

**Audit (mandatory):** grep `test_coles_recipe.py` for any existing test that
asserts retries on a NON-5xx status (e.g. a 404/429 expecting 3 attempts).
Update those expectations to the new semantics (one attempt). Do not weaken
any 5xx/timeout/401/403 case.

```powershell
& "$env:USERPROFILE\anaconda3\python.exe" -m py_compile grocery-price-tracker\extractors\coles_extractor.py
& "$env:USERPROFILE\anaconda3\python.exe" -m pytest grocery-price-tracker\tests\test_coles_recipe.py -q
```

---

## 3. WP3 — D25: specials flags `no`/`discount`/`multi-buy` (4 code files, 2 callers, 2 test files)

### Step 3.1 — Regexes + `classify_special` (extractors/specials_parser.py)

**File:** `<ROOT>\grocery-price-tracker\extractors\specials_parser.py`

**Anchor A — after the `FOR_RE` block (current lines 33-35).** Insert:
```python
# D25 Coles markers:
#   ``Was $X`` — dollar-off special (same style as SAVE_RE).
WAS_RE = re.compile(
    r"was[\s\xa0]+\$?\s*([\d]+(?:\.[\d]{1,2})?)", re.IGNORECASE
)

#   ``Any N | $X`` — multi-buy (e.g. ``Any 2 | $9``); spacing/case tolerant.
ANY_RE = re.compile(
    r"any\s+(\d+)\s*\|\s*\$?\s*([\d]+(?:\.[\d]{1,2})?)", re.IGNORECASE
)

#   Bare ``SPECIAL`` flag line (Coles layout places it ABOVE the name).
SPECIAL_FLAG_RE = re.compile(r"^special$", re.IGNORECASE)
```

**Anchor B — end of file (after `detect_special`).** Append:
```python


def classify_special(is_special: bool, special_desc: str) -> str:
    """Classify a specials observation into the D25 sheet vocabulary.

    Precedence (decision 25, binding):
        1. ``Any N | $X`` (or ``N for $X``) in desc -> "multi-buy";
        2. Save/Was in desc, or ``is_special`` flag -> "discount";
        3. otherwise -> "no".

    Args:
        is_special: the item's specials flag (docx marker or live API).
        special_desc: the item's specials text ("" when none).

    Returns:
        str: exactly one of "multi-buy" | "discount" | "no".
    """
    desc = special_desc or ""
    if ANY_RE.search(desc) or FOR_RE.search(desc):
        return "multi-buy"
    if WAS_RE.search(desc) or SAVE_RE.search(desc) or is_special:
        return "discount"
    return "no"
```

### Step 3.2 — docx marker detection (extractors/doc_parser.py)

**File:** `<ROOT>\grocery-price-tracker\extractors\doc_parser.py`

**Anchor A — the specials_parser import (find the existing
`from extractors.specials_parser import ...` line near the top of the file).**
Extend it to:
```python
from extractors.specials_parser import (
    SAVE_RE, FOR_RE, WAS_RE, ANY_RE, SPECIAL_FLAG_RE,
)
```
(Keep whatever names it already imports; add the four new ones. If the file
imports differently, add a second import line — both are fine.)

**Anchor B — the specials detection block inside `parse_docx`
(current lines 264-290).**
**Search anchor (exact):**
```python
            is_special = False
            special_desc = ""
            if i + 2 < len(lines):
                detail_line = lines[i + 2]
                save_m = SAVE_RE.search(detail_line)
                for_m = FOR_RE.search(detail_line)
                if save_m:
```
**Replace the WHOLE block from `is_special = False` through the
`special_desc = f"{qty} for ${bundle:.2f}"` line (current 269-290) with:**
```python
            # Specials detection (D25):
            #   below the price (i+2): SAVE $X / N FOR $X (existing) plus
            #     the Coles markers `Was $X` and `Any N | $X` (desc kept
            #     exactly as found in the doc).
            #   above the name (i-1): ONLY a bare `SPECIAL` flag line. A
            #     bare Save/Was above a product is the PREVIOUS product's
            #     marker in the WW layout — checking it would attach the
            #     wrong special (A7 misfire guard).
            is_special = False
            special_desc = ""
            if i + 2 < len(lines):
                detail_line = lines[i + 2]
                save_m = SAVE_RE.search(detail_line)
                for_m = FOR_RE.search(detail_line)
                if save_m:
                    save_amt = float(save_m.group(1))
                    original = price + save_amt
                    discount_pct = (
                        (save_amt / original * 100.0)
                        if original > 0 else 0.0
                    )
                    is_special = True
                    special_desc = (
                        f"save ${save_amt:.2f} ({discount_pct:.0f}% off)"
                    )
                elif for_m:
                    qty = int(for_m.group(1))
                    bundle = float(for_m.group(2))
                    is_special = True
                    special_desc = f"{qty} for ${bundle:.2f}"
                elif WAS_RE.search(detail_line) or ANY_RE.search(
                        detail_line):
                    is_special = True
                    special_desc = detail_line  # kept as found
            if (
                not is_special
                and i >= 1
                and SPECIAL_FLAG_RE.match(lines[i - 1].strip())
            ):
                is_special = True
                special_desc = "SPECIAL"
```
(P3b: below-line wins when both exist.) Name/price matching semantics,
ignore-list, dedup (`seen`) — **unchanged** (do not touch lines 246-263).

### Step 3.3 — `sync_prices` flag write (core/sheets_sync.py)

**File:** `<ROOT>\grocery-price-tracker\core\sheets_sync.py`

**Search anchor (exact, current lines 233-236):**
```python
        if result.store in specials_col:
            row[specials_col[result.store]] = (
                item.special_desc if item.is_special else ""
            )
```
**Replace with (exact):**
```python
        if result.store in specials_col:
            # D25: M/N hold exactly one of no/discount/multi-buy; "no"
            # overwrites stale free text on every matched row. Unmatched
            # rows keep their old cells (same semantics as prices).
            from extractors.specials_parser import classify_special
            row[specials_col[result.store]] = classify_special(
                bool(item.is_special), str(item.special_desc or ""))
```

### Step 3.4 — `add_product_row` specials params (core/sheets_sync.py)

**Anchor A — signature (current lines 660-672).** Add two keyword-only
params after `alias`:
```python
def add_product_row(
    generic_name: str,
    store: str,
    price: float,
    *,
    brand: str = "",
    size: str = "",
    category: str = "",
    store_keyword: str = "",
    alias: str = "",
    is_special: bool = False,
    special_desc: str = "",
    dry_run: bool = False,
    worksheet=None,
) -> dict:
```
Also extend the docstring Args block with:
```
        is_special: the live item's specials flag (D25; default False).
        special_desc: the live item's specials text (default "").
```

**Anchor B — after `keywords_col = _find_col(header, KEYWORDS_HEADER)`
(current line 728).** Insert:
```python
    specials_col = _find_col(
        header, SPECIALS_HEADER_BY_STORE.get(store_lower, ""))
```

**Anchor C — the `target_width` computation (current lines 731-737).** Add
one entry to the `max(...)` call:
```python
        (specials_col + 1) if specials_col is not None else 0,
```

**Anchor D — after the alias write (current lines 756-757).** Insert:
```python
    if specials_col is not None:
        from extractors.specials_parser import classify_special
        new_row[specials_col] = classify_special(is_special, special_desc)
```

### Step 3.5 — `update_single_price` specials params (core/sheets_sync.py)

**Anchor A — signature (current lines 302-309).** Add two keyword-only
params (P3a):
```python
def update_single_price(
    product_name: str,
    store: str,
    price: float,
    *,
    dry_run: bool = False,
    is_special: Optional[bool] = None,
    special_desc: str = "",
    worksheet=None,
) -> dict:
```
Docstring: add the two params (`None` = leave the specials cell untouched).

**Anchor B — the live-write block (current lines 436-449).**
**Search anchor (exact):**
```python
    ts = _sydney_now_str()
    full_row = list(row_data)  # make mutable copy
    target_width = max(price_col + 1, LAST_UPDATED_COL + 1)
    while len(full_row) < target_width:
        full_row.append("")
    full_row[price_col] = price
    full_row[LAST_UPDATED_COL] = ts
    # Truncate to target_width — the sheet row has 16 cols (A-P) but we only
    # write up to LAST_UPDATED_COL; gspread rejects writing past the range.
    full_row = full_row[:target_width]
```
**Replace with (exact):**
```python
    ts = _sydney_now_str()
    full_row = list(row_data)  # make mutable copy
    header = all_values[0] if all_values else []
    specials_col = _find_col(
        header, SPECIALS_HEADER_BY_STORE.get(store_lower, ""))
    write_specials = is_special is not None and specials_col is not None
    target_width = max(price_col + 1, LAST_UPDATED_COL + 1)
    if write_specials:
        # Widen past M/N so the flag cell is inside the written range.
        target_width = max(target_width, specials_col + 1)
    while len(full_row) < target_width:
        full_row.append("")
    full_row[price_col] = price
    full_row[LAST_UPDATED_COL] = ts
    if write_specials:
        from extractors.specials_parser import classify_special
        full_row[specials_col] = classify_special(is_special, special_desc)
    # Truncate to target_width — the sheet row has 16 cols (A-P); gspread
    # rejects writing past the range.
    full_row = full_row[:target_width]
```
(The `dry_run` early-return above is untouched — it never wrote cells.)

### Step 3.6 — CLI callers pass specials (grocery_price_cli.py; 3 sites)

**File:** `<ROOT>\grocery_price_cli.py` (workspace root, NOT inside the tracker).

1. `_search_add_item` (anchor: the `add_product_row(` call, current lines
   691-700). Add after `alias=product,`:
```python
            is_special=chosen.is_special,
            special_desc=chosen.special_desc,
```
2. `_add_from_live_search` (anchor: the `add_product_row(` call, current
   lines 2109-2118). Add after `alias=original_query,`:
```python
            is_special=best.is_special,
            special_desc=best.special_desc,
```
3. `map wool/coles --add` path (anchor, current line 2593):
```python
                res = update_single_price(item, store, best.price)
```
→
```python
                res = update_single_price(
                    item, store, best.price,
                    is_special=best.is_special,
                    special_desc=best.special_desc)
```
The `_cmd_update` call (line 414) and the interactive `_prompt_action` path
(line 2064) are deliberately NOT changed (no specials data / outside spec).

### Step 3.7 — Telegram gateway callers (telegram_gateway/handlers.py; 2 sites)

**File:** `<ROOT>\telegram_gateway\handlers.py`

1. `_add_from_live_search` (anchor: `add_product_row(` call, current lines
   663-671). Add after `alias=original_query,`:
```python
            is_special=best.is_special,
            special_desc=best.special_desc,
```
2. Map add path (anchor, current line 926):
```python
                    res = update_single_price(session["query"], store, best.price)
```
→
```python
                    res = update_single_price(
                        session["query"], store, best.price,
                        is_special=best.is_special,
                        special_desc=best.special_desc)
```
(Args-only; logic lives in sheets_sync per the spec.)

### Step 3.8 — Reporter vocabulary (core/specials_reporter.py)

**File:** `<ROOT>\grocery-price-tracker\core\specials_reporter.py`

**Anchor A — docstring (lines 47-49).** Change the last sentence to:
`A product is "on special" if its store specials cell (M for woolworths,
N for coles) is non-empty and not "no" (D25/A6).`

**Anchor B — the row loop (current lines 96-118).**
**Search anchor (exact):**
```python
        for store_key, col_idx in specials_col.items():
            if col_idx < len(row) and row[col_idx].strip():
```
**Replace with (exact):**
```python
        for store_key, col_idx in specials_col.items():
            if col_idx >= len(row):
                continue
            cell = str(row[col_idx]).strip()
            # A6 back-compat: empty/"no" -> not on special; "multi-buy"
            # reports as multi-buy; ANY other non-empty cell (incl.
            # legacy free text) reports as a special (discount).
            if not cell or cell.lower() == "no":
                continue
```
And in the `results.append({...})` below it, change
`"special_desc": str(row[col_idx]).strip(),` to `"special_desc": cell,`.
`format_specials_report` and the Wednesday step-8 specials report are NOT
touched.

### Step 3.9 — WP3 tests (NEW tests/test_specials_flags.py + test_sheets_sync.py additions)

**File (create):** `<ROOT>\grocery-price-tracker\tests\test_specials_flags.py`
```python
#!/usr/bin/env python3
"""D25/WP3: classifier matrix, Coles docx markers, sheet writes, reporter.

No network. Docx fixtures are written with python-docx into a temp dir.
"""
from __future__ import annotations
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from extractors.specials_parser import (  # noqa: E402
    WAS_RE, ANY_RE, SPECIAL_FLAG_RE, classify_special,
)
from extractors.doc_parser import parse_docx  # noqa: E402
from core.specials_reporter import get_active_specials  # noqa: E402


class FakeWorksheet:
    """Minimal gspread Worksheet mock (get_all_values only)."""

    def __init__(self, rows):
        self._values = [list(r) for r in rows]

    def get_all_values(self):
        return [list(r) for r in self._values]


def _write_docx(paragraphs):
    """Write a temp .docx with the given paragraph strings; return path."""
    from docx import Document
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "list.docx"
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    doc.save(str(path))
    return path, tmp


class TestClassifySpecial(unittest.TestCase):
    """Full precedence matrix (decision 25)."""

    def test_empty_and_not_special_is_no(self):
        self.assertEqual(classify_special(False, ""), "no")

    def test_flag_only_is_discount(self):
        self.assertEqual(classify_special(True, ""), "discount")

    def test_save_desc_is_discount(self):
        self.assertEqual(classify_special(True, "save $1.53 (35% off)"),
                         "discount")

    def test_was_desc_is_discount_even_without_flag(self):
        self.assertEqual(classify_special(False, "Was $13.20"), "discount")

    def test_for_desc_is_multi_buy(self):
        self.assertEqual(classify_special(True, "2 for $4.50"), "multi-buy")
        self.assertEqual(classify_special(True, "6 for $10"), "multi-buy")

    def test_any_desc_is_multi_buy(self):
        self.assertEqual(classify_special(True, "Any 2 | $9"), "multi-buy")

    def test_any_desc_spacing_case_tolerant(self):
        self.assertEqual(classify_special(False, "any 2|$9.00"), "multi-buy")
        self.assertEqual(classify_special(False, "ANY 2 |  $9"), "multi-buy")

    def test_any_beats_save(self):
        self.assertEqual(
            classify_special(True, "Any 2 | $9 and Save $2"), "multi-buy")

    def test_special_flag_desc_is_discount(self):
        self.assertEqual(classify_special(True, "SPECIAL"), "discount")

    def test_half_price_is_discount(self):
        self.assertEqual(classify_special(True, "Half Price"), "discount")

    def test_coles_promotion_type_multi_buy_is_discount(self):
        # P3c: promotionType MULTI_BUY renders as "Multi Buy" — no D25
        # desc pattern matches -> spec-sanctioned "else discount".
        self.assertEqual(classify_special(True, "Multi Buy"), "discount")


class TestMarkerRegexes(unittest.TestCase):
    def test_was_re(self):
        self.assertIsNotNone(WAS_RE.search("Was $13.20"))
        self.assertIsNotNone(WAS_RE.search("was\xa0$9"))
        self.assertIsNone(WAS_RE.search("save $1"))

    def test_any_re(self):
        self.assertIsNotNone(ANY_RE.search("Any 2 | $9"))
        self.assertIsNotNone(ANY_RE.search("ANY 2 | $9.00"))
        self.assertIsNone(ANY_RE.search("Any 2"))
        self.assertIsNone(ANY_RE.search("Any | $9"))

    def test_special_flag_re(self):
        self.assertIsNotNone(SPECIAL_FLAG_RE.match("SPECIAL"))
        self.assertIsNotNone(SPECIAL_FLAG_RE.match(" special "))
        self.assertIsNone(SPECIAL_FLAG_RE.match("SPECIAL OFFER"))
        self.assertIsNone(SPECIAL_FLAG_RE.match("Was $1"))


class TestDocxColesMarkers(unittest.TestCase):
    def _parse(self, paragraphs):
        path, tmp = _write_docx(paragraphs)
        self.addCleanup(tmp.cleanup)
        return parse_docx(str(path), store="coles")

    def test_special_flag_above_name(self):
        items = self._parse(
            ["SPECIAL", "Coles Milk 2L", "$3.20"])
        self.assertTrue(items[0].is_special)
        self.assertEqual(items[0].special_desc, "SPECIAL")

    def test_was_below_price(self):
        items = self._parse(
            ["Coles Bread Loaf", "$2.50", "Was $3.20"])
        self.assertTrue(items[0].is_special)
        self.assertEqual(items[0].special_desc, "Was $3.20")

    def test_any_below_price(self):
        items = self._parse(
            ["Coles Chips 175g", "$4.00", "Any 2 | $9"])
        self.assertTrue(items[0].is_special)
        self.assertEqual(items[0].special_desc, "Any 2 | $9")

    def test_below_line_wins_over_flag_above(self):
        items = self._parse(
            ["SPECIAL", "Coles Yogurt 700g", "$5.00", "Was $6.00"])
        self.assertTrue(items[0].is_special)
        self.assertEqual(items[0].special_desc, "Was $6.00")

    def test_a7_misfire_save_above_next_product_not_attached(self):
        items = self._parse(
            ["WW Product A", "$5.00", "save $1.00", "WW Product B", "$4.00"])
        by_name = {i.raw_name: i for i in items}
        self.assertTrue(by_name["WW Product A"].is_special)
        self.assertFalse(by_name["WW Product B"].is_special)

    def test_plain_item_not_special(self):
        items = self._parse(["Coles Milk 2L", "$3.20"])
        self.assertFalse(items[0].is_special)
        self.assertEqual(items[0].special_desc, "")


class TestReporterVocabulary(unittest.TestCase):
    HEADER = ["Product_Name", "Category", "Size", "Woolworths_Price",
              "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
              "Search_Keyword_Woolworths", "Search_Keyword_Coles",
              "Search_Keyword_Aldi", "Aldi_Refresh",
              "Woolworths_Specials", "Coles_Specials", "Rewards_Points"]

    def _rows(self, ww_cell, coles_cell):
        return [
            self.HEADER,
            ["Milk 2L", "", "", "$4.50", "$4.20", "", "", "",
             "", "", "", "", ww_cell, coles_cell, ""],
        ]

    def test_no_and_empty_excluded(self):
        ws = FakeWorksheet(self._rows("no", ""))
        self.assertEqual(get_active_specials(worksheet=ws), [])

    def test_vocabulary_included_with_cell_as_desc(self):
        ws = FakeWorksheet(self._rows("discount", "multi-buy"))
        result = get_active_specials(worksheet=ws)
        descs = sorted(r["special_desc"] for r in result)
        self.assertEqual(descs, ["discount", "multi-buy"])

    def test_legacy_free_text_reports_as_discount_special(self):
        ws = FakeWorksheet(self._rows("50% off", ""))
        result = get_active_specials(worksheet=ws)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["special_desc"], "50% off")


if __name__ == "__main__":
    unittest.main()
```

**File (edit):** `<ROOT>\grocery-price-tracker\tests\test_sheets_sync.py` —
append a class `TestSpecialsFlagWrites` covering, against the existing
FakeWorksheet pattern (copy the class if this file lacks one):
- `sync_prices`: matched item `is_special=True, special_desc="Any 2 | $9"` →
  M/N cell `"multi-buy"`; matched not-special item → cell `"no"`; unmatched
  row keeps its legacy cell (e.g. `"50% off"` stays).
- `add_product_row`: default call → specials cell `"no"`; with
  `is_special=True, special_desc="Was $2.00"` → `"discount"`; header without
  M/N → no specials write, no crash.
- `update_single_price`: no specials args → M/N cell untouched; with
  `is_special=False` → `"no"` written and `range_written` extends to M/N;
  with `is_special=True, special_desc="2 for $4"` → `"multi-buy"`.

**Verification (mandatory):**
```powershell
& "$env:USERPROFILE\anaconda3\python.exe" -m py_compile grocery-price-tracker\extractors\specials_parser.py grocery-price-tracker\extractors\doc_parser.py grocery-price-tracker\core\sheets_sync.py grocery-price-tracker\core\specials_reporter.py
& "$env:USERPROFILE\anaconda3\python.exe" -m pytest grocery-price-tracker\tests\test_specials_flags.py -q
& "$env:USERPROFILE\anaconda3\python.exe" -m pytest grocery-price-tracker\tests\test_sheets_sync.py -q
```
Then run the FULL suite. Existing tests that assert the OLD M/N write
semantics (`special_desc` or `""`) are the only ones allowed to be updated —
grep `test_sheets_sync.py`, `test_extractors.py`, `test_cli.py` for
`specials` cell assertions and align them with the vocabulary.

---

## 4. WP4 — D26/D27: real discovery recording + loud status (1 code file, 1 CLI file, 2 test files)

### Step 4.1 — `_parse_json_body` helper (extractors/session_refresh.py)

**File:** `<ROOT>\grocery-price-tracker\extractors\session_refresh.py`

Insert after `_write_json_atomic` (after current line ~127):
```python
def _parse_json_body(text) -> dict:
    """Best-effort JSON request-body parse; {} when missing/invalid (P4c)."""
    try:
        data = json.loads(text or "")
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}
```

### Step 4.2 — `_LocalDriver.capture_add_to_list` + `_verify_coles_lists_url`

**Anchor — inside `class _LocalDriver`, after the `close` method (current
line 624).** Insert:
```python
    def capture_add_to_list(self, store: str):
        """Record the real add-to-list API call (D26 discovery, §4.5).

        Attaches a Playwright request listener BEFORE prompting, prints
        the guided prompt, then polls up to TWO_FA_WAIT_S (3 min) for the
        FIRST same-origin non-GET request whose URL or body mentions a
        list. Coles additionally resolves + verifies `lists_url` (and
        sets `check_url`); a failed verification returns None so no
        broken capture is saved.

        Args:
            store: "woolworths" | "coles".

        Returns:
            dict: {"method", "url", "body_shape"} (+ "lists_url",
            "check_url" for coles), or None when nothing was captured.
        """
        page = self._pages[store]
        origin = ("https://www.woolworths.com.au"
                  if store == "woolworths"
                  else "https://www.coles.com.au")
        add_candidates: list = []
        list_gets: list = []

        def _on_request(request):
            try:
                method = str(request.method).upper()
                url = str(request.url)
                if not url.startswith(origin):
                    return
                if method != "GET":
                    body = request.post_data or ""
                    if "list" in url.lower() or "list" in body.lower():
                        add_candidates.append({
                            "method": method,
                            "url": url,
                            "body_shape": _parse_json_body(body),
                        })
                elif "list" in url.lower():
                    list_gets.append(url)
            except Exception:
                pass  # listener must never break the page

        page.on("request", _on_request)
        print(f"Add ONE item to your Price Compare list in the open "
              f"window ({store})…")
        deadline = time.monotonic() + TWO_FA_WAIT_S
        while time.monotonic() < deadline and not add_candidates:
            time.sleep(1.0)
        try:
            page.remove_listener("request", _on_request)
        except Exception:
            pass
        if not add_candidates:
            return None
        capture = dict(add_candidates[0])  # FIRST candidate wins
        if store == "coles":
            lists_url = self._verify_coles_lists_url(list_gets)
            if not lists_url:
                return None  # broken capture — discovery FAILED
            capture["lists_url"] = lists_url
            capture["check_url"] = lists_url
        return capture

    def _verify_coles_lists_url(self, list_gets: list):
        """Resolve + verify the Coles saved-lists URL (P4d).

        Candidates: observed same-origin GETs containing "list" (most
        recent first), then the current page URL when it contains
        "list". A candidate verifies when an in-page fetch returns ok
        AND a JSON array. Returns the verified URL or "".
        """
        page = self._pages["coles"]
        candidates: list = []
        seen = set()
        for url in reversed(list_gets):
            if url not in seen:
                seen.add(url)
                candidates.append(url)
        try:
            current = str(page.url)
            if "list" in current.lower() and current not in seen:
                candidates.append(current)
        except Exception:
            pass
        expression = (
            "async ([url]) => { try { const r = await fetch(url);"
            " if (!r.ok) return null; const data = await r.json();"
            " return Array.isArray(data) ? url : null; }"
            " catch (e) { return null; } }")
        for url in candidates:
            try:
                if self.evaluate("coles", expression, [url]) == url:
                    return url
            except Exception:
                continue
        return ""
```

### Step 4.3 — `_run_discovery`: prompt move + hasattr removal + force

**Search anchor (exact, current lines 1024-1043):**
```python
def _run_discovery(driver, summary: dict) -> None:
    """Guided API discovery (§4.5): once per store, user adds ONE item."""
    for store in STORES:
        if not _needs_capture(store):
            continue
        print(f"Add ONE item to your Price Compare list in the open "
              f"window ({store})…")
        # The real recording driver is configured by the caller through
        # driver.start(); this phase waits for the network event that
        # matches the saved-list mutation and records its shape.
        try:
            capture = driver.capture_add_to_list(store) if hasattr(
                driver, "capture_add_to_list") else None
        except Exception as exc:
            capture = {"error": str(exc)}
        if isinstance(capture, dict) and capture.get("url"):
            _write_discovery_capture(store, capture)
            summary.setdefault("discovery", {})[store] = "captured"
        else:
            summary.setdefault("discovery", {})[store] = "failed"
```
**Replace with (exact):**
```python
def _run_discovery(driver, summary: dict, force: bool = False) -> None:
    """Guided API discovery (§4.5): once per store, user adds ONE item.

    The driver prints the prompt itself AFTER attaching the request
    listener (P4a). ``force`` re-trains even when a capture exists
    (--recapture, P4b).
    """
    for store in STORES:
        if not force and not _needs_capture(store):
            continue
        try:
            capture = driver.capture_add_to_list(store)
        except Exception as exc:
            capture = {"error": str(exc)}
        if isinstance(capture, dict) and capture.get("url"):
            _write_discovery_capture(store, capture)
            summary.setdefault("discovery", {})[store] = "captured"
        else:
            summary.setdefault("discovery", {})[store] = "failed"
```

### Step 4.4 — Auto-discovery gate in `run()`

**Search anchor (exact, current lines 986-991):**
```python
    if recapture:
        try:
            _run_discovery(driver, summary)
        except Exception as exc:
            print(f"[session_refresh] discovery failed: {exc}",
                  file=sys.stderr)
```
**Replace with (exact):**
```python
    # D26: auto-discovery — run when forced OR when any store lacks a
    # capture (a true FIRST run must prompt, not fail wholesale).
    if recapture or any(_needs_capture(s) for s in STORES):
        try:
            _run_discovery(driver, summary, force=recapture)
        except Exception as exc:
            print(f"[session_refresh] discovery failed: {exc}",
                  file=sys.stderr)
```

### Step 4.5 — Per-store flush isolation in `_phase_b_flush`

**Search anchor (exact, current lines 788-797):**
```python
        add_item = _make_add_item(store, driver, capture)
        result = _flush_store(
            store, to_flush,
            add_item=add_item,
            consume_entry=_consume_queue_entry,
            log_append=lambda rec: _append_flush_log(FLUSH_LOG_PATH, rec),
            sleep=time.sleep, clock=time.monotonic,
            jitter=lambda: random.uniform(0, FLUSH_JITTER_S))
        result["parked"] = parked
        summary[store]["flush"] = result
```
**Replace with (exact):**
```python
        # D26: per-store isolation — a missing capture (or any per-store
        # failure) fails ONLY this store's flush; the other proceeds.
        try:
            add_item = _make_add_item(store, driver, capture)
            result = _flush_store(
                store, to_flush,
                add_item=add_item,
                consume_entry=_consume_queue_entry,
                log_append=lambda rec: _append_flush_log(FLUSH_LOG_PATH, rec),
                sleep=time.sleep, clock=time.monotonic,
                jitter=lambda: random.uniform(0, FLUSH_JITTER_S))
            result["parked"] = parked
            summary[store]["flush"] = result
        except RuntimeError as exc:
            summary[store]["flush"] = {
                "added": [], "failed": to_flush, "parked": parked,
                "session_died": False,
                "reason": "no API capture — run live-refresh --recapture",
            }
            print(f"[session_refresh] flush skipped for {store}: {exc}",
                  file=sys.stderr)
        except Exception as exc:
            summary[store]["flush"] = {
                "added": [], "failed": to_flush, "parked": parked,
                "session_died": False, "reason": str(exc),
            }
            print(f"[session_refresh] flush failed for {store}: {exc}",
                  file=sys.stderr)
```

### Step 4.6 — D27 CLI status prints (grocery_price_cli.py; 2 blocks)

**Block A — `_cmd_live_refresh` summary loop.** Search anchor (exact):
```python
        print(kv("Login", "OK" if login_ok else "FAILED"))
        if not login_ok:
            ok_all = False
```
Insert immediately AFTER `print(kv("Login", ...))` and BEFORE `if not
login_ok:`:
```python
        discovery = (summary.get("discovery") or {}).get(store)
        if discovery == "captured":
            print(kv("Discovery", "captured"))
        elif discovery is not None:
            print(kv(
                "Discovery",
                "failed — run 'live-refresh --recapture' to train"))
```

**Block B — wednesday live window block (current lines 1226-1229).**
Search anchor (exact):
```python
            for store in ("woolworths", "coles"):
                store_summary = window_summary.get(store, {})
                login = "OK" if store_summary.get("login") else "FAILED"
                print(f"  {store.capitalize()}: login {login}")
```
Insert immediately after the login print (before `flush_result =`):
```python
                discovery = (window_summary.get("discovery") or {}).get(store)
                if discovery == "captured":
                    print(f"    discovery: captured")
                elif discovery is not None:
                    print(f"    discovery: failed — run "
                          f"'live-refresh --recapture' to train")
```
Also in BOTH blocks, when a flush dict carries a `reason`, print it after
the counts (keep the existing failed-item lines):
- Block A, inside the `if phase == "flush":` branch, after the
  `Parked` kv line:
```python
                        if phase_result.get("reason"):
                            print(kv("Reason", phase_result["reason"]))
```
- Block B, after the flush counts print:
```python
                    if flush_result.get("reason"):
                        print(f"      reason: {flush_result['reason']}")
```

### Step 4.7 — WP4 tests (test_live_window.py + test_cli.py additions)

**File:** `<ROOT>\grocery-price-tracker\tests\test_live_window.py` — append:

```python
class FakeReq:
    """Playwright Request stand-in."""

    def __init__(self, method, url, post_data=None):
        self.method = method
        self.url = url
        self.post_data = post_data


class FakePage:
    """Playwright page stand-in: on()/remove_listener()/evaluate()/url."""

    def __init__(self, url=""):
        self.url = url
        self.listeners = {}
        self.eval_fn = lambda expr, arg: None

    def on(self, event, handler):
        self.listeners.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        if event in self.listeners:
            self.listeners[event] = [
                h for h in self.listeners[event] if h is not handler]

    def fire(self, request):
        for h in self.listeners.get("request", []):
            h(request)

    def evaluate(self, expression, arg=None):
        return self.eval_fn(expression, arg)


class TestCaptureAddToList(unittest.TestCase):
    """D26/WP4: _LocalDriver.capture_add_to_list via a fake page."""

    def _driver(self, store, page):
        drv = sr._LocalDriver(lambda: None)
        drv._pages = {store: page}
        return drv

    def setUp(self):
        self._mono = None  # each test sets a monotonic() value sequence

        def fake_monotonic():
            vals = self._mono
            if not vals:
                return 0.0
            return next(vals)
        patches = [
            patch.object(sr.time, "monotonic", side_effect=fake_monotonic),
            patch.object(sr.time, "sleep", side_effect=lambda s: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_first_candidate_wins(self):
        page = FakePage()
        drv = self._driver("woolworths", page)
        page.fire(FakeReq("POST",
                          "https://www.woolworths.com.au/apis/ui/mylists/items",
                          '{"listId": 1}'))
        # second (later) request must NOT replace the first capture
        page.fire(FakeReq("PUT",
                          "https://www.woolworths.com.au/apis/ui/other",
                          '{"listId": 2}'))
        page.listeners["request"] = []  # stop buffering; poll exits at once
        # monotonic(): deadline base (0), loop check (0 < 180 -> exit)
        self._mono = [0, 0]
        capture = drv.capture_add_to_list("woolworths")
        self.assertIsNotNone(capture)
        self.assertEqual(capture["method"], "POST")
        self.assertTrue(capture["url"].endswith("/mylists/items"))
        self.assertEqual(capture["body_shape"], {"listId": 1})

    def test_timeout_returns_none(self):
        page = FakePage()
        drv = self._driver("woolworths", page)
        self._mono = [0, 1, 2, 200]  # deadline exceeded, nothing fired
        self.assertIsNone(drv.capture_add_to_list("woolworths"))

    def test_foreign_origin_ignored(self):
        page = FakePage()
        drv = self._driver("woolworths", page)
        page.fire(FakeReq("POST", "https://evil.example.com/add-list", "{}"))
        self._mono = [0, 1, 2, 200]
        self.assertIsNone(drv.capture_add_to_list("woolworths"))

    def test_coles_lists_url_verified(self):
        page = FakePage("https://www.coles.com.au/shop/lists")
        drv = self._driver("coles", page)
        ok_url = "https://www.coles.com.au/api/v1/lists"
        page.eval_fn = (
            lambda expr, arg: arg[0] if arg and arg[0] == ok_url else None)
        page.fire(FakeReq("GET", ok_url))
        page.fire(FakeReq(
            "POST", "https://www.coles.com.au/api/v1/lists/items",
            '{"name": "x"}'))
        page.listeners["request"] = []  # stop buffering; poll exits at once
        self._mono = [0, 0]  # deadline base, loop check
        capture = drv.capture_add_to_list("coles")
        self.assertIsNotNone(capture)
        self.assertEqual(capture["lists_url"], ok_url)
        self.assertEqual(capture["check_url"], ok_url)

    def test_coles_lists_url_unverified_fails_discovery(self):
        page = FakePage("https://www.coles.com.au/shop/other")
        drv = self._driver("coles", page)
        page.eval_fn = lambda expr, arg: None  # nothing verifies
        page.fire(FakeReq(
            "POST", "https://www.coles.com.au/api/v1/lists/items",
            '{"name": "x"}'))
        page.listeners["request"] = []  # stop buffering; poll exits at once
        self._mono = [0, 0]  # deadline base, loop check
        self.assertIsNone(drv.capture_add_to_list("coles"))


class TestAutoDiscoveryAndIsolation(unittest.TestCase):
    """D26/WP4: auto-discovery gating + per-store flush isolation."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.capture_path = Path(self._tmp.name) / "capture.json"
        self._cap_patch = patch.object(
            sr, "CAPTURE_PATH", self.capture_path)
        self._cap_patch.start()
        self.addCleanup(self._cap_patch.stop)

    def test_auto_discovery_runs_when_capture_missing(self):
        calls = []

        class FakeDriver:
            def capture_add_to_list(self_, store):
                calls.append(store)
                return {"method": "POST", "url": "https://x/api",
                        "body_shape": {}}

        summary = {"woolworths": {}, "coles": {}}
        sr._run_discovery(FakeDriver(), summary, force=False)
        self.assertEqual(calls, ["woolworths", "coles"])
        self.assertEqual(summary["discovery"]["woolworths"], "captured")

    def test_no_discovery_when_captures_exist(self):
        self.capture_path.write_text(json.dumps({
            "woolworths": {"url": "https://x/api"},
            "coles": {"url": "https://y/api"},
        }), encoding="utf-8")

        class FakeDriver:
            def capture_add_to_list(self_, store):
                raise AssertionError("must not be called")

        summary = {"woolworths": {}, "coles": {}}
        sr._run_discovery(FakeDriver(), summary, force=False)
        self.assertNotIn("discovery", summary)

    def test_force_recaptures_even_when_captures_exist(self):
        self.capture_path.write_text(json.dumps({
            "woolworths": {"url": "https://x/api"},
            "coles": {"url": "https://y/api"},
        }), encoding="utf-8")

        class FakeDriver:
            def capture_add_to_list(self_, store):
                return {"method": "POST", "url": "https://z/api",
                        "body_shape": {}}

        summary = {"woolworths": {}, "coles": {}}
        sr._run_discovery(FakeDriver(), summary, force=True)
        self.assertEqual(summary["discovery"]["woolworths"], "captured")

    def test_run_auto_discovers_on_first_run(self):
        # run() gates on any(_needs_capture) — verify via a driver fake
        # whose capture works; login/flush/fetch disabled.
        class FakeDriver:
            def capture_add_to_list(self_, store):
                return {"method": "POST", "url": "https://x/api",
                        "body_shape": {}}

        with patch.object(sr, "_phase_a_login", lambda d, s: None):
            summary = sr.run(flush=False, fetch=False, _driver=FakeDriver())
        self.assertEqual(
            summary.get("discovery", {}).get("woolworths"), "captured")

    def test_phase_b_flush_isolates_missing_capture(self):
        capture = {"woolworths": {"method": "POST",
                                  "url": "https://ww/api",
                                  "body_shape": {}}}
        entries = [
            {"store": "woolworths", "keyword": "milk",
             "generic_name": "milk", "queue": "searched_items"},
            {"store": "coles", "keyword": "bread",
             "generic_name": "bread", "queue": "searched_items"},
        ]
        summary = {s: {"login": True, "flush": None, "fetch": None}
                   for s in sr.STORES}
        with patch.object(sr, "_load_both_queues", return_value=entries), \
             patch.object(sr, "_load_attempt_history", return_value={}), \
             patch.object(sr, "_read_json", return_value=capture), \
             patch.object(sr, "_flush_store") as flush_store, \
             patch.object(sr, "_append_flush_log"):
            flush_store.return_value = {"added": entries[:1], "failed": [],
                                        "session_died": False}
            sr._phase_b_flush(object(), summary)
        self.assertEqual(
            summary["woolworths"]["flush"]["added"][0]["keyword"], "milk")
        self.assertEqual(summary["coles"]["flush"]["failed"][0]
                         ["keyword"], "bread")
        self.assertEqual(
            summary["coles"]["flush"]["reason"],
            "no API capture — run live-refresh --recapture")
```

**File:** `<ROOT>\grocery-price-tracker\tests\test_cli.py` — append a class
`TestDiscoveryStatusPrints`: patch
`extractors.session_refresh.run` (as imported inside `_cmd_live_refresh`) to
return a fixed summary dict `{"woolworths": {"login": True, "flush": None,
"fetch": None}, "coles": {...}, "discovery": {"woolworths": "captured",
"coles": "failed"}}`, invoke `grocery_price_cli._cmd_live_refresh` with a
`SimpleNamespace(recapture=False, flush_only=False, fetch_only=False)`,
capture stdout, and assert `"Discovery: captured"` and
`"Discovery: failed — run 'live-refresh --recapture' to train"` appear.
(Reuse the module import pattern at the top of test_cli.py:
`import grocery_price_cli` — the file already bootstraps `_ROOT`.)

**Audit (mandatory):** existing `test_live_window.py` W-matrix tests that
call `sr.run(_driver=fake)` now also traverse the auto-discovery gate (their
temp/patched CAPTURE_PATH state decides). Run the suite; any fake driver
without `capture_add_to_list` records `"failed"` in
`summary["discovery"]` (caught by the `except` — never crashes). Only update
existing assertions that explicitly break; never delete a test.

**Verification (mandatory):**
```powershell
& "$env:USERPROFILE\anaconda3\python.exe" -m py_compile grocery-price-tracker\extractors\session_refresh.py grocery_price_cli.py
& "$env:USERPROFILE\anaconda3\python.exe" -m pytest grocery-price-tracker\tests\test_live_window.py -q
& "$env:USERPROFILE\anaconda3\python.exe" -m pytest grocery-price-tracker\tests\test_cli.py -q
```

---

## 5. WP5 — D24: Telegram topic split + `topics-check` (4 code files, 2 docs)

> All WP5 code ships with `None` placeholders + env overrides (P5a). The
> integer fill happens ONLY in Step 5.9 after manual step M1 (§8). Nothing
> ever posts to thread 151 again.

### Step 5.1 — topics.py: two new topics, retire 151

**File:** `<ROOT>\telegram_gateway\topics.py`
**Full replacement of the constants + resolver (keep the docstring, updating
it):**
```python
"""
Telegram Gateway - Forum Topics

Canonical source of thread IDs: TELEGRAM_TOPICS.md at the workspace root
("Claw Command Center" supergroup, verified via getUpdates on 2026-08-09;
D24 topics verified via `topics-check` after M1).

Keep THREAD_IDS in sync with TELEGRAM_TOPICS.md whenever topics change.
A duplicate morning-digest topic exists at thread_id 13 (created later);
the active digest target is thread_id 2.
"""

import os

CHAT_ID = -1004394070843  # Claw Command Center supergroup

# D24 (2026-08-30): Wednesday output split into two topics. IDs are filled
# from manual step M1 (user-reported via `topics-check`); the env overrides
# below always win (A8). Until filled, senders fall back to DM-only.
SPECIALS_WOOL_TOPIC_ID = None   # env: TELEGRAM_SPECIALS_TOPIC_ID
WEEKLY_LISTS_TOPIC_ID = None    # env: TELEGRAM_WEEKLY_TOPIC_ID

THREAD_IDS = {
    "morning-digest": 2,
    "llm-costs": 3,
    "finance": 4,
    "retail-deals": 5,
    "content-creation": 6,
    "video-projects": 7,   # DEPRECATED (Phase 8 audit, 2026-08-24): video pipeline retired in Phase 3.5.6
    "sysadmin": 8,
    "sports": 9,   # DEPRECATED (Phase 8 audit, 2026-08-24): only used by pl27_poster (REMOVED, Phase 3.5.6)
    "email-control": 10,   # DEPRECATED (Phase 8 audit, 2026-08-24): no COMMANDS entry references this topic
    "woolworths": 11,   # DEPRECATED (Phase 8 audit, 2026-08-24): no COMMANDS entry references this topic
    "nrma-giftcards": 12,   # DEPRECATED (Phase 8 audit, 2026-08-24): no COMMANDS entry references this topic
    "specials-wool": SPECIALS_WOOL_TOPIC_ID,    # D24: Wednesday specials report
    "weekly-lists": WEEKLY_LISTS_TOPIC_ID,      # D24: Wednesday summary + resolve lists
    # "grocery-sync-sheet" (151) RETIRED 2026-08-30 (D24): topic deleted by
    # the user after cutover. NO code may post to thread 151.
}

_ENV_OVERRIDE = {
    "specials-wool": "TELEGRAM_SPECIALS_TOPIC_ID",
    "weekly-lists": "TELEGRAM_WEEKLY_TOPIC_ID",
}


def thread_id_for(topic_key):
    """
    Returns the message_thread_id for a topic key, or None if unknown.

    Env overrides (A8) win over the table for the two D24 topics.

    Args:
        topic_key (str): Key from THREAD_IDS (e.g. "sysadmin").

    Returns:
        int | None: The thread ID, or None when the key is not mapped.
    """
    env_var = _ENV_OVERRIDE.get(topic_key)
    if env_var:
        raw = (os.environ.get(env_var) or "").strip()
        if raw.lstrip("-").isdigit():
            return int(raw)
    return THREAD_IDS.get(topic_key)
```
(`send_to_topic` already handles `None` gracefully — warning + 0 messages.)

### Step 5.2 — CLI constants + resolver + posting helpers (grocery_price_cli.py)

**Anchor A — replace the Telegram routing constants (current lines
975-978).**
**Search anchor (exact):**
```python
# Telegram routing (mirror telegram_gateway/topics.py + allowlist.py constants).
_TELEGRAM_CHAT_ID = -1004394070843
_TELEGRAM_THREAD_ID = 151  # grocery-sync-sheet topic
_TELEGRAM_USER_ID = 1594431983
```
**Replace with (exact):**
```python
# Telegram routing (mirror telegram_gateway/topics.py + allowlist.py constants).
_TELEGRAM_CHAT_ID = -1004394070843
# D24: 151 (grocery-sync-sheet) RETIRED — never post to it. The two new
# topics are filled from manual step M1; env overrides win (A8). Until
# then senders fall back to DM-only with a console note.
_SPECIALS_THREAD_ID = None   # specials-wool topic; env TELEGRAM_SPECIALS_TOPIC_ID
_WEEKLY_THREAD_ID = None     # weekly-lists topic; env TELEGRAM_WEEKLY_TOPIC_ID
_TELEGRAM_USER_ID = 1594431983


def _int_env(env_var: str, fallback):
    """Integer env override (A8): valid digits win, else the fallback.

    Args:
        env_var: environment variable name.
        fallback: int | None returned when the env var is unset/invalid.

    Returns:
        int | None
    """
    raw = (os.environ.get(env_var) or "").strip()
    if raw.lstrip("-").isdigit():
        return int(raw)
    return fallback
```

**Anchor B — after `_send_telegram` (current line 1016).** Insert:
```python
def _chunk_list_message(title: str, items: list, limit: int = 4000) -> list:
    """Build resolve-list message bodies, chunked to <= limit chars (A4).

    Args:
        title: list title (e.g. "Unmatched").
        items: item strings (may be empty).
        limit: max chars per message part.

    Returns:
        list[str]: message bodies; >1 part each carries "(part N/M)".
    """
    if not items:
        return [f"📋 {title}: none"]
    lines = [f"📋 {title} ({len(items)}):", ""]
    lines.extend(f"• {name}" for name in items)
    text = "\n".join(lines)
    parts = [text[i:i + limit] for i in range(0, len(text), limit)]
    total = len(parts)
    out = []
    for n, part in enumerate(parts, 1):
        suffix = f"\n(part {n}/{total})" if total > 1 else ""
        out.append(part + suffix)
    return out


def _post_weekly_summary(bot_token: str, summary_text: str,
                         resolve_lists: list) -> None:
    """Step 7 (D24): summary DM + weekly-lists; lists to weekly-lists only.

    resolve_lists: list of (title, items) tuples. Unset weekly topic ID ->
    DM-only with a console note (never posts, never crashes).
    """
    weekly_topic = _int_env("TELEGRAM_WEEKLY_TOPIC_ID", _WEEKLY_THREAD_ID)
    dm_ok = _send_telegram(bot_token, _TELEGRAM_USER_ID, summary_text)
    if weekly_topic is None:
        print("  weekly-lists topic ID unset — summary DM-only "
              "(set TELEGRAM_WEEKLY_TOPIC_ID or fill the M1 IDs)")
    else:
        topic_ok = _send_telegram(
            bot_token, _TELEGRAM_CHAT_ID, summary_text,
            message_thread_id=weekly_topic)
        print(f"  Weekly-lists topic: {'OK' if topic_ok else 'FAILED'}")
        for title, items in resolve_lists:
            bodies = _chunk_list_message(title, items)
            for body in bodies:
                _send_telegram(
                    bot_token, _TELEGRAM_CHAT_ID, body,
                    message_thread_id=weekly_topic)
            print(f"  {title} list → weekly-lists: "
                  f"{len(bodies)} message(s)")
    print(f"  DM: {'OK' if dm_ok else 'FAILED'}")


def _post_specials_report(bot_token: str, spec_text: str) -> None:
    """Step 8 (D24): specials report DM + specials-wool topic."""
    specials_topic = _int_env(
        "TELEGRAM_SPECIALS_TOPIC_ID", _SPECIALS_THREAD_ID)
    spec_dm = _send_telegram(bot_token, _TELEGRAM_USER_ID, spec_text)
    if specials_topic is None:
        print("  specials-wool topic ID unset — specials DM-only "
              "(set TELEGRAM_SPECIALS_TOPIC_ID or fill the M1 IDs)")
    else:
        spec_topic = _send_telegram(
            bot_token, _TELEGRAM_CHAT_ID, spec_text,
            message_thread_id=specials_topic)
        print(f"  Specials Topic: {'OK' if spec_topic else 'FAILED'}")
    print(f"  Specials DM: {'OK' if spec_dm else 'FAILED'}")
```

### Step 5.3 — Step 7 wiring (grocery_price_cli.py)

**Search anchor (exact, current lines 1540-1551):**
```python
        # Send to user DM + grocery-sync-sheet topic
        bot_token = os.environ.get("TELEGRAM_CLAW_BOT", "")
        if bot_token:
            dm_ok = _send_telegram(bot_token, _TELEGRAM_USER_ID, summary_text)
            topic_ok = _send_telegram(
                bot_token, _TELEGRAM_CHAT_ID, summary_text,
                message_thread_id=_TELEGRAM_THREAD_ID,
            )
            print(f"  DM: {'OK' if dm_ok else 'FAILED'}")
            print(f"  Topic: {'OK' if topic_ok else 'FAILED'}")
        else:
            print("  TELEGRAM_CLAW_BOT not set — skipping Telegram")
```
**Replace with (exact):**
```python
        # Send to user DM + weekly-lists topic; resolve lists to the topic
        bot_token = os.environ.get("TELEGRAM_CLAW_BOT", "")
        if bot_token:
            _post_weekly_summary(bot_token, summary_text, [
                ("Unmatched", unmatched_lines),
                ("Woolworths missing", wool_missing_lines),
                ("Coles missing", coles_missing_lines),
            ])
        else:
            print("  TELEGRAM_CLAW_BOT not set — skipping Telegram")
```

### Step 5.4 — Step 8 specials wiring (grocery_price_cli.py)

**Search anchor (exact, current lines 1615-1627):**
```python
            spec_text = "\n".join(spec_lines)
            bot_token = os.environ.get("TELEGRAM_CLAW_BOT", "")
            if bot_token:
                spec_dm = _send_telegram(
                    bot_token, _TELEGRAM_USER_ID, spec_text
                )
                spec_topic = _send_telegram(
                    bot_token, _TELEGRAM_CHAT_ID, spec_text,
                    message_thread_id=_TELEGRAM_THREAD_ID,
                )
                print(f"  Specials DM: {'OK' if spec_dm else 'FAILED'}")
                print(f"  Specials Topic: {'OK' if spec_topic else 'FAILED'}")
            else:
                print("  TELEGRAM_CLAW_BOT not set — skipping specials report")
```
**Replace with (exact):**
```python
            spec_text = "\n".join(spec_lines)
            bot_token = os.environ.get("TELEGRAM_CLAW_BOT", "")
            if bot_token:
                _post_specials_report(bot_token, spec_text)
            else:
                print("  TELEGRAM_CLAW_BOT not set — skipping specials report")
```

### Step 5.5 — `topics-check` subcommand (grocery_price_cli.py)

**Anchor A — handler.** Insert a new handler immediately BEFORE
`# ====== Handler: _cmd_map` (current line ~1728):
```python
# ============================================================================
# Handler: _cmd_topics_check — M1 helper (read-only, LOCAL machine only)
# ============================================================================

def _cmd_topics_check(args) -> int:
    """List forum topic names → thread IDs visible to the bot.

    Calls getUpdates ONCE and prints every forum-topic creation event
    (name → message_thread_id) plus every recent topic message
    (thread id · text head). Read-only: never posts. This is how the
    D24 topic IDs are discovered (M1 step 7).

    Args:
        args: parsed argparse Namespace (no options).

    Returns:
        int: 0 on success, 1 when the bot token is missing or the API
        call fails.
    """
    _load_env()
    bot_token = os.environ.get("TELEGRAM_CLAW_BOT", "")
    if not bot_token:
        print("Error: TELEGRAM_CLAW_BOT not set in env/.env",
              file=sys.stderr)
        return 1
    import json as _json
    import urllib.request as _req
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    try:
        with _req.urlopen(_req.Request(url), timeout=15) as resp:
            body = _json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        print(f"Error: getUpdates failed: {exc}", file=sys.stderr)
        return 1
    if not body.get("ok"):
        print(f"Error: getUpdates not ok: "
              f"{body.get('description', '')}", file=sys.stderr)
        return 1
    seen = set()
    found = 0
    for upd in body.get("result", []):
        msg = upd.get("message") or upd.get("edited_message") or {}
        thread_id = msg.get("message_thread_id")
        if thread_id is None:
            continue
        ftc = msg.get("forum_topic_created") or {}
        name = ftc.get("name")
        key = (thread_id, name or (msg.get("text") or "")[:40])
        if key in seen:
            continue
        seen.add(key)
        if name:
            print(f"{name} → {thread_id}")
        else:
            print(f"{thread_id} · {(msg.get('text') or '')[:40]}")
        found += 1
    if not found:
        print("No topic messages visible. Send '@ClawArkindBot id' in "
              "each topic, then re-run.")
    return 0
```

**Anchor B — parser registration.** In `build_parser`, after the `analyze`
block (after current line 200, before `return p`):
```python
    tch = sub.add_parser(
        "topics-check",
        help="List forum topic names → thread IDs (read-only, local)",
    )
    tch.set_defaults(func=_cmd_topics_check)
```

### Step 5.6 — wednesday_reminder.py: weekly topic + refreshed text

**File:** `<ROOT>\telegram_gateway\wednesday_reminder.py`

**Anchor A — constants (current lines 44-49).**
**Search anchor (exact):**
```python
CHAT_ID = -1004394070843
# "grocery-sync-sheet" topic (topics.py::THREAD_IDS), created for Phase 9 routing.
GROCERY_THREAD_ID = 151
```
**Replace with (exact):**
```python
CHAT_ID = -1004394070843
# D24: reminder posts to the weekly-lists topic (thread 151 RETIRED —
# never post to it). Placeholder until M1; env override wins (A8).
WEEKLY_THREAD_ID = None  # env: TELEGRAM_WEEKLY_TOPIC_ID
```

**Anchor B — add the resolver after `user_ids()` (after current
line 136):**
```python
def weekly_thread_id():
    """Returns the weekly-lists topic ID (env override wins; None=unset).

    Returns:
        int | None
    """
    raw = (os.environ.get("TELEGRAM_WEEKLY_TOPIC_ID") or "").strip()
    if raw.lstrip("-").isdigit():
        return int(raw)
    return WEEKLY_THREAD_ID
```

**Anchor C — `REMINDER_TEXT` (current lines 73-87).** Replace body:
```python
REMINDER_TEXT = (
    "📅 WEDNESDAY GROCERY SYNC\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "\n"
    "1. On the Windows machine, run the live Wednesday sync (one "
    "Chrome window, 2FA once) from the workspace root:\n"
    "    python grocery_price_cli.py wednesday --source live\n"
    "\n"
    "It logs in, flushes your queues, fetches both Price Compare "
    "lists, syncs the sheet, and posts the summary + resolve lists to "
    "#weekly-lists and the specials report to #specials-wool.\n"
    "\n"
    "Fallback: paste the lists into Woolworths.docx / Coles.docx and "
    "run plain `wednesday` (docx mode).\n"
    "\n"
    "No need to reply 'done'."
)
```

**Anchor D — `fire()` topic send (current lines 281-285).**
**Search anchor (exact):**
```python
    try:
        send_message(bot_token, CHAT_ID, REMINDER_TEXT, message_thread_id=GROCERY_THREAD_ID)
        results["topic"] = {"thread_id": GROCERY_THREAD_ID, "ok": True}
    except RuntimeError as exc:
        results["topic"] = {"thread_id": GROCERY_THREAD_ID, "ok": False, "error": str(exc)}
    return results
```
**Replace with (exact):**
```python
    tid = weekly_thread_id()
    if tid is None:
        # A8/P5c: unset ID -> DM-only with a note; never crash, never 151.
        print("weekly-lists topic ID unset — reminder DM-only "
              "(set TELEGRAM_WEEKLY_TOPIC_ID or fill the M1 IDs)")
        results["topic"] = {"thread_id": None, "ok": True, "skipped": True}
    else:
        try:
            send_message(bot_token, CHAT_ID, REMINDER_TEXT,
                         message_thread_id=tid)
            results["topic"] = {"thread_id": tid, "ok": True}
        except RuntimeError as exc:
            results["topic"] = {"thread_id": tid, "ok": False,
                                "error": str(exc)}
    return results
```
(Keep `all_ok` computation as-is — `skipped` rows are `ok: True`.)

### Step 5.7 — handlers.py: `handle_done` routing + current texts

**File:** `<ROOT>\telegram_gateway\handlers.py`

**Search anchor (exact, current lines 256-269):**
```python
    reply(
        bot_url,
        update,
        "Thanks — Wednesday grocery sync acknowledged. "
        "The local pipeline (name_importer -> local_sync) will process your "
        "Word docs and update the sheet. Watch the #grocery-sync-sheet topic.",
    )
    send_to_topic(
        bot_url,
        "grocery-sync-sheet",
        "<b>Wednesday sync requested</b>\n"
        "User replied 'done' — Word docs are ready. "
        "Awaiting local pipeline run (name_importer -> local_sync -> sheet update).",
    )
    return True
```
**Replace with (exact):**
```python
    reply(
        bot_url,
        update,
        "Thanks — Wednesday grocery sync acknowledged. "
        "The Wednesday live pipeline (wednesday --source live) will post "
        "the summary and resolve lists to #weekly-lists and the specials "
        "report to #specials-wool.",
    )
    send_to_topic(
        bot_url,
        "weekly-lists",
        "<b>Wednesday sync requested</b>\n"
        "User replied 'done' — awaiting the Wednesday live pipeline run "
        "(wednesday --source live → summary + resolve lists in "
        "#weekly-lists, specials in #specials-wool).",
    )
    return True
```
Also update the `handle_done` docstring's "grocery-sync-sheet topic"
mentions to "weekly-lists topic". No handler removal; `name_importer` /
`local_sync` references in this function are replaced by the wording above.

### Step 5.8 — WP5 tests (test_cli.py additions)

Append to `<ROOT>\grocery-price-tracker\tests\test_cli.py`:

```python
class TestTopicSplit(unittest.TestCase):
    """D24/WP5: routing, chunking, fallback, topics-check, reminder."""

    def setUp(self):
        import grocery_price_cli as gpc
        self.gpc = gpc
        self._env = {}
        self._env_patch = patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
        for var in ("TELEGRAM_WEEKLY_TOPIC_ID",
                    "TELEGRAM_SPECIALS_TOPIC_ID"):
            os.environ.pop(var, None)

    def test_int_env_matrix(self):
        gpc = self.gpc
        with patch.dict(os.environ, {"TELEGRAM_WEEKLY_TOPIC_ID": "777"}):
            self.assertEqual(
                gpc._int_env("TELEGRAM_WEEKLY_TOPIC_ID", None), 777)
        self.assertIsNone(gpc._int_env("TELEGRAM_WEEKLY_TOPIC_ID", None))
        with patch.dict(os.environ, {"TELEGRAM_WEEKLY_TOPIC_ID": "abc"}):
            self.assertEqual(
                gpc._int_env("TELEGRAM_WEEKLY_TOPIC_ID", 5), 5)

    def test_chunk_list_message(self):
        gpc = self.gpc
        self.assertEqual(gpc._chunk_list_message("Unmatched", []),
                         ["📋 Unmatched: none"])
        one = gpc._chunk_list_message("Unmatched", ["milk"])
        self.assertEqual(len(one), 1)
        self.assertIn("• milk", one[0])
        big = gpc._chunk_list_message(
            "Woolworths missing", [f"item {i} " * 8 for i in range(600)])
        self.assertGreater(len(big), 1)
        for n, part in enumerate(big, 1):
            self.assertLessEqual(len(part), 4000)
            self.assertIn(f"(part {n}/{len(big)})", part)

    def _posted(self, calls):
        return [
            (c.kwargs.get("message_thread_id"), c.args[1])
            for c in calls
        ]

    def test_post_weekly_summary_routes_to_weekly_topic_never_151(self):
        gpc = self.gpc
        calls = []
        with patch.dict(os.environ,
                        {"TELEGRAM_WEEKLY_TOPIC_ID": "777"}), \
             patch.object(gpc, "_send_telegram",
                          side_effect=lambda *a, **k: calls.append(
                              _Call(a, k)) or True):
            gpc._post_weekly_summary("tok", "summary", [
                ("Unmatched", ["a"]), ("Woolworths missing", []),
                ("Coles missing", ["b", "c"]),
            ])
        threads = [c.thread for c in calls]
        self.assertIn(777, threads)
        self.assertNotIn(151, threads)
        dm = [c for c in calls if c.chat == gpc._TELEGRAM_USER_ID]
        self.assertEqual(len(dm), 1)  # DMs keep exactly the summary

    def test_post_specials_routes_to_specials_topic_never_151(self):
        gpc = self.gpc
        calls = []
        with patch.dict(os.environ,
                        {"TELEGRAM_SPECIALS_TOPIC_ID": "888"}), \
             patch.object(gpc, "_send_telegram",
                          side_effect=lambda *a, **k: calls.append(
                              _Call(a, k)) or True):
            gpc._post_specials_report("tok", "specials text")
        threads = [c.thread for c in calls]
        self.assertIn(888, threads)
        self.assertNotIn(151, threads)

    def test_unset_ids_fall_back_to_dm_only(self):
        gpc = self.gpc
        calls = []
        with patch.object(gpc, "_send_telegram",
                          side_effect=lambda *a, **k: calls.append(
                              _Call(a, k)) or True):
            gpc._post_weekly_summary("tok", "summary", [("Unmatched", [])])
            gpc._post_specials_report("tok", "spec")
        for c in calls:
            self.assertIsNone(c.thread)
            self.assertEqual(c.chat, gpc._TELEGRAM_USER_ID)


class _Call:
    """Tiny record of one _send_telegram invocation."""

    def __init__(self, args, kwargs):
        self.args = args
        self.kwargs = kwargs
        self.chat = args[1]
        self.thread = kwargs.get("message_thread_id")


class TestTopicsCheck(unittest.TestCase):
    """WP5: topics-check parses a mocked getUpdates payload."""

    def test_parses_topic_creation_and_messages(self):
        import grocery_price_cli as gpc
        payload = {
            "ok": True,
            "result": [
                {"message": {
                    "message_thread_id": 543,
                    "forum_topic_created": {"name": "specials-wool"},
                    "text": "",
                }},
                {"message": {
                    "message_thread_id": 544,
                    "text": "@ClawArkindBot id",
                }},
            ],
        }
        fake_resp = SimpleNamespace(
            read=lambda: json.dumps(payload).encode("utf-8"),
            __enter__=lambda s: s,
            __exit__=lambda s, *a: None,
        )
        with patch("urllib.request.urlopen", return_value=fake_resp), \
             patch.dict(os.environ, {"TELEGRAM_CLAW_BOT": "tok"}):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = gpc._cmd_topics_check(argparse.Namespace())
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("specials-wool → 543", out)
        self.assertIn("544 · @ClawArkindBot id", out)


class TestWednesdayReminderRouting(unittest.TestCase):
    """WP5: reminder routes to the weekly ID via env/patchable constant."""

    _PATH = Path(__file__).resolve().parents[2] / \
        "telegram_gateway" / "wednesday_reminder.py"

    def _load(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "wednesday_reminder_test", str(self._PATH))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_env_override_routes_topic(self):
        mod = self._load()
        sent = []

        def fake_send(token, chat_id, text, message_thread_id=None):
            sent.append((chat_id, message_thread_id))

        with patch.dict(os.environ,
                        {"TELEGRAM_WEEKLY_TOPIC_ID": "777"}), \
             patch.object(mod, "send_message", fake_send), \
             patch.object(mod, "user_ids", lambda: [1]):
            mod.fire("tok")
        topic_calls = [c for c in sent if c[0] == mod.CHAT_ID]
        self.assertEqual(topic_calls, [(mod.CHAT_ID, 777)])

    def test_unset_id_dm_only_no_crash(self):
        mod = self._load()
        sent = []

        def fake_send(token, chat_id, text, message_thread_id=None):
            sent.append((chat_id, message_thread_id))

        os.environ.pop("TELEGRAM_WEEKLY_TOPIC_ID", None)
        with patch.object(mod, "WEEKLY_THREAD_ID", None), \
             patch.object(mod, "send_message", fake_send), \
             patch.object(mod, "user_ids", lambda: [1]):
            results = mod.fire("tok")
        self.assertEqual(
            [c for c in sent if c[0] == mod.CHAT_ID], [])
        self.assertTrue(results["topic"]["skipped"])
```
Add `import contextlib` to test_cli.py's imports. Audit test_cli.py for any
reference to `_TELEGRAM_THREAD_ID` / 151 and update to the new constants.

**Verification (mandatory):**
```powershell
& "$env:USERPROFILE\anaconda3\python.exe" -m py_compile grocery_price_cli.py telegram_gateway\topics.py telegram_gateway\wednesday_reminder.py telegram_gateway\handlers.py
& "$env:USERPROFILE\anaconda3\python.exe" -m pytest grocery-price-tracker\tests\test_cli.py -q
```

### Step 5.9 — M1-gated constant fill (AFTER manual step M1 only)

When the user reports the two IDs (e.g. `specials-wool → 543`,
`weekly-lists → 544`), fill the four placeholders with the REAL integers —
and nothing else changes:
1. `telegram_gateway/topics.py`: `SPECIALS_WOOL_TOPIC_ID = <id>`,
   `WEEKLY_LISTS_TOPIC_ID = <id>`.
2. `grocery_price_cli.py`: `_SPECIALS_THREAD_ID = <id>`,
   `_WEEKLY_THREAD_ID = <id>`.
3. `telegram_gateway/wednesday_reminder.py`: `WEEKLY_THREAD_ID = <id>`.
4. `Development Workflow\TELEGRAM_TOPICS.md`: both topics + IDs, and the
   151 RETIRED record (see Step 6.1).
Re-run the WP5 tests + full suite after the fill (env unset in tests → the
constants are exercised).

---

## 6. Documentation

### Step 6.1 — TELEGRAM_TOPICS.md

**File:** `<ROOT>\Development Workflow\TELEGRAM_TOPICS.md`
Add to the Thread IDs list:
```
specials-wool: <ID — filled after M1>
weekly-lists: <ID — filled after M1>
```
Add to Notes:
```
- D24 (2026-08-30): Wednesday output split — specials report →
  `specials-wool`, summary + resolve lists → `weekly-lists`. IDs verified
  via `python grocery_price_cli.py topics-check` (M1).
- `grocery-sync-sheet` (151) RETIRED 2026-08-30: topic deleted by the user
  after cutover; no code may post to thread 151.
```

### Step 6.2 — SKILL.md (WP5 rows + D25 vocabulary)

**File:** `<ROOT>\claw-skills\grocery-price\SKILL.md`
1. NL mapping table (after the live-refresh row, line ~152):
```
| "check telegram topics" / "list topic ids" | **Local-only:** tell the user to run `topics-check` on the Windows machine |
```
2. Sheet-semantics section (near "The Google Sheet ALWAYS stores **raw**
prices", line ~70), add:
```
- Sheet specials columns M/N hold exactly one of `no` / `discount` /
  `multi-buy` (D25). Legacy free-text cells still report as a special.
```

### Step 6.3 — README.md

**File:** `<ROOT>\grocery-price-tracker\README.md` — add a "D23–D27 +
B4/B5 completion (2026-08-30)" section documenting: compare/recipe
add-reminder (D23); Wednesday topic split `specials-wool` / `weekly-lists`
with 151 retired + `topics-check` helper (D24); M/N vocabulary
`no`/`discount`/`multi-buy` + Coles `Was`/`Any N | $X`/`SPECIAL` docx
markers (D25); real discovery recording + auto-discovery + per-store flush
isolation + `Discovery: captured/failed` status (D26/D27); Scrape.do retries
5xx/timeout only (B4) and the SKILL.md never-browse rule (B5). Do NOT
create or reference `PROJECT-MAP.md` (spec §5 note).

---

## 7. Deployment (automated — standing user directive 2026-08-29)

All automated; Local Terminal unless marked **Remote VPS**. Perform only
after the full suite is green.

1. **Sync changed files to the VPS** (mirrors `tasks/ai-tools/`):
```powershell
scp "grocery_price_cli.py" "ubuntu@169.58.107.0:/home/ubuntu/openclaw/tasks/ai-tools/grocery_price_cli.py"
scp "telegram_gateway/topics.py" "telegram_gateway/wednesday_reminder.py" "telegram_gateway/handlers.py" "ubuntu@169.58.107.0:/home/ubuntu/openclaw/tasks/ai-tools/telegram_gateway/"
scp "grocery-price-tracker/core/price_comparator.py" "grocery-price-tracker/core/sheets_sync.py" "grocery-price-tracker/core/specials_reporter.py" "ubuntu@169.58.107.0:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/core/"
scp "grocery-price-tracker/extractors/specials_parser.py" "grocery-price-tracker/extractors/doc_parser.py" "grocery-price-tracker/extractors/coles_extractor.py" "grocery-price-tracker/extractors/session_refresh.py" "ubuntu@169.58.107.0:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/extractors/"
scp "claw-skills/grocery-price/SKILL.md" "ubuntu@169.58.107.0:/home/ubuntu/openclaw/tasks/ai-tools/claw-skills/grocery/SKILL.md"
```
2. **Restart the gateway container** — **Remote VPS**:
```bash
ssh ubuntu@169.58.107.0 "docker restart openclaw-core"
```
3. **Post-deploy smoke check** (VPS, read-only):
```bash
ssh ubuntu@169.58.107.0 "cd /home/ubuntu/openclaw/tasks/ai-tools && python3 -m py_compile grocery_price_cli.py telegram_gateway/topics.py telegram_gateway/wednesday_reminder.py telegram_gateway/handlers.py grocery-price-tracker/core/price_comparator.py"
```
4. Git commits (each repo, concise messages matching repo style; inspect
   `git status` / `git diff` first; never commit secrets):
   - `grocery-price-tracker/`: WP1–WP4 code + tests + README.
   - `<ROOT>` siblings (`grocery_price_cli.py`, `telegram_gateway/`,
     `claw-skills/`, `Development Workflow/`): WP2/WP3/WP5 changes.
   Test files do NOT need VPS sync for pytest (VPS has no pytest) but sync
   them anyway per §9 housekeeping so the deployed tree is not stale:
   add `grocery-price-tracker/tests/` changed files to step 1.

---

## 8. Manual user steps (NOT automatable — external human actions)

- **M1 — create the two topics + report IDs** (before Step 5.9): follow
  architecture-spec §6 M1 verbatim (Telegram Desktop → Claw Command Center →
  ⊕ Create Topic `specials-wool`, repeat `weekly-lists`; send
  `@ClawArkindBot id` in each; run
  `python grocery_price_cli.py topics-check` locally; report the two
  numbers). 03 Code then executes Step 5.9.
- **M2 — after cutover:** delete the old "Grocery: Sync & Sheet" topic in
  Telegram (the system no longer posts to it).
- **M3 — D26 acceptance (user present, once):** run
  `python grocery_price_cli.py live-refresh --recapture` locally; add ONE
  item to the "Price Compare" list per store; summary must print
  `Discovery: captured` for both stores; next flush must succeed. Any
  `failed` line carries its recovery command.

---

## 9. Verification matrix (ALL mandatory; zero skips; no network)

Per-step commands are in §§1-5. Program-level gates:

| Gate | Command (Local Terminal, `<ROOT>`) | Expectation |
|------|------------------------------------|-------------|
| Compile | `& "$env:USERPROFILE\anaconda3\python.exe" -m py_compile <every edited .py>` | exit 0 |
| WP1 | `... -m pytest grocery-price-tracker\tests\test_comparator.py -q` | all pass |
| WP2 | `... -m pytest grocery-price-tracker\tests\test_coles_recipe.py -q` | all pass |
| WP3 | `... -m pytest grocery-price-tracker\tests\test_specials_flags.py grocery-price-tracker\tests\test_sheets_sync.py -q` | all pass |
| WP4 | `... -m pytest grocery-price-tracker\tests\test_live_window.py grocery-price-tracker\tests\test_cli.py -q` | all pass |
| WP5 | `... -m pytest grocery-price-tracker\tests\test_cli.py -q` | all pass |
| Full regression | `... -m pytest grocery-price-tracker\tests -q` | **0 failed**, count ≥ 446 + new; any failure is a regression to fix |
| No-151 grep | `rg -n "151" grocery_price_cli.py telegram_gateway\topics.py telegram_gateway\wednesday_reminder.py telegram_gateway\handlers.py` | only comments mention 151; no routing constant |
| Local run smoke (optional, read-only) | `... grocery_price_cli.py --help` | `topics-check` listed |

Acceptance (spec §7): all suites green locally with Anaconda Python; M1/M3
succeed; first live Wednesday after cutover posts summary + resolve lists to
`weekly-lists` and specials to `specials-wool`, nothing to 151.

---

## 10. Boundaries (spec §5 — hard)

- **Must NOT touch:** `core/lookup.py`, `core/uom.py`, `core/searched_items.py`,
  `core/add_to_list.py`, `core/missing_items_tracker.py`,
  `core/name_matcher.py`, `core/telegram_format.py`,
  `core/woolworths_discounts.py`, `core/schema_upgrade.py`,
  `extractors/woolworths_extractor.py`, `extractors/live_list_fetch.py`,
  `extractors/models.py`, any `.docx`, `.env`,
  `telegram_gateway/bot.py`/`commands.py`/`budget_sheets.py`/`allowlist.py`,
  `scripts/session_heartbeat_entry.py`, docx name/price matching semantics,
  and everything in spec §2 (regression-protect only).
- **No new files except** `grocery-price-tracker/tests/test_specials_flags.py`
  and `implementation-plan.md` (this doc). **No new dependencies.** No data
  migrations. **Never post to thread 151. Never invent topic IDs.**
- Revert guarantee: WP1/WP3/WP4 are additive or call-site-level; WP5 reverts
  by restoring the single 151 constant pair; WP2 reverts to the previous
  retry branch.
