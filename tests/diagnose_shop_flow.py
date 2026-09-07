#!/usr/bin/env python3
"""READ-ONLY diagnostic of the shop flow (2026-09-07 test round).

Run:  python tests/diagnose_shop_flow.py
Never writes to the sheet or any queue file. All writes are
monkeypatched to recorders.

Sections:
  T1  resolve_shop_items combination matrix (subcategory engagement)
  T2  substring-matching traps (sugar vs V Sugarfree etc.)
  T3  wall-clock + sheet-read amplification (1/5/10/20/40 items)
  T4  per-item shop+prefer round-trip cost (writes patched out)
  T5  current sheet-state evidence (2026-09-07 incident rows)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.sheets_client import _load_env            # noqa: E402
_load_env()

from core.sheets_client import connect_worksheet    # noqa: E402
from core.subcategory import NEEDS_REVIEW, all_labels  # noqa: E402
from core.preferences import (                      # noqa: E402
    read_qrs, resolve_shop_items, set_preferred,
)

# ---------------------------------------------------------------- patch
# QUOTA NOTE (measured 2026-09-07): every read_qrs()/resolve_shop_items
# call issues ONE full-sheet get_all_values; the Sheets user quota is
# 60 reads/min — a combination sweep of 350 phrases exhausted it live.
# The stateless CLI pays this on EVERY invocation; the harness below
# reads the sheet once and replays the snapshot in memory.
t0 = time.time()
real_ws = connect_worksheet()
CONNECT_S = time.time() - t0
t0 = time.time()
SNAPSHOT = real_ws.get_all_values()
READ_S = time.time() - t0


class CachedWS:
    """In-memory worksheet: serves the one-time snapshot; records
    writes instead of performing them; counts logical reads."""
    def __init__(self):
        self.reads = 0
        self.writes = []

    def get_all_values(self, *a, **k):
        self.reads += 1
        return [list(r) for r in SNAPSHOT]

    def update(self, *a, **k):
        self.writes.append(("update", str(a)[:120]))

    def batch_update(self, *a, **k):
        self.writes.append(("batch_update", str(a)[:160]))

    def append_row(self, *a, **k):
        self.writes.append(("append_row", str(a)[:120]))


ws = CachedWS()
rows = read_qrs(ws)
print(f"env: connect {CONNECT_S:.2f}s | 1 get_all_values "
      f"{READ_S:.2f}s | {len(rows)} sheet rows")

# ---------------------------------------------------------------- T1
print("\n" + "=" * 70)
print("T1 — resolve_shop_items: does a shopping-list phrase reach its")
print("     sub-category? (category mode = preferred-row flow)")
print("=" * 70)
sheet_subs = {}
for r in rows:
    if r["subcategory"]:
        sheet_subs.setdefault(r["subcategory"], 0)
        sheet_subs[r["subcategory"]] += 1
labels = sorted(set(all_labels()) | set(sheet_subs))

QUALIFIERS = [
    ("exact label",            "{l}"),
    ("label + size",           "{l} 2kg"),
    ("size + label",           "2kg {l}"),
    ("label plural-ish caps",  "{L} 2 kg"),
    ("label + brand prefix",   "woolworths {l}"),
]

fails, total = 0, 0
for label in labels:
    for name, tpl in QUALIFIERS:
        phrase = tpl.format(l=label, L=label.capitalize())
        total += 1
        plan = resolve_shop_items(ws, [phrase])
        hit = bool(plan["compare"]) or bool(plan["halted"])
        if name != "exact label" and not hit:
            fails += 1
            sample = (f"  MISS {name!r}: '{phrase}' -> "
                      f"compare={len(plan['compare'])} "
                      f"halted={len(plan['halted'])} "
                      f"cold={len(plan['cold'])}")
            if fails <= 12:
                print(sample)
print(f"\nT1 RESULT: {fails}/{total} qualifier phrases FAILED to reach "
      f"their sub-category (fell through to raw-text product mode)")

# ---------------------------------------------------------------- T2
print("\n" + "=" * 70)
print("T2 — substring trap: find_candidates('sugar …') scoring")
print("=" * 70)
from core.lookup import LookupIndex          # noqa: E402
vals = [list(r) for r in SNAPSHOT]
idx = LookupIndex(vals[1:], vals[0])
TRAPS = [
    ("sugar", "sugar"), ("sugar 2kg", "sugar"),
    ("water", "water"), ("egg", "eggs"), ("apple", "apples"),
]
for q, want_sub in TRAPS:
    cands = idx.find_candidates(q, limit=6)
    print(f"\nquery '{q}' (wanted sub-category: {want_sub})")
    for c in cands:
        name = getattr(c, "generic_name", "?")
        sub = ""
        for r in rows:
            if r["name"] == name:
                sub = r["subcategory"] or "(none)"
                break
        flag = "" if sub == want_sub else "   <-- WRONG FAMILY"
        print(f"  {getattr(c, 'score', '?'):>2}  {name[:52]:52}  "
              f"[{sub[:18]}]{flag}")

# ---------------------------------------------------------------- T3
print("\n" + "=" * 70)
print("T3 — wall time + sheet reads for compare_basket(sheet) lists")
print("=" * 70)
from core.price_comparator import compare_basket  # noqa: E402
# real preferred rows = realistic weekly list
with_p = [r["name"] for r in rows if r["preferred"] == "P"][:40]
if len(with_p) < 40:
    with_p = (with_p * 4)[:40]
for n in (1, 5, 10, 20, 40):
    ws2 = CachedWS()
    t = time.time()
    rep = compare_basket(with_p[:n], mode="sheet", worksheet=ws2)
    el = time.time() - t
    print(f"{n:>3} items: {el:6.2f}s wall | {ws2.reads} full-sheet "
          f"reads | {len(ws2.writes)} writes (patched)")

# ---------------------------------------------------------------- T4
print("\n" + "=" * 70)
print("T4 — per-item one-by-one round trip (shop + prefer, writes off)")
print("=" * 70)
# pick a sub-category with members and no P flag yet
no_p = None
for label in labels:
    members = [r for r in rows if r["subcategory"] == label]
    if len(members) >= 1 and not any(
            r["preferred"] == "P" for r in members):
        no_p = label
        break
print(f"test sub-category (no P yet): {no_p!r}")
ws3 = CachedWS()
t = time.time()
plan = resolve_shop_items(ws3, [no_p] if no_p else ["milk"])
t_resolve = time.time() - t
entry = plan["halted"][0] if plan["halted"] else None
t_set = 0.0
set_calls = 0
if entry and entry["options"]:
    code = entry["options"][0][2]
    ws4 = CachedWS()
    t = time.time()
    res = set_preferred(ws4, code)     # writes PATCHED — pattern only
    t_set = time.time() - t
    set_calls = ws4.reads
print(f"resolve_shop_items: {t_resolve:.2f}s, {ws3.reads} reads")
print(f"set_preferred (writes patched): {t_set:.2f}s, "
      f"{set_calls} reads")
print("=> real agent loop per item = 2 CLI processes (2x auth "
      f"~{CONNECT_S:.1f}s each) + these reads + Telegram + model "
      "turn; repeated per item")

# ---------------------------------------------------------------- T5
print("\n" + "=" * 70)
print("T5 — sheet-state evidence (2026-09-07 incident rows)")
print("=" * 70)
INTEREST = ("sugar", "olive", "mozzarella", "pancake", "eggs",
            "dermaveen", "lindt")
for r in rows:
    low = r["name"].lower()
    if any(k in low for k in INTEREST):
        print(f"row {r['row_index']:>3}: {r['name'][:44]:44} | "
              f"Q={r['subcategory'][:14]:14} | "
              f"R={r['item_code']:4} | S={r['preferred'] or '-'}")
# keyword columns for those rows
print("\nkeyword columns (I=WW, J=Coles) for the same rows:")
hdr_i, hdr_j = 8, 9
for r in rows:
    low = r["name"].lower()
    if any(k in low for k in INTEREST):
        raw = vals[r["row_index"] - 1]
        i_kw = str(raw[hdr_i])[:38] if len(raw) > hdr_i else ""
        j_kw = str(raw[hdr_j])[:38] if len(raw) > hdr_j else ""
        print(f"row {r['row_index']:>3}: I={i_kw:38} J={j_kw}")

# needs-review count
nr = sum(1 for r in rows if r["subcategory"] == NEEDS_REVIEW)
print(f"\nneeds-review rows: {nr}")
print("DONE — no writes were sent to the sheet or any queue file")
