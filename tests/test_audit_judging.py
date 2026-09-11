"""Audit-tool judging regressions (2026-09-11 fix session).

Covers the pure helpers the CHECK phase relies on:
- judge_matrix: FINDING probes recorded, no-halal-prefix D1 design
  ruling, twin-or-code, code-presence;
- _toggle_plural: realistic plural probes (no '(5kg)s' artifacts);
- sweep judge(): missing-list demand only for missing-class rows,
  twin self-exclusion, brand/size tokens never drive twin matching.
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from tools.item_audit import (                # noqa: E402
    _toggle_plural, judge, judge_matrix,
)
from core.v2_read import parse_master_row     # noqa: E402


def _m(name, code, ww="", sub=""):
    row = [""] * 13
    row[0], row[3], row[10], row[11] = name, ww, sub, code
    return parse_master_row(2, row)


class TestJudgeMatrix(unittest.TestCase):

    def test_finding_probes_are_recorded_never_fail(self):
        self.assertEqual(
            judge_matrix("code-as-query",
                         "FINDING-B: codes are not lookup keys in v2 "
                         "— record actual", "XJA", 0, "Not tracked"),
            "RECORDED")

    def test_standard_code_presence(self):
        self.assertEqual(judge_matrix("exact", "XJA", "XJA", 0,
                                      "missing list [XJA]"), "PASS")
        self.assertEqual(judge_matrix("exact", "XJA", "XJA", 0,
                                      "missing list [SNA]"),
                         "FAIL wrong-or-missing code")
        self.assertEqual(judge_matrix("drift-plural", "XJA", "XJA",
                                      0, ""), "FAIL empty reply")
        self.assertTrue(
            judge_matrix("exact", "XJA", "XJA", 1, "whatever")
            .startswith("FAIL rc="))

    def test_no_halal_prefix_design_ruling(self):
        # user ruling 2026-09-11: bare protein queries answer
        # Woolworths-scope by design — the row's own code passes and
        # an honest bare 'Not tracked' passes, but a WRONG row's code
        # still fails (cousin-code protection stays)
        self.assertEqual(judge_matrix("no-halal-prefix", "", "VCK",
                                      0, "Not tracked"),
                         "PASS")
        self.assertEqual(judge_matrix("no-halal-prefix", "", "VCK",
                                      0, "missing list [VCK]"),
                         "PASS")
        self.assertTrue(
            judge_matrix("no-halal-prefix", "", "VCK", 0,
                         "missing list [SNA]").startswith("FAIL"))
        self.assertTrue(
            judge_matrix("no-halal-prefix", "", "VCK", 0,
                         "🔥 butcher $9/kg").startswith("FAIL"))

    def test_twin_or_code(self):
        self.assertEqual(judge_matrix("with-halal-prefix",
                                      "twin-or-code", "GJZ", 0,
                                      "missing list [AUG] — also at "
                                      "Woolworths (non-halal)"),
                         "PASS")
        self.assertEqual(judge_matrix("with-halal-prefix",
                                      "twin-or-code", "GJZ", 0,
                                      "missing list [AUG]"),
                         "FAIL twin-or-code")


class TestTogglePlural(unittest.TestCase):

    def test_pack_size_never_toggled(self):
        self.assertEqual(
            _toggle_plural("Halal Chicken Thigh – (5kg)"),
            "Halal Chicken Thighs – (5kg)")
        self.assertEqual(
            _toggle_plural("Halal Lamb Mince – (5kg)"),
            "Halal Lamb Minces – (5kg)")

    def test_size_token_never_toggled(self):
        self.assertEqual(_toggle_plural("Woolworths Beef Mince 500g"),
                         "Woolworths Beef Minces 500g")

    def test_singular_direction(self):
        self.assertEqual(_toggle_plural("Cos Lettuces"),
                         "Cos Lettuce")

    def test_code_ish_tokens_skipped(self):
        self.assertEqual(_toggle_plural("Mango R2E2"),
                         "Mangos R2E2")


class TestSweepJudge(unittest.TestCase):

    MASTER = [
        _m("Halal Beef Mince", "AUG"),
        _m("Woolworths Beef Mince 500g", "GJZ", ww="15"),
        _m("Halal Lamb Mince – (5kg)", "WHA"),
    ]

    def test_tracked_row_needs_no_missing_list_line(self):
        # old condition was inverted and demanded a missing-list line
        # on tracked answers
        r = "Woolworths Beef Mince 500g\n  Woolworths $13.54"
        self.assertEqual(
            judge("Woolworths Beef Mince 500g", "tracked", "tracked",
                  r, self.MASTER, item_code="GJZ"),
            "PASS")

    def test_missing_row_demands_missing_list_and_twin(self):
        # A4 on a halal missing-class row: both the missing-list line
        # AND the non-halal twin line are required content
        both = ("Halal Beef Mince\n  not tracked at Woolworths — "
                "missing list [AUG]\n  also at Woolworths (non-halal)"
                ": $13.54 — Woolworths Beef Mince 500g")
        self.assertEqual(
            judge("Halal Beef Mince", "missing", "missing", both,
                  self.MASTER, item_code="AUG"),
            "PASS")
        no_list = both.replace("missing list [AUG]", "")
        self.assertTrue(judge("Halal Beef Mince", "missing", "missing",
                              no_list, self.MASTER,
                              item_code="AUG").startswith("FAIL"))
        no_twin = both.replace("also at Woolworths (non-halal)"
                               ": $13.54 — Woolworths Beef Mince 500g",
                               "")
        self.assertTrue(judge("Halal Beef Mince", "missing", "missing",
                              no_twin, self.MASTER,
                              item_code="AUG").startswith("FAIL"))

    def test_row_is_not_its_own_twin(self):
        # GJZ's own tracked answer must not be demanded a twin line
        # through a shared brand token
        self.assertFalse(
            judge("Woolworths Beef Mince 500g", "tracked", "tracked",
                  "tracked reply without twin", self.MASTER,
                  item_code="GJZ") == "FAIL: twin line missing")


if __name__ == "__main__":
    unittest.main()
