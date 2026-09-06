# TODO — Local Deals rebuild (gaps + verification protocol)

Created: 2026-09-05 (end of day, by request after failed first build).
Move to `old md/` ONLY when every task below is [DONE] and the user
has confirmed the end-to-end run. Until then this file is the single
source of truth for what is NOT finished.

TOMORROW'S ORDER (corrected 2026-09-05 evening — Fruitopia finishes
completely before any other store):
  Task 0  Re-verify topic 594 + VPS env
  Task 1  Sydney timezone helper
  Task 2  Fruitopia last-3-posts + validity filter
  Task 3  Fruitopia text AND image handling (image rendering +
          image-vs-text comparison per post)
  Task 4a Fruitopia integration + user confirmation   ← GATE
  ---- nothing below starts until 4a is confirmed ----
  Task 4b Merjan → 4c Dunya → 4d Abu Salim (same checklist each)

Ground rules for tomorrow (from the user):
1. FRUITOPIA FIRST, AND FINISHED COMPLETELY (tasks 0 → 2 → 3 → 4a)
   before ANY other store is touched. Merjan/Dunya/Abu Salim wait
   until the user confirms Fruitopia end-to-end.
2. One store at a time — verify with live evidence BEFORE integrating.
3. Check and RE-CHECK results (min. 3 passes per task) before
   reporting anything as done.
4. Every date comparison uses SYDNEY time, never server time.
5. Posts may be text-only OR image-only — the pipeline must handle
   both.
6. Only the LAST 3 POSTS per shop are in scope; report only posts
   whose validity date is in the future (Sydney).

---

## 0. Channel / topic  — [DONE 2026-09-06 evening; user visual re-check open]

- [x] Bot granted "Manage Topics" → topic created:
      `local-deals`, thread_id **594**, in Claw Command Center
      (-1004394070843). Test post delivered to the topic.
      `TELEGRAM_LOCAL_DEALS_TOPIC_ID=594` written to `.env`.
- [~] RE-CHECK (user): test messages now land INSIDE topic 594 from
      BOTH local and the VPS container (receipt message_id=604,
      thread=594, api ok). **User: confirm visually in the group.**
      (Note: a provisioning side effect created duplicate topic 601
      on 2026-09-06; it was deleted.)
- [x] RE-CHECK (code): `.env` now carries the key on BOTH sides —
      local root `.env` AND VPS `/home/ubuntu/openclaw/.env`
      (bind-mounted to the container's
      `/app/tasks/ai-tools/.env`; verified via in-container
      `_find_root_env()` + in-container test send).

## 1. Timezone discipline  — [DONE 2026-09-06 evening]

- [x] `core/sydney_time.py` — `sydney_now()` / `sydney_today()`, one
      place, ZoneInfo (AEST/AEDT by date; VPS runs UTC).
- [x] Replaced every `datetime.now()`/`date.today()` in the
      local-deals + halal paths: local_deals friday_gate_open,
      friday_gate_mark_fired, fired_at, run flow (today_syd,
      run_dir); halal ledger-TTL ×2, checked_at ×2. Full list in
      `grocery-price-tracker/test.md` round 2026-09-06 evening.
      (Queue/ISO-timestamp modules stay UTC — machine timestamps,
      not user-facing dates.)
- [x] RE-CHECK: `tests/test_sydney_time.py` pins 2026-09-06 20:00 UTC
      = 06:00 Mon 7 Sep Sydney and asserts the "5 & 6 September"
      catalogue is EXPIRED; plus 23:59 boundary, year rollover, AEDT
      offset, Friday gate from a UTC instant. 6 tests, green ×3.

## 2. Last-3-posts + future-validity rule  — [DONE for Fruitopia; one render gap]

- [x] Timeline enumeration built (`extractors/fb_timeline_fetch.py`)
      + `filter_recent_posts` (last-3, future-only, Sydney).
- [x] DISCOVERY: the anniversary post and the "5 & 6 September"
      catalogue are ONE post (974521905656870, created 2026-09-04
      07:06 UTC, 24 deal lines — user's earlier "17" was a partial
      parse). Validity extracted: ends 2026-09-06 → KEPT on 6 Sep,
      EXPIRED from 7 Sep (pinned test).
- [x] Undated posts → needs-date-review bucket: printed, EXCLUDED,
      never silently included (pipeline + test).
- [x] RE-CHECK: two independent renders (plain + scrolled) → same
      post, same 24-deal signature.
- [~] GAP RESOLVED BY REDESIGN (user decision 2026-09-06, late): the
      logged-out render exposes only the newest story, and the user
      REJECTED cookies outright (Woolworths/Coles 18-hour lesson) and
      approved building a logged-in route, then REPLACED it with the
      twice-daily detector flow (§2b below). Logged-in code exists
      and is dormant (`fb_timeline_fetch` route policy; needs
      FB_COOKIE_* env pair — NOT enabled, user must never supply
      cookies). GitHub workaround check done 2026-09-06: the known
      logged-out scrapers (kevinzg/facebook-scraper etc.) are dead
      or themselves cookie/login-based — nothing better than the
      detector.

## 2b. Twice-daily new-post detector (USER-DIRECTED 2026-09-06 — replaces last-3)

- [x] `--daily-scan` (cron, 05:00 + 15:00 Sydney, once per window):
      renders each public page logged out, compares the newest post
      id against `data/local_deals_scan_state.json`.
- [x] First run TODAY = the user's "last 3 days" backfill: reported
      DUNY (Thu 3 Sep 11:34), MERJ (Fri 4 Sep 20:20), FRUT (Fri 4 Sep
      17:06, valid until Sun 6 Sep — auto-parsed); ABSA newest post
      is 12 days old → correctly silent. Delivered to topic 594.
- [x] Every notification carries posted time (Sydney) + validity
      date parsed from the post text (or an explicit "will ask when
      you ingest") — the user imports images/text only; remembering
      dates is the pipeline's job.
- [x] `--ingest CODE`: processes the newest file dropped into
      `data/local_deals_inbox/<CODE>/` (image → vision, text →
      parser), prints deals + validity, posts the summary to the
      topic. Validity date is re-checked; if missing the user is
      asked inline.
- [x] `--ignore CODE`: marks the notified post skipped forever (scan
      never re-reports).
- [x] VPS deployed (7 code files + skill + catalogue, md5-verified)
      + cron line installed (own log: local_deals_scan.log).
- [x] Skill updated (local-deals SKILL.md: detector flow, codes,
      ingest/ignore routing) + catalogue regenerated (--check OK).
- [ ] FRIDAY RETIREMENT: keep the Friday cron until the user has
      seen a few daily cycles, then remove the `--friday-gate` line
      on their word.
- [ ] Known limit (documented, accepted): logged-out render exposes
      only the NEWEST post — if two posts land between scans, the
      older one is not enumerated; the user checks the page anyway
      during ingest.

## 8. Close-out refinements (user-directed 2026-09-06, late)

- [x] TAB LAYOUT (7 columns): Product | Dunya (site) | Dunya FB
      specials | Merjan | Fruitopia | Abu Salim | Comments. The
      Dunya SITE prices (dunyabutchery.com.au, `--dunya-site`) and
      the Dunya FACEBOOK specials (DUNY ingest) now have SEPARATE
      columns; multi-buy/bulk notes moved to the Comments column
      (numeric effective rate stays in the specials column).
      build_rows/rebuild_tab/merge_store_tab all 7-wide (A1:G).
- [x] PRODUCT NAME CLEANUP: WooCommerce names decoded
      ("&#8211;" -> en dash) and trailing size fragments dropped
      ("Lamb Leg Roast – 2.5-3kg" -> "Lamb Leg Roast" — ONE row,
      no size-specific duplicates). `_clean_site_name`.
- [x] Codes FRUT/MERJ/DUNY/ABSA confirmed; multiple pending posts
      per shop get FRUT_1, FRUT_2, ... (freed again once ingested).
- [x] Scan cadence fixed per user: cron tick HOURLY (was every
      15 min) — the real scan still only fires inside the 05:00 and
      15:00 Sydney windows, so Facebook is contacted twice a day.
      Scans belong to the VPS only (a local run would duplicate
      notifications — documented in the skill).
- [x] Notification messages rewritten in plain language (shop name,
      code, "When posted", "Valid until", numbered what-to-do, and
      the exact ignore line — no jargon).
- [x] Dunya site sheet BUILT from dunyabutchery.com.au: 101 items
      synced into Local_Deals (verified vs the 2026-09-05 values:
      BEEF MINCE (5KG) $64.99, Chicken Skewer $2.99, Greek Chops
      $21.99, Spicy Wings $10.99, Beef Curry /kg $15.99). Offers are
      visible two ways in every sync summary: site sale price vs
      regular price, and price changes vs the previous sync.
- [ ] LLM item-name genericisation: currently NOT in the project —
      Local_Deals item names come from the vision schema verbatim,
      and matching is rule-based (canonical_key + similarity). If
      the user wants FB deal names mapped to generic master names by
      an LLM, that is NEW work (LLM cost + a confirm step) — decide
      after seeing a few real ingests.
- [ ] Rebuild the live tab in the new 7-column layout + re-sync
      Dunya site prices (old layout was built before this change).

## 3. Text AND image posts (Fruitopia lesson)  — [DONE]

- [x] Per-post pipeline: `extract_post_deals` — TEXT first (any price
      lines), vision ONLY for image-only posts, on the post's OWN
      timeline-attributed images (photos-tab retired for fruitopia;
      other stores unchanged until their tasks).
- [x] Post images come from the timeline render itself
      (`download_post_images`, max 4, signed URLs as captured) —
      LIVE PROOF: vision read 24 deals off the anniversary post's own
      board image (the earlier "photos-tab → 0 images" was the wrong
      source, not missing boards).
- [x] RE-CHECK: synthetic fixtures — text post (vision never called),
      image-only post (vision called with the post's files), empty
      post → ("none"). 20 tests in `tests/test_deal_text.py`, green
      ×3; full suite 1101 passed.

## 4. Store-by-store verification (FRUITOPIA GATES 4b-4e)

- [~] **4a. FRUITOPIA — integrated, AWAITING USER CONFIRMATION.**
      Live dry-run 2026-09-06: "🛒 LOCAL BOARDS — Sun 2026-09-06"
      (real weekday — §5 bug fixed), 24 deals printed, look-only,
      exit 0. Deals for verification are in
      `grocery-price-tracker/test.md` (round 2026-09-06 evening) —
      confirm the list to unblock 4b-4d.
- [ ] **4b. Merjan Brothers Quality Meats** — BLOCKED until 4a is
      confirmed. Page id 61578274311504
      identity confirmed ("Merjan brothers quality meats حلال").
      NOT yet extracted. Check: text posts? images? last 3 posts +
      validity. (Earlier photos-tab fetch: "all renditions below size
      floors" — 0 usable images. Re-diagnose from the timeline.)
- [ ] **4c. Dunya Butchery** — BLOCKED until 4a. Page id
      100071472636159 identity confirmed.
      TWO sources: FB page + direct site
      dunyabutchery.com.au (WooCommerce Store API VERIFIED working
      2026-09-05 via Scrape.do: BEEF MINCE (5KG) $64.99, Chicken
      Skewer $2.99, Greek Chops $21.99, Spicy Wings $10.99, Beef
      Curry $15.99/kg — prices in CENTS). Decide with the user: site
      catalogue = normal prices; FB = weekly specials?
      NOTE: earlier vision on a Dunya FB image saw a display-case
      photo, not a board — the earlier "no deals" was correct
      behaviour on the wrong source.
- [ ] **4d. Abu Salim Fruit Market** — BLOCKED until 4a. Page id
      61592534263358 identity confirmed. NOT yet extracted at all.
- [ ] RE-CHECK each store on a SECOND render before user sign-off
      (render variance bit us twice on Fruitopia).

## 5. Report/date bugs carried from the failed first run

- [x] "Fri" hardcoded in both post headers — FIXED 2026-09-06: the
      run's actual Sydney weekday is rendered (live proof: "Sun
      2026-09-06"). Files: `core/local_deals.py`
      render_post1/render_post2_blocks + run_label in
      run_local_deals; header assertion updated.
- [ ] The old "photos-tab + vision, 3 most recent photo-groups"
      pipeline produced 0 offers for all 4 shops. After the text
      pipeline replaces it per-store, DELETE or clearly retire the
      dead path (and its tests) so it can't silently produce empty
      reports again. [Progress: fruitopia now on the timeline
      pipeline; the photos path remains for dunya/merjan/abusalim
      until 4b-4d — retirement happens at close-out.]
- [ ] Completion gate change: end-to-end PASS now requires
      deals > 0 for every in-scope shop (or an explicit, user-visible
      "no current catalogue" per shop with the post's validity
      reason) — never "messages delivered". [Progress: the timeline
      path raises FetchUnavailable on zero in-scope deals
      (fail-loud); the report-level gate lands with 4b-4d.]

## 6. Sheet tab + Telegram delivery (after stores are verified)

- [ ] Local_Deals tab: confirm the new data shape still fits
      (item names like "Washed Potatoes 5kg Bag" carry size in the
      name; multibuy cells stay notes; Fruitopia's bonus-list items
      must not collide with weekend-list rows).
- [ ] Telegram delivery to topic 594 (not DM) — verify a real post
      lands INSIDE the topic; receipt line must show thread=594.
- [ ] RE-CHECK: message length, section headers, and the actual
      weekday in the header.

## 7. Redeploy + cron (only after 1-6 are user-confirmed)

- [ ] Sync code + skills to VPS (scp), md5 verify, restart
      openclaw-core, `--dry-run` smoke on the VPS: deals > 0 for
      verified shops.
- [ ] Cron already installed (`*/15 * * * * … --friday-gate`).
      RE-CHECK the Friday 05:00 Sydney window logic AFTER the
      timezone helper lands (task 1).
- [ ] Final full run in user's presence; user confirms topic posts.

## 8. Close-out

- [ ] Update test.md with the rebuild evidence (per store, per
      re-check).
- [ ] README/PROJECT-MAP corrections (text+image posts, Sydney
      timezone rule, 3-posts rule).
- [ ] ONLY after the user explicitly confirms everything: move THIS
      file to `C:\Users\User.DESKTOP-R2G441H\Documents\AI related\grocery-price-tracker\old md\`.

## Open questions for the user (tomorrow)

1. Dunya: site catalogue (normal prices) + FB (weekly specials) —
   both in scope? Which wins on conflicts?
2. Undated posts: keep (current behaviour) or exclude pending a date?
3. Fruitopia anniversary bonus list (Cos Lettuce 99¢ etc.) — separate
   section in the report, or merged into the main weekend list?
