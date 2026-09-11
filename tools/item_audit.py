"""Sheet item audit — tests EVERY item on Products_Master, one by one.

For each master item this tool:
  1. runs the v2 lookup with the item's own name as the query,
  2. derives the EXPECTED answer class from the row's own state (§8
     semantics: tracked / gone / na / missing / not-tracked /
     out-of-domain),
  3. compares expected vs actual and records EVERYTHING to
     item_audit.csv (item, code, row, expected, actual, verdict,
     rendered reply) for the interpretation session.

Usage (from the tracker root):
  anaconda3/python.exe tools/item_audit.py                 # all items
  anaconda3/python.exe tools/item_audit.py --items "Halal Lamb Mince /kg, …"
                                                  # re-run failures only

READ-ONLY: this tool never writes to the sheet.
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.v2_read import (lookup_item, parse_ld_row, parse_master_row,
                          read_tabs)  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "test_logs"


def expected_class(m: dict, ld_by_code: dict) -> str:
    """§8 semantics derived from the row's own state."""
    if m["gone"]:
        return "gone"
    if m["na_marker"]:
        return "na"
    if m["ww_num"] is not None:
        return "tracked"
    pair = ld_by_code.get(m["code"])
    if pair and pair["prices"]:
        return "missing"          # local has it, Wool side blank
    return "not-tracked"


def meat_query(name: str) -> bool:
    from core.halal import is_meat_term
    return is_meat_term(name)


def twin_expected(name: str, m_rows: list[dict]) -> bool:
    """A4: a meat query shows the non-halal twin line whenever a plain
    (non-halal) meat master row shares a content token with the
    query."""
    from core.halal import is_meat_term
    if not is_meat_term(name):
        return False
    qtoks = {t for t in name.lower().split()
             if t not in ("halal", "and", "vs")}
    for r in m_rows:
        n = str(r["name"]).lower()
        if "halal" in n:
            continue
        if not is_meat_term(n):
            continue
        if qtoks & (set(n.split()) - {"each", "500g", "1kg"}):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", default="",
                    help="comma-separated item names to re-test "
                         "(default: every master item)")
    args = ap.parse_args()

    from core.sheets_client import connect_spreadsheet
    sh = connect_spreadsheet()
    master, ld = read_tabs()
    ld_by_code = {r["code"]: r for r in ld
                  if r.get("code")}

    wanted = None
    if args.items.strip():
        wanted = [s.strip().lower() for s in args.items.split(",")
                  if s.strip()]

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    out_csv = OUT / f"item_audit_{stamp}.csv"
    out_txt = OUT / f"item_audit_{stamp}_replies.txt"
    rows: list[dict] = []
    replies: list[str] = []

    for m in master:
        name = m["name"]
        if wanted and not any(w in name.lower() or
                              name.lower() in w for w in wanted):
            continue
        exp = expected_class(m, ld_by_code)
        result = lookup_item(name, master, ld)
        actual = result["status"]
        text = render_for(result)
        verdict = judge(name, exp, actual, text, master)
        rows.append({"item": name, "code": m.get("code", ""),
                     "row": m.get("row", ""), "query": name,
                     "expected": exp, "actual": actual,
                     "verdict": verdict, "render": text})
        replies.append(f"### {name} [{m.get('code','')}] "
                       f"expected={exp} actual={actual} {verdict}\n"
                       + text + "\n")

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["item", "code", "row",
                                          "query", "expected",
                                          "actual", "verdict",
                                          "render"])
        w.writeheader()
        w.writerows(rows)
    out_txt.write_text("\n".join(replies), encoding="utf-8")

    fails = [r for r in rows if r["verdict"] == "FAIL"]
    print(f"items tested: {len(rows)} | PASS: {len(rows)-len(fails)} "
          f"| FAIL: {len(fails)}")
    for r in fails[:25]:
        print(f"  FAIL: {r['item'][:44]} expected={r['expected']} "
              f"actual={r['actual']}")
    print(f"evidence: {out_csv.name} + {out_txt.name}")
    return 0


MEAT_STATUSES = {"meat-local-only", "tracked", "missing", "gone",
                 "na"}


def judge(name: str, exp: str, actual: str, text: str,
          m_rows: list) -> str:
    """§8 + A4 judging: meat queries are judged on CONTENT (locals +
    missing-list code + the non-halal twin line when a plain row
    exists), not on a single status token."""
    if meat_query(name):
        problems = []
        if "missing list [" not in text and exp in ("tracked",):
            problems.append("no missing-list line")
        if twin_expected(name, m_rows) and                 "also at Woolworths (non-halal)" not in text:
            problems.append("twin line missing")
        if problems:
            return "FAIL: " + "; ".join(problems)
        return "PASS"
    if exp != actual:
        return f"FAIL: expected {exp}, got {actual}"
    return "PASS"


def render_for(result: dict) -> str:
    from core.v2_read import render_lookup
    try:
        return render_lookup(result)
    except Exception as exc:                     # noqa: BLE001
        return f"RENDER ERROR: {exc}"


if __name__ == "__main__":
    raise SystemExit(main())
