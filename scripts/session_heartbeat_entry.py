#!/usr/bin/env python3
"""Heartbeat entrypoint for the VPS cron / Windows schtasks (§4.6).

Thin wrapper around extractors.session_refresh.run_heartbeat so the
scheduler only needs a plain file path:

    python scripts/session_heartbeat_entry.py

Measurement ONLY: uses saved cookies (data/session_state.json), never
triggers a login, never touches any third-party scraper service, never
raises (failures land in data/session_heartbeat.log as "unknown").
Always exits 0 so the scheduler sees success regardless of state.
"""
from __future__ import annotations
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_TRACKER = _HERE.parent
if str(_TRACKER) not in sys.path:
    sys.path.insert(0, str(_TRACKER))

from extractors.session_refresh import run_heartbeat  # noqa: E402


def main() -> int:
    """Run one heartbeat probe per store; ALWAYS exit 0 (D-5)."""
    try:
        results = run_heartbeat()
    except Exception:
        results = {}
    for store in ("woolworths", "coles"):
        print(f"{store}: {results.get(store, 'unknown')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
