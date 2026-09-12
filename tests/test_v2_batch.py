"""T-set 2 — the `batch` engine (spec §4/§7): every verdict on
FakeSheet pairs, archive-before-delete, unknown-code isolation,
ignored exclusion, post-batch audit ALIGNED, mixed-verdict ordering.
Offline (fake worksheets + tmp state files; no network, no sheet)."""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core.v2_batch import (                       # noqa: E402
    apply_verdicts, parse_verdicts,
)
from core.v2_read import lookup_item, missing_list, parse_ld_row, \
    parse_master_row                              # noqa: E402
from tools.parity_audit import audit as audit_fn  # noqa: E402

MASTER_HEADER = ["Product_Name", "Category", "Size",
                 "Woolworths_Price", "Brand_Type", "Last_Updated",
                 "Search_Keyword_Woolworths", "Woolworths_Specials",
                 "Rewards_Points", "Keywords", "Sub_Category",
                 "Item_Code", "Preferred"]


def _master_row(name, code, ww="", keyword=""):
    row = [""] * 13
    row[0], row[3], row[6], row[10], row[11] = (
        name, ww, keyword, "butchery", code)
    return row


class FakeWS:
    """Minimal gspread worksheet double (values + clear + update)."""

    def __init__(self, rows):
        self._values = [list(r) for r in rows]
        self.clears = 0
        self.updates = []

    def get_all_values(self):
        return [list(r) for r in self._values]

    def clear(self):
        self.clears += 1

    def freeze(self, rows=0):
        pass

    def update(self, *, values, range_name):
        self.updates.append(range_name)
        self._values = [list(r) for r in values]


def _fixture():
    """Aligned pair: master order == LD item order (audit pairing).

    Master: Tomato (priced), Halal Beef Mince (missing-list),
    Halal Lamb Shoulder (missing-list).
    """
    master = [MASTER_HEADER,
              _master_row("Tomato", "EYF", ww="$0.54",
                          keyword="woolworths tomato"),
              _master_row("Halal Beef Mince 500g", "AUG"),
              _master_row("Halal Lamb Shoulder", "HLS")]
    ld = [["Product", "", "", "", "", "", "", "", "", "", "", ""],
          ["Prices valid until", "n/a (live site)", "", "", "", "",
           "", "", "", "", "", ""],
          ["FRUITS"] + [""] * 11,
          ["Tomato", "", "", "", "", "0.90", "", "", "", "", "",
           "EYF"],
          ["BUTCHERY"] + [""] * 11,
          ["Halal Beef Mince 500g", "", "9.20", "", "", "", "", "",
           "", "", "", "AUG"],
          ["Halal Lamb Shoulder", "12.99", "", "", "", "", "", "",
           "", "", "", "HLS"]]
    return FakeWS(master), FakeWS(ld)


class TestParseVerdicts(unittest.TestCase):
    def test_mixed_parse(self):
        verdicts = parse_verdicts(
            "ABC done; DEF gone; GHI rename halal lamb shoulder; "
            "JKL remove; MNO ignore")
        self.assertEqual(verdicts, [
            {"code": "ABC", "verb": "done", "arg": ""},
            {"code": "DEF", "verb": "gone", "arg": ""},
            {"code": "GHI", "verb": "rename",
             "arg": "halal lamb shoulder"},
            {"code": "JKL", "verb": "remove", "arg": ""},
            {"code": "MNO", "verb": "ignore", "arg": ""},
        ])

    def test_unknown_verb_and_bare_rename(self):
        verdicts = parse_verdicts("ABC frobnicate; JKL rename; "
                                  "MNO gone")
        self.assertEqual(verdicts[0]["verb"], "?")
        self.assertEqual(verdicts[1]["verb"], "?")
        self.assertEqual(verdicts[2]["verb"], "gone")

    def test_empty_tokens_skipped(self):
        self.assertEqual(parse_verdicts("  ; ABC done ; "),
                         [{"code": "ABC", "verb": "done", "arg": ""}])


class TestVerdicts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.master, self.ld = _fixture()
        self.archive = Path(self.tmp.name) / "deleted_rows.json"
        self.ignored = Path(self.tmp.name) / "ignored_items.txt"

    def _run(self, text):
        return apply_verdicts(
            parse_verdicts(text), master_ws=self.master,
            ld_ws=self.ld, archive_path=self.archive,
            ignored_path=self.ignored, audit_fn=audit_fn)

    def test_done_verify_only_writes_nothing(self):
        replies = self._run("AUG done")
        self.assertEqual(replies, ["[AUG] ✗ not done — still blank: "
                                   "Woolworths price (col D) and "
                                   "search keyword (col G)"])
        self.assertEqual(self.master.clears, 0)
        self.assertEqual(self.ld.clears, 0)
        self.assertEqual(self.master.updates, [])

    def test_done_success_when_price_and_keyword_present(self):
        self.master._values[1][3] = "$0.60"          # Tomato priced
        replies = self._run("EYF done")
        self.assertEqual(replies, ["[EYF] ✓ done — off the list"])

    def test_done_names_only_the_blank_side(self):
        self.master._values[3][6] = "woolworths lamb shoulder"
        replies = self._run("HLS done")
        self.assertEqual(replies, ["[HLS] ✗ not done — still blank: "
                                   "Woolworths price (col D)"])

    def test_gone_stamps_master_d_row_kept(self):
        replies = self._run("HLS gone")
        self.assertEqual(replies, ["[HLS] ✓ marked GONE at "
                                   "Woolworths (row kept)"])
        self.assertEqual(self.master._values[3][3], "GONE")
        # row kept everywhere: same counts, LD price cell untouched
        self.assertEqual(len(self.master._values), 4)
        self.assertEqual(len(self.ld._values), 7)
        self.assertEqual(self.ld._values[6][0],
                         "Halal Lamb Shoulder")

    def test_rename_lands_on_both_tabs(self):
        replies = self._run("AUG rename halal lamb shoulder")
        self.assertIn("✓ renamed", replies[0])
        self.assertEqual(self.master._values[2][0],
                         "halal lamb shoulder")
        self.assertEqual(self.ld._values[5][0],
                         "halal lamb shoulder")
        self.assertEqual(self.master._values[2][11], "AUG")
        self.assertEqual(self.ld._values[5][2], "9.20")

    def test_remove_archives_before_deleting(self):
        replies = self._run("AUG remove")
        self.assertEqual(replies, ["[AUG] ✓ removed (archived to "
                                   "deleted_rows.json; both tabs)"])
        entries = json.loads(self.archive.read_text(
            encoding="utf-8"))
        self.assertEqual([e["side"] for e in entries],
                         ["master", "local_deals"])
        self.assertEqual(entries[0]["code"], "AUG")
        self.assertEqual(entries[0]["source"], "v2-batch-remove")
        self.assertEqual(entries[0]["row"][0],
                         "Halal Beef Mince 500g")
        self.assertEqual(entries[1]["row"][11], "AUG")
        codes = [r[11] for r in self.master._values[1:]]
        self.assertEqual(codes, ["EYF", "HLS"])
        self.assertEqual([r[0] for r in self.ld._values[1:]],
                         ["Prices valid until", "FRUITS", "Tomato",
                          "BUTCHERY", "Halal Lamb Shoulder"])

    def test_ignore_appends_line_and_hides_from_list(self):
        replies = self._run("AUG ignore")
        self.assertIn("✓ ignored", replies[0])
        self.assertEqual(self.ignored.read_text(
            encoding="utf-8").strip(), "[AUG] Halal Beef Mince 500g")
        master = [m for m in (parse_master_row(i, r)
                  for i, r in enumerate(self.master._values[1:], 2))
                  if m]
        ld = [l for l in (parse_ld_row(i, r)
              for i, r in enumerate(self.ld._values)) if l]
        items = missing_list(master, ld,
                             ignored_path=self.ignored)
        self.assertEqual([i["code"] for i in items], ["HLS"])

    def test_unknown_code_isolated(self):
        replies = self._run("ZZZ gone; AUG gone")
        self.assertEqual(replies[0], "[ZZZ] ✗ unknown code")
        self.assertEqual(replies[1], "[AUG] ✓ marked GONE at "
                                     "Woolworths (row kept)")
        self.assertEqual(self.master._values[2][3], "GONE")

    def test_unknown_verb_reply(self):
        replies = self._run("AUG frobnicate")
        self.assertEqual(replies, ["[AUG] ✗ unknown verdict"])

    def test_post_batch_audit_aligned_and_single_write(self):
        self._run("HLS gone; AUG ignore")
        self.assertEqual(self.master.clears, 1)
        self.assertEqual(self.master.updates, ["A1:M4"])
        # gone + ignore write NO LD cells — the LD tab stays untouched
        self.assertEqual(self.ld.clears, 0)
        self.assertEqual(self.ld.updates, [])
        result = audit_fn(self.master._values, self.ld._values)
        self.assertEqual(result["status"], "aligned")

    def test_remove_removes_audits_aligned(self):
        self._run("AUG remove")
        result = audit_fn(self.master._values, self.ld._values)
        self.assertEqual(result["status"], "aligned")

    def test_mixed_run_single_call_reply_order(self):
        replies = self._run("EYF done; HLS gone; AUG remove; "
                            "ZZZ done; EYF done")
        self.assertEqual([r.split("]")[0] + "]" for r in replies],
                         ["[EYF]", "[HLS]", "[AUG]", "[ZZZ]",
                          "[EYF]"])
        self.assertEqual(replies[0], "[EYF] ✓ done — off the list")
        self.assertEqual(replies[4], "[EYF] ✓ done — off the list")

    def test_lookup_still_answers_after_batch(self):
        self._run("HLS gone")
        master = [m for m in (parse_master_row(i, r)
                  for i, r in enumerate(self.master._values[1:], 2))
                  if m]
        ld = [l for l in (parse_ld_row(i, r)
              for i, r in enumerate(self.ld._values)) if l]
        result = lookup_item("halal lamb shoulder", master, ld)
        self.assertEqual(result["status"], "gone")
        self.assertTrue(result["local"])


if __name__ == "__main__":
    unittest.main()
