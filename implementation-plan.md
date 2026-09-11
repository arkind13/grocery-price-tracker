# Implementation Plan — Auto-ingest batch: watch-folder pipeline + ID-1/2/3 + S1–S16

- **Date:** 2026-09-11 · **Stage:** 02 Plan → 03 Code → 04 Checker
- **Inputs (read in the mandated order):** `auto-ingest-spec.md`
  (the work order — quotes below are verbatim from it),
  `architecture-spec.md` (v2 + §16 CRITICAL INFRASTRUCTURE),
  baseline suite **649 passed / 0 skipped** (verified this session),
  live-verified "Already live" list in the spec (multibuy per-kg
  recording + "min order …" compare wording — NOT rebuilt, only
  kept compatible).
- **Divergence check (mandatory, flagged not silent):**
  `architecture-spec.md` §"STAYS as-is" freezes the "twice-daily FB
  post detector (05:00/15:00 Sydney windows)" — this work order
  deliberately EVOLVES that detector into an auto-ingesting sweep
  (user directive 2026-09-11, newer primary source; charter rule 3:
  user directives govern over formalized specs). No other conflict
  found. **Not a STOP:** the spec explicitly mandates the change.
- **SCOPE GUARD:** local-deals ingest + detector messaging + the PC
  watcher ONLY. No new sheet columns, no master-tab layout change, no
  Woolworths/Coles/Aldi provider work, no v2_read/lookup changes
  beyond keeping comment formats compatible. M-items AI-M1…AI-M7 are
  BINDING; on any contradiction: STOP and report.
- **Carried proposals (unanswered user questions — one-word
  correctable later, spec-internal defaults used):**
  - **P1 (S5 ask):** "reply with the date, or 'open' to leave it
    undated" — spec's own wording (S5 row + message example).
  - **P2 (digest target):** local-deals topic only — spec pipeline
    §2 "posts the usual Telegram summary to the local-deals topic".
  - **P3 (S7):** "was $X → now $Y" change lines — spec matrix S7
    verbatim.
  - **P4 (shop resolution for watch-folder drops):** BOTH paths
    supported — shop subfolder (`shop-posts\Merjan\`) pins the shop;
    root drops mint a shop-less `AUTO…` code and the ingest ASKS in
    the digest (never guesses — the S10/S16 rule). Spec offered
    auto-resolve-or-subfolder; ask-on-ambiguous is the no-guess
    intersection.

## 0. Ground truth

| Fact | Consequence |
|------|-------------|
| `_canonical_match_index` (local_deals.py:2556) compares canonical-key EQUALITY; "Halal Sliced Lamb Neck /kg" ≠ "Halal Lamb Necks /kg" ({sliced} extra) → 13 duplicate rows this morning | ID-2 fix = layered matcher: canonical equality first, then plural-folded token CONTAINMENT (≥2 tokens on the smaller side), halal prefix + unit markers ignored; pack-size tokens stay (S9 separator) |
| `_multibuy_note` (local_deals.py:1358) hardcodes "/ea" in the rate suffix; spec comment format is "[MER] multi buy 3kg for $32.99" | ID-1 fix = unit-aware note: kg → "multi buy {qty}kg for ${total}" (no rate suffix); `_cell_for` already divides exactly once via `effective_unit_rate` (single-divider rule intact) |
| `_merge_comment_cell`/`_tag_note` never strip a tag embedded in the NOTE text; morning rescue produced "[MER] [MER] multi buy…" | ID-3 fix = `_tag_note` cleans `_TAG_RE` matches out of the note before tagging; merge stays strip-then-append per shop |
| Vision schema has board-level `valid_until` only; S6 needs ITEM-level dates | Extend prompt + validator: optional per-deal `valid_until`; `build_rows`/`_stamp_validity` per-deal machinery already exists (ingest stamps `c["valid_until"]` per deal) |
| Detector messages live in `run_daily_scan` (local_deals.py:463-526): "Save the post's picture…", heartbeat "…scan done — no new posts" | Retired/reworded per spec; internal `windows[key]="done"` STATE KEY is not a message and stays |
| Read side `v2_read._shop_note` strips the tag and renders note with "multi buy"→"min order" regex (v2_read.py:449) | Writer note "multi buy 3kg for $32.99" renders "min order 3kg for $32.99" — matches the live-verified wording; v2_read untouched |
| Sweep runs on the VPS in docker; `extract_post_deals` + `download_post_images` already fetch+parse posts there | Auto-ingest in the sweep reuses them — no new transport |
| CLI: workspace-root `grocery_price_cli.py`; watcher is PC-side `tools/inbox_watcher.py`; ssh alias `myvps` exists | Local vs VPS command split stays explicit per task |

## M-items (verbatim from auto-ingest-spec.md)

- **AI-M1:** "The ingest must ALWAYS write, for /kg rows: the **per-kg rate** in the shop's special cell + the **pack deal terms** in that shop's tagged Comments segment … It must never write a raw pack price, never write per-ea for a /kg row … Single-divider rule: the parse emits bundle total + qty; the tab writer divides exactly once."
- **AI-M2:** "before auto-creating any row, match the incoming name against existing rows with PLURAL-FOLDED, order-free token overlap, ignoring unit markers (/kg, /ea, pack sizes) and the halal prefix … On match → reuse the existing row + Item_Code (update prices + comments only) … with this exact pair as the regression test."
- **AI-M3:** "the comment merge is strip-then-append per shop (use `_strip_shop_segments` + append — never string-concatenate), and row writes go through the existing merge_store_tab path (which verifies its own post-state) — never hand-indexed grid writes."
- **AI-M4:** watcher — "watches ONE folder … pushed to the VPS inbox … single-instance lock; queue-then-retry on network failure (files wait in the folder until push succeeds); dedupe by file hash (the same image twice = one ingest); a one-line Windows startup story … the user must never run it by hand."
- **AI-M5:** "the 05:00/15:00 detector now AUTO-INGESTS every new post itself (vision + merge + parity) — it no longer asks you to save anything. **The word 'done' disappears from detector messages entirely**" + "ONE combined digest per window … per shop — items, prices, 'min order …' multibuy terms, per-item validity, standout comparisons vs Woolworths, and any QUESTIONS."
- **AI-M6:** every S1–S16 row "must be designed, tested, and answered in the Telegram reply; no silent paths".
- **AI-M7:** "README.md + PROJECT-MAP.md MUST be updated as part of DONE"; suite green (649+) with a regression test per behavior; this file archived at verifier sign-off (04 phase).

## Tasks

### T1 — (AI-M2, S8, S9) v2 reuse guard in `core/local_deals.py`

`_reuse_tokens(text) -> set[str]` (plural-folded `similarity_tokens`,
drop STOPWORDS/pure numbers/bare unit words kg|g|mg|ml|l|ea|each|pack,
drop "halal"; KEEP size tokens like "5kg" — S9 separator).
`_reuse_match_index(grid, name) -> int | None`: layer 1 exact
`canonical_key` equality (current behavior, first match wins); layer 2
token containment either direction with the smaller side ≥2 tokens,
tie-break most overlap, then earliest row. Switch `merge_store_tab`
(call site ~line 2654) and `set_store_prices` (~line 3014) to it;
`sync_dunya_site` stays canonical-exact (§18/A1 site names are clean).
`_canonical_match_index` remains (site sync + tests).

### T2 — (AI-M1) unit-aware multibuy note in `core/local_deals.py`

`_multibuy_note`: deal unit "kg" → `f"[multi buy {qty}kg for
{_money(total)}]"`; else current text. `_cell_for` unchanged (divides
once via `effective_unit_rate`). Verify command:
`pytest tests/test_local_deals.py -k multibuy_kg`.

### T3 — (AI-M1, S6, S10, S16) vision prompt + validator in `core/flyer_vision.py`

Prompt rules added: "'Nkg for $X' (min-weight deal on loose/per-kg
meat) → price_kind 'multibuy', multibuy_qty=N, unit 'kg', price=X (the
bundle total) — NEVER bulk_pack"; "bulk_pack ONLY for a PHYSICAL pack
(box/bag/tray product), never for 'Nkg for $X' deal wording"; "a deal
line may carry its own 'valid_until' (item-level date printed next to
the line) — YYYY-MM-DD or null". `_validate_deal`: accept optional
deal-level `valid_until` (YYYY-MM-DD or absent/None; error otherwise).

### T4 — (AI-M3) tag hygiene in `core/local_deals.py`

`_tag_note`: strip every `_TAG_RE` match out of the note text before
prepending the (single) shop tag. Idempotence preserved:
`_merge_comment_cell` already strip-then-append per shop.

### T5 — (S4, S6) item-level dates through the ingest in `core/local_deals.py`

`ingest_code`: per converted deal, `c["valid_until"] = deal-level
valid_until or post valid_until`. Row-2 stamp keeps newest dated post
(existing behavior = latest remaining; R2-6 sweep re-derives later).

### T6 — (S5, P1, P4) questions state in `core/local_deals.py`

`QUESTIONS_PATH = data/local_deals_questions.json`; helpers
`_load_questions/_save_questions`, `open_question(kind, code, file,
shop_key, text)`, `clear_questions(code, file=None)`. Kinds:
"expiry" (S5) and "shop" (P4 ambiguous AUTO drop). Every digest
appends unresolved questions until cleared.

### T7 — (AI-M5, S1–S3, S5–S12) digest renderer in `core/local_deals.py`

`_render_window_digest(sections, questions, label) -> list[str]`
(message chunks ≤4000, split at shop boundaries). Per shop section:
posts in post order — items with `min order …` terms + per-item
validity, "was $X → now $Y" change lines (P3), "notice only — no
prices" (S11), "image unreadable — forward a clearer version or
reply with the items as text" (S10/S16). Header per spec example
("🔍 Sweep 05:00 — …"). Standout comparisons appended from
`render_post1`. Questions block last. Never contains the word "done"
in detector-digest context.

### T8 — (AI-M4, P4, S14) ingest AUTO codes + digest summary in `core/local_deals.py`

`ingest_code`: accept shop-less codes (`AUTO…`): resolve shop=None →
parse WITHOUT writes, open a "shop" question, files stay pending
(retried when resolved). Shop-prefixed codes (watcher subfolders mint
`MER…` codes) behave as today. The immediate summary becomes a digest
(single shop). Change lines: capture the shop's special-column value
per matched row before merge → diff after.

### T9 — (S5, P1, P4) CLI: `--set-date … open` + `--resolve-shop` in `grocery_price_cli.py` + `core/local_deals.py`

`set_date_cmd`: literal "open" = record undated + clear expiry
question. `resolve_shop_cmd(code, shop)`: store resolution, run
ingest for that shop. CLI flags wired into `_cmd_local_deals`.

### T10 — (AI-M5) sweep auto-ingest in `core/local_deals.py::run_daily_scan`

After code minting: per new post `extract_post_deals(post, run_dir,
store_key)` (VPS downloads images itself); per shop ONE merge of all
its new posts (newest post wins — existing reversed-order rule);
S10/S16 failures flagged, no partial writes (a post's deals all-or-
nothing per file isolation already); ONE digest per window via T7.
Retired: "Want these prices? … Save the post's picture …", "Then send
me: CODE" text; heartbeat reworded "✅ Sweep {window} — no new posts…"
(no "done"). `USER_INBOX_ROOT_WIN` no longer appears in any message.

### T11 — (AI-M4, S13–S15) `tools/inbox_watcher.py` + `tools/install_inbox_watcher.ps1`

Pure core (offline-testable): `scan_batches(folder, settle_s,
now)` — group settled files (no new file for `settle_s`) by shop
subfolder; `file_hash(path)`; state `data/inbox_watcher_state.json`
(pushed hashes capped 500, pending queue, lock mtime). Loop: poll 10s
→ batch → push (ssh mkdir + scp; thin `_run(cmd)` subprocess wrapper,
mocked in tests) → trigger ingest (`ssh myvps "docker exec
openclaw-core python3 /app/tasks/ai-tools/grocery_price_cli.py
local-deals --ingest <CODE>"`). Failure → queue + 60s retry (S15).
Single-instance: lock file with PID + stale takeover. Codes: root =
`AUTO{ddmmyy}{HHMM}` (+_2 collisions), subfolder = shop 3-letter
code. Install: PowerShell one-liner registering a per-logon
scheduled task (hidden) — the one-line startup story.

### T12 — suite + docs

Full suite green (DELIVERED: 685 passed / 0 skipped, +36 new);
regressions counted separately from discoveries (charter rule 7) —
ZERO unintended regressions; 10 legacy expectations deliberately
updated, all spec-mandated: 4 detector rewording (digest model, no
'done'), 1 Q11 separate-row superseded by ID-2 halal-ignore, 5
comment-format unification to the spec's unbracketed '[MER] multi
buy 3kg for $32.99' segment (the only form v2_read renders as 'min
order …'). `README.md` (§ local-deals: the
zero-step flow, ID-1/2/3 behaviors, watcher, digest, questions) +
`PROJECT-MAP.md` (watch-folder, questions state file, AUTO codes).
Claw skill text referencing the retired save-into-inbox flow: check
`claw-skills/`, update + regenerate `claw_skills_easy.md` per
`.kilo/rules/04-claw-skills-doc-sync.md` if touched.

### T13 — three-way sync (standing rule)

Commit (leaving `data/ww_specials_report.txt` — live-run data —
untouched), push `feature/qrs-shop-multibuy`, scp changed runtime
files to the VPS mirror `/home/ubuntu/openclaw/tasks/ai-tools/…`
(checksum-verify). Never sync `.env`. Report sync status only.

## COMPLIANCE TABLE (M-item → task → test → verbatim quote)

| M-item | Task | Test name(s) | Verbatim quote (auto-ingest-spec.md) |
|--------|------|--------------|--------------------------------------|
| AI-M1 | T2, T3 | `test_multibuy_kg_cell_is_per_kg_rate` (asserts 32.99 never in the cell), `test_multibuy_kg_comment_terms`, `test_multibuy_kg_read_side_min_order` | "The ingest must ALWAYS write, for /kg rows: the **per-kg rate** in the shop's special cell + the **pack deal terms** in that shop's tagged Comments segment ('[MER] multi buy 3kg for $32.99')" |
| AI-M1 single divider | T2 | `test_multibuy_divides_exactly_once` | "Single-divider rule: the parse emits bundle total + qty; the tab writer divides exactly once." |
| AI-M2 | T1 | `test_lamb_neck_pair_reuses_row`, `test_reuse_keeps_item_code`, `test_pack_vs_kg_stay_separate_rows`, `test_beef_vs_lamb_curry_not_merged` | "v1's `is_same_product` is proven too strict for this (returns False on 'Halal Sliced Lamb Neck /kg' vs 'Halal Lamb Necks /kg') — build the v2 matcher, with this exact pair as the regression test." |
| AI-M3 | T4 | `test_remerge_idempotent_no_double_tag`, `test_pretagged_note_single_tag` | "the comment merge is strip-then-append per shop … never string-concatenate" |
| AI-M4 | T11 | `test_watcher_groups_settled_batch`, `test_watcher_hash_dedupe`, `test_watcher_retry_queue`, `test_watcher_single_instance_lock`, `test_watcher_codes`, `test_watcher_shop_subfolder_pins_code`, `test_watcher_unknown_shop_folder_ignored` | "single-instance lock; queue-then-retry on network failure … dedupe by file hash (the same image twice = one ingest); a one-line Windows startup story" |
| AI-M5 | T7, T10 | `test_three_images_one_post_one_digest`, `test_digest_no_done_word`, `test_lifecycle_codes_and_plain_message` (heartbeat, updated), `test_digest_format_spec_example` | "the 05:00/15:00 detector now AUTO-INGESTS every new post itself … **The word 'done' disappears from detector messages entirely**" |
| AI-M6 S1 | T7, T10 | `test_three_images_one_post_one_digest` | "All images under ONE code, ONE ingest pass, ONE merge — never 3 separate summaries" |
| AI-M6 S2 | T7, T10 | `test_two_posts_same_shop_newest_wins`, `test_missed_window_two_posts_both_notified` (updated) | "Each post = own code + own validity stamps; newest post's price wins on merge" |
| AI-M6 S3 | T7 | `test_two_shops_one_digest_sections` | "ONE combined digest, sections per shop; ingests are per-code" |
| AI-M6 S4 | T3, T5 | `test_item_level_dates_per_cell` | "Per-item/per-cell stamps — each item keeps its OWN till date" |
| AI-M6 S5 | T6, T9 | `test_unknown_expiry_ask_repeats`, `test_set_date_open_clears_question` | "The item still ingests (undated …) AND the digest ASKS you one question … The ask appears in EVERY digest until answered" |
| AI-M6 S6 | T3, T5 | `test_multiple_expiry_dates_one_post` | "each item keeps its OWN till date … the shop's row-2 stamp shows the LATEST remaining (never one date for all)" |
| AI-M6 S7 | T7 | `test_price_change_line_was_now` | "Newest post's price wins on merge; one row; digest shows the change ('was $X → now $Y')" |
| AI-M6 S8 | T1 | `test_cross_shop_one_row_both_columns` | "ONE item row, both shop columns filled (parity model §4.5)" |
| AI-M6 S9 | T1 | `test_pack_vs_kg_stay_separate_rows` | "Separate rows BY DESIGN (different pack = different product line)" |
| AI-M6 S10 | T10 | `test_vision_unreadable_no_writes_flagged` | "NO partial writes. Digest flags: 'image unreadable — forward a clearer version or reply with the items as text'" |
| AI-M6 S11 | T7 | `test_notice_only_no_prices` | "Detected, ingested as zero-item, digest says 'notice only — no prices'; no tab writes" |
| AI-M6 S12 | T7 | `test_notice_and_nonfood_render` | "Still ingested with the halal prefix (Q17: all butchery items, regardless of type)" |
| AI-M6 S13 | T11 | `test_watcher_single_instance_lock` | "Watcher queues (single-instance lock); files wait; ingests serialise — never two writers" |
| AI-M6 S14 | T11 | `test_watcher_hash_dedupe` | "File-hash dedupe: one ingest, one summary" |
| AI-M6 S15 | T11 | `test_watcher_retry_queue` | "Files queue in the folder until push succeeds; nothing lost, nothing duplicated" |
| AI-M6 S16 | T10 | `test_vision_unreadable_no_writes_flagged` | "Same as S10 — flag, ask, never write guesses" |
| AI-M7 | T12, T13 | suite run + git push + checksums | "README.md + PROJECT-MAP.md MUST be updated as part of DONE" / "Suite green (currently 649+)" |

**Self-check:** every M row carries a task, a named test, and a
verbatim quote; no empty/paraphrased cells. Regressions to be counted
separately at T12 (target zero beyond the mandated detector-wording
test updates, which are spec-mandated rewording, listed explicitly).
