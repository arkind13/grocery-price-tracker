#!/usr/bin/env python3
"""Manual website-add queue (add_to_list.json) — single-responsibility module.

When a wool/coles `map --add` (or the interactive `add` action) updates a
price in the sheet, the item is ALSO queued here so the user remembers to
add it to the store's website shopping list. The queue is drained ONLY by
`add-to-list done` — never automatically (spec §3.6: the item must resurface
in the missing list and later the unmatched report until the user marks it
done).

Entry shape (JSON list, insertion order preserved):
    {"store": "woolworths", "keyword": "Woolworths Beef Mince 500g",
     "generic_name": "Woolworths Beef Mince 500g", "size": "500g",
     "added_at": "2026-08-28T02:00:00.000000+00:00"}

Every NEW entry carries "size" (real value or the "unit
unavailable" marker, Rule B); legacy entries without the key read
as blank and display the note (Rule A).

Dup key: store + normalized Col A generic_name (live-search names drift;
Col A is stable). Atomic writes mirror missing_items_tracker._write_queue
(tempfile.mkstemp + os.replace) but RAISE on failure — the CLI caller
decides how to surface it (a queue write failure must not fail a price
write that already happened).
"""
from __future__ import annotations
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from core.telegram_format import (
    UNIT_UNAVAILABLE, header, subheader, unit_suffix,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ADD_TO_LIST_PATH = DATA_DIR / "add_to_list.json"     # module-level, patchable
VALID_STORES = ("coles", "woolworths")

# Canonical show order: Coles section first, then Woolworths (spec §7.3).
_STORE_ORDER = ("coles", "woolworths")


def _normalize_key(s: str) -> str:
    """Normalize a generic name for dup comparison.

    Reuses KeywordIndex._normalize (lowercase, trim, collapse whitespace)
    — identical to missing_items_tracker._normalize_key.

    Args:
        s (str): raw generic name.

    Returns:
        str: normalized key.
    """
    from core.name_matcher import KeywordIndex
    return KeywordIndex._normalize(s)


def load_pending() -> list[dict]:
    """Read the add_to_list queue.

    Returns:
        list[dict]: entries in file (insertion) order; [] if the file is
        missing, corrupt, or not a JSON list. Never raises.
    """
    try:
        if ADD_TO_LIST_PATH.exists():
            with open(ADD_TO_LIST_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except (OSError, ValueError):
        pass
    return []


def save_pending(entries: list[dict]) -> None:
    """Write the queue atomically (tempfile.mkstemp -> os.replace).

    Creates the data/ directory if absent. The temp file is unlinked on
    failure so no add_to_list_* leftovers remain.

    Args:
        entries (list[dict]): full entry list to persist.

    Raises:
        OSError: when the write or the atomic replace fails.
    """
    ADD_TO_LIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        suffix=".json",
        prefix="add_to_list_",
        dir=str(ADD_TO_LIST_PATH.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(ADD_TO_LIST_PATH))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def ordered_entries() -> list[dict]:
    """Return pending entries in canonical numbering order.

    Coles entries first (insertion order), then Woolworths (insertion
    order). This is the SINGLE source of truth for numbering so `show`,
    `done`, and the remaining-list render always agree.

    Returns:
        list[dict]: ordered pending entries.
    """
    entries = load_pending()
    ordered: list[dict] = []
    for store in _STORE_ORDER:
        ordered.extend(e for e in entries if e.get("store") == store)
    return ordered


def is_pending(store: str, generic_name: str) -> dict | None:
    """Dup guard: find a queued entry for the same store + generic name.

    Args:
        store (str): store id ("coles"/"woolworths").
        generic_name (str): Col A generic name.

    Returns:
        dict | None: the first matching entry, else None.
    """
    norm = _normalize_key(generic_name)
    for entry in load_pending():
        if entry.get("store", "").strip().lower() != store.strip().lower():
            continue
        if _normalize_key(entry.get("generic_name", "")) == norm:
            return entry
    return None


def add_entry(store: str, keyword: str, generic_name: str,
              size: str = "") -> dict:
    """Queue one item (dup-guarded on store + normalized generic name).

    Args:
        store (str): "coles" or "woolworths" (case-insensitive).
        keyword (str): the live-search result-0 exact store product name
            (what the user must find on the store website).
        generic_name (str): the Col A generic name (stable dup key).
        size (str): package size (real value or marker; "" → marker).

    Returns:
        dict: {"added": True, "entry": <new entry>} when appended;
        {"added": False, "entry": <existing entry>} when already queued
        (no write happens in that case).

    Raises:
        ValueError: when store is not a valid store, or keyword /
        generic_name is blank after strip.
        OSError: when the atomic write fails.
    """
    store_key = str(store).strip().lower()
    if store_key not in VALID_STORES:
        raise ValueError(
            f"Invalid store '{store}' — expected one of {VALID_STORES}.")
    kw = str(keyword).strip()
    gn = str(generic_name).strip()
    if not kw:
        raise ValueError("keyword must be a non-empty string.")
    if not gn:
        raise ValueError("generic_name must be a non-empty string.")

    existing = is_pending(store_key, gn)
    if existing is not None:
        return {"added": False, "entry": existing}

    entry = {
        "store": store_key,
        "keyword": kw,
        "generic_name": gn,
        # B4: always present; blank normalises to the marker (P6).
        "size": str(size or "").strip() or UNIT_UNAVAILABLE,
        # 2026-09-02: 3-letter reference code (same UX as searched items).
        "code": generate_code(),
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    entries = load_pending()
    entries.append(entry)
    save_pending(entries)
    return {"added": True, "entry": entry}


def parse_items_arg(text: str) -> list[int]:
    """Parse an --items argument like "1,2,3" or "item 1, 2 and 3".

    Splits on commas/whitespace, drops the filler words item/items/and,
    parses the rest as ints, dedupes preserving first-seen order.

    Args:
        text (str): raw --items value.

    Returns:
        list[int]: unique item numbers in first-seen order.

    Raises:
        ValueError: when any token is non-numeric, or nothing numeric
        remains (empty result).
    """
    numbers: list[int] = []
    for token in _numeric_tokens(text):
        numbers.append(int(token))
    if not numbers:
        raise ValueError(f"could not parse items '{text}'.")
    # Dedupe preserving order.
    seen: set[int] = set()
    unique = [n for n in numbers if not (n in seen or seen.add(n))]
    return unique


def _numeric_tokens(text: str) -> list[str]:
    """Split --items text into numeric candidate tokens.

    Splits on commas and whitespace; drops case-insensitive filler tokens
    "item", "items", "and".

    Args:
        text (str): raw --items value.

    Returns:
        list[str]: remaining tokens (each expected to parse as int).
    """
    fillers = {"item", "items", "and"}
    return [
        t for t in re.split(r"[,\s]+", str(text))
        if t and t.lower() not in fillers
    ]


def remove_by_numbers(numbers: list[int]) -> dict:
    """Remove queue entries by show-numbering. ALL-OR-NOTHING.

    Validates EVERY number against 1..len(ordered_entries()) BEFORE any
    mutation, so an invalid request never touches the file.

    Args:
        numbers (list[int]): item numbers from 'add-to-list show'.

    Returns:
        dict: {"removed": [entries in ascending number order],
        "remaining_count": int}.

    Raises:
        ValueError: when the queue is empty, or any number falls outside
        the valid range (message names the range). File untouched.
        OSError: when the atomic rewrite fails.
    """
    ordered = ordered_entries()
    if not ordered:
        raise ValueError("add_to_list is empty — nothing to remove.")
    total = len(ordered)
    unique: list[int] = []
    seen: set[int] = set()
    for n in numbers:
        if n in seen:
            continue
        seen.add(n)
        if not (1 <= n <= total):
            raise ValueError(
                f"Invalid item number {n} — valid range is 1-{total} "
                f"({total} pending).")
        unique.append(n)
    unique.sort()

    remove_set = set(unique)
    removed = [ordered[n - 1] for n in unique]
    remaining = [e for i, e in enumerate(ordered, 1) if i not in remove_set]
    save_pending(remaining)
    # 2026-09-02: tombstone removed codes for 7 days (no immediate
    # reuse on a different product).
    removed_codes = [
        str(e.get("code", "")).strip() for e in removed if e.get("code")]
    if removed_codes:
        try:
            _add_code_tombstones(removed_codes)
        except OSError:
            pass  # a tombstone failure must not fail the removal
    return {"removed": removed, "remaining_count": len(remaining)}


def render_show() -> str:
    """Render the 'add-to-list show' output block.

    Empty queue -> one friendly line. Otherwise a style-kit block:
    main header with pending count, then one subheader per NON-EMPTY
    store section (Coles first, then Woolworths) with continuous
    numbering across sections. No tables.

    Returns:
        str: multi-line render (print-ready).
    """
    ordered = ordered_entries()
    if not ordered:
        return "add_to_list is empty ✅"
    blocks = [header(f"Add_to_list — {len(ordered)} pending", "🛒")]
    counter = 0
    for store in _STORE_ORDER:
        store_entries = [e for e in ordered if e.get("store") == store]
        if not store_entries:
            continue
        blocks.append(subheader(store.capitalize()))
        for entry in store_entries:
            counter += 1
            code = str(entry.get("code", "")).strip()
            code_bit = f" [{code}]" if code else ""
            blocks.append(
                f"{counter}) {entry.get('keyword', '')}"
                f"{unit_suffix(entry.get('size', ''))}{code_bit}")
    return "\n".join(blocks)


def render_remaining_flat(entries: list[dict], start: int = 1) -> str:
    """Render the flat remaining-items list used by 'done' output.

    Args:
        entries (list[dict]): remaining entries in show order.
        start (int): first item number (default 1).

    Returns:
        str: lines like "1) Oak Chocolate Milk 750ml (Coles)"; when
        entries is empty, the friendly "add_to_list is now empty ✅".
    """
    if not entries:
        return "add_to_list is now empty ✅"
    lines = []
    for i, entry in enumerate(entries, start):
        store = str(entry.get("store", "")).strip().capitalize()
        code = str(entry.get("code", "")).strip()
        code_bit = f" [{code}]" if code else ""
        lines.append(
            f"{i}) {entry.get('keyword', '')}"
            f"{unit_suffix(entry.get('size', ''))} ({store}){code_bit}")
    return "\n".join(lines)


def since_label(entry: dict) -> str:
    """Short "DD Mon" label for when an entry was queued.

    Args:
        entry (dict): queue entry with an "added_at" ISO timestamp.

    Returns:
        str: e.g. "28 Aug" (zero-padded day is cross-platform safe —
        no %-d on Windows); the raw added_at string when parsing fails.
    """
    raw = str(entry.get("added_at", ""))
    try:
        return datetime.fromisoformat(raw).strftime("%d %b")
    except (TypeError, ValueError):
        return raw


# ===========================================================================
# 3-letter entry codes (2026-09-02 — mirrors searched_items codes)
# ===========================================================================
# Every entry gets a unique 3-letter code (letters only, no I/O, no
# repeated letter inside the code) so the user can reference items the
# same way as the searched list ("done KAT"). Removed codes are
# tombstoned for 7 days so a code can't immediately reattach to a
# different product after removal.

A_L_TOMBSTONES_PATH = DATA_DIR / "add_to_list_code_tombstones.json"
CODE_TTL_DAYS = 7
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"   # letters only, no I/O


def _load_code_tombstones(*, now: datetime | None = None) -> list[dict]:
    """Read code tombstones, pruning entries older than the TTL."""
    from datetime import timedelta

    now = now or datetime.now(timezone.utc)
    if not A_L_TOMBSTONES_PATH.exists():
        return []
    try:
        with open(A_L_TOMBSTONES_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    kept: list[dict] = []
    cutoff = now - timedelta(days=CODE_TTL_DAYS)
    for tomb in raw:
        try:
            ts = datetime.fromisoformat(str(tomb.get("removed_at", "")))
        except (TypeError, ValueError):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= cutoff:
            kept.append(tomb)
    return kept


def _save_code_tombstones(tombstones: list[dict]) -> None:
    """Write code tombstones atomically."""
    A_L_TOMBSTONES_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix="add_to_list_tombstones_",
        dir=str(A_L_TOMBSTONES_PATH.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(tombstones, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(A_L_TOMBSTONES_PATH))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _add_code_tombstones(codes: list[str], *,
                         now: datetime | None = None) -> None:
    """Tombstone the given codes (idempotent)."""
    now = now or datetime.now(timezone.utc)
    existing = _load_code_tombstones(now=now)
    have = {t.get("code", "") for t in existing}
    for code in codes:
        code = str(code or "").strip().upper()
        if code and code not in have:
            existing.append(
                {"code": code, "removed_at": now.isoformat()})
            have.add(code)
    _save_code_tombstones(existing)


def generate_code(*, rng=None, now: datetime | None = None) -> str:
    """Generate a fresh 3-letter code (no I/O, no repeated letter).

    Uniqueness is enforced against CURRENT entry codes and live
    tombstones. Exhaustion (astronomically unlikely at this scale)
    falls back to allowing a repeated letter before ever raising.

    Args:
        rng (random.Random | None): injected RNG for tests.
        now (datetime | None): injected clock for tombstone expiry.

    Returns:
        str: 3 uppercase letters.
    """
    import random as _random

    rng = rng or _random
    taken = {
        str(e.get("code", "")).strip().upper()
        for e in load_pending()
    }
    taken |= {t.get("code", "") for t in _load_code_tombstones(now=now)}
    for _ in range(500):
        code = "".join(rng.sample(_CODE_ALPHABET, 3))
        if code not in taken:
            return code
    # Fallback: allow repeated letters rather than fail.
    while True:
        code = "".join(rng.choices(_CODE_ALPHABET, k=3))
        if code not in taken:
            return code


def ensure_codes(*, rng=None, now: datetime | None = None) -> int:
    """Backfill codes for legacy entries created before 2026-09-02.

    Args:
        rng / now: injected for tests (see generate_code).

    Returns:
        int: number of codes assigned (0 when nothing to do, and the
        file is not touched in that case).
    """
    entries = load_pending()
    taken = {
        str(e.get("code", "")).strip().upper() for e in entries if e.get("code")}
    assigned = 0
    for entry in entries:
        if str(entry.get("code", "")).strip():
            continue
        for _ in range(50):
            code = generate_code(rng=rng, now=now)
            if code not in taken:
                break
        entry["code"] = code
        taken.add(code)
        assigned += 1
    if assigned:
        save_pending(entries)
    return assigned


def resolve_items_arg(text: str) -> list[int]:
    """Parse a mixed --items value ("1,KAT,3") into show numbers.

    Numbers pass through; 3-letter codes are resolved against the
    current entries (case-insensitive). An unknown code raises with
    the live code list so the user can self-correct (mirrors
    searched-items remove errors).

    Args:
        text (str): raw --items value.

    Returns:
        list[int]: show numbers, deduped, first-seen order.

    Raises:
        ValueError: unknown code (message lists current codes), or
        nothing parseable.
    """
    ordered = ordered_entries()
    by_code = {
        str(e.get("code", "")).strip().upper(): i
        for i, e in enumerate(ordered, 1) if e.get("code")}
    numbers: list[int] = []
    for token in _numeric_tokens(text):
        upper = token.strip().upper()
        if upper in by_code:
            numbers.append(by_code[upper])
            continue
        if re.fullmatch(r"[A-Z]{3}", upper):
            live = ", ".join(
                f"{e.get('code')} ({e.get('keyword', '')[:30]})"
                for e in ordered if e.get("code")) or "none"
            raise ValueError(
                f"unknown code '{upper}' — current codes: {live}.")
        try:
            numbers.append(int(token))
        except ValueError:
            raise ValueError(f"could not parse items '{text}'.")
    if not numbers:
        raise ValueError(f"could not parse items '{text}'.")
    seen: set[int] = set()
    return [n for n in numbers if not (n in seen or seen.add(n))]
