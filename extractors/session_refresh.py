#!/usr/bin/env python3
"""Live window orchestrator: login once -> flush queues -> fetch lists.

Implements spec §4.1/§4.4/§4.5/§4.6 as ONE local command
(``live-refresh``). Phases:

    A  login   headed Chromium + persistent profile; inject saved
               cookies; per-store login check; .env credentials +
               2FA polling when logged out; exports cookies + timestamp.
    B  flush   adds BOTH queues (searched_items + add_to_list) to the
               store website "Price Compare" list via the captured
               add-to-list API; throttled; per-item log; success removes
               from the queue; failures stay queued (3-strike park);
               session death aborts that store's remaining flush.
    C  fetch   enumerates each store's saved lists (EXACT name match),
               walks ALL pages (30-page hard cap, DELTA-2), dedups by
               product id, and writes snapshots for live_list_fetch.

    discovery  captures the add-to-list API + pagination shape per
               store (once; `--recapture` forces it).

    heartbeat  measurement-only session liveness check (never triggers
               a login; never touches any third-party scraper service).

HARD RULES (spec): local Windows machine only (headed browser, AU
residential IP); authenticated paths never touch any third-party
scraper service (guardrail 5 — asserted by grep); the flush never
writes Col I/J keywords; page-load attempts capped at 2; 401/403 are
never retried; transient network errors get exactly 1 retry.

Playwright is imported LAZILY inside ``_open_browser`` so that importing
this module succeeds without playwright (tests, VPS, --help).

Testability seams (plan §4.7, mandatory): the pagination walker, flush
grouping, throttle pacing, 3-strike park, session-death abort, and log
rotation are pure-ish functions taking injected fakes (``fetch_page``,
``add_item``, ``clock``, ``sleep``, ``jitter``) — NO test ever launches
a browser.
"""
from __future__ import annotations
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_TRACKER_DIR = _HERE.parent
if str(_TRACKER_DIR) not in sys.path:
    sys.path.insert(0, str(_TRACKER_DIR))

DATA_DIR = _TRACKER_DIR / "data"
SESSION_STATE_PATH = DATA_DIR / "session_state.json"
PROFILE_DIR = DATA_DIR / "ww_coles_profile"
FLUSH_LOG_PATH = DATA_DIR / "live_flush_log.json"
CAPTURE_PATH = DATA_DIR / "live_api_capture.json"
SNAPSHOTS_DIR = DATA_DIR / "live_snapshots"
HEARTBEAT_LOG_PATH = DATA_DIR / "session_heartbeat.log"

# Real-Chrome opt-in (--real-profile): seed the tool's dedicated
# profile with the logins from the user's daily Chrome. Chrome >= 136
# ignores --remote-debugging-pipe when --user-data-dir IS the default
# directory, so a real daily profile can never be driven in place
# (launching on it hangs Playwright forever). We COPY the
# login-bearing files over instead, then launch our own profile.
REAL_CHROME_PROFILE_DIR = Path(
    os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"

STORES = ("woolworths", "coles")

# EXACT list names targeted per store (never guessed; mismatches print
# the available names and fail the store).
LIST_NAMES = {
    "ww": ["Price Compare", "Special list (28)"],
    "coles": ["Price Compare"],
}
STORE_LIST_NAMES = {
    "woolworths": LIST_NAMES["ww"],
    "coles": LIST_NAMES["coles"],
}
FLUSH_TARGET_LIST = "Price Compare"   # flush NEVER touches the Specials list

PAGE_HARD_CAP = 30                    # per list (DELTA-2)
DEFAULT_PAGE_SIZE = 50

FLUSH_THROTTLE_S = 1.5
FLUSH_JITTER_S = 0.5
TWO_FA_WAIT_S = 180                   # <= 3 min
PAGE_LOAD_ATTEMPTS = 2                # §5.1 page-load cap
PARK_AFTER_ATTEMPTS = 3               # 3-strike park
FLUSH_LOG_MAX_BYTES = 1_000_000       # rotate beyond ~1 MB

FLUSH_LOG_FILENAME = "live_flush_log.json"


class LiveFetchError(RuntimeError):
    """One store's page fetch failed (store marked failed, §5.1)."""


def _now_iso() -> str:
    """Current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# Generic IO helpers
# ============================================================================
def _read_json(path: Path, default):
    """Read JSON; corrupt/missing -> default (never raises)."""
    try:
        if Path(path).exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except (OSError, ValueError):
        pass
    return default


def _write_json_atomic(path: Path, data) -> None:
    """Write JSON atomically (tempfile + os.replace)."""
    import tempfile
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(suffix=".json",
                                    prefix=path.stem + "_",
                                    dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _parse_json_body(text) -> dict:
    """Best-effort JSON request-body parse; {} when missing/invalid (P4c)."""
    try:
        data = json.loads(text or "")
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def _rotate_log_if_large(path: Path, max_bytes: int = FLUSH_LOG_MAX_BYTES) -> bool:
    """Rotate a JSON log aside when it exceeds max_bytes (keeps .1).

    Args:
        path (Path): log file path.
        max_bytes (int): size threshold.

    Returns:
        bool: True when a rotation happened.
    """
    path = Path(path)
    try:
        if path.exists() and path.stat().st_size > max_bytes:
            rotated = path.with_suffix(path.suffix + ".1")
            os.replace(str(path), str(rotated))
            return True
    except OSError:
        pass
    return False


# ============================================================================
# Pagination walker (Phase C core — pure, injectable, W-1..W-4)
# ============================================================================
def _walk_pagination(fetch_page, *, page_size: int,
                     max_pages: int | None = None,
                     store_label: str = "list") -> dict:
    """Walk a paginated list API until exhausted or capped.

    Args:
        fetch_page: callable(page_number) -> {"items": [...],
            "has_more": bool | None} or None on failure. ``has_more``
            absent (None) means "infer from page fullness".
        page_size (int): expected page size for short-page inference.
        max_pages (int | None): hard cap (PAGE_HARD_CAP when None).
        store_label (str): label for the per-list log line.

    Returns:
        dict: {"items": [...], "pages": int, "capped": bool,
        "warning": str}. ``warning`` is the LOUD cap warning ("" when
        the walk finished under the cap).

    Raises:
        LiveFetchError: when a page fetch fails (1 attempt per page,
        pages in order — §5.1); the store is then marked failed.
    """
    max_pages = max_pages or PAGE_HARD_CAP
    items: list = []
    pages = 0
    capped = False
    warning = ""
    for page in range(1, max_pages + 1):
        try:
            result = fetch_page(page)
        except Exception as exc:
            raise LiveFetchError(
                f"{store_label}: page {page} fetch failed: {exc}") from exc
        if result is None:
            raise LiveFetchError(
                f"{store_label}: page {page} fetch failed")
        page_items = list(result.get("items", []))
        items.extend(page_items)
        pages = page
        has_more = result.get("has_more")
        if has_more is None:
            if len(page_items) < page_size:
                break                      # W-2: short page, no field
            continue
        if not has_more:
            break                          # W-1: explicit end
    else:
        capped = True                      # W-3: cap reached
        warning = (f"WARNING: {store_label}: hit the {max_pages}-page "
                   f"hard cap — {len(items)} items fetched so far; "
                   f"THE LIST MAY BE INCOMPLETE.")
        print(warning, file=sys.stderr)
    if store_label and not capped:
        # W-4: per-list log line.
        print(f"{store_label}: {pages} pages, {len(items)} items")
    return {"items": items, "pages": pages, "capped": capped,
            "warning": warning}


# ============================================================================
# List-name matching (W-14: exact match; never guesses)
# ============================================================================
def _match_list_names(available: list, targets: list) -> list:
    """EXACT-match target list names against available names.

    Args:
        available (list[str]): names reported by the store.
        targets (list[str]): the exact names this integration targets.

    Returns:
        list[str]: the matched names (in target order).

    Raises:
        ValueError: when any target is missing — the message prints the
        AVAILABLE names and never guesses a substitute.
    """
    available_set = {str(a).strip() for a in available}
    missing = [t for t in targets if t not in available_set]
    if missing:
        raise ValueError(
            f"Exact-match list name(s) not found: {missing}. "
            f"Available lists: {sorted(available_set)}. "
            f"Rename the list (or update LIST_NAMES) — guessing is "
            f"never attempted.")
    return list(targets)


# ============================================================================
# Flush engine (Phase B core — pure, injectable, W-5..W-13)
# ============================================================================
def _group_by_store(entries: list) -> dict:
    """Group queue entries by store (insertion order preserved).

    Only 'coles'/'woolworths' entries are grouped; anything else is
    ignored (defensive).

    Args:
        entries (list[dict]): queue entries.

    Returns:
        dict: store -> [entries].
    """
    grouped: dict = {}
    for entry in entries:
        store = str(entry.get("store", "")).strip().lower()
        if store in STORES:
            grouped.setdefault(store, []).append(entry)
    return grouped


def _load_attempt_history(log_path: Path) -> dict:
    """Sum per-item add attempts from the flush log.

    Args:
        log_path (Path): flush log path.

    Returns:
        dict: (store, keyword) -> total attempts.
    """
    history: dict = {}
    records = _read_json(log_path, [])
    if isinstance(records, list):
        for rec in records:
            if not isinstance(rec, dict):
                continue
            key = (str(rec.get("store", "")),
                   str(rec.get("keyword", "")))
            history[key] = history.get(key, 0) + int(rec.get("attempts", 0) or 0)
    return history


def _flush_store(store: str, entries: list, *, add_item, consume_entry,
                 log_append, sleep=time.sleep, clock=time.monotonic,
                 jitter=None) -> dict:
    """Flush one store's queue entries (pure-ish; fully injectable).

    Semantics (§4.4 / §5.1):
        - throttle: every add AFTER the first waits FLUSH_THROTTLE_S +
          jitter() seconds (W-12);
        - transient failure -> exactly ONE retry; 401/403
          (session_death) -> never retried and aborts the remaining
          items for this store (W-10/W-11);
        - success -> consume_entry(entry) removes it from its queue
          (W-6); failure -> stays queued with reason + attempts (W-7);
          one item's failure never blocks the others (W-9).

    Args:
        store (str): store id.
        entries (list[dict]): the entries to add (parked EXCLUDED by the
            caller via _partition_parked).
        add_item: callable(entry) -> {"status": "added"|"failed",
            "kind": "ok"|"session_death"|"transient"|"permanent",
            "reason": str}.
        consume_entry: callable(entry) — removes a successful entry
            from its queue + tombstones its code.
        log_append: callable(record) — appends one flush-log record.
        sleep: injected sleep (tests record calls).
        clock: injected monotonic clock.
        jitter: callable() -> seconds 0..FLUSH_JITTER_S.

    Returns:
        dict: {"added": [...], "failed": [...], "session_died": bool}.
    """
    jitter = jitter or (lambda: 0.0)
    summary: dict = {"added": [], "failed": [], "session_died": False}
    last_add_ts = None
    for entry in entries:
        keyword = str(entry.get("keyword", "") or
                      entry.get("generic_name", ""))
        attempts = 0
        status = "failed"
        reason = ""
        for attempt in (1, 2):
            if last_add_ts is not None:
                sleep(FLUSH_THROTTLE_S + float(jitter()))
            last_add_ts = clock()
            attempts = attempt
            try:
                result = add_item(entry)
            except Exception as exc:
                result = {"status": "failed", "kind": "transient",
                          "reason": f"add failed: {exc}"}
            kind = str(result.get("kind", "permanent"))
            reason = str(result.get("reason", ""))
            if result.get("status") == "added":
                status = "added"
                break
            if kind == "session_death":
                status = "session_death"
                break
            if kind == "transient" and attempt == 1:
                continue                   # W-11: exactly 1 retry
            status = "failed"
            break
        record = {
            "store": store,
            "keyword": keyword,
            "status": status,
            "reason": reason,
            "attempts": attempts,
            "ts": _now_iso(),
        }
        code = str(entry.get("code", "") or "")
        if code:
            record["code"] = code
        log_append(record)
        if status == "added":
            try:
                consume_entry(entry)
            except Exception as exc:
                # Queue rewrite failure must not fail the (already
                # successful) website add; surfaced via the log record.
                record["status"] = "added_queue_rewrite_failed"
                record["reason"] = f"consume failed: {exc}"
                log_append(record)
            summary["added"].append(entry)
        elif status == "session_death":
            summary["failed"].append({**entry, "reason": reason})
            summary["session_died"] = True
            break                          # W-10: abort remaining flush
        else:
            summary["failed"].append({**entry, "reason": reason})
    return summary


def _partition_parked(store: str, entries: list, history: dict) -> tuple:
    """Split entries into (to_flush, parked) by accumulated attempts.

    Args:
        store (str): store id.
        entries (list[dict]): this store's queue entries.
        history (dict): (store, keyword) -> accumulated attempts.

    Returns:
        tuple: (to_flush, parked) entry lists.
    """
    to_flush, parked = [], []
    for entry in entries:
        key = (store, str(entry.get("keyword", "") or
                          entry.get("generic_name", "")))
        if history.get(key, 0) >= PARK_AFTER_ATTEMPTS:
            parked.append(entry)
        else:
            to_flush.append(entry)
    return to_flush, parked


def _append_flush_log(log_path: Path, record: dict) -> None:
    """Append one record to the flush log (rotate-then-write)."""
    _rotate_log_if_large(log_path)
    records = _read_json(log_path, [])
    if not isinstance(records, list):
        records = []
    records.append(record)
    _write_json_atomic(log_path, records)


# ============================================================================
# Phase B queue plumbing (real consume paths)
# ============================================================================
def _load_both_queues() -> list:
    """Load BOTH queues (searched_items + add_to_list) as entries.

    Returns:
        list[dict]: entries tagged with "queue": "searched_items" |
        "add_to_list" (the tag is internal to this module).
    """
    from core import add_to_list as atl
    from core import searched_items as si
    entries = []
    for entry in si.load_pending():
        item = dict(entry)
        item["queue"] = "searched_items"
        entries.append(item)
    for entry in atl.load_pending():
        item = dict(entry)
        item["queue"] = "add_to_list"
        entries.append(item)
    return entries


def _consume_queue_entry(entry: dict) -> None:
    """Remove one SUCCESSFULLY added entry from its queue (W-6).

    searched_items entries go through consume_entries (removes +
    tombstones the code); add_to_list entries are rewritten away
    (that module has no codes).
    """
    from core import add_to_list as atl
    from core import searched_items as si
    store = str(entry.get("store", "")).strip().lower()
    if entry.get("queue") == "searched_items":
        si.consume_entries(store, [entry])
        return
    norm = atl._normalize_key(str(entry.get("generic_name", "")))
    remaining = [
        e for e in atl.load_pending()
        if not (str(e.get("store", "")).strip().lower() == store
                and atl._normalize_key(str(e.get("generic_name", ""))) == norm)
    ]
    atl.save_pending(remaining)


# ============================================================================
# Discovery capture (§4.5, W-20)
# ============================================================================
def _needs_capture(store: str, capture_path: Path = None) -> bool:
    """Whether a valid discovery capture exists for the store."""
    path = Path(capture_path) if capture_path else CAPTURE_PATH
    capture = _read_json(path, {})
    entry = capture.get(store) if isinstance(capture, dict) else None
    return not (isinstance(entry, dict) and entry.get("url"))


def _write_discovery_capture(store: str, capture: dict,
                             capture_path: Path = None) -> None:
    """Persist one store's discovery capture {method, url, body_shape,
    pagination} (merged per store; atomic)."""
    path = Path(capture_path) if capture_path else CAPTURE_PATH
    all_captures = _read_json(path, {})
    if not isinstance(all_captures, dict):
        all_captures = {}
    all_captures[store] = capture
    _write_json_atomic(path, all_captures)


# ============================================================================
# Heartbeat (§4.6 — measurement only)
# ============================================================================
def run_heartbeat(*, state_path: Path = None, log_path: Path = None,
                  fetcher=None) -> dict:
    """One liveness probe per store; appends to the heartbeat log.

    Uses saved cookies ONLY — never triggers a login, never touches any
    third-party scraper service. Coles is best-effort ("unknown" is
    tolerated). NEVER raises: every failure is absorbed into the log
    line ("unknown").

    Args:
        state_path (Path | None): session_state.json path.
        log_path (Path | None): heartbeat log path.
        fetcher: optional callable(store, url, cookies) -> int status
            (injected for tests); curl_cffi is lazy-imported when None.

    Returns:
        dict: store -> "alive" | "dead" | "unknown".
    """
    state_path = Path(state_path) if state_path else SESSION_STATE_PATH
    log_path = Path(log_path) if log_path else HEARTBEAT_LOG_PATH
    state = _read_json(state_path, {})
    results: dict = {}
    checks = {
        "woolworths": ("https://www.woolworths.com.au/apis/ui/mylists",
                       "alive"),
        "coles": (str(state.get("coles", {}).get("check_url", "") or ""),
                  "unknown"),          # Coles best-effort
    }
    for store, (url, fallback) in checks.items():
        status = fallback
        cookies = (state.get(store, {}) or {}).get("cookies", {})
        try:
            if url:
                probe = fetcher
                if probe is None:
                    from curl_cffi import requests as cffi_requests
                    def probe(_store, _url, _cookies):
                        resp = cffi_requests.get(
                            _url, cookies=_cookies, timeout=20,
                            impersonate="chrome131")
                        return resp.status_code
                code = int(probe(store, url, cookies))
                if code == 200:
                    status = "alive"
                elif code in (401, 403):
                    status = "dead"
        except Exception:
            status = fallback if fallback == "unknown" else "unknown"
        results[store] = status
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            for store in STORES:
                f.write(f"{results.get(store, 'unknown')} {_now_iso()}\n")
    except OSError:
        pass
    return results


# ============================================================================
# Browser session (Phase A) — lazy playwright
# ============================================================================
def _chrome_is_running() -> bool:
    """Whether a chrome.exe process is up (Windows-only check).

    Used as a pre-flight guard for --real-profile: the daily profile's
    cookie files are locked while Chrome runs (and a clean Chrome
    shutdown purges session cookies — seeding must happen while it is
    fully closed).
    """
    if sys.platform != "win32":
        return False
    try:
        import subprocess
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
            capture_output=True, text=True, timeout=15).stdout or ""
        return "chrome.exe" in out.lower()
    except Exception:
        return False


def _seed_login_cookies_from_real_chrome(target_dir: Path) -> str:
    """Copy the login-bearing files from the user's daily Chrome
    profile into ``target_dir`` (the tool's dedicated profile).

    Why a copy (Chrome >= 136): Chrome ignores --remote-debugging-pipe
    when --user-data-dir points at the DEFAULT profile directory, so
    the daily profile can never be driven directly — launching on it
    hangs Playwright forever. Seeding our own profile with
    ``Local State`` (holds the os_crypt key; decryptable by the same
    installed chrome.exe + same Windows user) plus the Cookies DB
    carries the Woolworths/Coles logins over instead.

    Args:
        target_dir (Path): the persistent profile to seed (PROFILE_DIR).

    Returns:
        str: human-readable summary of what was seeded (no PII — file
        names only). NEVER raises; on any failure Phase A simply falls
        back to a normal in-window login.
    """
    import shutil
    src_root = REAL_CHROME_PROFILE_DIR
    if not (src_root / "Local State").exists():
        return "no daily Chrome profile found — starting fresh"
    # The daily logins may live in a non-Default profile dir
    # ("Profile 1", ...). Local State records the last-used one.
    profile_dir_name = "Default"
    try:
        state = _read_json(src_root / "Local State", {})
        name = str(((state or {}).get("profile") or {}).get(
            "last_used", "") or "")
        if (name and name not in (".", "..")
                and re.fullmatch(r"[\w][\w .-]*", name)):
            profile_dir_name = name
    except Exception:
        pass
    candidates = [
        src_root / "Local State",
        src_root / profile_dir_name / "Network" / "Cookies",
        src_root / profile_dir_name / "Cookies",   # pre-130 layout
    ]
    copied: list = []
    for src in candidates:
        try:
            if not src.exists():
                continue
            dst = target_dir / src.relative_to(src_root)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
            copied.append(str(dst.relative_to(target_dir)))
        except OSError:
            pass  # locked/missing -> Phase A falls back to a login
    if not copied:
        return "nothing copied (Chrome still running or files locked)"
    return "seeded: " + ", ".join(copied)


def _open_browser(real_profile: bool = False):
    """Launch headed Chrome with a persistent profile (LAZY import).

    Args:
        real_profile (bool): seed the tool's dedicated profile with the
            user's daily-Chrome logins first (requires Chrome fully
            closed). The launch itself is ALWAYS on the dedicated
            profile — the daily profile cannot be driven in place
            (Chrome >= 136 ignores the control channel on the default
            directory).

    Returns:
        _LocalDriver: the live driver.

    Raises:
        RuntimeError: with the user-facing guidance when playwright is
        unavailable (browser-less environment — VPS/CI/tests), or when
        the daily profile is locked (Chrome still running).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "live-refresh requires a local desktop (Playwright) — "
            "run it on the Windows machine") from exc
    return _LocalDriver(sync_playwright, profile_dir=PROFILE_DIR,
                        seed_from_real=real_profile)


class _LocalDriver:
    """Playwright-backed driver implementing the protocol used by the
    phase functions. Method-by-method behaviour is intentionally
    straightforward; the DISCOVERY capture (§4.5) is what makes the
    add/list API calls accurate — until a capture exists, Phase B/C
    refuse to guess and route the store through discovery."""

    def __init__(self, sync_playwright_factory, profile_dir: Path = None,
                 seed_from_real: bool = False):
        self._factory = sync_playwright_factory
        self._profile_dir = (Path(profile_dir) if profile_dir
                             else PROFILE_DIR)
        self._seed_from_real = seed_from_real
        self._pw = None
        self._context = None
        self._pages = {}

    def start(self):
        """Launch the persistent-profile browser context."""
        if self._seed_from_real:
            if _chrome_is_running():
                raise RuntimeError(
                    "Chrome is still running — close EVERY Chrome window "
                    "(and the tray icon), then re-run with --real-profile. "
                    "The daily-profile cookie files are locked while it "
                    "runs.")
            print(_seed_login_cookies_from_real_chrome(self._profile_dir))
        self._pw = self._factory().start()
        launch_kwargs = {
            "headless": False,
            # Fail loudly instead of hanging forever if Chrome ever
            # fails to bring up its control channel.
            "timeout": 60000,
            # Hide the AutomationControlled blink flag (Akamai signal).
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        try:
            # Real branded Chrome: the bundled-Chromium brand fingerprint
            # is what Akamai denied on woolworths.com.au (M3 finding,
            # 2026-08-30). Falls back to bundled Chromium when the
            # channel is unavailable on this machine.
            self._context = self._pw.chromium.launch_persistent_context(
                str(self._profile_dir), channel="chrome", **launch_kwargs)
        except Exception:
            self._context = self._pw.chromium.launch_persistent_context(
                str(self._profile_dir), **launch_kwargs)
        try:
            self._context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', "
                "{get: () => undefined});")
        except Exception:
            pass
        for store, url in (
            ("woolworths", "https://www.woolworths.com.au/"),
            ("coles", "https://www.coles.com.au/"),
        ):
            page = self._context.new_page()
            self._goto_store(page, url)
            self._pages[store] = page
        return self

    def _goto_store(self, page, url: str) -> None:
        """Navigate with the §5.1 two-attempt cap; a CDN denial page
        (woolworths 'unauthorisederror' / Akamai 'Access Denied')
        counts as a failed attempt and is retried once."""
        for _attempt in range(PAGE_LOAD_ATTEMPTS):
            try:
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
            except Exception:
                continue
            if not self._is_denied(page):
                return
            time.sleep(2.0)          # brief cooldown before the retry

    @staticmethod
    def _is_denied(page) -> bool:
        """Whether the page landed on a CDN/bot-manager denial page."""
        try:
            url = str(page.url).lower()
            if ("unauthorisederror" in url
                    or "errors.edgesuite" in url
                    or "/accessdenied" in url):
                return True
            return "access denied" in str(page.title()).strip().lower()
        except Exception:
            return False

    def page(self, store):
        """The live page object for one store."""
        return self._pages[store]

    def evaluate(self, store, expression, arg=None):
        """Run an async JS expression in the store's page context."""
        return self.page(store).evaluate(expression, arg)

    def cookies(self, store) -> list:
        """Export cookies for one store's origin ONLY.

        Scoped on purpose (defence in depth): only the store's own
        cookies are ever persisted to session_state.json, even if the
        profile ever holds more than the store sessions.
        """
        url = ("https://www.woolworths.com.au"
               if store == "woolworths" else "https://www.coles.com.au")
        return self._context.cookies([url])

    def set_cookies(self, cookies):
        """Inject previously saved cookies into the context."""
        if cookies:
            self._context.add_cookies(cookies)

    def close(self):
        """Close the browser context + playwright driver."""
        try:
            if self._context:
                self._context.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    def capture_add_to_list(self, store: str):
        """Record the real add-to-list API call (D26 discovery, §4.5).

        Attaches a Playwright request listener BEFORE prompting, prints
        the guided prompt, then polls up to TWO_FA_WAIT_S (3 min) for the
        FIRST same-origin non-GET request whose URL or body mentions a
        list. Coles additionally resolves + verifies `lists_url` (and
        sets `check_url`); a failed verification returns None so no
        broken capture is saved.

        Args:
            store: "woolworths" | "coles".

        Returns:
            dict: {"method", "url", "body_shape"} (+ "lists_url",
            "check_url" for coles), or None when nothing was captured.
        """
        page = self._pages[store]
        origin = ("https://www.woolworths.com.au"
                  if store == "woolworths"
                  else "https://www.coles.com.au")
        add_candidates: list = []
        list_gets: list = []

        def _on_request(request):
            try:
                method = str(request.method).upper()
                url = str(request.url)
                if not url.startswith(origin):
                    return
                if method != "GET":
                    body = request.post_data or ""
                    if "list" in url.lower() or "list" in body.lower():
                        add_candidates.append({
                            "method": method,
                            "url": url,
                            "body_shape": _parse_json_body(body),
                        })
                elif "list" in url.lower():
                    list_gets.append(url)
            except Exception:
                pass  # listener must never break the page

        page.on("request", _on_request)
        print(f"Add ONE item to your Price Compare list in the open "
              f"window ({store})…")
        deadline = time.monotonic() + TWO_FA_WAIT_S
        while time.monotonic() < deadline and not add_candidates:
            time.sleep(1.0)
        try:
            page.remove_listener("request", _on_request)
        except Exception:
            pass
        if not add_candidates:
            return None
        capture = dict(add_candidates[0])  # FIRST candidate wins
        if store == "coles":
            lists_url = self._verify_coles_lists_url(list_gets)
            if not lists_url:
                return None  # broken capture — discovery FAILED
            capture["lists_url"] = lists_url
            capture["check_url"] = lists_url
        return capture

    def _verify_coles_lists_url(self, list_gets: list):
        """Resolve + verify the Coles saved-lists URL (P4d).

        Candidates: observed same-origin GETs containing "list" (most
        recent first), then the current page URL when it contains
        "list". A candidate verifies when an in-page fetch returns ok
        AND a JSON array. Returns the verified URL or "".
        """
        page = self._pages["coles"]
        candidates: list = []
        seen = set()
        for url in reversed(list_gets):
            if url not in seen:
                seen.add(url)
                candidates.append(url)
        try:
            current = str(page.url)
            if "list" in current.lower() and current not in seen:
                candidates.append(current)
        except Exception:
            pass
        expression = (
            "async ([url]) => { try { const r = await fetch(url);"
            " if (!r.ok) return null; const data = await r.json();"
            " return Array.isArray(data) ? url : null; }"
            " catch (e) { return null; } }")
        for url in candidates:
            try:
                if self.evaluate("coles", expression, [url]) == url:
                    return url
            except Exception:
                continue
        return ""


def _inject_saved_cookies(driver, store: str) -> None:
    """Inject the store's saved cookies (never printed, never logged)."""
    state = _read_json(SESSION_STATE_PATH, {})
    cookies = (state.get(store, {}) or {}).get("cookies")
    try:
        driver.set_cookies(cookies)
    except Exception:
        pass


def _ww_logged_in(driver) -> bool:
    """WW login check: in-page fetch of /apis/ui/mylists is non-empty."""
    try:
        result = driver.evaluate(
            "woolworths",
            "async () => { try { const r = await fetch('/apis/ui/mylists');"
            " const t = await r.text(); return t && t !== 'null'; }"
            " catch (e) { return false; } }")
        return bool(result)
    except Exception:
        return False


def _coles_logged_in(driver) -> bool:
    """Coles login check per the discovery capture (fallback: marker)."""
    capture = _read_json(CAPTURE_PATH, {})
    check_url = str((capture.get("coles", {}) or {}).get("check_url", "") or "")
    expression = (
        "async () => { try { const r = await fetch("
        + json.dumps(check_url or "/api/v1/security/user/information")
        + "); return r.status === 200; } catch (e) { return false; } }")
    try:
        return bool(driver.evaluate("coles", expression))
    except Exception:
        return False


def _store_logged_in(driver, store: str) -> bool:
    """Per-store login check dispatch."""
    return _ww_logged_in(driver) if store == "woolworths" \
        else _coles_logged_in(driver)


def _get_credentials(store: str) -> tuple:
    """Read the store's credentials from the environment (.env-loaded).

    The agent NEVER reads, writes, echoes, or logs secret values — the
    values are only ever passed into the browser page.

    Returns:
        tuple: (user, password) — either may be "" when missing.
    """
    prefix = "WOOLWORTHS" if store == "woolworths" else "COLES"
    return os.getenv(f"{prefix}_USER", ""), os.getenv(f"{prefix}_PASS", "")


def _phase_a_login(driver, summary: dict) -> None:
    """Phase A: per-store login (cookies first, credentials + 2FA next)."""
    for store in STORES:
        try:
            _inject_saved_cookies(driver, store)
            if _store_logged_in(driver, store):
                summary[store]["login"] = True
                continue
            user, password = _get_credentials(store)
            if not user or not password:
                if store == "coles":
                    print("COLES_USER/COLES_PASS missing — add them to "
                          ".env and re-run live-refresh")
                summary[store]["login"] = False
                continue
            print(f"Complete 2FA in the window ({store})…")
            deadline = time.monotonic() + TWO_FA_WAIT_S
            logged_in = False
            while time.monotonic() < deadline:
                if _submit_credentials(driver, store, user, password):
                    pass  # submitted once; keep polling the check below
                if _store_logged_in(driver, store):
                    logged_in = True
                    break
                time.sleep(3)
            summary[store]["login"] = logged_in
            if logged_in:
                _export_session_cookies(driver, store)
        except Exception as exc:
            print(f"[session_refresh] login check failed for "
                  f"{store}: {exc}", file=sys.stderr)
            summary[store]["login"] = False


def _submit_credentials(driver, store: str, user: str, password: str) -> bool:
    """Best-effort credential fill on the store's login page (once)."""
    try:
        selector_user = ("#email" if store == "woolworths" else "#email")
        selector_pass = ("#password" if store == "woolworths" else "#password")
        page = driver.page(store)
        if page.locator(selector_user).count() == 0:
            return False
        page.fill(selector_user, user)
        page.fill(selector_pass, password)
        page.locator("button[type=submit]").first.click()
        return True
    except Exception:
        return False


def _export_session_cookies(driver, store: str) -> None:
    """Export per-store cookies + timestamp to session_state.json."""
    state = _read_json(SESSION_STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    try:
        cookies = driver.cookies(store)
    except Exception:
        cookies = []
    state.setdefault(store, {})
    state[store]["cookies"] = cookies
    state[store]["logged_in_at"] = _now_iso()
    _write_json_atomic(SESSION_STATE_PATH, state)


# ============================================================================
# Phase B (real): flush both queues via the captured add API
# ============================================================================
def _phase_b_flush(driver, summary: dict) -> None:
    """Flush both queues, grouped by store, into "Price Compare" only."""
    entries = _load_both_queues()
    grouped = _group_by_store(entries)
    history = _load_attempt_history(FLUSH_LOG_PATH)
    capture = _read_json(CAPTURE_PATH, {})
    for store in STORES:
        store_entries = grouped.get(store, [])
        if not store_entries:
            summary[store]["flush"] = {"added": [], "failed": [],
                                       "parked": [], "session_died": False}
            continue
        to_flush, parked = _partition_parked(store, store_entries, history)
        for entry in parked:
            _append_flush_log(FLUSH_LOG_PATH, {
                "store": store,
                "keyword": str(entry.get("keyword", "") or
                               entry.get("generic_name", "")),
                "code": entry.get("code", ""),
                "status": "parked",
                "reason": f"needs manual attention after "
                          f"{PARK_AFTER_ATTEMPTS} attempts",
                "attempts": 0,
                "ts": _now_iso(),
            })
        if not to_flush:
            summary[store]["flush"] = {"added": [], "failed": [],
                                       "parked": parked,
                                       "session_died": False}
            continue
        if summary[store].get("login") is not True:
            # Cannot add via a logged-out page — keep everything queued.
            summary[store]["flush"] = {
                "added": [], "failed": to_flush, "parked": parked,
                "session_died": False,
                "reason": "not logged in — nothing attempted"}
            continue
        # D26: per-store isolation — a missing capture (or any per-store
        # failure) fails ONLY this store's flush; the other proceeds.
        try:
            add_item = _make_add_item(store, driver, capture)
            result = _flush_store(
                store, to_flush,
                add_item=add_item,
                consume_entry=_consume_queue_entry,
                log_append=lambda rec: _append_flush_log(FLUSH_LOG_PATH, rec),
                sleep=time.sleep, clock=time.monotonic,
                jitter=lambda: random.uniform(0, FLUSH_JITTER_S))
            result["parked"] = parked
            summary[store]["flush"] = result
        except RuntimeError as exc:
            summary[store]["flush"] = {
                "added": [], "failed": to_flush, "parked": parked,
                "session_died": False,
                "reason": "no API capture — run live-refresh --recapture",
            }
            print(f"[session_refresh] flush skipped for {store}: {exc}",
                  file=sys.stderr)
        except Exception as exc:
            summary[store]["flush"] = {
                "added": [], "failed": to_flush, "parked": parked,
                "session_died": False, "reason": str(exc),
            }
            print(f"[session_refresh] flush failed for {store}: {exc}",
                  file=sys.stderr)


def _make_add_item(store: str, driver, capture: dict):
    """Build the add_item callable using the captured add-to-list API.

    Raises:
        RuntimeError: when no valid capture exists — discovery must run
        first (the store is never guessed at).
    """
    entry_capture = (capture.get(store) or {})
    if not entry_capture.get("url"):
        raise RuntimeError(
            f"No API capture for {store} — run `live-refresh "
            f"--recapture` and add ONE item to your Price Compare list "
            f"in the open window.")
    method = str(entry_capture.get("method", "POST")).upper()
    url = str(entry_capture["url"])
    body_shape = entry_capture.get("body_shape", {})

    def add_item(entry) -> dict:
        keyword = str(entry.get("keyword", "") or
                      entry.get("generic_name", ""))
        body = dict(body_shape)
        body["name"] = keyword
        body["productId"] = entry.get("store_product_id", "")
        expression = (
            "async ([method, url, body]) => { try { const r = await "
            "fetch(url, {method: method, headers: {'Content-Type': "
            "'application/json'}, body: JSON.stringify(body)});"
            " if (r.status === 401 || r.status === 403) return "
            "{status: 'failed', kind: 'session_death', reason: 'HTTP ' "
            "+ r.status}; if (!r.ok) return {status: 'failed', kind: "
            "'permanent', reason: 'HTTP ' + r.status}; return "
            "{status: 'added', kind: 'ok', reason: ''}; } catch (e) "
            "{ return {status: 'failed', kind: 'transient', reason: "
            "String(e)}; } }")
        result = driver.evaluate(store, expression,
                                 [method, url, body])
        if not isinstance(result, dict):
            return {"status": "failed", "kind": "transient",
                    "reason": "empty add response"}
        return result

    return add_item


# ============================================================================
# Phase C (real): enumerate lists + walk pages + write snapshots
# ============================================================================
def _phase_c_fetch(driver, summary: dict) -> None:
    """Fetch every targeted list (all pages) and write snapshots."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    capture = _read_json(CAPTURE_PATH, {})
    for store, slug in (("woolworths", "ww"), ("coles", "coles")):
        try:
            available = _fetch_list_names(driver, store, capture)
            targets = _match_list_names(available, STORE_LIST_NAMES[store])
            merged: dict = {}
            for list_name in targets:
                outcome = _walk_pagination(
                    lambda page, ln=list_name: _fetch_list_page(
                        driver, store, capture, ln, page),
                    page_size=DEFAULT_PAGE_SIZE,
                    store_label=f"{'WW' if store == 'woolworths' else 'Coles'}"
                                f" '{list_name}'")
                if outcome["capped"]:
                    summary[store]["fetch"] = {
                        "ok": False,
                        "reason": outcome["warning"]}
                for item in outcome["items"]:
                    key = json.dumps(item.get(
                        "Stockcode",
                        item.get("id", item.get("name", ""))), default=str)
                    merged[key] = item
                snapshot_items = list(merged.values())
                snapshot = SNAPSHOTS_DIR / (
                    f"{date_str}_{slug}_"
                    f"{re.sub(r'[^a-z0-9]', '', list_name.lower())}.json")
                _write_json_atomic(snapshot, snapshot_items)
            if store not in summary or summary[store].get("fetch") is None:
                summary[store]["fetch"] = {"ok": True}
        except Exception as exc:
            summary[store]["fetch"] = {"ok": False, "reason": str(exc)}


def _fetch_list_names(driver, store: str, capture: dict) -> list:
    """Enumerate the store's saved-list names (1 attempt, §5.1)."""
    if store == "woolworths":
        result = driver.evaluate(
            "woolworths",
            "async () => { const r = await fetch('/apis/ui/mylists');"
            " return await r.json(); }")
        names = []
        for entry in result or []:
            if isinstance(entry, dict) and entry.get("Name"):
                names.append(str(entry["Name"]))
        return names
    check = (capture.get("coles", {}) or {}).get("lists_url", "")
    expression = (
        "async ([url]) => { const r = await fetch(url);"
        " return await r.json(); }")
    result = driver.evaluate("coles", expression, [check])
    names = []
    for entry in result or []:
        if isinstance(entry, dict) and entry.get("name"):
            names.append(str(entry["name"]))
    return names


def _fetch_list_page(driver, store: str, capture: dict, list_name: str,
                     page: int):
    """One page of one list (1 attempt per page, pages in order)."""
    if store == "woolworths":
        expression = (
            "async ([listName, page]) => { const lists = await (await "
            "fetch('/apis/ui/mylists')).json(); const list = lists.find("
            "l => l.Name === listName); if (!list) return null;"
            " const r = await fetch(`/apis/ui/mylists/items?listId=${"
            "list.Id}&page=${page}`); if (!r.ok) return null;"
            " const data = await r.json(); const items = data.Items ||"
            " data.items || data || []; const hasMore = typeof data."
            "HasMore === 'boolean' ? data.HasMore : null; return "
            "{items: items, has_more: hasMore}; }")
        return driver.evaluate("woolworths", expression, [list_name, page])
    pagination = (capture.get("coles", {}) or {}).get("pagination", {}) or {}
    lists_url = str((capture.get("coles", {}) or {}).get("lists_url", ""))
    expression = (
        "async ([listsUrl, listName, page, pageParam]) => { const r = "
        "await fetch(listsUrl); const lists = await r.json(); const "
        "list = (Array.isArray(lists) ? lists : []).find(l => l.name "
        "=== listName); if (!list) return null; const url = (list.url "
        "|| listsUrl) + (pageParam ? ((list.url || listsUrl).includes("
        "'?') ? '&' : '?') + pageParam + '=' + page : ''); const r2 = "
        "await fetch(url); if (!r2.ok) return null; const data = await "
        "r2.json(); const items = data.items || data.products || [];"
        " const hasMore = typeof data.hasMore === 'boolean' ? data."
        "hasMore : null; return {items: items, has_more: hasMore}; }")
    return driver.evaluate(
        "coles", expression,
        [lists_url, list_name, page,
         str(pagination.get("page_param", "page"))])


# ============================================================================
# run(): Phase A -> B -> C
# ============================================================================
def run(flush: bool = True, fetch: bool = True, recapture: bool = False,
        *, _driver=None, real_profile: bool = False) -> dict:
    """Run the live window phases; each phase is independently
    fault-tolerant (W-15) and skippable (W-16).

    Args:
        flush (bool): run Phase B (queue flush).
        fetch (bool): run Phase C (list fetch + snapshots).
        recapture (bool): force API discovery even when a capture exists.
        _driver: injected driver (tests); a real one is launched when
        None.
        real_profile (bool): seed the dedicated profile with the user's
        daily-Chrome logins before launching (--real-profile; requires
        Chrome fully closed first).

    Returns:
        dict: {store: {"login": bool, "flush": dict | None,
        "fetch": dict | None}} for the CLI phase summary.
    """
    summary = {store: {"login": False, "flush": None, "fetch": None}
               for store in STORES}
    driver = None
    own_driver = _driver is None
    try:
        driver = (_driver if _driver is not None
                  else _open_browser(real_profile=real_profile))
        if own_driver:
            if hasattr(driver, "start"):
                driver.start()
        _phase_a_login(driver, summary)
    except Exception as exc:
        print(f"[session_refresh] login phase failed: {exc}",
              file=sys.stderr)
        if flush:
            for store in STORES:
                summary[store]["flush"] = {
                    "ok": False, "reason": f"login failed: {exc}"}
        if fetch:
            for store in STORES:
                summary[store]["fetch"] = {
                    "ok": False, "reason": f"login failed: {exc}"}
        if own_driver and driver is not None:
            _safe_close(driver)
        return summary

    # D26: auto-discovery — run when forced OR when any store lacks a
    # capture (a true FIRST run must prompt, not fail wholesale).
    if recapture or any(_needs_capture(s) for s in STORES):
        try:
            _run_discovery(driver, summary, force=recapture)
        except Exception as exc:
            print(f"[session_refresh] discovery failed: {exc}",
                  file=sys.stderr)

    if flush:
        try:
            _phase_b_flush(driver, summary)
        except Exception as exc:
            print(f"[session_refresh] flush phase failed: {exc}",
                  file=sys.stderr)
            for store in STORES:
                summary[store]["flush"] = {"ok": False, "reason": str(exc)}

    if fetch:
        try:
            _phase_c_fetch(driver, summary)
        except Exception as exc:
            print(f"[session_refresh] fetch phase failed: {exc}",
                  file=sys.stderr)
            for store in STORES:
                summary[store]["fetch"] = {"ok": False, "reason": str(exc)}

    if own_driver:
        _safe_close(driver)
    return summary


def _safe_close(driver) -> None:
    """Close the driver; absorb shutdown noise."""
    try:
        driver.close()
    except Exception:
        pass


def _run_discovery(driver, summary: dict, force: bool = False) -> None:
    """Guided API discovery (§4.5): once per store, user adds ONE item.

    The driver prints the prompt itself AFTER attaching the request
    listener (P4a). ``force`` re-trains even when a capture exists
    (--recapture, P4b).
    """
    for store in STORES:
        if not force and not _needs_capture(store):
            continue
        try:
            capture = driver.capture_add_to_list(store)
        except Exception as exc:
            capture = {"error": str(exc)}
        if isinstance(capture, dict) and capture.get("url"):
            _write_discovery_capture(store, capture)
            summary.setdefault("discovery", {})[store] = "captured"
        else:
            summary.setdefault("discovery", {})[store] = "failed"
