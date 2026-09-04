# Implementation Plan — Sub-Categories (Q), Item-Codes (R), Preferred (S), Multi-Buy & Full Names

- **Date:** 2026-09-04
- **Stage:** 02 Plan (this doc) → 03 Code → 04 Architect Checker
- **Binding input:** `architecture-spec.md` (same folder) — §12 file
  boundaries and §13 verification are CONTRACT. Decisions D-SC1…D-X1
  apply as written (spec §11 open items are resolved by this plan:
  D-IC1 letters-only codes per D-IC1 rationale; D-P1 new `shop`
  command; taxonomy seed delivered in §3 below and in `core/subcategory.py`).
- **Baseline:** full test suite green at 621 tests (spec §13.8).

---

## 0. Conventions (binding for 03 Code)

### 0.1 Paths

| Thing | Absolute path |
|---|---|
| Project root (repo) | `C:\Users\User.DESKTOP-R2G441H\Documents\AI related\grocery-price-tracker` |
| CLI entry (OUTSIDE repo; in parent repo) | `C:\Users\User.DESKTOP-R2G441H\Documents\AI related\grocery_price_cli.py` |
| Skill file (OUTSIDE repo; in parent repo) | `C:\Users\User.DESKTOP-R2G441H\Documents\AI related\claw-skills\grocery-price\SKILL.md` |
| Skill catalogue regenerator | `C:\Users\User.DESKTOP-R2G441H\Documents\AI related\skills_doc.py` |
| Parent repo (tracks CLI + claw-skills) | `C:\Users\User.DESKTOP-R2G441H\Documents\AI related` (its own git repo) |

Two nested git repos exist. `grocery-price-tracker` files are
committed in the inner repo; `grocery_price_cli.py` and
`claw-skills/**` in the parent repo (`AI related`). Never move files.

### 0.2 Test & verify commands

- Tests run from the project root:
  `python -m pytest tests/<file>.py -q` (fallback: `python -m unittest tests.<file> -v`).
- Compile check: `python -m py_compile <file>`.
- Shell is Windows PowerShell 5.1. Use `cmd1; if ($?) { cmd2 }` for
  dependent chains. Commands below marked **[Local]** run in the
  project root; **[VPS]** run on the remote host over ssh.

### 0.3 Hard rules

- **Zero-skip tests:** every test case in §Test Plan is MANDATORY. No
  `@skip`, no `xfail`, no commenting out. Full suite must stay green
  after every step.
- MUST NOT modify (spec §12): `core/uom.py`, `core/name_matcher.py`,
  `telegram_gateway/`, `app.py`, `local_sync.py`, `.env` handling,
  `core/searched_items.py`, `core/add_to_list.py`, sheet columns A–P
  semantics. Read-only reuse is fine.
- Every new/changed function gets a docstring (what/args/returns/
  raises) per coding standards. Max line 88 chars (Python).
- No secrets in code/logs; `.env` only via existing `_load_env()`.
- MANDATORY after ANY `claw-skills/` edit (rule
  `.kilo/rules/04-claw-skills-doc-sync.md`): run `python skills_doc.py`
  then `python skills_doc.py --check` (must print `OK`), commit BOTH
  `SKILL.md` and `claw-skills/claw_skills_easy.md`, sync both to VPS.
  A skill change without this is INCOMPLETE.

### 0.4 Step size

Each step touches ≤2 files and ≤~50 modified lines. NEW-file steps
may add up to ~120 lines of complete module code in one go where
splitting would leave a broken import target; those steps are marked
**(new file — complete code)** and their tests land in the same step
or the immediately following one.

---

## 1. Step overview (execution order)

| # | Step | Files | Depends on |
|---|---|---|---|
| S0 | Git branch | — | — |
| S1 | Subcategory taxonomy module + tests | `core/subcategory.py`†, `tests/test_subcategory.py`† | — |
| S2 | Multi-buy module + tests | `core/multibuy.py`†, `tests/test_multibuy.py`† | — |
| S3 | Item-codes pure core + tests | `core/item_codes.py`†, `tests/test_item_codes.py`† | — |
| S4 | Item-codes sheet layer + tests | `core/item_codes.py`, `tests/test_item_codes.py` | S3 |
| S5 | Preferences read model + prompts + tests | `core/preferences.py`†, `tests/test_preferences.py`† | S1 |
| S6 | `set_preferred` write + tests | `core/preferences.py`, `tests/test_preferences.py` | S5 |
| S7 | Pending-run IO + shop resolver + tests | `core/preferences.py`, `tests/test_preferences.py` | S6 |
| S8 | Schema: append Q/R/S | `core/schema_upgrade.py` | — |
| S9 | `add_product_row` Q/R/S hook + tests | `core/sheets_sync.py`, `tests/test_sheets_sync.py` | S1, S4 |
| S10 | Lookup row metadata + tests | `core/lookup.py`, `tests/test_lookup.py` | S1 |
| S11 | `ProductItem` multi-buy fields + tests | `extractors/models.py`, `tests/test_extractors.py` | — |
| S12 | D-MB2 live payload probe | none (read-only) | — |
| S13 | WW/Coles best-effort capture | `extractors/woolworths_extractor.py`, `extractors/coles_extractor.py` | S11, S12 |
| S14 | M/N multi-buy cell codec on write paths + tests | `core/sheets_sync.py`, `tests/test_sheets_sync.py` | S2 |
| S15 | Comparator: terms on BasketItem + tests | `core/price_comparator.py`, `tests/test_comparator.py` | S2 |
| S16 | Comparator: effective-rate math + tests | `core/price_comparator.py`, `tests/test_comparator.py` | S15 |
| S17 | telegram_format: multibuy tag + width 60 + tests | `core/telegram_format.py`, `tests/test_telegram_format.py` | S2 |
| S18 | Comparator display + footnote + tests | `core/price_comparator.py`, `tests/test_comparator.py` | S16, S17 |
| S19 | CLI parsers (5 new commands + `--subcategory`) + tests | `grocery_price_cli.py`, `tests/test_cli.py` | S1–S7 |
| S20 | `subcategories` + `backfill-subcategories` + `backfill-codes` handlers | `grocery_price_cli.py`, `tests/test_cli.py` | S19 |
| S21 | `shop` handler + tests | `grocery_price_cli.py`, `tests/test_cli.py` | S20 |
| S22 | `prefer` handler + tests | `grocery_price_cli.py`, `tests/test_cli.py` | S21 |
| S23 | `lists` surfacing (needs review + multi-P) + tests | `grocery_price_cli.py`, `tests/test_cli.py` | S20 |
| S24 | README | `README.md` | S20–S22 |
| S25 | PROJECT-MAP §6F | `PROJECT-MAP.md` | S24 |
| S26 | SKILL.md + catalogue regen + tests log | `claw-skills/grocery-price/SKILL.md`, `claw-skills/claw_skills_easy.md`, `test.md` | S25 |
| S27 | Deploy + one-time ops + full verification | — | all |

† = new file.

---

## 2. Seed taxonomy (spec §11 open item 3 — resolved here)

Source: 56 Woolworths master names in `woolworths_master_comparison.csv`
+ spec-mandated example labels (bread, apples, eggs, shredded cheese,
cheese slice). Rows the rules miss get `needs review` — NEVER a guess
(D-SC2). Ordering principle: **compound labels before their generic
parent** (`cheese slice` before `cheese`; `corn chips` before
`potato chips`); boundary-safe patterns so `breading`/`breadcrumbs`
never match `bread`. 65 labels below (spec said ~50 — this covers all
56 CSV names plus spec examples).

Full rule table lives in S1 (complete code). Summary of labels:

`cheese slice, shredded cheese, cream cheese, mozzarella, parmesan,
feta, crackers, cheese, greek yoghurt, yoghurt, eggs, long life milk,
milk, iced coffee, coffee syrup, coffee, spring onion, onion, bananas,
blueberries, raspberries, strawberries, apples, capsicum, cucumber,
tomato, fresh herbs, potatoes, salad, bread, croissant, pancake mix,
muffins, juice, mineral water, spring water, water, energy drink,
liquid breakfast, sports drink, soft drink, chocolate bar, chocolate
spread, chocolate, chewing gum, mints, corn chips, potato chips,
popcorn, biscuits, slices, lollies, ice cream, frozen snacks, frozen
berries, sugar, cereal, pasta, rice, flour, oil, sauce, spread, pads,
hand warmers`

---

## 3. Implementation steps

### S0 — Git branch **[Local]**

```powershell
git -C "grocery-price-tracker" status --short          # must be clean
git -C "grocery-price-tracker" checkout -b feature/qrs-shop-multibuy
```

Verify: `git -C "grocery-price-tracker" branch --show-current`
prints `feature/qrs-shop-multibuy`. The parent repo
(`AI related`) stays on its current branch; CLI/skill edits are
committed there on the same feature name:
`git checkout -b feature/qrs-shop-multibuy` (run in `AI related`).

---

### S1 — `core/subcategory.py` (new file — complete code) + tests

**Files:** NEW `core/subcategory.py`, NEW `tests/test_subcategory.py`.

Complete module content:

```python
#!/usr/bin/env python3
"""Canonical sub-category taxonomy for Products_Master Col Q (§3, §4).

Ordered regex -> label rules, specific before generic (first match
wins). No rule match -> caller writes the literal marker NEEDS_REVIEW
(D-SC2 — never a silent guess). New clusters are one line in
_RULE_DEFS (D-SC1). Normalisation: lowercase, trim, collapse
whitespace/underscores/hyphens to single spaces.

Boundary-safe patterns: \\bbreads?\\b can NOT match "breading" or
"breadcrumbs" (the letter after "bread" is a word char, so the \\b
fails) — spec §4 mandates this.
"""
from __future__ import annotations

import re

SUBCATEGORY_HEADER = "Sub_Category"   # Col Q (0-based idx 16)
NEEDS_REVIEW = "needs review"         # literal marker (D-SC2)
CONFIDENT_THRESHOLD = 0.75            # rule hit = 1.0 >= threshold


def normalize_subcategory(s: str) -> str:
    """Lowercase, trim, collapse whitespace/_/- to single spaces.

    Args:
        s: raw sub-category text (user flag, Col Q cell, label).

    Returns:
        str: canonical form ("Shredded_Cheese" -> "shredded cheese").
    """
    text = str(s or "").strip().lower()
    text = re.sub(r"[_\-\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# (pattern, label) — ORDER IS BINDING: first match wins; compounds
# BEFORE generic parents ("cheese slice" before "cheese").
_RULE_DEFS: list[tuple[str, str]] = [
    # --- cheese (compounds first) ---
    (r"cheese\s*slice", "cheese slice"),
    (r"shredded\s*cheese|grated\s*cheese", "shredded cheese"),
    (r"cream\s*cheese", "cream cheese"),
    (r"mozzarella", "mozzarella"),
    (r"parmesan", "parmesan"),
    (r"feta", "feta"),
    (r"cheese\s*&?\s*cracker|crackers?", "crackers"),
    (r"cheese", "cheese"),
    # --- dairy ---
    (r"greek\s*yogh?urt", "greek yoghurt"),
    (r"yogh?urt", "yoghurt"),
    (r"eggs?", "eggs"),
    (r"long\s*life\s*milk|uht", "long life milk"),
    (r"milk", "milk"),
    (r"iced\s*coffee", "iced coffee"),
    (r"coffee\s*syrup", "coffee syrup"),
    (r"coffee", "coffee"),
    # --- fruit & veg ---
    (r"spring\s*onion", "spring onion"),
    (r"onions?", "onion"),
    (r"bananas?", "bananas"),
    (r"blueberries", "blueberries"),
    (r"raspberries", "raspberries"),
    (r"strawberries", "strawberries"),
    (r"apples?", "apples"),
    (r"capsicum", "capsicum"),
    (r"cucumbers?", "cucumber"),
    (r"tomatoes?", "tomato"),
    (r"coriander|fresh\s*herbs?|herbs?", "fresh herbs"),
    (r"potatoes?", "potatoes"),
    (r"lettuce|salad\s*mix", "salad"),
    # --- bakery ---
    (r"breads?", "bread"),
    (r"croissants?", "croissant"),
    (r"pancake\s*mix", "pancake mix"),
    (r"muffins?", "muffins"),
    # --- drinks ---
    (r"juice", "juice"),
    (r"mineral\s*water", "mineral water"),
    (r"spring\s*water", "spring water"),
    (r"water", "water"),
    (r"energy\s*drink", "energy drink"),
    (r"liquid\s*breakfast", "liquid breakfast"),
    (r"sports?\s*drink", "sports drink"),
    (r"soft\s*drink|soda", "soft drink"),
    # --- snacks / confectionery ---
    (r"chocolate\s*bar", "chocolate bar"),
    (r"choc\s*hazelnut|hazelnut\s*chocolate|chocolate\s*spread",
     "chocolate spread"),
    (r"chocolate", "chocolate"),
    (r"chewing\s*gum", "chewing gum"),
    (r"mints?", "mints"),
    (r"corn\s*chips", "corn chips"),
    (r"potato\s*chips|grain\s*waves|grainwaves|chips", "potato chips"),
    (r"popcorn", "popcorn"),
    (r"biscuits?|quadratini", "biscuits"),
    (r"choc\s*slice|cake\s*slice|slices?", "slices"),
    (r"loll(ie)?s|lolly", "lollies"),
    # --- freezer ---
    (r"ice\s*cream|frozen\s*dessert", "ice cream"),
    (r"frozen\s*snacks?|nuggets?|pickers|frozen\s*veg", "frozen snacks"),
    (r"frozen\s*berries", "frozen berries"),
    # --- pantry ---
    (r"sugar", "sugar"),
    (r"cereal", "cereal"),
    (r"pasta", "pasta"),
    (r"rice", "rice"),
    (r"flour", "flour"),
    (r"oil", "oil"),
    (r"sauce", "sauce"),
    (r"spread", "spread"),
    # --- household / other ---
    (r"pads?|tampon", "pads"),
    (r"hand\s*warmers?", "hand warmers"),
]

SUBCATEGORY_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(p), label) for p, label in _RULE_DEFS
]


def classify_subcategory(
    name: str, category_hint: str = ""
) -> tuple[str, float]:
    """Classify a product name into a sub-category label.

    Args:
        name: product name (Col A style).
        category_hint: coarse Col B category — accepted for future
            use; NEVER rescues a non-match (D-SC2).

    Returns:
        (label, confidence): ("", 0.0) when no rule matches — the
        CALLER then writes NEEDS_REVIEW. A rule hit returns
        (label, 1.0).
    """
    text = normalize_subcategory(name)
    if not text:
        return ("", 0.0)
    for pattern, label in SUBCATEGORY_RULES:
        if pattern.search(text):
            return (label, 1.0)
    return ("", 0.0)


def all_labels() -> list[str]:
    """Distinct labels in rule order (deduped) — for `subcategories`.

    Returns:
        list[str]: labels in precedence order.
    """
    seen: set = set()
    out: list[str] = []
    for _pattern, label in SUBCATEGORY_RULES:
        if label not in seen:
            seen.add(label)
            out.append(label)
    return out
```

`tests/test_subcategory.py` (new) — mandatory cases:

```python
class TestNormalize(unittest.TestCase):
    def test_normalize_collapses_case_underscore_hyphen(self)
    def test_normalize_empty_returns_empty(self)

class TestClassify(unittest.TestCase):
    def test_spec_examples(self):           # eggs/bread/apples/...
    def test_compound_before_generic(self): # "Hillview Cheese Slices
        # Full Fat 500g" -> "cheese slice" (NOT "cheese"/"slices")
    def test_breading_not_bread(self):      # "AJI CRISPY FRY BREADING
        # MIX ORIGINAL" -> ("", 0.0) -> caller writes needs review
    def test_breadcrumbs_not_bread(self)
    def test_corn_chips_before_potato_chips(self)  # "Supreme Cheese
        # Corn Chips" -> "corn chips"
    def test_confidence_is_1_or_0(self)
    def test_category_hint_never_rescues(self)

class TestAllLabels(unittest.TestCase):
    def test_labels_ordered_deduped_nonempty(self)
    def test_spec_mandated_labels_present(self)  # 5 labels §2
```

**Verify:**
`python -m py_compile core/subcategory.py`
`python -m pytest tests/test_subcategory.py -q`

---

### S2 — `core/multibuy.py` (new file — complete code) + tests

**Files:** NEW `core/multibuy.py`, NEW `tests/test_multibuy.py`.

```python
#!/usr/bin/env python3
"""Multi-buy ("2 for $6.00") parsing, rates, display — spec §7.

Display + math ONLY; never touches core/uom.py (§7.3 rule 5).
Parsing REUSES extractors.specials_parser FOR_RE / ANY_RE (no regex
duplication, spec §12). Mixed-product "Any N" promos parse to terms
but are INFORMATIONAL ONLY (D-MB3): callers must gate rate math on
is_mixed_promo().
"""
from __future__ import annotations

from extractors.specials_parser import ANY_RE, FOR_RE

MULTIBUY_PREFIX = "multi-buy"  # M/N cell vocabulary prefix (D25)


def parse_multibuy(desc: str) -> tuple[int, float] | None:
    """Parse "2 for $6.00" / "Any 2 | $9" style promo text.

    Args:
        desc: specials text (docx line, live special_desc, M/N cell).

    Returns:
        (qty, bundle_total) with qty >= 2 and total > 0, else None.
    """
    text = str(desc or "")
    match = FOR_RE.search(text) or ANY_RE.search(text)
    if not match:
        return None
    qty = int(match.group(1))
    total = float(match.group(2))
    if qty < 2 or total <= 0:
        return None
    return (qty, total)


def is_mixed_promo(desc: str) -> bool:
    """True when ONLY the cross-range "any N" marker is present.

    Mixed-product bundles have no true per-product price (D-MB3) —
    informational text only, never a rate.
    """
    text = str(desc or "")
    return bool(ANY_RE.search(text)) and not FOR_RE.search(text)


def effective_unit_rate(qty: int, total: float) -> float:
    """Bundle per-unit rate: total / qty (6.00 / 2 = 3.00).

    Raises:
        ValueError: qty < 2 or total <= 0.
    """
    if qty < 2 or total <= 0:
        raise ValueError("multi-buy needs qty >= 2 and total > 0")
    return round(total / qty, 2)


def encode_multibuy_cell(qty: int, total: float) -> str:
    """D25 prefix + parseable terms: "multi-buy 2/$6.00" (§7.2)."""
    return f"{MULTIBUY_PREFIX} {qty}/${total:.2f}"


def decode_multibuy_cell(cell: str) -> tuple[int, float] | None:
    """Decode an M/N cell into (qty, total).

    Returns None for: empty cell, non-multi-buy cell, legacy bare
    "multi-buy" (no terms — informational only), unparsable terms.
    """
    text = str(cell or "").strip()
    if not text.lower().startswith(MULTIBUY_PREFIX):
        return None
    return parse_multibuy(text)


def is_multibuy_cell(cell: str) -> bool:
    """True for ANY cell starting with the prefix (incl. bare legacy)."""
    return str(cell or "").strip().lower().startswith(MULTIBUY_PREFIX)


def format_multibuy_note(qty: int, total: float) -> str:
    """Mandatory display tag, EXACT text (§7.3 rule 2).

    Delegates to core.telegram_format.multibuy_tag so the note text
    has ONE source of truth (§12 telegram_format helper).
    """
    from core.telegram_format import multibuy_tag
    return multibuy_tag(qty, total)
```

`tests/test_multibuy.py` — mandatory cases (spec §13.5):

- `test_parse_for_style` ("2 for $6.00" → (2, 6.0))
- `test_parse_any_style` ("Any 2 | $9" → (2, 9.0))
- `test_parse_negative_cream_for_men` ("Cream For Men" → None — the
  spec's canonical false-positive case; FOR_RE requires a digit)
- `test_parse_negative_qty_one` ("1 for $3.00" → None)
- `test_is_mixed_promo_true_for_any_only` / `..._false_for_for`
- `test_effective_rate_six_over_two` (6.00/2 → 3.00)
- `test_effective_rate_raises_on_bad_args`
- `test_encode_decode_roundtrip` ("multi-buy 2/$6.00")
- `test_decode_bare_legacy_cell_returns_none`
- `test_decode_non_multibuy_returns_none` ("discount", "", "no")
- `test_is_multibuy_cell_bare_and_terms`
- `test_format_note_exact_text` → contains
  `🏷️ 2 for $6.00  [Note: must purchase 2+ units to receive this price]`
  (requires S17's telegram_format helper — until then, write this
  test with the tag text inline and switch it to the helper in S17;
  simplest: implement S17's 3-line helper FIRST in this step by also
  touching `core/telegram_format.py` — allowed: 2 files/step. Do
  that: add the helper now, defer only the width change.)

**This step therefore also adds to `core/telegram_format.py`**
(after the `SEP = "·"` block, ~line 57):

```python
# Multi-buy tag (spec §7.3 rule 2) — EXACT mandatory note text.
MULTIBUY_NOTE = "[Note: must purchase 2+ units to receive this price]"


def multibuy_tag(qty: int, total: float) -> str:
    """Render '🏷️ N for $X.XX  [Note: must purchase 2+ units …]'.

    Args:
        qty: bundle quantity (>= 2).
        total: bundle total price.

    Returns:
        str: the mandatory multi-buy display tag.
    """
    return f"🏷️ {qty} for ${total:.2f}  {MULTIBUY_NOTE}"
```

**Verify:**
`python -m py_compile core/multibuy.py core/telegram_format.py`
`python -m pytest tests/test_multibuy.py tests/test_telegram_format.py -q`

---

### S3 — `core/item_codes.py` pure core (new file — complete code) + tests

**Files:** NEW `core/item_codes.py`, NEW `tests/test_item_codes.py`.

```python
#!/usr/bin/env python3
"""Permanent 3-letter Item-Codes for Products_Master Col R (§3, §8.2).

Codes: 3 DISTINCT letters from CODE_ALPHABET (A–Z minus I, L, O),
unique across live rows AND the registry; deleted-row codes are
NEVER reused (D-IC2). Separate namespace from queue codes (D-IC3).

Concurrency: local processes serialise on an advisory lock file;
VPS-vs-local races resolve via optimistic verify-and-regenerate
(D-IC4). Capacity 23*22*21 = 10,626 codes (§8.2).
"""
from __future__ import annotations

import itertools
import json
import os
import random
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ"  # 23 letters (no I, L, O)
CODE_LENGTH = 3
MAX_GENERATE_ATTEMPTS = 200

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REGISTRY_PATH = DATA_DIR / "item_code_registry.json"  # patchable
LOCK_PATH = DATA_DIR / ".item_code_lock"              # advisory
LOCK_STALE_SECONDS = 60
LOCK_TIMEOUT_SECONDS = 10

ITEM_CODE_HEADER = "Item_Code"  # Col R (0-based idx 17)
ITEM_CODE_COL = 17

_CODE_RE = re.compile(r"^[A-Z]{3}$")


def is_valid_code(code: str) -> bool:
    """True: 3 uppercase letters, alphabet-legal, no repeated letter."""
    text = str(code or "").strip().upper()
    if len(text) != CODE_LENGTH or not _CODE_RE.match(text):
        return False
    if any(ch not in CODE_ALPHABET for ch in text):
        return False
    return len(set(text)) == CODE_LENGTH


def load_registry(path=None) -> dict:
    """Read the registry JSON; missing/corrupt -> {} (queue pattern)."""
    path = Path(path) if path else REGISTRY_PATH
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def save_registry(registry: dict, path=None) -> None:
    """Atomic registry write (tempfile + os.replace)."""
    path = Path(path) if path else REGISTRY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(registry, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def retired_codes(registry: dict) -> set:
    """Every code EVER assigned (live + deleted rows) — never reuse."""
    return {str(code).upper() for code in registry}


def generate_codes(
    existing: set, n: int = 1, *, rng=None, seed: str = ""
) -> list[str]:
    """Generate n distinct codes not in `existing` (§8.2).

    Deterministic when `seed` given (random.Random(seed)); on attempt
    exhaustion falls back to a sequential scan of the sorted
    permutation space. Uniqueness is guaranteed by check-then-take,
    not by the seed.

    Raises:
        RuntimeError: the whole 10,626-code space is taken.
    """
    taken = {str(c).upper() for c in existing}
    rng = rng if rng is not None else random.Random(seed or None)
    out: list[str] = []
    for _ in range(int(n)):
        code = None
        for _attempt in range(MAX_GENERATE_ATTEMPTS):
            cand = "".join(rng.sample(CODE_ALPHABET, CODE_LENGTH))
            if cand not in taken:
                code = cand
                break
        if code is None:
            space = map(
                "".join,
                itertools.permutations(sorted(CODE_ALPHABET),
                                       CODE_LENGTH),
            )
            code = next((c for c in space if c not in taken), None)
        if code is None:
            raise RuntimeError("item-code space exhausted (10,626)")
        taken.add(code)
        out.append(code)
    return out


class _advisory_lock:
    """Local-only O_CREAT|O_EXCL file lock (steals after 60s stale).

    VPS-vs-local races are NOT covered — the verify step in
    reserve/confirm handles those (D-IC4).
    """

    def __enter__(self) -> "_advisory_lock":
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                self._fd = os.open(
                    str(LOCK_PATH),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.write(self._fd, str(os.getpid()).encode())
                return self
            except FileExistsError:
                try:
                    if time.time() - LOCK_PATH.stat().st_mtime > \
                            LOCK_STALE_SECONDS:
                        LOCK_PATH.unlink()
                        continue
                except OSError:
                    pass
                if time.time() > deadline:
                    raise TimeoutError(
                        "item-code lock busy >10s "
                        "(data/.item_code_lock)")
                time.sleep(0.1)

    def __exit__(self, *exc) -> None:
        try:
            os.close(self._fd)
        finally:
            try:
                LOCK_PATH.unlink()
            except OSError:
                pass
```

`tests/test_item_codes.py` — mandatory cases (spec §13.2):

- `test_is_valid_code_accepts_abc` / rejects `ABA` (repeat), `AB` ,
  `ABCD`, `ABI`/`ABL`/`ABO` (excluded letters), lowercase handled
- `test_alphabet_excludes_i_l_o` (23 letters, exact string)
- `test_generate_codes_unique_and_valid` (n=200, `existing=set()`)
- `test_generate_codes_avoids_existing`
- `test_generate_codes_deterministic_with_seed`
- `test_registry_roundtrip_atomic` (save → load; corrupt JSON → {})
- `test_retired_codes_uppercased`

**Verify:**
`python -m py_compile core/item_codes.py`
`python -m pytest tests/test_item_codes.py -q`

---

### S4 — `core/item_codes.py` sheet layer (append to S3 module) + tests

**Files:** `core/item_codes.py` (append), `tests/test_item_codes.py`
(append). Reuse the `FakeWorksheet` pattern from
`tests/test_cli.py:51-77` (copy the class into this test file).

Append to `core/item_codes.py`:

```python
def sheet_codes(worksheet) -> set:
    """Live valid Col R values — ONE get_all_values read."""
    values = worksheet.get_all_values()
    codes: set = set()
    for row in values[1:]:
        cell = (str(row[ITEM_CODE_COL]).strip().upper()
                if len(row) > ITEM_CODE_COL else "")
        if cell and is_valid_code(cell):
            codes.add(cell)
    return codes


def _spreadsheet_id(worksheet) -> str:
    """Best-effort spreadsheet id for seeding ("" when unknown)."""
    sheet = getattr(worksheet, "spreadsheet", None)
    return str(getattr(sheet, "id", "") or "")


def reserve_code(worksheet, row_index: int) -> str:
    """Pick + return ONE unused code for a NEW row (§8.2).

    NO sheet write here: add_product_row includes the code in its
    atomic A:S row write (§5); call confirm_code after that write.
    Taken-set = registry (retired) + live Col R.
    """
    with _advisory_lock():
        registry = load_registry()
        taken = retired_codes(registry) | sheet_codes(worksheet)
        seed = f"{_spreadsheet_id(worksheet)}:{len(registry)}"
        return generate_codes(taken, 1, seed=seed)[0]


def confirm_code(
    code: str, row_index: int, *, spreadsheet_id: str = ""
) -> None:
    """Persist a code AFTER its row write succeeded (idempotent).

    Raises:
        RuntimeError: the code is already registered to a DIFFERENT
        row — caller regenerates and retries (optimistic loop).
    """
    with _advisory_lock():
        registry = load_registry()
        entry = registry.get(str(code).upper())
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if entry and entry.get("row") == row_index:
            return
        if entry:
            raise RuntimeError(
                f"item code {code} already registered to row "
                f"{entry.get('row')} — collision; regenerate")
        registry[str(code).upper()] = {
            "row": row_index, "assigned_at": now,
            "sheet": spreadsheet_id,
        }
        save_registry(registry)


def verify_code(worksheet, row_index: int, code: str) -> bool:
    """Re-read Col R: True when `row_index` holds `code` AND no other
    row does (optimistic concurrency check, §8.2)."""
    values = worksheet.get_all_values()
    owners = []
    for i, row in enumerate(values[1:], start=2):
        cell = (str(row[ITEM_CODE_COL]).strip().upper()
                if len(row) > ITEM_CODE_COL else "")
        if cell == str(code).upper():
            owners.append(i)
    return owners == [row_index]


def ensure_codes(worksheet, *, dry_run: bool = False) -> dict:
    """Backfill: assign codes to every named row with empty Col R.

    Computes the full assignment in memory first, single-cell write
    per row R{row}, one final verify re-read; collisions regenerate
    (§8.1 batch discipline, §8.2 loop).

    Returns:
        dict {planned, written, skipped, failed, codes: list[str]}.
    """
    sid = _spreadsheet_id(worksheet)
    values = worksheet.get_all_values()
    with _advisory_lock():
        registry = load_registry()
        taken = retired_codes(registry) | sheet_codes(worksheet)
        planned: list[tuple[int, str]] = []
        skipped = 0
        for i, row in enumerate(values[1:], start=2):
            cell = (str(row[ITEM_CODE_COL]).strip().upper()
                    if len(row) > ITEM_CODE_COL else "")
            if cell:
                skipped += 1
                continue
            if not (row and str(row[0]).strip()):
                continue
            code = generate_codes(taken, 1, seed=f"{sid}:{i}")[0]
            taken.add(code)
            planned.append((i, code))
        if dry_run or not planned:
            return {"planned": len(planned), "written": 0,
                    "skipped": skipped, "failed": 0,
                    "codes": [c for _r, c in planned]}
        written = failed = 0
        for row_index, code in planned:
            try:
                worksheet.update(values=[[code]],
                                 range_name=f"R{row_index}")
                written += 1
            except Exception:
                failed += 1
                continue
            confirm_code(code, row_index, spreadsheet_id=sid)
        # Verify pass: concurrent duplicate -> regenerate once (D-IC4)
        for row_index, code in planned:
            if verify_code(worksheet, row_index, code):
                continue
            alt = generate_codes(
                taken | {code}, 1,
                seed=f"{sid}:fix{row_index}")[0]
            worksheet.update(values=[[alt]],
                             range_name=f"R{row_index}")
            confirm_code(alt, row_index, spreadsheet_id=sid)
            taken.add(alt)
        return {"planned": len(planned), "written": written,
                "skipped": skipped, "failed": failed,
                "codes": [c for _r, c in planned]}
```

Mandatory test cases (spec §13.2):

- `test_sheet_codes_reads_col_r` (FakeWorksheet with header A..S)
- `test_reserve_code_unused_and_registered_avoided`
- `test_confirm_code_idempotent_same_row` /
  `test_confirm_code_collision_raises`
- `test_verify_code_true_single_owner` /
  `test_verify_code_false_on_injected_collision` (simulate the
  concurrent writer: mutate the fake so another row holds the code)
- `test_ensure_codes_backfills_all_empty_named_rows` — 200-row
  synthetic fixture: all codes unique, valid shape, no I/L/O, no
  repeated letter; registry entries == written count
- `test_ensure_codes_idempotent_second_run` (second run planned=0,
  skipped=all)
- `test_ensure_codes_dry_run_writes_nothing`
- `test_lock_roundtrip` (enter/exit removes lock file; nested second
  lock raises TimeoutError quickly — patch LOCK_TIMEOUT_SECONDS=0.2)

**Verify:**
`python -m py_compile core/item_codes.py`
`python -m pytest tests/test_item_codes.py -q`

---

### S5 — `core/preferences.py` read model + prompts (new file — complete code) + tests

**Files:** NEW `core/preferences.py`, NEW `tests/test_preferences.py`.

```python
#!/usr/bin/env python3
"""Col Q/R/S read model, prompts, and the single P writer (§6, §8).

Single-writer rule (§8.3): EVERY 'P' write goes through
set_preferred. Wednesday sync never touches S; `prefer` is the only
writer. Sheet-side multi-P corruption is DETECTED (topmost P wins
until `prefer --code` fixes it) — never auto-deleted.
"""
from __future__ import annotations

from core.subcategory import NEEDS_REVIEW, normalize_subcategory

SUBCATEGORY_HEADER = "Sub_Category"   # Col Q (idx 16)
ITEM_CODE_HEADER = "Item_Code"        # Col R (idx 17)
PREFERRED_HEADER = "Preferred"        # Col S (idx 18)
SUBCATEGORY_COL = 16
ITEM_CODE_COL = 17
PREFERRED_COL = 18
PREFERRED_MARK = "P"


def _col_index(header: list, name: str):
    """Header name -> 0-based index (case-insensitive), else None."""
    for idx, cell in enumerate(header):
        if str(cell).strip().lower() == name.lower():
            return idx
    return None


def read_qrs(worksheet) -> list[dict]:
    """ONE get_all_values read -> per-row Q/R/S dicts (§9 read model).

    Rows with empty Col A are skipped. Missing Q/R/S headers yield
    empty-string fields (header-driven, robust to absence).

    Returns:
        list[dict]: {row_index, name, subcategory, item_code,
        preferred} — subcategory/``item_code`` normalised (code
        uppercased), preferred as-is ("" or "P").
    """
    values = worksheet.get_all_values()
    header = values[0] if values else []
    q = _col_index(header, SUBCATEGORY_HEADER)
    r = _col_index(header, ITEM_CODE_HEADER)
    s = _col_index(header, PREFERRED_HEADER)
    rows: list[dict] = []
    for i, row in enumerate(values[1:], start=2):
        name = str(row[0]).strip() if len(row) > 0 else ""
        if not name:
            continue
        rows.append({
            "row_index": i,
            "name": name,
            "subcategory": (normalize_subcategory(str(row[q]))
                            if q is not None and len(row) > q else ""),
            "item_code": (str(row[r]).strip().upper()
                          if r is not None and len(row) > r else ""),
            "preferred": (str(row[s]).strip()
                          if s is not None and len(row) > s else ""),
        })
    return rows


def find_by_code(rows: list[dict], code: str):
    """First row whose item_code equals `code` (uppercased), or None."""
    want = str(code or "").strip().upper()
    for row in rows:
        if row["item_code"] == want:
            return row
    return None


def get_preferred(rows: list[dict], subcategory: str):
    """The P-flagged row for a sub-category; multi-P -> TOPMOST P
    (§8.3 repair rule); no P -> None."""
    sub = normalize_subcategory(subcategory)
    flagged = [r for r in rows
               if r["subcategory"] == sub
               and r["preferred"] == PREFERRED_MARK]
    if not flagged:
        return None
    return min(flagged, key=lambda r: r["row_index"])


def list_subcategory_options(
    rows: list[dict], subcategory: str
) -> list[tuple[int, str, str]]:
    """All rows of a sub-category as (row_index, name, code) tuples."""
    sub = normalize_subcategory(subcategory)
    return [(r["row_index"], r["name"], r["item_code"])
            for r in rows if r["subcategory"] == sub]


def detect_multi_p(rows: list[dict]) -> list[dict]:
    """Sub-categories with >1 P: [{subcategory, rows: [...]}] (§8.3)."""
    by_sub: dict = {}
    for r in rows:
        if r["preferred"] == PREFERRED_MARK and r["subcategory"]:
            by_sub.setdefault(r["subcategory"], []).append(r)
    return [{"subcategory": s, "rows": rs}
            for s, rs in sorted(by_sub.items()) if len(rs) > 1]


def render_disambiguation_prompt(
    subcategory: str, options: list[tuple[int, str, str]]
) -> str:
    """EXACT §6.4 prompt text — never rephrase, never truncate names."""
    lines = [f"Sub-Category: {subcategory} - Which one would you "
             f"like to make your preferred item?"]
    for n, (_row, name, code) in enumerate(options, 1):
        lines.append(f"{n} - {name} - {code}")
    lines.append("Or: Not in list? Provide another keyword for "
                 "live search.")
    return "\n".join(lines)


def render_override_warning(name: str, subcategory: str) -> str:
    """EXACT §6.5 warning text — relay verbatim."""
    return (f"⚠️ Warning: [{name}] is not your preferred item for "
            f"sub-category [{subcategory}].\n"
            "Would you like to switch your preferred item in the "
            "sheet?\n"
            "Reply 'switch' to make it preferred, or 'keep' to "
            "continue without switching.")
```

`tests/test_preferences.py` — mandatory cases (spec §13.3/13.4):

- `test_read_qrs_parses_all_three_columns` (FakeWorksheet, header
  A..S, 3 data rows)
- `test_read_qrs_missing_headers_yield_empty_fields`
- `test_get_preferred_returns_p_row` / `test_get_preferred_none`
- `test_get_preferred_multi_p_topmost_wins_no_deletion`
- `test_list_subcategory_options_shape`
- `test_detect_multi_p_finds_only_excess`
- `test_prompt_exact_text` — golden compare against the §6.4 block:

```
Sub-Category: eggs - Which one would you like to make your preferred item?
1 - Woolworths 12 Extra Large Free Range Eggs 700g - ABC
2 - Coles 700g Free Range Eggs XL - DEF
Or: Not in list? Provide another keyword for live search.
```

- `test_override_warning_exact_text` (§6.5 golden)

**Verify:**
`python -m py_compile core/preferences.py`
`python -m pytest tests/test_preferences.py -q`

---

### S6 — `set_preferred` (append to preferences) + tests

**Files:** `core/preferences.py` (append), `tests/test_preferences.py`
(append).

```python
def set_preferred(worksheet, code: str) -> dict:
    """Clear-then-set ONE 'P' in `code`'s sub-category (§8.1).

    Steps: read Q+S -> compute the full S-vector for the
    sub-category's row span (non-members keep their existing S value
    so OTHER sub-categories' flags are never clobbered) -> ONE range
    write S{top}:S{bottom} -> re-read verify (exactly one P).

    Args:
        worksheet: connected gspread Worksheet.
        code: 3-letter Item-Code (case-insensitive).

    Returns:
        dict {wrote, row_index, subcategory, cleared,
        range_written, error} — error non-empty on any abort.
    """
    want = str(code or "").strip().upper()
    if not want:
        return {"wrote": False, "row_index": None, "subcategory": "",
                "cleared": 0, "range_written": "",
                "error": "code is required"}
    rows = read_qrs(worksheet)
    target = find_by_code(rows, want)
    if target is None:
        return {"wrote": False, "row_index": None, "subcategory": "",
                "cleared": 0, "range_written": "",
                "error": f"no row holds item-code {want}"}
    sub = target["subcategory"]
    if not sub:
        return {"wrote": False, "row_index": target["row_index"],
                "subcategory": "", "cleared": 0, "range_written": "",
                "error": "row has no sub-category "
                         "(run backfill-subcategories)"}
    by_index = {r["row_index"]: r for r in rows}
    members = {r["row_index"] for r in rows
               if r["subcategory"] == sub}
    top = min(members)
    bottom = max(members)
    vector: list[list[str]] = []
    cleared = 0
    for idx in range(top, bottom + 1):
        row = by_index.get(idx)
        if idx not in members:
            # Preserve other sub-categories' flags (never clobber).
            vector.append([row["preferred"] if row else ""])
        elif idx == target["row_index"]:
            vector.append([PREFERRED_MARK])
        else:
            if row and row["preferred"] == PREFERRED_MARK:
                cleared += 1
            vector.append([""])
    range_name = f"S{top}:S{bottom}"
    worksheet.update(values=vector, range_name=range_name)
    # Verify: exactly one P, on the target row (§8.1 step 4).
    check = read_qrs(worksheet)
    flags = [r for r in check
             if r["subcategory"] == sub
             and r["preferred"] == PREFERRED_MARK]
    if len(flags) != 1 or flags[0]["row_index"] != target["row_index"]:
        return {"wrote": False, "row_index": target["row_index"],
                "subcategory": sub, "cleared": cleared,
                "range_written": range_name,
                "error": "verify failed — check the sheet manually"}
    return {"wrote": True, "row_index": target["row_index"],
            "subcategory": sub, "cleared": cleared,
            "range_written": range_name, "error": ""}
```

Mandatory tests (spec §13.3):

- `test_set_preferred_sets_and_clears_sibling_one_write` — two rows
  in "eggs", set P on second: exactly ONE `update` call observed with
  range `S2:S3`, final state `["", "P"]`
- `test_set_preferred_interleaved_other_subcategory_preserved` —
  rows ordered eggs/milk/eggs; setting eggs P must NOT clear milk's P
  (S-vector carries milk's P through)
- `test_set_preferred_unknown_code_errors`
- `test_set_preferred_row_without_subcategory_errors`
- `test_set_preferred_verify_failure_detected` (FakeWorksheet
  subclass that corrupts S on write → wrote=False + error)

**Verify:**
`python -m pytest tests/test_preferences.py -q`

---

### S7 — Pending-run IO + shop resolver (append to preferences) + tests

**Files:** `core/preferences.py` (append),
`tests/test_preferences.py` (append).

```python
import json  # (place at module top with the other imports)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PENDING_PATH = DATA_DIR / "shop_pending.json"  # patchable
PENDING_STALE_HOURS = 24


def load_pending(path=None):
    """Load the halted-run file; None when absent/corrupt (D-P3)."""
    from pathlib import Path
    path = Path(path) if path else PENDING_PATH
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except (OSError, ValueError):
        return None


def save_pending(pending: dict, path=None) -> None:
    """Atomic write (tempfile + os.replace) — queue JSON pattern."""
    import os
    import tempfile
    from pathlib import Path
    path = Path(path) if path else PENDING_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(pending, fh, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def clear_pending(path=None) -> None:
    """Remove the pending file (missing_ok)."""
    from pathlib import Path
    path = Path(path) if path else PENDING_PATH
    try:
        path.unlink()
    except OSError:
        pass


def is_stale(pending: dict, *, now=None) -> bool:
    """True when the run started > PENDING_STALE_HOURS ago (§6.3)."""
    from datetime import datetime, timedelta, timezone
    try:
        started = datetime.fromisoformat(str(pending.get("started_at")))
    except ValueError:
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return now - started > timedelta(hours=PENDING_STALE_HOURS)


def resolve_shop_items(worksheet, items: list[str]) -> dict:
    """Deterministic shop read-side state machine (§6.2 steps 2-5).

    Category mode: normalised item equals a live Col Q value OR a
    taxonomy label (core.subcategory.all_labels). Product mode:
    exact Col A match (lookup-chain Step 1 equivalence); no exact
    match falls through to compare with the raw text.

    Args:
        worksheet: connected gspread Worksheet.
        items: user/agent-normalised item strings.

    Returns:
        dict with keys:
          compare: list[(user_item, col_a_name)] — price these rows;
          halted:  list[{item, subcategory,
                       options: [(row, name, code)]}] (S1);
          cold:    list[{item, subcategory}] (S0);
          warns:   list[{item, name, subcategory}] (S5 override);
          notes:   list[str] — multi-P ⚠️ lines (§8.3).
    """
    from core.subcategory import all_labels
    rows = read_qrs(worksheet)
    norm_map = {}  # normalised Col A -> row (first wins)
    for r in rows:
        key = normalize_subcategory(r["name"])
        norm_map.setdefault(key, r)
    sub_labels = {normalize_subcategory(x) for x in all_labels()}
    for r in rows:
        if r["subcategory"]:
            sub_labels.add(r["subcategory"])

    compare: list = []
    halted: list = []
    cold: list = []
    warns: list = []
    notes: list = []
    for item in items:
        key = normalize_subcategory(item)
        if key in sub_labels:  # ---- category mode (S4/S1/S0) ----
            members = [r for r in rows if r["subcategory"] == key]
            if not members:
                cold.append({"item": item, "subcategory": key})
                continue
            flagged = [r for r in members
                       if r["preferred"] == PREFERRED_MARK]
            if len(flagged) > 1:
                topmost = min(flagged,
                              key=lambda r: r["row_index"])
                notes.append(
                    f"⚠️ sub-category '{key}' has "
                    f"{len(flagged)} P flags — topmost (row "
                    f"{topmost['row_index']}) wins until "
                    f"'prefer --code {topmost['item_code']}' fixes it")
                flagged = [topmost]
            if flagged:
                compare.append((item, flagged[0]["name"]))
            else:
                halted.append({
                    "item": item, "subcategory": key,
                    "options": [(r["row_index"], r["name"],
                                 r["item_code"])
                                for r in members],
                })
        else:  # ---- product mode (S5) ----
            hit = norm_map.get(key)
            if hit is not None and hit["subcategory"]:
                pref = get_preferred(rows, hit["subcategory"])
                if pref is None or pref["row_index"] != \
                        hit["row_index"]:
                    warns.append({"item": item, "name": hit["name"],
                                  "subcategory":
                                  hit["subcategory"]})
            compare.append((item, hit["name"] if hit else item))
    return {"compare": compare, "halted": halted, "cold": cold,
            "warns": warns, "notes": notes}
```

(Tidy the inline imports to the module top during implementation —
`json`, `os`, `tempfile`, `datetime`, `Path` are placed once.)

Mandatory tests (spec §13.4):

- `test_pending_roundtrip_and_clear` (save → load → clear → None)
- `test_pending_corrupt_reads_none`
- `test_is_stale_true_after_24h` / `test_is_stale_false_fresh`
  (inject `now`)
- `test_resolve_category_mode_with_p_autoselects` (S4)
- `test_resolve_category_mode_no_p_halts_with_options` (S1 → options
  list exact shape)
- `test_resolve_category_mode_zero_rows_cold` (S0)
- `test_resolve_product_mode_warns_on_different_preferred` (S5)
- `test_resolve_product_mode_no_warning_when_preferred_matches`
- `test_resolve_multi_p_note_and_topmost_wins` (§8.3)
- `test_resolve_mixed_list_end_to_end` (eggs w/ P + apples w/o P +
  unknown → compare 1, halted 1, cold 1, warns 0)

**Verify:**
`python -m pytest tests/test_preferences.py -q`

---

### S8 — Schema upgrade: append Q/R/S

**Files:** `core/schema_upgrade.py` (2 edits).

Edit 1 — docstring line 4 area: extend the module docstring sentence
`Adds Woolworths_Specials (M), ... when they are absent.` with
`Also appends Sub_Category (Q), Item_Code (R), Preferred (S)`.

Edit 2 — replace the `NEW_COLUMNS` block at lines 33-38:

```python
NEW_COLUMNS = [
    "Woolworths_Specials",  # Col M
    "Coles_Specials",       # Col N
    "Rewards_Points",       # Col O
    "Keywords",             # Col P — user-side aliases (Phase 9.2)
    "Sub_Category",         # Col Q — granular cluster (spec §3)
    "Item_Code",            # Col R — permanent 3-letter row ID
    "Preferred",            # Col S — "P" flag, one per sub-category
]
```

Idempotency is inherited: `audit_schema` matches by normalized
header, `upgrade_schema` appends only missing columns. The live run
is manual step M1 (§Ops) — NOT part of the test suite (network).

**Verify:**
`python -m py_compile core/schema_upgrade.py`
`python core/schema_upgrade.py --dry-run` — **[Local, networked;
read-only]** prints `"planned_columns": ["Sub_Category",
"Item_Code", "Preferred"]` before M1, `"up to date"` after.

---

### S9 — `add_product_row` Q/R/S hook

**Files:** `core/sheets_sync.py`, `tests/test_sheets_sync.py`.

Edit 1 — constants: after `KEYWORDS_HEADER = "Keywords"` (~line 961)
insert:

```python
SUBCATEGORY_HEADER = "Sub_Category"   # Col Q (idx 16) — spec §3
ITEM_CODE_HEADER = "Item_Code"        # Col R (idx 17)
PREFERRED_HEADER = "Preferred"        # Col S (idx 18)
```

Edit 2 — signature: in `def add_product_row(` (line 1019), after
`special_desc: str = "",` (line 1030) insert one kwarg:

```python
    subcategory: str = "",
```

Edit 3 — row build: after the specials block (lines 1211-1213
ending `new_row[specials_col] = classify_special(...)`) insert:

```python
    # --- Q/R/S wiring (spec §5): every NEW row leaves with a
    # sub-category, a permanent code, and an EMPTY Preferred cell. ---
    from core.subcategory import (
        NEEDS_REVIEW, classify_subcategory, normalize_subcategory,
    )
    subcategory_col = _find_col(header, SUBCATEGORY_HEADER)
    item_code_col = _find_col(header, ITEM_CODE_HEADER)
    preferred_col = _find_col(header, PREFERRED_HEADER)
    label = normalize_subcategory(subcategory)
    if subcategory_col is not None:
        if not label:
            hit, confidence = classify_subcategory(
                generic_name, category)
            label = hit if confidence >= 1.0 else NEEDS_REVIEW
        new_row[subcategory_col] = label
    item_code = ""
    if item_code_col is not None and not dry_run:
        from core.item_codes import reserve_code
        item_code = reserve_code(worksheet, new_row_index)
        new_row[item_code_col] = item_code
    if preferred_col is not None:
        new_row[preferred_col] = ""  # ingestion NEVER auto-sets P (D-P2)
```

Edit 4 — `target_width` (lines 1184-1191): add three entries to the
`max(...)` call, before `len(header),`:

```python
        (subcategory_col + 1) if subcategory_col is not None else 0,
        (item_code_col + 1) if item_code_col is not None else 0,
        (preferred_col + 1) if preferred_col is not None else 0,
```

Edit 5 — after the range write (line 1222
`_update_with_backoff(worksheet, [new_row], range_name)`) insert:

```python
    if item_code:
        # Register + optimistic verify (§8.2): the A:S row write WAS
        # the reservation; a concurrent duplicate is caught here.
        from core.item_codes import confirm_code, verify_code
        confirm_code(item_code, new_row_index)
        if not verify_code(worksheet, new_row_index, item_code):
            # Concurrent writer grabbed the same code: regenerate and
            # rewrite ONLY this row's R cell, then re-verify.
            from core.item_codes import reserve_code
            item_code = reserve_code(worksheet, new_row_index)
            _update_with_backoff(
                worksheet, [[item_code]],
                f"R{new_row_index}")
            confirm_code(item_code, new_row_index)
```

(Extend the success return dict with `"item_code": item_code`.)

MERGE PATH GUARD: `update_single_price` (line 463) gets NO Q/R/S
write — add one comment line in its docstring Behavior list:
`10. Q/R/S untouched (one-line rule merge — row already owns them).`

Mandatory tests in `tests/test_sheets_sync.py` (spec §13.6):

- `test_add_row_writes_qrs_full_header` — header A..S; new row
  range `A{r}:S{r}` in ONE update; Q = classified label; R = valid
  code; S = `""`
- `test_add_row_subcategory_override_flag` — `subcategory="Eggs "`
  → Q = `eggs`
- `test_add_row_unclassifiable_gets_needs_review`
- `test_add_row_without_qrs_header_unchanged_width` — 16-col header:
  row still written, no crash (header-driven absence)
- `test_add_row_merge_leaves_qrs_untouched` — similar-name merge
  path: `update_single_price` called; Q/R/S cells of the existing
  row byte-identical; no new row
- `test_add_row_registry_confirmed` — registry file (patch
  `REGISTRY_PATH` to tmp) contains the code after write

**Verify:**
`python -m pytest tests/test_sheets_sync.py -q`

---

### S10 — `core/lookup.py` additive row metadata

**Files:** `core/lookup.py`, `tests/test_lookup.py`.

Edit 1 — `CandidateRow` (lines 96-111): add three defaulted fields
after `score: int`:

```python
    subcategory: str = ""   # Col Q (additive, spec §9)
    item_code: str = ""     # Col R
    preferred: str = ""     # Col S ("" or "P")
```

Edit 2 — `LookupIndex.__init__` (lines 181-268): after
`keywords_col = _find_col(header, KEYWORDS_HEADER)` (~line 203) add:

```python
        subcategory_col = _find_col(header, "Sub_Category")   # Q
        item_code_col = _find_col(header, "Item_Code")        # R
        preferred_col = _find_col(header, "Preferred")        # S
```

and extend the `row_dict` literal (lines 251-268) with:

```python
                "subcategory": (str(row[subcategory_col]).strip()
                                if subcategory_col is not None
                                and len(row) > subcategory_col
                                else ""),
                "item_code": (str(row[item_code_col]).strip()
                              .upper()
                              if item_code_col is not None
                              and len(row) > item_code_col
                              else ""),
                "preferred": (str(row[preferred_col]).strip()
                              if preferred_col is not None
                              and len(row) > preferred_col
                              else ""),
```

Edit 3 — `find_candidates` (line 363): pass the three fields at the
`CandidateRow(...)` construction (grep `CandidateRow(` inside
`find_candidates`; the row dict keys above are the values).

Edit 4 — `LookupResult` (lines 145-160): add three defaulted fields
after `sources: dict`:

```python
    subcategory: str = ""   # resolved row's Col Q (additive)
    item_code: str = ""     # resolved row's Col R
    preferred: str = ""     # resolved row's Col S
```

and populate them in `_finish_sheet_result` (line 708) wherever the
result is rebuilt with a known `row_index` (copy from the row dict;
defaulted construction sites elsewhere need no change — additive).

Mandatory tests (`tests/test_lookup.py`):

- `test_index_carries_qrs_metadata`
- `test_candidates_carry_subcategory_and_code`
- `test_result_metadata_absent_headers_empty` (16-col fixture)
- `test_chain_order_unchanged` — existing tests prove this; assert
  no new failures (full file run)

**Verify:**
`python -m pytest tests/test_lookup.py -q`

---

### S11 — `ProductItem` multi-buy fields

**Files:** `extractors/models.py`, `tests/test_extractors.py`.

Replace the field block (lines 42-53) ending with
`timestamp: str = field(default_factory=lambda: _now_iso())` —
insert BEFORE `timestamp`:

```python
    multi_buy_qty: int = 0        # bundle qty; 0 = no multi-buy
    multi_buy_total: float = 0.0  # bundle total $; 0.0 = none
```

Docstring: append two attribute lines after `product_id:` (lines
36-38):

```python
        multi_buy_qty: Multi-buy bundle quantity (e.g. 2 in "2 for
            $6.00"). 0 = no multi-buy (backwards compatible).
        multi_buy_total: Multi-buy bundle total in AUD. 0.0 = none.
```

Mandatory tests (`tests/test_extractors.py`):

- `test_product_item_multibuy_defaults_zero` — every existing
  constructor call site stays valid (defaults)
- `test_product_item_multibuy_roundtrip_dict` —
  `to_dict()` carries both keys
- `test_to_tuple_length_unchanged` — still 12 columns (A..L only;
  Q/R/S are written by sheets_sync, not by the model)

**Verify:**
`python -m pytest tests/test_extractors.py -q`

---

### S12 — D-MB2 live payload probe (read-only, MANUAL gate)

**[Local]** Read-only probe; writes nothing; decides S13's capture
keys. Run one live search per store and dump the RAW product payload
keys related to promos:

```powershell
python -c "from extractors.hub import *; import json, sys; sys.exit(0)"
python grocery_price_cli.py search --product "soft drink"
```

Then, to inspect raw payloads, add NOTHING to the repo — run a
throwaway probe in the temp dir
(`C:\Users\USER~1.DES\AppData\Local\Temp\kilo`):

```powershell
python -c "import sys, json; sys.path.insert(0, r'C:\Users\User.DESKTOP-R2G441H\Documents\AI related\grocery-price-tracker'); from extractors import woolworths_extractor as w; from extractors import coles_extractor as c; print([n for n in dir(w) if 'search' in n.lower()]); print([n for n in dir(c) if 'search' in n.lower()])"
```

Record (in `test.md` log): which payload keys carry multi-buy data
(WW candidates: `MultiBuy`, `PromotionId`, `WasPrice`-level siblings;
Coles: `pricing.now`-level siblings). Outcome A: keys exist → wire
them in S13. Outcome B: no keys → S13 wires NOTHING and live paths
degrade to normal pricing (D-MB2) — docx/sheet paths carry multi-buy
alone. NEVER invent promo fields.

**Manual step — requires live network + `.env`. No test depends on
its outcome (S13 handles both outcomes deterministically).**

---

### S13 — WW/Coles best-effort multi-buy capture

**Files:** `extractors/woolworths_extractor.py`,
`extractors/coles_extractor.py`. CONDITIONED on S12's recorded keys.

Woolworths — inside the specials block (lines 239-251,
`# Specials` … `special_desc = f"Save ${float(savings):.2f}"`),
append AFTER the `special_desc` chain (keep existing logic
untouched):

```python
    # D-MB2 best-effort multi-buy capture: ONLY when the payload
    # really carries it (probe 2026-09-04). Absent -> defaults 0.
    multi_buy_qty = 0
    multi_buy_total = 0.0
    promo = product.get("MultiBuy") or {}
    try:
        qty = int(promo.get("Quantity", 0) or 0)
        tot = float(promo.get("TotalPrice", 0.0) or 0.0)
        if qty >= 2 and tot > 0:
            multi_buy_qty, multi_buy_total = qty, tot
    except (TypeError, ValueError):
        pass
```

and pass `multi_buy_qty=multi_buy_qty,
multi_buy_total=multi_buy_total` into the `ProductItem(...)`
constructor (line 272). **If S12 outcome B: replace the `promo.get`
line with `promo = {}` — the block degrades to 0/0.0 and stays as
the documented hook.**

Coles — locate the `pricing` mapping (grep `pricing` in
`extractors/coles_extractor.py`; the spec verified it maps
`pricing.now/was/onlineSpecial`). Apply the same pattern:
`promo = (pricing or {}).get("multiBuy") or {}` with analogous
qty/total keys, defaulting 0/0.0, passed to its `ProductItem`.

Mandatory tests (`tests/test_extractors.py`):

- `test_ww_multibuy_captured_when_present` (fake product dict with
  `MultiBuy` → fields set)
- `test_ww_multibuy_absent_defaults_zero` (no key → 0/0.0)
- `test_ww_multibuy_garbage_tolerated` (`Quantity: "x"` → 0/0.0, no
  raise)
- `test_coles_multibuy_captured_when_present` /
  `test_coles_multibuy_absent_defaults_zero`

**Verify:**
`python -m pytest tests/test_extractors.py -q`

---

### S14 — M/N multi-buy cell encoding on write paths

**Files:** `core/sheets_sync.py`, `tests/test_sheets_sync.py`.

Two call sites classify specials into M/N:

1. `add_product_row` line ~1213:
   `new_row[specials_col] = classify_special(is_special, special_desc)`
2. `update_single_price` specials write (grep
   `classify_special(` in sheets_sync — one site inside
   `update_single_price`).

Introduce ONE shared writer (insert above `add_product_row`):

```python
def _specials_cell(is_special, special_desc: str) -> str:
    """Classify + encode a specials M/N cell (D25 + §7.2).

    classify_special vocabulary first; when the promo parses to
    product-specific multi-buy terms, the cell carries them
    ("multi-buy 2/$6.00"). Mixed "any N" promos stay the bare
    "multi-buy" marker (D-MB3 — informational only).
    """
    from core.multibuy import (
        encode_multibuy_cell, is_mixed_promo, parse_multibuy,
    )
    from extractors.specials_parser import classify_special
    kind = classify_special(bool(is_special), special_desc or "")
    if kind == "multi-buy" and not is_mixed_promo(
            special_desc or ""):
        terms = parse_multibuy(special_desc or "")
        if terms:
            return encode_multibuy_cell(*terms)
    return kind
```

Then replace BOTH call sites' `classify_special(is_special,
special_desc)` with `_specials_cell(is_special, special_desc)`.

Mandatory tests (`tests/test_sheets_sync.py`):

- `test_specials_cell_for_promo_encodes_terms`
  ("2 for $6.00" → `multi-buy 2/$6.00`)
- `test_specials_cell_any_promo_stays_bare` ("Any 2 | $9" →
  `multi-buy`)
- `test_specials_cell_discount_unchanged` (was/save → `discount`)
- `test_specials_cell_no_unchanged`
- `test_decode_roundtrip_via_multibuy` (cell decodes back to (2,
  6.0))

**Verify:**
`python -m pytest tests/test_sheets_sync.py tests/test_multibuy.py -q`

---

### S15 — Comparator: multi-buy terms on BasketItem

**Files:** `core/price_comparator.py`, `tests/test_comparator.py`.

Edit 1 — `BasketItem` (after `specials: dict` line 57):

```python
    multibuy: dict = field(default_factory=dict)
    # store -> (qty, bundle_total) for RATE-ELIGIBLE multi-buy terms
    # (mixed "any N" promos are display-only and never appear here).
```

Edit 2 — module helper (insert above `compare_basket`, ~line 118):

```python
def effective_price(item: BasketItem, store: str) -> float:
    """Math price for a store: multi-buy effective unit rate when
    rate-eligible terms exist (§7.3 rule 1), else the raw price.

    Args:
        item: the BasketItem.
        store: "woolworths" | "coles".

    Returns:
        float: effective unit price in AUD.
    """
    terms = item.multibuy.get(store)
    if terms:
        from core.multibuy import effective_unit_rate
        return effective_unit_rate(terms[0], terms[1])
    return item.prices[store]
```

Edit 3 — decode during the step-3 rebuild loop (lines 189-207):
inside the `for i, item in enumerate(items):` loop, before the
rebuild, compute terms; add `multibuy=mb,` to the `BasketItem(...)`
rebuild (the loop's comment at lines 200-201 exists precisely
because dropped fields bite):

```python
        from core.multibuy import (
            decode_multibuy_cell, is_mixed_promo, parse_multibuy,
        )
        mb: dict = {}
        for store in item.prices:
            desc = str(item.specials.get(store, "") or "")
            terms = decode_multibuy_cell(desc)  # sheet cell first
            if terms is None:
                terms = parse_multibuy(desc)    # live desc fallback
            if terms and not is_mixed_promo(desc):
                mb[store] = terms
```

Mandatory tests (`tests/test_comparator.py`):

- `test_effective_price_uses_rate_when_terms`
- `test_effective_price_raw_when_no_terms`
- `test_decode_sheet_cell_and_live_desc_paths` (BasketItem built
  via `_gather_lookup_prices` with FakeWorksheet-style rows; assert
  `item.multibuy["woolworths"] == (2, 6.0)`)
- `test_mixed_any_promo_never_yields_terms` (specials "Any 2 | $9"
  → `multibuy == {}`)

**Verify:**
`python -m pytest tests/test_comparator.py -q`

---

### S16 — Comparator: effective-rate math in totals/winner

**Files:** `core/price_comparator.py`, `tests/test_comparator.py`.

Edit 1 — step-4 raw_totals loop (lines 216-219): replace

```python
            if store in item.prices:
                total += item.prices[store]
```

with

```python
            if store in item.prices:
                total += effective_price(item, store)
```

Edit 2 — step-5 discount feed (lines 236-241): replace
`"price": item.prices["woolworths"],` with
`"price": effective_price(item, "woolworths"),` (WW display
discounts apply AFTER rate computation, display-only — §7.3 rule 4).

Edit 3 — format_report discount_items feed (line 804): replace
`raw_price = item.prices["woolworths"]` with
`raw_price = effective_price(item, "woolworths")`.

Winner/totals/`optimize` all flow from `raw_totals`/`final_totals` —
no other math changes (§7.3 rule 1).

Mandatory tests (spec §13.5):

- `test_multibuy_rate_flips_winner` — item priced WW $3.50 (multi-buy
  2/$6.00 → $3.00/u) vs Coles $3.20: WW wins
- `test_multibuy_totals_use_effective_rate` — raw_totals reflect
  3.00, not 3.50
- `test_normal_pricing_unchanged_without_multibuy` — golden on an
  existing fixture (regression)
- `test_ww_discounts_apply_after_rate` — discounted WW line computes
  from 3.00

**Verify:**
`python -m pytest tests/test_comparator.py -q`

---

### S17 — telegram_format: `MAX_NAME_WIDTH = 60` + tests

**Files:** `core/telegram_format.py`, `tests/test_telegram_format.py`.
(The `multibuy_tag` helper already landed in S2.)

Edit — line 47: `MAX_NAME_WIDTH = 24` → `MAX_NAME_WIDTH = 60`.
`MAX_BLOCK_WIDTH = 34` (line 48) UNCHANGED (§10). Update the
adjacent comment (line 46) to:
`# Width budgets (spec §3 + §10): names full up to 60 cells; fenced
# phone-fit tables stay 34.`

`item_block` (line 355) keeps calling
`truncate(name, MAX_NAME_WIDTH)` — no signature change.

Mandatory test updates (`tests/test_telegram_format.py`):

- UPDATE every test that assumes 24-cell truncation (lines ~78-93,
  ~237-251): a 52-char name ("AJI CRISPY FRY BREADING MIX ORIGINAL
  WITH GRAVY MIX 62G" = 52 chars) renders UNTRUNCATED
- `test_max_name_width_is_60` — `self.assertEqual(tf.MAX_NAME_WIDTH,
  60)`
- `test_fenced_table_truncates_with_ellipsis` (line 130) stays green
  (34-cell budget untouched — spec §13.7)
- `test_multibuy_tag_exact_text`

**Verify:**
`python -m pytest tests/test_telegram_format.py -q`

---

### S18 — Comparator display: tag + mandatory footnote

**Files:** `core/price_comparator.py`, `tests/test_comparator.py`.

Edit 1 — WW line (format_report lines 722-736): compute `eff =
effective_price(item, "woolworths")`, use it in BOTH branches
(`format_discounted_price(eff, ...)` / `f"${eff:.2f}"`), and when
`"woolworths" in item.multibuy` append the tag:

```python
            if "woolworths" in item.multibuy:
                from core.telegram_format import multibuy_tag
                q, t = item.multibuy["woolworths"]
                ww += f"  {multibuy_tag(q, t)}"
```

Edit 2 — Coles line (lines 737-746): same pattern with
`effective_price(item, "coles")` and the tag.

Edit 3 — totals footnote (after the fenced table append, line 789):

```python
    # §7.3 rule 2: totals footnote carries the mandatory note when
    # ANY displayed price is multi-buy-derived.
    if any(item.multibuy for item in report.items):
        from core.telegram_format import MULTIBUY_NOTE
        lines.append(f"🏷️ Multi-buy rates applied. {MULTIBUY_NOTE}")
        lines.append("")
```

Mandatory tests (spec §13.5):

- `test_multibuy_line_shows_rate_tag_and_note` — rendered block
  contains `$3.00`, `🏷️ 2 for $6.00`, and the exact note text
- `test_totals_footnote_present_with_multibuy` / `..._absent_without`
- `test_non_multibuy_lines_unchanged` (regression golden)

**Verify:**
`python -m pytest tests/test_comparator.py -q`

---

### S19 — CLI parsers: 5 new commands + `--subcategory` flags

**Files:** `grocery_price_cli.py`, `tests/test_cli.py`.

Edit 1 — `build_parser()` (line 45): after the `backfill-sizes`
block (`bsz = sub.add_parser(` … line 300-307) insert:

```python
    shp = sub.add_parser(
        "shop",
        help="Shopping-list compare with sub-category preferences")
    shp.add_argument("--items", required=True, metavar="LIST",
                     help="Comma-separated item list")
    shp.set_defaults(func=_cmd_shop)

    pfr = sub.add_parser(
        "prefer",
        help="Set the preferred (P) row for a sub-category")
    pfr.add_argument("--code", default=None, metavar="CODE",
                     help="3-letter Item-Code (Col R)")
    pfr.add_argument("--pick", type=int, default=None, metavar="N",
                     help="Option number from a pending shop run")
    pfr.set_defaults(func=_cmd_prefer)

    sct = sub.add_parser(
        "subcategories",
        help="List sub-category labels + live row counts")
    sct.set_defaults(func=_cmd_subcategories)

    bsc = sub.add_parser(
        "backfill-subcategories",
        help="One-time Col Q backfill via the classifier")
    bsc.add_argument("--dry-run", action="store_true", default=False)
    bsc.set_defaults(func=_cmd_backfill_subcategories)

    bcd = sub.add_parser(
        "backfill-codes",
        help="One-time Col R Item-Code backfill")
    bcd.add_argument("--dry-run", action="store_true", default=False)
    bcd.set_defaults(func=_cmd_backfill_codes)
```

Edit 2 — search parser (lines 91-108): after `--allow-duplicate`
add:

```python
    sp2.add_argument("--subcategory", default=None, metavar="TEXT",
                     help="Override the Col Q classifier for --add-item")
```

Edit 3 — map parser (lines 222-246): after `--unit` add the same
`--subcategory` argument on `mp`.

Edit 4 — `_search_add_item` add_product_row call (lines 2121-2133):
add one kwarg line after `special_desc=chosen.special_desc,`:

```python
            subcategory=getattr(args, "subcategory", "") or "",
```

Edit 5 — `_add_from_live_search` (line 4536): add kwarg
`subcategory: str = ""` to its signature; pass
`subcategory=subcategory,` into its `add_product_row` call (line
4580). In `_cmd_map_noninteractive` (line 4980), pass
`subcategory=getattr(args, "subcategory", "") or ""` at its
`_add_from_live_search(...)` call site. (optimize `--confirm …+add`
and Wednesday Step 1c auto-link reuse these same call sites — the
hook inside `add_product_row` covers every remaining path, spec §5.)

Temporary stubs (S19 only, replaced in S20-S22 — keep suite green):

```python
def _cmd_shop(args) -> int:        # replaced in S21
    print("Error: shop not implemented yet.", file=sys.stderr)
    return 1


def _cmd_prefer(args) -> int:      # replaced in S22
    print("Error: prefer not implemented yet.", file=sys.stderr)
    return 1


def _cmd_subcategories(args) -> int:        # replaced in S20
    print("Error: subcategories not implemented yet.", file=sys.stderr)
    return 1


def _cmd_backfill_subcategories(args) -> int:   # replaced in S20
    print("Error: backfill-subcategories not implemented yet.",
          file=sys.stderr)
    return 1


def _cmd_backfill_codes(args) -> int:           # replaced in S20
    print("Error: backfill-codes not implemented yet.", file=sys.stderr)
    return 1
```

Mandatory tests (`tests/test_cli.py`):

- `test_parser_has_five_new_commands`
- `test_search_parser_accepts_subcategory_flag`
- `test_map_parser_accepts_subcategory_flag`
- `test_stub_handlers_return_1` (removed in S20-22)

**Verify:**
`python -m py_compile ..\grocery_price_cli.py` (from project root;
adjust path as needed: `python -m py_compile "C:\Users\User.DESKTOP-R2G441H\Documents\AI related\grocery_price_cli.py"`)
`python -m pytest tests/test_cli.py -q`

---

### S20 — Handlers: `subcategories`, `backfill-subcategories`, `backfill-codes`

**Files:** `grocery_price_cli.py` (replace 3 stubs),
`tests/test_cli.py`.

`_cmd_subcategories` (replace stub):

```python
def _cmd_subcategories(args) -> int:
    """Taxonomy labels + live per-label row counts (agent ref, §6.6)."""
    _load_env()
    from core.subcategory import NEEDS_REVIEW, all_labels
    from core.preferences import read_qrs
    from core.sheets_client import connect_worksheet
    print(header("Sub-Categories", "🗂️"))
    print()
    try:
        rows = read_qrs(connect_worksheet())
    except Exception as exc:
        print(warn(f"Sheet unavailable ({exc}) — labels only."))
        rows = []
    counts: dict = {}
    for r in rows:
        label = r["subcategory"] or NEEDS_REVIEW
        counts[label] = counts.get(label, 0) + 1
    for label in all_labels():
        print(kv(label, str(counts.get(label, 0))))
    for label in sorted(set(counts) - set(all_labels())
                        - {NEEDS_REVIEW}):
        print(kv(f"{label} (sheet-only)", str(counts[label])))
    print(kv(NEEDS_REVIEW, str(counts.get(NEEDS_REVIEW, 0))))
    return 0
```

`_cmd_backfill_subcategories` (replace stub; mirrors
`_cmd_backfill_sizes` at lines 5671-5735):

```python
def _cmd_backfill_subcategories(args) -> int:
    """One-time Col Q backfill (§5): classifier fills ONLY empty Q
    cells — confident labels, else the literal "needs review".
    NEVER overwrites a non-empty Q. ONE batched update."""
    _load_env()
    from core.subcategory import (
        CONFIDENT_THRESHOLD, NEEDS_REVIEW, classify_subcategory,
    )
    from core.sheets_client import connect_worksheet
    ws = connect_worksheet()
    values = ws.get_all_values()
    planned = []       # (row_index, label)
    skipped_set = 0
    for i, row in enumerate(values[1:], start=2):
        name = str(row[0]).strip() if len(row) > 0 else ""
        current = str(row[16]).strip() if len(row) > 16 else ""
        hint = str(row[1]).strip() if len(row) > 1 else ""
        if current or not name:
            if current:
                skipped_set += 1
            continue
        label, confidence = classify_subcategory(name, hint)
        planned.append(
            (i, label if confidence >= CONFIDENT_THRESHOLD
             else NEEDS_REVIEW))
    filled = sum(1 for _r, lbl in planned if lbl != NEEDS_REVIEW)
    review = len(planned) - filled
    print(header("Backfill Sub-Categories (Col Q)", "🗂️"))
    print()
    print(kv("Rows examined", str(len(values) - 1)))
    print(kv("Planned writes", str(len(planned))))
    print(kv("Filled (confident)", str(filled)))
    print(kv("needs review", str(review)))
    print(kv("Skipped (Col Q already set)", str(skipped_set)))
    print()
    if args.dry_run:
        print(warn("[DRY RUN] no sheet write"))
        return 0
    if planned:
        ws.batch_update([
            {"range": f"Q{r}", "values": [[lbl]]}
            for r, lbl in planned
        ])
        print(f"Wrote {len(planned)} Col Q cell(s) in one batched "
              f"update.")
    return 0
```

`_cmd_backfill_codes` (replace stub):

```python
def _cmd_backfill_codes(args) -> int:
    """One-time Col R backfill (§5): item_codes.ensure_codes does the
    reserve-write-verify loop; prints the count; idempotent."""
    _load_env()
    from core.item_codes import ensure_codes
    from core.sheets_client import connect_worksheet
    print(header("Backfill Item-Codes (Col R)", "🏷️"))
    print()
    result = ensure_codes(connect_worksheet(),
                          dry_run=bool(args.dry_run))
    print(kv("Planned", str(result["planned"])))
    print(kv("Written", str(result["written"])))
    print(kv("Skipped (code already set)", str(result["skipped"])))
    print(kv("Failed", str(result["failed"])))
    if args.dry_run:
        print()
        print(warn("[DRY RUN] no sheet write"))
    return 0
```

Mandatory tests (`tests/test_cli.py`, patch
`core.sheets_client.connect_worksheet` to a FakeWorksheet and
`REGISTRY_PATH`/`LOCK_PATH` to tmp):

- `test_subcategories_prints_labels_and_counts`
- `test_backfill_subcategories_fills_confident_only` — 3 empty-Q
  rows (2 classifiable, 1 "BREADING MIX") → 2 labels + 1 `needs
  review`; non-empty Q untouched (spec §13.6/D-SC2)
- `test_backfill_subcategories_never_overwrites`
- `test_backfill_subcategories_dry_run_writes_nothing`
- `test_backfill_codes_assigns_unique_codes` + idempotent re-run
- `test_backfill_codes_dry_run_writes_nothing`

**Verify:**
`python -m pytest tests/test_cli.py -q`

---

### S21 — Handler: `_cmd_shop`

**Files:** `grocery_price_cli.py` (replace stub),
`tests/test_cli.py`.

```python
def _cmd_shop(args) -> int:
    """shop --items "…": preference state machine around
    compare_basket (§6.2). Deterministic; sheet-mode pricing for
    resolved rows; halts render the §6.4 prompt exactly."""
    items = [i.strip() for i in re.split(r"[,;]+", args.items or "")
             if i.strip()]
    if not items:
        print("Error: --items is required (comma-separated list).",
              file=sys.stderr)
        return 1
    _load_env()
    from core.sheets_client import connect_worksheet
    from core.preferences import (
        PENDING_STALE_HOURS, resolve_shop_items, save_pending,
        render_disambiguation_prompt, render_override_warning,
    )
    from core.price_comparator import compare_basket, format_report
    ws = connect_worksheet()
    plan = resolve_shop_items(ws, items)
    for note in plan["notes"]:
        print(warn(note))
    if plan["compare"]:
        names = [name for _item, name in plan["compare"]]
        report = compare_basket(names, mode="sheet", worksheet=ws)
        print(format_report(report))
        print()
    for entry in plan["halted"]:
        print(render_disambiguation_prompt(
            entry["subcategory"], entry["options"]))
        print()
    for entry in plan["cold"]:
        print(f"💬 '{entry['item']}' has no tracked products yet — "
              f"provide a keyword to live-search it (search "
              f"--product \"…\"), or drop it from this run.")
        print()
    for entry in plan["warns"]:
        print(render_override_warning(
            entry["name"], entry["subcategory"]))
        print()
    if plan["halted"]:
        from datetime import datetime, timezone
        pending = {
            "started_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            "items": items,
            "halted": plan["halted"],
        }
        save_pending(pending)
        print(warn(
            f"{len(plan['halted'])} item(s) halted — reply with a "
            f"code or option number via 'prefer --code ABC' / "
            f"'prefer --pick N' to finish (pending run saved, "
            f"{PENDING_STALE_HOURS}h window)."))
    return 0
```

Mandatory tests (`tests/test_cli.py`; patch worksheet + comparator):

- `test_shop_autoselects_preferred` (S4: table renders, P row priced)
- `test_shop_halts_with_exact_prompt` (S1: stdout contains the §6.4
  golden block verbatim; pending file written with the options)
- `test_shop_cold_item_offer` (S0 line)
- `test_shop_override_warning_exact_text` (S5 golden §6.5)
- `test_shop_multi_p_note_topmost` (§8.3)
- `test_shop_empty_items_errors` (exit 1)
- `test_shop_completed_items_render_with_halts` (mixed list: table +
  prompt both present)

**Verify:**
`python -m pytest tests/test_cli.py -q`

---

### S22 — Handler: `_cmd_prefer`

**Files:** `grocery_price_cli.py` (replace stub),
`tests/test_cli.py`.

```python
def _cmd_prefer(args) -> int:
    """prefer --code ABC / --pick N: set P (S3), then resume a
    pending shop run for that entry (§6.3)."""
    if not args.code and args.pick is None:
        print("Error: pass --code ABC or --pick N.",
              file=sys.stderr)
        return 1
    _load_env()
    from core.sheets_client import connect_worksheet
    from core.preferences import (
        clear_pending, is_stale, load_pending, save_pending,
        set_preferred,
    )
    from core.price_comparator import compare_basket, format_report
    code = (args.code or "").strip().upper()
    pending = load_pending()
    stale = pending is None or is_stale(pending)
    if stale and pending is not None:
        print(warn("Pending shop run is stale (>24h) — discarded; "
                   "re-run 'shop' for a fresh comparison."))
        clear_pending()
        pending = None
    if not code and pending:
        code = _pick_pending_code(pending, args.pick)
        if not code:
            print("Error: --pick N matched no pending option.",
                  file=sys.stderr)
            return 1
    ws = connect_worksheet()
    res = set_preferred(ws, code)
    if not res.get("wrote"):
        print(f"Error: {res.get('error', 'unknown')}",
              file=sys.stderr)
        return 1
    print(ok(f"Preferred set: {code} (row {res['row_index']}, "
             f"sub-category '{res['subcategory']}', "
             f"{res['cleared']} sibling flag(s) cleared)."))
    if pending:
        _resume_pending(ws, pending, code)
    return 0


def _pick_pending_code(pending: dict, pick: int) -> str:
    """Resolve --pick N against pending halted options (§6.4)."""
    for entry in pending.get("halted", []):
        options = entry.get("options", [])
        if options and 1 <= pick <= len(options):
            return str(options[pick - 1][2]).upper()
    return ""


def _resume_pending(ws, pending: dict, code: str) -> None:
    """Finish the halted run: compare the resolved entry, drop it
    from the pending file (clear when empty) (§6.3 S3->S4)."""
    from core.price_comparator import compare_basket, format_report
    halted = [e for e in pending.get("halted", [])
              if any(str(o[2]).upper() == code
                     for o in e.get("options", []))]
    if halted:
        print()
        print(format_report(compare_basket(
            [halted[0]["item"]], mode="sheet", worksheet=ws)))
    remaining = [e for e in pending.get("halted", []) if e not in
                 halted]
    if remaining:
        pending["halted"] = remaining
        save_pending(pending)
    else:
        from core.preferences import clear_pending
        clear_pending()
```

Mandatory tests (spec §13.4):

- `test_prefer_standalone_sets_p` (no pending → write + confirm line;
  exit 0)
- `test_prefer_pick_resolves_pending_option` (S2 → S3 write)
- `test_prefer_resumes_and_clears_pending` (table printed; pending
  file gone)
- `test_prefer_keeps_other_halted_entries`
- `test_prefer_stale_pending_discarded` (started_at 25h ago → warn +
  cleared, still sets P)
- `test_prefer_unknown_code_errors` (exit 1)
- `test_prever_requires_code_or_pick` (exit 1) — name it
  `test_prefer_requires_code_or_pick`

**Verify:**
`python -m pytest tests/test_cli.py -q`

---

### S23 — `lists` surfacing: needs review + multi-P

**Files:** `grocery_price_cli.py`, `tests/test_cli.py`.

In `_cmd_lists` (line 430): the function already does ONE
`get_all_values()`; compute from those SAME rows (spec §9 — no
second read). Insert before its final `return 0` (locate with
`def _cmd_lists` and the last return):

```python
    # §8.3 + D-SC2 surfacing: needs-review sub-categories and
    # multi-P corruption are visible in `lists` (never auto-fixed).
    needs_review = sum(
        1 for row in rows[1:]
        if len(row) > 16 and str(row[16]).strip().lower()
        == "needs review")
    if needs_review:
        print()
        print(warn(f"🗂️ {needs_review} row(s) with sub-category "
                   f"'needs review' — run 'subcategories' to view, "
                   f"re-classify via prefer/backfill."))
    flags: dict = {}
    for i, row in enumerate(rows[1:], start=2):
        if len(row) > 18 and str(row[18]).strip() == "P":
            sub = (str(row[16]).strip().lower()
                   if len(row) > 16 else "")
            if sub:
                flags.setdefault(sub, []).append(i)
    for sub, row_indexes in sorted(flags.items()):
        if len(row_indexes) > 1:
            print(warn(f"⚠️ sub-category '{sub}' has {len(row_indexes)}"
                       f" P flags (rows {row_indexes}) — topmost wins; "
                       f"fix with 'prefer --code'."))
```

NOTE: adapt `rows`/variable names to whatever `_cmd_lists` actually
holds its `all_values` in (read the function first; the block must
use that variable). If `_cmd_lists` has no direct rows variable,
patch minimal: reuse its existing data without a new API call.

Mandatory tests (`tests/test_cli.py`):

- `test_lists_shows_needs_review_count`
- `test_lists_warns_on_multi_p`
- `test_lists_silent_when_clean`

**Verify:**
`python -m pytest tests/test_cli.py tests/test_lists_cmd.py -q`

---

### S24 — README updates (spec §14.1)

**Files:** `README.md`.

1. **Sheet schema table** (rows exist at lines 515-520, `| A |…|
   | P |…|`): append after the `| P |` row:

```markdown
| Q | Sub_Category | Granular cluster (bread, shredded cheese, eggs); "needs review" marker |
| R | Item_Code | Permanent 3-letter row ID, A–Z minus I/L/O, no repeats |
| S | Preferred | "P" flag; at most one per sub-category; set only via prefer |
```

2. **CLI table** (row pattern at line 401): append five rows in the
   same `| `command` | flags | description |` shape used there:

```markdown
| `shop` | `--items "a, b, c"` | Shopping-list compare: resolves each item to its sub-category, auto-picks the preferred (P) row, asks ONE question when none is preferred |
| `prefer` | `--code ABC` / `--pick N` | Sets the Preferred (P) row for a sub-category; resumes a pending shop run |
| `subcategories` | — | Lists sub-category labels + live row counts |
| `backfill-subcategories` | `[--dry-run]` | One-time Col Q backfill; classifier-confident labels only, else "needs review"; never overwrites |
| `backfill-codes` | `[--dry-run]` | One-time Col R Item-Code backfill; unique permanent codes; idempotent |
```

3. **Telegram Style Kit** section: add
   `MAX_NAME_WIDTH = 60 — full product names everywhere; fenced
   tables stay 34 cells.`
4. **New "Multi-buy pricing" section** (after the specials/discounts
   content): rate math (`rate = total / qty`), the mandatory note
   text, M/N cell form `multi-buy 2/$6.00`, D-MB2 degradation (live
   paths fall back to normal pricing when payloads carry no
   multi-buy), D-MB3 (mixed "any N" informational only).
5. **New "Shopping list & preferences" section**: pointer to
   PROJECT-MAP §6F; the S0–S5 state machine in five bullet lines;
   `Item_Code ≠ queue codes` note.

**Verify:** markdown renders (eyeball); grep:

```powershell
Select-String -Path README.md -Pattern "Sub_Category|Item_Code|shop|prefer" | Measure-Object -Line
```

---

### S25 — PROJECT-MAP §6F (spec §14.2)

**Files:** `PROJECT-MAP.md`.

1. **§5 commands table** (line 172 area): add the five command rows
   (same plain-language style as the `backfill-sizes` row).
2. **New §6F** after §6E (line 255, before `## 7.`):

```markdown
### F. Shopping list (shop) — the preference flow

1. You send a list ("eggs, apples, bread"). The agent normalises each
   item to a sub-category (or a specific product) and calls
   `shop --items "…"`.
2. Each sub-category with a Preferred (P) row is compared
   automatically using that row.
3. No P yet? The CLI asks ONE question (the numbered prompt with
   full names + codes). Reply with a code or number → `prefer` sets
   P and finishes the comparison.
4. Not tracked at all? Offer a keyword → normal `search --add-item`
   flow; the new row arrives with Q/R/S filled and S empty — the
   next `shop` asks the one question (nothing is ever auto-preferred).
5. Asked for a specific variant that is NOT your preferred? You get
   the comparison plus the switch/keep warning. "keep" writes
   nothing.
Item-Code (Col R) is a DIFFERENT namespace from queue codes: `prefer
ABC` vs `todo done ABC` never collide.
```

3. **§2 sheet columns** (line 66 area): extend the Products_Master
   column description with Q/R/S (one line each).
4. **"The 7 lists" section** (line 11): add note
   `needs review` sub-categories surface in `lists`.

**Verify:** `Select-String -Path PROJECT-MAP.md -Pattern "6F|Item-Code|needs review"`.

---

### S26 — SKILL.md + catalogue regen + test.md log (spec §14.3-4)

**Files:** `claw-skills/grocery-price/SKILL.md`,
`claw-skills/claw_skills_easy.md` (generated),
`grocery-price-tracker/test.md`.

SKILL.md edits (sections by current heading lines):

1. `## Subcommands → user intent` (line 31): add three rows —
   shopping list → `shop --items`; "make X my usual/preferred" →
   `prefer --code ABC`; "what sub-categories exist" →
   `subcategories`.
2. `### NL → subcommand mappings` (line 160): add
   `"eggs, apples, bread" / "shop for …" → shop --items "…"`,
   `"ABC is my usual" / "make ABC preferred" → prefer --code ABC`.
3. `### Disambiguation` (line 226): add — when `shop` prints the
   numbered sub-category prompt, relay it **VERBATIM, never rephrase
   codes or numbers**; when the user replies with a code/number,
   call `prefer --code X` / `prefer --pick N`. Same for the
   switch/keep warning (§6.5 text): relay verbatim; route "switch"
   to `prefer --code <requested row's code>`; "keep" → nothing.
4. `## Hard rules` (line 273): add — never invent multi-buy prices
   (the CLI derives them); always forward the multi-buy note with
   the price; keep the B5 never-browse rule unchanged.
5. `## Normalisation` note under `## How to answer` (line 122):
   normalise list items against `subcategories` output before
   calling `shop` (§6.1 contract).

MANDATORY catalogue sync (rule 04) — **[Local]** from
`C:\Users\User.DESKTOP-R2G441H\Documents\AI related`:

```powershell
python skills_doc.py
python skills_doc.py --check
```

`--check` MUST print `OK` (exit 0). Both files are then committed
together and synced to the VPS in S27.

`test.md` (project root): append this round's execution log — steps
done, probe outcome (S12), test counts before/after, any deviations.

**Verify:**
`python skills_doc.py --check` prints `OK`.

---

### S27 — Deploy & one-time operations

Order matters: schema first (M1), then backfills (M2), then code
deploy (M3), then verification (M4).

**M1 — Schema append (manual, ONE time) [Local, networked]**

```powershell
python core/schema_upgrade.py --dry-run    # expect planned Q/R/S
python core/schema_upgrade.py              # writes Q1:S1 headers
python core/schema_upgrade.py --dry-run    # expect "up to date"
```

Idempotent; A–P data untouched (existing audit logic, spec §13.1).

**M2 — Backfills (manual, ONE time) [Local, networked]**

```powershell
python ..\grocery_price_cli.py backfill-subcategories --dry-run
python ..\grocery_price_cli.py backfill-subcategories
python ..\grocery_price_cli.py backfill-codes --dry-run
python ..\grocery_price_cli.py backfill-codes
```

(Correct CLI invocation per existing conventions — run from the
project root with the CLI path used today, e.g.
`python ..\grocery_price_cli.py …` or the absolute path.)

**M3 — Deploy code to VPS [Local]**

```powershell
python scripts/deploy_vps.py            # scp mode (default)
```

Skill files (mandatory rule 04) — scp BOTH to
`/home/ubuntu/openclaw/tasks/ai-tools/claw-skills/grocery-price/`
and the parent catalogue dir respectively, then verify md5 on both
sides (the rule's exact requirement):

```powershell
scp "claw-skills\grocery-price\SKILL.md" ubuntu@<vps>:/home/ubuntu/openclaw/tasks/ai-tools/claw-skills/grocery-price/SKILL.md
scp "claw-skills\claw_skills_easy.md" ubuntu@<vps>:/home/ubuntu/openclaw/tasks/ai-tools/claw-skills/claw_skills_easy.md
# md5 verify local vs remote for both files (certutil / md5sum)
```

**[VPS]** After deploy: no backfill re-run needed (M2 wrote the
shared sheet once). Sanity:

```bash
cd /home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker
python3 -m pytest tests/ -q      # or the VPS's established runner
python3 grocery_price_cli.py subcategories
```

**M4 — Full verification (§13 matrix) [Local]**

```powershell
python -m pytest tests/ -q        # full suite: 621 baseline + new,
                                  # ZERO skips (0 skipped in summary)
```

**Commits (after each phase, concise messages):**

```powershell
# inner repo (grocery-price-tracker)
git add core/ extractors/ tests/ README.md PROJECT-MAP.md test.md implementation-plan.md
git commit -m "Q/R/S + shop + multi-buy: core modules, ingestion, comparator, tests"
# parent repo (AI related) — CLI + skill
git add grocery_price_cli.py claw-skills/grocery-price/SKILL.md claw-skills/claw_skills_easy.md
git commit -m "grocery CLI: shop/prefer/subcategories/backfills + skill contract"
```

Review `git diff --staged` for secrets before every commit
(security rule). Push/PR only when explicitly requested.

---

## 4. Test plan (all MANDATORY — zero-skip)

### 4.1 Unit (new modules)

| Target | Cases (min) | File |
|---|---|---|
| normalize/classify/all_labels | §S1 list: spec examples, compound-before-generic, breading/breadcrumbs negatives, hint-never-rescues, 0/1 confidence | `tests/test_subcategory.py` |
| multibuy codec | §S2 list: FOR/ANY parse, Cream For Men negative, qty=1 negative, rate math + raises, encode/decode roundtrip, bare legacy, mixed-promo flag, exact note | `tests/test_multibuy.py` |
| item codes | §S3-S4 list: validity (alphabet, distinct, length), 200-code uniqueness, determinism, registry IO, reserve/confirm/verify, injected-collision retry, ensure_codes 200-row fixture, idempotency, lock | `tests/test_item_codes.py` |
| preferences | §S5-S7 list: read_qrs, get_preferred (+multi-P topmost), options, prompt/warning EXACT goldens, set_preferred one-write + interleave preservation + verify-failure, pending IO + 24h staleness, resolver S0/S1/S4/S5 + multi-P + mixed list | `tests/test_preferences.py` |

### 4.2 Functional (updated surfaces)

| Target | Cases | File |
|---|---|---|
| add_product_row | Q/R/S on create (one A:S write), --subcategory override, needs-review path, absent-header degradation, merge leaves Q/R/S, registry confirm | `tests/test_sheets_sync.py` |
| specials cell | FOR→encoded terms, ANY→bare, discount/no unchanged | `tests/test_sheets_sync.py` |
| lookup | Q/R/S metadata on index/candidates/results; absent headers; chain order regression | `tests/test_lookup.py` |
| extractors | ProductItem defaults + dict roundtrip + tuple length; WW/Coles multi-buy capture present/absent/garbage | `tests/test_extractors.py` |
| comparator | terms decode (cell + live desc), mixed-ANY excluded, winner flip via rate, totals on rate, WW discount after rate, display tag + note, footnote presence, regression goldens | `tests/test_comparator.py` |
| telegram_format | width 60, 52-char name intact, fenced 34 untouched, multibuy tag exact | `tests/test_telegram_format.py` |
| CLI | parsers, subcategories, both backfills (+dry-run), shop (S0/S1/S4/S5/multi-P/mixed), prefer (standalone/pick/resume/stale/errors), lists surfacing | `tests/test_cli.py` |

### 4.3 Integration (composition, still mock-free networkless)

- shop → compare_basket(sheet) → format_report with a preferred row
  AND a multi-buy cell in the same run: table + footnote + no prompt.
- search --add-item flow (mocked live results): row created with
  Q/R/S; subsequent shop hits S1 and halts (S6 end-to-end).
- prefer --pick → pending consumed → completed table printed.

### 4.4 Failure modes (mandatory)

- Concurrent-writer simulation: FakeWorksheet that injects a
  duplicate code between write and verify → regenerate path taken;
  final state unique (spec §13.2).
- Two-P corruption fixture: detection line, topmost wins, NO
  deletion (spec §13.3).
- Stale pending (>24h): reported + discarded, pointer to re-run
  (spec §13.4).
- Registry collision on confirm_code → RuntimeError → caller retry.
- set_preferred verify mismatch → wrote=False, actionable error.
- Corrupt `shop_pending.json` / registry JSON → treated as empty.
- Lock contention → TimeoutError with actionable message.
- Empty/whitespace `--items`, unknown `--code`, out-of-range
  `--pick` → exit 1 with stderr messages.

### 4.5 Verification matrix (spec §13 → steps)

| §13 | Covered by |
|---|---|
| 1 schema | S8 + M1 (dry-run → upgrade → up to date) |
| 2 codes | S3/S4 tests + M2 |
| 3 preferences | S6 tests (one write-range observed, two-P fixture) |
| 4 state machine | S7/S21/S22 golden tests (exact §6.4/§6.5) |
| 5 multi-buy | S2/S14/S15/S16/S18 tests |
| 6 ingestion | S9 tests (all paths funnel through add_product_row; merge untouched) |
| 7 truncation | S17 tests (52-char full; fenced ≤34) |
| 8 full suite | M4 — 621 baseline + new files, zero skips |

---

## 5. Rollback

- Phase-level: `git revert` the phase commit(s) in each repo; sheet
  Q/R/S columns are additive — leaving them in place harms nothing
  (readers are header-driven and absence-tolerant).
- Data-level: Q/R/S values can be cleared with a manual sheet
  select+delete; registry `data/item_code_registry.json` is a local
  file (delete to reset). No A–P data is ever rewritten by this
  feature except explicit price updates that already existed.

## 6. Out of scope (guards for 03 Code)

- 4-letter code widening (§8.2 future decision).
- Any `core/uom.py` change; any `telegram_gateway/` change (its
  `add_product_row` call gains Q/R/S via the hook, untouched).
- Auto-setting P anywhere; Wednesday writing S; reusing deleted
  codes; persisting derived rates.
