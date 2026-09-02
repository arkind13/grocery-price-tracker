#!/usr/bin/env python3
"""Headless exact-keyword name matcher and unmapped-product queue.

Sections:
    A — Data structures (MatchResult, KeywordIndex)
    B — NameMatcher (pure matching logic)
    C — Sheet I/O (headless connection, load_keyword_index)
    D — Auto-classification (classify_product)
    E — Unmapped queue (append_unmatched, get_pending_mappings, clear_resolved)
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Section A: Data Structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MatchResult:
    """Outcome of matching one scraped product name to a Products_Master row.

    Attributes:
        matched: True if an exact keyword hit was found.
        row_index: 1-based sheet row number of the matched row
            (2 = first data row; row 1 is the header). None if unmatched.
        generic_name: Col A value of the matched row ("" if unmatched).
        store: The store this item came from ("woolworths"|"coles").
        raw_name: The original scraped product name (unmodified).
        strategy: How the match was made: "exact_keyword" or "none".
    """
    matched: bool
    row_index: Optional[int]
    generic_name: str
    store: str
    raw_name: str
    strategy: str


class KeywordIndex:
    """In-memory map of normalized store keyword -> (row_index, generic_name).

    Built once from a sheet snapshot (or mock rows) and reused across many
    NameMatcher.match() calls. Holds two internal dicts, one per store,
    keyed by the normalized keyword.

    First occurrence wins on duplicate keywords.
    """

    # Column indices in Products_Master (0-based)
    _COL_GENERIC_NAME = 0
    _COL_KW_WOOLWORTHS = 8
    _COL_KW_COLES = 9

    _STORE_COL_MAP: dict[str, int] = {
        "woolworths": _COL_KW_WOOLWORTHS,
        "coles": _COL_KW_COLES,
    }

    def __init__(self, rows: list[list[str]]) -> None:
        """Build the index from Products_Master rows (header EXCLUDED).

        Args:
            rows: list of rows; each row is a list of cell strings.
                rows[i] corresponds to sheet row i+2 (1-based, +2 for header).
            Missing/short rows and empty keyword cells are skipped.
            First occurrence wins on duplicate keywords.
        """
        self._woolworths: dict[str, tuple[int, str]] = {}
        self._coles: dict[str, tuple[int, str]] = {}

        for i, row in enumerate(rows):
            row_index = i + 2  # 1-based: row 1 = header, row 2 = first data row
            generic_name = row[self._COL_GENERIC_NAME] if len(row) > self._COL_GENERIC_NAME else ""

            self._index_store_keywords(row, row_index, generic_name)

    def _index_store_keywords(self, row: list[str], row_index: int, generic_name: str) -> None:
        """Index keyword columns for both stores from a single row."""
        store_dicts = {
            "woolworths": self._woolworths,
            "coles": self._coles,
        }
        for store, col_idx in self._STORE_COL_MAP.items():
            if len(row) <= col_idx:
                continue
            keyword = row[col_idx]
            if not keyword or not keyword.strip():
                continue
            normalized = self._normalize(keyword)
            target = store_dicts[store]
            # First occurrence wins
            if normalized not in target:
                target[normalized] = (row_index, generic_name)

    def lookup(self, store: str, raw_name: str) -> Optional[tuple[int, str]]:
        """Return (row_index, generic_name) for an exact keyword match, else None.

        Args:
            store: "woolworths"|"coles" — selects which keyword column
                (I/J) to look in.
            raw_name: the scraped product name.
        """
        store_key = store.lower()
        if store_key not in self._STORE_COL_MAP:
            return None
        normalized = self._normalize(raw_name)
        target = getattr(self, f"_{store_key}", None)
        if target is None:
            return None
        return target.get(normalized)

    @staticmethod
    def _normalize(s: str) -> str:
        """Lowercase, trim, collapse internal whitespace runs to one space."""
        return re.sub(r"\s+", " ", str(s).strip().lower())


# ---------------------------------------------------------------------------
# Section A2: duplicate-detection similarity (2026-09-02 user rule:
# "one line per product even when names differ slightly")
# ---------------------------------------------------------------------------

# Store-brand words never distinguish one product from another.
_STORE_WORDS = frozenset({"woolworths", "coles", "aldi"})

# Names whose token sets overlap at/above this ratio are the same product
# ("Classic Hommus 200g" vs "Woolworths Hommus Classic 200g" -> 1.0).
DUP_SIMILARITY_THRESHOLD = 0.9


def similarity_tokens(name: str) -> set:
    """Token set of a name for duplicate detection.

    Lowercase alphanumeric tokens with store-brand words removed and
    apostrophes collapsed ("Carman's" == "Carmans"), so "Woolworths
    Full Cream Milk 3L" and "Full Cream Milk 3L" produce the SAME set
    ({"full", "cream", "milk", "3l"}).

    Args:
        name (str): raw product name.

    Returns:
        set[str]: comparison tokens (empty set for blank input).
    """
    cleaned = str(name).lower().replace("'", "").replace("\u2019", "")
    tokens = re.findall(r"[a-z0-9]+", cleaned)
    return {t for t in tokens if t not in _STORE_WORDS}


def token_set_ratio(a: str, b: str) -> float:
    """Order-insensitive name similarity (Jaccard on token sets, 0..1).

    "Obela Classic Hommus 200g" vs "Obela Hommus Classic 200g" -> 1.0;
    "...Fruit Straps 5 pack" vs "...Fruit Straps 70g" -> well below
    the threshold (genuinely different sizes stay separate).

    Args:
        a (str): first name.
        b (str): second name.

    Returns:
        float: 0.0 when either side has no tokens; else |A∩B| / |A∪B|.
    """
    ta = similarity_tokens(a)
    tb = similarity_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# Size-like words inside a product NAME ("70G", "5 pack", "6 x 170g",
# "2L") — used to split a name into its descriptive body and its size.
_NAME_SIZE_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:x\s*\d+(?:\.\d+)?\s*)?"
    r"(?:mg|g|kg|ml|l|mm|cm|m|packs|pack|pks|pk|each|ea|ct)\b",
    re.IGNORECASE,
)


def split_name_size(name: str) -> tuple:
    """Split a product name into (body-token set, parsed size).

    The body keeps the descriptive words (store-brand words dropped);
    the LAST size-like phrase in the name is parsed via uom.parse_size
    (multipacks like "6 x 170g" become their 1020 g total). Sizes the
    uom module cannot parse (e.g. "5 pack") still leave the body — a
    pack count is not a distinguishing measurement for the one-line
    rule (a 5-pack and a 70g bag of the same product are ONE item per
    the 2026-09-02 user rule).

    Args:
        name (str): raw product name.

    Returns:
        tuple[set, ParsedSize | None]: body tokens (may be empty) and
        the parsed size (None when no parseable size phrase exists).
    """
    from core.uom import parse_size

    text = str(name or "")
    matches = list(_NAME_SIZE_RE.finditer(text))
    body = text
    parsed = None
    for m in matches:
        body = body.replace(m.group(0), " ")
        try:
            candidate = parse_size(m.group(0))
        except Exception:
            candidate = None
        if candidate is not None:
            parsed = candidate  # keep the last parseable one
    body_tokens = similarity_tokens(body)
    return body_tokens, parsed


def is_same_product(a: str, b: str) -> bool:
    """The one-line rule: are two names the SAME product?

    User rule (2026-09-02): same product = one sheet line ALWAYS. The
    ONLY thing that keeps two near-identical names apart is a DIFFERENT
    AMOUNT OF THE SAME UNIT — e.g. 200g vs 400g, 1L vs 2L (same family,
    beyond the 20% tolerance). Everything else merges: different pack
    phrasing ("5 pack" vs "70g"), different families (g vs mL), or a
    missing size on either side. Brand words still separate products
    ("A2 Full Cream Milk" vs "Full Cream Milk" differ in body tokens).

    Args:
        a (str): first product name.
        b (str): second product name.

    Returns:
        bool: True when both names should share ONE sheet line.
    """
    from core.uom import size_families_match, within_20pct

    body_a, size_a = split_name_size(a)
    body_b, size_b = split_name_size(b)
    if not body_a or not body_b:
        return False
    if len(body_a & body_b) / len(body_a | body_b) < DUP_SIMILARITY_THRESHOLD:
        return False
    if size_a is not None and size_b is not None:
        if size_families_match(size_a, size_b) and \
                not within_20pct(size_a.value, size_b.value):
            return False  # 200g vs 400g: same unit, different amount
    return True

    def __len__(self) -> int:
        """Total number of indexed keywords across both stores."""
        return len(self._woolworths) + len(self._coles)


# ---------------------------------------------------------------------------
# Section B: NameMatcher
# ---------------------------------------------------------------------------


class NameMatcher:
    """Headless exact-keyword matcher. No fuzzy logic. No input() prompts."""

    def __init__(self, index: KeywordIndex) -> None:
        self._index = index

    def match(self, item) -> MatchResult:
        """Match a single ProductItem against the keyword index.

        1. Look up item.store / item.raw_name in the index.
        2. On hit -> MatchResult(matched=True, row_index, generic_name,
           strategy="exact_keyword").
        3. On miss -> classify_product(item.raw_name), append_unmatched(...),
           return MatchResult(matched=False, row_index=None, generic_name="",
           strategy="none"). Never raises on a miss.
        """
        result = self._index.lookup(item.store, item.raw_name)
        if result is not None:
            row_index, generic_name = result
            return MatchResult(
                matched=True,
                row_index=row_index,
                generic_name=generic_name,
                store=item.store,
                raw_name=item.raw_name,
                strategy="exact_keyword",
            )
        # Miss: classify and queue
        classification = classify_product(item.raw_name)
        append_unmatched(item, classification)
        return MatchResult(
            matched=False,
            row_index=None,
            generic_name="",
            store=item.store,
            raw_name=item.raw_name,
            strategy="none",
        )

    def match_batch(self, items) -> list[MatchResult]:
        """Match many items at once (convenience; preserves input order)."""
        return [self.match(item) for item in items]


# ---------------------------------------------------------------------------
# Section C: Sheet I/O (imported from shared sheets_client)
# ---------------------------------------------------------------------------

from .sheets_client import _load_env, connect_worksheet


def load_keyword_index(worksheet=None) -> KeywordIndex:
    """Build a KeywordIndex from the live Products_Master sheet.

    Args:
        worksheet: optional pre-connected gspread Worksheet (for tests / reuse).
            If None, a fresh headless connection is opened.

    Returns:
        KeywordIndex built from all data rows (header excluded).

    Raises:
        RuntimeError: if connection or env loading fails.
    """
    if worksheet is None:
        _load_env()
        worksheet = connect_worksheet()
    all_values = worksheet.get_all_values()
    rows = all_values[1:]  # skip header row
    return KeywordIndex(rows)


# ---------------------------------------------------------------------------
# Section D: Auto-classification
# ---------------------------------------------------------------------------

_KNOWN_BRANDS: list[str] = [
    "Woolworths", "Macro", "Oatly", "Devondale",
    "A2", "Bega", "Huggies",
]

_CATEGORY_MAP: dict[str, list[str]] = {
    "Dairy": ["milk", "cheese", "yogurt", "cream", "butter"],
    "Meat": ["chicken", "beef", "lamb", "mince", "pork", "sausage"],
    "Bakery": ["bread", "wrap", "loaf", "roll", "bun", "croissant"],
    "Fruit & Veg": [
        "apple", "banana", "potato", "onion", "carrot",
        "tomato", "lettuce", "broccoli", "spinach", "avocado",
    ],
}

_SIZE_PATTERN: re.Pattern = re.compile(
    r"(\d+\.?\d*\s?(?:kg|g|l|ml|pk|pack|ea|units|oz)\b)", re.IGNORECASE
)


def classify_product(raw_name: str) -> dict:
    """Best-effort classification of an unmapped product name.

    Returns dict with keys:
        brand: known brand or first whitespace token.
        size: e.g. "1L", "500g" (or "" if none).
        category: "Dairy"|"Meat"|"Bakery"|"Fruit & Veg"|"General".
        generic_name: raw_name minus brand and size tokens (best-effort).
    """
    name_lower = raw_name.lower().strip()

    # Size extraction (first match)
    size_match = _SIZE_PATTERN.search(raw_name)
    size = size_match.group(1).strip() if size_match else ""

    # Brand detection (known brand substring match, case-insensitive)
    brand = ""
    for known in _KNOWN_BRANDS:
        if known.lower() in name_lower:
            brand = known
            break
    if not brand:
        # Fallback: first whitespace token
        brand = raw_name.split()[0] if raw_name.split() else ""

    # Category detection
    category = "General"
    for cat, keywords in _CATEGORY_MAP.items():
        for kw in keywords:
            if kw in name_lower:
                category = cat
                break
        if category != "General":
            break

    # Generic name: remove brand and size substrings
    generic_name = raw_name
    if brand:
        generic_name = re.sub(
            re.escape(brand), "", generic_name, count=1, flags=re.IGNORECASE
        )
    if size:
        generic_name = re.sub(
            re.escape(size), "", generic_name, count=1, flags=re.IGNORECASE
        )

    # Collapse whitespace and strip punctuation
    generic_name = re.sub(r"\s+", " ", generic_name).strip(" ,-")

    return {
        "brand": brand,
        "size": size,
        "category": category,
        "generic_name": generic_name,
    }


# ---------------------------------------------------------------------------
# Section E: Unmapped Queue
# ---------------------------------------------------------------------------

QUEUE_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "unmapped_queue.json"
)


def _read_queue() -> list[dict]:
    """Read the unmapped queue file. Returns [] if file missing or corrupt."""
    if not QUEUE_PATH.is_file():
        return []
    try:
        with open(QUEUE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _write_queue(entries: list[dict]) -> None:
    """Write entries to the queue file atomically via temp file + rename.

    Creates data/ directory if missing.
    Never raises — prints warning to stderr on OSError.
    """
    try:
        QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: write to temp file, then rename
        fd, tmp_path = tempfile.mkstemp(
            suffix=".json",
            prefix="unmapped_queue_",
            dir=str(QUEUE_PATH.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_fh:
                json.dump(entries, tmp_fh, indent=2, ensure_ascii=False)
            os.replace(tmp_path, str(QUEUE_PATH))
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError as exc:
        print(
            f"[WARN] Could not write unmapped queue: {exc}",
            file=sys.stderr,
        )


def append_unmatched(item, classification: dict) -> None:
    """Append an unmatched ProductItem to the queue. Non-blocking and idempotent.

    - If (store, normalized raw_name) already present: increment count, update
      last_seen, leave status/first_seen/classification as-is.
    - Else: append a new entry with status="pending".
    - Create data/ dir if missing. Create the JSON file if missing.
    - Never raises on I/O — on failure, prints warning to stderr.
    """
    try:
        queue = _read_queue()
        normalized_key = KeywordIndex._normalize(item.raw_name)
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

        # Check for existing entry by (store, normalized_key)
        for entry in queue:
            if (
                entry.get("store") == item.store
                and entry.get("normalized_key") == normalized_key
            ):
                entry["count"] = entry.get("count", 1) + 1
                entry["last_seen"] = now_iso
                # Keep the latest-seen price so map --pick can write it
                # immediately (2026-09-02: pick without price update left
                # N/A markers sitting on genuinely-matched rows).
                entry["price"] = getattr(item, "price", None)
                _write_queue(queue)
                return

        # New entry
        queue.append({
            "store": item.store,
            "raw_name": item.raw_name,
            "normalized_key": normalized_key,
            "classification": classification,
            "price": getattr(item, "price", None),
            "first_seen": now_iso,
            "last_seen": now_iso,
            "count": 1,
            "status": "pending",
        })
        _write_queue(queue)
    except Exception as exc:
        print(
            f"[WARN] append_unmatched failed: {exc}",
            file=sys.stderr,
        )


def get_pending_mappings() -> list[dict]:
    """Return all entries with status == "pending".

    Used by Claw to tell the user on Telegram which products need mapping,
    without breaking the execution flow. Returns [] if file missing/empty.
    """
    queue = _read_queue()
    return [e for e in queue if e.get("status") == "pending"]


def refresh_pending_prices(items_by_store: dict) -> int:
    """Refresh pending debt entries with the latest parsed prices.

    The unmatched debt queue predates price storage (2026-09-02) — old
    entries carry no price, so map --pick on the VPS (where the docx
    files don't exist) could not write prices. The Wednesday run calls
    this after parsing: every pending entry whose raw_name matches a
    parsed item for its store gets that item's price stored, and the
    enriched queue is scp'd to the VPS with the lists — picks then
    write prices immediately.

    Args:
        items_by_store (dict): {"woolworths": [ProductItem, ...],
            "coles": [...]} — tonight's parsed lists.

    Returns:
        int: number of entries whose price changed.
    """
    changed = 0
    try:
        queue = _read_queue()
    except Exception:
        return 0
    lookup = {}
    for store, items in (items_by_store or {}).items():
        for item in items or []:
            raw = str(getattr(item, "raw_name", "") or "").strip()
            if raw:
                lookup[(store, KeywordIndex._normalize(raw))] = \
                    getattr(item, "price", None)
    for entry in queue:
        if entry.get("status") != "pending":
            continue
        key = (entry.get("store", ""),
               KeywordIndex._normalize(str(entry.get("raw_name", ""))))
        new_price = lookup.get(key)
        if new_price is None:
            continue
        try:
            if float(new_price) <= 0:
                continue
        except (TypeError, ValueError):
            continue
        if entry.get("price") != new_price:
            entry["price"] = new_price
            changed += 1
    if changed:
        _write_queue(queue)
    return changed


def clear_resolved(store: str, raw_name: str) -> None:
    """Mark a queued entry as resolved (status="resolved"). Idempotent.

    No error if the entry is absent.
    """
    try:
        queue = _read_queue()
        normalized_key = KeywordIndex._normalize(raw_name)
        updated = False
        for entry in queue:
            if (
                entry.get("store") == store
                and entry.get("normalized_key") == normalized_key
            ):
                entry["status"] = "resolved"
                updated = True
        if updated:
            _write_queue(queue)
    except Exception as exc:
        print(
            f"[WARN] clear_resolved failed: {exc}",
            file=sys.stderr,
        )
