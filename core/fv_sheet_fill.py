#!/usr/bin/env python3
"""Fill Products_Master col D (Woolworths_Price) for FRUIT & VEGETABLE rows
from our own WW catalogue (2026-10-25, user ask). Produce-aware matching:
size-aligned bags/each/kg, organic-premium + processed-impostor penalties,
honest basis suffixes (/kg, /ea, /2kg bag, /250g, /half) whenever the
catalogue basis differs from the row's ask. DRY RUN by default; --apply
writes targeted col-D cells + Last_Updated via the tracker readwrite creds.
"""
from __future__ import annotations

import csv
import re
import sys
from datetime import date

sys.path.insert(0, ".")

UNIT_WORDS = {"kg", "kgs", "g", "gm", "ml", "l", "ltr", "ea", "pk", "pack", "per"}
STOP = {"fresh", "woolworths", "woolies", "the", "loose", "net", "tray", "bag", "bunch", "punnet", "each"} | UNIT_WORDS
PROCESSED = re.compile(r"(tube|paste|juice|frozen|glaze|smoothie|fingers|quarter|lightly dried|gourmet garden|roast|shred|cubed|pieces|tub|cut|with mint)")


def stems(text: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z]+", (text or "").lower()) if w not in STOP and not w.isdigit()]
    return [w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w for w in words]


def sheet_core(name: str) -> list[str]:
    n = re.sub(r"\(.*?\)", " ", name.lower())
    n = re.sub(r"/\s*(kg|ea|each|bunch|bag)\s*$", " ", n)
    n = re.sub(r"\d+(\.\d+)?\s*(kg|g|gm|ml|l|pk|pack)\b", " ", n)
    n = re.sub(r"\b\d+(\.\d+)?\b", " ", n)
    return stems(n)


def row_size_info(name: str, size: str) -> dict:
    t = f"{name} {size}".lower()
    if m := re.search(r"(\d+(?:\.\d+)?)\s*kg\s*bag", t):
        return {"bagkg": float(m.group(1))}
    if m := re.search(r"bag.*?(\d+(?:\.\d+)?)\s*kg", t):
        return {"bagkg": float(m.group(1))}
    if m := re.search(r"(\d+(?:\.\d+)?)\s*kg\b", t):
        return {"bagkg" if "bag" in t else "kg": float(m.group(1))}
    if re.search(r"/\s*kg\b|\bper kg\b", t):
        return {"kg": True}
    if m := re.search(r"(\d+)\s*g\b", t):
        return {"g": int(m.group(1))}
    if "bunch" in t:
        return {"bunch": True}
    if re.search(r"/\s*ea\b|\beach\b", t):
        return {"each": True}
    return {}


def cat_size_info(cat: dict) -> dict:
    info = row_size_info(cat["name"], cat.get("sizeText") or "")
    if "kg" in info and isinstance(info["kg"], float):
        info["bagkg"] = info.pop("kg")
    unit = (cat.get("unitPrice") or "").lower()
    if "/ 1kg" in unit or "/kg" in unit:
        info["perkg"] = True
    if "/ 1ea" in unit or "/ea" in unit:
        info["eachprice"] = True
    return info


def score(sheet_words: list[str], want: dict, cat: dict) -> float:
    name_l = cat["name"].lower()
    cwords = stems(cat["name"])
    if not sheet_words or not cwords:
        return -10.0
    joined = " ".join(cwords)
    sheet_l = " ".join(sheet_words)
    def word_hit(w):
        return any(w == t or (len(w) > 5 and t.startswith(w)) or (len(t) > 5 and w.startswith(t)) for t in cwords)
    hit = sum(1 for w in sheet_words if word_hit(w))
    s = hit / len(sheet_words) + (0.3 if sheet_words[-1] in joined else 0.0)
    if ("organic" in name_l or name_l.startswith("macro")) and "organic" not in sheet_l:
        s -= 0.5
    if ("half" in name_l or "twin" in name_l) and "half" not in sheet_l and "2 pack" not in sheet_l:
        s -= 0.3
    if PROCESSED.search(name_l) and not PROCESSED.search(sheet_l):
        s -= 1.2
    if "paste" in sheet_l and "paste" not in name_l:
        s -= 1.5
    if "odd bunch" in name_l and "odd" not in sheet_l:
        s -= 0.4
    if "kids" in name_l and "kids" not in sheet_l:
        s -= 0.5
    m = re.search(r"(\d+)\s*(pack|pk)\b", name_l)
    if m and "pack" not in sheet_l and "pk" not in sheet_l:
        s -= 0.35
    ci = cat_size_info(cat)
    if want.get("bunch"):
        s += 0.4 if "bunch" in name_l else -0.4
    if "bagkg" in want:
        if "bagkg" in ci and abs(ci["bagkg"] - want["bagkg"]) < 0.01:
            s += 0.8
        elif ci.get("perkg") or "bagkg" in ci:
            s += 0.1
        elif ci.get("eachprice"):
            s -= 0.6
    if "kg" in want:
        s += 0.5 if (ci.get("perkg") or ci.get("bagkg")) else (-0.2 if ci.get("eachprice") else 0.0)
    if "g" in want:
        if ci.get("g") == want["g"]:
            s += 0.6
        elif ci.get("g"):
            s -= 0.2
    if want.get("each") and ci.get("perkg"):
        s -= 0.3
    return s


def basis_label(want: dict, cat: dict) -> str:
    ci = cat_size_info(cat)
    name_l = cat["name"].lower()
    if "g" in want and ci.get("g") == want["g"]:
        return ""
    if "bagkg" in want and ci.get("bagkg"):
        return "" if abs(ci["bagkg"] - want["bagkg"]) < 0.01 else f"/{ci['bagkg']:g}kg bag"
    if ci.get("g") and ci.get("g") >= 100:
        return f"/{ci['g']:g}g"
    if ci.get("bagkg") and (want.get("kg") or want.get("each")):
        return f"/{ci['bagkg']:g}kg bag"
    if ci.get("perkg") and not want.get("kg"):
        return "/kg"
    if ci.get("eachprice") and want.get("kg"):
        return "/ea"
    if "pack" in want and not ci.get("pack"):
        return "/ea"
    if "half" in name_l:
        return "/half"
    return ""


def main(apply: bool) -> None:
    from core import sheets_client

    cats = list(csv.DictReader(open("data/ww-fv-catalogue.csv", encoding="utf-8")))
    ws = sheets_client.connect_worksheet("Products_Master")
    vals = ws.get_values("A1:L321")
    today = date.today().isoformat()
    plan, misses = [], []
    for idx, row in enumerate(vals[1:], start=2):
        if not row or not row[0]:
            continue
        cat_b = (row[1] if len(row) > 1 else "") or ""
        if not ("fruit" in cat_b.lower() or "veg" in cat_b.lower() or "f&v" in cat_b.lower() or "produce" in cat_b.lower()):
            continue
        name, size = row[0], (row[2] if len(row) > 2 else "") or ""
        cur = (row[3] if len(row) > 3 else "") or ""
        words = sheet_core(name)
        if not words:
            misses.append((idx, name, "no words"))
            continue
        want = row_size_info(name, size)
        best, best_score = None, -10.0
        for c in cats:
            sc = score(words, want, c)
            if sc > best_score:
                best, best_score = c, sc
        if not best or best_score < 0.9:
            misses.append((idx, name, f"best {best_score:.2f} {best['name'][:26] if best else ''}"))
            continue
        price = float(best["price"])
        text = f"${price:.2f}{basis_label(want, best)}"
        if cur.strip() == text:
            continue
        plan.append((idx, name[:34], size[:7], cur[:11] or "-", best["name"][:40], best["price"], text))

    print(f"matched-to-write: {len(plan)} | unmatched: {len(misses)}")
    for p in plan:
        print(f"  row {p[0]:>3}  {p[1]:<34} sz={p[2]:<7} cur={p[3]:<11} -> {p[4]:<40} ${p[5]:<6} D={p[6]}")
    print("\nUNMATCHED:")
    for m in misses:
        print(f"  row {m[0]:>3}  {m[1]}  ({m[2]})")

    # hand-checked corrections (2026-10-25 dry-run review): these matches
    # are wrong (different vegetable/variety) or have a better exact pick
    EXCLUDE_ROWS = {272, 290, 298, 305}   # snake beans!=sprouts, barhi!=medjool, bitter!=mix tub, roma!=mini-roma
    OVERRIDE_D = {280: "$3.00",           # Cos Hearts Lettuce 2 pack (exact WW product)
                  262: "$4.00"}           # Onion Brown Bag 1kg (exact WW product)
    plan = [(idx, n, s, c, m, p, OVERRIDE_D.get(idx, d)) for idx, n, s, c, m, p, d in plan]
    plan = [p for p in plan if p[0] not in EXCLUDE_ROWS]

    if apply and plan:
        print("\nAPPLYING targeted col-D writes…")
        for idx, _, _, _, _, _, text in plan:
            ws.update(f"D{idx}", [[text]])
            ws.update(f"F{idx}", [[today]])
        print(f"wrote {len(plan)} rows (col D + Last_Updated).")


if __name__ == "__main__":
    main("--apply" in sys.argv)
