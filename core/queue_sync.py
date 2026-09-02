#!/usr/bin/env python3
"""Queue sync — converge local and VPS copies of the Wednesday queues.

The searched-items and add-to-list queues are written on BOTH machines:
Claw adds items on the VPS (Telegram `search --add-item`), the user adds
items locally, and the Wednesday run consumes them locally (live window
flush). Before 2026-09-01 the Wednesday run only pulled queues in live
mode — a plain docx run never saw VPS items, and the live-mode pull
OVERWROTE the local file (losing local-only entries).

This module implements the safe convergence used by Wednesday Step 0
(both modes) and the end-of-run mirror push:

  * union-merge both queue copies by (store, normalised generic name)
  * keep the earliest added_at (an item queued anywhere is queued)
  * searched-items codes: first entry keeps its code; a colliding code
    on a different item is regenerated via the injected code_maker
  * searched-items tombstones (7-day removal markers) are union-merged
    too, and any queued entry whose code is tombstoned on EITHER side
    is dropped — a removal done via Claw must not be resurrected by
    the union
  * after the merge, both sides are pushed the identical content, so
    the queues only diverge between runs (and re-converge next run)

Pure stdlib; no network (the CLI does the scp). Mirrors the atomic-IO
rules of searched_items/add_to_list (missing/corrupt file = empty).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

# Files synced between local and VPS (queue + removal markers).
QUEUE_FILES = (
    "add_to_list.json",
    "searched_items.json",
    "searched_item_code_tombstones.json",
    "add_to_list_code_tombstones.json",
)


def _normalize(s: str) -> str:
    """Normalise a name for keying (lowercase, trim, collapse spaces).

    Reuses KeywordIndex._normalize so keys match the dup guards in
    searched_items / add_to_list exactly.

    Args:
        s (str): raw name.

    Returns:
        str: normalised key.
    """
    from core.name_matcher import KeywordIndex
    return KeywordIndex._normalize(s)


def entry_key(entry: dict) -> tuple[str, str]:
    """Stable identity of a queue entry: (store, normalised name).

    Prefer generic_name (the dup key used by both queue modules); fall
    back to keyword so hand-edited entries still merge sanely.

    Args:
        entry (dict): queue entry.

    Returns:
        tuple[str, str]: (store-lower, normalised-name).
    """
    store = str(entry.get("store", "")).strip().lower()
    name = str(entry.get("generic_name", "")).strip() or \
        str(entry.get("keyword", "")).strip()
    return (store, _normalize(name))


def _parse_ts(raw: str) -> datetime | None:
    """Parse an ISO added_at/removed_at stamp; None when unparseable.

    Args:
        raw (str): ISO timestamp string.

    Returns:
        datetime | None: parsed value (naive-comparable only against
        other results of this function; both sides use UTC ISO stamps).
    """
    try:
        return datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def _merge_fields(base: dict, other: dict) -> dict:
    """Fill blank fields of base from other (ids, size, keyword).

    Args:
        base (dict): winning entry (mutated copy returned).
        other (dict): losing entry.

    Returns:
        dict: base with blanks filled from other.
    """
    for field in ("store_product_id", "size", "keyword", "generic_name"):
        if not str(base.get(field, "") or "").strip() and \
                str(other.get(field, "") or "").strip():
            base[field] = other[field]
    return base


def merge_entries(
    local: list[dict],
    remote: list[dict],
    *,
    code_maker=None,
) -> list[dict]:
    """Union-merge two queue copies without losing either side.

    Args:
        local (list[dict]): local queue entries.
        remote (list[dict]): VPS queue entries.
        code_maker (callable | None): () -> str generator for new
            3-letter codes used when two DIFFERENT items arrive with
            the same code (e.g. queued independently on both sides).
            None keeps the colliding code blank.

    Returns:
        list[dict]: merged entries, ordered by added_at ascending
        (insertion order as tiebreak). Dup keys keep the earliest
        added_at and share fields via _merge_fields.
    """
    by_key: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []

    def _consider(entry: dict) -> None:
        key = entry_key(entry)
        if key not in by_key:
            by_key[key] = dict(entry)
            order.append(key)
            return
        kept = by_key[key]
        kept_ts = _parse_ts(kept.get("added_at", ""))
        new_ts = _parse_ts(entry.get("added_at", ""))
        # Earliest stamp wins the identity; blanks always backfill.
        if new_ts is not None and (kept_ts is None or new_ts < kept_ts):
            winner, loser = dict(entry), kept
            by_key[key] = _merge_fields(winner, loser)
        else:
            _merge_fields(kept, entry)

    for entry in local:
        _consider(entry)
    for entry in remote:
        _consider(entry)

    merged = [by_key[key] for key in order]
    merged.sort(key=lambda e: _parse_ts(e.get("added_at", "")) or
                datetime.max.replace(tzinfo=None))

    # Code collision pass: one entry per code; later entries regenerate.
    taken: set[str] = set()
    for entry in merged:
        code = str(entry.get("code", "") or "").strip().upper()
        if not code:
            continue
        if code in taken:
            if code_maker is not None:
                entry["code"] = code_maker()
            else:
                entry["code"] = ""
        else:
            taken.add(code)
    return merged


def merge_tombstones(
    local: list[dict],
    remote: list[dict],
) -> list[dict]:
    """Union tombstone lists by code, keeping the newest removed_at.

    Args:
        local (list[dict]): local tombstones.
        remote (list[dict]): VPS tombstones.

    Returns:
        list[dict]: merged tombstones (oldest first).
    """
    by_code: dict[str, dict] = {}
    for tomb in list(local) + list(remote):
        code = str(tomb.get("code", "")).strip().upper()
        if not code:
            continue
        kept = by_code.get(code)
        if kept is None:
            by_code[code] = dict(tomb)
            continue
        kept_ts = _parse_ts(kept.get("removed_at", ""))
        new_ts = _parse_ts(tomb.get("removed_at", ""))
        if new_ts is not None and (kept_ts is None or new_ts > kept_ts):
            by_code[code] = dict(tomb)
    merged = list(by_code.values())
    merged.sort(key=lambda t: _parse_ts(t.get("removed_at", "")) or
                datetime.max.replace(tzinfo=None))
    return merged


def tombstoned_codes(tombstones: list[dict]) -> set[str]:
    """Extract the uppercase code set from a tombstone list.

    Args:
        tombstones (list[dict]): tombstone entries.

    Returns:
        set[str]: live (non-expired filtering is the caller's job —
        expiry is 7 days and re-adding after that is fine) codes.
    """
    return {
        str(t.get("code", "")).strip().upper()
        for t in tombstones
        if str(t.get("code", "")).strip()
    }


def drop_tombstoned(
    entries: list[dict],
    tombstones: list[dict],
) -> list[dict]:
    """Remove queue entries whose code is tombstoned (removed by the
    user on either machine). Entries without a code are kept.

    Args:
        entries (list[dict]): merged queue entries.
        tombstones (list[dict]): merged tombstones.

    Returns:
        list[dict]: entries not matching any tombstone code.
    """
    dead = tombstoned_codes(tombstones)
    if not dead:
        return entries
    return [
        e for e in entries
        if not (str(e.get("code", "")).strip().upper() and
                str(e.get("code", "")).strip().upper() in dead)
    ]


def load_json_list(path) -> list[dict]:
    """Read a JSON list file; missing/corrupt/None reads as empty.

    Args:
        path: file path (str | Path | None). None (e.g. a remote side
            that was never pulled) reads as empty.

    Returns:
        list[dict]: parsed entries; [] on any read problem.
    """
    try:
        if path is None:
            return []
        p = Path(path)
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except (OSError, ValueError):
        pass
    return []


def save_json_list(path, entries: list[dict]) -> None:
    """Write a JSON list atomically (tempfile -> os.replace).

    Args:
        path: target file path (str | Path). None is a no-op (used when
            the caller passes no tombstone path).
        entries (list[dict]): full list to persist.

    Raises:
        OSError: when the write or replace fails.
    """
    if path is None:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        suffix=".json", prefix=p.stem + "_", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(p))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def merge_queue_file(
    local_path,
    remote_path,
    *,
    is_searched: bool = False,
    tombstone_local_path=None,
    tombstone_remote_path=None,
    code_maker=None,
) -> dict:
    """Merge one queue file pair on disk; returns a small summary.

    The classic pair is (local searched_items.json, VPS copy). For the
    searched queue the tombstone files merge as well and tombstoned
    entries are dropped. The LOCAL files are rewritten with the merged
    content; the caller pushes them to the VPS afterwards.

    Args:
        local_path: local queue file (str | Path).
        remote_path: pulled VPS copy (str | Path). Missing = empty.
        is_searched (bool): merge tombstones + drop removed codes.
        tombstone_local_path: local tombstones file (searched only).
        tombstone_remote_path: pulled VPS tombstones file.
        code_maker (callable | None): see merge_entries.

    Returns:
        dict: {"local_before": int, "remote_before": int,
               "merged": int, "dropped_tombstoned": int,
               "tombstones_merged": int}
    """
    local = load_json_list(local_path)
    remote = load_json_list(remote_path)
    merged = merge_entries(local, remote, code_maker=code_maker)

    summary = {
        "local_before": len(local),
        "remote_before": len(remote),
        "merged": len(merged),
        "dropped_tombstoned": 0,
        "tombstones_merged": 0,
    }

    if is_searched:
        tom_local = load_json_list(tombstone_local_path)
        tom_remote = load_json_list(tombstone_remote_path)
        tom_merged = merge_tombstones(tom_local, tom_remote)
        kept = drop_tombstoned(merged, tom_merged)
        summary["dropped_tombstoned"] = len(merged) - len(kept)
        summary["tombstones_merged"] = len(tom_merged)
        summary["merged"] = len(kept)
        merged = kept
        if tombstone_local_path is not None:
            save_json_list(tombstone_local_path, tom_merged)

    save_json_list(local_path, merged)
    return summary
