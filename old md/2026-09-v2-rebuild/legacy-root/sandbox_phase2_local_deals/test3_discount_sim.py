#!/usr/bin/env python3
"""Test 3 sandbox harness — simulate the >20% local-deal detection against
Products_Master rows (Phase 2: Localised Store Specials).

Sandbox ONLY: offline, pure stdlib, no network, no sheet access. Fixture
rows mirror the real Products_Master column layout:
    A name | B category | C size | D Woolworths_Price | E Coles_Price |
    ... | M wool_specials | N coles_specials

The logic under test (candidate architecture for pre-arch.md):

  1. MATCH   local flyer deal -> Products_Master row by tolerant token
             overlap (sandbox stand-in for core/name_matcher semantics).
  2. GATE    - price_kind "bulk_pack" is NEVER the comparison unit
                 (requirement 5). If it is the ONLY price for the item,
                 emit the inline tag
                 "[Multi-buy: Store has Xkg for $Y — switch?]" and keep
                 the basket default at Woolworths/Coles.
               - multibuy (same standard pack, "2 for $15") converts to
                 its effective unit rate total/qty — same rule the sheet
                 already applies via core/multibuy.py.
               - per-kg flyer prices compare against the master row's
                 implied $/kg (price / parsed size) — same family both
                 sides, UOM gate (core/uom.py rules) still applied.
  3. ALERT   discount_pct = (baseline - local) / baseline, baseline =
             cheaper of Woolworths/Coles effective price. Flag when
             strictly > 20% (requirement 6 wording ">20% cheaper").
  4. OPTIMISER  diverting items to the local store only earns an "extra
             stop" recommendation when the summed movement savings is
             STRICTLY above the existing $3.00 threshold
             (core/basket_optimizer.DEFAULT_SPLIT_THRESHOLD semantics).

Run:  python test3_discount_sim.py
Exit: 0 when every embedded edge-case assertion passes.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field

# Windows consoles default to cp1252 and crash on emoji/arrows in output.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

THRESHOLD_DISCOUNT = 0.20          # strictly greater flags the alert
MOVEMENT_THRESHOLD = 3.00          # dollars (matches DEFAULT_SPLIT_THRESHOLD)
BULK_TAG = "[Multi-buy: Store has {size} for ${total} — switch?]"

_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(kg|g|each|ea)\s*$",
                      re.IGNORECASE)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@dataclass
class MasterRow:
    """One Products_Master row (subset of columns that matter here)."""
    name: str
    size: str            # Col C, e.g. "500g", "1kg", "2L", "1 each"
    ww_price: float | None
    coles_price: float | None
    ww_specials: str = ""   # Col M
    coles_specials: str = ""  # Col N


@dataclass
class LocalDeal:
    """One validated Vision-JSON deal (Test 2's schema, flattened)."""
    store: str
    item: str
    price: float
    unit: str                 # "kg" | "ea" | "pack"
    price_kind: str           # "single" | "multibuy" | "bulk_pack"
    multibuy_qty: int | None = None
    bulk_size: str | None = None


@dataclass
class Verdict:
    """Outcome of evaluating one local deal against the master sheet."""
    deal: LocalDeal
    matched_row: MasterRow | None = None
    local_unit_basis: float | None = None   # $/kg or $/ea after normalising
    baseline_unit_basis: float | None = None
    baseline_store: str = ""
    discount_pct: float | None = None
    alerted: bool = False
    bulk_tag: str | None = None
    notes: list[str] = field(default_factory=list)


MASTER_ROWS = [
    # name, size, WW, Coles, M, N
    MasterRow("Beef Diced 500g", "500g", 8.75, 9.00),
    MasterRow("Chicken Breast Fillet 1kg", "1kg", 15.50, 16.00),
    MasterRow("Whole Chicken 1.6kg", "1.6kg", 13.60, None),
    MasterRow("Beef Sausages 500g", "500g", 6.50, 6.00),
    MasterRow("Apples Royal Gala 1kg", "1kg", 4.50, 4.90),
    MasterRow("Bananas 1kg", "1kg", 4.20, 3.90),
    MasterRow("Potatoes Brushed 2kg", "2kg", 5.50, 6.00),
    # Control: item the local stores never sell — must never alert.
    MasterRow("Full Cream Milk 2L", "2L", 3.05, 3.10),
]

LOCAL_DEALS = [
    # Clear alert: butcher $/kg vs implied WW/Coles $/kg.
    LocalDeal("dunya", "Beef Diced", 12.99, "kg", "single"),
    # Master implied: WW 8.75/0.5kg = 17.50/kg -> local 12.99 = 25.8% off.
    # Below-threshold: only 14% cheaper -> no alert.
    LocalDeal("dunya", "Chicken Breast", 14.50, "kg", "single"),
    # (WW 15.50/kg -> 14.50 = 6.5%; Coles 16.00 -> 9.4% -> no alert)
    # Multibuy same-size pack: 2 for $15 on 500g sausage packs
    # -> effective 7.50/500g = 15.00/kg vs baseline 12.00/kg -> no alert.
    LocalDeal("merjan", "Sausages", 15.00, "pack", "multibuy",
              multibuy_qty=2),
    # Bulk-only item: NO standard price exists -> tag + default stays WW/Coles.
    LocalDeal("dunya", "Bulk Beef Box", 89.90, "pack", "bulk_pack",
              bulk_size="10kg"),
    # Produce: >20% -> alert.
    LocalDeal("fruitopia", "Apples Royal Gala", 3.20, "kg", "single"),
    # (baseline 4.50/kg -> 3.20 = 28.9% off)
    # Name drift: flyer says "Bananas", master row "Bananas 1kg" -> match.
    LocalDeal("fruitopia", "Bananas", 2.90, "kg", "single"),
    # (baseline 3.90 -> 25.6% off)
    # No match: flyer item with no master row -> informational only.
    LocalDeal("abusalim", "Pomegranates", 5.99, "kg", "single"),
    # Cross-family trap: per-kg deal vs a count/each-size master row.
    # Whole Chicken 1.6kg is weight so this one is fine (13.60/1.6=8.50/kg;
    # local 7.99 = 6% -> no alert) — the REAL trap is milk: a per-kg deal
    # must never match a volume (L) row.
    LocalDeal("fruitopia", "Full Cream Milk", 1.55, "kg", "single"),
]


# ---------------------------------------------------------------------------
# Sandbox stand-ins for the real core modules
# ---------------------------------------------------------------------------
def parse_size(text: str) -> tuple[float, str] | None:
    """Minimal mirror of core/uom.parse_size for fixtures (kg/g/each)."""
    m = _SIZE_RE.match(str(text or ""))
    if not m:
        return None
    value, unit = float(m.group(1)), m.group(2).lower()
    if unit == "kg":
        return value * 1000.0, "weight"
    if unit == "g":
        return value, "weight"
    return value, "count"


def token_overlap(a: str, b: str) -> float:
    """Tolerant match score: |shared words| / min(|a|,|b|) (sandbox
    stand-in for name_matcher ranking; never rejects, only ranks)."""
    wa = {w for w in re.findall(r"[a-z]+", a.lower())
          if w not in {"the", "and"}}
    wb = {w for w in re.findall(r"[a-z]+", b.lower())
          if w not in {"the", "and"}}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def match_row(deal: LocalDeal, rows: list[MasterRow]) -> MasterRow | None:
    """Rank rows by token overlap; require >= 0.6 in the sandbox."""
    best, best_score = None, 0.0
    for row in rows:
        score = token_overlap(deal.item, row.name)
        if score > best_score:
            best, best_score = row, score
    return best if best_score >= 0.6 else None


def implied_unit_price(price: float, size: str) -> tuple[float, str] | None:
    """Price per canonical unit: $/kg for weight rows, $/ea for counts."""
    parsed = parse_size(size)
    if parsed is None:
        return None
    value, family = parsed
    if family == "weight" and value > 0:
        return price / (value / 1000.0), "kg"
    if family == "count" and value > 0:
        return price / value, "ea"
    return None


def deal_unit_basis(deal: LocalDeal,
                    row: MasterRow) -> tuple[float, str] | None:
    """Normalise a local deal to (price-per-canonical-unit, basis).

    bulk_pack returns None by design: bulk tier prices never become a
    comparison basis (requirement 5).
    """
    if deal.price_kind == "bulk_pack":
        return None
    price = deal.price
    if deal.price_kind == "multibuy":
        # Same standard pack, N for $X -> effective per-pack rate first.
        if not deal.multibuy_qty or deal.multibuy_qty < 2:
            return None
        price = price / deal.multibuy_qty
    row_basis = implied_unit_price(1.0, row.size or "1 each")
    if row_basis is None:
        return None
    basis = row_basis[1]
    if basis == "kg":
        if deal.unit == "kg":
            return price, "kg"
        if deal.unit == "pack":
            # pack price: use the MASTER row size as the pack size
            # (multibuy rates apply to the same standard pack)
            row_parsed = parse_size(row.size)
            if row_parsed and row_parsed[1] == "weight":
                return price / (row_parsed[0] / 1000.0), "kg"
        return None
    if basis == "ea":
        if deal.unit in ("ea", "pack"):
            return price, "ea"
        return None
    return None


def evaluate(deal: LocalDeal, rows: list[MasterRow]) -> Verdict:
    """Full Test-3 evaluation of one deal -> Verdict."""
    verdict = Verdict(deal=deal)

    if deal.price_kind == "bulk_pack":
        verdict.bulk_tag = BULK_TAG.format(
            size=deal.bulk_size or "?", total=f"{deal.price:.2f}")
        verdict.notes.append(
            "bulk-only price: comparison stays Woolworths/Coles (req 5)")
        row = match_row(deal, rows)
        verdict.matched_row = row  # matched, but NEVER priced from bulk
        return verdict

    row = match_row(deal, rows)
    if row is None:
        verdict.notes.append("no master row matched — informational only")
        return verdict
    verdict.matched_row = row

    local = deal_unit_basis(deal, row)
    if local is None:
        verdict.notes.append("no comparable basis (unit family/gate)")
        return verdict
    verdict.local_unit_basis = local[0]

    # Baseline: cheaper of WW/Coles using the SAME basis. Effective rates
    # already live in D/E for this sandbox (sheet holds effective price).
    candidates = []
    if row.ww_price is not None:
        basis = implied_unit_price(row.ww_price, row.size)
        if basis and basis[1] == local[1]:
            candidates.append(("woolworths", basis[0]))
    if row.coles_price is not None:
        basis = implied_unit_price(row.coles_price, row.size)
        if basis and basis[1] == local[1]:
            candidates.append(("coles", basis[0]))
    if not candidates:
        verdict.notes.append("no WW/Coles baseline on same basis")
        return verdict

    verdict.baseline_store, verdict.baseline_unit_basis = min(
        candidates, key=lambda c: c[1])
    verdict.discount_pct = (
        (verdict.baseline_unit_basis - verdict.local_unit_basis)
        / verdict.baseline_unit_basis)
    verdict.alerted = verdict.discount_pct > THRESHOLD_DISCOUNT
    return verdict


def optimiser(alerted: list[Verdict]) -> dict:
    """$3.00-movement rule: recommend the extra local stop only when the
    summed per-item savings is STRICTLY above $3.00.

    Savings are computed on the master row's PACK price (what you'd
    actually pay), not the per-kg basis, to keep the dollar figures real.
    """
    savings = []
    for v in alerted:
        row = v.matched_row
        baseline_pack = min(p for p in (row.ww_price, row.coles_price)
                            if p is not None)
        # pack-equivalent local price = local per-unit * pack size
        parsed = parse_size(row.size)
        if parsed and parsed[1] == "weight":
            local_pack = v.local_unit_basis * (parsed[0] / 1000.0)
        else:
            local_pack = v.local_unit_basis
        savings.append((v, max(0.0, baseline_pack - local_pack)))
    total = round(sum(s for _, s in savings), 2)
    return {
        "items": savings,
        "total_savings": total,
        "recommend_extra_stop": total > MOVEMENT_THRESHOLD,
    }


# ---------------------------------------------------------------------------
# Review-response checks (2026-09-05): Red Flag 1 (canonical row
# grouping) and Edge Case 2 (produce variety false alerts)
# ---------------------------------------------------------------------------
STOPWORDS = {"kg", "each", "ea", "pack", "bag", "box", "fresh"}
VARIETY_TOKENS = {
    "royal gala", "pink lady", "granny smith", "fuji", "jazz",
    "cos", "iceberg", "jap", "butternut", "sebago", "desiree",
    "truss", "cherry", "roma", "round",
}


def canonical_key(item: str) -> str:
    """Variety-aware canonical grouping key (Red Flag 1).

    - token set, stopwords and unit suffixes removed, order-insensitive
      ("Beef Diced" == "Diced Beef")
    - a variety qualifier ("royal gala", "pink lady", ...) is REQUIRED
      in the key when present on either side, so different varieties
      never merge into one row
    """
    words = [w for w in re.findall(r"[a-z0-9.]+", item.lower())
             if w not in STOPWORDS and not re.fullmatch(r"\d+(\.\d+)?", w)]
    tokens = set(words)
    variety = set()
    for v in VARIETY_TOKENS:
        for vt in v.split():
            if vt in tokens:
                variety.add(v)
    if variety:
        tokens -= {w for v in variety for w in v.split()}
    # keep the price KIND out of the key: bulk 5kg bags stay separate
    # (their cell is a note, not a price) — handled by the caller.
    return " ".join(sorted(tokens)) + (
        "|" + "+".join(sorted(variety)) if variety else "")


def group_rows(deals: list[LocalDeal]) -> dict[str, list[LocalDeal]]:
    """Merge equivalent items into one canonical row per product."""
    rows: dict[str, list[LocalDeal]] = {}
    for deal in deals:
        if deal.price_kind == "bulk_pack":
            # bulk notes never take a price row (requirement 5)
            continue
        rows.setdefault(canonical_key(deal.item), []).append(deal)
    return rows


def variety_conflict(flyer_item: str, master_name: str) -> bool:
    """Edge Case 2 guard: generic flyer item vs a VARIETIED master row
    (or conflicting varieties) — such pairs must never fire a >20%
    alert (economy apples vs Pink Lady would be a false 50% 'saving').
    """
    fv = {v for v in VARIETY_TOKENS
          if any(t in canonical_key(flyer_item).split()
                 or t in flyer_item.lower() for t in v.split())}
    mv = {v for v in VARIETY_TOKENS
          if any(t in master_name.lower() for t in v.split())}
    if fv and mv:
        return fv != mv            # both specific, different varieties
    return bool(mv and not fv)     # master names a variety, flyer generic


def review_checks() -> tuple[list[tuple[str, bool]], str]:
    """Run RF1 + EC2 checks; returns (checks, summary_table)."""
    checks: list[tuple[str, bool]] = []
    lines = ["", "=" * 78,
             "REVIEW RESPONSE — canonical rows (RF1) + variety guard (EC2)",
             "=" * 78]

    # --- RF1: cross-store canonical grouping ---
    catalogue = [
        LocalDeal("dunya", "Beef Diced", 12.99, "kg", "single"),
        LocalDeal("merjan", "Diced Beef", 13.50, "kg", "single"),
        LocalDeal("dunya", "Beef Sausages", 14.90, "kg", "single"),
        LocalDeal("fruitopia", "Apples Royal Gala", 3.20, "kg", "single"),
        LocalDeal("abusalim", "Pink Lady Apples", 3.50, "kg", "single"),
        LocalDeal("abusalim", "Washed Potato", 2.99, "pack", "bulk_pack",
                  bulk_size="5kg"),
    ]
    rows = group_rows(catalogue)
    merged_beef = next((v for k, v in rows.items()
                        if "beef" in k and "diced" in k), None)
    checks.append(("'Beef Diced' + 'Diced Beef' share ONE canonical row",
                   merged_beef is not None and len(merged_beef) == 2))
    gala = next((v for k, v in rows.items() if "gala" in k), None)
    lady = next((v for k, v in rows.items() if "pink lady" in k), None)
    checks.append(("Royal Gala and Pink Lady stay on SEPARATE rows",
                   gala is not None and lady is not None
                   and gala is not lady))
    checks.append(("bulk_pack deals take no price row",
                   not any(any(d.price_kind == "bulk_pack" for d in v)
                           for v in rows.values())))
    lines.append(f"canonical rows ({len(rows)}):")
    for key, items in sorted(rows.items()):
        stores = ", ".join(f"{d.store}:${d.price}" for d in items)
        lines.append(f"  {key:34} <- {stores}")

    # --- EC2: variety guard on >20% alerts ---
    generic_apples = LocalDeal("fruitopia", "Apples", 2.29, "kg", "single")
    master = MasterRow("Apples Royal Gala 1kg", "1kg", 4.50, 4.90)
    checks.append(("generic 'Apples' vs 'Royal Gala' master: "
                   "variety conflict detected",
                   variety_conflict(generic_apples.item, master.name)))
    specific = LocalDeal("fruitopia", "Royal Gala Apples", 3.20,
                         "kg", "single")
    checks.append(("'Royal Gala Apples' vs same-variety master: "
                   "no conflict -> alert allowed",
                   not variety_conflict(specific.item, master.name)))
    pink_lady = LocalDeal("abusalim", "Pink Lady Apples", 3.50,
                          "kg", "single")
    checks.append(("'Pink Lady' vs 'Royal Gala' master: conflict",
                   variety_conflict(pink_lady.item, master.name)))
    non_variety = LocalDeal("dunya", "Beef Diced", 12.99, "kg", "single")
    checks.append(("non-variety items unaffected by the guard",
                   not variety_conflict(non_variety.item,
                                        "Beef Diced 500g")))

    lines.append("")
    return checks, "\n".join(lines)


def main() -> int:
    verdicts = [evaluate(d, MASTER_ROWS) for d in LOCAL_DEALS]

    print("=" * 78)
    print("TEST 3 — >20% local-deal detection (offline simulation)")
    print("=" * 78)
    for v in verdicts:
        d = v.deal
        if v.bulk_tag:
            print(f"\n{d.store:10} {d.item:22} bulk_pack ${d.price:.2f}")
            print(f"  → {v.bulk_tag}")
            print(f"  → basket default stays Woolworths/Coles")
            continue
        if v.discount_pct is None:
            print(f"\n{d.store:10} {d.item:22} ${d.price:.2f}/{d.unit}")
            print(f"  → no comparison ({'; '.join(v.notes)})")
            continue
        print(f"\n{d.store:10} {d.item:22} ${d.price:.2f}/{d.unit}")
        print(f"  matched: {v.matched_row.name!r}")
        print(f"  baseline {v.baseline_store}: "
              f"${v.baseline_unit_basis:.2f}/{d.unit if d.unit != 'pack' else 'pack'}"
              f"  local ${v.local_unit_basis:.2f}/{d.unit if d.unit != 'pack' else 'pack'}")
        print(f"  discount {v.discount_pct * 100:.1f}% "
              f"→ {'🚨 ALERT (>20%)' if v.alerted else 'no alert (≤20%)'}")

    # ---- assertions -----------------------------------------------------
    checks: list[tuple[str, bool]] = []
    by_item = {v.deal.item: v for v in verdicts}

    checks.append(("beef diced >20% alert fires",
                   by_item["Beef Diced"].alerted is True))
    checks.append(("chicken breast 6-9% does NOT alert",
                   by_item["Chicken Breast"].alerted is False))
    checks.append(("sausage multibuy rate 15.00/kg does NOT alert",
                   by_item["Sausages"].alerted is False
                   and abs(by_item["Sausages"].local_unit_basis - 15.0) < 0.01))
    bulk = by_item["Bulk Beef Box"]
    checks.append(("bulk pack never priced/alerted",
                   bulk.discount_pct is None and bulk.bulk_tag is not None))
    checks.append(("bulk tag format matches requirement",
                   bulk.bulk_tag ==
                   "[Multi-buy: Store has 10kg for $89.90 — switch?]"))
    checks.append(("apples 28.9% alert fires",
                   by_item["Apples Royal Gala"].alerted is True))
    checks.append(("name drift 'Bananas' matches and alerts",
                   by_item["Bananas"].matched_row is not None
                   and by_item["Bananas"].alerted is True))
    checks.append(("milk per-kg deal never matches volume row",
                   by_item["Full Cream Milk"].discount_pct is None))
    checks.append(("unmatched item is informational only",
                   by_item["Pomegranates"].matched_row is None))

    # Optimiser: apples (~1.30 on 1kg pack) + bananas (~1.00) + beef
    # (~2.26 on the 500g pack) -> total must clear $3.00.
    alerted = [v for v in verdicts if v.alerted]
    plan = optimiser(alerted)
    print("\n" + "=" * 78)
    print(f"OPTIMISER — movement on {len(alerted)} alerted items")
    for v, s in plan["items"]:
        print(f"  {v.deal.item:22} saving ${s:.2f} "
              f"(pack-equivalent vs {v.baseline_store})")
    print(f"  total movement: ${plan['total_savings']:.2f} "
          f"(threshold ${MOVEMENT_THRESHOLD:.2f})")
    print(f"  extra local stop recommended: "
          f"{plan['recommend_extra_stop']}")
    checks.append(("movement > $3.00 recommends extra stop",
                   plan["recommend_extra_stop"] is True))

    # Sub-threshold variant: keep only apples+bananas -> under $3.
    small = [v for v in alerted if v.deal.item in
             ("Apples Royal Gala", "Bananas")]
    small_plan = optimiser(small)
    checks.append(("sub-$3 movement does NOT recommend extra stop",
                   small_plan["recommend_extra_stop"] is False))

    # Review-response checks (RF1 canonical rows + EC2 variety guard).
    more_checks, review_output = review_checks()
    print(review_output)
    checks.extend(more_checks)

    print("\n" + "=" * 78)
    failed = 0
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        failed += 0 if ok else 1
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
