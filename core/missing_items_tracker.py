#!/usr/bin/env python3
"""Cross-store missing-items tracker — atomic JSON queue diff.

Read-only diffing on matched MatchResult.generic_name sets. Items present
in one store's saved list but absent from the other are upserted into a
per-store JSON queue (woolworths_missing_items.json / coles_missing_items.json).

Reuses KeywordIndex._normalize for idempotent keys. Atomic writes mirror the
name_matcher._write_queue pattern (tempfile.mkstemp + os.replace).
"""
from __future__ import annotations
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WOOLWORTHS_MISSING_PATH = DATA_DIR / "woolworths_missing_items.json"
COLES_MISSING_PATH      = DATA_DIR / "coles_missing_items.json"

MISSING_PATH_BY_STORE = {
    "woolworths": WOOLWORTHS_MISSING_PATH,
    "coles":      COLES_MISSING_PATH,
}


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    """Return current UTC timestamp as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _normalize_key(s: str) -> str:
    """Reuse KeywordIndex._normalize for consistent key generation."""
    from core.name_matcher import KeywordIndex
    return KeywordIndex._normalize(s)


# ---------------------------------------------------------------------------
# Atomic read/write
# ---------------------------------------------------------------------------

def _read_queue(path: Path) -> list[dict]:
    """Read JSON queue file. Return [] if missing or corrupt."""
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception as exc:
        print(f"[missing_items_tracker] read failed for {path.name}: {exc}",
              file=sys.stderr)
    return []


def _write_queue(path: Path, entries: list[dict]) -> None:
    """Write queue atomically via tempfile + os.replace. Never raises."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            suffix=".json",
            prefix=f"missing_{path.stem}_",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, str(path))
        except Exception:
            os.unlink(tmp_path)
            raise
    except Exception as exc:
        print(f"[missing_items_tracker] write failed for {path.name}: {exc}",
              file=sys.stderr)


# ---------------------------------------------------------------------------
# Core diff function
# ---------------------------------------------------------------------------

def update_missing_items(
    woolworths_results: list,
    coles_results: list,
) -> dict:
    """Diff matched generic-name sets across stores; upsert both queues.

    Strategy: a store's "covered generic names" = the set of
    MatchResult.generic_name for results where matched==True. An item present
    in Coles's covered set but absent from Woolworths's covered set is
    "missing from Woolworths" -> upserted into woolworths_missing_items.json
    (source_store="coles"). Symmetric for Coles-missing.

    Why generic-name, not raw-name: the same product is listed under different
    store-specific names. Comparing raw names would produce false "missing".
    Generic names (Col A) are the canonical cross-store key.

    Idempotent upsert per normalized_key: existing entries increment count
    and bump last_seen; brand-new entries get count=1.

    Returns:
        {"woolworths_missing": int, "coles_missing": int}
    """
    from core.name_matcher import KeywordIndex

    def _covered_generic_names(results: list) -> dict:
        """Build {normalized_generic_name: (generic_name, raw_name, store)}
        for matched results only. First raw_name wins per generic name."""
        covered = {}
        for r in results:
            if not getattr(r, "matched", False):
                continue
            gn = getattr(r, "generic_name", "")
            if not gn:
                continue
            norm = KeywordIndex._normalize(gn)
            if norm not in covered:
                rn = getattr(r, "raw_name", gn)
                st = getattr(r, "store", "")
                covered[norm] = (gn, rn, st)
        return covered

    ww_covered = _covered_generic_names(woolworths_results)
    coles_covered = _covered_generic_names(coles_results)

    ww_norms = set(ww_covered.keys())
    coles_norms = set(coles_covered.keys())

    now = _utc_now_iso()

    # --- Items missing from Woolworths (present in Coles, not in Woolworths) ---
    missing_from_ww = coles_norms - ww_norms
    ww_queue = _read_queue(WOOLWORTHS_MISSING_PATH)
    ww_index = {_normalize_key(e.get("product_name", "")): e for e in ww_queue}

    for norm in missing_from_ww:
        gn, rn, st = coles_covered[norm]
        key = _normalize_key(rn)
        if key in ww_index:
            entry = ww_index[key]
            entry["last_seen"] = now
            entry["count"] = entry.get("count", 0) + 1
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
            ww_index[key] = entry

    _write_queue(WOOLWORTHS_MISSING_PATH, ww_queue)

    # --- Items missing from Coles (present in Woolworths, not in Coles) ---
    missing_from_coles = ww_norms - coles_norms
    coles_queue = _read_queue(COLES_MISSING_PATH)
    coles_index = {_normalize_key(e.get("product_name", "")): e for e in coles_queue}

    for norm in missing_from_coles:
        gn, rn, st = ww_covered[norm]
        key = _normalize_key(rn)
        if key in coles_index:
            entry = coles_index[key]
            entry["last_seen"] = now
            entry["count"] = entry.get("count", 0) + 1
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
            coles_index[key] = entry

    _write_queue(COLES_MISSING_PATH, coles_queue)

    return {
        "woolworths_missing": len(missing_from_ww),
        "coles_missing": len(missing_from_coles),
    }


# ---------------------------------------------------------------------------
# Accessor functions
# ---------------------------------------------------------------------------

def get_missing_items(store: str) -> list[dict]:
    """Return the missing-items queue for the target store.

    store selects which QUEUE: "woolworths" -> items missing from Woolworths
    (source_store="coles"). Returns [] if file missing/corrupt.
    """
    path = MISSING_PATH_BY_STORE.get(store.lower())
    if path is None:
        return []
    return _read_queue(path)


def clear_missing(store: str, product_name: str) -> None:
    """Remove a resolved missing-item entry by normalized product_name.

    Called when the user has added the item to the other store's list
    (manual) or marked it unavailable. Idempotent; never raises.
    """
    path = MISSING_PATH_BY_STORE.get(store.lower())
    if path is None:
        return
    queue = _read_queue(path)
    target_key = _normalize_key(product_name)
    filtered = [e for e in queue if _normalize_key(e.get("product_name", "")) != target_key]
    if len(filtered) != len(queue):
        _write_queue(path, filtered)


def format_missing_summary() -> str:
    """Render the Queue Summary block for the sync command output."""
    from core.name_matcher import get_pending_mappings

    unmapped = len(get_pending_mappings())
    ww_missing = len(get_missing_items("woolworths"))
    coles_missing = len(get_missing_items("coles"))

    return (
        "**Queue Summary:**\n"
        f"- \U0001f4dd Unmapped items: {unmapped}\n"
        f"- \u274c Woolworths missing items (on Coles list, not at Woolworths): {ww_missing}\n"
        f"- \u274c Coles missing items (on Woolworths list, not at Coles): {coles_missing}"
    )
