# AUTO-INGEST SPEC — watch-folder pipeline + the three ingest defects (fix session work order)

> Written 2026-09-11 after the MER1109260507 failure (user: "3 images took
> 45+ minutes and still got it wrong"). Evidence: VPS Claw transcript
> `d40ae3c1…topic-594.jsonl` (the multi-round manual rescue), VPS post log
> (3 × MER1109260507 entries, 08:06–08:09 Sydney), and the user's
> corrections ("i repeat not one or two each and every of those 20").

## Mission (the only acceptance that matters)

**User saves the shop's images into one folder. Everything else happens
without them.** No forwarding into Telegram topics, no commands, no
"not working" round trips, no manual sheet rescue. Target: images
dropped → Telegram summary posted, sheet correct, in ≤5 minutes total
human time = zero.

## What broke this morning (root causes from the transcript — the fix session MUST prove each is dead)

- **ID-1 — pack-deal semantics at ingest.** The board's prices are pack
  / multibuy deals ("2 for $11.99", "5kg for $19.99", "3kg for $32.99").
  The ingest must ALWAYS write, for /kg rows: the **per-kg rate** in the
  shop's special cell + the **pack deal terms** in that shop's tagged
  Comments segment ("[MER] multi buy 3kg for $32.99"). It must never
  write a raw pack price, never write per-ea for a /kg row, and never
  need a human to redo the maths. Single-divider rule: the parse emits
  bundle total + qty; the tab writer divides exactly once.
- **ID-2 — near-duplicate rows created over existing items.** This
  morning 13 rows (LD/master 144–157) were created for items that
  ALREADY existed (the sheet had "Whole chicken s9", "Beef Curry",
  "mid-wings"…). The ingest's reuse guard must be v2-native: before
  auto-creating any row, match the incoming name against existing rows
  with PLURAL-FOLDED, order-free token overlap, ignoring unit markers
  (/kg, /ea, pack sizes) and the halal prefix (source-based, added
  separately). On match → reuse the existing row + Item_Code (update
  prices + comments only). v1's `is_same_product` is proven too strict
  for this (returns False on "Halal Sliced Lamb Neck /kg" vs "Halal
  Lamb Necks /kg") — build the v2 matcher, with this exact pair as the
  regression test.
- **ID-3 — comment doubling + scrambled cells on re-merge.** "[MER]
  [MER] multi buy…" came from non-idempotent tag handling, and manual
  index math scrambled neighbouring rows. Rule: the comment merge is
  strip-then-append per shop (use `_strip_shop_segments` + append —
  never string-concatenate), and row writes go through the existing
  merge_store_tab path (which verifies its own post-state) — never
  hand-indexed grid writes.

## The pipeline to build

1. **PC watch-folder** (`tools/inbox_watcher.py`, runs on the Windows
   PC, auto-start optional): watches ONE folder (user's choice, e.g.
   `Desktop\shop-posts`). Any image (.jpg/.png/.webp) or text (.txt/.md)
   dropped there is pushed to the VPS inbox:
   `ssh myvps "mkdir -p …/data/local_deals_inbox/<CODE>"` + scp, where
   CODE = shop-less timestamped code (e.g. `AUTO110926HHMM`); the shop
   is resolved at ingest from the existing post-log/matching (or the
   user names the subfolder per shop — planner's call, ask the user).
2. **Auto-trigger**: after the push, the watcher runs the VPS ingest
   (`ssh myvps "docker exec openclaw-core python3 /app/tasks/ai-tools/
   grocery_price_cli.py local-deals --ingest <CODE>"`) and posts the
   usual Telegram summary to the local-deals topic. The Telegram topic
   remains the notification channel — the user reads results on their
   phone, zero round trips.
3. **Ingest hardening** (ID-1/2/3 above) lands in the same round — the
   watcher is only worth building on a pipeline that records correctly
   the first time.
4. **Watcher resilience**: single-instance lock; queue-then-retry on
   network failure (files wait in the folder until push succeeds);
   dedupe by file hash (the same image twice = one ingest); a one-line
   Windows startup story (Task Scheduler or Startup folder) — the user
   must never run it by hand.

## Mandatory process clauses (user directive 2026-09-11)

- **README.md + PROJECT-MAP.md MUST be updated** as part of DONE: the
  new folder, the zero-step flow, and the ID-1/2/3 behaviors documented
  in the living docs — not in this file.
- **This file is archived at close-out**: move it to
  `old md/2026-09-v2-rebuild/` when the verifier signs off. The root
  never accumulates round files.
- Suite green (currently 649+), every behavior above gets a regression
  test (ID-1: pack-deal board fixture → per-kg cell + comment; ID-2:
  the Sliced-Lamb-Necks pair → reuse, no new row; ID-3: re-merge
  idempotence; watcher: hash-dedupe + retry queue — offline-testable
  pieces only; the ssh push is a thin shell).
- STOP-and-report on any conflict with `architecture-spec.md` (v2).

## Already live (do NOT rebuild)

- Multibuy per-unit/per-kg recording + terms in Comments (verified on
  the live Merjan rows).
- Multibuy TERMS in the Telegram compare reply, phrased
  "min order 2kg for $29.99" next to the per-kg rate (2026-09-11).
- Meat vocabulary incl. curry/stirfry/necks + plural-fold matching;
  the Lamb Necks / Lamb Curry duplicates merged; parity ALIGNED.
