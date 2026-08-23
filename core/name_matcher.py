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
        store: The store this item came from ("woolworths"|"coles"|"aldi").
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
    NameMatcher.match() calls. Holds three internal dicts, one per store,
    keyed by the normalized keyword.

    First occurrence wins on duplicate keywords.
    """

    # Column indices in Products_Master (0-based)
    _COL_GENERIC_NAME = 0
    _COL_KW_WOOLWORTHS = 8
    _COL_KW_COLES = 9
    _COL_KW_ALDI = 10

    _STORE_COL_MAP: dict[str, int] = {
        "woolworths": _COL_KW_WOOLWORTHS,
        "coles": _COL_KW_COLES,
        "aldi": _COL_KW_ALDI,
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
        self._aldi: dict[str, tuple[int, str]] = {}

        for i, row in enumerate(rows):
            row_index = i + 2  # 1-based: row 1 = header, row 2 = first data row
            generic_name = row[self._COL_GENERIC_NAME] if len(row) > self._COL_GENERIC_NAME else ""

            self._index_store_keywords(row, row_index, generic_name)

    def _index_store_keywords(self, row: list[str], row_index: int, generic_name: str) -> None:
        """Index keyword columns for all three stores from a single row."""
        store_dicts = {
            "woolworths": self._woolworths,
            "coles": self._coles,
            "aldi": self._aldi,
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
            store: "woolworths"|"coles"|"aldi" — selects which keyword column
                (I/J/K) to look in.
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

    def __len__(self) -> int:
        """Total number of indexed keywords across all three stores."""
        return len(self._woolworths) + len(self._coles) + len(self._aldi)


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
                _write_queue(queue)
                return

        # New entry
        queue.append({
            "store": item.store,
            "raw_name": item.raw_name,
            "normalized_key": normalized_key,
            "classification": classification,
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
