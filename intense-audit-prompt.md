# INTENSE FULL AUDIT — every sheet name, every format, new accuracy criteria (paste into a fresh session)

---

You are the verification executor for the grocery-price-tracker. This is
the INTENSE audit: every item × every message format × accuracy
criteria that prior rounds did not check. Record everything. **Fix
nothing.**

## Read first
1. `grocery-price-tracker/sheet-item-tester.md` — the loop + judging rules.
2. `grocery-price-tracker/architecture-spec.md` — §8 semantics + §18 amendments.
3. `grocery-price-tracker/data/test_logs/2026-09-11-verification-run2/interpretation-summary.md`
   — the previous round's fix list; every item marked fixed must
   reproduce on your own evidence.

## Environment
Anaconda python (`C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe`),
work from `C:\Users\User.DESKTOP-R2G441H\Documents\AI related\`.
**QUOTA LAW**: one session at a time on the sheet; ≥1.3s between
commands; 429 → wait 120s, resume. Evidence dir:
`grocery-price-tracker/data/test_logs/<today>-intense/`.

## The audit — three layers

**Layer A — semantic audit (every item, in-process):**
`tools/item_audit.py` — every master item through the lookup; the CSV
gives expected/actual/verdict per item. Judge the rendered replies
against §8 + A4 (twin line on meat queries when a plain row exists).

**Layer B — REAL COMMAND EXECUTION (every item, real CLI):**
`tools/item_audit.py --exec` — every item through the actual
`grocery_price_cli.py price --item "<name>"` with the reply recorded.
Then the routing variants for every item with a pack marker or meat
name:
- pack items: query `<product> <packsize>` (e.g. "chicken breast 5kg")
  → the reply MUST cite that pack row's code, never a /kg cousin's
- meat items: query without "halal" AND with "halal" → the halal-scoped
  answer + the twin line must appear in both
- plural-toggle query → must resolve to the same row

**Layer C — accuracy criteria (NEW, per quote in every reply):**
| Criterion | Rule | FAIL example (the Cos Lettuce class) |
|---|---|---|
| Domain accuracy | a produce item NEVER cites a butchery (Merjan/Dunya); a meat item NEVER cites a fruit & veg shop (Fruitopia/Abu Salim) | "Cos lettuce — 99c at Merjan" |
| Per-shop price accuracy | every rendered shop price equals that shop's cell on the Local_Deals tab (read the tab, compare) | "$7 everywhere" when cells differ |
| Source labels | Dunya labelled as the SITE (permanent, no validity); Merjan/Fruitopia/Abu Salim as FB specials with their stamps | "Dunya FB (till 12 Sep)" |
| Multibuy terms | every "(special)" quote carries its "min order …" terms from the Comments cell | "(special)" with no terms |
| Per-kg normalisation | every /ea pack quote shows its per-kg; /kg quotes show per-kg; the winner is chosen on comparable units | a 5kg pack price compared against a /kg price raw |
| Validity stamps | every dated special shows its "(till …)" stamp; expired stamps never render | a special shown with an expired stamp |
| Header code | the missing-list header cites the MATCHED row's code — never a cousin's | "lamb necks" headed [YTB] instead of [YCQ] |

Judging: automated where possible (the driver), human/AI review of the
rendered replies for the rest. Every FAIL gets the reproducing command
+ the observed vs required line, saved to the evidence dir.

**Layer D — live gateway battery (real Telegram, 10 messages):**
per-item lookups in different phrasings (exact / "how much is X" /
"price of X" / pack phrase), one multibuy item, one twin-line compare,
one `list`, one `batch` verify-only, one GONE-item query. Quote every
delivered reply.

## Final gates
1. Suite green, 0 skipped (report count).
2. Parity audit ALIGNED; zero sheet writes from the audit (md5 the tabs
   before/after).
3. Three-way sync (local ↔ GitHub ↔ VPS, checksums).
4. The deliverable: `verification-report-<today>.md` with per-layer
   totals, every non-PASS classified (real defect / judging artifact /
   environment), and the numbered fix list for the next session.

## Known open items going in (verify, don't re-discover)
- D1 halal-optional matching (117 rows) — claimed open; verify the
  count is unchanged
- D2 price-of dump (6 rows) — open
- Lamb necks header code flip (sorted-first row) — open
- GW relay discipline (agent quotes CLI lines verbatim) — open
- The `specials` scope question — user decision pending
