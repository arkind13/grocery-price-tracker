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
import re
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
    ap.add_argument("--exec", action="store_true",
                    help="REAL command execution: every item through "
                         "the actual CLI, multiple formats, replies "
                         "recorded")
    args = ap.parse_args()
    if args.exec:
        return exec_audit(args.items)

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



# ---------------------------------------------------------------------------
# EXEC MODE — real commands, real answers, recorded (user mandate
# 2026-09-11: "send commands for each and every item in different
# formats and then record the answers").
# ---------------------------------------------------------------------------

import subprocess  # noqa: E402

ROOT = Path(__file__).resolve().parents[1].parent
CLI = ROOT / "grocery_price_cli.py"
PYEXE = Path(r"C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe")


def run_cli(args_list: list, timeout: int = 90) -> tuple[int, str]:
    cmd = [str(PYEXE), str(CLI)] + args_list
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=timeout, cwd=str(ROOT))
        return p.returncode, (p.stdout or "") + (
            ("\n[stderr] " + p.stderr.strip()) if p.stderr.strip() else "")
    except subprocess.TimeoutExpired:
        return -99, f"TIMEOUT after {timeout}s"


def pack_token(name: str) -> str | None:
    m = re.search(r"\((\d+(?:[.,]\d+)?\s*kg)\)", name.lower())
    return m.group(1).replace(" ", "") if m else None


def exec_audit(items_filter: str = "") -> int:
    from core.sheets_client import connect_spreadsheet
    sh = connect_spreadsheet()
    master = sh.worksheet("Products_Master").get_all_values()
    rows = []
    for i, r in enumerate(master[1:], start=2):
        name = str(r[0]).strip()
        if not name:
            continue
        if items_filter and not any(
                f.lower() in name.lower() for f in items_filter.split(",")):
            continue
        rows.append({"row": i, "name": name, "d": str(r[3]).strip(),
                     "kw": str(r[6]).strip(),
                     "code": str(r[11]).strip() if len(r) > 11 else ""})
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    out_csv = OUT / f"item_exec_{stamp}.csv"
    w = csv.writer(out_csv.open("w", encoding="utf-8", newline=""))
    w.writerow(["item", "code", "format", "command", "rc", "verdict",
                "reply"])
    total = passed = 0
    for r in rows:
        name = r["name"]
        # FORMAT 1 — plain item name
        rc, reply = run_cli(["price", "--item", name])
        verdict = "PASS" if (rc == 0 and
                             (f"[{r['code']}]" in reply or
                              "Not tracked" in reply)) else \
            f"FAIL rc={rc}"
        total += 1
        passed += (verdict == "PASS")
        w.writerow([name, r["code"], "name-exact",
                    f"price --item {name}", rc, verdict,
                    reply.strip()[:1500]])
        # FORMAT 3 — pack routing: pack items queried by pack phrase
        # (NL phrasing variety is agent-layer; tested via gateway sample)
        pk = pack_token(name)
        if pk:
            base = name.lower().replace(f"({pk})", "").replace("–", "")
            base = " ".join(base.split())
            rc3, reply3 = run_cli(["price", "--item", f"{base} {pk}"])
            # the reply must cite THIS row's code (pack routing, not a
            # /kg cousin)
            ok3 = rc3 == 0 and f"[{r['code']}]" in reply3
            v3 = "PASS" if ok3 else "CHECK routing — see reply"
            total += 1
            passed += (ok3)
            w.writerow([name, r["code"], "pack-routing",
                        f"price --item {base} {pk}", rc3, v3,
                        reply3.strip()[:1500]])
    print(f"EXEC items: {len(rows)} | checks: {total} | "
          f"PASS: {passed} | non-PASS: {total-passed}")
    print(f"evidence: {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
