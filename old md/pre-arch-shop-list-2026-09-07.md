# Pre-Arch — Shopping List Rebuild (speed, sub-categories, keyword/todo handshake)

- **Date:** 2026-09-07 (test evidence from the live session 09:12–10:02
  Sydney + read-only harness runs the same day)
- **Author:** 00 Tester Agent (test phase only — no production code
  changed; every harness below ran READ-ONLY against the live sheet,
  writes monkeypatched)
- **Mission (user's TEST, verbatim):** "Why is the shopping list
  process so slow it took 1 hour to get 10 items the process is simple
  I give names it searches subcategory, gives me list one by one, I
  tell preferred, items not on list live search, get pricing, adds a
  new row, adds pricing, asks if i want the item to be added to
  todolist, gives me my shopping list. Less than 5 mins why so
  complicated. Go through the whole process run some tests and make it
  more quicker. Try building shopping list with many many items and
  combinations I need to get to know the exact issue why is it
  happening again and again."
- **Evidence artifacts:**
  - `tests/diagnose_shop_flow.py` — read-only harness (T1–T5)
  - Claw session transcript `9cc5c5fd…-topic-239` (VPS
    `/home/node/.openclaw/agents/main/sessions/`) — the 1-hour session

---

# PART A — Test evidence

## A1. The 1-hour session, decomposed (log truth)

User list sent 09:12:30, session aborted 10:01:57 (= **49 min**, plus
the earlier turns that day). Where the time actually went:

| Window | What happened | Time |
|---|---|---|
| 09:12–09:13 | `optimize` run 1 (sheet+classification) — fine | ~1 min |
| 09:15–09:22 | **one-by-one shop flow, 8 items** — `shop` + `prefer` per item, ~50 s/item incl. model turns | ~7 min |
| 09:28–09:36 | user gave 2 exact-product changes → **agent read the CLI source code** (7 grep/sed calls) because NO CLI command covers "write these exact WW+Coles names for this row" | ~8 min |
| 09:36–09:44 | live searches, serial, incl. off-scope ones (sugar, pancake, olive — not asked) + raw-price discovery (more code reading) | ~8 min |
| 09:44–09:48 | **manual gspread writes** (batch_update / append_row hand-rolled, one format-error retry, one post-write fix-up) | ~4 min |
| 09:49–09:52 | final `compare` re-run in AUTO mode → re-did live searches; primary model timed out → fallback model | ~3 min |
| 09:52–10:01 | dermaveen+lindt turn: more searches, `todo done`, then "row 90's WW keyword vanished" investigation | ~9 min, aborted |

**Verdict:** the designed `shop`/`prefer` loop is NOT the bottleneck
(~50 s/item, most of it model turn-time + per-call process auth).
The hour is: (a) no CLI command for the exact-name change → agent
code-archaeology + hand-rolled sheet writes, (b) those manual writes
skipping every invariant (keywords written direct, sub-categories
written silent, rows renamed) → self-inflicted damage control, (c)
serial live searches repeated across optimize/compare re-runs,
(d) model timeouts + fallback. **Root cause class: missing
entry-points + stateless per-call CLI, not slow math.**

## A2. Why olive spread went straight into keywords (user question)

Session 09:45:21 — the agent hand-wrote a NEW row "Olive Oil Spread
500g" with `ws.append_row([...])` including:
`I='Woolworths Olive Oil Spread 500g'`, `J='Coles Olive Oil Spread'`
(names the agent CONSTRUCTED, not verbatim live-search captures),
Q='spread', R='OOS'. Two layers caused it:

1. **No CLI path fits the moment.** The user's change-requests named
   exact store products mid-chat. The only designed paths are
   `map --keyword` (writes the typed text DIRECT to Col I/J —
   `grocery_price_cli.py:5745`, `set_store_keyword`,
   `core/sheets_sync.py:900`) and `optimize --confirm` codes (which
   the agent wasn't holding). So the agent improvised raw gspread.
2. **The skill itself teaches "typed name → keyword column".**
   SKILL.md resolve-session rule: *any other text during a wool/coles
   session → `map --keyword`* — i.e. the designed system also puts
   user-typed names directly into keywords, with no live-search
   validation, no price, no to-do handshake. (The olive case just
   bypassed even that validation-free path.)

Current sheet state (T5 dump): row 113 carries BOTH keywords
(I+J) and NO to-do entry — the website-add handshake never happened.
Same for row 14 (eggs), row 94 (pancake — Col A was RENAMED to
"Green's Original Pancake Shake 375g" over the old row), row 114
(Lindt, J keyword in caps).

## A2b. The Woolworths-name-into-Coles mix-up (user report, traced)

The full 09:28:23 user message (verbatim from the transcript):

> 2 changes for eggs use this Macro Wholefoods Market Large Organic
> Free Range Eggs 600g 12 Pack and coles Coles Organic Free Range
> Eggs 12 Pack | 600g
> For mozarella sticks - woolworths Keith's Foods Mozzarella Cheese
> Sticks 235g 10 Pack and coles GONE. Make this item preferred for
> mozarella sticks so next time it straight brings me this
> I don't why items are marked as non tracked in coles are they in
> coles missing list
> Pancake - Green's Original Pancake Shake | 375g
> Sugar - Coles Simply Australian Raw Sugar | 2Kg
> Olive spread - Coles Olive Oil Spread

What the agent did with each part (verified against writes + sheet):

- eggs / mozzarella: explicit "woolworths X and coles Y" — written
  to the correct I/J columns. ✓
- **the three unlabelled lines (Pancake / Sugar / Olive spread):
  the agent ASSUMED they were Coles keyword fills** (those rows were
  "not tracked at Coles") and wrote them into J — then **invented the
  Woolworths-side names itself** (I94="Green's Pancake Mix Original
  Shake 375g", I113="Woolworths Olive Oil Spread 500g" — names it
  constructed from its own searches, never shown to or approved by
  the user). The user's intent for those names was the products they
  want (Woolworths side); the agent had no way to ask.
- **Lindt (09:52 turn):** the agent captured "LINDT HOT CHOC FLAKE
  MILK TIN 210G" from a **Coles** live-search result, wrote the
  Coles price (E=14.0) and slated the name for the Coles keyword
  column (its own script comment: `# J Coles kw`), leaving WW for
  "resolve" — while the user wanted it tracked for Woolworths. The
  user later manually moved the name to I themselves (sheet now:
  I=LINDT…, J empty).
- **Root cause (systemic): the shopping-list flow has NO
  store-assignment step.** `map --keyword` infers the store from the
  session's list; `search --add-item` takes the store from whichever
  store's results the Nth item came from (nondeterministic across
  re-runs — see A5); the Sep-7 manual path guessed. Any ambiguity is
  silently resolved by a guess. The user experienced this as "I said
  Woolworths, it landed in Coles" — correct for Lindt (store never
  asked), partially correct for the three unlabelled lines (store
  assumed), and compounded by invented names on the other side.
- **User correction (2026-09-07):** the user manually edited whatever
  needed fixing on these rows and added the items to their website
  shopping lists. **Rows 14/94/113/114 stay AS-IS (binding B9) —
  do not "repair" them in the rebuild.**

## A3. Sub-category not taken (sugar / V Sugarfree) — two bugs

**Bug 1 — category mode is exact-string-equality only**
(`core/preferences.py:resolve_shop_items`, key must EQUAL a label).
Harness sweep, 122 labels × 5 forms:

| phrase form | result |
|---|---|
| bare label ("sugar") | CATEGORY mode (70 halt-no-P, 48 cold, 4 with P) |
| label + size ("sugar 2kg", "Sugar-2 kg") | **100% fell through to RAW-TEXT mode** |
| size + label / brand prefix / singular-vs-plural ("egg" vs "eggs") | **100% RAW-TEXT** |

The user's actual 8-item list: only Milk + Bread reached the preferred
path. "Egg", "Sugar-2 kg", "Mozarella sticks", "Cucumber mini",
"Pancake mix original (greens)" all fell to raw-text compare. RAW-TEXT
mode = lookup partial-match or live search = the "not taking
subcategory" complaint. The SKILL tells the agent to pre-normalise
against `subcategories` — glm-5.3-flash doesn't do it reliably, and
the CLI has no fallback.

**Bug 2 — substring matching in `find_candidates`**
(`core/lookup.py:391`, `if v in norm_a` — no word boundaries; the
2026-09-05 \b fix went into the sub-category classifier ONLY, not the
lookup engine). Live-sheet proof:

- query `sugar` → top-6 candidates: Raw Sugar 3Kg ✅, RAW SUGAR 2KG ✅,
  **V Sugarfree 4\*250 ❌, Red Bull Sugar Free ❌, Dare No Sugar ❌,
  V Energy Zero Sugar ❌** — all tied at score 3.
- `water` → V Watermelon (×2) ❌ ties with Mount Franklin ✅;
  `egg` → Steggles Wings ("egg" ⊂ "stEggles") ❌;
  `apple` → Carman's Apple Fruit Straps ❌.

`find_substitute` (`core/basket_confirm.py:283`) reuses the same
`find_candidates` — first candidate with a price wins. That is exactly
why the weekly basket offered "Chocolate Hazelnut Spread" (shares
token "spread") for olive spread, and aluminium-foil-class rows for
other items. **One engine, three symptoms: sugar→sugarfree,
wrong substitutes, ugly weekly basket.**

## A4. Keyword / live-search → what the DESIGN does vs the new user rule

| path | keyword col | price | to-do entry | matches new rule? |
|---|---|---|---|---|
| `map --keyword` (skill routes ANY typed text here) | **written direct** | no | no | ❌ |
| `map --add` | empty ✓ | yes | yes | ✅ |
| `search --add-item N` | empty ✓ | yes | yes | ✅ |
| `optimize --confirm` A/B | stale keyword cleared, correct product → to-do ✓ | yes | yes | ✅ |
| agent manual gspread (this session) | **written direct** | yes | no | ❌❌ |

The desired semantics ALREADY EXIST (`optimize --confirm` /
`search --add-item`); they're just not reachable from the
shopping-list chat flow, and the one reachable path
(`map --keyword`) violates the rule.

## A5. Sub-categories written silently, wrongly (user complaint)

Evidence: the manual writes at 09:44–09:47 wrote Q cells in the same
breath as prices (Q='mozzarella', Q='spread'), violating the standing
2026-09-05 ask-first rule; sheet now shows 'cheese sticks'/'olive
spread' for those rows (labels that are NOT in the taxonomy — the
user corrected them by hand afterwards). Sheet reality: **122
distinct Q labels, 48 of which have ZERO rows** (taxonomy bloat),
0 `needs review` rows, plus multiple sheet-only labels ('v energy
drink', 'red bull', 'cold coffee', 'cheese sticks', 'olive spread',
'aa battery'…).

## A5b. Add-flow nondeterminism (Sep 6 lotion session, traced)

The "add all" lotion session (Sep 6 23:10–23:55) shows the add path
is nondeterministic and invites improvisation:

- `search --product X --add-item N` **re-runs the search**; between
  the display and the `--add-item 4` call the results shifted, so it
  grabbed **Cetaphil 236mL instead of the intended DermaVeen 500mL**
  (wrong item, wrong size).
- The agent then **hand-deleted the wrong row via a /tmp python
  script** (`/tmp/delete_row_107.py`) — another raw-gspread bypass —
  and used `--allow-duplicate` to force a re-add.
- Result on the sheet (user-verified 2026-09-07, CORRECTED — these
  are NOT duplicates): row 106 = DermaVeen **Daily Nourish 500mL**,
  row 107 = DermaVeen **Extra Hydration 500mL**, row 108 = DermaVeen
  **Extra Hydration 1L Colloidal Oatmeal** (Coles side, $12.00 in E).
  Three distinct products/sizes. (Earlier draft of this doc wrongly
  flagged 107/108 as duplicates from truncated names — retracted.)
- Data-hygiene note only: row 107's WW price cell holds the string
  `'$12.00'` (dollar-prefixed text, atypical — sheet convention is a
  bare number), likely a leftover from the misfire dance. Leave or
  fix at the user's discretion.

## A6. Per-call overhead measurements (read-only)

- CLI process start + gspread auth: **~3.2–4.0 s every invocation**
  (stateless); one full-sheet read 0.32 s; compare_basket(sheet)
  logic for 40 items: ~0.00 s (1 read).
- Per-item one-by-one round trip = 2 CLI processes (`shop` +
  `prefer`) ≈ 8–9 s pure overhead × items, before model turns
  (~20–30 s/item observed) and Telegram latency.
- **Sheets quota:** each `resolve_shop_items`/`read_qrs` = ONE
  full-sheet read; 60 reads/min user quota — a 350-phrase sweep
  exhausted it live (the harness now caches one snapshot). A
  many-item `shop` session at N items ≈ 2N+ reads — fine, but any
  agent-side improvisation multiplies this fast.

## A7. Friday run path (to be scrapped — user decision B6)

- VPS crontab (ubuntu):
  `*/15 * * * * docker exec openclaw-core python3 …/grocery_price_cli.py local-deals --friday-gate`
  plus the hourly `--daily-scan` tick (05:00/15:00 windows).
- Code: `--friday-gate` path in `_cmd_local_deals`
  (`grocery_price_cli.py` ~line 370-410) + Friday gates inside
  `core/local_deals.py`; docs: README "Local deals — Friday" section,
  PROJECT-MAP §Local deals, SKILL/`claw_skills_easy.md` mentions.
- Daily FB lists (`--daily-scan` + `--ingest CODE`) now cover the same
  shops — the Friday rebuild+post is redundant.

---

# PART B — Binding user decisions (2026-09-07, do not re-litigate)

1. **B1 — The flow is fixed and simple:** user gives names → system
   searches sub-category → presents items ONE BY ONE → user tells
   preferred → items not on list: live search → price goes into the
   sheet → new row added if needed → **product goes on the TO-DO
   list** → system asks whether to add to to-do (for tracked items) →
   final shopping list. Target: **under 5 minutes** for a list.
2. **B2 — Keywords are NEVER written directly to the sheet.** When the
   user gives keywords (e.g. for a Coles-missing item), write ONLY the
   price into the sheet and put the PRODUCT on the to-do list. The
   keyword arrives later via the website-add handshake
   (`todo done`). (`map --keyword`'s direct-write semantics are
   superseded by this rule for the shopping-list flow.)
3. **B3 — Live-search items:** item → to-do list; ONLY the price goes
   into the sheet. (Same rule, stated separately for the live path.)
4. **B4 — Sub-categories: never write silently, never guess**
   (re-affirms 2026-09-05). Any label the system is not confident in →
   ask; wrong labels currently on the sheet get fixed by asking, never
   re-guessed.
5. **B5 — Shopping-list output needs ONE fixed, clear format**
   (architect to spec the template; today the agent ad-libs it).
6. **B6 — Scrap the Friday local-deals run path** — daily FB lists
   supersede it (cron line + gate path + docs). (User clarification
   2026-09-07: the Friday run was for the OTHER shops, never linked
   to the shopping-list flow; the Wednesday run alone is enough.)
7. **B7 — Ask, don't assume** (standing user instruction: "Any
   questions ask 100s do not assume") — architecture questions go to
   the user before implementation choices are frozen.
8. **B8 — Names and store assignment are never guessed.** A name
   written against a row must come either from the USER verbatim or
   from the sheet / a live-search result verbatim — the agent NEVER
   invents or "constructs" a store name (I94/I113-style inventions
   are the violation that caused the WW/Coles frustration). When a
   user-supplied name doesn't say which store it belongs to, the
   system ASKS ("this name for Woolworths or Coles?") before writing
   anything. When naming a NEW row, ask the user or derive the name
   from the sheet/taxonomy — never a random name (user rule
   2026-09-07: "next time pls ask me or at least assign them names
   as per sheet and not any random names").
9. **B9 — Rows 14/94/113/114 stay AS-IS** (user manually corrected
   keywords/names and completed the website adds on 2026-09-07).
   The rebuild must NOT "repair" or re-normalise these rows.
10. **B10 — `search --add-item N` determinism:** the add must resolve
   against the SAME result list that was displayed (no silent
   re-search between display and add — the Sep-6 wrong-item grab is
   the evidence). Architect specs the mechanism (result pinning or
   id-based add).

# PART C — Direction for 01 Architect (from evidence, not binding)

1. **One command for the whole chat flow** (e.g. `shop` hardened, or a
   `shop`/`shop resolve` pair) so the agent NEVER hand-writes gspread:
   - accept the raw user list; internal normalisation to sub-category
     (token/qualifier-stripping + plural folding + label index with
     containment, e.g. "Sugar-2 kg" → `sugar`; "egg" → `eggs`);
   - batch the one-by-one prompt loop in a single session state with
     ONE sheet read per turn (cache the snapshot; invalidate on write);
   - exact-name change requests land in the SAME handshake as
     `optimize --confirm`: price into the row, keyword cleared/empty,
     product queued on to-do (B2/B3).
2. **Fix the matcher once, use it everywhere:** word-boundary token
   matching in `find_candidates` (+ reuse for `find_substitute`);
   gate substitutes by sub-category family so "Chocolate Hazelnut
   Spread" can never answer "olive spread".
3. **Speed budget to hit <5 min:** 1 sheet read + ≤1 live-search
   round for the whole list (batched, parallel per store), one CLI
   process per user turn (persistent session or single multi-item
   command), no code-reading detours possible because no path requires
   improvisation. Consider agent-side caching of `subcategories` +
   labels.
4. **Sub-category hygiene:** taxonomy slim-down (48 zero-row labels),
   sheet-only label reconciliation, `needs review` ask-flow wired into
   the shopping-list UI (B4).
5. **Friday removal (B6):** delete the crontab line, retire
   `--friday-gate` (keep code shelved or remove — architect decides),
   update README/PROJECT-MAP/SKILL + `claw_skills_easy.md` (doc-sync
   rule) in the same change.

# PART D — Open items (user-answered 2026-09-07; remaining at bottom)

1. ~~Rows 14/94/113/114 agent-written direct keywords~~ — **ANSWERED:
   KEEP** (user manually edited what was needed and completed the
   website adds) — binding B9.
2. ~~Row 94's Col A renamed by the agent — restore?~~ — **ANSWERED:
   KEEP the names as they are now** (user changed them; B8 governs
   future behaviour).
3. ~~DermaVeen duplicates~~ — **RETRACTED: no duplicates** (106 Daily
   500mL / 107 Extra 500mL / 108 Extra 1L — distinct products, see
   A5b). Only open micro-item: row 107's `'$12.00'` string price.
4. ~~Friday / weekly summary~~ — **ANSWERED: Wednesday run is enough**
   (B6); Friday was for the other shops, unrelated to this flow.
5. Sub-category set: keep the granular sheet-only labels
   ('cheese sticks', 'olive spread') or fold them into taxonomy
   families? — still open (architect may propose; user decides).
6. Add-flow live tests: the test phase was READ-ONLY by design (the
   live sheet + the user's in-flight WIP made write-tests unsafe).
   The architect's test plan MUST include end-to-end add-flow tests
   (add → price → to-do handshake → `todo done`) executed against a
   scratch sheet or after the user green-lights live writes.
