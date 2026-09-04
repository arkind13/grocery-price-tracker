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
    """Atomic registry write (tempfile + os.replace).

    Retries the rename a few times: on OneDrive/AV-shadowed folders
    (this data dir) a freshly-written temp file can stay locked for a
    fraction of a second, making os.replace raise WinError 5.
    """
    path = Path(path) if path else REGISTRY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(registry, fh, indent=2, sort_keys=True)
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.2 * (attempt + 1))
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

    Reentrant WITHIN one process (nested reserve/confirm calls under
    ensure_codes must not self-deadlock); cross-process via the lock
    file. VPS-vs-local races are NOT covered — the verify step in
    reserve/confirm handles those (D-IC4).
    """

    _depth = 0  # per-process nesting depth (single-threaded CLI)

    def __enter__(self) -> "_advisory_lock":
        if _advisory_lock._depth > 0:
            _advisory_lock._depth += 1
            return self
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                self._fd = os.open(
                    str(LOCK_PATH),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.write(self._fd, str(os.getpid()).encode())
                _advisory_lock._depth += 1
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
        _advisory_lock._depth -= 1
        if _advisory_lock._depth > 0:
            return
        try:
            os.close(self._fd)
        finally:
            try:
                LOCK_PATH.unlink()
            except OSError:
                pass


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
