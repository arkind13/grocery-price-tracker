#!/usr/bin/env python3
"""Pre-flight trial checklist for the grocery tracker (D-3).

Run before the live trial (or any deploy) to verify the environment:

    python scripts/trial_check.py

Checks (each prints PASS/FAIL with detail):
    1. Python >= 3.10
    2. Required env vars present in the environment / mounted .env
       (values are NEVER printed)
    3. Import health: core.lookup, core.uom, core.searched_items,
       extractors.session_refresh (no playwright needed to import)
    4. CLI --help smoke test (argparse builds)
    5. Pure-unit sanity: uom.parse_size("25L"), searched_items import
       paths resolve
    6. Test suite smoke: pytest tests/test_uom.py -q (offline)

Exit codes: 0 = all PASS, 1 = at least one FAIL.
"""
from __future__ import annotations
import argparse
import importlib
import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_TRACKER = _HERE.parent
if str(_TRACKER) not in sys.path:
    sys.path.insert(0, str(_TRACKER))

_RESULTS: list[tuple[str, bool, str]] = []


def _record(name: str, ok: bool, detail: str = "") -> None:
    """Record + print one check result."""
    _RESULTS.append((name, ok, detail))
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)


def check_python() -> None:
    """1. Python version floor."""
    ok = sys.version_info >= (3, 10)
    _record("python >= 3.10", ok, sys.version.split()[0])


def check_env() -> None:
    """2. Required env vars present (never print values)."""
    required = [
        "GROCERY_SERVICE_ACCOUNT_JSON",
        "GROCERY_SPREADSHEET_ID",
        "SCRAPEDO_API_KEY",
    ]
    optional = [
        "WOOLWORTHS_COOKIE", "COLES_COOKIE",
        "WOOLWORTHS_USER", "WOOLWORTHS_PASS",
        "COLES_USER", "COLES_PASS",
    ]
    # Best-effort .env load so a locally-configured machine passes too.
    env_file = _TRACKER.parent / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8",
                                       errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())
    missing = [k for k in required if not os.environ.get(k)]
    _record("required env vars", not missing,
            "missing: " + ", ".join(missing) if missing else
            f"{len(required)} present")
    present_opt = [k for k in optional if os.environ.get(k)]
    _record("optional env vars (live window)", True,
            "present: " + (", ".join(present_opt) or "none") +
            " (live-refresh needs USER/PASS pairs)")


def check_imports() -> None:
    """3. Import health (playwright must NOT be required)."""
    for module in ("core.lookup", "core.uom", "core.searched_items",
                   "core.price_comparator", "extractors.live_list_fetch",
                   "extractors.session_refresh"):
        try:
            importlib.import_module(module)
            _record(f"import {module}", True)
        except Exception as exc:
            _record(f"import {module}", False, str(exc))


def check_cli() -> None:
    """4. CLI argparse smoke test."""
    cli = _TRACKER.parent / "grocery_price_cli.py"
    if not cli.is_file():
        _record("cli --help smoke", False, f"{cli} not found")
        return
    try:
        result = subprocess.run(
            [sys.executable, str(cli), "--help"],
            capture_output=True, text=True, timeout=60)
        ok = result.returncode == 0 and "searched-items" in result.stdout \
            and "live-refresh" in result.stdout
        _record("cli --help smoke", ok,
                "subcommands registered" if ok else result.stderr[:120])
    except Exception as exc:
        _record("cli --help smoke", False, str(exc))


def check_uom_sanity() -> None:
    """5. Pure-unit sanity: parse + compare a known pair."""
    try:
        from core.uom import Verdict, compare_sizes, parse_size
        a = parse_size("25L")
        b = parse_size("30L")
        ok = (a is not None and a.value == 25000.0
              and compare_sizes(a, b).verdict == Verdict.COMPARABLE_TOLERANT)
        _record("uom sanity (25L/30L)", ok)
    except Exception as exc:
        _record("uom sanity (25L/30L)", False, str(exc))


def check_tests_smoke() -> None:
    """6. Offline test smoke: the UOM suite must pass in seconds."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_uom.py", "-q"],
            capture_output=True, text=True, timeout=300,
            cwd=str(_TRACKER))
        passed = " passed" in result.stdout
        _record("pytest tests/test_uom.py", passed,
                result.stdout.strip().splitlines()[-1]
                if result.stdout.strip() else result.stderr[:120])
    except Exception as exc:
        _record("pytest tests/test_uom.py", False, str(exc))


# The three Wednesday list files compared by --compare-lists.
COMPARE_LIST_FILES = ("unmatched.txt", "wool_missing.txt",
                      "coles_missing.txt")


def compare_lists(dir_a: Path, dir_b: Path) -> list:
    """Compare the Wednesday list files between two directories.

    A mismatch is any missing file OR any difference in line content
    (order-sensitive) OR line count between the two sides.

    Args:
        dir_a (Path): first directory (e.g. local data/).
        dir_b (Path): second directory (e.g. pulled VPS copy).

    Returns:
        list[str]: human-readable mismatch lines (empty when identical).
    """
    mismatches = []
    for name in COMPARE_LIST_FILES:
        lines_a = _read_list_lines(Path(dir_a) / name)
        lines_b = _read_list_lines(Path(dir_b) / name)
        if lines_a is None or lines_b is None:
            missing_side = "A" if lines_a is None else "B"
            mismatches.append(
                f"{name}: missing in side {missing_side} "
                f"({dir_a if lines_a is None else dir_b})")
            continue
        if len(lines_a) != len(lines_b):
            mismatches.append(f"{name}: line count differs "
                              f"({len(lines_a)} vs {len(lines_b)})")
            continue
        for i, (la, lb) in enumerate(zip(lines_a, lines_b), 1):
            if la != lb:
                mismatches.append(f"{name}: line {i} differs: "
                                  f"{la!r} vs {lb!r}")
    return mismatches


def _read_list_lines(path: Path):
    """Read one list file's significant lines; None when missing."""
    if not Path(path).is_file():
        return None
    lines = []
    for line in Path(path).read_text(encoding="utf-8",
                                     errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def main() -> int:
    """Run every check; exit 0 only when all pass."""
    parser = argparse.ArgumentParser(
        description="Grocery tracker trial checklist")
    parser.add_argument(
        "--compare-lists", nargs=2, metavar=("DIR_A", "DIR_B"),
        help="Compare unmatched/wool_missing/coles_missing lists between "
             "two directories (e.g. local data/ vs a pulled VPS copy) "
             "instead of running the environment checks")
    args = parser.parse_args()

    if args.compare_lists:
        dir_a, dir_b = args.compare_lists
        mismatches = compare_lists(Path(dir_a), Path(dir_b))
        if mismatches:
            print("=== list comparison FAILED ===")
            for line in mismatches:
                print(f"[FAIL] {line}")
            return 1
        print("=== list comparison passed: lists identical ===")
        return 0

    print("=== Grocery tracker trial check ===")
    check_python()
    check_env()
    check_imports()
    check_cli()
    check_uom_sanity()
    check_tests_smoke()
    failures = [r for r in _RESULTS if not r[1]]
    print(f"=== {len(_RESULTS) - len(failures)}/{len(_RESULTS)} checks "
          f"passed ===")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
