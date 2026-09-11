"""One-time butchery section sort (user request 2026-09-11).

Order: CHICKEN items, then GOAT, then LAMB, then BEEF (user
ruling 2026-09-11), then UNDECIDED (items with no recognisable
protein - the user will classify them with the store later).
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
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.sheets_client import connect_spreadsheet  # noqa: E402

PROTEIN_RANK = [("chicken", 0), ("goat", 1), ("lamb", 2), ("beef", 3)]
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


_RANK = dict(PROTEIN_RANK)


def sort_key(name: str) -> tuple:
    prot = protein(name)
    fam = family(name, prot)
    return (_RANK.get(prot, 9), fam, name.lower())


def main(mode="preview") -> int:
    sh = connect_spreadsheet()
    ld = sh.worksheet("Local_Deals")
    mw = sh.worksheet("Products_Master")
    ld_grid = ld.get_all_values()
    m_grid = mw.get_all_values()

    pairs = collect_pairs(ld_grid, m_grid)
    ordered = sorted(pairs, key=lambda pr: sort_key(str(pr[3][0]).strip()))

    if mode == "preview":
        for j, p in enumerate(ordered, 1):
            nm = str(p[3][0])
            prt = protein(nm)
            fam = family(nm, prt)
            print("  %3d. [%s] %-12s %s  [%s]" % (j, prt[:3].upper(), fam[:12], nm[:50], p[0]))
        print("PREVIEW ONLY - run with apply to rewrite both tabs.")
        return 0

    # APPLY: reorder CONTENT within the fixed butchery position set.
    ld_pos = sorted(p[1] for p in pairs)
    m_pos = sorted(p[2] for p in pairs)
    print("APPLY: sorting %d pairs (LD %d-%d, master %d-%d)" % (
        len(ordered), ld_pos[0], ld_pos[-1], m_pos[0], m_pos[-1]))
    time.sleep(1)
    ld_base = ld_pos[0]
    m_base = m_pos[0]
    writes_ld = []
    writes_m = []
    for j, p in enumerate(ordered):
        slot = j
        writes_ld.append((ld_base + slot, (list(p[3]) + [""] * 11)[:11]))
        writes_m.append((m_base + slot, (list(p[4]) + [""] * 13)[:13]))
    writes_ld.sort()
    writes_m.sort()
    ld.update(values=[r for _s, r in writes_ld],
              range_name="A%d:K%d" % (writes_ld[0][0], writes_ld[-1][0]))
    time.sleep(1)
    mw.update(values=[r for _s, r in writes_m],
              range_name="A%d:M%d" % (writes_m[0][0], writes_m[-1][0]))
    print("APPLIED: %d sorted pairs written to both tabs." % len(ordered))
    return 0




def collect_pairs(ld_grid: list, m_grid: list) -> list:
    """(code, ld_idx, m_idx, ld_row, m_row) for every coded butchery
    item, keyed by Item_Code (the parity key)."""
    ld_items: dict = {}
    first_fruit = None
    for i, r in enumerate(ld_grid[2:], start=3):
        n = str(r[0]).strip()
        code = str(r[10]).strip() if len(r) > 10 else ""
        if n in ("FRUITS", "FRUIT & VEG", "OTHER"):
            first_fruit = i
            break
        if n and code and n not in ("BUTCHERY", "PRICES VALID UNTIL",
                                    "Product"):
            ld_items[code] = (i, list(r))
    pairs = []
    for code, (li, lrow) in ld_items.items():
        twin = None
        for mi, mr in enumerate(m_grid[1:], start=2):
            if len(mr) > 11 and str(mr[11]).strip() == code:
                twin = (mi, list(mr))
                break
        if twin is None:
            print(f"SKIP (no master twin): LD {li} "
                  f"{str(lrow[0])[:40]} [{code}]")
            continue
        pairs.append((code, li, twin[0], lrow, twin[1]))
    return pairs


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "preview"))


def collect_pairs(ld_grid: list, m_grid: list) -> list:
    """(code, ld_idx, m_idx, ld_row, m_row) for every coded butchery
    item, keyed by Item_Code (the parity key)."""
    ld_items: dict = {}
    first_fruit = None
    for i, r in enumerate(ld_grid[2:], start=3):
        n = str(r[0]).strip()
        code = str(r[10]).strip() if len(r) > 10 else ""
        if n in ("FRUITS", "FRUIT & VEG", "OTHER"):
            first_fruit = i
            break
        if n and code and n not in ("BUTCHERY", "PRICES VALID UNTIL",
                                    "Product"):
            ld_items[code] = (i, list(r))
    pairs = []
    for code, (li, lrow) in ld_items.items():
        twin = None
        for mi, mr in enumerate(m_grid[1:], start=2):
            if len(mr) > 11 and str(mr[11]).strip() == code:
                twin = (mi, list(mr))
                break
        if twin is None:
            print(f"SKIP (no master twin): LD {li} "
                  f"{str(lrow[0])[:40]} [{code}]")
            continue
        pairs.append((code, li, twin[0], lrow, twin[1]))
    return pairs
