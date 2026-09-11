"""One-time butchery section sort (user request 2026-09-11).

Order: CHICKEN items, then LAMB, then GOAT, then BEEF, then MISC
(items with no recognisable protein). Within a protein, items cluster
by FAMILY so the same product's presentations sit together —
"Chicken Breast (5kg)" next to "Chicken Breast Fillet /kg", all minces
adjacent, all chops adjacent — and /kg rows sit with their pack twins.

Both tabs are rewritten in the SAME order (positional parity, spec
§3.3): master row N+1 ↔ Local_Deals item row N. The Fruit & Veg
section, structural rows, and every Item_Code are preserved.

Usage:
  python tools/sort_butchery.py preview   # read-only, prints the new order
  python tools/sort_butchery.py apply     # rewrite both tabs (backup first!)

Run ONLY when no other ingest/sync is writing the sheet.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.sheets_client import connect_spreadsheet  # noqa: E402

PROTEIN_RANK = [("chicken", 0), ("lamb", 1), ("goat", 2), ("beef", 3)]
STYLE_WORDS = {"halal", "turkish", "lebanese", "greek", "spicy",
               "premium", "lean", "whole", "skin", "off", "boneless",
               "bbq", "cook", "cooking", "finely", "fresh", "each",
               "s9", "s14"}
PACK_RE = re.compile(r"\(?\d+(?:[.,]\d+)?\s*kg\)?", re.I)


def _tokens(name: str) -> list[str]:
    toks = [t for t in re.findall(r"[a-z0-9]+", name.lower())
            if t not in STYLE_WORDS and not PACK_RE.fullmatch(t)]
    return toks


def protein(name: str) -> str:
    low = name.lower()
    for word, rank in PROTEIN_RANK:
        if word in low:
            return word
    # protein-specific cuts that imply the animal
    if re.search(r"drum|wing|maryland|thigh|tender", low):
        return "chicken"
    if re.search(r"\bchop|cutlet|backstrap|topside|blade\b", low):
        return "lamb"
    return "misc"


UNIT_TOKENS = {"ea", "kg", "g", "pk", "pack"}
FAMILY_ORDER = ["breast", "mince", "thigh", "drum", "drumette", "wings",
                "tender", "maryland", "fillet", "neck", "chops",
                "cutlet", "curry", "sausage", "skewer", "kofta",
                "adana", "whole", "roast", "shank", "ribs", "blade",
                "backstrap", "topside", "stirfry", "diced", "burger",
                "bucco", "bone", "steak", "gravy", "silverside",
                "rump", "kofte"]


def family(name: str, prot: str) -> str:
    toks = _tokens(name)
    content = [t for t in toks
               if t != prot and t not in UNIT_TOKENS and not t.isdigit()]
    # singular-fold so "necks"/"neck" share a family
    heads = {t[:-1] if t.endswith("s") and len(t) > 2 else t
             for t in content}
    # 'fillet' of chicken IS breast (user: breast /kg + 5kg together)
    if prot == "chicken" and "fillet" in heads:
        heads.add("breast")
        heads.discard("fillet")
    if not heads:
        return prot
    known = [h for h in heads if h in FAMILY_ORDER]
    if known:
        return min(known, key=FAMILY_ORDER.index)
    return sorted(heads)[0]


def sort_key(name: str) -> tuple:
    prot = protein(name)
    fam = family(name, prot)
    return (prot, fam, name.lower())


def main(mode: str = "preview") -> int:
    sh = connect_spreadsheet()
    ld = sh.worksheet("Local_Deals")
    mw = sh.worksheet("Products_Master")
    ld_grid = ld.get_all_values()
    m_grid = mw.get_all_values()

    # ---- collect butchery pairs via Item_Code (parity key) ----
    ld_items = {}    # code -> (ld_row_idx, ld_row)
    for i, r in enumerate(ld_grid[2:], start=3):
        n = str(r[0]).strip()
        code = str(r[10]).strip() if len(r) > 10 else ""
        if n and code and n not in ("BUTCHERY", "PRICES VALID UNTIL",
                                    "Product", "FRUITS",
                                    "FRUIT & VEG", "OTHER"):
            ld_items[code] = (i, r)
    m_items = {}
    first_fruit_m = None
    for i, r in enumerate(m_grid[1:], start=2):
        code = str(r[11]).strip() if len(r) > 11 else ""
        sub = str(r[9]).strip().lower() if len(r) > 9 else ""
        name = str(r[0]).strip()
        if code and code in ld_items:
            m_items[code] = (i, r)
    # butchery = LD codes whose position precedes the FRUITS section
    first_fruit = next((i for i, r in enumerate(ld_grid[2:], start=3)
                        if str(r[0]).strip() in ("FRUITS",
                                                 "FRUIT & VEG")), None)
    pairs = []
    for code, (i, r) in ld_items.items():
        if first_fruit is not None and i > first_fruit:
            continue
        if code not in m_items:
            print(f"SKIP (no master twin): LD {i} {r[0][:40]} [{code}]")
            continue
        pairs.append((code, i, m_items[code][0], r,
                      m_items[code][1]))
    print(f"butchery pairs: {len(pairs)}")

    # ---- sort the pairs ----
    def pair_key(p):
        r = p[3]
        return sort_key(str(r[0]).strip())
    pairs.sort(key=pair_key)

    if mode == "preview":
        for j, (code, li, mi, r, _mr) in enumerate(pairs, 1):
            print(f"  {j:3d}. [{protein(str(r[0]))[:3].upper()}] "
                  f"{family(str(r[0]), protein(str(r[0])))[:12]:12s} "
                  f"{str(r[0])[:50]}  [{code}]  (LD{li}/M{mi})")
    print("\nPREVIEW ONLY — run `apply` to rewrite both tabs.")
    return 0

    # ---- apply: reorder CONTENT within the existing position set ----
    ld_positions = sorted(p[1] for p in pairs)          # ascending
    m_positions = sorted(p[2] for p in pairs)
    assert len(ld_positions) == len(m_positions) == len(pairs)
    time.sleep(1)
    for j, (code, _li, _mi, _r, _mr) in enumerate(pairs):
        ld_row_content = next(p[3] for p in pairs if p[1] == ld_positions[j])
        m_row_content = next(p[4] for p in pairs if p[2] == m_positions[j])
        # pad/trim to the tab width
        ld_row_content = (list(ld_row_content) + [""] * 11)[:11]
        m_row_content = (list(m_row_content) + [""] * 13)[:13]
        ld.update(values=[ld_row_content],
                  range_name=f"A{ld_positions[j]}:K{ld_positions[j]}")
        mw.update(values=[m_row_content],
                  range_name=f"A{m_positions[j]}:M{m_positions[j]}")
        time.sleep(1.05)
    print(f"rewrote {len(pairs)} sorted pairs on both tabs "
          f"(content travels with its code — parity preserved)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "preview"))
