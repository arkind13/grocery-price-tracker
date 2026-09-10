# Implementation Plan — v2 Round 4: Wednesday v2 + skills + VPS sync + live Telegram test

- **Date:** 2026-09-10 · **Stage:** 02 Plan → 03 Code
- **Inputs:** `architecture-spec.md` (v2 + §18 A1–A3 + §16 CRITICAL
  INFRASTRUCTURE clause), `rebuild-plan.md` (Round 4 scope — RECONCILED:
  the reminder-cron/VPS-script removal listed there was executed in
  Round 3 D5 and is verify-only now), Round-3 close-out (tracker
  `bf61e4a`, checker re-audit PASS — 580 green / 0 skipped, exactly 7
  CLI verbs, grep-clean 0, parity ALIGNED, 13/13 VPS md5s, skills
  doc-check OK).
- **SCOPE GUARD:** Round 4 ONLY. No new verbs (the 7-command surface is
  final), no deletions, no speed-budget campaign (Round 5), no final
  tidy (Round 5), no sheet-structure changes. §16 CRITICAL
  INFRASTRUCTURE (GCP project, GitHub repos, VPS, the 03:17 backup
  cron) is load-bearing — NEVER deleted/archived/paused; a backup-cron
  failure is a page, not noise. **On any spec contradiction: STOP and
  report.**
- **Rule:** this file is overwritten in place each round.

## 0. Ground truth (R3 close) + consequences

| Fact | Consequence |
|------|-------------|
| CLI = exactly 7 verbs {price, list, live, batch, ignored, specials, local-deals}; v2_read/v2_batch/v2_live + style kit + item_codes registry all live | Wednesday v2 is a pure ADDITION (one new module + one re-added subcommand); the list post REUSES `v2_read.missing_list + render_list`; codes via `core/item_codes.py` |
| No topic-routing constants exist anywhere (grep 206/208 = 0 hits) | `v2_wednesday` defines the two topic IDs as constants with env override (§17.4: specials→206, list→208) |
| `core/local_deals.py::_send_message(bot_token, chat_id, text, thread_id)` returns a parsed receipt | Wednesday posts reuse it (import; no new sender) |
| `extractors/doc_parser.py` (parse_docx/parse_docx_cache/auto_parse) + `extractors/specials_parser.py` (detect_special/classify_special) + `core/multibuy.py` all SURVIVED R3 | The whole parse chain is on kept modules — Wednesday v2 wires them, reinvents nothing |
| Real inputs on disk: `Woolworths.docx` (Sep 4), `Woolworths_Specials.docx` (Sep 2) | Live fire may use them AFTER the in-session freshness question (W4.1); the user may paste this week's first |
| Skills already carry the 6-verb routing + no-pre-investigation rule (checker B6 PASS) | K1 is an ADDITIVE Wednesday section + verification, NOT a rewrite |
| Parity 139/139 ALIGNED; day-one list = 105; `ignored` = 34 hidden | The A2 parity step's auto-mirror/alert paths get their first live wiring |

**"Exactly two messages" reconciliation (binding):** Wednesday makes
exactly TWO posts — specials (topic 206) and the ONE list (topic 208).
The list post may split into ≤4000-char chunks per the style kit
(105 entries); every chunk carries thread 208. Two POSTS, N physical
messages — that is the acceptance wording's intent.

## W0 — Backup + canary gate (STOP-gate; scripted; NEVER modifies anything)

```bash
cd "C:/Users/User.DESKTOP-R2G441H/Documents/AI related/grocery-price-tracker"
"$USERPROFILE/anaconda3/python.exe" tools/sheet_backup.py          # exit 0; today's JSON
ssh myvps 'crontab -l'        # MUST show the 03:17 sheet-backup line AND the daily-scan line; MUST NOT show wednesday_reminder
ssh myvps 'ls /home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/backups/'
```
STOP conditions: backup exit ≠ 0; either cron line missing; any
wednesday_reminder leftover (would contradict R3 D5 — STOP and report).
This gate READS ONLY — the canary cron is never touched (§16).

## W1 — `core/v2_wednesday.py` (NEW; the §10 pipeline)

```python
"""Wednesday v2 (spec §10): parse the two pasted Woolworths docx files,
sync prices/markers/deal-rates to the 13-col master, run the A2 parity
step, post specials (topic 206) + the ONE list (topic 208). No pause,
no scp, no queues. ≤30s."""

SPECIALS_TOPIC_ID = 206   # env override TELEGRAM_SPECIALS_TOPIC_ID
LISTS_TOPIC_ID = 208      # env override TELEGRAM_LISTS_TOPIC_ID

def parse_inputs() -> tuple[list, list]:
    """(main_items, specials_items) — main via
    extractors.doc_parser.parse_docx_cache('woolworths') (or auto_parse
    on the file — match the existing doc_parser tests' entry);
    specials via extractors.specials_parser (its doc-level entry; if
    none, parse_docx + per-item detect_special/classify_special)."""

def match_index(master_grid: list[list]) -> dict:
    """normalized keyword (col G idx 6) -> row index. Case-insensitive,
    whitespace-collapsed. Rows with a blank keyword are NOT indexed."""

def plan_sync(master_grid, main_items, specials_items,
              today: date) -> dict:
    """Pure grid-in plan-out (offline-testable). Returns
    {'writes': [(idx, col, value)], 'matched': int, 'na': [names],
    'unavailable': [names], 'multibuy': [names], 'cleared_h': [names],
    'unmatched': [names]}.
    Semantics (spec §10 + §17.6 + §4.3):
    - main-docx item whose keyword matches -> D = price (2-dp); a real
      price OVERWRITES GONE / N/A / unavailable markers.
    - keyword-matched row ABSENT from the main docx -> D = 'N/A <today>'
      — UNLESS its current D is 'GONE' (GONE survives until a real
      price returns; never N/A'd).
    - present but no usable price -> D = 'unavailable <today>'.
    - specials-docx match with multibuy terms (qty/total parsed from
      special_desc, e.g. '2 for $6'; rate via core.multibuy
      effective_unit_rate) -> D = per-unit rate, H = 'multi-buy N/$X'.
    - specials match without multibuy -> H = special_desc.
    - row whose H carried terms but is ABSENT from the new specials
      docx -> H cleared (deal ended; D already holds the main-docx
      normal price).
    - docx line with NO keyword match -> 'unmatched' report only —
      NEVER a write (no auto-add, §4.2)."""

def apply_writes(master_ws, master_grid, writes: list) -> None:
    """One clear+update (A1:M) when writes exist; no-op otherwise."""

def parity_step(master_grid, ld_grid, ld_ws) -> str:
    """tools/parity_audit.audit on the two grids. ALIGNED -> one clean
    line, continue. bottom_append -> AUTO-MIRROR during the run (blank
    counterpart rows appended, codes reserved via core.item_codes,
    report lines, continue — §18/A2). middle_insert -> print the
    VERBATIM A2 alert and ABORT: no writes, no posts, exit 1."""

def render_specials_post() -> str    # specials_reporter data + style kit
def run(dry_run: bool = False, send: bool = True) -> int
    """Full pipeline: parse -> read both tabs -> parity_step ->
    plan_sync -> apply_writes (skipped in dry-run) -> TWO posts via
    core.local_deals._send_message (skipped in dry-run / send=False;
    list post = v2_read.read_tabs + missing_list + render_list).
    Prints the receipt line per post ('[telegram] ok message_id=…').
    Console always ends with: matched/unmatched/marker counts + the
    unmatched names + elapsed seconds."""
```

## W2 — CLI: `wednesday` re-added (`grocery_price_cli.py`)

`wednesday [--dry-run] [--no-telegram]` → thin handler calling
`v2_wednesday.run`. `--dry-run` = parse + match + full would-do report,
ZERO writes/posts. `--help` must list EIGHT subcommands after this.

**Verify:** `py_compile` both files; `grocery_price_cli.py --help`.

## W3 — Tests (`grocery-price-tracker/tests/test_v2_wednesday.py`, NEW; mandatory, zero-skip, offline)

Fixtures: docx built in-test via python-docx (mirror the existing
doc_parser test patterns in `tests/test_extractors.py`); FakeSheet
pairs (13-col master + 11-col LD) mirroring `tests/test_v2_batch.py`'s
harness. Cases (each named, each asserting):
1. keyword match writes D price (2-dp).
2. absent keyword-row → `N/A <date>`; GONE row absent → GONE PRESERVED.
3. real price overwrites GONE and overwrites an old `N/A` marker.
4. listed-but-unpriced → `unavailable <date>`.
5. multibuy special → D = rate + H = `multi-buy N/$X` (e.g. 2/$6 → 3.00).
6. deal ended → H cleared, D = normal price.
7. unmatched docx line → appears in `unmatched`, ZERO writes for it.
8. specials-only item with no keyword → report-only, no write.
9. parity ALIGNED → run completes; two post renders produced.
10. parity bottom_append → blank rows mirrored on BOTH tabs with codes
    (registry patched in-test via `REGISTRY_PATH`), counts equal after.
11. parity middle_insert → the VERBATIM A2 alert, run exits 1, no
    writes, no posts (fake sender asserts zero calls).
12. dry-run → no writes, no posts, full report.
13. list post render >4000 chars → split chunks, each ≤4000, all
    styled per kit.
Full suite expectation: **580 + ~13 green, 0 skipped** (report count).

## W4 — Live fire sequence (scripted; in-session)

1. **Freshness question (console, not a gate):** confirm with the user
   whether `Woolworths.docx` (Sep 4) / `Woolworths_Specials.docx`
   (Sep 2) are this week's lists; if not, the user pastes fresh ones
   first (their action, waited on).
2. `grocery_price_cli.py wednesday --dry-run` → full report; the user
   eyeballs the matched/unmatched plan.
3. `grocery_price_cli.py wednesday` (timed — MUST be ≤30s; report the
   elapsed seconds). Verify: exactly two posts landed (specials in
   topic 206, list chunks in topic 208; receipt lines quoted
   verbatim in the report); sheet D/H updated; parity audit →
   `tools/migrate_v2.py audit` ALIGNED after the run.

## K1 — Skills (additive; the 6-verb rewrite already landed in R3)

1. `claw-skills/grocery-price/SKILL.md` — ADD a "Wednesday weekly run"
   section: inputs (the two docx pastes), what posts arrive (206/208),
   the ≤30s budget, and the A2 middle-insert alert meaning + the manual
   fix (move the row to the bottom, rerun). Verify the 6-verb routing +
   no-pre-investigation rule are already present (checker B6 PASS) —
   do not rewrite them.
2. `claw-skills/local-deals/SKILL.md` — verify the halal-prefix wording
   is current (R3 B6 already synced; touch ONLY if stale).
3. Regenerate `claw-skills/claw_skills_easy.md` per the standing
   AGENTS.md doc-sync rule (`skills_doc.py --check` must report OK).

## V1 — VPS sync + canary re-verify (Remote)

```bash
scp grocery_price_cli.py myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery_price_cli.py
scp grocery-price-tracker/core/v2_wednesday.py myvps:/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/core/v2_wednesday.py
scp "claw-skills/grocery-price/SKILL.md" "claw-skills/local-deals/SKILL.md" "claw-skills/claw_skills_easy.md" \
    myvps:/home/ubuntu/openclaw/tasks/ai-tools/claw-skills/   # into their per-skill dirs
# md5-verify every scp'd file local ↔ VPS; ssh myvps 'crontab -l' (canary lines still present)
```
No container restart (live bind mount). The canary cron is verified,
never touched.

## V2 — Faithful live Telegram battery (the plan's end-to-end test)

```bash
ssh myvps 'docker exec openclaw-core node /app/openclaw.mjs agent --channel telegram --to 1594431983 --message "<Q>" --deliver'
```
Battery (NL routing through the REAL skill, replies delivered to the
user's Telegram — quote each reply in the report):
1. "how much is halal beef mince" → styled lookup block.
2. "live search chicken breast" → ≤3/store prices, sheet side-note.
3. "show me the list" → styled missing list (first chunk).
4. "what's on special at Woolies" → specials.
5. batch verify-only: pick a real code from the list reply →
   "<CODE> done" → the honest not-done/blank report, ZERO writes.

## A — Close-out + acceptance

Suite green → tracker commit (core/v2_wednesday.py, tests,
implementation-plan.md, rebuild-plan.md reconciliation) + push; parent
commit (grocery_price_cli.py, claw-skills ×3, test.md entry) + push;
md5 table in the report; three-way sync status line.

**Acceptance criteria (rebuild-plan Round 4):**
1. A (real, timed) Wednesday run posts exactly two messages and takes
   ≤30s (elapsed seconds + receipt lines in the report).
2. The VPS md5s match local (every scp'd file).
3. The reminder cron is STILL gone (`crontab -l` proof — verify-only;
   removed in R3 D5, not redone here).
4. Live Telegram replies correct (all 5 battery queries quoted).
5. Parity audit ALIGNED after the Wednesday run; suite green 0 skipped.

## Rollback

Wednesday writes D/H cells only (markers/prices/deal terms — the
routine weekly sync; a wrong run is corrected by the next paste or by
`batch`/manual cell edits). Parity auto-mirror rows are additive. The
03:17 backup JSON from the morning of the run is the point-in-time
net. Code: git revert (both repos).
