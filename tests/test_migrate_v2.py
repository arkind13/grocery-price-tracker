"""S1/S10.1 — v2 migration tool: pure helpers + apply-* idempotence
on a FakeSpreadsheet. No network."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core.item_codes import is_valid_code          # noqa: E402
from tools.migrate_v2 import (                      # noqa: E402
    NEW_MASTER_HEADERS, apply_columns, apply_parity,
    apply_stay_leave, blank_master_row, build_archive_grid,
    build_parity_plan, drop_columns, align_grids, ld_row_code_map,
    plan_halal_renames, plan_new_master_rows, stay_leave,
)
from tools.parity_audit import audit               # noqa: E402

MASTER_HEADER_19 = [
    "Product_Name", "Category", "Size", "Woolworths_Price",
    "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
    "Search_Keyword_Woolworths", "Search_Keyword_Coles",
    "Search_Keyword_Aldi", "Aldi Refresh", "Woolworths_Specials",
    "Coles_Specials", "Rewards_Points", "Keywords", "Sub_Category",
    "Item_Code", "Preferred",
]
LD_HEADER_10 = ["Product", "Dunya perm (site)", "Dunya special (FB)",
                "Merjan perm", "Merjan special", "Fruitopia perm",
                "Fruitopia special", "Abu Salim perm",
                "Abu Salim special", "Comments"]


def _mrow19(name, code, sub=""):
    row = [""] * 19
    row[0], row[16], row[17] = name, sub, code
    return row


def master19():
    """Keep / borderline / leave / blank-subcategory coverage."""
    rows = [MASTER_HEADER_19]
    data = [
        ("Apples Royal Gala", "AP1", "apples"),    # KEEP
        ("Tomato", "TM1", "tomato"),               # KEEP
        ("Beef Mince 500g", "BM1", "beef mince"),  # KEEP (butchery)
        ("Lettuce Cos", "LT1", "lettuce"),         # BORDERLINE
        ("Coriander Bunch", "CR1", "coriander"),   # BORDERLINE
        ("Greek Salad A", "GS1", "greek salad"),
        ("Greek Salad B", "GS2", "greek salad"),
        ("Crackers Box", "PY1", "crackers"),       # LEAVE
        ("Misc NoSub", "NS1", ""),                 # blank sub -> LEAVE
    ]
    for name, code, sub in data:
        rows.append(_mrow19(name, code, sub))
    return rows


def ld10():
    rows = [LD_HEADER_10, ["Prices valid until"] + [""] * 9]
    rows.append(["BUTCHERY"] + [""] * 9)
    rows.append(["BEEF MINCE (5KG) /ea", "64.99"] + [""] * 8)
    rows.append(["Whole chicken /ea"] + [""] * 9)
    rows.append(["Halal Sausages /kg"] + [""] * 9)   # already prefixed
    rows.append(["FRUITS"] + [""] * 9)
    rows.append(["Tomatoes /kg", "", "3.99"] + [""] * 7)
    rows.append(["Grapes /ea"] + [""] * 9)
    return rows


def master13_keeps():
    """Post-G1/G2 master: the two keep rows matched by the LD grid
    plus one Wool-only row (no LD counterpart)."""
    rows = [list(NEW_MASTER_HEADERS)]
    rows.append(_mrow13("Tomato", "TM1", "tomato"))
    rows.append(_mrow13("Apples Royal Gala", "AP1", "apples"))
    rows.append(_mrow13("Wool Only Peas", "WP1", ""))
    return rows


def _mrow13(name, code, sub="", price="", keyword=""):
    row = [""] * 13
    row[0], row[3], row[6], row[10], row[11] = (
        name, price, keyword, sub, code)
    return row


class FakeWorksheet:
    """gspread Worksheet stand-in recording every write."""

    def __init__(self, title, rows=None):
        self.title = title
        self.rows = [list(r) for r in (rows or [])]
        self.updates: list = []
        self.batch: list = []
        self.clear_calls = 0
        self.delete_row_calls: list = []
        self.delete_col_calls: list = []
        self.frozen = None

    @property
    def col_count(self):
        return max((len(r) for r in self.rows), default=1)

    def add_cols(self, n):
        for row in self.rows:
            row.extend([""] * n)

    def get_all_values(self):
        return [list(r) for r in self.rows]

    def clear(self):
        self.clear_calls += 1
        self.rows = []

    def freeze(self, rows=None, cols=None):
        self.frozen = rows

    def update(self, values=None, range_name=None, **_kw):
        self.updates.append((values, range_name))
        self.rows = [list(r) for r in values]

    def batch_update(self, data, **_kw):
        self.batch.append(list(data))
        for cell in data:
            row = self._row_by_number(int(cell["range"][1:]))
            row[0] = cell["values"][0][0]

    def delete_rows(self, index):
        self.delete_row_calls.append(index)
        del self.rows[index - 1]

    def delete_columns(self, index):
        self.delete_col_calls.append(index)
        for row in self.rows:
            if len(row) >= index:
                del row[index - 1]

    def _row_by_number(self, sheet_row):
        return self.rows[sheet_row - 1]


class FakeSpreadsheet:
    def __init__(self, sheets):
        self.sheets = list(sheets)
        self.id = "fake-sheet-id"

    def worksheet(self, title):
        for ws in self.sheets:
            if ws.title == title:
                return ws
        raise KeyError(title)

    def add_worksheet(self, title, rows=100, cols=26):
        ws = FakeWorksheet(title)
        self.sheets.append(ws)
        return ws


class TestStayLeave(unittest.TestCase):
    def test_classification_incl_borderline_and_blank(self):
        result = stay_leave(master19())
        self.assertEqual([e["name"] for e in result["keep"]],
                         ["Apples Royal Gala", "Tomato",
                          "Beef Mince 500g"])
        self.assertEqual([e["name"] for e in result["borderline"]],
                         ["Lettuce Cos", "Coriander Bunch",
                          "Greek Salad A", "Greek Salad B"])
        self.assertEqual([e["name"] for e in result["leave"]],
                         ["Crackers Box", "Misc NoSub"])
        for e in result["keep"] + result["borderline"] \
                + result["leave"]:
            self.assertIn("row", e)
            self.assertIn("code", e)
            self.assertIn("sub_category", e)

    def test_rejects_non_19_col_grid(self):
        with self.assertRaises(ValueError):
            stay_leave([list(NEW_MASTER_HEADERS)])


class TestArchiveGrid(unittest.TestCase):
    def test_verbatim_full_copy(self):
        grid = master19()
        out = build_archive_grid(grid)
        self.assertEqual(len(out), len(grid))
        self.assertEqual(out[0], MASTER_HEADER_19)
        self.assertEqual(out, [list(r) for r in grid])
        self.assertTrue(all(len(r) == 19 for r in out))


class TestDropColumns(unittest.TestCase):
    def test_exact_header_and_value_positions(self):
        grid = master19()
        grid[1][3] = "$4.50"            # D  ww price   -> stays 3
        grid[1][6] = "Home"             # G  brand      -> 4
        grid[1][7] = "2026-09-09"       # H  updated    -> 5
        grid[1][8] = "kw wool"          # I  keyword    -> 6
        grid[1][12] = "Half Price"      # M  specials   -> 7
        grid[1][14] = "100"             # O  rewards    -> 8
        grid[1][15] = "alias"           # P  keywords   -> 9
        grid[1][16] = "apples"          # Q  sub        -> 10
        grid[1][17] = "AP1"             # R  code       -> 11
        out = drop_columns(grid)
        self.assertEqual(out[0], NEW_MASTER_HEADERS)
        row = out[1]
        self.assertEqual(row[3], "$4.50")
        self.assertEqual(row[4], "Home")
        self.assertEqual(row[5], "2026-09-09")
        self.assertEqual(row[6], "kw wool")
        self.assertEqual(row[7], "Half Price")
        self.assertEqual(row[8], "100")
        self.assertEqual(row[9], "alias")
        self.assertEqual(row[10], "apples")
        self.assertEqual(row[11], "AP1")
        self.assertEqual(len(row), 13)

    def test_raises_without_writes_on_mismatch(self):
        bad = [["Wrong"] + [""] * 18]
        with self.assertRaises(ValueError):
            drop_columns(bad)


class TestHalalRenames(unittest.TestCase):
    def test_butchery_only_and_case_insensitive(self):
        renames = plan_halal_renames(ld10())
        renamed = {old: new for _i, old, new in renames}
        self.assertEqual(renamed,
                         {"BEEF MINCE (5KG) /ea":
                          "Halal BEEF MINCE (5KG) /ea",
                          "Whole chicken /ea":
                          "Halal Whole chicken /ea"})
        # the already-prefixed row and every FRUITS row untouched
        self.assertNotIn("Halal Sausages /kg", renamed)
        self.assertNotIn("Tomatoes /kg", renamed)
        self.assertNotIn("Grapes /ea", renamed)
        for idx, _old, _new in renames:
            self.assertIn(idx, (3, 4))   # the BUTCHERY item rows

    def test_apply_renames_idempotent(self):
        grid = ld10()
        renames = plan_halal_renames(grid)
        once = plan_halal_renames(_renamed_grid(grid, renames))
        self.assertEqual(once, [])


def _renamed_grid(grid, renames):
    out = [list(r) for r in grid]
    for idx, _old, new in renames:
        out[idx][0] = new
    return out


class TestNewMasterRows(unittest.TestCase):
    def test_prefix_rule_codes_and_matching(self):
        m13 = master13_keeps()
        planned = plan_new_master_rows(ld10(), m13)
        names = [p["name"] for p in planned]
        # 'Tomatoes' canonical-matches keep TM1 -> NOT planned
        self.assertNotIn("Tomatoes", names)
        # butchery rows get the prefix; fruit rows do not
        self.assertIn("Halal BEEF MINCE (5KG)", names)
        self.assertIn("Halal Whole chicken", names)
        self.assertIn("Halal Sausages", names)
        self.assertIn("Grapes", names)
        codes = [p["code"] for p in planned]
        self.assertEqual(len(codes), len(set(codes)))
        for code in codes:
            self.assertTrue(is_valid_code(code),
                            f"{code} not A-Z minus I/L/O x3")
        # matched pairing: Tomatoes carries the EXISTING TM1 code
        code_map = ld_row_code_map(ld10(), m13, planned)
        tomatoes_idx = 7               # ld10() grid index
        self.assertEqual(code_map[tomatoes_idx], ("TM1", "matched"))
        new_codes = {c for c, k in code_map.values() if k == "new"}
        self.assertEqual(new_codes, set(codes))

    def test_crash_resume_occurrence_pairing(self):
        """Canonical-equal LD rows pair by OCCURRENCE order with the
        master's appended twins — never first-hit aliasing (the Lamb
        Curry defect: both LD rows grabbed ZWX, orphaning ZGK)."""
        m13 = [list(NEW_MASTER_HEADERS),
               _mrow13("Halal Lamb Curry", "ZWX", "butchery"),
               _mrow13("Halal Lamb Curry", "ZGK", "butchery")]
        ld = [["Product"] + [""] * 9,
              ["Prices valid until"] + [""] * 9,
              ["BUTCHERY"] + [""] * 9,
              ["Halal Lamb Curry /kg", "17.99"] + [""] * 8,
              ["Halal Lamb Curry", "", "", "", "27.99"] + [""] * 5]
        planned = plan_new_master_rows(ld, m13)
        self.assertEqual(planned, [])      # both have master twins
        code_map = ld_row_code_map(ld, m13, planned)
        self.assertEqual(code_map[3], ("ZWX", "matched"))
        self.assertEqual(code_map[4], ("ZGK", "matched"))
        # alignment accepts the distinct pairing …
        ld11 = [list(r) + [""] * (11 - len(r)) for r in ld]
        ld11[0][10] = "Item_Code"
        for idx, (code, _k) in code_map.items():
            ld11[idx][10] = code
        master_out, ld_out = align_grids(
            m13 + [blank_master_row("Apples", "AP1", "fruit & veg")],
            ld11)
        codes = [r[11] for r in master_out[1:]]
        self.assertEqual(sorted(codes), ["AP1", "ZGK", "ZWX"])
        # … and REJECTS a duplicate-code grid loudly.
        ld11[4][10] = "ZWX"                # re-create the defect
        with self.assertRaises(ValueError):
            align_grids(m13, ld11)

    def test_every_code_unique_vs_master(self):
        m13 = master13_keeps()
        planned = plan_new_master_rows(ld10(), m13)
        existing = {"TM1", "AP1", "WP1"}
        for p in planned:
            self.assertNotIn(p["code"], existing)


class TestAlignGrids(unittest.TestCase):
    def test_counts_pairing_and_blank_mirror_shape(self):
        m13 = master13_keeps()
        plan = build_parity_plan(m13, ld10())
        master_out, ld_out = plan["master_final"], plan["ld_final"]
        ld_items = [r for i, r in enumerate(ld_out)
                    if i and r[0] not in ("BUTCHERY", "FRUITS",
                                          "OTHER")
                    and r[0] != "Prices valid until"]
        self.assertEqual(len(master_out) - 1, len(ld_items))
        # per-position code pairing
        for m, l in zip(master_out[1:], ld_items):
            self.assertEqual(m[11], l[10])
            self.assertTrue(m[11])
        # section titles preserved on the LD side only
        firsts = [r[0] for r in ld_out]
        self.assertIn("BUTCHERY", firsts)
        self.assertIn("FRUITS", firsts)
        for m in master_out[1:]:
            self.assertNotIn(m[0], ("BUTCHERY", "FRUITS", "OTHER"))
        # Wool-only rows mirrored by BLANK LD rows at the END
        self.assertEqual(ld_items[-1][0], "")
        self.assertEqual(ld_items[-1][10], "WP1")
        self.assertEqual(master_out[-1][0], "Wool Only Peas")

    def test_raises_on_unresolvable_ld_code(self):
        m13 = master13_keeps()
        ld = ld10()
        ld.append(["Ghost /ea"] + [""] * 9)
        with self.assertRaises(ValueError):
            align_grids(m13, ld)


class TestBlankMasterRow(unittest.TestCase):
    def test_name_code_subcategory_only(self):
        row = blank_master_row("Halal Wings", "HW1", "butchery")
        self.assertEqual(len(row), 13)
        self.assertEqual(row[0], "Halal Wings")
        self.assertEqual(row[10], "butchery")
        self.assertEqual(row[11], "HW1")
        self.assertEqual(row[3], "")    # D stays blank (spec §4.2)
        self.assertEqual(row[6], "")    # G stays blank


class TestApplyIdempotence(unittest.TestCase):
    def _spy(self, sheets):
        return {ws.title: [len(ws.updates), len(ws.batch),
                           len(ws.delete_row_calls),
                           len(ws.delete_col_calls),
                           ws.clear_calls]
                for ws in sheets}

    def test_apply_stay_leave_twice(self):
        sheets = [FakeWorksheet("Products_Master", master19())]
        sp = FakeSpreadsheet(sheets)
        self.assertEqual(apply_stay_leave(sp), 0)
        after = sp.worksheet("Products_Master").get_all_values()
        self.assertEqual(len(after), 1 + 3)     # header + 3 keeps
        archive = sp.worksheet("Archive")
        self.assertEqual(len(archive.get_all_values()), 10)
        spy = self._spy(sp.sheets)
        self.assertEqual(apply_stay_leave(sp), 0)
        self.assertEqual(self._spy(sp.sheets), spy)
        self.assertEqual(
            sp.worksheet("Products_Master").get_all_values(), after)

    def test_apply_stay_leave_user_ruling(self):
        sheets = [FakeWorksheet("Products_Master", master19())]
        sp = FakeSpreadsheet(sheets)
        rc = apply_stay_leave(sp, force_keep=["LT1", "GS1"],
                              force_leave=["AP1"])
        self.assertEqual(rc, 0)
        names = [r[0] for r in
                 sp.worksheet("Products_Master")
                 .get_all_values()[1:]]
        self.assertIn("Lettuce Cos", names)
        self.assertIn("Greek Salad A", names)
        self.assertNotIn("Apples Royal Gala", names)
        self.assertIn("Tomato", names)

    def test_apply_columns_twice(self):
        sheets = [FakeWorksheet("Products_Master", master19())]
        sp = FakeSpreadsheet(sheets)
        self.assertEqual(apply_columns(sp), 0)
        got = sp.worksheet("Products_Master").get_all_values()[0]
        self.assertEqual(got, NEW_MASTER_HEADERS)
        spy = self._spy(sp.sheets)
        self.assertEqual(apply_columns(sp), 0)
        self.assertEqual(self._spy(sp.sheets), spy)

    def test_apply_parity_twice_ends_aligned(self):
        sheets = [FakeWorksheet("Products_Master", master13_keeps()),
                  FakeWorksheet("Local_Deals", ld10())]
        sp = FakeSpreadsheet(sheets)
        self.assertEqual(apply_parity(sp), 0)
        result = audit(sp.worksheet("Products_Master")
                       .get_all_values(),
                       sp.worksheet("Local_Deals").get_all_values())
        self.assertEqual(result["status"], "aligned")
        spy = self._spy(sp.sheets)
        self.assertEqual(apply_parity(sp), 0)
        self.assertEqual(self._spy(sp.sheets), spy)
        # every LD item row carries a code
        for i, row in enumerate(sp.worksheet("Local_Deals")
                                .get_all_values()):
            if i and row[0] and row[0] not in ("BUTCHERY", "FRUITS",
                                               "OTHER") \
                    and row[0] != "Prices valid until":
                self.assertTrue(str(row[10]).strip(), f"row {i}")


if __name__ == "__main__":
    unittest.main()
