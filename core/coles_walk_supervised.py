"""Coles walk SUPERVISOR (user ask 2026-10-28: "have a mechanism in place to
make sure if a freeze like this happens it is... restarted — I cant keep
checking every hour").

Runs the walker in a loop and watches the shared log's freshness. The walker
logs a line for EVERY aisle (and 20s-wait notes during challenge auto-waits),
so a quiet log means a frozen browser — the class that hung today for 2.5h
(browser death => Playwright sync client blocks forever; the walker's own
timeouts can never fire). On silence > STALE_MIN minutes: kill the walker
tree (python + chromium), restart it — the same-day resume (state.json)
continues exactly where it died. Exits when the walker completes (upload
done), or after MAX_RESTARTS freezes.

Usage: python core/coles_walk_supervised.py [--polite-ms 4500]
Log: data/coles-catalogue/supervisor.log
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

TRACKER = Path(__file__).resolve().parent.parent
DATA = TRACKER / "data" / "coles-catalogue"
WALK_LOG = DATA / "full-walk-local-weekly.log"
SUP_LOG = DATA / "supervisor.log"
STALE_MIN = 10          # no log line for this long = frozen (longest legit
                        # silence: a many-page aisle ~5 min, challenges ~5 min)
HEARTBEAT_MIN = 5       # supervisor notes liveness even when all is well
MAX_RESTARTS = 8        # then give up loudly — a death loop needs a human
PY = sys.executable


def log(msg: str) -> None:
    line = f"[supervisor {datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        with open(SUP_LOG, "a", encoding="utf8") as f:
            f.write(line + "\n")
    except Exception:
        pass


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--polite-ms", type=int, default=4500)
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    log(f"supervisor start — stale threshold {STALE_MIN} min, max restarts {MAX_RESTARTS}")
    restarts = 0
    while True:
        # remember the log size so completion of THIS invocation is detectable
        start_size = WALK_LOG.stat().st_size if WALK_LOG.exists() else 0
        log(f"starting walker (attempt {restarts + 1}, resume from aisle {aisles_done() + 1})")
        proc = subprocess.Popen(
            [PY, "-u", str(TRACKER / "core" / "coles_catalogue_walk.py"),
             "--polite-ms", str(args.polite_ms)],
            cwd=str(TRACKER),
            stdout=open(WALK_LOG, "a", encoding="utf8"),
            stderr=subprocess.STDOUT,
        )
        last_beat = time.time()
        frozen_at = None
        while True:
            time.sleep(30)
            if proc.poll() is not None:
                code = proc.returncode
                if walk_completed() and WALK_LOG.stat().st_size > start_size:
                    log(f"walker finished cleanly (exit {code}) — aisles {aisles_done()}. Done.")
                    return 0
                log(f"walker exited early (exit {code}) without WALK DONE — restarting")
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


if __name__ == "__main__":
    sys.exit(main())
