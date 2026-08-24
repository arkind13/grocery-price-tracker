"""Phase 9.0.a — Env probe: assert all 10 env vars are non-empty.

Never prints secret values. Exits non-zero if any var is missing/empty.
Mirrors sheets_client._find_root_env + _load_env for consistency.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Required env vars (from TASK_3.5.8_GROCERY_TRACKER_PLAN.md Phase 9.0)
# ---------------------------------------------------------------------------
REQUIRED_VARS = [
    "GROCERY_SERVICE_ACCOUNT_JSON",
    "GROCERY_SPREADSHEET_ID",
    "WOOLWORTHS_COOKIE",
    "WOOLWORTHS_USER",
    "WOOLWORTHS_PASS",
    "COLES_COOKIE",
    "COLES_USER",
    "COLES_PASS",
    "SCRAPEDO_API_KEY",
    "COLES_API_KEY",
]


def _find_root_env() -> Path:
    """Walk up from this file (core/) to find the workspace .env. Max 6 levels."""
    start = Path(__file__).resolve().parent  # core/
    for _ in range(6):
        candidate = start / ".env"
        if candidate.is_file():
            return candidate
        start = start.parent
    raise FileNotFoundError(
        "Could not find root .env file. "
        "Searched upward from: " + str(Path(__file__).resolve().parent)
    )


def _load_env() -> None:
    """Load .env via python-dotenv if available, else manual KEY=VALUE parse."""
    env_path = _find_root_env()
    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=str(env_path), override=True)
    except ImportError:
        with open(env_path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("\"'")
                os.environ[key] = val


def probe() -> dict[str, bool]:
    """Return {var_name: is_set} for all REQUIRED_VARS. Prints summary."""
    _load_env()
    results: dict[str, bool] = {}
    for var in REQUIRED_VARS:
        results[var] = bool(os.getenv(var))
    return results


def main() -> int:
    """Run the probe and exit 0 if all 10 are set, 1 otherwise."""
    results = probe()
    passed = sum(1 for v in results.values() if v)
    total = len(results)

    print(f"=== ENV PROBE: {passed}/{total} ===")
    for var, is_set in results.items():
        status = "TRUE " if is_set else "FALSE"
        print(f"  [{status}] {var}")

    if passed == total:
        print(f"\nSUCCESS: All {total} env vars are set.")
        return 0
    else:
        missing = [k for k, v in results.items() if not v]
        print(
            f"\nFAILURE: {total - passed} env var(s) missing/empty: "
            f"{', '.join(missing)}"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
