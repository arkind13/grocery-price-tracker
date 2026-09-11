# MERJAN BOARD CORRECTIONS — 2026-09-12

> Trigger: the gateway bot flagged "pack totals as per-kg prices" in
> the Merjan cells. Verified against the SOURCE boards (the three
> 2026-09-11 08:06–08:09 ingested images, archived at
> `data/local_deals_inbox/MER1109260507/processed/`, copies in this
> dir). Every Merjan weekend tile is an "N KG for $X" pack deal.

## The defect

The 2026-09-11 morning ingest wrote the PACK TOTAL into the /kg
special cell for 14 rows (and dropped the multibuy terms comment on
exactly those rows), while 9 other rows from the same boards parsed
correctly (per-kg + terms). Pattern: tiles whose text the parser
failed to read as "N kg … $X" kept the raw number as the cell value.

## Corrections applied (`local-deals --set-special`, till 13 Sep)

| LD row | Item | Was (wrong) | Now (board-correct) | Terms |
|---|---|---|---|---|
| 14 | Chicken Drumette | 19.99 | **4.00/kg** | 5kg for $19.99 |
| 18 | Chicken maryland | 34.99 | **7.00/kg** | 5kg for $34.99 |
| 21 | Chicken mid-wings | 19.99 | **9.00/kg** | 2kg for $17.99 |
| 23 | Chicken Mince | 17.99 | **9.00/kg** | 2kg for $17.99 |
| 53 | Lamb Mince | 29.99 | **15.00/kg** | 2kg for $29.99 |
| 73 | Beef Curry | 49.99 | **10.00/kg** | 5kg for $49.99 |
| 140 | BBQ Blade Steak | 31.99 | **16.00/kg** | 2kg for $31.99 |
| 141 | Flavoured Sausages | 29.99 | **15.00/kg** | 2kg for $29.99 |
| 142 | Sausages | 29.99 | **15.00/kg** | 2kg for $29.99 |
| 143 | Goat Curry (/kg) | 29.99 | **15.00/kg** | 2kg for $29.99 |
| 145 | Chicken Tenderloins | 32.99 | **11.00/kg** | 3kg for $32.99 |
| 146 | Steamer Chickens | 11.99/ea | **6.00/kg** | 2kg for $11.99 |
| 147 | Chicken Drumsticks | 19.99 | **4.00/kg** | 5kg for $19.99 |
| 148 | Thigh Fillet | 21.99 | **11.00/kg** | 2kg for $21.99 |

Note: the first correction pass passed the `--note` strings through
double quotes and Git Bash ate the `$NN` amounts ("for 1.99"); all 14
notes were re-applied single-quoted and verified intact.

## Spurious specials cleared (no board tile supports them)

| LD row | Item | Cleared |
|---|---|---|
| 2 | chicken breast diced /kg | `34.99 (till 13 Sep)` → empty |
| 43 | Lamb Curry /kg | `27.99 (till 13 Sep)` → empty |

## Verified correct without changes (9)

Chicken Breast 5kg (34.99/ea = 7.00/kg) · Whole chicken s14 (7.00/ea,
5 for $34.99) · Whole chicken s9 (6.00/ea, 2 for $11.99 — the steamer
per-bird view) · Drumstick 4.00 · Wings 4.00 · tenders 11.00 · Thighs
11.00 · Grilling Chops 17.00 · Sliced Lamb Neck 15.00 · Lamb Ribs
15.00 · Povi Masima Bucket 49.99.

## OPEN — the ingest defect itself

The parser must turn every "N KG <item> $X" tile into per-kg + terms;
on these stylised tiles (multi-line, "2 KG / LAMB MINCE / $29.99") it
sometimes wrote $X raw. Next fix cycle: repro with the tile text in
the deal-text/vision parse chain + regression test, so the next
weekend board cannot re-pollute the tab. Filed as the top item in
`data/test_logs/open-fix-list.md`.
