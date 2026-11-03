#!/usr/bin/env python3
"""Coles cookie REFRESH (user protocol 2026-11-04: "if it fails 2 times send
me a message on telegram saying coles failed fresh cookie from my browser
required to run - once i open coles site i reply coles on telegram and then
you can fetch fresh cookie from my open session and restart the run").

Borrows the user's live Coles cookies from their OWN Chrome (the one they
just opened coles.com.au in) and hands them to the walker:
  data/coles-catalogue/cookies.json  ->  injected by coles_catalogue_walk.py

PROTOCOL REALITY (live-proven 2026-11-04): while Chrome is RUNNING it holds
the cookie DB locked (share-denied — plain reads, sqlite and esentutl all
fail). So the user's sequence is: open coles.com.au in Chrome -> reply
"coles" -> FULLY QUIT Chrome (flushes the fresh clearance to disk and
unlocks the file). The moment Chrome is gone, the DB is copyable; the user
can reopen Chrome right after the borrow. The supervisor's --auto poller
fires by itself within 60s of the unlock — no further interaction needed.

HOW (no cookie-value decryption in Python — Chrome does it itself):
  Chrome encrypts its cookie DB with an app-bound key tied to the Chrome
  BINARY (not the profile path), so a COPIED profile is decryptable by real
  Chrome wherever it lives. We copy the freshest Coles profile's cookie DB
  (+ Local State) into a scratch dir, open it with REAL Chrome via
  Playwright, visit coles.com.au — Chrome decrypts the user's cookies, the
  Imperva clearance rides along, and we read the (now session-refreshed)
  cookies straight out of the live context. The visit doubles as the
  verification: no __NEXT_DATA__ = the borrow failed.

Modes:
  python core/coles_refresh_cookie.py                 # fetch NOW (the
        agent runs this when the user replies "coles"; also manual)
  python core/coles_refresh_cookie.py --auto --since "2026-11-04T09:00:00"
        # supervisor poll: exit 10 = nothing to borrow yet (Chrome still
        # running, or no Coles visit since --since); otherwise fetch ->
        # 0 ok / 1 fail

Never prints or logs cookie VALUES. Scratch profile is deleted after.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRACKER = HERE.parent
DATA_DIR = TRACKER / "data" / "coles-catalogue"
OUT_PATH = DATA_DIR / "cookies.json"
CHROME_USER_DATA = Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
BASE = "https://www.coles.com.au"
SYDNEY = timezone(timedelta(hours=11))

# Chrome DB timestamps are microseconds since 1601-01-01 (Windows epoch)
CHROME_EPOCH_OFFSET_S = 11644473600


def log(msg: str) -> None:
    print(f"[cookie-refresh {datetime.now(SYDNEY).strftime('%H:%M:%S')}] {msg}", flush=True)


LOCK_HELP = ("Chrome still holds the cookie file locked — the user must "
             "FULLY QUIT Chrome (tray icon -> exit, all windows closed); "
             "the borrow fires the moment it unlocks")


def _copy_retry(src: Path, dst: Path, tries: int = 3) -> None:
    """Copy a file Chrome may be mid-writing (WAL churn) — retry on lock.
    Raises PermissionError with LOCK_HELP context when Chrome keeps the
    file share-locked (i.e. it is still running)."""
    for i in range(tries):
        try:
            shutil.copy2(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise PermissionError(f"{src.name}: {LOCK_HELP}") from None
            time.sleep(1)


def _profile_cookie_dbs() -> list[tuple[str, Path]]:
    """(profile name, Network/Cookies path) for every Chrome profile."""
    out = []
    if not CHROME_USER_DATA.exists():
        return out
    for entry in sorted(CHROME_USER_DATA.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if name != "Default" and not name.startswith("Profile "):
            continue
        for rel in ("Network/Cookies", "Cookies"):
            ck = entry / rel
            if ck.exists():
                out.append((name, ck))
                break
    return out


def _coles_rows(db_path: Path) -> list[dict]:
    """Cookie rows for coles.com.au from a COPY of the DB (names/timestamps
    only — values stay encrypted and are never read here)."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "Cookies"
        _copy_retry(db_path, tmp)
        conn = sqlite3.connect(f"file:{tmp.as_posix()}?mode=ro", uri=True)
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(cookies)")}
            stamp_col = "last_update_utc" if "last_update_utc" in cols else "creation_utc"
            rows = conn.execute(
                f"SELECT host_key, name, {stamp_col} FROM cookies "
                "WHERE host_key LIKE '%coles.com.au%'").fetchall()
        finally:
            conn.close()
    return [{"host": h, "name": n, "stamp": s or 0} for h, n, s in rows]


def _stamp_to_iso(us: int) -> str:
    try:
        return datetime.fromtimestamp(us / 1_000_000 - CHROME_EPOCH_OFFSET_S, SYDNEY).isoformat()
    except Exception:
        return "?"


def user_visited_since(since_dt: datetime) -> tuple[bool, str]:
    """Has the user's Chrome touched any coles.com.au cookie since since_dt?
    Returns (yes, freshest-profile-name or '')."""
    best_iso, best_profile = 0, ""
    for name, db in _profile_cookie_dbs():
        try:
            rows = _coles_rows(db)
        except Exception:
            continue
        newest = max((r["stamp"] for r in rows), default=0)
        if newest > best_iso:
            best_iso, best_profile = newest, name
    if not best_iso:
        return False, ""
    # re-parse: compare in unix seconds
    fresh = best_iso / 1_000_000 - CHROME_EPOCH_OFFSET_S > since_dt.timestamp()
    return fresh, best_profile


def extract(profile: str) -> int:
    """Copy the profile's cookie bits, open REAL Chrome on the copy, visit
    Coles, save verified cookies. 0 ok / 1 fail."""
    from playwright.sync_api import sync_playwright

    src_profile = CHROME_USER_DATA / profile
    src_cookies = None
    for rel in ("Network/Cookies", "Cookies"):
        if (src_profile / rel).exists():
            src_cookies = src_profile / rel
            break
    if not src_cookies:
        log(f"FATAL: no cookie DB in profile {profile}")
        return 1

    scratch = Path(tempfile.mkdtemp(prefix="coles-cookie-"))
    ud = scratch / "User Data"
    (ud / "Default" / "Network").mkdir(parents=True)
    _copy_retry(CHROME_USER_DATA / "Local State", ud / "Local State")
    _copy_retry(src_cookies, ud / "Default" / "Network" / "Cookies")
    for suffix in ("-wal", "-shm"):
        if Path(str(src_cookies) + suffix).exists():
            _copy_retry(Path(str(src_cookies) + suffix),
                        ud / "Default" / "Network" / ("Cookies" + suffix))

    log(f"profile {profile}: copied — launching real Chrome on the copy")
    try:
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(ud),
                channel="chrome",  # REAL Chrome binary — it can decrypt the copy
                headless=False,    # Imperva detects headless (walker lesson)
                args=["--disable-blink-features=AutomationControlled"],
                viewport={"width": 1380, "height": 900},
            )
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
                page.goto(f"{BASE}/browse", timeout=60000, wait_until="domcontentloaded")
                try:
                    page.wait_for_selector("#__NEXT_DATA__", timeout=30000)
                except Exception:
                    pass
                data = page.evaluate(
                    "() => { const el = document.getElementById('__NEXT_DATA__');"
                    " return el ? el.textContent : null; }")
                if not data:
                    log("FATAL: challenge NOT passed even with the user's cookies — "
                        "ask the user to fully load coles.com.au in Chrome and retry")
                    return 1
                ua = page.evaluate("() => navigator.userAgent")
                cookies = [c for c in ctx.cookies(BASE) if "coles.com.au" in (c.get("domain") or "")]
                if not cookies:
                    log("FATAL: no coles.com.au cookies in the borrowed context")
                    return 1
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                OUT_PATH.write_text(json.dumps({
                    "fetchedAt": datetime.now(SYDNEY).isoformat(timespec="seconds"),
                    "userAgent": ua, "profile": profile, "cookies": cookies,
                }, indent=1))
                log(f"OK: {len(cookies)} coles cookies borrowed + challenge VERIFIED "
                    f"-> {OUT_PATH.name} (values never logged)")
                return 0
            finally:
                try:
                    ctx.close()
                except Exception:
                    pass
    except Exception as exc:
        log(f"FATAL: {type(exc).__name__}: {str(exc)[:200]}")
        return 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto", action="store_true",
                    help="gate on the user having (re)visited Coles since --since")
    ap.add_argument("--since", default="",
                    help="ISO datetime (Sydney); cookie rows must be newer")
    args = ap.parse_args()

    if args.auto:
        if not args.since:
            log("--auto needs --since")
            return 2
        since_dt = datetime.fromisoformat(args.since)
        fresh, profile = user_visited_since(since_dt)
        if not fresh:
            return 10  # quiet: nothing to borrow yet
        log(f"user visited Coles (profile {profile}) — fetching")
        return extract(profile)

    # manual/agent path: the user said go — fetch from the freshest profile
    best_stamp, best_profile = 0, "Default"
    for name, db in _profile_cookie_dbs():
        try:
            rows = _coles_rows(db)
        except PermissionError:
            log(f"profile {name}: LOCKED — {LOCK_HELP}")
            continue
        except Exception:
            continue
        newest = max((r["stamp"] for r in rows), default=0)
        log(f"profile {name}: {len(rows)} coles cookies, newest {_stamp_to_iso(newest)}")
        if newest > best_stamp:
            best_stamp, best_profile = newest, name
    if not best_stamp:
        log("FATAL: no coles.com.au cookies in ANY Chrome profile — "
            "open coles.com.au in Chrome first")
        return 1
    return extract(best_profile)


if __name__ == "__main__":
    sys.exit(main())
