"""Session-wide state-file isolation — R2-8 (R13).

A full pytest run used to pollute the REAL data/ state files
(proven by the 2026-09-08 verification round): unmapped_queue.json
count/last_seen bumps, +10 local_deals_post_log entries, +8 burned
item codes, search_last_results rewrites. This autouse session
fixture points every state path at a throwaway directory for the
whole suite and asserts at teardown that the real files are
byte-identical to their pre-run state.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib
import sys
import tempfile
from pathlib import Path

import pytest

# Bootstrap both roots BEFORE any import: the CLI lives in the parent
# directory (repo layout: grocery_price_cli.py is the parent-repo
# file), and core/ lives in the tracker root. Test modules do this
# themselves; conftest runs first and must not rely on them.
_HERE = Path(__file__).resolve().parent          # tests/
_PROJECT = _HERE.parent                          # tracker root
_ROOT = _PROJECT.parent                          # parent ("AI related")
for _p in (str(_PROJECT), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# (module, attribute, tmp file name) for the proven leak paths.
_STATE_ATTRS = [
    ("core.name_matcher", "QUEUE_PATH", "unmapped_queue.json"),
    ("core.local_deals", "POST_LOG_PATH", "local_deals_post_log.json"),
    ("core.item_codes", "REGISTRY_PATH", "item_code_registry.json"),
    # R3-2 (R19): the R2-4 reason helper reads the breaker state
    # through this path — without isolation the suite's PASS/FAIL
    # depended on the user's REAL scrapedo_health.json (a genuine
    # fail_streak flipped 2 tests red with zero code regressions).
    ("extractors.coles_extractor", "SCRAPEDO_HEALTH_PATH",
     "scrapedo_health.json"),
]


def _digest(path: Path):
    """sha256 of a file's bytes, or None when absent."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


@pytest.fixture(autouse=True, scope="session")
def isolate_state_files():
    """Redirect state writes to a temp dir; verify the real files
    were untouched when the suite ends."""
    from unittest.mock import patch

    tmp = Path(tempfile.mkdtemp(prefix="gpt_state_iso_"))
    before: dict[str, str | None] = {}

    with contextlib.ExitStack() as stack:
        for mod_name, attr, fname in _STATE_ATTRS:
            mod = importlib.import_module(mod_name)
            real = Path(getattr(mod, attr))
            before[str(real)] = _digest(real)
            stack.enter_context(patch.object(mod, attr, tmp / fname))

        yield

    # Teardown: the real state files must be byte-identical (or still
    # absent) — a suite that leaked state fails HERE, at the source.
    for path_str, digest in before.items():
        assert _digest(Path(path_str)) == digest, (
            f"REAL state file mutated by the test suite: {path_str} "
            "(R2-8/R13 isolation broken — a test bypassed the "
            "conftest patches)")
