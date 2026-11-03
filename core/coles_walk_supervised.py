"""Coles walk SUPERVISOR (user ask 2026-10-28: "have a mechanism in place to
make sure if a freeze like this happens it is... restarted — I cant keep
checking every hour"; 2026-11-04 cookie protocol: "if it fails 2 times send
me a message on telegram saying coles failed fresh cookie from my browser
required to run - once i open coles site i reply coles on telegram and then
you can fetch fresh cookie from my open session and restart the run").

Runs the walker in a loop and watches the shared log's freshness. The walker
logs a line for EVERY aisle (and 20s-wait notes during challenge auto-waits),
so a quiet log means a frozen browser — the class that hung today for 2.5h
(browser death => Playwright sync client blocks forever; the walker's own
timeouts can never fire). On silence > STALE_MIN minutes: kill the walker
tree (python + chromium), restart it — the same-day resume (state.json)
continues exactly where it died. Exits when the walker completes (upload
done), or after MAX_RESTARTS freezes.

2026-11-04 — TWO-FAIL COOKIE PROTOCOL (fixes the infinite restart loop of
2026-11-04: the walker was challenge-fatal on warm-up every ~2.5 min and
early exits never counted toward any limit, so the supervisor retried
forever and hammered Coles all morning):
  * walker exit code 3 = challenged on warm-up. TWO such strikes ->
    STOP retrying, send the user the Telegram message ("Coles failed -
    fresh cookie from my browser required to run"), then WAIT.
  * while waiting: poll core/coles_refresh_cookie.py --auto every 60s —
    the moment the user's own Chrome shows a coles.com.au visit newer than
    the message (they opened Coles, maybe replied "coles" to the claw —
    the agent path runs the same script directly), the borrow+verify fires,
    cookies.json lands, strikes reset, the walk restarts with the cookie.
    Re-nudge on Telegram every 2h so an overnight wait isn't forgotten.
  * any OTHER early exit counts toward MAX_EARLY_EXITS (consecutive
    no-progress exits) — never an infinite loop again.

Usage: python core/coles_walk_supervised.py [--polite-ms 4500]
Log: data/coles-catalogue/supervisor.log
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

TRACKER = Path(__file__).resolve().parent.parent
DATA = TRACKER / "data" / "coles-catalogue"
WALK_LOG = DATA / "full-walk-local-weekly.log"
SUP_LOG = DATA / "supervisor.log"
COOKIES = DATA / "cookies.json"
STALE_MIN = 10          # no log line for this long = frozen (longest legit
                        # silence: a many-page aisle ~5 min, challenges ~5 min)
HEARTBEAT_MIN = 5       # supervisor notes liveness even when all is well
MAX_RESTARTS = 8        # freezes — then give up loudly, a death loop needs a human
MAX_EARLY_EXITS = 8     # consecutive no-progress non-challenge early exits
CHALLENGE_STRIKES = 2   # challenge-fatal exits before the cookie protocol fires
NUDGE_H = 2             # re-send the Telegram ask every N hours while waiting
SYDNEY = timezone(timedelta(hours=11))
PY = sys.executable

FAIL_MSG = ("Coles failed - fresh cookie from my browser required to run.\n\n"
            "The Coles walk has been blocked by the site's robot check twice.\n"
            "Please:\n"
            "1. open coles.com.au in your Chrome\n"
            "2. reply: coles\n"
            "3. fully QUIT Chrome (all windows) so I can borrow the fresh "
            "cookie — you can reopen it right after")


def log(msg: str) -> None:
    line = f"[supervisor {datetime.now(SYDNEY).strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        with open(SUP_LOG, "a", encoding="utf8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def telegram(msg: str) -> None:
    """Send via the claw bot (sendMessage only — NEVER getUpdates: the claw
    gateway owns the polling side of that bot)."""
    try:
        import urllib.request
        bot, chat = os.getenv("TELEGRAM_CLAW_BOT", ""), os.getenv("TELEGRAM_CHAT_ID", "")
        if not bot or not chat:
            log("telegram not sent: TELEGRAM_CLAW_BOT/TELEGRAM_CHAT_ID missing "
                "(add to laptop/ww-upload.env)")
            return
        urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{bot}/sendMessage",
            data=json.dumps({"chat_id": chat, "text": msg}).encode(),
            headers={"Content-Type": "application/json"}), timeout=15)
    except Exception as exc:
        log(f"telegram send failed: {exc}")


def kill_tree(proc: subprocess.Popen) -> None:
    try:
        # /T takes the whole tree — chromium dies with the walker
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True, timeout=30)
    except Exception as exc:
        log(f"kill failed ({exc}) — trying python kill")
        try:
            proc.kill()
        except Exception:
            pass


def aisles_done() -> int:
    try:
        with open(WALK_LOG, "r", encoding="utf8", errors="ignore") as f:
            text = f.read()
        return text.count(" OK\n") + text.count("resumed-done")
    except FileNotFoundError:
        return 0


def walk_completed() -> bool:
    """The walker prints WALK DONE per invocation; today's completion is the
    LAST line saying DONE with an upload after the current supervisor start."""
    try:
        with open(WALK_LOG, "r", encoding="utf8", errors="ignore") as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        return bool(lines) and "WALK DONE" in lines[-1]
    except FileNotFoundError:
        return False


def await_fresh_cookie() -> bool:
    """The 2026-11-04 wait state: message sent, now poll for the user's
    Coles visit. Returns True when a verified fresh cookie is banked
    (cookies.json newer than the message). False only on impossible
    subprocess errors — waiting itself is unbounded (user may be asleep)."""
    since = datetime.now(SYDNEY)
    telegram(FAIL_MSG)
    log(f"CHALLENGED {CHALLENGE_STRIKES}x — stopped retrying; Telegram ask sent "
        f"{since.strftime('%H:%M')}; waiting for a fresh cookie")
    last_nudge, last_beat, last_cookies = time.time(), time.time(), 0.0
    while True:
        time.sleep(60)
        try:
            if COOKIES.exists():
                last_cookies = COOKIES.stat().st_mtime
        except OSError:
            pass
        if last_cookies > since.timestamp():
            log("fresh cookies.json banked — resuming the walk")
            return True
        # the user visited Coles but nobody ran the fetch yet (agent path
        # down / no session): do it ourselves — the script verifies too
        r = subprocess.run(
            [PY, "-u", str(TRACKER / "core" / "coles_refresh_cookie.py"),
             "--auto", "--since", since.isoformat(timespec="seconds")],
            cwd=str(TRACKER), capture_output=True, text=True, timeout=300)
        if r.returncode == 0:
            log(f"cookie fetch OK ({(r.stdout or '').strip().splitlines()[-1] if r.stdout.strip() else 'no output'}) — resuming the walk")
            telegram("Coles cookie fetched — restarting the walk 🛒")
            return True
        if r.returncode not in (10,):  # 10 = nothing to borrow yet (normal)
            log(f"cookie fetch failed (exit {r.returncode}): "
                f"{(r.stdout or r.stderr or '').strip()[:200]}")
        if time.time() - last_nudge > NUDGE_H * 3600:
            last_nudge = time.time()
            telegram(FAIL_MSG)
            log("re-nudged (still waiting for the Coles cookie)")
        if time.time() - last_beat > HEARTBEAT_MIN * 60:
            last_beat = time.time()
            log("still waiting for a fresh Coles cookie "
                f"(asked {datetime.now(SYDNEY) - since} ago)")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--polite-ms", type=int, default=4500)
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    log(f"supervisor start — stale {STALE_MIN} min, max restarts {MAX_RESTARTS}, "
        f"max early exits {MAX_EARLY_EXITS}, cookie protocol after "
        f"{CHALLENGE_STRIKES} challenge-fails")
    restarts = 0
    challenge_strikes = 0
    early_exits = 0
    while True:
        # remember the log size so completion of THIS invocation is detectable
        start_size = WALK_LOG.stat().st_size if WALK_LOG.exists() else 0
        start_aisles = aisles_done()
        log(f"starting walker (attempt {restarts + 1}, resume from aisle {start_aisles + 1}"
            + (f", borrowed cookies ON, {challenge_strikes} prior challenge-strike(s)"
               if challenge_strikes else "") + ")")
        proc = subprocess.Popen(
            [PY, "-u", str(TRACKER / "core" / "coles_catalogue_walk.py"),
             "--polite-ms", str(args.polite_ms)],
            cwd=str(TRACKER),
            stdout=open(WALK_LOG, "a", encoding="utf8"),
            stderr=subprocess.STDOUT,
        )
        last_beat = time.time()
        frozen_at = None
        restart_reason = None
        while True:
            time.sleep(30)
            if proc.poll() is not None:
                code = proc.returncode
                if walk_completed() and WALK_LOG.stat().st_size > start_size:
                    log(f"walker finished cleanly (exit {code}) — aisles {aisles_done()}. Done.")
                    return 0
                if code == 3:  # challenged on warm-up (the walker's contract)
                    challenge_strikes += 1
                    restart_reason = f"challenge-strike {challenge_strikes}/{CHALLENGE_STRIKES}"
                else:
                    early_exits += 1
                    restart_reason = f"early exit {code} ({early_exits}/{MAX_EARLY_EXITS})"
                log(f"walker exited early (exit {code}) — {restart_reason}")
                break
            # freshness: the walker appends a line per aisle (and per wait)
            try:
                age = time.time() - WALK_LOG.stat().st_mtime
            except FileNotFoundError:
                age = 0
            if age > STALE_MIN * 60:
                if frozen_at is None:
                    frozen_at = time.time()
                    log(f"FROZEN (log quiet {int(age / 60)} min) — killing walker tree, restarting")
                    kill_tree(proc)
                    restarts += 1
                    restart_reason = f"freeze {restarts}/{MAX_RESTARTS}"
                    if restarts >= MAX_RESTARTS:
                        log(f"GIVING UP after {restarts} freezes — needs a human. "
                            f"Aisles banked: {aisles_done()}")
                        return 1
                    time.sleep(10)  # let the tree die
                    break
            else:
                frozen_at = None
                if time.time() - last_beat > HEARTBEAT_MIN * 60:
                    last_beat = time.time()
                    log(f"ok — walker alive, aisles {aisles_done()}")
        # -- post-exit bookkeeping ------------------------------------------
        if challenge_strikes >= CHALLENGE_STRIKES:
            await_fresh_cookie()          # blocks until a verified cookie lands
            challenge_strikes = 0         # fresh borrow — clean slate
            early_exits = 0
            continue
        if early_exits >= MAX_EARLY_EXITS and aisles_done() == start_aisles:
            log(f"GIVING UP after {early_exits} no-progress early exits — needs a "
                f"human. Aisles banked: {aisles_done()}")
            telegram("Coles walk supervisor gave up — repeated early exits, no "
                     "progress. Needs a look.")
            return 1
        if aisles_done() > start_aisles:
            early_exits = 0  # progress was made — this isn't a death loop


if __name__ == "__main__":
    sys.exit(main())
