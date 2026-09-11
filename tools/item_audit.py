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
import time
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
    ap.add_argument("--matrix", action="store_true",
                    help="FORMAT MATRIX: every item x every real-world "
                         "message format (exact/drift/plural/halal-"
                         "toggle/code/NL), all judged + recorded")
    ap.add_argument("--round", type=int, default=1,
                    help="verification round number - varies the "
                         "invented query formats per cycle")
    args = ap.parse_args()
    if args.exec:
        return exec_audit(args.items)
    if args.matrix:
        return matrix_audit(args.items, rnd=max(1, args.round))

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
        verdict = judge(name, exp, actual, text, master,
                        item_code=m.get("code", ""))
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
          m_rows: list, item_code: str = "") -> str:
    """§8 + A4 judging: meat queries are judged on CONTENT (locals +
    missing-list code + the non-halal twin line when a plain row
    exists), not on a single status token.

    2026-09-11 fixes: the missing-list line is required for
    missing-class rows (the old `exp == 'tracked'` condition was
    inverted — a tracked row's §8 answer shows the WW price, not a
    missing-list line); and a plain row that answers its OWN name is
    never demanded as a twin of itself (twin self-exclusion by
    code)."""
    if meat_query(name):
        problems = []
        if "missing list [" not in text and exp == "missing":
            problems.append("no missing-list line")
        if twin_expected(name, m_rows, item_code) \
                and "also at Woolworths (non-halal)" not in text:
            problems.append("twin line missing")
        if problems:
            return "FAIL: " + "; ".join(problems)
        return "PASS"
    if exp != actual:
        return f"FAIL: expected {exp}, got {actual}"
    return "PASS"


def twin_expected(name: str, m_rows: list[dict],
                  item_code: str = "") -> bool:
    """A4: a meat query shows the non-halal twin line whenever a plain
    (non-halal) meat master row shares a PRODUCT token with the query.
    Brand/size tokens never drive the overlap (the old raw split made
    'Woolworths … 500g' rows twin every 500g row through the shared
    brand/size tokens), and the answering row never twins itself."""
    from core.halal import is_meat_term
    from core.v2_read import _query_tokens

    if not is_meat_term(name):
        return False
    # a query that names a plain row verbatim IS that row's answer —
    # no twin demand (its §8 reply is the WW tracked block itself)
    low = name.lower()
    for r in m_rows:
        n = str(r["name"] or "").lower()
        if n == low and "halal" not in n:
            return False
    qtoks = {t for t in _query_tokens(name)
             if not t[0].isdigit() and t not in ("each", "ea")}
    for r in m_rows:
        if item_code and str(r.get("code", "")) == item_code:
            continue
        n = str(r["name"]).lower()
        if "halal" in n:
            continue
        if not is_meat_term(n):
            continue
        ntoks = {t for t in _query_tokens(n)
                 if not t[0].isdigit() and t not in ("each", "ea")}
        if qtoks & ntoks:
            return True
    return False


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
    time.sleep(1.2)                     # quota throttle (R12 lesson)
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




# ---------------------------------------------------------------------------
# MATRIX MODE — every item × every real-world message format, judged
# (user mandate 2026-09-11: "test all scenarios the message can be
# received in — real-world, rigorous, all formats").
# ---------------------------------------------------------------------------

def _shuffle(name: str) -> str:
    toks = name.split()
    if len(toks) < 2:
        return name
    return " ".join([toks[-1]] + toks[:-1])


def _toggle_plural(name: str) -> str:
    """Toggle the LAST real product word. Pack-size tokens ('(5kg)',
    '500g'), code-ish tokens ('s9/s14', 'R2E2') and 'each' are never
    toggled — '(5kg)s'/'500gs' was a generator artifact no shopper
    sends (run-2 'mangled' bucket), so the plural probe now lands on
    the word a real message would pluralise. -ies/-oes words get
    their PROPER singular ('Strawberries' -> 'Strawberry',
    'Mangoes' -> 'Mango'), not the naive 'Strawberrie'/'Mangoe'
    typo forms (cycle-2 mangled bucket)."""
    toks = name.split()
    for i in range(len(toks) - 1, -1, -1):
        t = toks[i]
        if t.lower() == "halal" or t.startswith("(") \
                or any(c.isdigit() for c in t) \
                or t.lower() in ("each", "ea") or len(t) <= 2:
            continue
        low = t.lower()
        if low.endswith("ies") and len(t) > 4:
            toks[i] = t[:-3] + "y"
        elif low.endswith("oes") and len(t) > 4:
            toks[i] = t[:-2]
        elif low.endswith(("ches", "shes", "xes")) and len(t) > 4:
            toks[i] = t[:-2]
        else:
            toks[i] = t[:-1] if t.endswith("s") else t + "s"
        break
    return " ".join(toks)


def _strip_halal(name: str) -> str:
    return re.sub(r"\bhalal\s*", "", name, flags=re.I).strip() or name


def _add_halal(name: str) -> str:
    return "halal " + name if "halal" not in name.lower() else name


def matrix_formats(item: dict, seq: int) -> list[tuple]:
    """(format-name, query, expected-marker) — expected-marker is the
    string that MUST appear in a correct reply (the row's code, unless
    the format is expected to answer without it)."""
    name = item["name"]
    code = item["code"]
    low = name.lower()
    fmts = [("exact", name, code)]
    if len(name.split()) > 1:
        fmts.append(("drift-shuffle", _shuffle(name), code))
    fmts.append(("drift-plural", _toggle_plural(name), code))
    if "halal" in low:
        fmts.append(("no-halal-prefix", _strip_halal(name), code))
    else:
        prot = any(w in low for w in ("chicken", "lamb", "goat",
                                      "beef", "mutton"))
        if prot:
            fmts.append(("with-halal-prefix", _add_halal(name),
                         "twin-or-code"))
    if seq % 10 == 0:
        fmts.append(("code-as-query", code, "FINDING-B: codes are not "
                     "lookup keys in v2 — record actual"))
    if seq % 25 == 0:
        # NL filler probe — the CLI strips price fillers since the
        # 2026-09-11 D2 fix, so this is judged like any real format
        fmts.append(("nl-price-of", f"price of {name}", code))
    return fmts


STYLE_WORDS = {"the", "and", "at", "for", "of"}


def judge_matrix(fmt: str, marker: str, code: str, rc: int,
                 reply: str) -> str:
    """Matrix verdict for ONE check (pure — unit-tested).

    - FINDING probes (code-as-query): recorded, never FAIL — codes
      are not lookup keys by design.
    - no-halal-prefix on a halal meat row: the D1 design ruling
      (user, 2026-09-11) — 'the halal keyword gates the BUTCHER
      search … bare protein queries are Woolworths-scope by design'
      — so the row's own code PASSES and an honest Woolworths-scope
      'Not tracked' answer PASSES; anything else FAILs.
    - with-halal-prefix on a plain row: 'twin-or-code' — the halal
      cluster with the row's code, or the non-halal twin line.
    - everything else: the row's own code must appear (rc=0)."""
    if marker.startswith("FINDING"):
        return "RECORDED"
    if rc != 0:
        return f"FAIL rc={rc}"
    body = (reply or "").strip()
    if not body:
        return "FAIL empty reply"
    if fmt == "no-halal-prefix":
        if code and code in body:
            return "PASS"
        if "Not tracked" in body or "not tracked" in body:
            return "PASS"
        return "FAIL bare query: neither the row code nor a " \
               "Woolworths-scope answer"
    if marker == "twin-or-code":
        if (code and code in body) or "non-halal" in body:
            return "PASS"
        return "FAIL twin-or-code"
    if code:
        return "PASS" if code in body else "FAIL wrong-or-missing code"
    return "PASS"


ROUND_VARIANTS = {
    # each verification round invents DIFFERENT commands: the shuffle
    # rotation, the plural direction and the qualifier phrasing change
    # per round, so the system is tested against fresh inputs every
    # cycle (user mandate 2026-09-11 — no overfitting to fixed strings).
    1: lambda toks: " ".join(reversed(toks)),
    2: lambda toks: " ".join(toks[1:]) + " " + toks[0],
    3: lambda toks: " ".join(t + "s" for t in toks),
    4: lambda toks: " ".join(t[:-1] if t.endswith("s") else t
                              for t in toks),
    5: lambda toks: " and ".join(toks),
}


def _round_variant(name: str, rnd: int) -> str:
    toks = [t for t in re.findall(r"[a-z0-9]+", name.lower())
            if t not in STYLE_WORDS]
    if not toks:
        return name
    fn = ROUND_VARIANTS.get(rnd)
    return fn(toks) if fn else name


def matrix_audit(items_filter: str = "", rnd: int = 1) -> int:
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
        rows.append({"row": i, "name": name,
                     "code": str(r[11]).strip() if len(r) > 11 else ""})
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    out_csv = OUT / f"item_matrix_{stamp}.csv"
    w = csv.writer(out_csv.open("w", encoding="utf-8", newline=""))
    w.writerow(["item", "code", "format", "command", "rc", "verdict",
                "reply"])
    total = passed = 0
    for seq, r in enumerate(rows, start=1):
        fmts = matrix_formats(r, seq)
        if rnd > 1:
            # round-invented variant: the row's name cycled through this
            # round's transformation (fresh commands, same product)
            nm = r["name"]
            fmts.append((f"round{rnd}-variant", _round_variant(nm, rnd),
                         r["code"]))
        for fmt, query, marker in fmts:
            rc, reply = run_cli(["price", "--item", query])
            verdict = judge_matrix(fmt, marker, r["code"], rc, reply)
            total += 1
            passed += (verdict == "PASS")
            w.writerow([r["name"], r["code"], fmt, query, rc, verdict,
                        reply.strip()[:1200]])
    print(f"MATRIX items: {len(rows)} | checks: {total} | "
          f"PASS: {passed} | non-PASS: {total - passed}")
    print(f"evidence: {out_csv}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
