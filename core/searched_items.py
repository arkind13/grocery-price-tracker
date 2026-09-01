#!/usr/bin/env python3
"""Searched-items queue (searched_items.json) — explicit-add Wednesday queue.

When the user EXPLICITLY adds a live-search result (`search --add-item N`
or the `map --add` unmatched-live route), the exact store product is
queued here so the live window (session_refresh Phase B) can add it to
the store's website "Price Compare" list later. Nothing is ever queued
automatically (spec §3.4 / guardrail 3).

Each entry gets a unique 3-letter code (A-Z minus I/O, no repeated
letter) used by the queue-management UX:

    Queued for Wednesday: 'Obela Classic Hommus 200g' (Coles) [KAT]
    💬 Reply 'remove KAT' if this isn't the right product.

Removals tombstone their codes for 7 days so a removed code is not
reassigned to a different product in the meantime (stale chat messages
must not silently point at the wrong item).

Entry shape (JSON list, insertion order preserved):
    {"store": "coles", "keyword": "Obela Classic Hommus 200g",
     "store_product_id": "1234567", "generic_name": "Obela Classic
     Hommus 200g", "code": "KAT",
     "added_at": "2026-08-29T02:00:00.000000+00:00"}

Every NEW entry carries "size" (real value or the "unit unavailable"
marker); legacy entries without the key read as blank and display the
note (Rule A/B).

Structure mirrors core/add_to_list.py (atomic writes RAISE on failure;
missing/corrupt file reads as empty; dup guard on store + normalised
generic name; Coles section first, then Woolworths).
"""
from __future__ import annotations
import json
import os
import random
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.telegram_format import (
    UNIT_UNAVAILABLE, header, subheader, unit_suffix,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SEARCHED_ITEMS_PATH = DATA_DIR / "searched_items.json"   # patchable
TOMBSTONES_PATH = DATA_DIR / "searched_item_code_tombstones.json"
VALID_STORES = ("coles", "woolworths")

# 3-letter codes from A-Z minus I/O (24 letters — avoids I/1 and O/0 mixups).
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"
CODE_LENGTH = 3
TOMBSTONE_TTL_DAYS = 7

# Canonical show order: Coles section first, then Woolworths (mirrors
# add_to_list / spec §7.3).
_STORE_ORDER = ("coles", "woolworths")


def _normalize_key(s: str) -> str:
    """Normalize a generic name for dup comparison.

    Reuses KeywordIndex._normalize (lowercase, trim, collapse whitespace)
    — identical to add_to_list._normalize_key.

    Args:
        s (str): raw generic name.

    Returns:
        str: normalized key.
    """
    from core.name_matcher import KeywordIndex
    return KeywordIndex._normalize(s)


# ---------------------------------------------------------------------------
# Queue IO (mirror of add_to_list.load_pending / save_pending)
# ---------------------------------------------------------------------------
def load_pending() -> list[dict]:
    """Read the searched_items queue.

    Returns:
        list[dict]: entries in file (insertion) order; [] if the file is
        missing, corrupt, or not a JSON list. Never raises.
    """
    try:
        if SEARCHED_ITEMS_PATH.exists():
            with open(SEARCHED_ITEMS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except (OSError, ValueError):
        pass
    return []


def save_pending(entries: list[dict]) -> None:
    """Write the queue atomically (tempfile.mkstemp -> os.replace).

    Creates the data/ directory if absent. The temp file is unlinked on
    failure so no searched_items_* leftovers remain. Written with
    indent=2 and ensure_ascii=False so product names stay readable.

    Args:
        entries (list[dict]): full entry list to persist.

    Raises:
        OSError: when the write or the atomic replace fails.
    """
    SEARCHED_ITEMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        suffix=".json",
        prefix="searched_items_",
        dir=str(SEARCHED_ITEMS_PATH.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(SEARCHED_ITEMS_PATH))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def ordered_entries() -> list[dict]:
    """Return pending entries in canonical numbering order.

    Coles entries first (insertion order), then Woolworths (insertion
    order). Single source of truth for `show`, removal validation, and
    the code-collision check.

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
        generic_name (str): exact product name (stable dup key).

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


# ---------------------------------------------------------------------------
# Code generation + tombstones
# ---------------------------------------------------------------------------
def _load_tombstones() -> list[dict]:
    """Read tombstones, pruning entries older than the TTL.

    Returns:
        list[dict]: live (non-expired) tombstones, newest last. Missing
        or corrupt file reads as [] — never raises.
    """
    try:
        if TOMBSTONES_PATH.exists():
            with open(TOMBSTONES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return _prune_expired(data)
    except (OSError, ValueError):
        pass
    return []


def _save_tombstones(tombstones: list[dict]) -> None:
    """Write tombstones atomically (same mechanics as save_pending).

    Args:
        tombstones (list[dict]): full tombstone list to persist.

    Raises:
        OSError: when the write or the atomic replace fails.
    """
    TOMBSTONES_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        suffix=".json",
        prefix="searched_item_tombstones_",
        dir=str(TOMBSTONES_PATH.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(tombstones, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(TOMBSTONES_PATH))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _prune_expired(tombstones: list[dict], *, now: datetime | None = None) -> list[dict]:
    """Drop tombstones older than TOMBSTONE_TTL_DAYS (their codes may be
    reused again).

    Args:
        tombstones (list[dict]): raw tombstone entries.
        now (datetime | None): injected clock for tests; defaults to UTC now.

    Returns:
        list[dict]: only tombstones still within the TTL. Entries with an
        unparseable removed_at are dropped (treated as expired).
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=TOMBSTONE_TTL_DAYS)
    live = []
    for tomb in tombstones:
        try:
            removed_at = datetime.fromisoformat(str(tomb.get("removed_at", "")))
        except (TypeError, ValueError):
            continue
        if removed_at >= cutoff:
            live.append(tomb)
    return live


def _add_tombstones(codes: list[str], *, now: datetime | None = None) -> None:
    """Tombstone the given codes (idempotent; prunes expired on write).

    Args:
        codes (list[str]): uppercase codes to record.
        now (datetime | None): injected clock for tests.
    """
    now = now or datetime.now(timezone.utc)
    existing = _load_tombstones()
    known = {t.get("code") for t in existing}
    stamp = now.isoformat()
    for code in codes:
        if code not in known:
            existing.append({"code": code, "removed_at": stamp})
            known.add(code)
    _save_tombstones(existing)


def generate_code(*, rng=None, now: datetime | None = None) -> str:
    """Generate a unique 3-letter code (no repeated letter within it).

    Uniqueness is checked against BOTH the current queue codes and the
    live (non-expired) tombstones, so a code removed moments ago is not
    immediately reassigned to a different product.

    Args:
        rng: random.Random-like instance with .choice (injected for
            deterministic tests); a module-level Random when None.
        now (datetime | None): injected clock for tombstone expiry.

    Returns:
        str: e.g. "KAT" — CODE_LENGTH letters from CODE_ALPHABET.

    Raises:
        RuntimeError: when no unique code exists (practically impossible:
        24 x 23 x 22 = 12144 candidates).
    """
    drawer = rng if rng is not None else random.Random()
    taken = {e.get("code", "") for e in load_pending()}
    taken |= {t.get("code", "") for t in _load_tombstones()}
    alphabet = CODE_ALPHABET
    for _ in range(10000):
        code = "".join(drawer.choice(alphabet) for _ in range(CODE_LENGTH))
        if len(set(code)) != CODE_LENGTH:
            continue  # no repeated letter within a code
        if code in taken:
            continue
        return code
    raise RuntimeError("generate_code exhausted: no unique code available.")


# ---------------------------------------------------------------------------
# Add / remove
# ---------------------------------------------------------------------------
def add_entry(
    store: str,
    keyword: str,
    generic_name: str,
    store_product_id: str = "",
    size: str = "",
) -> dict:
    """Queue one item (dup-guarded on store + normalised generic name).

    Args:
        store (str): "coles" or "woolworths" (case-insensitive).
        keyword (str): the exact store product name to add to the store
            website list during the live window.
        generic_name (str): stable dup key (Col A name when known, else
            the keyword itself).
        store_product_id (str): store product id captured at search time
            ("" when the payload lacked one).
        size (str): package size string captured at add time ("" when
            unknown; blank normalises to the canonical marker).

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
        "store_product_id": str(store_product_id or "").strip(),
        "generic_name": gn,
        "code": generate_code(),
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    # B5: every NEW entry carries "size" — blank normalises to the
    # canonical marker (add paths resolve beforehand; this is the
    # last-resort backstop, plan P6).
    entry["size"] = str(size or "").strip() or UNIT_UNAVAILABLE
    entries = load_pending()
    entries.append(entry)
    save_pending(entries)
    return {"added": True, "entry": entry}


def _unknown_code_error(code: str) -> ValueError:
    """Build the exact self-correcting unknown-code ValueError.

    Args:
        code (str): the code the user asked to remove.

    Returns:
        ValueError: message
        "⚠️ Code 'X' not found. Current queue codes: A, B, C."
        (codes in show order; "none" when the queue is empty).
    """
    current = [e.get("code", "") for e in ordered_entries()]
    if current:
        listing = ", ".join(c for c in current if c)
    else:
        listing = "none"
    return ValueError(
        f"⚠️ Code '{code}' not found. Current queue codes: {listing}.")


def remove_by_codes(codes: list[str]) -> dict:
    """Remove queue entries by their 3-letter codes. ALL-OR-NOTHING.

    Validates EVERY code against the current queue (case-insensitive)
    BEFORE any mutation, so an unknown code never touches the file.

    Args:
        codes (list[str]): codes from 'searched-items show' (any case).

    Returns:
        dict: {"removed": [removed entries in show order],
        "remaining_count": int}.

    Raises:
        ValueError: when the queue is empty, or any code is not currently
        queued (message lists the current codes). File untouched.
        OSError: when the atomic rewrite or tombstone write fails.
    """
    ordered = ordered_entries()
    if not ordered:
        raise ValueError("searched_items is empty — nothing to remove.")

    by_code = {}
    for entry in ordered:
        by_code[str(entry.get("code", "")).upper()] = entry

    wanted: list[str] = []
    seen: set[str] = set()
    for raw in codes:
        code = str(raw).strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        if code not in by_code:
            raise _unknown_code_error(code)
        wanted.append(code)

    removed = [by_code[c] for c in wanted]
    removed_codes = {e.get("code", "") for e in removed}
    remaining = [e for e in ordered if e.get("code", "") not in removed_codes]
    save_pending(remaining)
    _add_tombstones(sorted(removed_codes))
    return {"removed": removed, "remaining_count": len(remaining)}


def consume_entries(store: str, entries: list[dict]) -> None:
    """Flush-success path: remove consumed entries + tombstone their codes.

    Called by session_refresh Phase B after an item was successfully
    added to the store website list. Matching is by store + normalised
    generic_name (entries already removed by the user are skipped
    silently — idempotent).

    Args:
        store (str): store id the flush succeeded for.
        entries (list[dict]): the consumed entry dicts (or at minimum
            dicts carrying store/generic_name and ideally code).

    Raises:
        OSError: when the atomic rewrite or tombstone write fails.
    """
    store_key = str(store).strip().lower()
    consumed_norms = {
        _normalize_key(str(e.get("generic_name", "")))
        for e in entries
        if str(e.get("generic_name", "")).strip()
    }
    if not consumed_norms:
        return
    remaining = []
    tombstone_codes = []
    for entry in load_pending():
        same_store = entry.get("store", "").strip().lower() == store_key
        norm = _normalize_key(str(entry.get("generic_name", "")))
        if same_store and norm in consumed_norms:
            code = str(entry.get("code", "")).upper()
            if code:
                tombstone_codes.append(code)
            continue
        remaining.append(entry)
    save_pending(remaining)
    if tombstone_codes:
        _add_tombstones(tombstone_codes)


def clear_all() -> dict:
    """Empty the queue and tombstone EVERY code.

    Returns:
        dict: {"removed": [all entries in show order],
        "remaining_count": 0}.

    Raises:
        OSError: when the atomic rewrite or tombstone write fails.
    """
    ordered = ordered_entries()
    save_pending([])
    codes = sorted({e.get("code", "") for e in ordered if e.get("code", "")})
    if codes:
        _add_tombstones(codes)
    return {"removed": ordered, "remaining_count": 0}


# ---------------------------------------------------------------------------
# CLI argument parsing + render
# ---------------------------------------------------------------------------
def parse_codes_arg(text: str) -> list[str]:
    """Parse a codes argument like "KAT,RUM" or "kat rum and KAT".

    Splits on commas/whitespace, drops the filler word "and", uppercases,
    validates every token as alphabetic, dedupes preserving first-seen
    order.

    Args:
        text (str): raw --items value.

    Returns:
        list[str]: unique uppercase codes in first-seen order.

    Raises:
        ValueError: when any token is not alphabetic, or nothing valid
        remains (empty result).
    """
    codes: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[,\s]+", str(text)):
        if not token or token.lower() == "and":
            continue
        if not token.isalpha():
            raise ValueError(
                f"Invalid code '{token}' — codes are letters only "
                f"(e.g. KAT).")
        code = token.upper()
        if code in seen:
            continue
        seen.add(code)
        codes.append(code)
    if not codes:
        raise ValueError(f"could not parse codes '{text}'.")
    return codes


def render_show() -> str:
    """Render the 'searched-items show' output block.

    Empty queue -> one friendly line. Otherwise a style-kit block:
    main header with pending count, then one subheader per NON-EMPTY
    store section (Coles first, then Woolworths). Each entry line is
    "store · exact product name · unit tag · [CODE]" (the tag is a real
    size or the ⚠️ marker note — never omitted, Rule A).

    Returns:
        str: multi-line render (print-ready).
    """
    ordered = ordered_entries()
    if not ordered:
        return "searched_items is empty ✅"
    blocks = [header(f"Searched items — {len(ordered)} pending", "🔍")]
    for store in _STORE_ORDER:
        store_entries = [e for e in ordered if e.get("store") == store]
        if not store_entries:
            continue
        blocks.append(subheader(store.capitalize()))
        for entry in store_entries:
            # A8 (Rule A): unit segment ALWAYS present; legacy entries
            # without a "size" key read as blank -> the ⚠️ note.
            blocks.append(
                " · ".join([store, entry.get("keyword", "")])
                + unit_suffix(entry.get("size", ""))
                + f" [{entry.get('code', '')}]")
    return "\n".join(blocks)


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
