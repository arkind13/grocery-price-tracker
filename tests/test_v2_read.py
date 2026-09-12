"""S8/S10.3 — minimal v2 read path: one test per §8 lookup row, §6
list-rule cases, and meat-query halal scoping. Offline (parsed-row
dicts; no network, no writes)."""
from __future__ import annotations
import copy
import inspect
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core.v2_read import (                         # noqa: E402
    _non_halal_twin, lookup_item, missing_list, parse_ld_row,
    parse_master_row, render_list, render_lookup,
)

MASTER_HEADER = ["Product_Name", "Category", "Size",
                 "Woolworths_Price", "Brand_Type", "Last_Updated",
                 "Search_Keyword_Woolworths", "Woolworths_Specials",
                 "Rewards_Points", "Keywords", "Sub_Category",
                 "Item_Code", "Preferred"]


def _m(name, code, ww="", keyword="", sub="", alias="", brand="",
       specials="", size=""):
    row = [""] * 13
    row[0], row[2], row[3], row[4], row[6], row[7], row[9], \
        row[10], row[11] = (
        name, size, ww, brand, keyword, specials, alias, sub, code)
    return parse_master_row(2, row)


def _l(name, code, **prices):
    """prices: shop_key -> (cell_value). Special-first parsing is
    tab_store_price's job — feed raw cells through parse_ld_row.
    13-col layout (Category col B added 2026-09-12): comments idx 11,
    Item_Code idx 12."""
    row = [""] * 13
    row[0] = name
    row[12] = code
    col = {"category": 1, "dunya_perm": 2, "dunya_sp": 3,
           "merjan_perm": 4, "merjan_sp": 5, "fruitopia_perm": 6,
           "fruitopia_sp": 7, "abusalim_perm": 8, "abusalim_sp": 9,
           "nazar_perm": 10}
    for key, value in prices.items():
        row[col[key]] = value
    return parse_ld_row(3, row, today=None)


class TestLookup(unittest.TestCase):
    """§8 search semantics table (sheet-only)."""

    def setUp(self):
        self.master = [
            _m("Halal Beef Mince 500g", "AUG", ww="$8.50",
               sub="butchery", brand="Home"),
            _m("Tomato", "EYF", ww="$0.54", keyword="woolworths tomato",
               sub="tomato"),
            _m("Halal Lamb Shoulder", "HLS", sub="butchery"),
            _m("Greek Salad Kit", "GS1", sub="greek salad"),
            _m("Tasty Cheese Crackers", "PYF", alias="cheese crackers",
               sub="crackers"),
            _m("Wool-only Peas", "WP1", sub=""),
        ]
        self.ld = [
            _l("Halal Beef Mince 500g", "AUG",
               merjan_sp="7.99 (till 12 Sep)", dunya_perm="9.20"),
            _l("Tomato", "EYF", fruitopia_sp="0.90"),
            _l("Halal Lamb Shoulder", "HLS", dunya_sp="12.99"),
            _l("Greek Salad Kit", "GS1", fruitopia_perm="5.00"),
            _l("Wool-only Peas", "WP1"),
        ]

    def test_row1_tracked(self):
        result = lookup_item("tomato", self.master, self.ld)
        self.assertEqual(result["status"], "tracked")
        self.assertEqual(result["master"]["code"], "EYF")
        self.assertEqual(result["best"][0], "fruitopia")

    def test_row2_meat_term_halal_row(self):
        result = lookup_item("halal beef mince 500g", self.master,
                             self.ld)
        self.assertEqual(result["status"], "tracked")
        self.assertIn("halal", result["master"]["name"].lower())

    def test_row3_meat_term_no_halal_row(self):
        result = lookup_item("chicken", self.master, self.ld)
        self.assertEqual(result["status"], "meat-local-only")
        # nothing matches 'chicken', so the unfiltered last-resort
        # pool answers WITHOUT a code (2026-09-11 D2 honesty fix: the
        # old first-in-tab-order code cited an unrelated beef row)
        self.assertEqual(result["code"], "")
        self.assertTrue(result["local"])

    def test_row3b_plain_meat_row_invisible_to_meat_query(self):
        """A plain (non-halal) meat row NEVER matches a meat query —
        the §8 row-3 answer (butcher prices + missing-list) applies."""
        master = self.master + [_m("Beef Diced", "BD1", ww="$9.00",
                                   sub="beef diced")]
        result = lookup_item("beef diced", master, self.ld)
        self.assertEqual(result["status"], "meat-local-only")
        self.assertNotEqual(result.get("master") or {},
                            {"name": "Beef Diced"})

    def test_row4_not_tracked_local_has_it(self):
        result = lookup_item("halal lamb shoulder", self.master,
                             self.ld)
        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["code"], "HLS")
        self.assertEqual(result["best"][0], "dunya")

    def test_row5_not_tracked_local_blank_too(self):
        result = lookup_item("wool-only peas", self.master, self.ld)
        self.assertEqual(result["status"], "not-tracked")

    def test_row5b_unknown_query_never_raises(self):
        result = lookup_item("zzz unknown", self.master, self.ld)
        self.assertEqual(result["status"], "not-tracked")

    def test_row6_gone(self):
        master = self.master + [_m("Halal Sausages", "HSG",
                                   ww="GONE", sub="butchery")]
        ld = self.ld + [_l("Halal Sausages", "HSG",
                           merjan_perm="8.00")]
        result = lookup_item("halal sausages", master, ld)
        self.assertEqual(result["status"], "gone")
        self.assertTrue(result["local"])

    def test_row7_na_marker(self):
        master = self.master + [_m("Halal Wings", "HWG",
                                   ww="N/A 2026-09-08", sub="butchery")]
        ld = self.ld + [_l("Halal Wings", "HWG", dunya_perm="11.00")]
        result = lookup_item("halal wings", master, ld)
        self.assertEqual(result["status"], "na")
        self.assertEqual(result["master"]["na_marker"],
                         "N/A 2026-09-08")

    def test_row8_out_of_domain(self):
        result = lookup_item("cheese crackers", self.master, self.ld)
        self.assertEqual(result["status"], "out-of-domain")

    def test_row9_no_live_search_on_miss(self):
        """A miss answers from the sheet only — never a live search."""
        result = lookup_item("never tracked item", self.master,
                             self.ld)
        self.assertEqual(result["status"], "not-tracked")
        self.assertEqual(result["local"], {})

    def test_alias_match(self):
        result = lookup_item("cheese crackers", self.master, self.ld)
        self.assertEqual(result["master"]["code"], "PYF")


class TestMissingList(unittest.TestCase):
    def test_rule_cases(self):
        master = [
            _m("Listed", "LST", ww="", keyword="",
               sub="butchery"),                      # listed
            _m("Real Price", "RPR", ww="$2.00", keyword="",
               sub="tomato"),                        # price -> no
            _m("Keyword Only", "KWO", ww="", keyword="kw",
               sub="tomato"),                        # keyword -> no
            _m("Gone Row", "GNE", ww="GONE", keyword="",
               sub="butchery"),                      # GONE -> no
            _m("Price Only No Local", "PNL", ww="$1.00",
               keyword="kw", sub="tomato"),          # no local -> no
            _m("No Local Price", "NLP", ww="", keyword="",
               sub="butchery"),                      # blank local -> no
            _m("Na With Keyword Not Missing", "NAK",
               ww="N/A 2026-09-01", keyword="kw", sub="tomato"),
        ]
        ld = [
            _l("Listed", "LST", dunya_perm="9.20"),
            _l("Real Price", "RPR"),
            _l("Keyword Only", "KWO"),
            _l("Gone Row", "GNE"),
            _l("Price Only No Local", "PNL"),
            _l("No Local Price", "NLP"),
            _l("Na With Keyword Not Missing", "NAK",
               fruitopia_sp="3.00"),
        ]
        items = missing_list(master, ld)
        self.assertEqual([i["code"] for i in items], ["LST"])
        entry = items[0]
        self.assertEqual(entry["best_local"], (9.20, "dunya"))
        self.assertEqual(entry["shops"], ["dunya"])
        self.assertEqual(entry["name"], "Listed")

    def test_na_without_keyword_is_missing(self):
        master = [_m("Halal Okra", "HOK", ww="unavailable 2026-09-01",
                     sub="butchery")]
        ld = [_l("Halal Okra", "HOK", merjan_perm="6.00")]
        items = missing_list(master, ld)
        self.assertEqual([i["code"] for i in items], ["HOK"])


class TestRender(unittest.TestCase):
    def test_render_tracked_has_display_and_winner(self):
        master = [_m("Halal Beef Mince 500g", "AUG", ww="$8.50",
                     sub="butchery", brand="Home")]
        ld = [_l("Halal Beef Mince 500g", "AUG", merjan_sp="7.99")]
        out = render_lookup(lookup_item("halal beef mince 500g",
                                        master, ld))
        self.assertIn("Halal Beef Mince 500g", out)
        self.assertIn("$", out)
        self.assertIn("🏆", out)
        self.assertIn("[AUG]", out)
        # style kit v2 (spec §11): emoji section header for the
        # WW line + compact footer with the code legend
        self.assertIn("🟢 Woolworths", out)
        self.assertIn("⏱️ 2026-", out)
        self.assertIn("[CODE] = sheet Item_Code", out)

    def test_render_gone_keeps_locals(self):
        master = [_m("Halal Sausages", "HSG", ww="GONE",
                     sub="butchery")]
        ld = [_l("Halal Sausages", "HSG", merjan_perm="8.00")]
        out = render_lookup(lookup_item("halal sausages", master, ld))
        self.assertIn("GONE at Woolworths", out)
        self.assertIn("Merjan", out)

    def test_render_list_lines_and_count(self):
        items = [{"code": "LST", "name": "Listed",
                  "best_local": (9.2, "dunya"), "shops": ["dunya"]}]
        out = render_list(items)
        self.assertIn("[LST] Listed — best $9.20 (Dunya (site))", out)
        self.assertIn("1 item(s)", out)
        self.assertIn("empty", render_list([]))


class TestNonHalalTwin(unittest.TestCase):
    """§18 A4 / R5-M1…M5 — the display-only non-halal Woolworths twin
    line in meat lookups. Fixture = test.md Evidence rows VERBATIM:
    row 92 `Halal Beef Mince` [AUG] D blank; row 139 `Woolworths Beef
    Mince 500g` [GJZ] D=15, brand Home, keyword filled."""

    TWIN_LINE = ("also at Woolworths (non-halal): $13.54"
                 " · 500g = $27.08/kg"
                 " — Woolworths Beef Mince 500g")

    def _fixture(self, aug_ww="", extra_master=(), extra_ld=()):
        master = [
            _m("Halal Beef Mince", "AUG", ww=aug_ww, sub="butchery"),
            _m("Woolworths Beef Mince 500g", "GJZ", ww="15",
               keyword="Woolworths Beef Mince 500g", sub="beef mince",
               brand="Home"),
        ]
        ld = [_l("Halal Beef Mince", "AUG", dunya_perm="15.99")]
        return master + list(extra_master), ld + list(extra_ld)

    def test_beef_mince_fixture_twin_line_all_three_sides(self):
        """Mandatory M1/M3 test (AUG priced $12.99 like the R4 live
        proof): ONE answer = 🟢 WW halal (discounted) + local butcher
        + 🏆 + the twin line naming GJZ."""
        master, ld = self._fixture(aug_ww="$12.99")
        out = render_lookup(lookup_item("halal beef mince", master,
                                        ld))
        self.assertIn("$12.34", out)          # 🟢 halal, 5% display cut
        self.assertIn("Dunya", out)           # 🔪 local butcher side
        self.assertIn("🏆", out)              # winner badge
        self.assertIn(self.TWIN_LINE, out)    # $15 Home → $13.54

    def test_twin_line_when_halal_price_blank(self):
        """M1 constraint 3: the twin shows immediately even with the
        halal row's D blank (the real-sheet state)."""
        master, ld = self._fixture(aug_ww="")
        for q in ("halal beef mince", "beef mince"):
            out = render_lookup(lookup_item(q, master, ld))
            self.assertIn(self.TWIN_LINE, out)

    def test_exact_plain_name_query_tracks_its_own_row(self):
        """run-2 fix list #2: the exact WW-row name answers §8 row 1 —
        GJZ's own tracked class (was: a locals dump under a false
        header, 'the GJZ tracked-class answer never shown')."""
        master, ld = self._fixture()
        result = lookup_item("Woolworths Beef Mince 500g", master, ld)
        self.assertEqual(result["status"], "tracked")
        self.assertEqual(result["code"], "GJZ")
        out = render_lookup(result)
        self.assertIn("13.54", out)          # discounted WW price
        self.assertNotIn("missing list [", out)

    def test_non_halal_side_never_local(self):
        """M2: twins come from master rows ONLY — an LD decoy sharing
        the twin's name/code never becomes the non-halal side."""
        master, ld = self._fixture(extra_ld=[
            _l("Woolworths Beef Mince 500g", "GJZ",
               merjan_perm="99.99")])
        result = lookup_item("beef mince", master, ld)
        master_names = {m["name"] for m in master}
        names = [t["name"] for t in result["non_halal_twins"]]
        self.assertEqual(names, ["Woolworths Beef Mince 500g"])
        for name in names:
            self.assertIn(name, master_names)
        out = render_lookup(result)
        twin_lines = [ln for ln in out.splitlines()
                      if "non-halal" in ln]
        self.assertEqual(twin_lines, [self.TWIN_LINE])  # $99.99 decoy
        self.assertIn("Dunya", out)                     # halal side only
        self.assertNotIn("99.99", out)

    def test_twin_row_states(self):
        """TW2 states: priced / GONE / N-A render their lines; blank-D
        plain rows are omitted entirely."""
        master, ld = self._fixture(extra_master=[
            _m("Beef Diced", "BD1", ww="GONE", sub="butchery"),
            _m("Beef Ribs", "BR2", ww="N/A 2026-09-08",
               sub="butchery"),
            _m("Beef Strips", "BS3", ww="", sub="butchery"),
        ])
        result = lookup_item("beef", master, ld)
        states = {t["name"]: (t["state"], t["value"])
                  for t in result["non_halal_twins"]}
        self.assertEqual(states["Woolworths Beef Mince 500g"],
                         ("priced", 15.0))
        self.assertEqual(states["Beef Diced"], ("gone", None))
        self.assertEqual(states["Beef Ribs"], ("na", "N/A 2026-09-08"))
        self.assertNotIn("Beef Strips", states)
        out = render_lookup(result)
        self.assertIn(self.TWIN_LINE, out)
        self.assertIn("also at Woolworths (non-halal): GONE"
                      " — Beef Diced", out)
        self.assertIn("also at Woolworths (non-halal): unavailable"
                      " (N/A 2026-09-08) — Beef Ribs", out)
        self.assertNotIn("Beef Strips", out)

    def test_lookup_zero_writes_q11_intact(self):
        """M4: the lookup+render battery mutates nothing (Q11 rows stay
        separate and untouched), the twin path accepts no worksheet
        handle, and no live fallback exists in the read module."""
        master, ld = self._fixture()
        master_before = copy.deepcopy(master)
        ld_before = copy.deepcopy(ld)
        for q in ("beef mince", "halal beef mince",
                  "Woolworths Beef Mince 500g"):
            render_lookup(lookup_item(q, master, ld))
        self.assertEqual(master, master_before)
        self.assertEqual(ld, ld_before)
        self.assertEqual(
            list(inspect.signature(lookup_item).parameters),
            ["query", "master_rows", "ld_rows"])
        self.assertEqual(
            list(inspect.signature(_non_halal_twin).parameters),
            ["query", "master_rows", "exclude_code"])
        self.assertNotIn("v2_live", (_PROJECT / "core" / "v2_read.py")
                         .read_text(encoding="utf-8"))


class TestUnitAwareQuotes(unittest.TestCase):
    """2026-09-10 user unit rule: /kg butcher quotes and per-pack Wool
    prices must convert to a common $/kg basis on screen; the meat
    fallback pool must never quote a DIFFERENT product's row; and the
    raw compare phrasing still yields the twin line."""

    def _rows(self):
        master = [
            _m("Halal BEEF MINCE (5KG)", "EPJ", sub="butchery"),
            _m("Halal Beef Mince", "AUG", sub="butchery"),
            _m("Woolworths Beef Mince 500g", "GJZ", ww="15",
               size="500g", sub="beef mince", brand="Home"),
        ]
        ld = [
            _l("Halal BEEF MINCE (5KG) /ea", "EPJ",
               dunya_perm="64.99"),
            _l("Halal Beef Mince /kg", "AUG", dunya_perm="15.99"),
        ]
        return master, ld

    def test_kg_and_ea_quotes_convert(self):
        master, ld = self._rows()
        result = lookup_item("beef mince", master, ld)
        out = render_lookup(result)
        self.assertIn("$15.99/kg", out)
        self.assertIn("$64.99 / 5kg pack = $13.00/kg", out)
        # winner on the $/kg basis, not the raw numbers
        self.assertIn("🏆 Best local: $13.00/kg — Dunya (site)", out)
        # cheapest per-kg quote lists first
        self.assertLess(out.index("$13.00/kg"), out.index("$15.99/kg"))

    def test_ww_halal_price_shows_per_kg(self):
        master, ld = self._rows()
        master[1] = _m("Halal Beef Mince", "AUG", ww="$12.99",
                       size="500g", sub="butchery")
        out = render_lookup(lookup_item("halal beef mince", master,
                                        ld))
        self.assertIn("🟢 Woolworths  $12.34 · 500g = $24.68/kg", out)

    def test_fallback_pool_never_crosses_products(self):
        """The R4-era bug: 'beef mince' quoted Merjan $13.99 from a
        CHICKEN row — the pool must filter to the query's product."""
        master, ld = self._rows()
        ld.append(_l("Halal Chicken Breast Strips /kg", "AXW",
                     merjan_perm="13.99"))
        result = lookup_item("beef mince", master, ld)
        out = render_lookup(result)
        # 2026-09-11 D3 fix: the header cites the best-MATCHED row
        # (the /kg AUG row), never sheet order
        self.assertEqual(result["code"], "AUG")
        self.assertNotIn("Merjan", out)
        self.assertNotIn("13.99", out)
        self.assertNotIn("Chicken", out)

    def test_compare_filler_phrase_still_twin(self):
        master, ld = self._rows()
        result = lookup_item("compare halal vs non halal beef mince",
                             master, ld)
        out = render_lookup(result)
        self.assertIn(TestNonHalalTwin.TWIN_LINE, out)

    def test_bare_prices_keep_legacy_render(self):
        """LD rows without a unit suffix render bare prices and the
        legacy raw-price winner badge (no /kg invented)."""
        master = [_m("Halal Lamb Shoulder", "HLS", sub="butchery")]
        ld = [_l("Halal Lamb Shoulder", "HLS", dunya_perm="12.99")]
        out = render_lookup(lookup_item("halal lamb shoulder", master,
                                        ld))
        self.assertIn("🔪 Dunya (site)", out)
        self.assertIn("$12.99", out)
        self.assertNotIn("/kg", out)


class TestLocalSpecialsReport(unittest.TestCase):
    """`specials --store local` (user decision 2026-09-12): the four
    shops' CURRENT specials, read-only — kind 'special' only, grouped
    per shop, multibuy terms rewritten 'min order …', permanent
    prices never shown, empty → honest no-specials line."""

    def _report(self, ld):
        from core.v2_read import local_specials_report
        return local_specials_report(ld)

    def test_specials_only_grouped_with_min_order(self):
        ld = [
            _l("Halal Lamb Mince /kg", "GVJ",
               merjan_sp="15 (till 13 Sep)",
               merjan_perm="16.99", dunya_perm="15.99"),
            _l("Halal Drumstick", "VCK", merjan_sp="4"),
            _l("Cos Lettuce /ea", "COS", fruitopia_perm="0.99"),
        ]
        out = self._report(ld)
        self.assertIn("Merjan Brothers Quality Meats", out)
        self.assertIn("Halal Lamb Mince — $15.00/kg (special)", out)
        self.assertIn("Halal Drumstick — $4.00 (special)", out)
        # permanent prices never appear in the specials answer
        self.assertNotIn("16.99", out)
        self.assertNotIn("15.99", out)
        self.assertNotIn("Fruitopia", out)
        self.assertIn("📊 2 local special(s) across 1 shop(s)", out)

    def test_min_order_terms_rendered(self):
        ld = [_l("Halal Goat Curry /kg", "NZH",
                 merjan_sp="15 (till 13 Sep)")]
        ld[0]["comments"] = "[MER] multi buy 2kg for $29.99"
        out = self._report(ld)
        self.assertIn("min order 2kg for $29.99", out)
        self.assertNotIn("multi buy", out)

    def test_empty_is_honest(self):
        self.assertEqual(self._report([]),
                         "No active local specials right now.")
        ld = [_l("Cos Lettuce /ea", "COS", fruitopia_perm="0.99")]
        self.assertEqual(self._report(ld),
                         "No active local specials right now.")


if __name__ == "__main__":
    unittest.main()


class TestMultibuyTermsInReply(unittest.TestCase):
    """R5-follow-up: multibuy TERMS ride the quote into the reply —
    '(special)' alone hid the actual offer (user, 2026-09-11)."""

    LD = {"row": 36, "name": "Halal Lamb Mince /kg",
          "prices": {"merjan": (15.0, "special"),
                     "dunya": (15.99, "permanent")},
          "comments": "[MER] multi buy 2kg for $29.99", "code": "GVJ"}

    def test_quote_carries_shop_note(self):
        from core.v2_read import _ld_quotes
        quotes = {q["shop"]: q for q in _ld_quotes(self.LD)}
        self.assertEqual(quotes["merjan"]["note"],
                         "multi buy 2kg for $29.99")
        self.assertEqual(quotes["dunya"]["note"], "")

    def test_render_shows_terms_next_to_price(self):
        from core.v2_read import _ld_quotes, _local_lines, render_lookup
        quotes = _ld_quotes(self.LD)
        result = {"status": "meat-local-only", "master": None,
                  "local": self.LD["prices"], "best": ("merjan", 15.0,
                                                       "special"),
                  "best_label": "$15.00/kg",
                  "local_quotes": quotes, "code": "GVJ",
                  "non_halal_twins": [], "query": "halal lamb mince"}
        text = render_lookup(result)
        self.assertIn("min order 2kg for $29.99", text)
        self.assertIn("(special)", text)

    def test_no_note_no_render(self):
        from core.v2_read import _ld_quotes, _local_lines
        ld = dict(self.LD, comments="")
        lines = _local_lines({"local_quotes": _ld_quotes(ld)})
        self.assertFalse(any("multi buy" in ln for ln in lines))


class TestPackRouting(unittest.TestCase):
    """2026-09-11 fix (item_exec_2026-09-11_1106.csv): a pack-
    presented row ('Name – (5kg)') must answer a name+size-token
    query with ITS code. Evidence rows: SDB 'halal lebanese kofta
    4kg', KWM 'halal turkish kofta 5kg', PSB 'halal chicken
    tenderloin 5kg', HSZ 'halal premium chuck mince 5kg' all
    answered bare 'Not tracked' — 'kofta'/'tenderloin'/'chuck' are
    not meat terms, so the §8 row-3 halal-local fallback never ran
    and the exact-name match missed the '– (5kg)' decoration."""

    def setUp(self):
        self.master = [
            _m("Halal Lebanese Kofte", "GMH", sub="butchery"),
            _m("Halal Lebanese kofta – (4kg)", "SDB", sub="butchery"),
            _m("Halal Turkish Kofte", "FZH", sub="butchery"),
            _m("Halal Turkish Kofta – (5kg)", "KWM", sub="butchery"),
            _m("Halal chicken tenders", "BUD", sub="butchery"),
            _m("Halal Chicken Tenderloin – (5kg)", "PSB",
               sub="butchery"),
            _m("Halal Lamb Tenderloin – (5kg)", "WZF",
               sub="butchery"),
            _m("Halal Beef premium Mince", "VFZ", sub="butchery"),
            _m("Halal Lean Lamb Mince – (5kg)", "ZDA",
               sub="butchery"),
            _m("Halal Lamb Mince – (5kg)", "WHA", sub="butchery"),
            _m("Halal premium chuck Mince – (5kg)", "HSZ",
               sub="butchery"),
        ]
        self.ld = [
            _l("Halal Lebanese Kofte /kg", "GMH", dunya_perm="16.99"),
            _l("Halal Lebanese kofta – (4kg) /ea", "SDB",
               dunya_perm="59.99"),
            _l("Halal Turkish Kofte /kg", "FZH", dunya_perm="16.99"),
            _l("Halal Turkish Kofta – (5kg) /ea", "KWM",
               dunya_perm="74.99"),
            _l("Halal chicken tenders /kg", "BUD",
               merjan_sp="11.00 (till 12 Sep)"),
            _l("Halal Chicken Tenderloin – (5kg) /ea", "PSB",
               dunya_perm="54.99"),
            _l("Halal Lamb Tenderloin – (5kg) /ea", "WZF",
               dunya_perm="134.99"),
            _l("Halal Beef premium Mince /kg", "VFZ",
               dunya_perm="17.99"),
            _l("Halal Lean Lamb Mince – (5kg) /ea", "ZDA",
               dunya_perm="79.99"),
            _l("Halal Lamb Mince – (5kg) /ea", "WHA",
               dunya_perm="69.99"),
            _l("Halal premium chuck Mince – (5kg) /ea", "HSZ",
               dunya_perm="79.99"),
        ]

    def _missing(self, query):
        result = lookup_item(query, self.master, self.ld)
        self.assertEqual(result["status"], "missing")
        return result

    def test_sdb_lebanese_kofta_4kg(self):
        result = self._missing("halal lebanese kofta 4kg")
        self.assertEqual(result["code"], "SDB")
        out = render_lookup(result)
        self.assertIn("missing list [SDB]", out)
        self.assertIn("$59.99 / 4kg pack = $15.00/kg", out)

    def test_kwm_turkish_kofta_5kg(self):
        result = self._missing("halal turkish kofta 5kg")
        self.assertEqual(result["code"], "KWM")
        self.assertIn("missing list [KWM]",
                      render_lookup(result))

    def test_psb_chicken_tenderloin_5kg(self):
        result = self._missing("halal chicken tenderloin 5kg")
        self.assertEqual(result["code"], "PSB")
        self.assertIn("$54.99 / 5kg pack = $11.00/kg",
                      render_lookup(result))

    def test_hsz_premium_chuck_mince_5kg(self):
        result = self._missing("halal premium chuck mince 5kg")
        self.assertEqual(result["code"], "HSZ")
        self.assertIn("missing list [HSZ]",
                      render_lookup(result))

    def test_wzf_lamb_tenderloin_5kg(self):
        # 5th evidence row in the same CSV (line 'halal lamb
        # tenderloin 5kg' -> bare 'Not tracked')
        result = self._missing("halal lamb tenderloin 5kg")
        self.assertEqual(result["code"], "WZF")

    def test_wha_exact_token_set_beats_lean_cousin(self):
        # 'lamb mince 5kg' must cite WHA (Lamb Mince), not ZDA (Lean
        # Lamb Mince) — same sheet, both 5kg packs
        result = self._missing("halal lamb mince 5kg")
        self.assertEqual(result["code"], "WHA")
        out = render_lookup(result)
        self.assertIn("$69.99 / 5kg pack = $14.00/kg", out)
        self.assertNotIn("Lean", out)

    def test_size_mismatch_never_routes_to_pack_row(self):
        # wrong size token: no 5kg kofta row exists -> honest miss,
        # never the 4kg row
        result = lookup_item("halal lebanese kofta 5kg",
                             self.master, self.ld)
        self.assertNotEqual(result["code"], "SDB")
        self.assertIsNone(result["master"])

    def test_exact_name_still_wins_over_pack_match(self):
        result = lookup_item("Halal Turkish Kofta – (5kg)",
                             self.master, self.ld)
        self.assertEqual(result["code"], "KWM")
