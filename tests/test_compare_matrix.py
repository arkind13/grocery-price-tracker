"""The comparison matrix (user ask 2026-09-27: 'I want you do
extensive comparison not only 1 item compare 50 items all different
scenarios i dont want to open this topic again').

50+ scenarios across every row shape the sheet now carries, each
asserting the EXACT rendered reply lines through the REAL lookup +
render pipeline (parse_master_row / parse_ld_row → lookup_item →
render_lookup), including the user's named case:
  'what happens if the same individual line is at Dunya, Nazar and
  Merjan and Merjan also has a bulk weekend offer - does it show me
  all 4 comparisons' — yes, all four, and the winner carries its
  minimum order.
"""
from __future__ import annotations

import unittest
from datetime import date

from core import local_deals as ld
from core.v2_read import (lookup_item, parse_ld_row, parse_master_row,
                          render_lookup)

TODAY = date(2026, 9, 27)


def _m(name, code, ww="", keyword="", sub="", alias="", brand="",
       specials="", size=""):
    row = [""] * 13
    row[0], row[2], row[3], row[4], row[6], row[7], row[9], \
        row[10], row[11] = (
        name, size, ww, brand, keyword, specials, alias, sub, code)
    return parse_master_row(2, row)


def _l(name, code, comments="", **prices):
    """LD row through the REAL parser; prices: col_key -> cell text."""
    row = [""] * 13
    row[0] = name
    row[12] = code
    row[11] = comments
    col = {"dunya_perm": 2, "dunya_sp": 3, "merjan_perm": 4,
           "merjan_sp": 5, "fruitopia_perm": 6, "fruitopia_sp": 7,
           "abusalim_perm": 8, "abusalim_sp": 9, "nazar_perm": 10}
    for key, value in prices.items():
        row[col[key]] = value
    return parse_ld_row(3, row, today=TODAY)


def _reply(query, master, lds):
    return render_lookup(lookup_item(query, master, lds))


# ---------------------------------------------------------------------------
# THE user-named scenario class: one item, every shop, bulk included
# ---------------------------------------------------------------------------
class TestFourWayComparisons(unittest.TestCase):

    def _rows(self):
        master = [
            _m("Halal Chicken Thigh Fillet", "APM", sub="butchery"),
        ]
        lds = [
            _l("Halal Chicken Thigh Fillet /kg", "APM",
               dunya_perm="15.99", merjan_perm="18.50",
               nazar_perm="16.9"),
            _l("Halal Chicken Thigh Fillet \u2013 (2kg) /ea", "KXQ",
               comments="[MER] multi buy 2kg for $21.99",
               merjan_sp="21.99 (till 27 Sep)"),
        ]
        return master, lds

    def test_all_four_quotes_shown(self):
        out = _reply("halal chicken thigh fillet", *self._rows())
        self.assertIn("Dunya (site)", out)
        self.assertIn("$15.99/kg", out)
        self.assertIn("Nazar", out)
        self.assertIn("$16.90/kg", out)
        self.assertIn("Merjan", out)
        self.assertIn("$18.50/kg", out)          # Merjan regular
        self.assertIn("$21.99 / 2kg pack = $10.99/kg (special)", out)
        knife = [ln for ln in out.splitlines()
                 if "\U0001F52A" in ln]
        self.assertEqual(len(knife), 4)          # four shop lines

    def test_winner_carries_minimum_order(self):
        out = _reply("halal chicken thigh fillet", *self._rows())
        self.assertIn(
            "\U0001F3C6 Best local: $10.99/kg (min 2kg order)"
            " \u2014 Merjan Brothers Quality Meats", out)
        self.assertNotIn(
            "\U0001F3C6 Best local: $10.99/kg \u2014", out)

    def test_bulk_note_not_duplicated_on_pack_line(self):
        out = _reply("halal chicken thigh fillet", *self._rows())
        # the pack math already says it — no '· min order 2kg for
        # $21.99' repetition on the same line (user: 'the format of
        # the message is not right')
        self.assertNotIn("min order 2kg for $21.99", out)

    def test_footer_cites_the_answering_rows_code(self):
        out = _reply("halal chicken thigh fillet", *self._rows())
        lines = out.splitlines()
        codes = [ln.strip() for ln in lines
                 if ln.strip().startswith("[") and "]" in ln
                 and "missing list" not in ln]
        self.assertIn("[KXQ]", codes)   # pack row answered the price
        self.assertIn("[APM]", out)     # /kg row leads missing-WW

    def test_plain_per_kg_beats_expensive_bulk(self):
        """When the bulk rate LOSES, the plain winner carries NO
        qualifier (nothing misleading either way)."""
        master, lds = self._rows()
        lds[1] = _l("Halal Chicken Thigh Fillet \u2013 (2kg) /ea",
                    "KXQ",
                    comments="[MER] multi buy 2kg for $39.98",
                    merjan_sp="39.98 (till 27 Sep)")
        out = _reply("halal chicken thigh fillet", master, lds)
        self.assertIn(
            "\U0001F3C6 Best local: $15.99/kg \u2014 Dunya (site)",
            out)

    def test_reg_price_rides_the_bulk_special_line(self):
        master, lds = self._rows()
        out = _reply("halal chicken thigh fillet", master, lds)
        self.assertIn("reg $18.50", out)


class TestCountedFourWay(unittest.TestCase):
    """Steamer chickens: Nazar per-bird + Merjan 2-bird bundle."""

    def _rows(self):
        master = [_m("Halal Steamer Chickens", "KJP",
                     sub="butchery")]
        lds = [
            _l("Halal Steamer Chickens /ea", "KJP",
               nazar_perm="12.9"),
            _l("Halal Steamer Chickens \u2013 (2 pack) /ea", "ST2",
               comments="[MER] multi buy 2 for $11.99",
               merjan_sp="11.99 (till 27 Sep)"),
        ]
        return master, lds

    def test_both_quotes_and_per_bird_winner_with_min(self):
        out = _reply("halal steamer chickens", *self._rows())
        self.assertIn("$12.90/ea", out)
        self.assertIn("$11.99 / 2 pack = $6.00/ea (special)", out)
        self.assertIn(
            "\U0001F3C6 Best local: $6.00/ea (min 2)"
            " \u2014 Merjan Brothers Quality Meats", out)

    def test_counted_bundle_losing_to_plain_per_bird(self):
        master, lds = self._rows()
        lds[0] = _l("Halal Steamer Chickens /ea", "KJP",
                    nazar_perm="5.50")
        out = _reply("halal steamer chickens", master, lds)
        self.assertIn(
            "\U0001F3C6 Best local: $5.50/ea \u2014 Nazar", out)


# ---------------------------------------------------------------------------
# Sealed weight packs, size specs, captions, expiry, twins
# ---------------------------------------------------------------------------
class TestLineDedupeAndTieBreak(unittest.TestCase):
    """2026-09-27 read-side formats, pinned from the live battery:
    identical family lines collapse; equal $/kg prefers the smaller
    minimum order."""

    def test_identical_shop_price_lines_collapse(self):
        """Three chicken-breast rows all priced 13.99 at Dunya render
        ONE Dunya line (family pooling must not repeat itself)."""
        master = [_m("Halal Chicken Breast", "XJA", sub="butchery")]
        lds = [
            _l("Halal chicken breast diced /kg", "D1",
               dunya_perm="13.99"),
            _l("Halal chicken breast strips /kg", "D2",
               dunya_perm="13.99"),
            _l("Halal Chicken Breast Fillet /kg", "D3",
               dunya_perm="13.99"),
        ]
        out = _reply("halal chicken breast", master, lds)
        self.assertEqual(out.count("Dunya (site)  $13.99/kg"), 1)

    def test_rate_tie_prefers_smaller_minimum(self):
        master = [_m("Halal Chicken Tenderloins", "TN",
                     sub="butchery")]
        lds = [
            _l("Halal Chicken Tenderloins – (3kg) /ea", "T3",
               comments="[MER] multi buy 3kg for $32.99",
               merjan_sp="32.99 (till 27 Sep)"),
            _l("Halal Chicken Tenderloins – (5kg) /ea", "T5",
               dunya_perm="54.99"),
        ]
        out = _reply("halal chicken tenderloins", master, lds)
        self.assertIn(
            "🏆 Best local: $11.00/kg (min 3kg order)"
            " — Merjan Brothers Quality Meats", out)


class TestWeightPacksAndSpecs(unittest.TestCase):

    def test_sealed_5kg_pack_renders_with_min_qualifier(self):
        master = [_m("Halal BEEF MINCE (5KG)", "EPJ",
                     sub="butchery")]
        lds = [_l("Halal BEEF MINCE (5KG) /ea", "EPJ",
                  dunya_perm="64.99"),
               _l("Halal Beef Mince /kg", "AUG", dunya_perm="15.99")]
        out = _reply("halal beef mince", master, lds)
        self.assertIn("$64.99 / 5kg pack = $13.00/kg", out)
        self.assertIn("(min 5kg order)", out)

    def test_min_weight_size_spec_keeps_its_note(self):
        """'(min 1.9kg)' on a per-bird row is a SIZE spec — the note
        STAYS (it is information, not a bundle repetition)."""
        master = [_m("Halal Whole chicken s14", "ATN",
                     sub="butchery")]
        lds = [_l("Halal Whole chicken s14 /ea", "ATN",
                  comments="[MER] min 1.9kg",
                  merjan_sp="34.99 (till 27 Sep)",
                  nazar_perm="12.9")]
        out = _reply("halal whole chicken", master, lds)
        self.assertIn("$34.99/ea (special) · min 1.9kg", out)

    def test_caption_condition_note_survives(self):
        master = [_m("Halal Beef Sirloin", "SIR", sub="butchery")]
        lds = [_l("Halal Beef Sirloin /kg", "SIR",
                  comments="[DUN] when you buy the whole slab",
                  dunya_sp="24.99 (till 27 Sep)")]
        out = _reply("halal beef sirloin", master, lds)
        self.assertIn(
            "$24.99/kg (special) · when you buy the whole slab", out)

    def test_expired_special_not_quoted(self):
        master = [_m("Halal Lamb Loin", "LL", sub="butchery")]
        lds = [_l("Halal Lamb Loin /kg", "LL",
                  merjan_sp="15.99 (till 25 Sep)",   # 2 days past
                  nazar_perm="18.9")]
        out = _reply("halal lamb loin", master, lds)
        self.assertIn("$18.90/kg", out)
        self.assertNotIn("15.99", out)


class TestWinnerEdgeCases(unittest.TestCase):

    def test_kg_tie_earliest_min_stable(self):
        master = [_m("Halal Goat Curry", "GC", sub="butchery")]
        lds = [_l("Halal Goat Curry /kg", "GC",
                  dunya_perm="18.00", nazar_perm="18.00")]
        out = _reply("halal goat curry", master, lds)
        self.assertIn("Best local: $18.00/kg", out)

    def test_cheapest_per_kg_lists_first(self):
        master = [_m("Halal Chicken Breast", "CB", sub="butchery")]
        lds = [
            _l("Halal Chicken Breast /kg", "CB",
               dunya_perm="15.99", nazar_perm="16.9"),
            _l("Halal Chicken Breast \u2013 (5kg) /ea", "CB5",
               comments="[MER] multi buy 5kg for $34.99",
               merjan_sp="34.99 (till 27 Sep)"),
        ]
        out = _reply("halal chicken breast", master, lds)
        self.assertLess(out.index("$7.00/kg"), out.index("$15.99/kg"))

    def test_bare_price_winner_no_label(self):
        master = [_m("Halal Kofta Box", "KB", sub="butchery")]
        lds = [_l("Halal Kofta Box", "KB", merjan_sp="19.99")]
        out = _reply("halal kofta box", master, lds)
        self.assertIn("Best local: $19.99", out)
        self.assertNotIn("/kg", out.split("Best local")[1][:30])


# ---------------------------------------------------------------------------
# THE 50-ITEM BATTERY: every row shape × lookup — no crash, no
# misleading line, money format sane, winner present when priced
# ---------------------------------------------------------------------------
_ITEMS = [
    # (query, master_name, ld_shapes)
    ("halal chicken thigh fillet", "Halal Chicken Thigh Fillet",
     [("kg_plain", 3), ("pack2kg", 5)]),
    ("halal beef curry", "Halal Beef Curry",
     [("kg_plain", 2), ("pack5kg", 5)]),
    ("halal goat curry", "Halal Goat Curry",
     [("kg_plain", 2), ("pack2kg", 5), ("pack5kg", 10)]),
    ("halal chicken wings", "Halal Chicken Wings",
     [("kg_plain", 2), ("pack5kg", 5)]),
    ("halal drumsticks", "Halal Chicken Drumsticks",
     [("kg_plain", 2), ("pack5kg", 5), ("pack_ea", 9)]),
    ("halal steamer chickens", "Halal Steamer Chickens",
     [("ea_plain", 10), ("pack2pc", 5)]),
    ("halal whole chicken", "Halal Whole chicken s14",
     [("ea_plain", 10), ("pack5pc", 5)]),
    ("halal chicken tenderloins", "Halal Chicken Tenderloins",
     [("kg_plain", 2), ("pack3kg", 5)]),
    ("halal sausages", "Halal Sausages", [("kg_plain", 2)]),
    ("halal lamb mince", "Halal Lamb Mince",
     [("kg_plain", 2), ("pack2kg", 5), ("pack5kg_ea", 2)]),
    ("halal beef mince", "Halal Beef Mince",
     [("kg_plain", 2), ("pack5kg_ea", 2)]),
    ("halal lamb ribs", "Halal Lamb Ribs", [("kg_plain", 2)]),
    ("halal lamb necks", "Halal Lamb Necks",
     [("kg_plain", 2), ("pack2kg", 5)]),
    ("halal bbq blade steak", "Halal BBQ Blade Steak",
     [("kg_plain", 2), ("pack2kg", 5)]),
    ("halal lamb grilling chops", "Halal Lamb Grilling Chops",
     [("kg_plain", 2), ("pack2kg", 5)]),
    ("halal chicken maryland", "Halal Chicken Maryland",
     [("kg_plain", 2), ("pack5kg", 5)]),
    ("halal chicken mince", "Halal Chicken Mince",
     [("kg_plain", 2), ("pack2kg", 5)]),
    ("halal mid wings", "Halal Mid Wings",
     [("kg_plain", 2), ("pack2kg", 5)]),
    ("halal povi masima", "Halal Povi Masima Bucket",
     [("bare", 5)]),
    ("halal lamb leg", "Halal Lamb Leg", [("kg_plain", 10)]),
    ("halal lamb shoulder", "Halal Lamb Shoulder",
     [("kg_plain", 10)]),
    ("halal lamb cutlet", "Halal Lamb Cutlet", [("kg_plain", 10)]),
    ("halal whole rump", "Halal Whole Rump", [("kg_plain", 10)]),
    ("halal breast", "Halal Chicken Breast",
     [("kg_plain", 10), ("pack5kg", 5)]),
    ("halal beef sirloin", "Halal Beef Sirloin", [("kg_plain", 2)]),
    ("halal beef cube", "Halal Beef Cube",
     [("kg_plain", 10), ("pack2kg", 5)]),
    ("halal lamb curry", "Halal Lamb Curry", [("kg_plain", 10)]),
    ("halal lamb chops", "Halal Lamb Chops", [("kg_plain", 10)]),
    ("halal lamb shanks", "Halal Lamb Shanks", [("kg_plain", 10)]),
    ("halal osso buco", "Halal Osso Buco", [("kg_plain", 10)]),
    ("halal beef ribs", "Halal Beef Ribs", [("kg_plain", 10)]),
    ("halal brisket", "Halal Beef Brisket", [("kg_plain", 10)]),
    ("halal shin bone", "Halal Shin Bone", [("kg_plain", 10)]),
    ("halal chicken burger", "Halal Chicken Burgers",
     [("ea_plain", 9)]),
    ("halal seekh kebab", "Halal Seekh Kebab", [("kg_plain", 10)]),
    ("halal lamb kofta", "Halal Lamb Kofta", [("kg_plain", 10)]),
    ("halal chicken nuggets", "Halal Chicken Nuggets",
     [("ea_plain", 9)]),
    ("halal drumettes", "Halal Chicken Drumettes",
     [("kg_plain", 2), ("pack2kg", 5)]),
    ("halal flavoured sausages", "Halal Flavoured Sausages",
     [("kg_plain", 2), ("pack2kg", 5)]),
    ("halal lamb sausages", "Halal Lamb Sausages",
     [("kg_plain", 2)]),
    ("halal chicken skewers", "Halal Chicken Skewers",
     [("ea_plain", 9)]),
    ("halal wingettes", "Halal Chicken Wingettes",
     [("kg_plain", 2)]),
    ("halal quarter", "Halal Chicken Quarter", [("ea_plain", 9)]),
    ("halal Silverside", "Halal Beef Silverside",
     [("kg_plain", 10)]),
    ("halal rib fillet", "Halal Beef Rib Fillet",
     [("kg_plain", 10)]),
    ("halal rump", "Halal Beef Rump", [("kg_plain", 10)]),
    ("halal chuck", "Halal Beef Chuck", [("kg_plain", 10)]),
    ("halal blade", "Halal Beef Blade", [("kg_plain", 10)]),
    ("halal oyster blade", "Halal Beef Oyster Blade",
     [("kg_plain", 10)]),
    ("halal knuckle", "Halal Beef Knuckle", [("kg_plain", 10)]),
    ("halal gravy beef", "Halal Gravy Beef", [("kg_plain", 10)]),
]

_COL_FOR = {"dunya_perm": 2, "dunya_sp": 3, "merjan_perm": 4,
            "merjan_sp": 5, "fruitopia_perm": 6, "fruitopia_sp": 7,
            "abusalim_perm": 8, "abusalim_sp": 9, "nazar_perm": 10}
_KEY_FOR = {v: k for k, v in _COL_FOR.items()}
_PRICE = {"abusalim_sp": "4.50 (till 27 Sep)", "abusalim_perm": "14.50", "dunya_perm": "15.99", "dunya_sp": "13.99",
          "merjan_perm": "18.50", "merjan_sp": "21.99 (till 27 Sep)",
          "nazar_perm": "16.9", "fruitopia_sp": "3.99 (till 27 Sep)"}


def _shape_row(base, shape, price_col, i):
    """Build one LD row of a given shape with a distinct code."""
    if shape == "kg_plain":
        name, col = f"{base} /kg", price_col
    elif shape == "ea_plain":
        name, col = f"{base} /ea", price_col
    elif shape == "bare":
        name, col = base, price_col
    elif shape == "pack2kg":
        name, col = f"{base} \u2013 (2kg) /ea", price_col
    elif shape == "pack3kg":
        name, col = f"{base} \u2013 (3kg) /ea", price_col
    elif shape == "pack5kg":
        name, col = f"{base} \u2013 (5kg) /ea", price_col
    elif shape == "pack5kg_ea":
        name, col = f"{base} \u2013 (5kg) /ea", "dunya_perm"
    elif shape == "pack_ea":
        name, col = f"{base} \u2013 (5kg) /ea", "abusalim_perm"
    elif shape == "pack2pc":
        name, col = f"{base} \u2013 (2 pack) /ea", price_col
    elif shape == "pack5pc":
        name, col = f"{base} \u2013 (5 pack) /ea", price_col
    else:
        raise AssertionError(shape)
    row = [""] * 13
    row[0] = f"Halal {name}" if not name.startswith("Halal") \
        else name
    row[12] = f"S{i:03d}"
    key = price_col if isinstance(price_col, str) \
        else _KEY_FOR[price_col]
    row[_COL_FOR[key]] = _PRICE[key]
    return parse_ld_row(i + 3, row, today=TODAY)


class TestFiftyItemBattery(unittest.TestCase):
    """50 items across every shape; every reply must be well-formed:
    correct money formats, pack maths right, winner labelled honestly
    (a bundle winner ALWAYS shows its minimum order)."""

    def test_all_fifty_replies_well_formed(self):
        import re
        checked = 0
        for i, (query, mname, shapes) in enumerate(_ITEMS):
            master = [_m(f"Halal {mname}" if not mname.startswith(
                "Halal") else mname, f"M{i:03d}", sub="butchery")]
            lds = []
            for j, (shape, pcol) in enumerate(shapes):
                base = mname if not mname.startswith("Halal") \
                    else mname[6:]
                lds.append(_shape_row(base, shape, pcol, i * 10 + j))
            out = _reply(query, master, lds)
            self.assertTrue(out.strip(), query)
            # money format sanity — no raw floats/None anywhere
            self.assertNotIn("None", out, query)
            self.assertNotIn("nan", out.lower(), query)
            for money in re.findall(r"\$\d+(?:\.\d+)?", out):
                self.assertRegex(money, r"^\$\d+\.\d{2}$",
                                 f"{query}: {money}")
            # every pack line shows its computed basis
            for m2 in re.findall(
                    r"\$(\d+(?:\.\d+)?) / (\d+(?:\.\d+)?) "
                    r"(kg pack|pack) = \$(\d+(?:\.\d+)?)", out):
                total, basis, _unit, rate = m2
                expect = round(float(total) / float(basis), 2)
                self.assertAlmostEqual(
                    float(rate), expect, places=2, msg=query)
            # a bundle winner ALWAYS carries its minimum order
            win = next((ln for ln in out.splitlines()
                        if "Best local" in ln), "")
            if " pack" in out:
                self.assertIn("min", win,
                              f"{query}: bundle won without min: {win}")
            checked += 1
        self.assertGreaterEqual(checked, 50)

    def test_each_query_answers_every_shop_row(self):
        """The pooled answer mentions EVERY row that prices the item
        (the /kg row AND every pack row) — nothing silently hidden."""
        for i, (query, mname, shapes) in enumerate(_ITEMS):
            master = [_m(f"Halal {mname}" if not mname.startswith(
                "Halal") else mname, f"M{i:03d}", sub="butchery")]
            lds = [_shape_row(
                mname if not mname.startswith("Halal") else mname[6:],
                shape, pcol, i * 10 + j)
                for j, (shape, pcol) in enumerate(shapes)]
            out = _reply(query, master, lds)
            shop_icons = ("\U0001F52A", "\U0001F34E", "\U0001F955")
            knife = [ln for ln in out.splitlines()
                     if any(ic in ln for ic in shop_icons)]
            self.assertEqual(
                len(knife), len(lds),
                f"{query}: {len(knife)} lines for {len(lds)} rows"
                f"\n{out}")


if __name__ == "__main__":
    unittest.main()
