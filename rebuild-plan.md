# Rebuild Plan — grocery tracker v2 (phased, time-boxed, days-sized)

- **Date:** 2026-09-09 · **Stage:** 01 Architect
- **Input:** `architecture-spec.md` (v2, 2026-09-09 — decision log §2 there; + §18 user-approved amendments A1–A3, 2026-09-09)
- **Status:** AWAITING USER APPROVAL — no coding starts until approved.
- **Standing rule for every round:** the system is FULLY FUNCTIONAL the
  moment each round ends (user rule, interview Q19). No round deletes a
  working path before its replacement exists.

**Round-1 note (deviation documented):** the work order sketched Round 1
as "comment fix + cleanup + sheet migration" but ALSO defined the first
coder task as the comment fix alone. This plan resolves the conflict using
the Q19 functional-after-every-round rule: Round 1 = comment fix + orphan
cleanup + FULL SHEET BACKUP (zero-risk, leaves v1 untouched and working);
the migration moves to Round 2, deletions to Round 3. Nothing is executed
out of an order that keeps the system usable.

| Round | Scope | Time-box |
|-------|-------|----------|
| 1 | Local_Deals comment-lifecycle fix + orphan cleanup + full sheet backup | 0.5 day |
| 2 | Sheet migration v2 (archive, columns, halal renames, parity rows, codes, alignment) + minimal v2 read path | 1 day |
| 3 | Command surface v2 (6 verbs + batch engine + list renderer + style kit) + DELETION MANIFEST execution | 1.5 days |
| 4 | Wednesday v2 + skill rewrite + VPS sync | 1 day |
| 5 | Verification (speed budget + live Telegram) + FINAL TIDY | 0.5 day |
| | **Total** | **~4.5 days** |

### Round status (living tracker — update at every round close; same table every round)

| Round | Scope (one line) | Time-box | Status | Closed |
|-------|------------------|----------|--------|--------|
| 1 | Comment lifecycle + orphan cleanup + backup system (PC + VPS + daily cron) | 0.5 d | ✅ **DONE** — checker PASS, 1319 green ×10 runs, tracker `933af6e` / parent `5342201` | 2026-09-09 |
| 2 | Sheet migration v2 (gates G1–G3) + `price`/`list` read path + parity audit | 1 d | ✅ **DONE** — user sheet-confirmed; 12 keeps + 127 coded rows, 139/139 parity ALIGNED, `list` = 105 entries, 1361 green / 0 skipped, tracker `5bda9ae` / parent `265e975`, VPS md5-verified | 2026-09-10 |
| 3 | 6 verbs + batch engine + style kit + deletion manifest | 1.5 d | ⬜ pending | — |
| 4 | Wednesday v2 + skills rewrite + VPS sync | 1 d | ⬜ pending | — |
| 5 | Speed-budget verification + FINAL TIDY | 0.5 d | ⬜ pending | — |

---

## Round 1 — Local_Deals comment lifecycle + backup (FIRST CODER TASK)

**Scope (spec §9/§13 context):**
1. Audit EVERY removal/clearing path that can drop a price without its
   shop-tagged Comments segment: expire sweep, new-post merge that drops
   an item, plain reprice, item removal. Eliminate any path that can
   orphan a comment.
2. Clear the known orphan residue: `[FRU]` multi-buy comments on empty
   cells — Local_Deals rows 115 (Celery) and 116 (Carrots 1kg Bag) —
   plus a scan for any other empty-cell comment segments.
3. One regression test per audited path (4+ new tests).
4. **Test-hygiene riders (spec §18/A3):** refresh the date-rotted
   specials fixture to a rolling date; de-flake the scan-window timing
   test (larger offset). Suite must be fully green (only Round-3-known
   nits existed; after this round, none).
4. **Full Google Sheet backup**: copy the spreadsheet (all 4 tabs) to
   `grocery-tracker-backup-YYYY-MM-DD`; verify by row/column counts of
   every tab. This backup is the safety net for Round 2 and satisfies
   the work order's backup deliverable.

**Acceptance criteria:** no code path can orphan a comment (each path has
a test proving the comment dies with its price); rows 115/116 clean; a
full-sheet scan finds zero empty-cell comment segments; backup exists and
verifies; offline suite green.

**Verification:** run the suite; `local-deals --expire-sweep` dry-run on
the live tab; before/after diff of the Comments column.

## Round 2 — Sheet migration v2 (backup from Round 1 is the net)

**Scope (spec §3/§4/§5):**
0. Backup freshness check as STEP 0: local JSON backup + VPS offsite
   copy + the daily 03:17 VPS cron all confirmed present — STOP if any
   is missing. Every destructive step below is a **USER GATE** in the
   coder session: printed preview + explicit user confirmation before
   executing (stay/leave list, halal rename preview, column drop).
   Mark each gate 'USER GATE' in the work order.
1. Print the stay/leave list (sub-category rule, Q1) → user confirms
   one time.
2. Create the `Archive` tab; copy ALL 112 current rows with all 19
   columns; delete the ~80 retired rows from Products_Master.
3. Drop columns E, F, J, K, L, N; remap every code reference to the new
   13-column layout (spec §3.1).
4. Rename the LOCAL side: butchery items → `halal xxx` (printed preview
   first). The user manually matches/renames EXISTING master rows (Q10).
5. Auto-create blank master rows + Item_Codes for every local item with
   no master match (Q26) — including the Dunya site catalogue rows
   (Q18) — names per the source-prefix rule.
6. Add Local_Deals col K `Item_Code`; backfill for every paired row.
7. Impose positional alignment (spec §3.3): master row N ↔ Local_Deals
   row N+1; mirror-sort both tabs to the same order; Wool-only rows get
   blank Local_Deals rows.
8. Ship the MINIMAL v2 read path in the same round: sheet-only lookup +
   `list` render (so the system answers questions the moment migration
   ends — Q19 rule). v1 read paths that reference dead columns are
   disabled at dispatch with a one-line notice.

**Acceptance criteria:** parity audit passes — row counts equal (offset
+1), every Local_Deals row carries a resolvable code, every list rule
case (§6) renders correctly; backup untouched; user confirms the
stay/leave and rename previews; lookup + list answer from the live sheet.

**Verification:** parity audit utility (counts + codes + spot pairs);
`list` output eyeballed against the sheet; suite green with remapped
column tests.

## Round 3 — Command surface v2 + DELETION MANIFEST

**Scope (spec §7/§8/§11/§13):**
1. The 6 verbs: default lookup, `live` (≤3/store, provider-list design
   for the §15 future clause), `list`, `specials`, `batch` (done/gone/
   rename/remove/ignore — spec §4 semantics), `ignored`.
2. Telegram style kit v2 (§11) with tests.
3. Execute the FULL deletion manifest (§13): commands, core modules,
   state files (archive copies first), cron + VPS reminder script,
   ceremony code paths. `claw_skills_easy.md` regenerated per the
   standing rule.
4. Prune tests of deleted code; add tests: batch engine per verdict,
   list rule cases, ingest auto-create + prefix, GONE semantics, live
   no-write guarantee.

**Acceptance criteria:** every verb answers within budget on the live
sheet; batch executes mixed verdicts in ONE call with per-code replies;
zero references remain to deleted commands/files (grep-clean);
`claw-skills` docs regenerated + synced.

**Verification:** live Telegram end-to-end (3 queries + one batch);
`grep -r` sweep for dead symbols; suite green.

## Round 4 — Wednesday v2 + skills + VPS

**Scope (spec §10):**
1. `wednesday` v2: WW docx + specials docx → prices/markers/deal rates →
   specials message (topic 206) + ONE list (topic 208) + parity warning
   line. No pause, no scp, no queues. ≤30s.
2. Rewrite `claw-skills/grocery-price/SKILL.md` for the 6 verbs + NL
   routing + the no-pre-investigation rule; touch `local-deals/SKILL.md`
   only where the prefix rule changed wording.
3. VPS sync (scp + checksum): CLI, core/extractors, skills; container
   needs no restart (live bind mount); remove the reminder cron + VPS
   script; run the faithful Telegram test via `openclaw.mjs agent`.

**Acceptance criteria:** a dry Wednesday run posts exactly two messages
and takes ≤30s; the VPS md5s match local; the reminder cron is gone
(`crontab -l` proof); live Telegram replies correct.

**Verification:** timed local run + timed live run; three-way sync check
(local git ↔ GitHub ↔ VPS checksums).

## Round 5 — Verification + FINAL TIDY

**Scope:**
1. Measure the speed budget (§12) on live paths; any miss = fix before
   close (a budget miss is a wrong design choice, not a tuning note).
2. Full regression: offline suite + live spot checks (lookup, live,
   list, batch, Wednesday, ingest of a real inbox post).
3. FINAL TIDY (mandatory): move ALL rebuild artifacts (arch-prompt.md,
   this plan, coder reports, verification reports) into
   `old md/2026-09-v2-rebuild/`; update the living docs (README,
   PROJECT-MAP, architecture-spec pointer notes, parent test.md) so the
   tracker root holds ONLY living documents.
4. Three-way sync closes the round: local commit + GitHub push + VPS
   mirror checksum-verified.

**Acceptance criteria:** every budget target measured and met; suite
green; root contains only living docs; three-way sync reported in sync.

**Verification:** this round IS the verification step; the checker (04)
signs off against this plan's acceptance criteria.

---

## Speed budget (work-order section — binding targets)

| Operation | Target | Enforced/measured in |
|---|---|---|
| Sheet lookup reply | ≤10s | Round 3 build, Round 5 measure |
| Live search reply | ≤20s | Round 3 build, Round 5 measure |
| Batch correction | ≤10s | Round 3 build, Round 5 measure |
| Wednesday run | ≤30s | Round 4 build, Round 4+5 measure |
| One-list render | ≤5s | Round 2 build, Round 5 measure |

## Rules the coder carries through every round

- Docs-only decisions live in `architecture-spec.md` — never re-litigate
  them; if reality contradicts the spec, STOP and report, don't adapt
  silently.
- Full sheet backup (Round 1) is never modified; migration writes only
  per spec.
- No new state files, queues, or ledgers — anything that smells like one
  is a design error (§0 law).
- Every round ends functional; every deletion is preceded by its archive
  copy; secrets are never printed, committed, or synced.
- The same rule as this plan's header applies downstream: `architecture-
  spec.md` is always overwritten in place, never renamed or forked.
