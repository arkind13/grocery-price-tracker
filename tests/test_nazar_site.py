"""Nazar Butchery site shop (2026-09-12): ONE permanent column (the
site has no specials), strict unit-aware catalogue reuse (same item
reuses its row; a NEW row only when the item is 100% not found),
per-100g conversion, duplicate-listing dedupe, and the layout
migration. Offline (fake worksheets; no network, no real sheet)."""
from __future__ import annotations
import io
import contextlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core import local_deals as ld                 # noqa: E402
from core.v2_read import lookup_item, parse_ld_row, \
    parse_master_row                               # noqa: E402
from tools.parity_audit import audit as audit_fn   # noqa: E402

LD_HEADER = ["Product"] + [n for _k, n in ld.TAB_COLUMNS]
MASTER_HEADER = ["Product_Name", "Category", "Size",
                 "Woolworths_Price", "Brand_Type", "Last_Updated",
                 "Search_Keyword_Woolworths", "Woolworths_Specials",
                 "Rewards_Points", "Keywords", "Sub_Category",
                 "Item_Code", "Preferred"]


class FakeWS:
    def __init__(self, rows):
        self.grid = [list(r) for r in rows]

    def get_all_values(self):
        return [list(r) for r in self.grid]

    def clear(self):
        pass

    def freeze(self, rows=0):
        pass

    def update(self, *, values, range_name=None, **_kw):
        self.grid = [list(r) for r in values]


def _cat(name, price, display_unit="", categories=(), price_range="",
         regular_price=None):
    """One normalised catalogue item (WC minor-unit prices)."""
    return {"name": name, "price": price,
            "regular_price": regular_price or price,
            "categories": list(categories), "unit": "",
            "display_unit": display_unit,
            "price_range": price_range}


def _sheet():
    """An aligned master+LD pair with one reusable lamb-mince row."""
    master = [MASTER_HEADER]
    m = [""] * 13
    m[0], m[10], m[11] = "Halal Lamb Mince /kg", "butchery", "LAM1"
    master.append(m)
    ld = [LD_HEADER,
          ["Halal Lamb Mince /kg", "", "", "", "", "", "", "", "",
           "", "", "", "LAM1"]]
    return FakeWS(master), FakeWS(ld)


# --- strict reuse matcher -------------------------------------------------
class TestSiteReuseMatch(unittest.TestCase):
    GRID = [
        ["Product"] + [n for _k, n in ld.TAB_COLUMNS],
        ["Halal Lamb Mince /kg", "", "", "", "", "", "", "", "",
         "", "", "", "LAM1"],
        ["Halal Beef Osso Bucco /kg", "", "", "", "", "", "", "",
         "", "", "", "", "OBB1"],
        ["Halal Whole chicken s14 /ea", "", "", "", "", "", "", "",
         "", "", "", "", "WC14"],
        ["Halal Lamb Shank – each /ea", "", "", "", "", "", "", "",
         "", "", "", "", "LSH1"],
        ["Lebanese Bread /ea", "", "", "", "", "", "", "", "",
         "", "", "", "LBR1"],
    ]

    def _match(self, name):
        return ld._site_reuse_match(self.GRID, name)

    def test_unit_kind_gates_everything(self):
        # a per-kg price NEVER enters a /ea row (unit gate)
        self.assertEqual(self._match("Halal Whole Chicken /kg"), None)
        # ...and a per-item price never enters a /kg row
        self.assertEqual(self._match("Halal Lamb Mince /ea"), None)

    def test_exact_and_plural_reuse(self):
        self.assertEqual(self._match("Halal Lamb Mince /kg"), 1)
        self.assertEqual(self._match("Halal Lamb Mince /kg"), 1)

    def test_species_word_containment(self):
        # 'Osso Bucco' reuses 'Halal Beef Osso Bucco /kg' — the
        # missing species word is not a different product
        self.assertEqual(self._match("Halal Osso Bucco /kg"), 2)

    def test_descriptor_drift_never_reuses(self):
        # 'Seekh Kebab (lamb mince marinated ...)' contains 'lamb
        # mince' but IS a different product — new row, always
        self.assertEqual(self._match(
            "Halal Seekh Kebab (lamb mince marinated in spices) /kg"),
            None)
        # 'Beef Best Mince' is a different grade from 'Beef Mince'
        self.assertEqual(self._match("Halal Beef Best Mince /kg"),
                         None)

    def test_style_words_never_split_or_merge(self):
        # 'bbq'/'whole'/size-codes are style: 'Blade Steak' reuses
        # a 'BBQ Blade Steak' row; 'Whole Chicken' reuses the s14 row
        grid = list(self.GRID) + [
            ["Halal BBQ Blade Steak /kg", "", "", "", "", "", "", "",
             "", "", "", "", "BBS1"]]
        self.assertEqual(
            ld._site_reuse_match(grid, "Halal Blade Steak /kg"), 6)
        self.assertEqual(
            self._match("Halal Whole Chicken /ea"), 3)

    def test_pack_sizes_stay_separate(self):
        grid = list(self.GRID) + [
            ["Halal Lamb Leg /kg", "", "", "", "", "", "", "", "",
             "", "", "", "LLG1"]]
        self.assertEqual(
            ld._site_reuse_match(grid, "Halal Lamb Leg (3kg) /ea"),
            None)

    def test_bare_rows_only_take_bare_items(self):
        grid = list(self.GRID) + [
            ["Halal Whole Lamb", "", "", "", "", "", "", "", "",
             "", "", "", "WLM1"]]
        # a per-item price MAY fill a bare row (same pack semantics)
        self.assertEqual(
            ld._site_reuse_match(grid, "Halal Whole Lamb /ea"), 6)
        self.assertEqual(
            ld._site_reuse_match(grid, "Halal Whole Lamb"), 6)
        # ...but a bare row never takes a /kg price, and a bare item
        # never enters a /kg row
        self.assertEqual(
            ld._site_reuse_match(grid, "Halal Whole Lamb /kg"), None)


# --- layout migration -----------------------------------------------------
class TestEnsureShopColumns(unittest.TestCase):
    def test_splices_missing_nazar_column_in_order(self):
        old_header = ["Product", "Dunya perm (site)",
                      "Dunya special (FB)", "Merjan perm",
                      "Merjan special", "Fruitopia perm",
                      "Fruitopia special", "Abu Salim perm",
                      "Abu Salim special", "Comments", "Item_Code"]
        ws = FakeWS([old_header,
                     ["Halal Lamb Mince /kg", "13.99", "", "", "", "",
                      "", "", "", "", "XJA"]])
        self.assertTrue(ld.ensure_shop_columns(ws))
        self.assertEqual(ws.grid[0],
                         ["Product"] + [n for _k, n in ld.TAB_COLUMNS])
        self.assertEqual(ws.grid[0][1], "Category")
        self.assertEqual(ws.grid[0][10], "Nazar perm")
        # existing data kept its column meaning: all shop cells +2
        self.assertEqual(ws.grid[1][2], "13.99")
        self.assertEqual(ws.grid[1][12], "XJA")

    def test_idempotent(self):
        ws = FakeWS([LD_HEADER])
        self.assertFalse(ld.ensure_shop_columns(ws))

    def test_unknown_column_aborts(self):
        ws = FakeWS([["Product", "Mystery", "Comments"]])
        with self.assertRaises(RuntimeError):
            ld.ensure_shop_columns(ws)

    def test_no_header_grid_is_left_alone(self):
        ws = FakeWS([["FRUITS"] + [""] * 9])
        self.assertFalse(ld.ensure_shop_columns(ws))
        self.assertEqual(ws.grid[0][0], "FRUITS")


# --- the sync itself ------------------------------------------------------
class TestSyncNazarSite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _run(self, catalogue, dry_run=False):
        master, ldtab = _sheet()
        sent = []

        def _fake_send(bot_token, chat_id, text, **_kw):
            sent.append(text)
            return {"ok": True}

        with patch("extractors.shop_site_catalogue."
                   "get_normalised_catalogue",
                   return_value=catalogue), \
             patch("core.sheets_client.connect_spreadsheet",
                   return_value=type("SS", (), {
                       "worksheet": lambda self, t: ldtab})()), \
             patch("core.sheets_client.connect_worksheet",
                   return_value=master), \
             patch("core.sheets_client._load_env", lambda: None), \
             patch("core.local_deals._send_message", _fake_send):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = ld.sync_nazar_site(dry_run=dry_run)
        return rc, master, ldtab, sent, buf.getvalue()

    def test_reuse_writes_perm_column(self):
        cat = [_cat("Lamb Mince", 1990, "per kg", ["Lamb"])]
        rc, master, ldtab, _sent, _out = self._run(cat)
        self.assertEqual(rc, 0)
        self.assertEqual(ldtab.grid[1][10], 19.9)   # Nazar perm col
        self.assertEqual(len(ldtab.grid), 2)       # NO new row
        self.assertEqual(master.grid[1][3], "")    # master untouched

    def test_new_row_appends_and_mirrors(self):
        cat = [_cat("Lamb Mince", 1990, "per kg", ["Lamb"]),
               _cat("Kusbasi (boneless lamb shoulder diced small)",
                    3690, "per kg", ["Lamb"])]
        rc, master, ldtab, _sent, _out = self._run(cat)
        self.assertEqual(rc, 0)
        self.assertEqual(ldtab.grid[1][10], 19.9)
        self.assertEqual(ldtab.grid[2][0],
                         "Halal Kusbasi (boneless lamb shoulder "
                         "diced small) /kg")
        self.assertEqual(ldtab.grid[2][10], 36.9)
        code = ldtab.grid[2][12]
        self.assertTrue(code and len(code) == 3)   # fresh Item_Code
        # master mirror: blank price + keyword, butchery sub-category
        self.assertEqual(master.grid[2][0],
                         ldtab.grid[2][0])
        self.assertEqual(master.grid[2][11], code)
        self.assertEqual(master.grid[2][3], "")
        self.assertEqual(master.grid[2][6], "")
        self.assertEqual(master.grid[2][10], "butchery")
        self.assertEqual(
            audit_fn(master.grid, ldtab.grid)["status"], "aligned")

    def test_per_100g_becomes_per_kg_with_note(self):
        cat = [_cat("Turkey (Spicy)", 500, "per 100g", ["Deli"])]
        rc, _master, ldtab, _sent, _out = self._run(cat)
        self.assertEqual(rc, 0)
        self.assertEqual(ldtab.grid[2][0], "Halal Turkey (Spicy) /kg")
        self.assertEqual(ldtab.grid[2][10], 50.0)   # $5/100g = $50/kg
        self.assertIn("site price per 100g",
                      str(ldtab.grid[2][11]))

    def test_price_range_noted(self):
        cat = [_cat("Whole Chicken", 1290, "per item", ["Chicken"],
                    price_range="12.90-14.90")]
        rc, _master, ldtab, _sent, _out = self._run(cat)
        self.assertEqual(ldtab.grid[2][10], 12.9)
        self.assertIn("12.90-14.90", str(ldtab.grid[2][11]))

    def test_duplicate_listing_keeps_categorised(self):
        cat = [_cat("Lamb Mince", 1690, "per kg", []),        # stray
               _cat("Lamb Mince", 1990, "per kg", ["Lamb"])]  # canon
        rc, _master, ldtab, _sent, out = self._run(cat)
        self.assertEqual(ldtab.grid[1][10], 19.9)   # canonical wins
        self.assertEqual(len(ldtab.grid), 2)
        self.assertIn("duplicate", out)

    def test_quote_only_items_skipped(self):
        cat = [_cat("Whole Round", 0, "", ["Specials"]),
               _cat("Lamb Mince", 1990, "per kg", ["Lamb"])]
        rc, _master, ldtab, _sent, out = self._run(cat)
        self.assertEqual(rc, 0)
        self.assertEqual(len(ldtab.grid), 2)
        self.assertIn("Whole Round", out)

    def test_dry_run_writes_nothing(self):
        cat = [_cat("Lamb Mince", 1990, "per kg", ["Lamb"]),
               _cat("Kusbasi", 3690, "per kg", ["Lamb"])]
        rc, master, ldtab, sent, out = self._run(cat, dry_run=True)
        self.assertEqual(rc, 0)
        self.assertEqual(sent, [])                 # no telegram
        self.assertEqual(ldtab.grid[1][9], "")     # sheet untouched
        self.assertEqual(len(master.grid), 2)
        self.assertIn("reuse existing rows: 1", out)
        self.assertIn("NEW rows: 1", out)


# --- read path: lookups include Nazar -------------------------------------
class TestNazarReadPath(unittest.TestCase):
    def test_parse_ld_row_reads_nazar_column(self):
        row = ["Halal Lamb Mince /kg", "", "", "", "", "", "", "",
               "", "", 19.9, "", "LAM1"]
        parsed = parse_ld_row(2, row)
        self.assertEqual(parsed["prices"]["nazar"],
                         (19.9, "permanent"))

    def test_lookup_winner_includes_nazar(self):
        master = [parse_master_row(2, [
            "Halal Lamb Mince /kg", "", "", "", "", "", "", "", "",
            "", "butchery", "LAM1", ""])]
        ld_row = parse_ld_row(2, [
            "Halal Lamb Mince /kg", "", "", "", "", "", "", "",
            "", "", 19.9, "", "LAM1"])
        result = lookup_item("halal lamb mince", master, [ld_row])
        # a /kg-named row answers via the halal locals pool (§8)
        self.assertEqual(result["status"], "meat-local-only")
        self.assertIn("nazar", result["local"])
        self.assertEqual(result["best"][0], "nazar")

    def test_expiry_sweep_never_touches_perm_only_shop(self):
        ws = FakeWS([LD_HEADER,
                     ["Halal Lamb Mince /kg", "", "", "", "", "", "",
                      "", "", 19.9, "", "LAM1"]])
        lines = ld.sweep_expired_specials(
            ws, today=__import__("datetime").date(2026, 9, 12))
        self.assertEqual(lines, [])
        self.assertEqual(ws.grid[1][9], 19.9)      # perm survives

    def test_grid_range_is_full_width(self):
        self.assertEqual(ld.grid_range(6), "A1:M6")

    def test_target_column_is_perm(self):
        col, kind = ld._target_column("nazar")
        self.assertEqual((col, kind), (10, "perm"))


if __name__ == "__main__":
    unittest.main()
