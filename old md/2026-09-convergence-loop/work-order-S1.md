# WORK ORDER — Round S1: chicken-breast special move + butchery sort + verification

> Self-contained work order for a FRESH coder session (03 Code). Execute in
> order, STOP at every gate, fix nothing outside this scope.
> Written 2026-09-11 by the orchestrator after live verification of the
> current sheet state — no re-investigation needed.

## Current state (verified 2026-09-11)

- Local_Deals: 147 grid rows; Products_Master: 144 grid rows; parity audit
  = **ALIGNED** (run `tools/parity_audit.py` via the pattern in the file's
  callers to re-confirm at start).
- **Misplaced special:** LD row 83 `Halal Chicken Breast Fillet /kg`
  carries `merjan_spec = "7.00 (till 13 Sep)"` + comment
  `[MER] multi buy 5kg for $34.99`. The Merjan deal is a **5kg chicken
  breast pack** — it belongs to **LD row 70 `Halal Chicken Breast – (5kg)
  /ea` [NTB]** (Dunya permanent 54.99, Merjan column currently empty),
  per the user's product knowledge.
- **Butchery section: 100 coded item pairs, UNSORTED** (Dunya catalogue
  rows + Merjan rows interleaved). Sort tool exists and is preview-verified:
  `tools/sort_butchery.py` (protein order chicken → lamb → goat → beef,
  undecided LAST; families cluster /kg + pack twins together — breast
  cluster includes Fillet + (5kg); minces adjacent; chops adjacent).
- **UNDECIDED ITEMS (user will confirm with the store — do NOT classify):**
  `Halal Mince – (5kg)`, `Halal Kofte skewer`, `Halal Lebanese Kofte`,
  `Halal Turkish Kofte`, `Halal Turkish Adana`. They stay in the
  undecided group at the END of butchery. A later `batch rename` moves
  them once the user confirms.
- Eye cluster ruling: Rib Eye + eye-fillet stay TOGETHER (user confirmed).
- Suite: green and growing (the parallel Aldi session adds tests —
  coordinate, see STOP gate).

## STOP GATE (before any write)

1. Ask the user: **"Is the ingest finished?"** Do not proceed until YES.
2. Fresh backup: `tools/sheet_backup.py` → exit 0, BACKUP VERIFIED.
3. Single writer: confirm no other session is mid-write (the parallel
   Aldi session may be active — coordinate with the user).

## Task 1 — move the misplaced Merjan special (LD 83 → LD 70)

- LD 70 merjan_spec = `34.99 (till 13 Sep)`; append comment
  `[MER] multi buy 5kg for $34.99` (strip-then-append; never
  concatenate tags).
- LD 83 merjan_spec = cleared; strip the `[MER]` segment from its
  comments (Dunya permanent 13.99 stays).
- Verify by read-back of both rows.

## Task 2 — butchery sort

- Print `tools/sort_butchery.py preview` (for the record), then run
  `apply`. The tool reorders CONTENT within the existing position set —
  parity is preserved by construction.
- Verify: `tools/parity_audit.py` → ALIGNED; spot-check that the breast
  cluster (diced / Fillet /kg / strips / (5kg)) is adjacent and that
  LD row N+1 still pairs with master row N (Item_Code match).

## Task 3 — live Telegram verification (VPS gateway)

Fire as real messages (`openclaw.mjs agent --channel telegram --to
1594431983 --message '…' --deliver`) and quote the delivered replies:
1. `check halal chicken breast pricing` — MUST show Dunya per-kg
   (fillet $13.99/kg; 5kg $54.99 = $11.00/kg) AND the Merjan min-order
   deal ($34.99 / 5kg pack = $7.00/kg) + 🏆 winner.
2. `lamb necks` — regression: merged row [YCQ] (Merjan $15/kg special +
   Dunya $16.99) still answers.
3. `goat curry` — regression: both presentations still shown.

## Task 4 — suite + commit + sync

- Full suite green, 0 skipped (count at time of writing: 646+ and
  growing from the parallel Aldi session — report the actual number).
- Commit: the sheet edits are DATA (no code changes in this round
  except none expected) — commit `tools/sort_butchery.py` (new tool)
  + any test touched + the report.
- Three-way sync: local ↔ GitHub push ↔ VPS scp + md5 verify.

## Task 5 — documentation + archive (user-mandated)

- Add ONE line to `PROJECT-MAP.md` (sheet section): butchery items are
  sorted protein-first (chicken → lamb → goat → beef → undecided),
  family-clustered (/kg and pack twins adjacent).
- `README.md` needs no change (data-only operation) — confirm, don't
  edit.
- Move THIS work-order file to `old md/2026-09-v2-rebuild/` at close.
- Report ends with: per-task status, the Telegram receipts, the parity
  audit line, and the three-way sync line.

## Scope guard

Round S1 only: Task 1–5 above. No schema changes, no new commands, no
ingest-logic changes (the auto-ingest spec is a SEPARATE work order),
no classification of the undecided items. STOP and report on any
contradiction with this file or `architecture-spec.md`.
