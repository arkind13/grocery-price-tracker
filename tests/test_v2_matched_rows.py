"""Run-2 fix-list regressions (2026-09-11 fix session).

Every test pins a defect the run-2 verification recorded:
- lamb-necks vocabulary-path header flip [YCQ] -> [YTB] after the
  butchery sort (header code must come from the MATCHED row);
- D3 cousin codes (AQZ->SNA, AUG->EPJ, GJZ->XJA);
- D2 'price of …' / exact WW-name full-sheet dump under a false
  header;
- the D1 real remainder: plural / singular / noun-first realistic
  forms (produce + halal-prefixed meat);
- the D1 DESIGN half (user ruling 2026-09-11): bare protein queries
  answer Woolworths-scope and an unfiltered pool never claims a
  false missing-list code.
Offline (parsed-row dicts; no network, no writes).
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core.v2_read import (                    # noqa: E402
    lookup_item, parse_ld_row, parse_master_row, render_lookup,
)

MASTER_HEADER = ["Product_Name", "Category", "Size",
                 "Woolworths_Price", "Brand_Type", "Last_Updated",
                 "Search_Keyword_Woolworths", "Woolworths_Specials",
                 "Rewards_Points", "Keywords", "Sub_Category",
                 "Item_Code", "Preferred"]


def _m(name, code, ww="", sub="", alias=""):
    row = [""] * 13
    row[0], row[3], row[10], row[11] = name, ww, sub, code
    row[9] = alias
    return parse_master_row(2, row)


def _l(name, code, dunya="", merjan=""):
    row = [""] * 11
    row[0], row[1], row[3], row[10] = name, dunya, merjan, code
    return parse_ld_row(3, row, today=None)


def sheet():
    """Mirror of the run-2 sheet identities around the defects."""
    master = [
        _m("Halal Lamb Neck Fillet (BBQ)", "YTB",
           sub="lamb & mutton"),
        _m("Halal Sliced Lamb Neck", "YCQ", sub="lamb & mutton"),
        _m("Halal Beef Mince", "AUG"),
        _m("Halal BEEF MINCE (5KG)", "EPJ"),
        _m("Woolworths Beef Mince 500g", "GJZ", ww="15"),
        _m("Halal Chicken Thighs", "AQZ"),
        _m("Halal Chicken Thigh – (5kg)", "SNA"),
        _m("Halal Goat Curry – (5kg)", "PTU"),
        _m("Halal Drumstick", "VCK"),
        _m("Cauliflower", "CAU", sub="cucumber"),
        _m("Chokos", "CHK", sub="potatoes"),
        _m("Mango R2E2", "MGO", sub="apples"),
        _m("Pink Lady Apples", "PLA", sub="apples"),
        _m("Granny Smith Apples", "GSA", sub="apples"),
        _m("Halal Lamb Breast", "LBR", sub="lamb & mutton"),
    ]
    ld = [
        _l("Halal Lamb Neck Fillet (BBQ)", "YTB", dunya="29.99"),
        _l("Halal Sliced Lamb Neck", "YCQ", merjan="15"),
        _l("Halal Beef Mince", "AUG", dunya="15.99"),
        _l("Halal BEEF MINCE (5KG)", "EPJ", dunya="64.99"),
        _l("Halal Chicken Thighs", "AQZ", dunya="14.99"),
        _l("Halal Chicken Thigh – (5kg)", "SNA", dunya="54.99"),
        _l("Halal Goat Curry – (5kg)", "PTU", merjan="15",
           dunya="89.99"),
        _l("Halal Drumstick", "VCK", merjan="4"),
        _l("Cauliflower", "CAU", dunya="3.99"),
        _l("Chokos", "CHK", dunya="2.99"),
        _l("Halal Lamb Breast", "LBR", dunya="12.99"),
    ]
    return master, ld


class TestMatchedRowCitation(unittest.TestCase):
    """The header code comes from the MATCHED row, never sheet order."""

    def setUp(self):
        self.master, self.ld = sheet()

    def reply(self, q):
        return render_lookup(lookup_item(q, self.master, self.ld))

    def code(self, q):
        return lookup_item(q, self.master, self.ld).get("code", "")

    def test_lamb_necks_cites_sliced_neck_not_fillet(self):
        # run-2 regression: post-sort sheet order put [YTB] first
        self.assertEqual(self.code("lamb necks"), "YCQ")
        r = self.reply("lamb necks")
        self.assertIn("[YCQ]", r)
        self.assertNotIn("[YTB]", r)
        # pooled cluster content survives (both LD rows quoted)
        self.assertIn("Merjan", r)
        self.assertIn("Dunya", r)

    def test_beef_mince_cites_perkg_row_not_pack_cousin(self):
        # run-2 D3: 'Beef Mince' / 'Mince Halal Beef' cited [EPJ]
        for q in ("beef mince", "Mince Halal Beef", "Halal beef mince"):
            self.assertEqual(self.code(q), "AUG", q)
        r = self.reply("beef mince")
        self.assertIn("[AUG]", r)
        # pooled quotes from BOTH beef mince LD rows survive
        self.assertIn("15.99", r)
        self.assertIn("64.99", r)
        # the non-halal twin line (standing §3.3 check) stays
        self.assertIn("also at Woolworths (non-halal)", r)
        self.assertIn("Woolworths Beef Mince 500g", r)

    def test_chicken_thigh_drift_forms_cite_aqz_not_sna(self):
        # run-2 D3: all three cited the 5kg pack cousin [SNA]
        for q in ("Halal Chicken Thigh", "Thighs Halal Chicken",
                  "Chicken Thighs"):
            self.assertEqual(self.code(q), "AQZ", q)
            self.assertIn("[AQZ]", self.reply(q))

    def test_goat_curry_still_ptu_both_presentations(self):
        for q in ("goat curry", "price of goat curry",
                  "Goat Curry"):
            self.assertEqual(self.code(q), "PTU", q)
        r = self.reply("goat curry")
        self.assertIn("Merjan", r)          # /kg special presentation
        self.assertIn("89.99", r)           # 5kg pack presentation


class TestWWRowNamed(unittest.TestCase):
    """§8 row 1: a query naming the Woolworths product itself answers
    that row's tracked class (run-2 D2: GJZ's answer was never shown;
    the query dumped the locals pool under a false header)."""

    def setUp(self):
        self.master, self.ld = sheet()

    def reply(self, q):
        return render_lookup(lookup_item(q, self.master, self.ld))

    def test_exact_ww_name_is_tracked_gjz(self):
        r = self.reply("Woolworths Beef Mince 500g")
        self.assertIn("[GJZ]", r)
        self.assertIn("Woolworths", r)       # tracked price section
        # the answering row must never twin itself
        self.assertNotIn("also at Woolworths (non-halal)", r)

    def test_drift_forms_still_gjz(self):
        for q in ("500g Woolworths Beef Mince",
                  "Woolworths Beef Minces 500g",
                  "price of Woolworths Beef Mince 500g"):
            res = lookup_item(q, self.master, self.ld)
            self.assertEqual(res["status"], "tracked", q)
            self.assertEqual(res["code"], "GJZ", q)

    def test_halal_prefixed_brand_query_shows_twin(self):
        # 'halal Woolworths Beef Mince 500g' — nonsense on a plain
        # row, so the halal cluster answer (with the non-halal twin
        # line) is the honest §8 output, never a false-code dump
        r = self.reply("halal Woolworths Beef Mince 500g")
        self.assertIn("also at Woolworths (non-halal)", r)
        self.assertNotIn("[GJZ]", r)


class TestNLFillers(unittest.TestCase):
    """run-2 D2: 'price of …' filler tokens matched no row name, so
    the query dumped the unfiltered pool under a false header."""

    def setUp(self):
        self.master, self.ld = sheet()

    def test_price_of_equals_bare_query(self):
        bare = render_lookup(lookup_item("goat curry", self.master,
                                         self.ld))
        nl = render_lookup(lookup_item("price of goat curry",
                                       self.master, self.ld))
        self.assertEqual(bare, nl)

    def test_how_much_is_stripped(self):
        r = render_lookup(lookup_item("how much is halal goat curry",
                                      self.master, self.ld))
        self.assertIn("[PTU]", r)


class TestRealisticForms(unittest.TestCase):
    """D1 real remainder: plural / singular / noun-first forms."""

    def setUp(self):
        self.master, self.ld = sheet()

    def code(self, q):
        return lookup_item(q, self.master, self.ld).get("code", "")

    def test_produce_plural(self):
        self.assertEqual(self.code("Cauliflowers"), "CAU")

    def test_produce_singular_on_plural_name(self):
        self.assertEqual(self.code("Choko"), "CHK")

    def test_noun_first_shuffles(self):
        self.assertEqual(self.code("R2E2 Mango"), "MGO")

    def test_produce_plural_vs_tracked_row(self):
        res = lookup_item("Tomatos", [_m("Tomatoes", "TOM",
                                         ww="0.54", sub="tomato")],
                          [])
        self.assertEqual(res["status"], "tracked")
        self.assertEqual(res["code"], "TOM")

    def test_halal_plural_pack_row(self):
        self.assertEqual(self.code("Halal Drumsticks"), "VCK")

    def test_generic_single_word_stays_unanswered(self):
        # two apple candidates — a bare 'apples' must not guess
        res = lookup_item("apples", self.master, self.ld)
        self.assertEqual(res["status"], "not-tracked")
        self.assertEqual(res["code"], "")

    def test_single_token_strict_winner_answers(self):
        # 'halal drumsticks' folds to one token with two candidates:
        # the /kg row (diff 1) strictly beats the 5kg pack (diff 2)
        # -> answer the /kg row, never guess, never stay bare
        master = [
            _m("Halal Drumstick", "VCK"),
            _m("Halal Drumsticks – (5kg)", "RPG"),
        ]
        ld = [_l("Halal Drumstick", "VCK", merjan="4")]
        res = lookup_item("halal drumsticks", master, ld)
        self.assertEqual(res["code"], "VCK")
        self.assertEqual(res["status"], "missing")


class TestUnfilteredPoolHonesty(unittest.TestCase):
    """run-2 D2 half-b: the last-resort pool (2026-09-10 user fix: a
    meat term never answers empty) answers WITHOUT a code — never a
    false 'missing list [XJA]' header on a full-sheet dump."""

    def setUp(self):
        # NO lamb-shoulder LD row: the query can match nothing
        self.master = [
            _m("Halal Beef Mince", "AUG"),
            _m("Halal Sausages", "HSG"),
            _m("Halal Lamb Shoulder", "HLS"),
        ]
        self.ld = [
            _l("Halal Beef Mince", "AUG", dunya="15.99"),
            _l("Halal Sausages", "HSG", dunya="9.99"),
        ]

    def test_pool_answers_without_false_code(self):
        res = lookup_item("halal lamb ribs", self.master, self.ld)
        self.assertEqual(res["status"], "meat-local-only")
        self.assertEqual(res["code"], "")
        r = render_lookup(res)
        self.assertIn("Not tracked at Woolworths", r)
        self.assertNotIn("missing list [", r)
        # never-empty rule (2026-09-10): locals still shown
        self.assertIn("Dunya", r)


if __name__ == "__main__":
    unittest.main()
