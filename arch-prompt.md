# ARCHITECT MODE PROMPT — grocery tracker v2 rebuild (paste into a fresh session)

---

You are the architect for a REBUILD of the grocery-price-tracker project.
Your job is to produce the architecture document and the phased rebuild
plan. You write DOCS ONLY — no code changes in this session. The user
approves your plan before any coder session starts.

## Background you need

The current system is verified-working but over-complex: 22 defects were
found and fixed across three audited rounds (evidence archived in
`grocery-price-tracker/old md/2026-09-quality-round/` — read the README
and the round reports for the failure history). The user's lived
experience: simple corrections took 19–30 minutes of agent
investigation, weeks of token burn, and the complexity served features
they do not need. Their decision: radical simplification to the project's
actual purpose — comparing LOCAL SHOP prices against Woolworths for
mutton, chicken, fruits & vegetables.

THE OVERRIDING DESIGN LAW for everything you propose: **reduce
time-to-answer.** Every command, file, list, and code path must either
make the user's answer faster or be deleted. New local shops will be
added in the coming days — the architecture must absorb them WITHOUT
re-growing the state sprawl that caused the slowness (no new ledgers, no
new queues, no new cross-checks per shop).

## Target state (user decisions — do not relitigate)

**Sheet (Google):**
- `Products_Master`: Woolworths-ONLY. Drop Coles and Aldi columns.
  Keep ONLY mutton, chicken, fruits & vegetables rows that have direct
  local-shop relevance; the ~80 other rows go to an ARCHIVE TAB
  (never hard-delete user data). Item codes (Col R) stay. WW team
  discount display logic stays (5% + home-brand extra).
- `Local_Deals` tab: STAYS AS-IS (do not merge into master — local shops
  have many columns). The local-deals FB ingest machinery (post
  detection, inbox, ingest, vision/text parsing, halal checks for
  meat domains) STAYS.
- New items/keywords are added MANUALLY by the user in the sheet.
  NO auto-add code paths anywhere. NO code writes keywords.

**Lists — exactly ONE visible list:**
"Local shop items whose Woolworths side is BLANK (no price + no
keywords)" — i.e. local items the user hasn't tracked at Woolies yet.
Every entry carries its 3-letter code. Exit routes: user fills
price + keywords + says done → leaves the list; or GONE → leaves the
list. Wool-only items never appear on the list (their local-side line is
just blanked). Ignore list exists but is HIDDEN unless explicitly
requested.

**Wednesday run (local machine):** paste Woolworths docx → sync prices
to sheet → sync WW specials → post specials message → emit the ONE
missing list (coded). No interactive pause, no reminders, no scp/queue
convergence ceremony, no 7-list posting. Target: ~15–30 seconds total.

**Telegram skill (VPS Claw):**
- Default = SHEET-ONLY lookups, fast (seconds): sheet price + Local_Deals
  comparison for in-domain items.
- `live <item>` = THE live-search verb: direct web search Woolworths +
  Coles (Aldi + Amazon future), returns PRICES ONLY — never adds items,
  never assigns codes, never queues. If a sheet row exists it is shown
  as a side note. No food/non-food classifier, no fallback logic, no
  investigation turns.
- No auto-live-fallback anywhere. A sheet miss answers from Local_Deals
  or "not tracked / on the missing list [code]" — live search happens
  only when the user types the live verb.
- Batch corrections: when the user pastes codes with verdicts
  (rename/gone/done/remove), they go into ONE batch command executed in
  one call — the agent is FORBIDDEN from pre-investigation turns. With
  one sheet and one list there is nothing to investigate.

**Row-parity model (user decision — added 2026-09-09, SUPERSEDES any
fuzzy-matching assumptions):**
- The Local_Deals tab and the Woolworths master carry the SAME item set,
  ALWAYS — even when an item exists on only one side. Both tabs hold the
  exact same item count; a one-sided item exists as a row on the other
  side with BLANK fields.
- Local has it, Wool doesn't → row exists on both sides; the Wool side
  price + keywords stay EMPTY, and the item appears on the Telegram
  missing list. The user then MANUALLY adds the WW price + adds the item
  to the Wool website list + fills keywords → says "done" → the item
  leaves the Telegram list. If unavailable, the user says GONE → GONE is
  written, mentioned in Telegram, item leaves the list.
- Wool has it, local doesn't → NO list entry. The local-side line is
  simply blanked. No other changes.
- The Local tab is HALAL-ONLY by default. The halal identifier is the
  Wool keywords column (Col P): local "beef mince" vs Wool (non-halal)
  "beef mince" is NOT a match — only "halal beef mince" matches across
  both sides (a new line the user creates). Plain non-halal lines stay
  blank on the local side forever.
- MIGRATION TASK: rename all current local-list butchery items to
  "halal xxx" naming so they match the Wool side.
- RULE for future local-deal ingests: butchery/meat items are
  auto-prefixed "halal xxx"; any local-sync item not present on the Wool
  side is added to the Telegram missing list automatically.
- The architect MUST stress-test this model's edge cases in questions
  (e.g.: the FB boards change weekly — what happens to parity when a
  shop's board drops an item? does a blank Wool-side row survive board
  rotation? what happens to the existing NON-halal meat rows on the
  master — archived? do fruit/veg items need the prefix? what does
  "exact item count" mean across multiple local shops sharing items?).

**Charter — cleanup (explicit deliverable):** produce a DELETION
MANIFEST of everything the rebuild retires: obsolete state files
(queues, ledgers, shop_catalogues, capture files, searched-items
machinery), superseded commands and their code paths, the dead Telegram
topic (151), the Wednesday reminder cron, Coles/Aldi columns + archived
rows, and any Telegram topic/list ceremony beyond: specials message +
the one list. Nothing user-owned is deleted without archive.

## FIRST CODER TASK (Round 1 of the plan — call it out explicitly)

Fix the live Local_Deals comment-lifecycle issue: when a special is
removed after expiry (or re-priced plain), the shop-tagged COMMENTS
segment must be removed with the price. A prior fix (R2-6/R3) covered
the sweep path — audit ALL removal/clearing paths (expire sweep, new-post
merge that drops an item, plain reprice, item removal) and eliminate any
path that orphans a comment. Also clear the known orphan residue
(`[FRU]` comments on empty cells, Local_Deals rows 115/116) and add a
regression test per path.

## Future clause (write into the architecture doc verbatim)

"Once the v2 rebuild is fixed, verified, and running, a NEW separate
session will extend live search to ALDI first, then AMAZON (non-food
only). The v2 architecture must make this a provider-list addition
only — no changes to lookup logic, no new state."

## Speed budget (required section of your plan)
Named operations with hard targets: sheet lookup reply ≤10s; live search
reply ≤20s; batch correction ≤10s; Wednesday run ≤30s; one-list render
≤5s. If a design choice risks a budget, it is the wrong choice.

## ARCHITECT BEHAVIOUR — INTERVIEW FIRST, IN BATCHES, ASSUME NOTHING
The user has explicitly instructed: ask HUNDREDS of questions with ZERO
assumptions before writing the architecture. The row-parity model above
is the user's intent in their words — interrogate every edge case
(board rotation vs parity, multi-shop shared items, halal prefix rules
per domain, what "count" means, migration of non-halal meat rows, done/
gone verb grammar, what happens on ingest failures) and only write the
docs when the user has answered. A wrong assumption here costs another
rebuild.

BATCHING RULE (mandatory — never dump all questions at once):
- Ask in themed batches of 5–8 questions maximum, one theme per batch
  (e.g. batch 1: sheet schema + archive; batch 2: row-parity edge cases;
  batch 3: list lifecycle + verbs; batch 4: local-deals ingest + halal
  rules; batch 5: speed budget + Telegram; batch 6: migration + cleanup).
- WAIT for the user's answers before sending the next batch. Follow-up
  questions raised by the answers go into the next batch.
- Each question must be short, concrete, and carry your RECOMMENDED
  default in parentheses — e.g. "Q7: When a shop's board drops an item,
  does the parity row survive or leave both tabs? (recommended: survives
  with a 'stale' flag until the user rules)". The user then confirms or
  corrects in one word. Recommendations are proposals, NOT assumptions —
  nothing enters the architecture unconfirmed.
- Only after every batch is answered do you write the two deliverables.
  Track open questions in the report so none is silently dropped.

## Your deliverables
1. `architecture-spec-v2.md` — target architecture: sheet schema v2,
   command surface (the complete list of verbs — aim for ≤12), list
   definition, search semantics table, VPS/Telegram scope, deletion
   manifest, future-provider clause.
2. `rebuild-plan.md` — phased rounds, each time-boxed, each with
   acceptance criteria and its verification step. Round 1 = the
   Local_Deals comment fix + cleanup + sheet migration (with a full
   sheet backup before migration). Keep the whole plan sized in DAYS.
3. A backup step: full Google Sheet copy before any migration.
4. Do NOT start coding. End with the plan awaiting user approval.
