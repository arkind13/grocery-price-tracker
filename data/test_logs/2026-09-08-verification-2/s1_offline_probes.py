"""§1 offline probes (read-only against the sheet; all state paths sandboxed).

Probes:
  P1 (R2-1/D19): find_product on sugar-family queries — V Zero must never
      auto-answer 'sugar'; RAW SUGAR rows or candidates instead;
      directionality: 'zero sugar'/'v zero' queries still match V Zero;
      'no sugar' matches Dare No Sugar; plain 'milk' not over-blocked.
  P2 (R2-3/D22): split_name_size order-independence + merge-candidate for
      the D22 reorder; exact-dup + different-size guards.
  P3 (D14 watch): is_same_product + merge behavior on the user-retracted
      distinct pairs — must NOT merge.
  P4 (R2-2/D20): is_same_product Lindt pair = False.
Prints PASS/FAIL lines; full detail goes to stdout for the receipt.
"""
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

# ---- sandbox every state write BEFORE importing core modules ----
import core.name_matcher as nm
_tmp = Path(tempfile.mkdtemp(prefix="v2_sandbox_"))
nm.QUEUE_PATH = _tmp / "unmapped_queue.json"
import core.searched_items as si
for attr in dir(si):
    if attr.isupper() and attr.endswith("_PATH"):
        pass  # (searched_items only written by search flows, not used here)
import core.local_deals as ld
ld.POST_LOG_PATH = _tmp / "post_log.json"

from core.lookup import LookupEngine  # noqa: E402
from core.sheets_client import connect_worksheet  # noqa: E402
from core.name_matcher import is_same_product, split_name_size  # noqa: E402

ws = connect_worksheet()
eng = LookupEngine(ws)

results = []


def check(label, ok, detail=""):
    results.append((label, ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))


def show(tag, query, **kw):
    r = eng.find_product(query, **kw)
    print(f"  {tag}: find_product({query!r}, {kw}) -> status={r.status.name} "
          f"row={r.row_index} name={r.generic_name!r} note={r.note!r}")
    return r


print("=" * 78)
print("P1 — R2-1 (D19): alias-path negation guard")
print("=" * 78)
r_sugar = show("sugar-auto", "sugar", interactive=False)
check("R2-1: 'sugar' does NOT auto-answer V Zero 250 Ml (row 30)",
      not (r_sugar.row_index == 30), f"got row {r_sugar.row_index} {r_sugar.generic_name!r}")
check("R2-1: 'sugar' lands on a RAW SUGAR row (47/90) or candidates",
      r_sugar.row_index in (47, 90) or r_sugar.status.name == "CANDIDATES",
      f"row={r_sugar.row_index} status={r_sugar.status.name}")
r_dir = show("zero-sugar-dir", "zero sugar", interactive=False)
check("R2-1 directionality: 'zero sugar' STILL matches V Zero (row 30)",
      r_dir.row_index == 30, f"got row {r_dir.row_index} {r_dir.generic_name!r}")
r_rb = show("red-bull", "red bull", interactive=False)
print(f"  (info) 'red bull' -> row {r_rb.row_index} {r_rb.generic_name!r}")
# ('no sugar dare' probe removed on re-run: it fell through to Step-5 live
#  search and burned a store call; receipt S1_R2-1_offline_probe.txt run 1
#  already recorded it — live auto-select returned the correct Dare
#  No Added Sugar product for the negation-carrying query.)
r_milk = show("milk", "milk", interactive=False)
check("R2-1 spillover: plain 'milk' still auto-resolves (not over-blocked)",
      r_milk.row_index is not None and r_milk.status.name != "NOT_FOUND",
      f"row={r_milk.row_index} {r_milk.generic_name!r}")
r_inter = eng.find_product("sugar", interactive=True)
print(f"  sugar-interactive -> status={r_inter.status.name} "
      f"cands={[c.generic_name for c in (r_inter.candidates or [])][:6]}")

print()
print("=" * 78)
print("P2 — R2-3 (D22): order-independent size parse + merge")
print("=" * 78)
from core.sheets_sync import add_product_row  # noqa: E402
canon = "Evamay Pads With Wings Super 14 pack"
reord = "pack Evamay Pads With Wings Super 14"
b_c = split_name_size(canon)
b_r = split_name_size(reord)
print(f"  split({canon!r}) = {b_c}")
print(f"  split({reord!r}) = {b_r}")
body_c = set(b_c[0]) if not isinstance(b_c[0], str) else set(b_c[0].split())
body_r = set(b_r[0]) if not isinstance(b_r[0], str) else set(b_r[0].split())
check("R2-3: reordered variant yields the SAME body tokens as canonical",
      body_c == body_r, f"{sorted(body_c)} vs {sorted(body_r)}")
check("R2-3: both parse the same size", b_c[1] == b_r[1], f"{b_c[1]!r} vs {b_r[1]!r}")
same_reord = is_same_product(canon, reord)
print(f"  is_same_product(canon, reorder) = {same_reord}")
check("R2-3: matcher now treats the reorder as the SAME product", same_reord is True)

print()
print("=" * 78)
print("P3 — D14 watch: user-retracted DISTINCT pairs must not merge")
print("=" * 78)
pairs = [
    ("Organic Free Range Eggs 12 Pack 600g", "Eggs Free Rage 12Pc"),
    ("Sunbites Sour 60g", "Sunbites Sour Cream Mulipack"),
    ("Sunbites Sour Cream Mulipack",
     "Sunbites Grain Waves Sour Cream & Chives 22g x 8 pack"),
    ("V Watermelon 250Ml", "V Watermelon 4*250"),
]
for a, b in pairs:
    same = is_same_product(a, b)
    print(f"  is_same_product({a!r}, {b!r}) = {same}")
    check(f"D14: matcher keeps {a.split()[0]}… pair DISTINCT", same is False)

print()
print("=" * 78)
print("P4 — R2-2 (D20): Lindt different-product verdict")
print("=" * 78)
same = is_same_product("Lindt Hot Choc Flakes Tin 210g",
                       "Lindt Lindor Assorted Chocolate Gift Box 235g")
print(f"  is_same_product(Lindt Hot Choc Flakes Tin 210g, Lindt Lindor Assorted ... 235g) = {same}")
check("R2-2: matcher says the Lindor gift box is a DIFFERENT product", same is False)

print()
n_ok = sum(1 for _, ok in results if ok)
print(f"SUMMARY: {n_ok}/{len(results)} checks passed")
