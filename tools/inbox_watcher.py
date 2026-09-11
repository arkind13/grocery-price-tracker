#!/usr/bin/env python3
"""PC watch-folder -> VPS inbox pusher (auto-ingest spec AI-M4).

The user saves a shop's post images/text into ONE folder; this
watcher pushes them to the VPS local-deals inbox and triggers the
ingest — the Telegram digest IS the result. Zero commands, zero
round trips (user directive 2026-09-11).

Layout:
    <root>/            -> shop-less AUTO<ddmmyy><HHMM> codes; the
                          digest asks which shop (never guesses)
    <root>/<Shop>/     -> shop-prefixed codes (Merjan -> MER…):
                          drop into a shop subfolder to pin it

Resilience (S1/S13/S14/S15): single-instance lock; a settle window
batches a burst of images into ONE post; sha256 dedupe (the same
image twice = one ingest); failed pushes queue in place and retry —
nothing lost, nothing duplicated.

Run:   python tools/inbox_watcher.py            (loop, auto-start)
       python tools/inbox_watcher.py --once     (single scan)
Install (one line, per-logon, hidden):
       powershell -ExecutionPolicy Bypass -File tools\\install_inbox_watcher.ps1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.sydney_time import SYDNEY_TZ  # noqa: E402

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp",
                      ".txt", ".text", ".md"}
DEFAULT_ROOT = Path.home() / "Desktop" / "shop-posts"
DEFAULT_SETTLE_S = 90            # no new file for 90s closes a batch
POLL_S = 10
RETRY_AFTER_S = 60               # S15: queue-then-retry cadence
LOCK_STALE_S = 15 * 60
PUSHED_HASH_CAP = 500
RETAIN_DAYS = 14                 # .sent pruning (user rule
                                 # 2026-09-11: no unbounded buildup)

# shop subfolder name -> the VPS ingest resolves the shop from the
# code's first three letters (core.local_deals._store_for_code)
SHOP_CODES = {"dunya": "DUN", "dun": "DUN", "dunya butchery": "DUN",
              "merjan": "MER", "mer": "MER",
              "merjan brothers": "MER",
              "fruitopia": "FRU", "fru": "FRU",
              "abusalim": "ABS", "abs": "ABS", "abu salim": "ABS"}
# Pre-created on every start (user answer 2026-09-11: 'subfolder but
# create the subfolder for those 4 shops pls') — the user only ever
# drops into them.
SHOP_SUBFOLDERS = ("Dunya", "Merjan", "Fruitopia", "Abu Salim")

VPS_ALIAS = os.getenv("INBOX_WATCHER_VPS", "myvps")
REMOTE_BASE = os.getenv(
    "INBOX_WATCHER_REMOTE_BASE",
    "/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker"
    "/data/local_deals_inbox")
REMOTE_INGEST = os.getenv(
    "INBOX_WATCHER_REMOTE_INGEST",
    "docker exec openclaw-core python3 /app/tasks/ai-tools/"
    "grocery_price_cli.py local-deals --ingest")


def _run(cmd: list[str], timeout: int = 120) -> int:
    """One subprocess call, no shell (space-safe). Returns rc."""
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-200:]
        print(f"[watcher] cmd failed ({proc.returncode}): "
              f"{' '.join(cmd[:3])}… {tail}")
    return proc.returncode


def file_hash(path: Path) -> str:
    """sha256 of a file's bytes (S14 dedupe key)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _state_path(root: Path) -> Path:
    return root / ".watcher_state.json"


def load_state(root: Path) -> dict:
    try:
        return json.loads(_state_path(root).read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return {"pushed": {}, "retry_after": 0}


def save_state(root: Path, state: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _state_path(root).write_text(json.dumps(state, indent=2),
                                 encoding="utf-8")


def _sydney_now() -> datetime:
    return datetime.now(ZoneInfo(SYDNEY_TZ))


def mint_code(shop_code: str | None,
              now: datetime | None = None) -> str:
    """AUTO1109260907 / MER1109260907 — shop-less vs shop-prefixed."""
    now = now or _sydney_now()
    return f"{shop_code or 'AUTO'}{now:%d%m%y%H%M}"


def _shop_code_for(folder_name: str) -> str | None:
    """Folder name -> shop code letters (None = unknown folder)."""
    return SHOP_CODES.get(" ".join(
        str(folder_name or "").lower().split()))


def ensure_shop_folders(root: Path) -> list[Path]:
    """Create the four shop subfolders under the watch root (user
    answer 2026-09-11) — idempotent; returns the ones it created."""
    root.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for name in SHOP_SUBFOLDERS:
        folder = root / name
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
            made.append(folder)
    return made


def scan_batches(root: Path, settle_s: int = DEFAULT_SETTLE_S,
                 now: float | None = None) -> list[dict]:
    """Settled, unpushed file groups, one per folder (S1: a burst of
    images dropped together forms ONE batch once quiet for
    settle_s). Root files form the AUTO batch; each shop subfolder
    its own. Unsupported/hidden files and unknown folders skipped.
    """
    now = time.time() if now is None else now
    if not root.is_dir():
        return []
    state = load_state(root)
    pushed = state.get("pushed") or {}
    batches: list[dict] = []
    folders = [root] + sorted(p for p in root.iterdir()
                              if p.is_dir()
                              and not p.name.startswith("."))
    for folder in folders:
        group: list[Path] = []
        for p in sorted(folder.iterdir()):
            if not p.is_file() or p.name.startswith("."):
                continue
            if p.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            if now - p.stat().st_mtime < settle_s:
                group = []        # still receiving — not settled yet
                break
            if file_hash(p) in pushed:
                continue          # S14: already ingested
            group.append(p)
        if group:
            shop_code = (None if folder == root
                         else _shop_code_for(folder.name))
            batches.append({"folder": folder, "shop_code": shop_code,
                            "files": group})
    return batches


def push_batch(batch: dict, code: str) -> bool:
    """mkdir the remote inbox dir, scp the files, trigger the ingest.
    Returns True only when every step succeeded (S15: any failure
    leaves the files queued for the next attempt)."""
    remote_dir = f"{REMOTE_BASE}/{code}"
    if _run(["ssh", VPS_ALIAS, f"mkdir -p '{remote_dir}'"]) != 0:
        return False
    dest = [f"{batch['folder'] / f.name}"
            for f in batch["files"]]
    if _run(["scp", "-q", *dest,
             f"{VPS_ALIAS}:{remote_dir}/"]) != 0:
        return False
    rc = _run(["ssh", VPS_ALIAS,
               f"{REMOTE_INGEST} {code}"], timeout=600)
    return rc == 0


def prune_sent(root: Path, keep_days: int = RETAIN_DAYS,
               now: float | None = None) -> int:
    """Delete .sent/<CODE> dirs older than keep_days (user rule
    2026-09-11: processed images do not pile up — the pushed hashes
    in the state file still dedupe re-drops). Returns how many
    were pruned."""
    now = time.time() if now is None else now
    sent = root / ".sent"
    if not sent.is_dir():
        return 0
    cutoff = now - keep_days * 86400
    pruned = 0
    for d in sent.iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                pruned += 1
        except OSError:
            continue
    return pruned


def run_once(root: Path, settle_s: int = DEFAULT_SETTLE_S,
             now: float | None = None,
             push=None, code_now=None) -> list[str]:
    """One scan-push-record cycle; returns report lines. `push` and
    `code_now` are injection seams for the offline tests."""
    now = time.time() if now is None else now
    push = push or push_batch
    state = load_state(root)
    if now < float(state.get("retry_after") or 0):
        return ["[watcher] retry window not reached — files keep "
                "waiting"]
    lines: list[str] = []
    pushed = state.setdefault("pushed", {})
    for batch in scan_batches(root, settle_s=settle_s, now=now):
        if batch["shop_code"] is None and batch["folder"] != root:
            lines.append(f"[watcher] {batch['folder'].name}/: not a "
                         f"known shop folder — ignored (use merjan/"
                         f" dunya/ fruitopia/ abusalim, or the "
                         f"folder root)")
            continue
        code = (code_now or (lambda: mint_code(batch["shop_code"])))()
        lines.append(f"[watcher] pushing {len(batch['files'])} "
                     f"file(s) as {code}")
        if not push(batch, code):
            state["retry_after"] = now + RETRY_AFTER_S
            save_state(root, state)
            lines.append(f"[watcher] push failed — files stay "
                         f"queued, retry in {RETRY_AFTER_S}s")
            return lines           # S13: never two writers, stop here
        for f in batch["files"]:
            pushed[file_hash(f)] = code
        while len(pushed) > PUSHED_HASH_CAP:   # trim oldest
            pushed.pop(next(iter(pushed)))
        sent = root / ".sent" / code
        sent.mkdir(parents=True, exist_ok=True)
        for f in batch["files"]:
            try:
                f.replace(sent / f.name)
            except OSError:
                pass
        lines.append(f"[watcher] {code}: pushed + ingest triggered")
    save_state(root, state)
    pruned = prune_sent(root)
    if pruned:
        lines.append(f"[watcher] pruned {pruned} .sent folder(s) "
                     f"older than {RETAIN_DAYS} days")
    return lines


def acquire_lock(root: Path) -> bool:
    """Single-instance lock (S13). A stale lock (no heartbeat for
    LOCK_STALE_S) is taken over."""
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".watcher.lock"
    if lock.exists():
        try:
            age = time.time() - lock.stat().st_mtime
            pid = int(lock.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            age, pid = LOCK_STALE_S + 1, 0
        if age < LOCK_STALE_S and pid != os.getpid():
            return False
    lock.write_text(str(os.getpid()), encoding="utf-8")
    return True


def heartbeat_lock(root: Path) -> None:
    """Refresh the lock mtime each loop iteration."""
    lock = root / ".watcher.lock"
    try:
        lock.touch()
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="inbox_watcher.py",
        description="PC watch-folder -> VPS auto-ingest pusher")
    ap.add_argument("--root", default=os.getenv(
        "INBOX_WATCHER_ROOT", str(DEFAULT_ROOT)),
        help="the ONE watched folder (default Desktop/shop-posts)")
    ap.add_argument("--settle", type=int, default=DEFAULT_SETTLE_S,
                    help="quiet seconds that close a batch (S1)")
    ap.add_argument("--once", action="store_true",
                    help="single scan cycle, then exit")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if not acquire_lock(root):
        print("[watcher] another instance holds the lock — exiting")
        return 0
    made = ensure_shop_folders(root)
    if made:
        print(f"[watcher] shop folders created: "
              f"{', '.join(f.name for f in made)}")
    print(f"[watcher] watching {root} (settle {args.settle}s)")
    try:
        while True:
            for line in run_once(root, settle_s=args.settle):
                print(line)
            if args.once:
                break
            heartbeat_lock(root)
            time.sleep(POLL_S)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
