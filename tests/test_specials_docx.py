"""2026-09-10 user fix — parse_specials_docx: the saved specials-panel
docx must yield EVERY product (incl. out-of-stock panels with no price
line, which doc_parser.parse_docx's name->price adjacency drops) with
SAVE / N-for / bonus badges attributed to the right panel, and the
Wednesday specials section must group discounted vs multi-buy deals.

Offline: docx built in-test via python-docx (tmp path)."""
from __future__ import annotations
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from extractors.models import ProductItem         # noqa: E402
from extractors.specials_parser import (          # noqa: E402
    parse_specials_docx,
)
from core.v2_wednesday import render_docx_specials_section  # noqa: E402


def _docx(tmp: str, lines: list) -> str:
    from docx import Document
    doc = Document()
    for ln in lines:
        doc.add_paragraph(ln)
    path = str(Path(tmp) / "specials.docx")
    doc.save(path)
    return path


LINES = [
    "Special list (5 Products)",        # page furniture
    "Add all to cart (3)",
    "Toggle Fruit & Veg group Dropdown",
    "Strawberries Punnet 250g",         # plain item, no badge
    "$3.00",
    "$12.00 / 1KG",
    "Add to cart",
    "SAVE\xa0$1.00",                    # badge ABOVE the next name
    "Weet Cereal 400g",
    "$4.00",
    "$1.00 / 100G",
    "Add to cart",
    "Choc Biscuits 200g",               # 2-for after the unit-price line
    "$4.00",
    "$10.00 / 100G",
    "2 for $7.00 - $8.75/100G",
    "Add to cart",
    "Yoghurt Pouch Mango 150g",         # bonus + tail-badge -> NEXT panel
    "$1.90",
    "$1.27 / 100G",
    "Buy 1 get a bonus Container credit^",
    "Add to cart",
    "SAVE\xa0$1.30",
    "Mist Toner Spray 120mL",           # badge UNDER the name, no price
    "SAVE\xa0$7.20",
    "Lotion Bottle 500mL",              # out of stock: no price line
    "Out of stock",
]


class TestParseSpecialsDocx(unittest.TestCase):
    def test_all_items_badges_and_prices(self):
        with tempfile.TemporaryDirectory() as tmp:
            items = parse_specials_docx(_docx(tmp, LINES))
        by_name = {i.raw_name: i for i in items}
        # EVERY panel parses — incl. the out-of-stock tail panel
        self.assertEqual(len(items), 6)
        self.assertIn("Strawberries Punnet 250g", by_name)
        self.assertIn("Lotion Bottle 500mL", by_name)

        def _one(fragment):
            return next(i for i in items if fragment in i.raw_name)

        plain = _one("Strawberries")
        self.assertEqual(plain.price, 3.0)
        self.assertFalse(plain.is_special)

        weet = _one("Weet Cereal")
        self.assertEqual(weet.price, 4.0)
        self.assertTrue(weet.is_special)
        self.assertEqual(weet.special_desc, "save $1.00 (20% off)")

        choc = _one("Choc Biscuits")
        self.assertEqual(choc.special_desc, "2 for $7.00")

        yog = _one("Yoghurt Pouch")
        self.assertEqual(yog.price, 1.9)
        # rule (3): the mid-panel bonus badge is Yoghurt's own
        self.assertIn("bonus", yog.special_desc)
        self.assertNotIn("save $1.30", yog.special_desc)

        mist = _one("Mist Toner Spray")
        self.assertIsNone(mist.price)          # no price line in panel
        # rule (2): the panel-TAIL badge ($1.30 after Add to cart) and
        # the badge under its own name ($7.20) both land on Mist
        self.assertIn("save $1.30", mist.special_desc)
        self.assertIn("save $7.20", mist.special_desc)

        lotion = _one("Lotion Bottle")
        self.assertIsNone(lotion.price)
        self.assertFalse(lotion.is_special)


class TestDocxSpecialsSection(unittest.TestCase):
    def _item(self, name, price, desc=""):
        return ProductItem(store="woolworths", raw_name=name,
                           price=price, is_special=bool(desc),
                           special_desc=desc)

    def test_groups_discounted_and_multibuy(self):
        out = render_docx_specials_section([
            self._item("Choc Biscuits 200g", 4.0, "2 for $7.00"),
            self._item("Yoghurt Pouch 150g", 1.9,
                       "save $1.30 (41% off)"),
            self._item("Strawberries 250g", 3.0),
            self._item("Mist Toner 120mL", None, "save $7.20"),
        ])
        self.assertIn("📦 MULTI-BUY DEALS", out)
        self.assertIn("💰 DISCOUNTED", out)
        self.assertIn("ALSO ON YOUR LIST", out)
        # grouping is per deal type
        self.assertLess(out.index("2 for $7.00"),
                        out.index("save $1.30"))
        self.assertIn("Strawberries 250g — $3.00", out)
        self.assertIn("no price shown", out)

    def test_empty_items_no_section(self):
        self.assertEqual(render_docx_specials_section([]), "")


if __name__ == "__main__":
    unittest.main()
