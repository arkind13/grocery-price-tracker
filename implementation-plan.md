# Implementation Plan — Units Always Visible (Col C = the single unit source)

- **Date:** 2026-09-01
- **Pipeline stage:** 02 Plan (this doc) → 03 Code → 04 Architect Checker
- **Source spec:** `grocery-price-tracker/architecture-spec.md` (LOCKED,
  user-confirmed 2026-09-01). Rules A/B/C and decisions D-U1…D-U4 are
  BINDING. 03 Code executes this plan literally; do not re-litigate.
- **Baseline:** full suite **504 passed / 0 failed / 0 skipped**
  (`test.md` closeout 2026-08-31, independently re-verified twice).
  Regression bar: full suite green, 0 failed, 0 skipped, count ≥ 504
  + new tests.
- **Python:** Anaconda interpreter only. `python` is NOT on PATH. In
  PowerShell always invoke as `& "$env:USERPROFILE\anaconda3\python.exe"`
  (shorthand `$PY` below). **Never `pip install`** — stdlib + existing
  deps only; this cycle adds ZERO new dependencies.
- **Working directory for ALL commands (Local Terminal):**
  `C:\Users\User.DESKTOP-R2G441H\Documents\AI related` (referred to as
  `<ROOT>`). Tests bootstrap `sys.path` themselves, so pytest resolves
  both `grocery-price-tracker` and the sibling `grocery_price_cli.py`.
- **Command shorthand:** `$PY = & "$env:USERPROFILE\anaconda3\python.exe"`.

---

## 0. Repo layout + the CLI location mismatch (spec §7 NOTE — binding)

```
<ROOT>/                                        ← working dir for ALL commands
├── grocery_price_cli.py                       ← IN SCOPE, lives OUTSIDE the
│                                                 repo root (3201 lines today)
├── telegram_gateway/                          ← frozen (separate repo)
└── grocery-price-tracker/                     ← the git repo
    ├── architecture-spec.md                   ← binding spec
    ├── implementation-plan.md                 ← THIS FILE (overwrites prior cycle)
    ├── core/                                  ← telegram_format, price_comparator,
    │                                             sheets_sync, searched_items,
    │                                             add_to_list, missing_items_tracker,
    │                                             specials_reporter (all in scope)
    ├── extractors/                            ← frozen (already return .size)
    ├── tests/                                 ← all test files in scope
    └── data/                                  ← JSON queues (runtime)
```

**Mismatch flag (spec §7 NOTE):** `deploy_vps.py:45` expects
`grocery_price_cli.py` in the repo root, but the file lives at `<ROOT>`.
This cycle modifies it AT ITS CURRENT PATH ONLY (README §9 "pending
migration" zone). The repo root has NO copy today (verified by glob).
Deploy implication is recorded in §7 (Ops) — no copy is made as part of
the code steps.

**Frozen (MUST NOT modify — spec §7):** `core/uom.py`, `core/lookup.py`
(verify-only), `core/extractors/*`, `core/name_matcher.py`, sheet schema,
`.env` handling, `telegram_gateway/`, `app.py`, `local_sync.py`.

---

## 1. Plan-level resolutions (spec-silent points; binding for 03 Code)

| # | Question | Resolution |
|---|----------|------------|
| P1 | How does `item_block` know a caller wants no unit segment (search flow shows units on store lines, A1)? | `item_block(..., unit: str \| None = None)`. `None` (default) → NO segment appended (legacy callers unchanged). ANY string — including `""` — appends `unit_suffix(unit)` AFTER truncation. The comparator (A3) ALWAYS passes a string, so compare titles always show unit or marker. |
| P2 | A2 says ` — <name> <unit_tag> (<source>)` — with ⚠️? | No. A2's formula uses plain `unit_tag` (no ⚠️, no `·`). The ` · ⚠️ unit unavailable` form (spec §3 formatting rule) applies to the inline ` · `-separated surfaces: A1, A4, A5, A6, A7, A8, A9 and the A3 title tag. |
| P3 | Non-interactive add with no resolvable unit: fail fast — but how does the user ever supply the unit one-shot? | NEW optional `--unit UNIT` flag on BOTH `search` and `map` parsers (mechanism behind the spec's error text "pass a size or the marker"). Interactive TTY sessions get the ask-once prompt (D-U4) instead; Claw relays the question when it sees the fail-fast error, then re-runs with `--unit`. |
| P4 | B6 wants missing-queue entries to copy size from the source store's sheet row, but `MatchResult` has no size field and `core/name_matcher.py` is frozen. | `update_missing_items(..., *, sizes_by_generic: dict \| None = None)`. Callers pass `{generic_name: Col C value}` built from the sheet. New entries get `"size"` (may be `""`, which displays as the note). No migration of old entries (read-as-blank per spec §2). |
| P5 | A9: the Wednesday txt files (`unmatched.txt`, `wool_missing.txt`, `coles_missing.txt`) are MACHINE-parsed by the `map` flows — appending units there would corrupt `map wool`/`map coles` searches. | txt files keep their exact current line format. Units are appended ONLY on the Telegram resolve-list display lines (parallel `*_display` lists passed to `_post_weekly_summary`). This is the single correctness trap of A9; do not "simplify" it. |
| P6 | Queue `add_entry` defaults when the caller passes no size. | Blank → canonical marker normalization INSIDE `add_entry` (entries ALWAYS carry `"size"`). Fail-fast applies only to `add_product_row` (sheet writes), exactly as spec B1 states. |
| P7 | A7 scope. | `format_specials_report` sheet lines + the `_cmd_specials` live saved-list block. `get_active_specials` dicts gain a `"size"` key (read Col C). The separate `rewards` report is NOT in spec A7's anchor list — untouched. |
| P8 | Marker case-insensitivity. | `unit_tag` treats the marker phrase case-insensitively as input; the OUTPUT marker is always exact lowercase `unit unavailable` (spec §2). |

---

## 2. Data contract (spec §2 — implemented once, in S1)

| Item | Value |
|---|---|
| Canonical marker | `unit unavailable` (exact lowercase) |
| `core/telegram_format.py : UNIT_UNAVAILABLE` | `str` constant |
| `core/telegram_format.py : unit_tag(size: str \| None) -> str` | trimmed size, or marker when blank/whitespace/marker |
| `core/telegram_format.py : unit_suffix(size: str \| None) -> str` | `" · 1L"` or `" · ⚠️ unit unavailable"` (single composition over `unit_tag`) |
| Col C states | real size = known; marker = assessed-unknown; blank = legacy (displays identically to marker) |
| UOM gate | UNCHANGED — verified in S0.2: `parse_size("unit unavailable") is None` |
| Sheet column constant | `core/sheets_sync.py : SIZE_COL = 2` (Col C, 0-based) |

---

## 3. Build order (fixed)

```
S0 baseline → S1 → S2 (foundation)
→ S3 → S4 → S5 → S6 → S7 → S8 (Rule A display)
→ S9 → S10 → S11 → S12 → S13 → S14 → S15 → S16 (Rule B writes + A9)
→ S17 (Rule C heal) → S18 (docs) → S19 (closeout verification)
```

Each step: 1–2 files, ≤ 50 modified lines, its own mandatory tests and
deterministic verify command. If a verify fails, FIX BEFORE MOVING ON.
Never batch steps.

**Edit mechanics for 03 Code:** the ANCHOR blocks below are quoted from
the 2026-09-01 file state. Line numbers are informational — they DRIFT as
edits land. Always locate edits by the quoted anchor TEXT (unique in
file), not by line number. After each edit, run the step's verify command.

---

## S0 — Baseline (no modifications)

**S0.1 Full suite green.**
```powershell
$PY = & "$env:USERPROFILE\anaconda3\python.exe"
$PY -m pytest grocery-price-tracker/tests/ -q
```
Expected: `504 passed`, 0 failed, 0 skipped. Record the number.

**S0.2 UOM gate invariant (spec §2, frozen).**
```powershell
$PY -c "import sys; sys.path.insert(0, 'grocery-price-tracker'); from core.uom import parse_size; assert parse_size('unit unavailable') is None; print('gate-ok')"
```
Expected stdout: `gate-ok`.

**S0.3 Both entry files compile.**
```powershell
$PY -m py_compile grocery_price_cli.py; $PY -m py_compile grocery-price-tracker/core/telegram_format.py
```
Expected: no output, exit 0.

---

## S1 — Foundation: `UNIT_UNAVAILABLE`, `unit_tag`, `unit_suffix`

**Files:** `grocery-price-tracker/core/telegram_format.py` (edit),
`grocery-price-tracker/tests/test_telegram_format.py` (append tests).

**Edit 1 — insert after the `kv()` function (anchor: the full `kv` block
ending `return f"{label} {SEP} {value}"`):**

```python
# Canonical Col C marker for "unit assessed, unknown" (architecture-spec
# §2 — the user's own words, exact lowercase phrase). Blank Col C means
# "legacy, not yet assessed"; both DISPLAY identically via unit_tag().
UNIT_UNAVAILABLE = "unit unavailable"


def unit_tag(size: str | None) -> str:
    """Return the display text for a package size (Rule A, spec §2).

    Args:
        size: raw size string (Col C value, live listing size, or a
            queue entry's "size" key). None-safe.

    Returns:
        str: the trimmed size when one is known; else the canonical
        marker "unit unavailable". Blank, whitespace-only, and the
        marker itself (any case) all map to the marker.
    """
    text = str(size or "").strip()
    if not text or text.lower() == UNIT_UNAVAILABLE:
        return UNIT_UNAVAILABLE
    return text


def unit_suffix(size: str | None) -> str:
    """Return the inline unit segment for a product-mention line.

    Single composition over unit_tag (DRY — one source for the marker).

    Args:
        size: raw size string (None-safe).

    Returns:
        str: " · 1L" for a known size; " · ⚠️ unit unavailable" for an
        unknown one (spec §3 formatting rule — silent omission banned).
    """
    if unit_tag(size) == UNIT_UNAVAILABLE:
        return f" {SEP} ⚠️ {UNIT_UNAVAILABLE}"
    return f" {SEP} {unit_tag(size)}"
```

**Tests — append to `tests/test_telegram_format.py` (new class after
`TestHeaderAndDividers`):**

```python
class TestUnitTag(unittest.TestCase):
    """unit_tag / unit_suffix — the Rule A data contract (spec §2)."""

    def test_unit_tag_real_sizes_pass_through_trimmed(self):
        self.assertEqual(tf.unit_tag("1L"), "1L")
        self.assertEqual(tf.unit_tag("  250g "), "250g")
        self.assertEqual(tf.unit_tag("6 x 170g"), "6 x 170g")

    def test_unit_tag_empty_none_and_marker_map_to_marker(self):
        for raw in ("", "   ", None, "unit unavailable",
                    "Unit Unavailable", "UNIT UNAVAILABLE"):
            self.assertEqual(tf.unit_tag(raw), "unit unavailable")

    def test_unit_suffix_known_and_unknown_exact_strings(self):
        self.assertEqual(tf.unit_suffix("1L"), " · 1L")
        self.assertEqual(tf.unit_suffix(""), " · ⚠️ unit unavailable")
        self.assertEqual(tf.unit_suffix(None), " · ⚠️ unit unavailable")

    def test_unit_suffix_marker_input_shows_warning_note(self):
        self.assertEqual(
            tf.unit_suffix("unit unavailable"),
            " · ⚠️ unit unavailable",
        )
```

**Verify:**
```powershell
$PY -m pytest grocery-price-tracker/tests/test_telegram_format.py -q
$PY -m py_compile grocery-price-tracker/core/telegram_format.py
```

---

## S2 — `item_block` gains the `unit` param (A3 groundwork)

**Files:** `grocery-price-tracker/core/telegram_format.py` (edit),
`grocery-price-tracker/tests/test_telegram_format.py` (append tests).

**Edit — replace the `item_block` signature + body head. ANCHOR (old):**

```python
def item_block(
    index: int,
    name: str,
    prices: list[str],
    home_brand: bool = False,
) -> str:
    """Build one numbered list-style item with indented store lines.

    Args:
        index: 1-based item number.
        name: product name (truncated to MAX_NAME_WIDTH cells).
        prices: pre-rendered store_line() strings, one per store.
        home_brand: append the 🏠 Woolworths home-brand marker.

    Returns:
        str: multi-line block, e.g.
        "2. Full Cream Milk 2L  🏠\\n   🟢 Woolworths  $3.32".
    """
    title = truncate(str(name or ""), MAX_NAME_WIDTH)
    first = f"{index}. {title}"
    if home_brand:
        first += "  🏠"
    lines = [first]
```

**NEW:**

```python
def item_block(
    index: int,
    name: str,
    prices: list[str],
    home_brand: bool = False,
    unit: str | None = None,
) -> str:
    """Build one numbered list-style item with indented store lines.

    Args:
        index: 1-based item number.
        name: product name (truncated to MAX_NAME_WIDTH cells).
        prices: pre-rendered store_line() strings, one per store.
        home_brand: append the 🏠 Woolworths home-brand marker.
        unit: package size for the unit tag (Rule A, spec A3/D-U2).
            None = caller manages units elsewhere (NO segment appended);
            any string — including "" — appends unit_suffix(unit) AFTER
            truncation so the tag is never cut off.

    Returns:
        str: multi-line block, e.g.
        "2. Full Cream Milk 2L  🏠 · 1L\\n   🟢 Woolworths  $3.32".
    """
    title = truncate(str(name or ""), MAX_NAME_WIDTH)
    first = f"{index}. {title}"
    if home_brand:
        first += "  🏠"
    if unit is not None:
        first += unit_suffix(unit)
    lines = [first]
```

**Tests — append:**

```python
class TestItemBlockUnit(unittest.TestCase):
    """item_block unit param — appended after truncation (A3/D-U2)."""

    def test_unit_appended_after_truncation_never_cut(self):
        long_name = "Full Cream Milk Chocolate Organic Supreme"  # > 24 cells
        block = tf.item_block(1, long_name, [], unit="200g")
        first_line = block.split("\n")[0]
        self.assertTrue(first_line.endswith(" · 200g"))
        self.assertIn("…", first_line)  # name was truncated, unit was not

    def test_unit_empty_string_shows_marker_note(self):
        block = tf.item_block(2, "Milk", [], unit="")
        self.assertIn(" · ⚠️ unit unavailable", block.split("\n")[0])

    def test_unit_none_appends_nothing(self):
        self.assertEqual(
            tf.item_block(3, "Milk", []).split("\n")[0], "3. Milk")
```

**Verify:**
```powershell
$PY -m pytest grocery-price-tracker/tests/test_telegram_format.py -q
```

---

## S3 — A2: `_identity_suffix` size segment ALWAYS present

**Files:** `grocery-price-tracker/core/price_comparator.py` (edit),
`grocery-price-tracker/tests/test_comparator.py` (append + update).

**Edit — replace the whole `_identity_suffix` body. ANCHOR (old):**

```python
    matched_name = item.matched_names.get(store, "")
    if not matched_name:
        return ""
    size = item.matched_sizes.get(store, "")
    source = item.sources.get(store, "sheet")
    if size:
        return f" — {matched_name} {size} ({source})"
    return f" — {matched_name} ({source})"
```

**NEW:**

```python
    from core.telegram_format import unit_tag
    matched_name = item.matched_names.get(store, "")
    if not matched_name:
        return ""
    # Rule A: the size segment is ALWAYS present — real size or the
    # explicit marker (plain text here; the ⚠️ form is reserved for
    # the ·-separated surfaces, spec §3 / plan P2).
    size = unit_tag(item.matched_sizes.get(store, ""))
    source = item.sources.get(store, "sheet")
    return f" — {matched_name} {size} ({source})"
```

Also update the function docstring line `The size segment is omitted
when the matched product has no size.` → `The size segment is ALWAYS
present (Rule A): real size via unit_tag, else "unit unavailable".`

**Existing-test update (mandatory):** grep the file for
`_identity_suffix` and for exact suffix strings like
`f" — {name} ({source})"` expectations — every no-size branch assertion
gains ` unit unavailable` before ` ({source})`.
```
Grep pattern "_identity_suffix|unit unavailable" in tests/test_comparator.py
```

**Tests — append:**

```python
class TestIdentitySuffixAlwaysUnit(unittest.TestCase):
    """A2: the size segment is always present (Rule A)."""

    def _item(self, sizes, names=None):
        from core.price_comparator import BasketItem
        return BasketItem(
            name="milk",
            prices={"woolworths": 3.0, "coles": 3.5},
            sources={"woolworths": "sheet", "coles": "sheet"},
            matched_names=names or {
                "woolworths": "Milk 1L", "coles": "Milk 1L"},
            matched_sizes=sizes,
        )

    def test_size_present_when_known(self):
        from core.price_comparator import _identity_suffix
        suffix = _identity_suffix(self._item({"woolworths": "1L"}),
                                  "woolworths")
        self.assertEqual(suffix, " — Milk 1L 1L (sheet)")

    def test_marker_present_when_missing(self):
        from core.price_comparator import _identity_suffix
        suffix = _identity_suffix(self._item({}), "woolworths")
        self.assertEqual(suffix, " — Milk 1L unit unavailable (sheet)")

    def test_empty_when_no_matched_name(self):
        from core.price_comparator import _identity_suffix
        suffix = _identity_suffix(self._item({}, names={}), "woolworths")
        self.assertEqual(suffix, "")
```

(Note: R3 accepted — names that embed the size may show it twice.)

**Verify:**
```powershell
$PY -m pytest grocery-price-tracker/tests/test_comparator.py -q
```

---

## S4 — A3 + A4: compare title tag + found-block size

**Files:** `grocery-price-tracker/core/price_comparator.py` (edit),
`grocery-price-tracker/tests/test_comparator.py` (append + update).

**Edit 1 (A4) — `_found_block_lines` store line. ANCHOR (old):**

```python
    from core.telegram_format import warn
    lines = [warn("No matching product — sizes don't compare.")]
    for store in ("woolworths", "coles"):
        found = item.closest.get(store)
        if not found:
            continue
        label = _FOUND_LABELS.get(store, f"{store.capitalize()}:")
        pad = " " * max(0, _FOUND_LABEL_WIDTH - len(label))
        lines.append(f"   {label}{pad}{found.get('name', '')}")
```

**NEW:**

```python
    from core.telegram_format import unit_suffix, warn
    lines = [warn("No matching product — sizes don't compare.")]
    for store in ("woolworths", "coles"):
        found = item.closest.get(store)
        if not found:
            continue
        label = _FOUND_LABELS.get(store, f"{store.capitalize()}:")
        pad = " " * max(0, _FOUND_LABEL_WIDTH - len(label))
        # A4: closest[store]["size"] exists — always surface it (Rule A).
        lines.append(
            f"   {label}{pad}{found.get('name', '')}"
            f"{unit_suffix(found.get('size', ''))}")
```

**Edit 2 (A3) — `format_report` item_block call. ANCHOR (old):**

```python
        lines.append(item_block(
            i, item.name, store_lines,
            home_brand=item.is_woolworths_home_brand,
        ))
```

**NEW:**

```python
        # A3: title shows Woolworths' size when present, else Coles'
        # (store lines in A2 show each store's own). Always a string →
        # the tag (or the ⚠️ marker note) is NEVER omitted.
        unit = (
            item.matched_sizes.get("woolworths")
            or item.matched_sizes.get("coles")
            or ""
        )
        lines.append(item_block(
            i, item.name, store_lines,
            home_brand=item.is_woolworths_home_brand,
            unit=unit,
        ))
```

**Existing-test update:** grep `test_comparator.py` for
`item_block|format_report` exact-string assertions — compare report
titles now carry ` · <unit>` / ` · ⚠️ unit unavailable`.

**Tests — append:**

```python
class TestReportUnitSurfaces(unittest.TestCase):
    """A3/A4: title tag survives truncation; found-block shows size."""

    def test_found_block_shows_store_size_and_marker(self):
        from core.price_comparator import BasketItem, _found_block_lines
        item = BasketItem(
            name="flour", prices={}, sources={}, closest={
                "woolworths": {"name": "Flour Plain", "size": "1kg"},
                "coles": {"name": "Coles Flour", "size": ""},
            })
        lines = _found_block_lines(item)
        self.assertTrue(any(ln.endswith(" · 1kg") for ln in lines))
        self.assertTrue(
            any(" · ⚠️ unit unavailable" in ln for ln in lines))

    def test_format_report_title_tag_survives_truncation(self):
        from core.price_comparator import BasketItem, ComparisonReport,
        ...
```

(03 Code: implement the second test concretely — build a
`ComparisonReport` with one `BasketItem` whose `name` is 30+ cells and
`matched_sizes={"woolworths": "200g"}`; assert the rendered first line
of its block `endswith(" · 200g")` and contains `…`. Follow the
existing `ComparisonReport(...)` construction pattern already used in
`test_comparator.py`.)

**Verify:**
```powershell
$PY -m pytest grocery-price-tracker/tests/test_comparator.py -q
$PY -m py_compile grocery-price-tracker/core/price_comparator.py
```

---

## S5 — A7: specials report unit tags

**Files:** `grocery-price-tracker/core/specials_reporter.py` (edit),
`grocery-price-tracker/tests/test_specials_flags.py` (append).

**Edit 1 — `get_active_specials` result dict carries size. ANCHOR (old):**

```python
            results.append({
                "name": name,
                "store": store_key,
                "special_desc": cell,
                "price": price,
                "brand": brand,
                "row_index": sheet_row,
            })
```

**NEW (same block plus one key):**

```python
            results.append({
                "name": name,
                "store": store_key,
                "special_desc": cell,
                "price": price,
                "brand": brand,
                "row_index": sheet_row,
                "size": str(row[2]).strip() if len(row) > 2 else "",
            })
```

**Edit 2 — `format_specials_report` item name line. ANCHOR (old):**

```python
        lines.append(f"{i}. {s['name']}")
```

**NEW:**

```python
        # A7 (Rule A): every item line carries the unit tag.
        lines.append(f"{i}. {s['name']}{unit_suffix(s.get('size', ''))}")
```

**Edit 3 — extend the local import. ANCHOR (old):**
`    from core.telegram_format import header`
**NEW:**
`    from core.telegram_format import header, unit_suffix`

**Tests — append to `test_specials_flags.py` (uses its existing
FakeWorksheet pattern; if absent, mirror the one in `test_cli.py`):**

```python
class TestSpecialsUnitTags(unittest.TestCase):
    """A7: specials lines always carry the unit tag (Rule A)."""

    def test_format_specials_report_appends_unit_and_marker(self):
        from core.specials_reporter import format_specials_report
        out = format_specials_report([
            {"name": "Oat Milk", "store": "coles", "price": 2.0,
             "special_desc": "was $3", "brand": "", "size": "1L"},
            {"name": "Bread", "store": "coles", "price": 1.0,
             "special_desc": "", "brand": "", "size": ""},
        ])
        self.assertIn("1. Oat Milk · 1L", out)
        self.assertIn("2. Bread · ⚠️ unit unavailable", out)

    def test_get_active_specials_carries_col_c_size(self):
        from core.specials_reporter import get_active_specials
        ws = _FakeSpecialsWorksheet(...)  # rows: A=name, C=size, N=flag
        rows = get_active_specials(worksheet=ws)
        assert rows and rows[0]["size"] == "1L"
```

(03 Code: build the fake worksheet rows so Col C=index 2 holds `"1L"`
and one row holds `""`; assert both the `"size"` key and the rendered
` ⚠️ unit unavailable` line.)

**Verify:**
```powershell
$PY -m pytest grocery-price-tracker/tests/test_specials_flags.py -q
$PY -m py_compile grocery-price-tracker/core/specials_reporter.py
```

---

## S6 — B5 + A8: `searched_items` always carries + shows size

**Files:** `grocery-price-tracker/core/searched_items.py` (edit),
`grocery-price-tracker/tests/test_searched_items.py` (append + update).

**Edit 1 — import. ANCHOR (old):**
`from core.telegram_format import header, subheader`
**NEW:**
`from core.telegram_format import UNIT_UNAVAILABLE, header, subheader, unit_suffix`

**Edit 2 — module docstring line. ANCHOR (old):**
`The "size" key is present only when a size was captured at add time.`
**NEW:**
`Every NEW entry carries "size" (real value or the "unit unavailable"
marker); legacy entries without the key read as blank and display the
note (Rule A/B).`

**Edit 3 — `add_entry` always stores size. ANCHOR (old):**

```python
    size_clean = str(size or "").strip()
    if size_clean:
        entry["size"] = size_clean
    entries = load_pending()
```

**NEW:**

```python
    # B5: every NEW entry carries "size" — blank normalises to the
    # canonical marker (add paths resolve beforehand; this is the
    # last-resort backstop, plan P6).
    entry["size"] = str(size or "").strip() or UNIT_UNAVAILABLE
    entries = load_pending()
```

**Edit 4 — `render_show` entry line. ANCHOR (old):**

```python
        for entry in store_entries:
            segments = [store, entry.get("keyword", "")]
            size = entry.get("size", "")
            if size:
                segments.append(size)
            segments.append(f"[{entry.get('code', '')}]")
            blocks.append(" · ".join(segments))
```

**NEW:**

```python
        for entry in store_entries:
            # A8 (Rule A): unit segment ALWAYS present; legacy entries
            # without a "size" key read as blank -> the ⚠️ note.
            blocks.append(
                " · ".join([store, entry.get("keyword", "")])
                + unit_suffix(entry.get("size", ""))
                + f" [{entry.get('code', '')}]")
```

**Existing-test update:** grep `test_searched_items.py` for
`"size"` assertions expecting the key to be ABSENT after `add_entry`
with `size=""` — now expect `"size": "unit unavailable"`. Also update
`render_show` exact-line assertions.

**Tests — append:**

```python
class TestSearchedItemsSizeContract(unittest.TestCase):
    """B5/A8: size always stored; show always renders the tag."""

    def test_add_entry_blank_size_stores_marker(self):
        # patch si.SEARCHED_ITEMS_PATH to a tmp file first (existing
        # setUp pattern in this file)
        result = si.add_entry("coles", "Beans 400g", "Beans 400g")
        self.assertEqual(result["entry"]["size"], "unit unavailable")

    def test_show_renders_unit_and_marker(self):
        # seed the patched queue file with:
        #   {"store": "coles", "keyword": "Beans 400g", "code": "AAA",
        #    "generic_name": "Beans 400g", "size": "400g", ...}
        #   {"store": "woolworths", "keyword": "Milk", "code": "BBB",
        #    "generic_name": "Milk"}                      # legacy: no key
        out = si.render_show()
        self.assertIn(" · 400g [AAA]", out)
        self.assertIn(" · ⚠️ unit unavailable [BBB]", out)
```

(03 Code: reuse the file's existing tmp-path patching fixture for
`SEARCHED_ITEMS_PATH` / tombstones; the tests above are behavioural
specs, wire them to that fixture.)

**Verify:**
```powershell
$PY -m pytest grocery-price-tracker/tests/test_searched_items.py -q
```

---

## S7 — B4 + A8: `add_to_list` entry schema + show rendering

**Files:** `grocery-price-tracker/core/add_to_list.py` (edit),
`grocery-price-tracker/tests/test_add_to_list.py` (append + update).

**Edit 1 — import. ANCHOR (old):**
`from core.telegram_format import header, subheader`
**NEW:**
`from core.telegram_format import UNIT_UNAVAILABLE, header, subheader, unit_suffix`

**Edit 2 — module docstring entry shape. ANCHOR (old):**

```
    Entry shape (JSON list, insertion order preserved):
        {"store": "woolworths", "keyword": "Woolworths Beef Mince 500g",
         "generic_name": "Woolworths Beef Mince 500g",
         "added_at": "2026-08-28T02:00:00.000000+00:00"}
```

**NEW (adds the size key to the documented shape):**

```
    Entry shape (JSON list, insertion order preserved):
        {"store": "woolworths", "keyword": "Woolworths Beef Mince 500g",
         "generic_name": "Woolworths Beef Mince 500g", "size": "500g",
         "added_at": "2026-08-28T02:00:00.000000+00:00"}

    Every NEW entry carries "size" (real value or the "unit
    unavailable" marker, Rule B); legacy entries without the key read
    as blank and display the note (Rule A).
```

**Edit 3 — `add_entry` signature + entry dict. ANCHOR (old):**

```python
def add_entry(store: str, keyword: str, generic_name: str) -> dict:
```

**NEW:**

```python
def add_entry(store: str, keyword: str, generic_name: str,
              size: str = "") -> dict:
```

And inside, ANCHOR (old):

```python
    entry = {
        "store": store_key,
        "keyword": kw,
        "generic_name": gn,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
```

**NEW:**

```python
    entry = {
        "store": store_key,
        "keyword": kw,
        "generic_name": gn,
        # B4: always present; blank normalises to the marker (P6).
        "size": str(size or "").strip() or UNIT_UNAVAILABLE,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
```

(Also extend the `Args:` docstring with
`size (str): package size (real value or marker; "" → marker).`)

**Edit 4 — `render_show` entry line. ANCHOR (old):**
`            blocks.append(f"{counter}) {entry.get('keyword', '')}")`
**NEW:**
```python
            blocks.append(
                f"{counter}) {entry.get('keyword', '')}"
                f"{unit_suffix(entry.get('size', ''))}")
```

**Edit 5 — `render_remaining_flat` line. ANCHOR (old):**
`        lines.append(f"{i}) {entry.get('keyword', '')} ({store})")`
**NEW:**
```python
        lines.append(
            f"{i}) {entry.get('keyword', '')}"
            f"{unit_suffix(entry.get('size', ''))} ({store})")
```

**Existing-test update:** grep `test_add_to_list.py` for
`add_entry(` and entry-shape/assertEqual-dict assertions — new entries
now include `"size"`. Positional 3-arg calls keep working (default).

**Tests — append:**

```python
class TestAddToListSizeContract(unittest.TestCase):
    """B4/A8: size param always stored; renders tag / marker note."""

    def test_add_entry_stores_real_and_marker_size(self):
        r1 = atl.add_entry("coles", "Beans 400g", "Beans", size="400g")
        r2 = atl.add_entry("woolworths", "Milk", "Milk")  # no size
        self.assertEqual(r1["entry"]["size"], "400g")
        self.assertEqual(r2["entry"]["size"], "unit unavailable")

    def test_render_show_and_remaining_show_unit(self):
        # seed patched ADD_TO_LIST_PATH with one entry carrying
        # "size": "500g" and one legacy entry with no "size" key
        show = atl.render_show()
        self.assertIn(") Beans · 500g", show)
        flat = atl.render_remaining_flat(atl.ordered_entries())
        self.assertIn(" · ⚠️ unit unavailable", flat)
```

(Wire to the file's existing tmp-path fixture as in S6.)

**Verify:**
```powershell
$PY -m pytest grocery-price-tracker/tests/test_add_to_list.py -q
```

---

## S8 — CLI display surfaces: A1, A5, A6

**Files:** `grocery_price_cli.py` (edit),
`grocery-price-tracker/tests/test_cli.py` (append + update).

**Edit 1 — extend the module-level style-kit import. ANCHOR (old):**

```python
from core.telegram_format import (                  # noqa: E402
    header, subheader, fenced_table, item_block, store_line,
    kv, money, warn, ok, fail, tail, truncate, divider,
    HEAVY_DIVIDER, HEAVY_DIVIDER_WIDTH,
)
```

**NEW:**

```python
from core.telegram_format import (                  # noqa: E402
    header, subheader, fenced_table, item_block, store_line,
    kv, money, warn, ok, fail, tail, truncate, divider,
    unit_tag, unit_suffix, UNIT_UNAVAILABLE,
    HEAVY_DIVIDER, HEAVY_DIVIDER_WIDTH,
)
```

**Edit 2 (A1) — `_size_suffix` inside `_cmd_search`. ANCHOR (old):**

```python
    def _size_suffix(item) -> str:
        return f" · {item.size}" if getattr(item, "size", "") else ""
```

**NEW:**

```python
    def _size_suffix(item) -> str:
        # A1 (Rule A): never silently omit — unit_suffix yields
        # " · 1L" or " · ⚠️ unit unavailable".
        return unit_suffix(getattr(item, "size", "") or "")
```

**Edit 3 (A5) — interactive candidate lines in `_map_unmatched_item`.
ANCHOR (old):**

```python
        for i, c in enumerate(result.candidates, 1):
            brand = f" ({c.brand})" if c.brand else ""
            print(f"    {i}) {c.generic_name}{brand} [score {c.score}]")
```

**NEW:**

```python
        for i, c in enumerate(result.candidates, 1):
            brand = f" ({c.brand})" if c.brand else ""
            print(f"    {i}) {c.generic_name}{brand}"
                  f"{unit_suffix(getattr(c, 'size', '') or '')} "
                  f"[score {c.score}]")
```

**Edit 4 (A5) — non-interactive candidate lines in
`_resolve_and_print_unmatched`. ANCHOR (old):**

```python
        for i, c in enumerate(result.candidates or [], 1):
            brand = f" ({c.brand})" if c.brand else ""
            print(f"    {i}) {c.generic_name}{brand} [score {c.score}]")
```

**NEW:**

```python
        for i, c in enumerate(result.candidates or [], 1):
            brand = f" ({c.brand})" if c.brand else ""
            print(f"    {i}) {c.generic_name}{brand}"
                  f"{unit_suffix(getattr(c, 'size', '') or '')} "
                  f"[score {c.score}]")
```

**Edit 5 (A6) — `_print_queue_confirmation`. ANCHOR (old):**

```python
    store = str(entry.get("store", "")).strip().capitalize()
    code = entry.get("code", "")
    print(f"Queued for Wednesday: '{entry.get('keyword', '')}' "
          f"({store}) [{code}]")
```

**NEW:**

```python
    store = str(entry.get("store", "")).strip().capitalize()
    code = entry.get("code", "")
    # A6: ack shows the unit — 'X' · 200g (Coles) [KAT]; legacy
    # entries without "size" show the ⚠️ note.
    print(f"Queued for Wednesday: '{entry.get('keyword', '')}'"
          f"{unit_suffix(entry.get('size', ''))} ({store}) [{code}]")
```

**Existing-test update:** grep `test_cli.py` for
`Queued for Wednesday|_size_suffix|score ` exact-output assertions and
update expected strings.

**Tests — append:**

```python
class TestCliUnitSurfaces(unittest.TestCase):
    """A1/A5/A6 CLI display units."""

    def test_print_queue_confirmation_with_and_without_size(self):
        import grocery_price_cli as gpc
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            gpc._print_queue_confirmation(
                {"store": "coles", "keyword": "Beans", "code": "KAT",
                 "size": "400g"})
            gpc._print_queue_confirmation(
                {"store": "coles", "keyword": "Milk", "code": "RUM"})
        out = buf.getvalue()
        self.assertIn("Queued for Wednesday: 'Beans' · 400g (Coles) [KAT]",
                      out)
        self.assertIn(
            "Queued for Wednesday: 'Milk' · ⚠️ unit unavailable "
            "(Coles) [RUM]", out)
```

**Verify:**
```powershell
$PY -m pytest grocery-price-tracker/tests/test_cli.py -q
$PY -m py_compile grocery_price_cli.py
```

---

## S9 — Rule B resolver `_resolve_add_unit` + `--unit` flags

**Files:** `grocery_price_cli.py` (edit),
`grocery-price-tracker/tests/test_cli.py` (append).

**Edit 1 — insert the resolver directly AFTER the `_queue_searched_item`
function (anchor: its final lines
`    return entry` + blank line before `def _cmd_search`):**

```python
_UNIT_REQUIRED_ERROR = "unit is required: pass a size or the marker"


def _resolve_add_unit(name: str, live_size: str = "", *,
                      override: str = "", interactive: bool | None = None,
                      _input=input) -> str:
    """Resolve the unit for an add (Rule B chain, spec §4).

    Order: (1) explicit override (--unit flag), (2) live listing size,
    (3) size parsed from the product name via _SIZE_PATTERN, (4) ask
    the user once (D-U4; blank or 'unknown' -> marker), else fail fast
    (non-interactive one-shot runs, spec R1).

    Args:
        name (str): the product name being added.
        live_size (str): the live listing's size field ("" when absent).
        override (str): explicit --unit value ("" when not given).
        interactive (bool | None): force interactive mode; None =
            auto-detect via stdin TTY.
        _input: injectable input() for tests.

    Returns:
        str: a real size ("1L") or the canonical marker
        "unit unavailable".

    Raises:
        ValueError: _UNIT_REQUIRED_ERROR when nothing resolved and the
        session is non-interactive.
    """
    for candidate in (str(override or "").strip(),
                      str(live_size or "").strip()):
        if candidate:
            return candidate
    from core.name_matcher import _SIZE_PATTERN
    m = _SIZE_PATTERN.search(name or "")
    if m:
        return m.group(1).strip()
    if interactive is None:
        try:
            interactive = sys.stdin.isatty()
        except (ValueError, OSError):
            interactive = False
    if not interactive:
        raise ValueError(_UNIT_REQUIRED_ERROR)
    answer = str(_input(
        f"What unit is {name}? e.g. 1L / 250g / 5 pack — "
        f"reply, or 'unknown': ")).strip()
    if not answer or answer.lower() == "unknown":
        return UNIT_UNAVAILABLE
    return answer
```

**Edit 2 — `search` parser gains `--unit`. ANCHOR (old):**

```python
    sp2.add_argument("--add-item", type=int, default=None, metavar="N",
                     help="Queue the Nth displayed result for Wednesday "
                          "(sheet row + searched-items queue; explicit add)")
    sp2.set_defaults(func=_cmd_search)
```

**NEW:**

```python
    sp2.add_argument("--add-item", type=int, default=None, metavar="N",
                     help="Queue the Nth displayed result for Wednesday "
                          "(sheet row + searched-items queue; explicit add)")
    sp2.add_argument("--unit", default=None, metavar="UNIT",
                     help="Unit for --add-item when the result has none "
                          "(e.g. 1L / 250g / 5 pack, or the literal "
                          "'unit unavailable')")
    sp2.set_defaults(func=_cmd_search)
```

**Edit 3 — `map` parser gains `--unit`. ANCHOR (old):**

```python
    mp.add_argument("--keyword", type=str, default=None, metavar="STORE_NAME",
                    help="Non-interactive: save STORE_NAME as store keyword (wool/coles only), advance")
    mp.set_defaults(func=_cmd_map)
```

**NEW:**

```python
    mp.add_argument("--keyword", type=str, default=None, metavar="STORE_NAME",
                    help="Non-interactive: save STORE_NAME as store keyword (wool/coles only), advance")
    mp.add_argument("--unit", default=None, metavar="UNIT",
                    help="Unit for --add when the result has none "
                         "(e.g. 1L / 250g / 5 pack, or the literal "
                         "'unit unavailable')")
    mp.set_defaults(func=_cmd_map)
```

**Tests — append:**

```python
class TestResolveAddUnit(unittest.TestCase):
    """Rule B unit resolution chain (spec §4, D-U4, R1)."""

    def test_override_then_live_size_win(self):
        r = gpc._resolve_add_unit("Milk", "1L", override="2L")
        self.assertEqual(r, "2L")
        self.assertEqual(gpc._resolve_add_unit("Milk", "1L"), "1L")

    def test_name_parse_falls_through(self):
        self.assertEqual(
            gpc._resolve_add_unit("Devondale Milk 2L", ""), "2L")

    def test_noninteractive_fails_fast_with_exact_error(self):
        with self.assertRaises(ValueError) as ctx:
            gpc._resolve_add_unit("Milk", "", interactive=False)
        self.assertEqual(
            str(ctx.exception),
            "unit is required: pass a size or the marker")

    def test_interactive_ask_once_unknown_and_blank_write_marker(self):
        replies = iter(["unknown", "  "])
        fake_input = lambda prompt: next(replies)  # noqa: E731
        self.assertEqual(
            gpc._resolve_add_unit(
                "Milk", "", interactive=True, _input=fake_input),
            "unit unavailable")
        self.assertEqual(
            gpc._resolve_add_unit(
                "Milk", "", interactive=True, _input=fake_input),
            "unit unavailable")

    def test_interactive_answer_returned_verbatim(self):
        self.assertEqual(
            gpc._resolve_add_unit(
                "Milk", "", interactive=True,
                _input=lambda prompt: "5 pack"),
            "5 pack")
```

**Verify:**
```powershell
$PY -m pytest grocery-price-tracker/tests/test_cli.py -k resolve_add_unit -q
$PY -m py_compile grocery_price_cli.py
```

---

## S10 — B1 (sheet side): `add_product_row` size becomes REQUIRED

**Files:** `grocery-price-tracker/core/sheets_sync.py` (edit),
`grocery-price-tracker/tests/test_sheets_sync.py` (update + append).

**Edit 1 — module import. ANCHOR (old):**
`from core.name_matcher import KeywordIndex  # for _normalize reuse`
**NEW:**
`from core.name_matcher import KeywordIndex, _SIZE_PATTERN  # _normalize reuse + size parse`

**Edit 2 — Section A constant. ANCHOR (old):**

```python
PRICE_COL = {"woolworths": 3, "coles": 4}   # D, E
LAST_UPDATED_COL = 7                                     # H
```

**NEW:**

```python
PRICE_COL = {"woolworths": 3, "coles": 4}   # D, E
SIZE_COL = 2                                             # C (unit column)
LAST_UPDATED_COL = 7                                     # H
```

**Edit 3 — signature. ANCHOR (old, inside `add_product_row` params):**
`    size: str = "",`
**NEW:**
`    size: str,`

**Edit 4 — docstring arg line. ANCHOR (old):**
`        size: size string for Col C (default "").`
**NEW:**
```python
        size: REQUIRED Col C value — a real size ("1L") or the
            canonical marker "unit unavailable" (Rule B, spec B1).
```

**Edit 5 — fail-fast validation. ANCHOR (old):**

```python
    if price <= 0:
        return {
            "wrote": False, "row_index": None, "range_written": "",
            "error": "price must be > 0",
        }
```

**NEW (append a size check immediately after this block):**

```python
    if price <= 0:
        return {
            "wrote": False, "row_index": None, "range_written": "",
            "error": "price must be > 0",
        }
    size_clean = str(size or "").strip()
    if not size_clean:
        return {
            "wrote": False, "row_index": None, "range_written": "",
            "error": "unit is required: pass a size or the marker",
        }
```

**Edit 6 — row build. ANCHOR (old):**

```python
    new_row[0] = generic_name.strip()             # Col A
    if category:
        new_row[1] = category                      # Col B
    if size:
        new_row[2] = size                          # Col C
```

**NEW:**

```python
    new_row[0] = generic_name.strip()             # Col A
    if category:
        new_row[1] = category                      # Col B
    new_row[SIZE_COL] = size_clean                 # Col C (always set)
```

**Existing-test update (mandatory before running the suite):**
```
Grep "add_product_row(" in tests/test_sheets_sync.py and in
grocery_price_cli.py — every call site needs an explicit size=
argument (use a real size like "1L" or the marker string).
```
In tests: calls that previously relied on the default `size=""` now
pass `size="1L"` (or `"unit unavailable"` where a marker case is
asserted). No behavioural expectation changes other than Col C being
populated.

**Tests — append to `test_sheets_sync.py`:**

```python
class TestAddProductRowRequiredSize(unittest.TestCase):
    """B1: empty size is rejected; marker is accepted (fail-fast)."""

    def test_blank_size_rejected_with_exact_error(self):
        from core.sheets_sync import add_product_row
        res = add_product_row("Milk", "coles", 3.0, size="   ",
                              worksheet=FakeWorksheet([...]))
        self.assertFalse(res["wrote"])
        self.assertEqual(
            res["error"], "unit is required: pass a size or the marker")

    def test_marker_accepted_and_written_to_col_c(self):
        from core.sheets_sync import add_product_row
        ws = FakeWorksheet([...])
        res = add_product_row("Milk", "coles", 3.0,
                              size="unit unavailable", worksheet=ws)
        self.assertTrue(res["wrote"])
        written = ws.updates[0][0][0]
        self.assertEqual(written[2], "unit unavailable")
```

(03 Code: give `FakeWorksheet` the same header/rows the file's existing
`add_product_row` tests use.)

**Verify:**
```powershell
$PY -m pytest grocery-price-tracker/tests/test_sheets_sync.py -q
```

---

## S11 — B1/B2 (CLI side): resolve-before-write in both add routes

**Files:** `grocery_price_cli.py` (edit),
`grocery-price-tracker/tests/test_cli.py` (append + update).

**Edit 1 (B1) — `_search_add_item`. ANCHOR (old):**

```python
    chosen = displayed[n - 1]
    store = chosen.store.lower()

    # Sheet row first; Col I/J stays EMPTY (interpretation 0.4).
    _load_env()
```

**NEW:**

```python
    chosen = displayed[n - 1]
    store = chosen.store.lower()

    # Rule B: resolve the unit BEFORE any write (live size -> name
    # parse -> --unit -> ask -> fail-fast; spec §4).
    try:
        unit = _resolve_add_unit(
            chosen.raw_name,
            getattr(chosen, "size", "") or "",
            override=getattr(args, "unit", None) or "")
    except ValueError as exc:
        print(f"Error: {exc} — re-run with --unit \"1L\" or "
              f"--unit \"unit unavailable\"", file=sys.stderr)
        return 1

    # Sheet row first; Col I/J stays EMPTY (interpretation 0.4).
    _load_env()
```

Then in the same function, ANCHOR (old):

```python
            brand=chosen.brand,
            size=chosen.size,
```

**NEW:**

```python
            brand=chosen.brand,
            size=unit,
```

And ANCHOR (old):

```python
    _queue_searched_item(
        store, chosen.raw_name, chosen.raw_name,
        store_product_id=getattr(chosen, "product_id", "") or "",
        size=getattr(chosen, "size", "") or "")
    return 0
```

**NEW:**

```python
    _queue_searched_item(
        store, chosen.raw_name, chosen.raw_name,
        store_product_id=getattr(chosen, "product_id", "") or "",
        size=unit)
    return 0
```

**Edit 2 (B2) — `_add_from_live_search` signature + resolution. ANCHOR
(old):**

```python
def _add_from_live_search(result, original_query: str) -> None:
    """Explicit add of a live-search result to the sheet + Queue 2.
```

**NEW:**

```python
def _add_from_live_search(result, original_query: str,
                          unit_override: str = "") -> bool:
    """Explicit add of a live-search result to the sheet + Queue 2.
```

(Extend the docstring: `Returns: bool — True when the row was written
and queued; False on any failure (error already printed).`)

Then ANCHOR (old):

```python
    # Use the live result's store for the price column
    store = best.store.lower()
    try:
        res = add_product_row(
            generic_name=best.raw_name,
            store=store,
            price=best.price,
            brand=best.brand,
            size=best.size,
```

**NEW:**

```python
    # Use the live result's store for the price column
    store = best.store.lower()
    # Rule B: resolve the unit BEFORE the write (B2). Non-interactive
    # callers pass unit_override (--unit); interactive sessions ask.
    try:
        unit = _resolve_add_unit(
            best.raw_name, getattr(best, "size", "") or "",
            override=unit_override)
    except ValueError as exc:
        print(f"  {exc} — re-run with --unit \"1L\" or "
              f"--unit \"unit unavailable\"")
        return False
    try:
        res = add_product_row(
            generic_name=best.raw_name,
            store=store,
            price=best.price,
            brand=best.brand,
            size=unit,
```

And the queue + failure tails of the same function, ANCHOR (old):

```python
            _queue_searched_item(
                store, best.raw_name, best.raw_name,
                store_product_id=getattr(best, "product_id", "") or "",
                size=getattr(best, "size", "") or "")
        else:
            print(f"  Add failed: {res.get('error', 'unknown')}")
    except Exception as exc:
        print(f"  add_product_row failed: {exc}")
```

**NEW:**

```python
            _queue_searched_item(
                store, best.raw_name, best.raw_name,
                store_product_id=getattr(best, "product_id", "") or "",
                size=unit)
            return True
        else:
            print(f"  Add failed: {res.get('error', 'unknown')}")
    except Exception as exc:
        print(f"  add_product_row failed: {exc}")
    return False
```

**Edit 3 — non-interactive `map unmatched --add` call site. ANCHOR
(old):**

```python
            _add_from_live_search(result, name)
        else:
```

**NEW:**

```python
            if not _add_from_live_search(
                    result, name,
                    unit_override=getattr(args, "unit", None) or ""):
                return 1
        else:
```

(The interactive call site `_add_from_live_search(result, name)` in
`_map_unmatched_item` stays as-is: TTY sessions ask via the resolver.)

**Existing-test update:** grep `test_cli.py` for
`_search_add_item|_add_from_live_search` — fake chosen/live items now
need a size, a size-bearing name, `--unit`, or an expected fail-fast.

**Tests — append:**

```python
class TestAddRoutesResolveUnit(unittest.TestCase):
    """B1/B2: add routes resolve the unit before any write."""

    def test_search_add_item_fails_fast_without_unit(self):
        args = argparse.Namespace(add_item=1, expand=False, unit=None)
        chosen = SimpleNamespace(
            store="Coles", raw_name="Milk", price=3.0, brand="",
            size="", category="", is_special=False, special_desc="",
            product_id="")
        rc = gpc._search_add_item(args, "milk", [chosen])
        self.assertEqual(rc, 1)  # non-TTY under pytest -> fail fast

    def test_search_add_item_uses_flag_unit(self):
        # patch gpc.add_product_row (module: core.sheets_sync) and
        # gpc._queue_searched_item; assert both received size="2L"
        args = argparse.Namespace(add_item=1, expand=False, unit="2L")
        chosen = SimpleNamespace(
            store="Coles", raw_name="Milk", price=3.0, brand="",
            size="", category="", is_special=False, special_desc="",
            product_id="")
        with patch("core.sheets_sync.add_product_row") as apr, \
             patch.object(gpc, "_queue_searched_item") as qsi:
            apr.return_value = {"wrote": True, "row_index": 9}
            rc = gpc._search_add_item(args, "milk", [chosen])
        self.assertEqual(rc, 0)
        self.assertEqual(apr.call_args.kwargs["size"], "2L")
        self.assertEqual(qsi.call_args.kwargs["size"], "2L")
```

(03 Code: `_load_env()` runs inside `_search_add_item`; keep the
existing env-patching pattern this file already uses for search tests.)

**Verify:**
```powershell
$PY -m pytest grocery-price-tracker/tests/test_cli.py -q
$PY -m py_compile grocery_price_cli.py
```

---

## S12 — B3/C.1: `update_single_price` gains `size` + blank-Col C backfill

**Files:** `grocery-price-tracker/core/sheets_sync.py` (edit),
`grocery-price-tracker/tests/test_sheets_sync.py` (append).

**Edit 1 — signature. ANCHOR (old):**

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

**NEW:**

```python
def update_single_price(
    product_name: str,
    store: str,
    price: float,
    *,
    dry_run: bool = False,
    is_special: Optional[bool] = None,
    special_desc: str = "",
    size: str = "",
    worksheet=None,
) -> dict:
```

(Extend the docstring Args with:
`size: Rule B resolved unit — written to a BLANK Col C in the same
row write; a non-empty Col C is never modified (spec §5.3).`)

**Edit 2 — backfill block + width. ANCHOR (old):**

```python
    target_width = max(price_col + 1, LAST_UPDATED_COL + 1)
    if write_specials:
        # Widen past M/N so the flag cell is inside the written range.
        target_width = max(target_width, specials_col + 1)
    while len(full_row) < target_width:
        full_row.append("")
    full_row[price_col] = price
    full_row[LAST_UPDATED_COL] = ts
```

**NEW:**

```python
    target_width = max(price_col + 1, LAST_UPDATED_COL + 1, SIZE_COL + 1)
    if write_specials:
        # Widen past M/N so the flag cell is inside the written range.
        target_width = max(target_width, specials_col + 1)
    while len(full_row) < target_width:
        full_row.append("")
    # Rule B/C.1: fill a BLANK Col C in the same row write (atomic,
    # no extra API call). Explicit size (marker allowed) wins;
    # otherwise parse from the matched name. Non-empty Col C is
    # NEVER modified (spec §5.3). Parse-based writes are real sizes
    # only — no marker is ever guessed here (D-U3).
    size_clean = str(size or "").strip()
    if not size_clean:
        m = _SIZE_PATTERN.search(product_name or "")
        size_clean = m.group(1).strip() if m else ""
    col_c = (str(full_row[SIZE_COL]).strip()
             if len(full_row) > SIZE_COL else "")
    if size_clean and not col_c:
        full_row[SIZE_COL] = size_clean
    full_row[price_col] = price
    full_row[LAST_UPDATED_COL] = ts
```

**Tests — append:**

```python
class TestUpdateSinglePriceBackfill(unittest.TestCase):
    """C.1: blank Col C healed in the same write; never overwritten."""

    def test_blank_col_c_backfilled_once_from_explicit_size(self):
        ws = FakeWorksheet([
            ["Name", "Cat", "Size", "WW", "Coles", "", "Brand", "TS"],
            ["Milk", "", "", "", "", "", "", ""],
        ])
        from core.sheets_sync import update_single_price
        res = update_single_price("Milk", "coles", 3.0,
                                  size="1L", worksheet=ws)
        self.assertTrue(res["wrote"])
        row = ws.updates[0][0][0]
        self.assertEqual(row[2], "1L")

    def test_second_run_writes_nothing_new_to_col_c(self):
        ws = FakeWorksheet([
            ["Name", "Cat", "Size", "WW", "Coles", "", "Brand", "TS"],
            ["Milk", "", "1L", "", "", "", "", ""],
        ])
        from core.sheets_sync import update_single_price
        update_single_price("Milk", "coles", 3.5,
                            size="unit unavailable", worksheet=ws)
        row = ws.updates[0][0][0]
        self.assertEqual(row[2], "1L")  # non-empty Col C untouched

    def test_name_parse_backfills_when_no_size_param(self):
        ws = FakeWorksheet([
            ["Name", "Cat", "Size", "WW", "Coles", "", "Brand", "TS"],
            ["Milk 2L", "", "", "", "", "", "", ""],
        ])
        from core.sheets_sync import update_single_price
        update_single_price("Milk 2L", "coles", 3.0, worksheet=ws)
        self.assertEqual(ws.updates[0][0][0][2], "2L")
```

**Verify:**
```powershell
$PY -m pytest grocery-price-tracker/tests/test_sheets_sync.py -q
```

---

## S13 — B3 (CLI side): map wool/coles add paths carry size

**Files:** `grocery_price_cli.py` (edit),
`grocery-price-tracker/tests/test_cli.py` (append).

**Edit 1 — `_queue_add_to_list` size param. ANCHOR (old):**

```python
def _queue_add_to_list(store: str, generic_name: str, keyword: str) -> None:
```

**NEW:**

```python
def _queue_add_to_list(store: str, generic_name: str, keyword: str,
                       size: str = "") -> None:
```

(Extend the docstring Args with
`size (str): Rule B resolved unit (stored on the queue entry).`)
And ANCHOR (old): `        result = atl.add_entry(store, keyword, generic_name)`
**NEW:** `        result = atl.add_entry(store, keyword, generic_name, size=size)`

**Edit 2 — interactive `_map_store_item` add branch. ANCHOR (old):**

```python
    if action in ("a", "add"):
        # Update the price for this generic name in the sheet
        from core.sheets_sync import update_single_price
        best = results[0]
        try:
            res = update_single_price(item, store, best.price)
            if res.get("found"):
                print(ok(f"Updated {store} price for '{item}' "
                         f"(row {res.get('row_index')}): ${best.price:.2f}"))
                _queue_add_to_list(store, item, best.raw_name)
```

**NEW:**

```python
    if action in ("a", "add"):
        # Update the price for this generic name in the sheet
        from core.sheets_sync import update_single_price
        best = results[0]
        # Rule B: resolve the unit (live size -> name parse -> ask).
        try:
            unit = _resolve_add_unit(
                best.raw_name, getattr(best, "size", "") or "")
        except ValueError as exc:
            print(f"  {exc}")
            return _prompt_action(
                "[a]dd [na] [keyword] [s]kip [stop] [done]")
        try:
            res = update_single_price(item, store, best.price, size=unit)
            if res.get("found"):
                print(ok(f"Updated {store} price for '{item}' "
                         f"(row {res.get('row_index')}): ${best.price:.2f}"))
                _queue_add_to_list(store, item, best.raw_name, size=unit)
```

**Edit 3 — non-interactive `map wool/coles --add` branch. ANCHOR
(old):**

```python
            best = results[0]
            from core.sheets_sync import update_single_price
            try:
                res = update_single_price(
                    item, store, best.price,
                    is_special=best.is_special,
                    special_desc=best.special_desc)
                if res.get("found"):
                    print(ok(f"Updated {store} price for '{item}' "
                             f"(row {res.get('row_index')}): ${best.price:.2f}"))
                    _queue_add_to_list(store, item, best.raw_name)
```

**NEW:**

```python
            best = results[0]
            # Rule B: resolve the unit (--unit -> live size -> name
            # parse -> fail-fast; interactive sessions ask instead).
            try:
                unit = _resolve_add_unit(
                    best.raw_name,
                    getattr(best, "size", "") or "",
                    override=getattr(args, "unit", None) or "")
            except ValueError as exc:
                print(f"Error: {exc} — re-run with --unit \"1L\" or "
                      f"--unit \"unit unavailable\"", file=sys.stderr)
                return 1
            from core.sheets_sync import update_single_price
            try:
                res = update_single_price(
                    item, store, best.price,
                    is_special=best.is_special,
                    special_desc=best.special_desc,
                    size=unit)
                if res.get("found"):
                    print(ok(f"Updated {store} price for '{item}' "
                             f"(row {res.get('row_index')}): ${best.price:.2f}"))
                    _queue_add_to_list(store, item, best.raw_name,
                                       size=unit)
```

**Tests — append:**

```python
class TestMapAddCarriesUnit(unittest.TestCase):
    """B3: wool/coles add passes size to the row write and the queue."""

    def test_noninteractive_add_passes_unit_to_write_and_queue(self):
        # patch _search_store_with_fallback -> [SimpleNamespace(
        #   raw_name="Milk 2L", price=3.0, size="", is_special=False,
        #   special_desc="", brand="")],
        # patch core.sheets_sync.update_single_price -> {"found": True,
        #   "row_index": 5}, patch gpc._queue_add_to_list,
        # patch gpc._advance_and_show -> 0; feed a minimal args
        # Namespace + items/progress fixtures as existing map tests do.
        ...
        self.assertEqual(
            usp.call_args.kwargs["size"], "2L")  # name-parsed
        self.assertEqual(qal.call_args.kwargs["size"], "2L")
```

(03 Code: wire this following the existing `_cmd_map_noninteractive`
test fixtures in `test_cli.py`; assert via the patched call kwargs as
sketched.)

**Verify:**
```powershell
$PY -m pytest grocery-price-tracker/tests/test_cli.py -q
$PY -m py_compile grocery_price_cli.py
```

---

## S14 — B7/C.1: `sync_prices` heals blank Col C in the batch write

**Files:** `grocery-price-tracker/core/sheets_sync.py` (edit),
`grocery-price-tracker/tests/test_sheets_sync.py` (append).

**Edit — inside the matched-row loop. ANCHOR (old):**

```python
        row = rows[list_idx]
        row[PRICE_COL[result.store]] = item.price
```

**NEW:**

```python
        row = rows[list_idx]
        row[PRICE_COL[result.store]] = item.price

        # Rule B/C.1: heal a blank Col C in the same batch write —
        # live item size first, then parse from the item's raw name.
        # NEVER writes the marker; a non-empty Col C is untouched
        # (D-U3 / spec §5.3). Rows are pre-padded to width >= 8, so
        # Col C (index 2) is always inside the written range.
        col_c = (str(row[SIZE_COL]).strip()
                 if len(row) > SIZE_COL else "")
        if not col_c:
            live_size = str(getattr(item, "size", "") or "").strip()
            if not live_size:
                m = _SIZE_PATTERN.search(
                    str(getattr(item, "raw_name", "") or ""))
                live_size = m.group(1).strip() if m else ""
            if live_size:
                row[SIZE_COL] = live_size
```

**Tests — append (spec §8.6):**

```python
class TestSyncPricesColCHeal(unittest.TestCase):
    """B7/C.1: sync heals blank Col C; never overwrites, no marker."""

    def _run(self, ws, item, result):
        from core.sheets_sync import sync_prices
        return sync_prices([result], [item], worksheet=ws)

    def test_blank_col_c_healed_from_item_size(self):
        # header + one row with blank Col C; MatchResult matched to
        # row 2; ProductItem(size="600g") -> written row[2] == "600g"
        ...

    def test_blank_col_c_healed_from_raw_name_parse(self):
        # ProductItem(size="", raw_name="Bread 650g") -> "650g"
        ...

    def test_nonempty_col_c_untouched_and_no_marker_written(self):
        # row Col C "1L"; item size "2L" -> stays "1L";
        # unparseable item (size="", raw_name="Herbs") -> stays ""
        ...
```

(03 Code: reuse the existing `sync_prices` FakeWorksheet fixtures in
this file; assert on `ws.updates[0][0]` rows. All three cases are
mandatory.)

**Verify:**
```powershell
$PY -m pytest grocery-price-tracker/tests/test_sheets_sync.py -q
```

---

## S15 — B6: missing-items queues carry `"size"`

**Files:** `grocery-price-tracker/core/missing_items_tracker.py` (edit),
`grocery-price-tracker/tests/test_cli.py` (append — the tracker tests
live there).

**Edit 1 — signature + docstring. ANCHOR (old):**

```python
def update_missing_items(
    woolworths_results: list,
    coles_results: list,
) -> dict:
```

**NEW:**

```python
def update_missing_items(
    woolworths_results: list,
    coles_results: list,
    *,
    sizes_by_generic: dict | None = None,
) -> dict:
```

(Extend the docstring: `sizes_by_generic (dict | None): optional map
of generic_name (Col A) -> Col C size, built from the source store's
sheet rows. New entries copy it into "size" (may be ""). Plan P4 —
MatchResult itself has no size field and name_matcher is frozen.`)

**Edit 2 — Woolworths-missing new entry. ANCHOR (old):**

```python
        else:
            entry = {
                "product_name": rn,
                "normalized_key": key,
                "source_store": "coles",
                "first_seen": now,
                "last_seen": now,
                "count": 1,
            }
            ww_queue.append(entry)
```

**NEW:**

```python
        else:
            entry = {
                "product_name": rn,
                "normalized_key": key,
                "source_store": "coles",
                # B6: copy the source store's Col C size ("" reads as
                # the note downstream — spec §2).
                "size": str(
                    (sizes_by_generic or {}).get(gn, "")).strip(),
                "first_seen": now,
                "last_seen": now,
                "count": 1,
            }
            ww_queue.append(entry)
```

**Edit 3 — Coles-missing new entry. Same pattern; ANCHOR (old):**

```python
        else:
            entry = {
                "product_name": rn,
                "normalized_key": key,
                "source_store": "woolworths",
                "first_seen": now,
                "last_seen": now,
                "count": 1,
            }
            coles_queue.append(entry)
```

**NEW:**

```python
        else:
            entry = {
                "product_name": rn,
                "normalized_key": key,
                "source_store": "woolworths",
                "size": str(
                    (sizes_by_generic or {}).get(gn, "")).strip(),
                "first_seen": now,
                "last_seen": now,
                "count": 1,
            }
            coles_queue.append(entry)
```

**Tests — append to `test_cli.py` (next to the existing
`update_missing_items` tests; reuse their fixture):**

```python
class TestMissingTrackerCarriesSize(unittest.TestCase):
    """B6: new queue entries copy size from sizes_by_generic."""

    def test_new_entries_carry_size_and_blank(self):
        # existing MatchResult fixture: one coles-only + one
        # woolworths-only matched item
        sizes = {"Beef Mince": "500g", "Oat Milk": ""}
        result = mit.update_missing_items(
            ww_results, coles_results, sizes_by_generic=sizes)
        ...
        # assert the new entries' "size" values match the map
```

(03 Code: mirror `test_update_missing_items_symmetric_disjoint`
fixtures; patch the queue paths to tmp files as that test does.)

**Verify:**
```powershell
$PY -m pytest grocery-price-tracker/tests/test_cli.py -k missing -q
$PY -m py_compile grocery-price-tracker/core/missing_items_tracker.py
```

---

## S16 — A9: Wednesday displays + unmatched queue display

**Files:** `grocery_price_cli.py` (edit),
`grocery-price-tracker/tests/test_cli.py` (append).

> **P5 TRAP:** txt files keep their machine format. Units are added
> ONLY to the Telegram display lines.

**Edit 1 — display helpers, inserted after `_chunk_list_message`
(anchor: its final lines `    return out` + blank line before
`def _post_weekly_summary`):**

```python
def _unmatched_display_line(entry: dict) -> str:
    """Telegram resolve-list line for one pending unmapped entry (A9)."""
    size = (entry.get("classification") or {}).get("size", "")
    return (f"{entry.get('raw_name', '')} [{entry.get('store', '')}]"
            f"{unit_suffix(size)}")


def _unmatched_display_lines(pending: list) -> list:
    """Telegram resolve-list lines for pending unmapped entries (A9)."""
    return [_unmatched_display_line(e) for e in pending]


def _missing_display_line(generic: str, size: str) -> str:
    """Telegram resolve-list line for one wool/coles-missing row (A9)."""
    return f"{generic}{unit_suffix(size)}"
```

**Edit 2 — unmatched block rebuild (keeps the forgotten-items print).
ANCHOR (old):**

```python
    pending = get_pending_mappings()
    unmatched_lines = [
        f"{e.get('raw_name', '')} [{e.get('store', '')}]"
        for e in pending
    ]
    # Exclude items the user permanently forgot via `map unmatched --forget`.
    ignored = _read_ignored_items(data_dir)
    if ignored:
        before = len(unmatched_lines)
        unmatched_lines = [ln for ln in unmatched_lines if ln not in ignored]
        if before != len(unmatched_lines):
            print(f"  (excluded {before - len(unmatched_lines)} forgotten items)")
```

**NEW:**

```python
    pending = get_pending_mappings()
    # Exclude items the user permanently forgot via `map unmatched --forget`.
    ignored = set(_read_ignored_items(data_dir))

    def _machine_line(e: dict) -> str:
        return f"{e.get('raw_name', '')} [{e.get('store', '')}]"

    pending_visible = [e for e in pending
                       if _machine_line(e) not in ignored]
    if len(pending_visible) != len(pending):
        print(f"  (excluded {len(pending) - len(pending_visible)} "
              f"forgotten items)")
    # Machine lines feed unmatched.txt (parsed by `map unmatched`);
    # display lines carry units for Telegram only (plan P5).
    unmatched_lines = [_machine_line(e) for e in pending_visible]
    unmatched_display = _unmatched_display_lines(pending_visible)
```

**Edit 3 — wool/coles missing build loop. ANCHOR (old):**

```python
    wool_missing_lines = []
    coles_missing_lines = []
    if not args.dry_run:
        # Re-read the sheet to compare keyword columns I and J per row
        ws = connect_worksheet()
        all_values = ws.get_all_values()
        rows = all_values[1:] if len(all_values) > 1 else []
        for row in rows:
            generic = row[0].strip() if row else ""
            if not generic:
                continue
            ww_kw = row[_WW_KW_COL].strip() if len(row) > _WW_KW_COL else ""
            coles_kw = row[_COLES_KW_COL].strip() if len(row) > _COLES_KW_COL else ""
            # "NA" (set by the `na` action) counts as populated -> excluded.
            if coles_kw and not ww_kw:
                wool_missing_lines.append(generic)
            if ww_kw and not coles_kw:
                coles_missing_lines.append(generic)
```

**NEW:**

```python
    wool_missing_lines = []
    coles_missing_lines = []
    wool_missing_display = []   # Telegram-only lines with units (P5)
    coles_missing_display = []
    if not args.dry_run:
        # Re-read the sheet to compare keyword columns I and J per row
        ws = connect_worksheet()
        all_values = ws.get_all_values()
        rows = all_values[1:] if len(all_values) > 1 else []
        for row in rows:
            generic = row[0].strip() if row else ""
            if not generic:
                continue
            size_c = row[2].strip() if len(row) > 2 else ""
            ww_kw = row[_WW_KW_COL].strip() if len(row) > _WW_KW_COL else ""
            coles_kw = row[_COLES_KW_COL].strip() if len(row) > _COLES_KW_COL else ""
            # "NA" (set by the `na` action) counts as populated -> excluded.
            if coles_kw and not ww_kw:
                wool_missing_lines.append(generic)
                wool_missing_display.append(
                    _missing_display_line(generic, size_c))
            if ww_kw and not coles_kw:
                coles_missing_lines.append(generic)
                coles_missing_display.append(
                    _missing_display_line(generic, size_c))
```

**Edit 4 — pass display lists to Telegram. ANCHOR (old):**

```python
            _post_weekly_summary(bot_token, summary_text, [
                ("Unmatched", unmatched_lines),
                ("Woolworths missing", wool_missing_lines),
                ("Coles missing", coles_missing_lines),
```

**NEW:**

```python
            _post_weekly_summary(bot_token, summary_text, [
                ("Unmatched", unmatched_display),
                ("Woolworths missing", wool_missing_display),
                ("Coles missing", coles_missing_display),
```

**Edit 5 — flush failed/parked lines carry the queue entry's unit.
ANCHOR (old):**

```python
                    for failed_item in failed:
                        summary_lines.append(
                            fail(f"- {failed_item.get('keyword', '')}"))
                    for parked_item in parked:
                        summary_lines.append(
                            fail(f"- {parked_item.get('keyword', '')} "
                                 f"(parked)"))
```

**NEW:**

```python
                    for failed_item in failed:
                        summary_lines.append(
                            fail(f"- {failed_item.get('keyword', '')}"
                                 f"{unit_suffix(failed_item.get('size', ''))}"))
                    for parked_item in parked:
                        summary_lines.append(
                            fail(f"- {parked_item.get('keyword', '')} "
                                 f"(parked)"
                                 f"{unit_suffix(parked_item.get('size', ''))}"))
```

**Edit 6 — `_cmd_unmatched` detail join always shows the size tag.
ANCHOR (old):**

```python
        detail = " · ".join(
            str(v) for v in (
                cls.get("brand", ""),
                cls.get("size", ""),
                cls.get("category", ""),
            ) if v
        )
```

**NEW:**

```python
        # A9: unit_tag never returns "" -> the size segment ALWAYS
        # shows (real size or the marker note, Rule A).
        detail = " · ".join(
            str(v) for v in (
                cls.get("brand", ""),
                unit_tag(cls.get("size", "")),
                cls.get("category", ""),
            ) if v
        )
```

**Tests — append:**

```python
class TestWednesdayDisplayUnits(unittest.TestCase):
    """A9: display lines carry units; machine lines stay clean (P5)."""

    def test_missing_display_line_known_and_unknown(self):
        self.assertEqual(
            gpc._missing_display_line("Milk", "1L"), "Milk · 1L")
        self.assertEqual(
            gpc._missing_display_line("Herbs", ""),
            "Herbs · ⚠️ unit unavailable")

    def test_unmatched_display_lines_use_classification_size(self):
        pending = [{"raw_name": "Beans 400g",
                    "store": "coles",
                    "classification": {"brand": "", "size": "400g",
                                       "category": ""}},
                   {"raw_name": "Herbs",
                    "store": "woolworths",
                    "classification": {}}]
        lines = gpc._unmatched_display_lines(pending)
        self.assertEqual(lines[0], "Beans 400g [coles] · 400g")
        self.assertEqual(lines[1],
                         "Herbs [woolworths] · ⚠️ unit unavailable")
```

**Existing-test update:** grep `test_cli.py` for wednesday-summary
assertions touching `unmatched_lines|wool_missing_lines` — counts and
machine formats are unchanged; only `_post_weekly_summary` inputs
change (display variants).

**Verify:**
```powershell
$PY -m pytest grocery-price-tracker/tests/test_cli.py -q
$PY -m py_compile grocery_price_cli.py
```

---

## S17 — Rule C.2: `backfill-sizes` command

**Files:** `grocery_price_cli.py` (edit),
`grocery-price-tracker/tests/test_cli.py` (append).

**Edit 1 — parser entry, inserted after the `backfill-home-brands`
block (anchor: `bh.set_defaults(func=_cmd_backfill_home_brands)`):**

```python
    bsz = sub.add_parser(
        "backfill-sizes",
        help="One-time Col C (size) backfill parsed from Col A/I/J "
             "names; fills only blank cells, never overwrites",
    )
    bsz.add_argument("--dry-run", action="store_true",
                     help="Print planned writes; no sheet mutation")
    bsz.set_defaults(func=_cmd_backfill_sizes)
```

**Edit 2 — size column constant, next to the backfill constants.
ANCHOR (old):**

```python
# Column indices in Products_Master (0-based) for the backfill.
_KEYWORDS_COL = 15      # P (Keywords — user-query aliases)
```

**NEW:**

```python
# Column indices in Products_Master (0-based) for the backfill.
_SIZE_COL_BF = 2        # C (size — the unit column)
_KEYWORDS_COL = 15      # P (Keywords — user-query aliases)
```

**Edit 3 — handler, inserted between `_cmd_backfill_keywords` and
`_cmd_backfill_home_brands` (anchor: the comment banner line
`# Handler: _cmd_backfill_home_brands — Col G home-brand classifier
backfill`):**

```python
def _cmd_backfill_sizes(args) -> int:
    """One-time Col C (size) backfill parsed from Col A/I/J (spec §5.2).

    Fills ONLY blank Col C cells whose size is parseable via
    name_matcher._SIZE_PATTERN from Col A, then Col I, then Col J.
    Non-empty Col C cells are NEVER modified (Rule C.3); unparseable
    rows stay blank and display the note (D-U3 — no guessed sizes, no
    bulk marker write). ONE batched update for all planned cells.
    """
    _load_env()
    from core.sheets_client import connect_worksheet
    from core.name_matcher import _SIZE_PATTERN

    ws = connect_worksheet()
    all_values = ws.get_all_values()
    rows = all_values[1:] if len(all_values) > 1 else []

    planned = []          # (row_index_1based, generic, size)
    skipped_set = 0       # Col C already non-empty
    left_blank = 0        # blank Col C, nothing parseable
    for i, row in enumerate(rows):
        row_index = i + 2
        generic = row[0].strip() if len(row) > 0 else ""
        current = (row[_SIZE_COL_BF].strip()
                   if len(row) > _SIZE_COL_BF else "")
        if current:
            skipped_set += 1
            continue
        size = ""
        for col in (0, 8, 9):  # Col A, Col I, Col J
            if len(row) > col:
                m = _SIZE_PATTERN.search(row[col])
                if m:
                    size = m.group(1).strip()
                    break
        if generic and size:
            planned.append((row_index, generic, size))
        else:
            left_blank += 1

    print(header("Backfill Sizes (Col C)", "📋"))
    print()
    print(kv("Rows examined", str(len(rows))))
    print(kv("Planned writes", str(len(planned))))
    print(kv("Skipped (Col C already set)", str(skipped_set)))
    print(kv("Left blank (no parseable size)", str(left_blank)))
    print()
    for row_index, generic, size in planned:
        print(f"{row_index}. {truncate(generic, 30)} · {EM_DASH} → {size}")

    if args.dry_run:
        print()
        print(warn("[DRY RUN] no sheet write"))
        return 0
    if not planned:
        print()
        print("Nothing to write.")
        return 0
    ws.batch_update([
        {"range": f"C{row_index}", "values": [[size]]}
        for row_index, _generic, size in planned
    ])
    print()
    print(f"Wrote {len(planned)} Col C cell(s) in one batched update.")
    return 0
```

**Tests — append (FakeWorksheet needs a `batch_update` method — extend
the local fake or subclass it in the test):**

```python
class _BatchFakeWorksheet(FakeWorksheet):
    def batch_update(self, updates):
        self.batch_updates = updates

class TestBackfillSizes(unittest.TestCase):
    """C.2: fills only parseable blanks; never touches non-empty C."""

    def _args(self, dry_run):
        return argparse.Namespace(dry_run=dry_run)

    def test_plans_only_blank_parseable_rows(self):
        ws = _BatchFakeWorksheet([
            ["Name", "Cat", "Size", "WW", "Coles", "", "Brand", "TS",
             "", "", "", "", "", "", "", ""],
            ["Milk 2L", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
            ["Herbs", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
            ["Bread", "", "650g", "", "", "", "", "", "", "", "", "", "", "", "", ""],
        ])
        with patch("core.sheets_client.connect_worksheet",
                   return_value=ws), \
             patch.object(gpc, "_load_env"):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                rc = gpc._cmd_backfill_sizes(self._args(dry_run=True))
        self.assertEqual(rc, 0)
        self.assertIn("Planned writes · 1", out.getvalue())
        self.assertIn("Left blank (no parseable size) · 1",
                      out.getvalue())
        self.assertIn("Skipped (Col C already set) · 1", out.getvalue())

    def test_live_run_batches_single_cell_ranges(self):
        ws = _BatchFakeWorksheet([...same rows...])
        with patch("core.sheets_client.connect_worksheet",
                   return_value=ws), \
             patch.object(gpc, "_load_env"):
            with contextlib.redirect_stdout(io.StringIO()):
                rc = gpc._cmd_backfill_sizes(self._args(dry_run=False))
        self.assertEqual(rc, 0)
        self.assertEqual(
            ws.batch_updates,
            [{"range": "C2", "values": [["2L"]]}])
```

(03 Code: pad the fake rows to 16 columns exactly as sketched; the
`_load_env` import site in the handler is `core.sheets_client` — patch
accordingly, matching how existing backfill tests in this file handle
env, if they exist; otherwise the pattern above is authoritative.)

**Verify:**
```powershell
$PY -m pytest grocery-price-tracker/tests/test_cli.py -k backfill_sizes -q
$PY -m py_compile grocery_price_cli.py
```

---

## S18 — Docs sync

**Files:** `grocery-price-tracker/PROJECT-MAP.md`, `grocery-price-tracker/README.md`
(behaviour notes only — the architect already updated them 2026-09-01).

Add/adjust (≤ 15 lines each file):
1. `backfill-sizes` command in the command list (one line, next to
   `backfill-keywords`).
2. `--unit` flag on `search --add-item` and `map --add` (one line).
3. Col C contract sentence: "Col C is the unit column; every add path
   fills it (real size or the literal `unit unavailable`); blank =
   legacy — displays as ` · ⚠️ unit unavailable` everywhere."

**Verify (deterministic):**
```powershell
$PY -c "from pathlib import Path; r = Path('grocery-price-tracker/README.md').read_text(encoding='utf-8'); assert 'backfill-sizes' in r and '--unit' in r; print('docs-ok')"
```

---

## S19 — Closeout verification (all mandatory, zero-skip)

```powershell
# 19.1 Full suite (regression bar: >= 504 + new, 0 failed, 0 skipped)
$PY -m pytest grocery-price-tracker/tests/ -q

# 19.2 Spec §8 verification matrix, targeted
$PY -m pytest grocery-price-tracker/tests/test_telegram_format.py -k "unit" -q
$PY -m pytest grocery-price-tracker/tests/test_comparator.py -q
$PY -m pytest grocery-price-tracker/tests/test_sheets_sync.py -q
$PY -m pytest grocery-price-tracker/tests/test_searched_items.py -q
$PY -m pytest grocery-price-tracker/tests/test_add_to_list.py -q
$PY -m pytest grocery-price-tracker/tests/test_cli.py -q

# 19.3 UOM gate still frozen (spec §2)
$PY -c "import sys; sys.path.insert(0, 'grocery-price-tracker'); from core.uom import parse_size; assert parse_size('unit unavailable') is None; print('gate-ok')"

# 19.4 Frozen files untouched (git, from the repo dir)
git -C grocery-price-tracker status --porcelain
git -C grocery-price-tracker diff --stat -- core/uom.py core/lookup.py core/name_matcher.py core/extractors
# Expected: empty diff for the frozen paths.

# 19.5 CLI compiles + smoke (help text lists backfill-sizes)
$PY -m py_compile grocery_price_cli.py
$PY grocery_price_cli.py --help
```

**Optional git checkpoint (ONLY if the user/pipeline requests commits —
never commit unprompted):**
```powershell
git -C grocery-price-tracker add -A
git -C grocery-price-tracker commit -m "Units always visible: unit_tag everywhere, force Col C on adds, backfill-sizes"
```
(Note: `grocery_price_cli.py` lives OUTSIDE this git repo — see §7 Ops.)

---

## 4. Mandatory test matrix (spec §8 → steps; zero-skip enforcement)

| Spec §8 check | Implemented by | Test location |
|---|---|---|
| 1. unit_tag: real / blank / None / marker / whitespace | S1 | `test_telegram_format.py::TestUnitTag` |
| 2. Search display: ` · 200g` / ` · ⚠️ unit unavailable` exact | S1 (helper) + S8 (surface) | TestUnitTag + TestCliUnitSurfaces |
| 3. Title tag survives 24-cell truncation; no no-size branch in `_identity_suffix`; found-block shows `closest` size | S2, S3, S4 | TestItemBlockUnit, TestIdentitySuffixAlwaysUnit, TestReportUnitSurfaces |
| 4. `add_product_row` rejects empty size; accepts marker | S10 | TestAddProductRowRequiredSize |
| 5. Queue round-trip: entry JSON has `"size"`; show prints tag; legacy entry prints note | S6, S7, S11 | TestSearchedItemsSizeContract, TestAddToListSizeContract, TestAddRoutesResolveUnit |
| 6. `update_single_price` backfills blank Col C exactly once | S12 | TestUpdateSinglePriceBackfill (3 cases) |
| 7. Full suite green | S19.1 | — |

Additional mandatory coverage beyond §8 (plan-required):
resolver chain + fail-fast + ask-once (S9), map add pass-through
(S13), sync heal no-marker/no-overwrite (S14), tracker size copy
(S15), Wednesday display vs machine lines (S16), backfill-sizes
plan/batch/idempotence (S17).

**Zero-skip rule:** no `unittest.skip`, no `pytest.mark.skip`, no
`-k` exclusions in S19.1. Every test added above MUST run and pass.

---

## 5. Error boundaries & edge cases (binding)

1. `_resolve_add_unit` NEVER guesses: no name-parse hit and no
   interactive answer → exact error `unit is required: pass a size or
   the marker` (spec B1 text). Wrapper prints add the `--unit` hint.
2. `add_product_row` with blank/whitespace `size` → returns
   `{"wrote": False, "error": "unit is required: pass a size or the
   marker"}` — does NOT raise (callers already handle the dict shape).
3. Marker in Col C: accepted everywhere (writes, backfill param);
   NEVER written by an automated parse path (sync/backfill parse only
   real sizes — D-U3).
4. Non-empty Col C is NEVER modified by `update_single_price`,
   `sync_prices`, or `backfill-sizes` (Rule C.3).
5. Queue writes stay non-fatal after a successful price write
   (`_queue_add_to_list` / `_queue_searched_item` print errors, never
   raise) — preserved from current behaviour.
6. Legacy queue entries without `"size"`: `.get("size", "")` → blank →
   ⚠️ note. No migration scripts.
7. Wednesday txt file formats are UNCHANGED (machine-parsed by map
   flows); only Telegram display lines gain units (P5).
8. `unit_tag(None)` and `unit_suffix(None)` are safe (str-cast first).

---

## 6. File-by-file change budget

| File (absolute path) | Steps | Approx. lines changed |
|---|---|---|
| `<ROOT>\grocery-price-tracker\core\telegram_format.py` | S1, S2 | +55 |
| `<ROOT>\grocery-price-tracker\core\price_comparator.py` | S3, S4 | ~25 |
| `<ROOT>\grocery-price-tracker\core\specials_reporter.py` | S5 | ~8 |
| `<ROOT>\grocery-price-tracker\core\searched_items.py` | S6 | ~20 |
| `<ROOT>\grocery-price-tracker\core\add_to_list.py` | S7 | ~18 |
| `<ROOT>\grocery-price-tracker\core\sheets_sync.py` | S10, S12, S14 | ~45 |
| `<ROOT>\grocery-price-tracker\core\missing_items_tracker.py` | S15 | ~12 |
| `<ROOT>\grocery_price_cli.py` | S8, S9, S11, S13, S16, S17 | ~150 total (6 visits, each ≤ 50) |
| `<ROOT>\grocery-price-tracker\tests\*` (7 files) | alongside each step | tests only |
| `<ROOT>\grocery-price-tracker\PROJECT-MAP.md`, `README.md` | S18 | ≤ 15 each |

Frozen and untouched (verified in S19.4): `core/uom.py`,
`core/lookup.py`, `core/name_matcher.py` (import-only usage of
`_SIZE_PATTERN`), `core/extractors/*`, `telegram_gateway/`, `app.py`,
`local_sync.py`, sheet schema, `.env` handling.

---

## 7. Ops / deployment notes

**Local Terminal only (all steps above).** Nothing in this cycle
touches the VPS directly. After 03/04 complete:

1. **CLI copy-to-root mismatch (spec §7 NOTE):** `deploy_vps.py:45`
   expects `grocery_price_cli.py` inside the repo root. Before any
   VPS deploy, the updated CLI must be copied there (deterministic,
   Local Terminal, user-initiated deploy only):
   ```powershell
   Copy-Item "grocery_price_cli.py" "grocery-price-tracker\grocery_price_cli.py"
   ```
   This is a DEPLOY-time step, not part of S1–S18 (the working copy
   stays at `<ROOT>` per README §9 "pending migration").
2. **Live-sheet `backfill-sizes` run (manual, user-confirmed):**
   mutates the real sheet; requires `.env`. Run dry-run first, review
   the plan, then run live:
   ```powershell
   $PY grocery_price_cli.py backfill-sizes --dry-run
   $PY grocery_price_cli.py backfill-sizes
   ```
3. **Remote VPS:** no commands this cycle. Wednesday sync/scp flows
   pick up the new behaviour on the next local run automatically.

---

## 8. Risks tracked (carried from spec §9)

- **R1:** `--add-item` / `map --add` one-shot runs without a resolvable
  unit now FAIL FAST with an actionable `--unit` hint (deliberate;
  D-U4 ask-once covers interactive sessions; Claw relays the question).
- **R2:** size strings are display-only text; `1L` vs `1 L` drift is
  acceptable — `parse_size` normalises where comparability matters.
- **R3:** Col A names that embed the unit plus a Col C unit show the
  unit twice on compare titles — accepted this cycle.
- **R-new (this plan):** Wednesday txt formats are load-bearing for the
  map flows — guarded by P5 and the S16 machine/display split.

**Rollback:** every step is a small forward edit in one git repo +
one sibling file; `git -C grocery-price-tracker checkout -- <path>`
reverts repo files; the CLI is reverted from its git history only if
it has been committed outside this cycle — otherwise keep the S-step
edits inverted manually per the ANCHOR/NEW pairs above.
