"""py3.11 syntax guard (run-2 fix list #7 — VPS sync blocker).

The VPS container runs Python 3.11.2, which rejects PEP 701 f-strings
(nested same-quote expressions — the `__import__('re').sub(r'^multi
buy\b', …)` line that shipped in core/v2_read.py and had to be
hot-patched on the container 2026-09-11 03:22). ast.parse with
feature_version=(3, 11) catches that class from any local Python, so
a container-breaking syntax can never ship again.
"""
from __future__ import annotations
import ast
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

ROOTS = [_PROJECT / "core", _PROJECT / "tools",
         _PROJECT / "grocery_price_cli.py"]


def _py_files():
    for root in ROOTS:
        if root.is_file():
            yield root
        elif root.is_dir():
            yield from sorted(root.glob("*.py"))


class TestPy311Safe(unittest.TestCase):

    def test_all_runtime_files_parse_as_py311(self):
        bad = []
        for path in _py_files():
            src = path.read_text(encoding="utf-8")
            try:
                ast.parse(src, filename=str(path),
                          feature_version=(3, 11))
            except SyntaxError as exc:
                bad.append(f"{path.name}: {exc}")
        self.assertEqual(bad, [],
                         "py3.11-unsafe syntax (breaks the VPS "
                         "container):\n" + "\n".join(bad))

    def test_v2_read_still_parses_clean(self):
        # the file that shipped the blocker — pinned explicitly
        src = (_PROJECT / "core" / "v2_read.py").read_text(
            encoding="utf-8")
        ast.parse(src, feature_version=(3, 11))


if __name__ == "__main__":
    unittest.main()
