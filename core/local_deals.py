"""Local-deals pipeline: orchestration, tab rebuild, domain-gated
matching, detection, report rendering (§5-§9)."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.name_matcher import similarity_tokens, token_set_ratio
from core.subcategory import normalize_subcategory
from core.sydney_time import SYDNEY_TZ, sydney_now, sydney_today

ALERT_PCT = 20.0                # strictly greater (20.0 -> no alert)
MATCH_MIN_RATIO = 0.65          # master-match threshold (§1.4.3)
MSG_CHAR_LIMIT = 4000           # hard pre-send check (4096 budget)
# Split-recommendation threshold in the standout report — the value
# the retired Round-3 split-optimizer module carried (this is the
# only survivor).
DEFAULT_SPLIT_THRESHOLD = 3.00  # dollars; split only worth it above this
STATE_PATH = (Path(__file__).resolve().parent.parent / "data"
              / "local_deals_cron_state.json")
SCAN_STATE_PATH = (Path(__file__).resolve().parent.parent / "data"
                   / "local_deals_scan_state.json")
POST_LOG_PATH = (Path(__file__).resolve().parent.parent / "data"
                 / "local_deals_post_log.json")
# Open user questions (S5/P4, user directive 2026-09-11): expiry +
# shop asks that repeat in EVERY digest until answered.
QUESTIONS_PATH = (Path(__file__).resolve().parent.parent / "data"
                  / "local_deals_questions.json")
SCAN_WINDOWS = (5, 15)          # Sydney hours: 05:00 and 15:00
INBOX_DIRNAME = "local_deals_inbox"
INBOX_DIR = (Path(__file__).resolve().parent.parent / "data"
             / INBOX_DIRNAME)
# The scanner runs on the VPS, but the USER saves inbox files on
# Windows — notifications carry this full copy-paste path
# (user rule 2026-09-07).
USER_INBOX_ROOT_WIN = ("C:\\Users\\User.DESKTOP-R2G441H\\Documents"
                       "\\AI related\\grocery-price-tracker\\data"
                       "\\local_deals_inbox")

# Butchery comparison domain — the SAME label set as
# HALAL_CHECK_CATEGORIES (spec §8.4; unified in step S23).
from core.halal import HALAL_CHECK_CATEGORIES as BUTCHERY_DOMAIN  # noqa: E402
STATE_PATH = (Path(__file__).resolve().parent.parent / "data"
              / "local_deals_cron_state.json")

# Butchery comparison domain — the SAME label set as
# HALAL_CHECK_CATEGORIES (spec §8.4; unified in step S23).
from core.halal import HALAL_CHECK_CATEGORIES as BUTCHERY_DOMAIN
FRUITSHOP_COARSE = "fruit & veg"   # Col B authority (normalised)
PRODUCE_SUBCATEGORIES = {          # taxonomy produce labels
    "spring onion", "onion", "bananas", "blueberries", "raspberries",
    "strawberries", "apples", "capsicum", "cucumber", "tomato",
    "fresh herbs", "potatoes", "salad", "fruit & veg",
}

STOPWORDS = {"kg", "each", "ea", "pack", "bag", "box", "fresh"}
VARIETY_TOKENS = {
    "royal gala", "pink lady", "granny smith", "fuji", "jazz",
    "cos", "iceberg", "jap", "butternut", "sebago", "desiree",
    "truss", "cherry", "roma", "round",
}

TELEGRAM_CHAT_ID = -1004394070843   # Claw Command Center (mirror CLI)
TELEGRAM_USER_ID = 1594431983       # DM fallback (D24)
LOCAL_DEALS_TOPIC_ENV = "TELEGRAM_LOCAL_DEALS_TOPIC_ID"


def _singular(word: str) -> str:
    """Naive food-plural folder (user rule 2026-09-07):
    strawberries -> strawberry, tomatoes -> tomato, onions -> onion,
    peaches -> peach, grapes -> grape. Anything it does not recognise
    passes through unchanged (cos, rice, watercress ...)."""
    w = (word or "").lower()
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith(("oes", "xes", "zes", "ches",
                                  "shes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") \
            and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def _fold_plurals(tokens) -> set:
    """Map _singular over a token iterable -> folded token set."""
    return {_singular(t) for t in tokens}


def _deal_weight_g(item: str, bulk_size: str = "") -> float | None:
    """Weight in GRAMS carried inside a deal's own text (user rule
    2026-09-07): 'Onions 5kg Bag' -> 5000.0, 'Cos Lettuce 500g' ->
    500.0. First weight match wins; None when the text carries no
    weight size (loose/per-kg/each deals). Uses parse_size per match
    so the unit grammar stays in ONE place (core.uom)."""
    from core.uom import FAMILY_WEIGHT, parse_size
    text = f"{item or ''} {bulk_size or ''}"
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s?(kg|g|mg)\b",
                         text, re.IGNORECASE):
        parsed = parse_size(m.group(0))
        if parsed is not None and parsed.family == FAMILY_WEIGHT:
            return parsed.value
    return None


def _item_tokens(text: str) -> set:
    """Plural-folded, SIZE-STRIPPED word tokens for name matching.

    Size tokens ('5kg', '500g', bare units) never participate: the
    bag rule compares ACROSS sizes on purpose, so 'Onions 5kg Bag'
    must match 'Woolworths Onions 2kg Bag' (user rule 2026-09-07).
    """
    size_re = re.compile(r"\d+(?:[.,]\d+)?\s*(?:kg|g|mg|ml|l)\Z",
                         re.IGNORECASE)
    tokens = set()
    for t in similarity_tokens(text or ""):
        if re.fullmatch(r"\d+(?:[.,]\d+)?", t):
            continue
        if size_re.fullmatch(t):
            continue
        if t in ("kg", "g", "mg", "ml", "l"):
            continue
        tokens.add(t)
    return _fold_plurals(tokens)


def canonical_key(item_name: str) -> tuple:
    """Variety-aware canonical grouping key (RF1, sandbox test3 18/18).

    Word-order-insensitive tokens via name_matcher.similarity_tokens,
    plural-folded ("Strawberry" == "Strawberries" — user rule
    2026-09-07), stopwords + pure numbers stripped; a variety
    qualifier is REQUIRED in the key when present ("Beef Diced" ==
    "Diced Beef"; "Royal Gala" never merges with "Pink Lady").
    Returns (base, variety).

    Args:
        item_name: raw product/deal name.

    Returns:
        (base, variety) — both sorted token tuples; variety phrases
        contribute their component words to neither part twice.
    """
    name = (item_name or "").lower()
    tokens = {_singular(t) for t in similarity_tokens(name)
              if t not in STOPWORDS
              and not re.fullmatch(r"\d+(\.\d+)?", t)}
    variety: set[str] = set()
    for v in VARIETY_TOKENS:
        if any(vt in tokens for vt in v.split()):
            variety.add(v)
    if variety:
        tokens -= {w for v in variety for w in v.split()}
    return (tuple(sorted(tokens)), tuple(sorted(variety)))


def is_in_domain(store_kind: str, deal_category: str,
                 master_subcategory: str,
                 master_coarse_category: str) -> bool:
    """The DOMAIN GATE (§8.4, plan §1.4.2). BOTH sides checked.

    A butchery deal needs vision category 'butchery' AND master Col Q
    in BUTCHERY_DOMAIN; a fruit-shop deal needs vision 'fruits' AND
    (master Col B coarse == 'fruit & veg' OR Col Q in
    PRODUCE_SUBCATEGORIES). Anything else is out of domain.

    Args:
        store_kind: 'butchery' | 'fruits' (fb_flyer_fetch STORES).
        deal_category: vision category of the deal line.
        master_subcategory: master Col Q (normalised here).
        master_coarse_category: master Col B (normalised).

    Returns:
        True when the deal may be compared against the master row.
    """
    sub = normalize_subcategory(master_subcategory or "")
    coarse = normalize_subcategory(master_coarse_category or "")
    if store_kind == "butchery":
        return deal_category == "butchery" and sub in BUTCHERY_DOMAIN
    if store_kind == "fruits":
        return (deal_category == "fruits"
                and (coarse == FRUITSHOP_COARSE
                     or sub in PRODUCE_SUBCATEGORIES))
    return False


def _load_gate_state() -> dict:
    """Read the gate state file; missing/corrupt counts as not-fired."""
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _load_scan_state() -> dict:
    """Read local_deals_scan_state.json ({} when missing/corrupt)."""
    try:
        return json.loads(SCAN_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_scan_state(state: dict) -> None:
    SCAN_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCAN_STATE_PATH.write_text(json.dumps(state, indent=2),
                               encoding="utf-8")


def daily_scan_window(now: datetime | None = None
                      ) -> tuple[bool, str]:
    """Inside a daily scan window (05:00-05:59 or 15:00-15:59 Sydney)?

    Args:
        now: injectable clock (tests); defaults to sydney_now().

    Returns:
        tuple: (is_open, window_key) — key like "2026-09-07:5".
    """
    now_syd = (now or sydney_now()).astimezone(ZoneInfo(SYDNEY_TZ))
    open_now = now_syd.hour in SCAN_WINDOWS
    key = f"{now_syd.date().isoformat()}:{now_syd.hour}"
    return open_now, key


def _post_snippet(text: str, limit: int = 70) -> str:
    """First non-empty line of a post, trimmed — the visual hook
    that lets the user recognise WHICH post a notification means."""
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return (line[:limit] + "…") if len(line) > limit \
                else line
    return "(image-only post — no text)"


def _run_morning_sweep() -> list[str]:
    """Connect to the sheet and sweep expired specials (05:00 hook).

    Module-level so tests can patch it — the daily-scan suite must
    stay hermetic even when run INSIDE the real 05:00 Sydney window.

    Returns:
        list[str]: the sweep's report lines ([] on any failure —
        the sweep never kills the scan; the next morning retries).
    """
    try:
        from core.sheets_client import connect_spreadsheet
        worksheet = ensure_local_deals_tab(connect_spreadsheet())
        lines = sweep_expired_specials(worksheet)
    except Exception as exc:  # noqa: BLE001 — degrade, never raise
        print(f"[daily-scan] expiry sweep failed: "
              f"{exc.__class__.__name__}")
        return []
    for line in lines:
        print(f"[daily-scan] sweep: {line}")
    return lines


def _sweep_auto_ingest(new_posts: list, window_label: str,
                       send: bool = True) -> None:
    """AI-M5 (user directive 2026-09-11): the 05:00/15:00 sweep
    AUTO-INGESTS every new post itself — vision + merge + parity —
    and posts ONE combined digest for the window. It never asks the
    user to save anything and never says 'done'.

    Per post (S10/S16): a vision failure writes NOTHING and flags the
    post unreadable in the digest. S11: no-price posts record as
    notices. S5: undated boards open the expiry question (repeats in
    every digest until answered). S2/S7: per-shop merge, newest
    post's price wins, changes shown as 'was $X -> now $Y'.
    """
    from extractors.fb_flyer_fetch import FLYERS_DIR
    from core.sheets_client import connect_spreadsheet

    run_dir = FLYERS_DIR / sydney_now().strftime("%Y%m%d_%H%M%S")
    today = sydney_today()
    shops: dict[str, dict] = {}       # store_key -> digest entry
    for store, post, code, _detail in new_posts:
        entry = shops.setdefault(store["key"], {
            "store": store, "deals": [], "posts": []})
        fname = f"fb:{getattr(post, 'post_ref', '') or code}"
        try:
            deals, source, valid_until = extract_post_deals(
                post, run_dir, store["key"])
        except Exception as exc:  # noqa: BLE001 — post isolation
            print(f"[daily-scan] {code}: vision failed "
                  f"({exc.__class__.__name__}) — flagged unreadable")
            entry["posts"].append({
                "code": code, "file": fname, "valid_txt": "",
                "items": [], "notice_only": False, "unreadable": True})
            continue
        if source == "text":
            # extract_post_deals hands back None for text posts — the
            # board date lives in the text itself; parse it here.
            from extractors.deal_text import parse_validity_end
            valid_until = parse_validity_end(post.text, today=today)
        if not deals:
            entry["posts"].append({
                "code": code, "file": fname, "valid_txt": "",
                "items": [], "notice_only": True, "unreadable": False})
            continue
        if valid_until is not None and valid_until < today:
            entry["posts"].append({
                "code": code, "file": fname,
                "valid_txt": (f"deals ended {valid_until:%a %d %b} "
                              f"— nothing written"),
                "items": [], "notice_only": False,
                "unreadable": False, "expired": True})
            continue
        deals = _prefix_butcher_deals(store["key"], deals)
        category = _store_kind(store["key"]) or "other"
        converted = [_to_vision_deal(d, category) for d in deals]
        for c, d in zip(converted, deals):
            c["valid_until"] = d.get("valid_until") or valid_until
        entry["deals"].extend(converted)
        valid_txt = (f"valid until {valid_until:%a %d %b}"
                     if valid_until
                     else "no end date — question asked")
        entry["posts"].append({
            "code": code, "file": fname, "valid_txt": valid_txt,
            "items": _digest_items(converted),
            "notice_only": False, "unreadable": False})
        if valid_until is None and not any(
                c.get("valid_until") for c in converted):
            label = SHORT_SHOP_NAMES.get(store["key"],
                                         store["name"])
            open_question(
                "expiry", code, fname, store["key"],
                f"{label}: no end date on this board ({code}) — "
                f"reply with the date, or 'open' to leave it "
                f"undated")

    write_failures: list[str] = []
    spreadsheet = None
    if any(e["deals"] for e in shops.values()):
        try:
            spreadsheet = connect_spreadsheet()
        except Exception as exc:  # noqa: BLE001 — flag, never silent
            print(f"[daily-scan] sheet connect failed: "
                  f"{exc.__class__.__name__}")
            write_failures = [e["store"]["name"]
                              for e in shops.values() if e["deals"]]
    for key, entry in shops.items():
        if not entry["deals"] or spreadsheet is None:
            continue        # nothing to write / connect failed above
        store = entry["store"]
        try:
            worksheet = ensure_local_deals_tab(spreadsheet)
            sp_col = _special_column_for(key)
            before = _norm_grid(worksheet.get_all_values() or [])
            newest_valid = next(
                (c.get("valid_until") for c in entry["deals"]
                 if c.get("valid_until")), None)
            merge_store_tab(
                worksheet,
                "dunya_fb" if key == "dunya" else key,
                list(reversed(entry["deals"])),
                valid_until=newest_valid,
                master_ws=spreadsheet.worksheet(MASTER_TAB))
            after = _norm_grid(worksheet.get_all_values() or [])
            if sp_col is not None:
                changes: dict[str, float] = {}
                # S7 'was' priority: the OLDER same-window post's
                # price when the item repeats (the change the user
                # saw posted), else the sheet value the merge
                # replaced.
                older_post: dict[str, float] = {}
                for c in reversed(entry["deals"]):   # merge order
                    older_post.setdefault(_display_name(c),
                                          c.get("price"))
                for c in reversed(entry["deals"]):
                    display = _display_name(c)
                    i_new = _reuse_match_index(after, display)
                    new = _numeric_price(
                        after[i_new][sp_col]
                        if i_new is not None
                        and len(after[i_new]) > sp_col else None)
                    was = older_post.get(display)
                    if was is not None and new is not None \
                            and abs(float(was) - new) >= 0.01:
                        changes.setdefault(display,
                                           round(float(was), 2))
                        continue
                    i_old = _reuse_match_index(before, display)
                    if i_old is None or i_new is None:
                        continue
                    old = _numeric_price(
                        before[i_old][sp_col]
                        if len(before[i_old]) > sp_col else "")
                    if old is not None and new is not None \
                            and abs(new - old) >= 0.01:
                        changes.setdefault(display, old)
                for p in entry["posts"]:
                    for i in p.get("items") or []:
                        if i["name"] in changes:
                            i["was"] = changes[i["name"]]
        except Exception as exc:  # noqa: BLE001 — flag, never silent
            print(f"[daily-scan] {key}: sheet write failed "
                  f"({exc.__class__.__name__})")
            write_failures.append(store["name"])

    standout_lines: list[str] = []
    try:
        scan_rows = []
        for key, entry in shops.items():
            for c in entry["deals"]:
                row = dict(c)
                row["store_key"] = key
                row["store_name"] = entry["store"]["name"]
                scan_rows.append(row)
        if scan_rows:
            from core.sheets_client import connect_worksheet
            master_rows = _load_master_rows(connect_worksheet())
            results = match_and_detect(scan_rows, master_rows, {})
            standout_lines = render_post1(
                results,
                sydney_now().strftime("%a %Y-%m-%d")).splitlines()
    except Exception as exc:  # noqa: BLE001 — degrade cleanly
        print(f"[daily-scan] standout check failed: "
              f"{exc.__class__.__name__}")

    sections = [{
        "shop_label": SHORT_SHOP_NAMES.get(key, entry["store"]["name"]),
        "shop": entry["store"]["name"],
        "posts": entry["posts"],
    } for key, entry in shops.items()]
    messages = _render_window_digest(
        sections, _load_questions(), window_label,
        standout_lines=standout_lines or None)
    if write_failures:
        messages[-1] += (f"\n\n⚠️ Sheet write failed for: "
                         f"{', '.join(sorted(set(write_failures)))} "
                         f"— prices above are NOT saved; ask for a "
                         f"re-ingest once the sheet is reachable.")
    if send:
        _post_digest(messages)
    else:
        for text in messages:
            print(text)


def run_daily_scan(dry_run: bool = False, send: bool = True,
                   max_posts: int = 3, backfill_days: int = 3,
                   force: bool = False) -> int:
    """Twice-daily new-post detector (user-directed 2026-09-06).

    OWNERSHIP: the VPS cron is the only scanner. Running this on a
    second machine duplicates notifications (each machine keeps its
    own seen-state). Local runs: --dry-run for testing only.

    SCHEDULE: the cron ticks hourly, but WITHOUT force this function
    contacts Facebook ONLY inside the 05:00-05:59 and 15:00-15:59
    Sydney windows, once per window (zero credits otherwise).
    force=True scans now regardless of the clock (manual runs).

    WINDOWS: each scan records a cutoff (Sydney time). Ongoing scans
    report only posts CREATED after the previous cutoff — i.e. what
    was posted between the two alerts. First-ever sighting of a shop
    = the user's "last 3 days" backfill: notify only when the newest
    post is within backfill_days, else silent baseline.

    INBOX CODES (user rule 2026-09-07): every notification carries
    <3-letter shop><ddmmyy><HHMM> of the ALERT (Sydney time the
    notification is sent — FRU0709260507 = Fruitopia, alerted
    07 Sep 26, 05:07), plus the posted time and the validity date
    parsed from the post text. Several posts of one shop between two
    scans each get their own code (same-minute collisions take a
    _2/_3 suffix). 'ingest CODE' completes the code; 'ignore CODE'
    retires it.

    HEARTBEAT (user rule 2026-09-07): a completed scan with nothing
    new sends one "✅ ... no new posts" message (with a could-not-
    check note when a store fetch failed) — silence never means
    broken. Off-window ticks and already-serviced windows still stay
    fully silent.

    Args:
        dry_run: print instead of sending Telegram; state untouched.
        send: send the notification via Telegram (topic 594).
        max_posts: newest posts inspected per store (a missed window
            must not silently drop the middle posts).
        backfill_days: max age of a first-sighting post to report.
        force: scan now even outside the 05:00/15:00 windows.

    Returns:
        int: 0 all stores checked (or window closed), 1 partial
        failure, 2 total failure.
    """
    from datetime import datetime as _dt

    from extractors.fb_flyer_fetch import FetchUnavailable
    from extractors.fb_timeline_fetch import fetch_timeline_posts

    open_now, window_key = daily_scan_window()
    if not open_now and not dry_run and not force:
        # Off-schedule cron tick: do not contact Facebook at all
        # (twice-daily scans only — user rule 2026-09-06).
        return 0

    state = _load_scan_state()
    windows = state.setdefault("windows", {})
    if open_now and not dry_run and windows.get(window_key) == "done":
        return 0                      # this window already serviced

    # Morning expiry sweep (user rule 2026-09-07): a special valid
    # till 6-Sep must be OFF the tab on 7-Sep morning. Runs inside the
    # once-per-window guard, 05:00 window only — independent of the
    # Facebook fetches (a failed fetch never skips the cleanup).
    sweep_lines: list[str] = []
    if open_now and window_key.endswith(":5") and not dry_run:
        sweep_lines = _run_morning_sweep()
    sweep_block = ""
    if sweep_lines:
        sweep_block = ("\n🧹 Expired specials removed:\n"
                       + "\n".join(f"• {ln}" for ln in sweep_lines))

    print(f"[daily-scan] window={window_key or 'off-schedule'}"
          f"{' (forced)' if force else ''}"
          f"{' (dry-run)' if dry_run else ''}")
    from core.sheets_client import _load_env
    _load_env()
    from extractors.fb_flyer_fetch import STORES

    now_syd = sydney_now()
    stores = state.setdefault("stores", {})
    new_posts: list[tuple[dict, object, str, str]] = []
    failures: list[str] = []
    for store in STORES:
        try:
            posts = fetch_timeline_posts(store, max_posts=max_posts)
        except FetchUnavailable as exc:
            failures.append(store["key"])
            print(f"[daily-scan] {store['key']}: {exc}")
            continue
        except Exception as exc:      # noqa: BLE001 — store isolation
            failures.append(store["key"])
            print(f"[daily-scan] {store['key']}: "
                  f"{exc.__class__.__name__}")
            continue
        if not posts:
            # Empty timeline (FB hiccup): skip the store instead of
            # crashing on posts[0] — reported via the heartbeat.
            failures.append(store["key"])
            print(f"[daily-scan] {store['key']}: timeline returned "
                  f"no posts")
            continue
        newest = posts[0]
        seen = stores.get(store["key"], {})
        notified = dict(seen.get("notified", {}))   # post_ref -> code
        ignored = seen.get("ignored", [])
        cutoff_raw = seen.get("last_cutoff")
        newest_age = ((now_syd.timestamp()
                       - (newest.creation_time or 0)) / 86400
                      ) if newest.creation_time else 999
        baselined = bool(seen.get("baselined"))

        # Advance the cutoff no matter what happens below — this scan
        # is "the previous alert" for the next one.
        seen["last_cutoff"] = now_syd.isoformat(timespec="seconds")
        seen["last_post_ref"] = newest.post_ref
        seen["last_creation"] = newest.creation_time
        seen["baselined"] = True
        stores[store["key"]] = seen   # persist every branch

        if not baselined and newest_age > backfill_days:
            print(f"[daily-scan] {store['key']}: newest post is "
                  f"{newest_age:.0f}d old — nothing from the last "
                  f"{backfill_days} days, staying quiet")
            continue

        # Timestamped inbox codes (user rule 2026-09-07): the code is
        # <3-letter shop><ddmmyy><HHMM> of the ALERT (Sydney, when the
        # notification is sent) — never the post's own time. Posts
        # alerted in the same scan share the stamp; _2/_3 keeps every
        # code unique even across two scans within one minute.
        stamp = f"{store['code']}{now_syd:%d%m%y%H%M}"
        taken = set(notified.values())

        def _next_code() -> str:
            code = stamp
            n = 1
            while code in taken:
                n += 1
                code = f"{stamp}_{n}"
            taken.add(code)
            return code

        for post in posts:            # newest first
            if post.post_ref in ignored:
                print(f"[daily-scan] {store['key']}: post "
                      f"{post.post_ref} ignored — skipped")
                continue
            if post.post_ref in notified:
                print(f"[daily-scan] {store['key']}: already "
                      f"reported ({notified[post.post_ref]})")
                continue

            # Time window: ongoing scans report only posts CREATED
            # since the previous alert (between-alerts rule); a fresh
            # first sighting reports only the backfill window.
            if baselined and cutoff_raw and post.creation_time:
                try:
                    posted_dt = _dt.fromtimestamp(
                        post.creation_time, ZoneInfo(SYDNEY_TZ))
                    if posted_dt <= _dt.fromisoformat(cutoff_raw):
                        print(f"[daily-scan] {store['key']}: post "
                              f"{post.post_ref} predates the last "
                              f"alert ({cutoff_raw}) — outside the "
                              f"between-alerts window")
                        continue
                except ValueError:
                    pass               # bad stored cutoff -> notify
            elif not baselined and post.creation_time:
                age_days = ((now_syd.timestamp()
                             - post.creation_time) / 86400)
                if age_days > backfill_days:
                    continue

            code = _next_code()
            posted_line = "when posted: unknown"
            if post.creation_time:
                posted = _dt.fromtimestamp(
                    post.creation_time, ZoneInfo(SYDNEY_TZ))
                posted_line = (f"When posted: "
                               f"{posted:%a %d %b, %I:%M %p}")
            from extractors.deal_text import parse_validity_end
            valid_end = parse_validity_end(post.text,
                                           today=now_syd.date())
            valid_line = (f"Valid until: {valid_end:%a %d %b}"
                          if valid_end
                          else "Valid until: not written in the "
                               "post — I will ask you for the date")
            snippet_line = (f"Post starts with: "
                            f"\"{_post_snippet(post.text)}\"")

            notified[post.post_ref] = code
            new_posts.append((store, post, code,
                              f"{posted_line}\n{valid_line}\n"
                              f"{snippet_line}"))
            print(f"[daily-scan] {store['key']}: new post -> code "
                  f"{code}")

        seen["notified"] = notified

    if not dry_run:
        if open_now:
            windows[window_key] = "done"
        _save_scan_state(state)

    # AI-M5 (user directive 2026-09-11): the sweep AUTO-INGESTS every
    # new post itself and posts ONE combined digest — the retired
    # 'save the picture into the inbox' instruction never returns;
    # 'done' never appears in detector messages.
    if new_posts:
        window_label = "Sweep"
        if window_key:
            _h = window_key.rsplit(":", 1)[-1]
            if _h.isdigit():
                window_label = f"Sweep {int(_h):02d}:00"
        if dry_run:
            for store, post, code, detail in new_posts:
                print(f"[daily-scan] would auto-ingest {code} "
                      f"({store['name']})\n{detail}")
        else:
            _sweep_auto_ingest(new_posts, window_label, send=send)

    if not new_posts:
        # Heartbeat (user rule 2026-09-07): a finished scan with
        # nothing to report must never be silent — the user cannot
        # tell "all clear" from "broken" otherwise.
        names = {s["key"]: s["name"] for s in STORES}
        checked = f"{now_syd:%a %d %b, %I:%M %p}"
        bad = [names[k] for k in failures if k in names]
        if failures and len(failures) == len(STORES):
            text = (f"⚠️ Local deals sweep could not check any shop "
                    f"({checked} Sydney) — will retry at the next "
                    f"window")
        else:
            text = (f"✅ Local deals sweep — no new posts from "
                    f"any of the {len(STORES)} shops ({checked} "
                    f"Sydney)")
            if bad:
                text += f"\n⚠️ Could not check: {', '.join(bad)}"
        text += sweep_block           # heartbeat carries it when no
        # digest went out
        print(text)
        if send and not dry_run:
            bot_token = os.getenv("TELEGRAM_CLAW_BOT", "")
            topic_id = _env_int(LOCAL_DEALS_TOPIC_ENV)
            receipt = _send_message(bot_token, TELEGRAM_CHAT_ID,
                                    text, thread_id=topic_id
                                    or TELEGRAM_CHAT_ID)
            if not receipt.get("ok"):
                print("[daily-scan] telegram delivery failed")

    if failures and len(failures) < len(STORES):
        return 1
    if failures:
        return 2
    return 0


def _store_for_code(code: str) -> dict | None:
    """Resolve any inbox-code form to its STORES entry.

    The shop is always the FIRST THREE letters: current codes are
    <3-letter shop><ddmmyy><HHMM> (FRU0709260507), and the retired
    4-letter codes (FRUT/MERJ/DUNY/ABSA — alerts sent before
    2026-09-07) also start with the same 3 letters, so one rule
    resolves both.

    Args:
        code: raw code from the user (any case, suffix allowed).

    Returns:
        The matching STORES dict, or None when unknown.
    """
    from extractors.fb_flyer_fetch import STORES

    base = code.strip().upper().split("_")[0][:3]
    return next((s for s in STORES if s.get("code") == base), None)


def _store_and_entry_for_code(code: str) -> tuple[dict | None, dict,
                                                  str | None]:
    """Resolve an inbox code (FRU0709260507, legacy FRUT, FRUT_1,
    ...) to its store and the pending notified entry {post_ref:
    code}."""
    store = _store_for_code(code)
    if store is None:
        return None, {}, None
    state = _load_scan_state()
    seen = state.setdefault("stores", {}).get(store["key"], {})
    notified = seen.get("notified", {})
    ref = next((r for r, c in notified.items()
                if c == code.strip().upper()), None)
    return store, seen, ref


def ignore_post(code: str) -> int:
    """'ignore <CODE>' — retire that post (scan never re-reports it).

    Args:
        code: the post's code (FRU0709260507; legacy FRUT / FRUT_1).

    Returns:
        int: 0 retired, 1 nothing to retire.
    """
    store, seen, ref = _store_and_entry_for_code(code)
    if store is None or ref is None:
        print(f"[ignore] {code.upper()}: no such pending post")
        return 1
    state = _load_scan_state()
    entry = state.setdefault("stores", {}).setdefault(
        store["key"], seen)
    notified = entry.get("notified", {})
    ignored = entry.setdefault("ignored", [])
    if ref not in ignored:
        ignored.append(ref)
    notified.pop(ref, None)
    entry["notified"] = notified
    _save_scan_state(state)
    print(f"[ignore] {code.upper()}: post retired — the scan will "
          f"not mention it again")
    return 0


def _load_post_log() -> list:
    """Read local_deals_post_log.json ([] when missing/corrupt)."""
    try:
        return json.loads(POST_LOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save_post_log(entries: list) -> None:
    POST_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    POST_LOG_PATH.write_text(json.dumps(entries, indent=2),
                             encoding="utf-8")


def _load_questions() -> list:
    """Open questions ([] when missing/corrupt)."""
    try:
        return json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save_questions(questions: list) -> None:
    QUESTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUESTIONS_PATH.write_text(json.dumps(questions, indent=2),
                              encoding="utf-8")


def open_question(kind: str, code: str, filename: str,
                  shop_key: str, text: str) -> None:
    """Record an unanswered user question (S5 'no end date on this
    board — reply with the date or open'; P4 ambiguous shop for AUTO
    codes). Idempotent per (kind, code, file); the ask repeats in
    EVERY digest until cleared by set-date / resolve-shop."""
    questions = _load_questions()
    if any(q.get("kind") == kind and q.get("code") == code.upper()
           and q.get("file") == filename
           for q in questions):
        return
    questions.append({"kind": kind, "code": code.upper(),
                      "file": filename, "shop": shop_key,
                      "text": text,
                      "asked_since": sydney_now().isoformat(
                          timespec="seconds")})
    _save_questions(questions)


def clear_questions(code: str, filename: str | None = None) -> int:
    """Drop answered questions for a code (optionally one file).
    Returns how many were cleared."""
    code = code.strip().upper()
    questions = _load_questions()
    kept = [q for q in questions
            if not (q.get("code") == code
                    and (filename is None
                         or q.get("file") == filename))]
    cleared = len(questions) - len(kept)
    if cleared:
        _save_questions(kept)
    return cleared


def post_log_cmd(code: str) -> int:
    """'--post-log CODE' — show the remembered posts for a shop:
    file, when ingested, validity date (the pipeline's memory).

    The code resolves to its STORE (marathon G8 fix 2026-09-08): FRU,
    legacy FRUT and timestamped FRUddmmyyHHMM all show the same
    shop's posts."""
    code = code.strip().upper()
    store = _store_for_code(code)
    if store is None:
        print(f"[post-log] unknown code: {code}")
        return 1
    key = store["key"]

    def _same_shop(entry_code: str) -> bool:
        s = _store_for_code(str(entry_code or ""))
        return s is not None and s["key"] == key

    entries = [e for e in _load_post_log() if _same_shop(e.get("code"))]
    if not entries:
        print(f"[post-log] {code}: nothing recorded yet")
        return 1
    print(f"[post-log] {code}: {len(entries)} post(s) on record")
    for e in entries[-10:]:
        print(f"   {e.get('file')} | ingested {e.get('ingested_at')}"
              f" | valid until {e.get('valid_until') or 'UNKNOWN'}"
              f" | {e.get('items')} items")
    return 0


def _restamp_undated(grid: list, store_key: str,
                     valid_until: "date") -> tuple[list, int]:
    """Stamp the store's UNDATED special cells + row 2 (checker fix
    2026-09-08: --set-date previously recorded the date only in the
    post log — the sheet kept bare cells and a blank validity row, so
    the user could not see the validity).

    Only cells WITHOUT an existing ' (till ...)' stamp are touched
    (a dated cell keeps its own date); row 2 gets the store summary
    stamp. Returns (grid, stamped_count).
    """
    if isinstance(store_key, dict):     # _store_for_code() shape
        store_key = store_key.get("key", "")
    col = _special_column_for(store_key)
    if col is None:
        return grid, 0
    grid = [list(r) for r in grid]
    width = len(TAB_COLUMNS) + 1
    grid = [(r + [""] * width)[:width] for r in grid]
    if len(grid) < 2 or str(grid[1][0]).strip() != \
            "Prices valid until":
        return grid, 0
    stamped = 0
    for row in grid[2:]:
        cell = str(row[col]) if len(row) > col else ""
        if cell.strip() and "(till" not in cell.lower():
            row[col] = _stamp_validity(cell, valid_until)
            stamped += 1
    grid[1][col] = f"valid until {valid_until:%a %d %b}"
    return grid, stamped


def set_date_cmd(code: str, filename: str, date_text: str) -> int:
    """'--set-date CODE FILE DATE' — record a validity date for a
    pasted post whose board didn't show one, and archive the file.

    The date is ALSO stamped onto the sheet: every undated special
    cell of that store + the row-2 summary (checker fix 2026-09-08).

    Args:
        code: the notification's inbox code (FRU0709260507; legacy
            FRUT / FRUT_1).
        filename: the file name inside needs_date/ (or processed/
            when re-running set-date to fix stamps).
        date_text: e.g. "2026-09-12" or "12 September".
    """
    from core.sydney_time import sydney_today
    from extractors.deal_text import parse_validity_end

    code = code.strip().upper()
    store = _store_for_code(code)
    if store is None:
        print(f"[set-date] unknown code: {code}")
        return 1
    # S5 (user directive 2026-09-11): 'open' = the user's explicit
    # answer "leave it undated" — records the decision, clears the
    # repeating question, stamps nothing.
    open_undated = str(date_text or "").strip().lower() == "open"
    valid_until = None
    if not open_undated:
        valid_until = parse_validity_end(
            "valid until " + date_text, today=sydney_today())
        if valid_until is None:
            parsed = None
            try:
                parsed = date.fromisoformat(date_text.strip())
            except ValueError:
                pass
            valid_until = parsed
        if valid_until is None:
            print(f"[set-date] could not read a date from: {date_text}")
            return 1

    folder = inbox_dir_for(code)
    needs = folder / "needs_date"
    src = needs / filename
    done = folder / "processed"
    done.mkdir(parents=True, exist_ok=True)
    if src.exists():
        src.replace(done / filename)
    elif not (done / filename).exists():
        # Sweep-ingested posts keep no inbox file (their images stay
        # in the run dir) — the date answer still records + stamps.
        print(f"[set-date] {filename}: no inbox file for {code} "
              f"(sweep post?) — recording the date anyway")

    entries = _load_post_log()
    for e in entries:
        if e.get("code") == code and e.get("file") == filename:
            e["valid_until"] = (valid_until.isoformat()
                                if valid_until else None)
            e["archived"] = "processed"
            break
    else:
        entries.append({"code": code, "file": filename,
                        "valid_until": (valid_until.isoformat()
                                        if valid_until else None),
                        "ingested_at": sydney_now().isoformat(
                            timespec="seconds"), "items": None,
                        "archived": "processed"})
    _save_post_log(entries)
    cleared = clear_questions(code, filename)

    # Sheet stamps (checker fix): the tab reflects the date now.
    stamped = 0
    if valid_until is not None:
        try:
            from core.sheets_client import connect_worksheet
            tab = connect_worksheet().spreadsheet.worksheet(TAB_NAME)
            grid, stamped = _restamp_undated(tab.get_all_values(),
                                             store, valid_until)
            tab.clear()
            tab.freeze(rows=2)
            tab.update(values=grid,
                       range_name=f"A1:K{len(grid)}")
        except Exception as exc:  # noqa: BLE001 — log update already safe
            print(f"[set-date] ⚠️ sheet re-stamp failed: {exc}")
    outcome = (f"valid until {valid_until:%a %d %b}"
               if valid_until else "left undated (open)")
    print(f"[set-date] {filename}: {outcome} recorded and archived"
          + (f" · {stamped} cell(s) stamped" if stamped else "")
          + (f" · {cleared} question(s) cleared" if cleared else ""))
    return 0


def resolve_shop_cmd(code: str, shop: str) -> int:
    """'--resolve-shop CODE SHOP' (P4, user directive 2026-09-11):
    complete a pending AUTO… watch-folder drop — re-point its inbox
    folder at the named shop, clear the shop question, ingest now.

    Args:
        code: the AUTO… code shown in the digest question.
        shop: dunya | merjan | fruitopia | abusalim (prefixes/aliases
            like 'mer', 'abu salim', or the full shop name all work).

    Returns:
        int: the ingest's exit code, or 1 on unknown shop/no files.
    """
    from extractors.fb_flyer_fetch import STORES

    code = code.strip().upper()
    raw = " ".join(str(shop or "").lower().split())
    aliases = {}
    for s in STORES:
        aliases[s["key"]] = s
        aliases[s["code"].lower()] = s
        aliases[s["name"].lower()] = s
    store = aliases.get(raw) or next(
        (s for s in STORES if s["name"].lower().startswith(raw)),
        None)
    if store is None:
        print(f"[resolve-shop] unknown shop '{shop}' — use dunya | "
              f"merjan | fruitopia | abusalim")
        return 1
    old_folder = INBOX_DIR / code
    if not old_folder.is_dir() or not _all_inbox_files(old_folder):
        print(f"[resolve-shop] {code}: no pending files in the inbox")
        return 1
    base = f"{store['code']}{sydney_now():%d%m%y%H%M}"
    new_code = base
    n = 1
    while (INBOX_DIR / new_code).exists():
        n += 1
        new_code = f"{base}_{n}"
    old_folder.rename(INBOX_DIR / new_code)
    clear_questions(code)
    print(f"[resolve-shop] {code} -> {new_code} ({store['name']}) "
          f"— ingesting")
    return ingest_code(new_code)


def inbox_dir_for(code: str) -> Path:
    """The per-code inbox folder, created on demand."""
    d = INBOX_DIR / code.strip().upper()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _newest_inbox_file(folder: Path) -> Path | None:
    """Newest non-hidden file in the folder (mtime), or None."""
    files = _all_inbox_files(folder)
    return files[0] if files else None


def _all_inbox_files(folder: Path) -> list[Path]:
    """Every non-hidden file in the folder, newest first.

    The user may paste ALL of a shop's recent post images at once
    (e.g. Merjan made 5 posts in 3 days) — ingest processes every
    one of them, one vision call per image, in a single command.
    """
    files = [p for p in folder.iterdir()
             if p.is_file() and not p.name.startswith(".")]
    return sorted(files, key=lambda p: p.stat().st_mtime,
                  reverse=True)


def _norm_grid(grid: list) -> list[list]:
    """Row-padded width-normalised copy of a tab grid."""
    width = len(TAB_COLUMNS) + 1
    return [(list(r) + [""] * width)[:width] for r in grid]


def _digest_items(converted: list[dict],
                  changes: dict | None = None) -> list[dict]:
    """Digest item records from vision-schema deals: price text with
    unit, 'min order …' terms, per-item till date, and the previous
    price when a re-post moved it (S7 'was $X -> now $Y')."""
    from core.multibuy import effective_unit_rate
    from core.uom import FAMILY_WEIGHT, parse_size
    changes = changes or {}
    items: list[dict] = []
    for c in converted:
        kind = c.get("price_kind")
        price = c.get("price")
        unit = (c.get("unit") or "").lower()
        terms = None
        per_kg = None
        if kind == "bulk_pack":
            size = str(c.get("bulk_size") or "")
            price_text = f"{_money(float(price or 0))} {size}".strip()
            terms = f"{size} pack"
            parsed = parse_size(size)
            if parsed is not None \
                    and parsed.family == FAMILY_WEIGHT \
                    and parsed.value > 0 and price:
                per_kg = round(float(price)
                               / (parsed.value / 1000.0), 2)
        elif kind == "multibuy":
            qty = int(c.get("multibuy_qty") or 0)
            total = float(price or 0)
            rate = (effective_unit_rate(qty, total)
                    if qty >= 2 and total > 0 else None)
            price_text = (f"{_money(rate)}/{unit}"
                          if rate is not None else "?")
            terms = (f"{qty}kg for {_money(total)}" if unit == "kg"
                     else f"{qty} for {_money(total)}")
            per_kg = rate if unit == "kg" else None
        else:
            price_text = (f"{_money(float(price))}/{unit}"
                          if price else "?")
            per_kg = float(price) if unit == "kg" else None
        display = _display_name(c)
        items.append({
            "name": display, "price_text": price_text,
            "terms": terms,
            "till": (f"{c['valid_until']:%a %d %b}"
                     if c.get("valid_until") else None),
            "was": changes.get(display), "per_kg": per_kg})
    return items


def _ingest_unknown_shop(code: str, dry_run: bool = False) -> int:
    """AUTO… codes (P4, user directive 2026-09-11): a watch-folder
    root drop with no shop subfolder. Files STAY pending — nothing is
    written, never a guess (the S10/S16 rule) — and the digest asks
    which shop the board belongs to; --resolve-shop completes it.
    """
    folder = inbox_dir_for(code)
    files = _all_inbox_files(folder)
    if not files:
        print(f"[ingest] no file in {folder}")
        return 1
    if dry_run:
        print(f"[ingest] {code}: {len(files)} file(s) awaiting shop "
              f"resolution (dry-run)")
        return 0
    open_question(
        "shop", code, files[0].name, "",
        f"{code} (saved from your watch folder): which shop is this "
        f"board? reply with the shop — dunya / merjan / fruitopia / "
        f"abusalim")
    _post_digest(_render_window_digest(
        [], _load_questions(),
        f"Watch-folder drop {code}"))
    print(f"[ingest] {code}: {len(files)} file(s) pending — shop "
          f"question asked")
    return 0


def ingest_code(code: str, dry_run: bool = False) -> int:
    """Process EVERY file in data/local_deals_inbox/<CODE>/.

    The user copies a shop's post content into the inbox and replies
    with the code — ALL files are processed, newest first (one vision
    call per image; text files through the deal-line parser), so a
    shop with several posts is one command. On success the
    Local_Deals tab is UPDATED for this store only (merge — other
    stores' rows untouched) and one combined summary is posted to
    the local-deals topic.

    Args:
        code: the notification's inbox code (FRU0709260507; legacy
            FRUT / FRUT_1).
        dry_run: parse and print only; no sheet write, no Telegram.

    Returns:
        int: 0 processed, 1 nothing readable / bad code.
    """
    from extractors.deal_text import (
        parse_fruitopia_deals, parse_validity_end,
    )
    from core.sydney_time import sydney_today

    code = code.strip().upper()
    store = _store_for_code(code)
    if store is None and code.startswith("AUTO"):
        # P4: shop-less watch-folder drop — ask, never guess.
        return _ingest_unknown_shop(code, dry_run=dry_run)
    if store is None:
        print(f"[ingest] unknown code: {code}")
        return 1
    folder = inbox_dir_for(code)
    files = _all_inbox_files(folder)
    if not files:
        print(f"[ingest] no file in {folder}")
        return 1
    print(f"[ingest] {code}: processing {len(files)} file(s)")
    today = sydney_today()

    all_vision_deals: list[dict] = []
    batches: list[dict] = []     # per-file summaries (writable)
    expired_batches: list[dict] = []   # FIX-4 (D2): read, never written
    notice_batches: list[dict] = []    # S11: zero-price posts, no writes
    unreadable_files: list[str] = []   # S10/S16: vision failed, pending
    category = _store_kind(store["key"]) or "other"
    for path in files:
        try:
            if path.suffix.lower() in (".txt", ".text", ".md"):
                text = path.read_text(encoding="utf-8",
                                      errors="replace")
                deals = parse_fruitopia_deals(text)
                source = "text"
                valid_until = parse_validity_end(text, today=today)
            elif path.suffix.lower() in (".jpg", ".jpeg", ".png",
                                         ".webp"):
                from core.flyer_vision import parse_board_images
                payload = parse_board_images([path])
                deals = payload.get("deals") or []
                source = "vision"
                raw_until = payload.get("valid_until")
                try:
                    valid_until = (date.fromisoformat(str(raw_until))
                                   if raw_until else None)
                except ValueError:
                    valid_until = None
            else:
                print(f"[ingest] {path.name}: unsupported type "
                      f"{path.suffix} — skipped")
                continue
        except Exception as exc:   # noqa: BLE001 — file isolation
            # S10/S16 (user directive 2026-09-11): vision failure on a
            # file writes NOTHING, the file stays pending (retried on
            # the next better file) and the digest flags it.
            print(f"[ingest] {path.name}: "
                  f"{exc.__class__.__name__} — flagged unreadable")
            unreadable_files.append(path.name)
            continue

        # Q17 (Round 3): butchery posts are prefixed at normalization
        # — every item, whatever the type; fruit shops never.
        deals = _prefix_butcher_deals(store["key"], deals)

        if not deals:
            # S11: an announcement/notice post — detected, recorded as
            # zero-item, never a tab write.
            print(f"[ingest] {path.name}: 0 prices read — notice only")
            notice_batches.append({
                "file": path.name, "deals": [],
                "valid_until": None,
                "snippet": (
                    _post_snippet(text) if source == "text" else
                    "(image-only post — no text)")})
            continue
        # FIX-4 (D2): freshness gate — a board whose printed end date
        # is already past writes NOTHING (user rule 2026-09-09; the
        # 6-Sep FRUT board was fully written on 8-Sep). Undated boards
        # keep today's behavior (needs-date review).
        if valid_until is not None and valid_until < today:
            print(f"[ingest] {path.name}: deals ended "
                  f"{valid_until:%a %d %b} — nothing written")
            expired_batches.append({
                "file": path.name, "deals": deals,
                "valid_until": valid_until, "expired": True,
                "snippet": (
                    _post_snippet(text) if source == "text" else
                    ", ".join(d["item"] for d in deals[:3])
                    + ("…" if len(deals) > 3 else ""))})
            continue
        valid_txt = (f"valid until {valid_until:%a %d %b}"
                     if valid_until
                     else "valid until — date to confirm")
        print(f"[ingest] {path.name}: {len(deals)} items "
              f"({source}; {valid_txt})")
        for d in deals:
            note = f" ({d['multibuy_note']})" \
                if d.get("multibuy_note") else ""
            print(f"   - {d['item']} — "
                  f"{_money(d.get('unit_price', d['price']))}"
                  f"/{d['unit']}{note}")
        batches.append({"file": path.name, "deals": deals,
                        "valid_until": valid_until,
                        "valid_txt": valid_txt,
                        "snippet": (
                            _post_snippet(text)
                            if source == "text" else
                            ", ".join(d["item"] for d in deals[:3])
                            + ("…" if len(deals) > 3 else ""))})
        converted = [_to_vision_deal(d, category) for d in deals]
        for c, d in zip(converted, deals):
            # Per-post validity rides on every deal — merge_store_tab
            # stamps each special cell with ITS OWN post's date, so
            # two posts with different end dates coexist (user rule
            # 2026-09-07). S6 (2026-09-11): an ITEM-level date read
            # from the line itself wins over the post-level date.
            c["valid_until"] = d.get("valid_until") or valid_until
        all_vision_deals.extend(converted)
        batches[-1]["converted"] = converted

    if not all_vision_deals and not expired_batches \
            and not notice_batches and not unreadable_files:
        print("[ingest] nothing readable in the folder")
        return 1
    if dry_run:
        print("[ingest] dry-run: sheet write + summary skipped")
        return 0

    changes: dict[str, float] = {}    # display name -> previous price
    standout_block: list[str] = []
    if all_vision_deals:
        from core.sheets_client import connect_spreadsheet
        spreadsheet = connect_spreadsheet()
        worksheet = ensure_local_deals_tab(spreadsheet)
        # FB-post ingest targets the shop's FB specials column (Dunya:
        # "dunya_fb"); the site column is --dunya-site's.
        col_store = ("dunya_fb" if store["key"] == "dunya"
                     else store["key"])
        # S7 (user directive 2026-09-11): snapshot the shop's cells
        # before the merge so the digest can show 'was $X -> now $Y'
        # when a same-day re-post moves a price.
        sp_col = _special_column_for(store["key"])
        before_grid = _norm_grid(worksheet.get_all_values() or [])
        # Files are newest-first; reversed so the NEWEST post's deal
        # wins when two posts list the same item (older posts never
        # overwrite fresher prices on the sheet). Validity stays per
        # post/file in the post log + summary — never merged away.
        newest_valid = next((b["valid_until"] for b in batches
                             if b["valid_until"]), None)
        # §4.2 parity auto-create: the SAME operation bottom-appends
        # the blank master counterpart (name + code + sub-category;
        # D/G blank) for every NEW row.
        rows, new_rows = merge_store_tab(
            worksheet, col_store,
            list(reversed(all_vision_deals)),
            valid_until=newest_valid,
            master_ws=spreadsheet.worksheet(MASTER_TAB))
        print(f"[ingest] Local_Deals tab updated ({rows} rows incl. "
              f"headers)")
        for line in new_rows:
            print(f"   + {line}")
        after_grid = _norm_grid(worksheet.get_all_values() or [])
        if sp_col is not None:
            # S7 'was' priority: the OLDER same-window post's price
            # when the item repeats, else the replaced sheet value.
            older_post: dict[str, float] = {}
            for c in reversed(all_vision_deals):    # merge order
                older_post.setdefault(_display_name(c),
                                      c.get("price"))
            for c in reversed(all_vision_deals):
                display = _display_name(c)
                i_new = _reuse_match_index(after_grid, display)
                new = _numeric_price(
                    after_grid[i_new][sp_col]
                    if i_new is not None
                    and len(after_grid[i_new]) > sp_col else None)
                was = older_post.get(display)
                if was is not None and new is not None \
                        and abs(float(was) - new) >= 0.01:
                    changes.setdefault(display, round(float(was), 2))
                    continue
                i_old = _reuse_match_index(before_grid, display)
                if i_old is None or i_new is None:
                    continue
                old = _numeric_price(
                    before_grid[i_old][sp_col]
                    if len(before_grid[i_old]) > sp_col else "")
                if old is not None and new is not None \
                        and abs(new - old) >= 0.01:
                    changes.setdefault(display, old)

        # Standout check vs the master sheet — the SAME >20% machinery
        # as the Friday/on-demand report (user rule 2026-09-07: the
        # alert must show up at ingest time, not only in the report).
        # Each batch carries its OWN validity; expired batches are
        # recorded but never compared.
        try:
            from core.sheets_client import connect_worksheet
            master_rows = _load_master_rows(connect_worksheet())
            scan_rows = []
            for b in batches:
                for d in b["deals"]:
                    row = dict(d)
                    row["store_key"] = store["key"]
                    if b["valid_until"]:
                        row["valid_until"] = b["valid_until"]
                    scan_rows.append(row)
            results = match_and_detect(scan_rows, master_rows, {})
            standout_block = render_post1(
                results,
                sydney_now().strftime("%a %Y-%m-%d")).splitlines()
        except Exception as exc:  # noqa: BLE001 — degrade cleanly
            print(f"[ingest] standout check failed: "
                  f"{exc.__class__.__name__}")
            standout_block = ["⚠️ Standout check failed — run the "
                              "local-deals report later"]
    else:
        # FIX-4 (D2): every readable post was already expired — the
        # freshness gate wrote 0 cells; say so.
        print("[ingest] 0 cells written — every readable post had "
              "already ended")

    # S5 (user directive 2026-09-11): undated boards open the expiry
    # question — it repeats in EVERY digest until answered ('open'
    # leaves the board undated) via the existing set-date path.
    shop_label = SHORT_SHOP_NAMES.get(store["key"], store["name"])
    for b in batches:
        if not b["valid_until"]:
            open_question(
                "expiry", code, b["file"], store["key"],
                f"{shop_label}: no end date on this board "
                f"({code} {b['file']}) — reply with the date, or "
                f"'open' to leave it undated")
            print(f"[ingest] {b['file']} — expiry question asked")

    # The ONE digest for this ingest (instant path): items, terms,
    # per-item validity, changes, notices, unreadable flags,
    # standouts, and every open question.
    posts = [{
        "code": code, "file": b["file"],
        "valid_txt": b["valid_txt"],
        "items": _digest_items(b.get("converted") or [], changes),
        "notice_only": False, "unreadable": False,
    } for b in batches]
    posts += [{"code": code, "file": n["file"], "valid_txt": "",
               "items": [], "notice_only": True, "unreadable": False}
              for n in notice_batches]
    posts += [{"code": code, "file": f, "valid_txt": "", "items": [],
               "notice_only": False, "unreadable": True}
              for f in unreadable_files]
    _post_digest(_render_window_digest(
        [{"shop_label": shop_label, "shop": store["name"],
          "posts": posts}],
        _load_questions(),
        f"Ingest {code}",
        standout_lines=standout_block or None))

    # Archive what was processed; route unknown-validity files to
    # needs_date/ (settled later with --set-date). Everything is
    # remembered in the post log: file, snippet, validity, items —
    # expired boards included, flagged expired: true (FIX-4: read,
    # refused, never re-alerted).
    entries = _load_post_log()
    for b in batches + expired_batches + notice_batches:
        is_expired = bool(b.get("expired"))
        sub = ("processed" if (b["valid_until"] or is_expired
                               or not b.get("deals"))
               else "needs_date")
        dest_dir = folder / sub
        dest_dir.mkdir(parents=True, exist_ok=True)
        src = folder / b["file"]
        try:
            src.replace(dest_dir / b["file"])
        except OSError:
            pass
        entry = {"code": code, "file": b["file"],
                 "valid_until": (b["valid_until"].isoformat()
                                 if b["valid_until"]
                                 else None),
                 "ingested_at": sydney_now().isoformat(
                     timespec="seconds"),
                 "items": len(b["deals"]),
                 "snippet": b["snippet"],
                 "archived": sub}
        if is_expired:
            entry["expired"] = True
        entries.append(entry)
    _save_post_log(entries)
    needs = [b for b in batches if not b["valid_until"]]
    if needs:
        print("[ingest] posts missing a validity date (question "
              "asked; repeats in every digest until answered):")
        for b in needs:
            print(f"   {b['file']} — starts with: {b['snippet']}")
        print("[ingest] reply with the dates (e.g. '<code> board.jpg "
              "valid until 12 September') or 'open' to leave "
              "undated")

    # All posts are handled: clear every pending code for this shop
    # (the next alert mints a fresh timestamped code).
    state = _load_scan_state()
    seen = state.setdefault("stores", {}).setdefault(store["key"], {})
    freed = sorted(seen.get("notified", {}).values())
    seen["notified"] = {}
    _save_scan_state(state)
    if freed:
        print(f"[ingest] code(s) {', '.join(freed)} completed — "
              f"the next alert mints a fresh code")
    return 0


def friday_gate_open(now: datetime | None = None) -> bool:
    """True iff now is Friday 05:00-05:59 Sydney AND not yet fired.

    DST-proof via zoneinfo. A missing/corrupt state file counts as
    not-fired (silently re-fires — D-LD1).

    Args:
        now: injectable clock (tests); defaults to real now.

    Returns:
        True when the Friday send window is open for today.
    """
    now_syd = (now or sydney_now()).astimezone(
        ZoneInfo(SYDNEY_TZ))
    if now_syd.weekday() != 4 or now_syd.hour != 5:
        return False
    state = _load_gate_state()
    return state.get("last_fire_date") != now_syd.date().isoformat()


def friday_gate_mark_fired(now: datetime | None = None) -> None:
    """Write {"last_fire_date": YYYY-MM-DD} (Sydney) after ANY fired
    run (success OR failure) — one send per Friday.

    Args:
        now: injectable clock (tests); defaults to real now.
    """
    now_syd = (now or sydney_now()).astimezone(
        ZoneInfo(SYDNEY_TZ))
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({"last_fire_date": now_syd.date().isoformat()},
                   indent=2),
        encoding="utf-8")


SECTION_ORDER = ("FRUITS", "BUTCHERY", "OTHER")

TAB_COLUMNS = [  # Local_Deals tab layout v2.1 (user rule 2026-09-07,
    # + Round-2 col K): every shop gets a PERMANENT column (no
    # validity) and a SPECIAL column (validity-stamped cells);
    # comparisons read special first, then permanent.
    ("dunya_perm", "Dunya perm (site)"),   # dunyabutchery.com.au
    ("dunya_sp", "Dunya special (FB)"),    # Facebook post prices
    ("merjan_perm", "Merjan perm"),
    ("merjan_sp", "Merjan special"),
    ("fruitopia_perm", "Fruitopia perm"),
    ("fruitopia_sp", "Fruitopia special"),
    ("abusalim_perm", "Abu Salim perm"),
    ("abusalim_sp", "Abu Salim special"),
    ("comments", "Comments"),       # shop-tagged multibuy/bulk notes
    ("item_code", "Item_Code"),     # col K: paired master code (v2)
]
# Kept for callers that reason about the four physical shops.
STORE_COLUMNS = [
    ("dunya", "Dunya (site)"),
    ("merjan", "Merjan Brothers Quality Meats"),
    ("fruitopia", "Fruitopia Mt Druitt"),
    ("abusalim", "Abu Salim Fruit Market"),
]
TAB_NAME = "Local_Deals"
# The master tab is opened by NAME through THIS constant only
# (the test_products_master_single_read_occurrence grep guard
# counts the literal: read-helper docstring + this line).
MASTER_TAB = "Products_Master"
SHOP_TAGS = {"dunya": "DUN", "merjan": "MER",
             "fruitopia": "FRU", "abusalim": "ABS"}


def _grid_col(key: str) -> int | None:
    """Row-list index for a TAB_COLUMNS key (0 = Product name;
    'comments' -> 9). Sheet column = index + 1 (A1 range is fixed)."""
    return next((i + 1 for i, (k, _n) in enumerate(TAB_COLUMNS)
                 if k == key), None)


def _perm_column_for(store_key: str) -> int | None:
    """1-based permanent-price column for a shop key."""
    return _grid_col(f"{store_key}_perm")


def _special_column_for(store_key: str) -> int | None:
    """1-based special-price column for a shop key."""
    return _grid_col(f"{store_key}_sp")


def _target_column(store_key: str) -> tuple[int | None, str]:
    """(1-based column, kind) a deals store_key writes to.

    'dunya' (site catalogue) -> permanent column; every FB-post key
    ('dunya_fb', or a plain shop key) -> the SPECIAL column.
    """
    if store_key == "dunya":
        return _perm_column_for("dunya"), "perm"
    if store_key == "dunya_fb":
        return _special_column_for("dunya"), "special"
    return _special_column_for(store_key), "special"


def _column_for(store_key: str) -> int | None:
    """Legacy shim: the column a store key targets (perm for the
    Dunya site key, special for every FB-post key)."""
    return _target_column(store_key)[0]


def _comment_tag(store_key: str) -> str:
    """Shop tag for the shared Comments column ('FRU', 'MER', ...)."""
    return SHOP_TAGS.get(store_key.replace("_fb", ""), "DUN")


def _tag_note(store_key: str, note: str) -> str:
    """'[FRU] multi buy 2 for $1.50 — $0.75/ea' (shop-tagged).

    ID-3 (user directive 2026-09-11): any shop tag embedded in the
    note text is stripped FIRST — the cell merge stays strip-then-
    append per shop, so a tag can never stack ('[MER] [MER] …')."""
    clean = _TAG_RE.sub("", str(note or "")).strip()
    return f"[{_comment_tag(store_key)}] {clean}"


_TAG_RE = re.compile(r"\[(DUN|MER|FRU|ABS)\]\s*")
_TAG_TO_SHOP = {"DUN": "dunya", "MER": "merjan",
                "FRU": "fruitopia", "ABS": "abusalim"}


def _shop_key_for_tag(tag: str) -> str:
    """'FRU' -> 'fruitopia' (the shop behind a Comments tag)."""
    return _TAG_TO_SHOP.get(tag, "dunya")


def _strip_shop_segments(existing: str, shop_keys) -> str:
    """Comments cell without the given shops' tag segments."""
    cur = str(existing or "")
    for sk in shop_keys:
        cur = _merge_comment_cell(cur, sk, "")
    return cur


def _merge_comment_cell(existing: str, store_key: str, note: str
                        ) -> str:
    """Shared Comments cell for one row: THIS shop's tagged note is
    replaced, every OTHER shop's tag segment is kept (user rule
    2026-09-07 — two shops sharing a row keep their notes apart).

    Args:
        existing: current Comments cell text (may be "").
        store_key: the shop writing a note.
        note: the note text ("" clears this shop's segment).

    Returns:
        The merged cell text ('' when nothing remains).
    """
    tag = _comment_tag(store_key)
    others: list[str] = []
    for seg in str(existing or "").split(";"):
        seg = seg.strip()
        if not seg:
            continue
        m = _TAG_RE.match(seg)
        # ID-3 robustness: an untagged free-text segment is KEPT
        # (never crashes the merge — the morning scramble came from
        # tag handling that could not digest what it had written).
        if m is None or m.group(1) != tag:
            others.append(seg)
    if not note:
        return "; ".join(others)
    return "; ".join(others + [_tag_note(store_key, note)])


# --- validity-stamped special cells -------------------------------------
# Format: "<price or offer> (till 12 Sep)" — the date is parsed by
# the sweep and ignored by numeric readers; undated cells stay until
# replaced (never swept).

_TILL_RE = re.compile(
    r"\s*\((?:valid )?till\s+(\d{1,2})\s+([A-Za-z]+)\)\s*$", re.I)


def _stamp_date(cell: str, today: "date") -> "date | None":
    """Row-2 summary-stamp date for 'valid until Fri 11 Sep', or None.

    R2-6 (D21): the stamp carries a WEEKDAY-prefixed date ("%a %d %b"),
    which _cell_till_date's '(till d Mon)' pattern cannot parse — this
    helper keeps the old sweep's generic first-date extraction (with
    the >180-day rollback for stale year-crossing stamps).
    """
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)", str(cell or ""))
    if not m:
        return None
    month = _month_num(m.group(2))
    if month is None:
        return None
    try:
        stamp = date(today.year, month, int(m.group(1)))
    except ValueError:
        return None
    if (stamp - today).days > 180:
        try:
            return date(today.year - 1, month, int(m.group(1)))
        except ValueError:
            return None
    return stamp


def _stamp_validity(cell, valid_until: "date | None"):
    """Append ' (till 12 Sep)' to a special cell (date aware)."""
    if valid_until is None or cell is None:
        return cell
    return f"{cell} (till {valid_until.day} {valid_until:%b})"


def _strip_till(text: str) -> str:
    """'0.75 (till 12 Sep)' -> '0.75' (the cell without its stamp)."""
    return _TILL_RE.sub("", str(text or "")).strip()


def _month_num(token: str) -> int | None:
    """Month number for 'Sep' / 'september' (3-letter prefix match)."""
    from extractors.deal_text import MONTHS
    t = (token or "").lower()[:3]
    return next((num for name, num in MONTHS.items()
                 if name[:3] == t), None)


def _cell_till_date(cell, today: "date") -> "date | None":
    """The validity end stamped in a special cell, or None.

    Accepts ' (till 12 Sep)' / ' (till 12 September)'. The year is
    today's year, rolled back one year when that would land more
    than 180 days ahead (a stale cell from last December).
    """
    m = _TILL_RE.search(str(cell or ""))
    if not m:
        return None
    month = _month_num(m.group(2))
    if month is None:
        return None
    try:
        candidate = date(today.year, month, int(m.group(1)))
    except ValueError:
        return None
    if (candidate - today).days > 180:
        try:
            candidate = date(today.year - 1, month, int(m.group(1)))
        except ValueError:
            return None
    return candidate


def _special_expired(cell, today: "date") -> bool:
    """True when a special cell carries a validity date in the past."""
    until = _cell_till_date(cell, today)
    return until is not None and until < today


def ensure_local_deals_tab(spreadsheet) -> "Worksheet":
    """Return the Local_Deals worksheet, creating it when missing.

    Raises RuntimeError (secret-free) when creation fails.
    """
    try:
        return spreadsheet.worksheet(TAB_NAME)
    except Exception:  # noqa: BLE001 — missing tab falls through to create
        pass
    try:
        return spreadsheet.add_worksheet(title=TAB_NAME, rows=200,
                                         cols=10)
    except Exception as exc:  # noqa: BLE001 — secret-free re-raise
        raise RuntimeError(
            f"Failed to ensure {TAB_NAME} tab: "
            f"{exc.__class__.__name__}") from exc


def _store_kind(store_key: str) -> str:
    """'butchery' | 'fruits' for a store key ('' when unknown)."""
    from extractors.fb_flyer_fetch import STORES
    if store_key in ("dunya", "dunya_fb"):
        return "butchery"        # dunya_fb = Dunya's Facebook posts
    return next((s["kind"] for s in STORES if s["key"] == store_key),
                "")


def _prefix_butcher_deals(store_key: str, deals: list) -> list:
    """Q17 halal prefix at deal normalization: EVERY item from a
    butchery-source store gets the 'Halal ' prefix — regardless of
    item type; fruit shops are never prefixed. Idempotent (an item
    already carrying 'halal' stays as-is) and order-preserving; the
    deals are mutated in place AND returned for chaining. The master
    side inherits the same name via the bottom-append mirror, so
    plain (non-halal) master rows can never pair with butchery items
    (Q11, spec §5)."""
    if _store_kind(store_key) != "butchery":
        return deals
    for deal in deals:
        item = str(deal.get("item") or "").strip()
        if item and "halal" not in item.lower():
            deal["item"] = f"Halal {item}"
    return deals


def _section_for(deal: dict) -> str:
    """FRUITS for category 'fruits', BUTCHERY for 'butchery', else
    OTHER (out-of-domain items are recorded — B7/B10)."""
    if deal.get("category") == "fruits":
        return "FRUITS"
    if deal.get("category") == "butchery":
        return "BUTCHERY"
    return "OTHER"


def _display_name(deal: dict) -> str:
    """Canonical Col A text: item + ' /kg' | ' /ea' suffix for unit
    deals; bulk rows carry the size in the name ('Potatoes 5kg')."""
    item = str(deal.get("item") or "").strip()
    kind = deal.get("price_kind")
    if kind == "bulk_pack":
        size = str(deal.get("bulk_size") or "").strip()
        return f"{item} {size}".strip()
    unit = deal.get("unit")
    if unit == "kg":
        return f"{item} /kg"
    if unit == "ea":
        return f"{item} /ea"
    return item


def _money(value: float) -> str:
    """Fixed two-decimal dollar text ('$2.99')."""
    return f"${value:.2f}"


def _bulk_note(deal: dict) -> str:
    """'[multi buy 5kg for $2.99]' exact wording (plan §1.4.6)."""
    return (f"[multi buy {deal.get('bulk_size')} "
            f"for {_money(float(deal.get('price') or 0))}]")


def _multibuy_note(deal: dict) -> str:
    """'[multi buy 2 for $15.00 — $7.50/ea]' (effective_unit_rate
    math, read-only reuse of core.multibuy semantics).

    ID-1 (user directive 2026-09-11): a /kg deal ('3kg for $32.99')
    carries the PACK TERMS in kg — 'multi buy 3kg for $32.99' — with
    NO per-ea rate suffix (the per-kg rate lives in the price cell;
    never per-ea on a /kg row)."""
    from core.multibuy import effective_unit_rate
    qty = int(deal.get("multibuy_qty") or 0)
    total = float(deal.get("price") or 0)
    if (deal.get("unit") or "").lower() == "kg":
        return f"[multi buy {qty}kg for {_money(total)}]"
    rate = effective_unit_rate(qty, total)
    return (f"[multi buy {qty} for {_money(total)} "
            f"— {_money(rate)}/ea]")


def _cell_for(deal: dict) -> tuple:
    """(price cell, comments cell) for one deal.

    Price cell: single deals -> the price; multibuy -> the effective
    UNIT rate (comparable number); bulk -> the bundle price. Comments
    cell: the multi-buy/bulk note text WITHOUT its enclosing brackets
    (the live-verified segment format '[MER] multi buy 3kg for
    $32.99' — what v2_read renders as 'min order …'; the bracketed
    note form is kept only for the in-place offer text fallback).
    None when the price is missing entirely.
    """
    kind = deal.get("price_kind")
    price = deal.get("price")
    note = ""
    if kind == "bulk_pack":
        note = _bulk_note(deal)
    elif kind == "multibuy":
        note = _multibuy_note(deal)
    if isinstance(price, (int, float)) and price > 0:
        cell = float(price)
        if kind == "multibuy":
            from core.multibuy import effective_unit_rate
            qty = int(deal.get("multibuy_qty") or 0)
            if qty:
                cell = round(effective_unit_rate(qty, cell), 2)
    elif note:
        cell = note          # keep the offer text visible in-place
    else:
        cell = None
    comment = note
    if comment.startswith("[") and comment.endswith("]"):
        comment = comment[1:-1]
    return cell, comment


def build_rows(all_store_deals: dict) -> dict:
    """{section: [[Product, Dunya perm(site), Dunya special(FB),
    Merjan perm, Merjan special, Fruitopia perm, Fruitopia special,
    Abu Salim perm, Abu Salim special, Comments], ...]}.

    Canonical rows (RF1): equivalent IN-DOMAIN items share ONE row
    keyed by canonical_key. The Dunya SITE key writes its PERMANENT
    column; every FB-post key writes its shop's SPECIAL column,
    validity-stamped ' (till 12 Sep)' when the deal carries a
    valid_until (user rule 2026-09-07). Multi-buy/bulk NOTE text is
    shop-tagged into the shared Comments column ('[FRU] ...'; two
    shops sharing a row keep their notes apart). Out-of-domain items
    NEVER merge into domain rows (Oreo rule) — standalone rows under
    OTHER.

    Args:
        all_store_deals: {store_key: [deal dicts with category +
            price_kind fields from the vision schema; optional
            valid_until date]}. store_key "dunya" targets the
            PERMANENT site column; "dunya_fb" and plain shop keys
            target the SPECIAL columns.

    Returns:
        section -> grid rows (10 cells each, "" for absent stores).
    """
    rows_by_section: dict[str, list[list]] = {
        s: [] for s in SECTION_ORDER}
    row_index: dict[tuple, int] = {}
    comments_col = _grid_col("comments")
    for store_key, deals in all_store_deals.items():
        in_domain_kind = _store_kind(store_key)
        col, kind = _target_column(store_key)
        for deal in deals:
            in_domain = deal.get("category") == in_domain_kind
            if not in_domain:
                section = "OTHER"
                key = ("od", store_key,
                       canonical_key(deal.get("item") or ""))
            else:
                # One row per canonical base: the numeric specials
                # price sits in the store's special column and the
                # multibuy/bulk note is shop-tagged in Comments.
                section = _section_for(deal)
                key = canonical_key(deal.get("item") or "")
            cell, comment = _cell_for(deal)
            if kind == "special":
                cell = _stamp_validity(cell, deal.get("valid_until"))
            display = _display_name(deal)
            slot = row_index.get((section, key))
            if slot is None:
                grid_row = [display] + [""] * (len(TAB_COLUMNS))
                rows_by_section[section].append(grid_row)
                row_index[(section, key)] = \
                    len(rows_by_section[section]) - 1
                slot = row_index[(section, key)]
            if col is not None and cell is not None:
                rows_by_section[section][slot][col] = cell
            if col is not None:
                # FIX-4 (D11): the NEWEST deal owns this shop's
                # comment segment — a plain price (empty note) CLEARS
                # it. Comments never outlive their prices.
                cur = rows_by_section[section][slot][comments_col]
                rows_by_section[section][slot][comments_col] = \
                    _merge_comment_cell(cur, store_key, comment)
    return {s: rows for s, rows in rows_by_section.items() if rows}


def rebuild_tab(worksheet, rows_by_section: dict,
                store_keys: list[str],
                validity: dict[str, str] | None = None) -> None:
    """Rewrite THIS run's shops' SPECIAL columns; preserve everything
    else (idempotent). ONE batch update A1:K{N}.

    Layout v2 semantics (user rule 2026-09-07):
    - PERMANENT columns (Dunya site + manual perm entries) are NEVER
      wiped — they survive rebuilds, subset runs and failures.
    - SPECIAL columns of shops IN this run are fully rebuilt from
      the parsed boards (an item no longer posted loses its special
      cell — old specials never linger).
    - SPECIAL columns of shops NOT in this run (fetch failed /
      --stores subset) are PRESERVED — a store whose list wasn't
      parsed is never marked (master-sync principle).
    - The shared Comments column is shop-tagged: this run's notes
      replace their shop's segment, other shops' notes survive.

    Row 2 is the "Prices valid until" summary row: one stamp per
    shop column (newest dated special); per-cell dates are
    authoritative. The Dunya PERM column is n/a (live site prices).

    Args:
        worksheet: gspread/Fake worksheet handle for Local_Deals.
        rows_by_section: build_rows() output.
        store_keys: shops in THIS run (their FB-post keys, e.g.
            "dunya_fb"; other shops' columns stay untouched).
        validity: optional {store_key: "valid until …"} row-2
            summary stamps.
    """
    run_keys = {k.strip() for k in (store_keys or []) if k and
                k.strip()}
    # Grid key -> the TAB_COLUMNS key this run's shop writes to.
    run_cols = {}
    for key in run_keys:
        col, _kind = _target_column(key)
        if col is not None:
            run_cols[col] = key
    comments_col = _grid_col("comments")
    perm_cols = {c for c in (_perm_column_for(s)
                             for s in SHOP_TAGS) if c is not None}

    old = worksheet.get_all_values() or []
    width = len(TAB_COLUMNS) + 1
    old = [(list(r) + [""] * width)[:width] for r in old]
    # Preserve: per (section, Col A name) the permanent cells, the
    # non-run shops' special cells, and the non-run shops' comments.
    preserved: dict[tuple, dict] = {}
    section = ""
    for row in old[1:]:
        first = str(row[0]).strip()
        if first in SECTION_ORDER:
            section = first
            continue
        if not first or section == "":
            continue
        keep = {"comments": str(row[comments_col] or "")}
        for i, (k, _n) in enumerate(TAB_COLUMNS, start=1):
            if i in perm_cols or i not in run_cols:
                if i != comments_col and str(row[i] or "").strip():
                    keep.setdefault("cells", {})[i] = row[i]
        preserved[(section, first)] = keep

    run_shop_keys = [k.replace("_fb", "") for k in run_keys]
    grid = [["Product"] + [name for _k, name in TAB_COLUMNS],
            ["Prices valid until", "n/a (live site)",
             "", "", "", "", "", "", "", "", ""]]
    # Row 2: keep non-run shops' existing summary stamps.
    if len(old) > 1 and str(old[1][0]).strip() == \
            "Prices valid until":
        for i in range(1, width):
            if i not in run_cols:
                grid[1][i] = old[1][i]

    seen: set[tuple] = set()
    for sec in SECTION_ORDER:
        section_rows = rows_by_section.get(sec) or []
        if not section_rows:
            continue
        grid.append([sec] + [""] * len(TAB_COLUMNS))
        for row in section_rows:
            row = list(row)
            name = str(row[0]).strip()
            # Overlay preserved non-run data on the rebuilt row:
            # permanent cells and non-run shops' special cells fill
            # only blanks; comments merge (other shops kept, this
            # run's notes replace their own).
            keep = preserved.get((sec, name))
            if keep:
                for i, cellv in (keep.get("cells") or {}).items():
                    if not str(row[i] or "").strip():
                        row[i] = cellv
                merged = _strip_shop_segments(
                    keep.get("comments") or "", run_shop_keys)
                for seg in str(row[comments_col] or "").split(";"):
                    seg = seg.strip()
                    m = _TAG_RE.match(seg)
                    if m:
                        merged = _merge_comment_cell(
                            merged,
                            _shop_key_for_tag(m.group(1)),
                            seg[m.end():].strip())
                row[comments_col] = merged
            seen.add((sec, name))
            grid.append(row)
    # Re-append rows this run no longer carries but which still hold
    # preserved data (other shops' prices / perm entries). This run's
    # shops' notes drop with their rebuilt specials.
    for sec in SECTION_ORDER:
        for (psec, name), keep in preserved.items():
            if psec != sec or (sec, name) in seen:
                continue
            cells = keep.get("cells") or {}
            comments = _strip_shop_segments(
                keep.get("comments") or "", run_shop_keys)
            if not (cells or comments):
                continue
            row = [name] + [""] * len(TAB_COLUMNS)
            for i, cellv in cells.items():
                row[i] = cellv
            row[comments_col] = comments
            grid.append(row)
    # Row 2 summary stamps for THIS run's shops.
    for key, text in (validity or {}).items():
        col = _target_column(key)[0]
        if col is not None and col != _perm_column_for("dunya"):
            grid[1][col] = text
    worksheet.clear()
    worksheet.freeze(rows=2)
    worksheet.update(values=grid, range_name=f"A1:K{len(grid)}")


@dataclass
class MatchResult:
    """One compared or recorded deal (fields per spec §6.4)."""
    store_key: str
    store_name: str
    item_name: str
    in_domain: bool
    alert: bool = False
    pct: float | None = None
    baseline_store: str = ""          # "Woolworths" | "Coles" | ""
    baseline_price: float | None = None
    flyer_price: float | None = None
    variety_conflict: bool = False
    matched_master: str = ""
    site_price_note: str = ""          # normal site price (Dunya)
    multibuy_note: str = ""            # bulk/multibuy note text
    deal_kind: str = "single"
    note: str = ""                     # informational lines
    _basis: str = "ea"                 # comparison basis: "kg" | "ea"


def _numeric_price(cell) -> float | None:
    """float > 0 when the cell parses as a price, else None (D-LD3).

    Decodes multi-buy cells via core.multibuy decode_multibuy_cell
    first (the rate IS the cell's price); a validity stamp
    (' (till 12 Sep)') is stripped before parsing. Marker cells
    (N/A <date>, unavailable <date>, GONE, blank) return None.
    """
    if isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell) if cell > 0 else None
    text = _strip_till(str(cell or ""))
    if not text:
        return None
    from core.multibuy import decode_multibuy_cell, effective_unit_rate
    decoded = decode_multibuy_cell(text)
    if decoded is not None:
        qty, total = decoded
        return effective_unit_rate(qty, total)
    try:
        value = float(text.replace("$", "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def _load_master_rows(worksheet) -> list[dict]:
    """READ-ONLY Products_Master scan (v2 13-column layout).

    Returns {row_index, name, category, size, wool_price,
    subcategory} (numeric-decoded D). Fixed indices per the v2
    layout (spec §3.1): A name, B coarse category, C size,
    D Woolworths, K Sub_Category. Never writes.
    """
    all_values = worksheet.get_all_values()
    if not all_values:
        return []

    def _cell(row: list, idx: int) -> str:
        return str(row[idx]).strip() if len(row) > idx else ""

    rows: list[dict] = []
    for i, row in enumerate(all_values[1:], start=2):
        name = _cell(row, 0)
        if not name:
            continue
        rows.append({
            "row_index": i,
            "name": name,
            "category": _cell(row, 1),
            "size": _cell(row, 2),
            "wool_price": _numeric_price(_cell(row, 3)),
            "subcategory": normalize_subcategory(_cell(row, 10)),
        })
    return rows


def _variety_conflict(flyer_item: str, master_name: str) -> bool:
    """EC2 guard (sandbox test3 logic, verbatim semantics).

    Both sides name the SAME variety -> no conflict; different
    varieties -> conflict; master names a variety the flyer lacks
    (generic vs varietied) -> conflict.
    """
    flyer_words = set(re.findall(r"[a-z0-9]+", flyer_item.lower()))
    master_words = set(re.findall(r"[a-z0-9]+", master_name.lower()))
    fv = {v for v in VARIETY_TOKENS
          if any(t in flyer_words for t in v.split())}
    mv = {v for v in VARIETY_TOKENS
          if any(t in master_words for t in v.split())}
    if fv and mv:
        return fv != mv            # both specific, different varieties
    return bool(mv and not fv)     # master varietied, flyer generic


def _unit_prices_agree(deal: dict, master_row: dict) -> bool:
    """Unit-family gate (plan §1.4.4): kg<->weight sizes, ea<->count;
    never weight<->volume<->count. Per-kg exception is scoped here.

    kg deals need a parseable WEIGHT master size (both sides $/kg);
    ea deals need a COUNT size (or no parseable size at all — the
    common 'unit unavailable' case cannot contradict); anything else
    reports a unit mismatch.
    """
    from core.uom import FAMILY_COUNT, FAMILY_WEIGHT, parse_size
    unit = (deal.get("unit") or "").lower()
    parsed = parse_size(master_row.get("size") or "")
    if unit == "kg":
        return parsed is not None and parsed.family == FAMILY_WEIGHT
    if unit == "ea":
        return parsed is None or parsed.family == FAMILY_COUNT
    return True


def _master_unit_price(master_row: dict) -> tuple[float, str, str] | None:
    """Master baseline on its comparison basis (Q20: RAW WW only).

    Returns (unit_price, basis, store_name) — $/kg when the size
    parses as weight, else the raw unit price on the 'ea' basis, from
    the Woolworths D cell. None when no numeric baseline.
    """
    from core.uom import FAMILY_WEIGHT, parse_size
    baseline = None
    price = master_row.get("wool_price")
    if price is not None:
        baseline = (price, "Woolworths")
    if baseline is None:
        return None
    parsed = parse_size(master_row.get("size") or "")
    if parsed is not None and parsed.family == FAMILY_WEIGHT \
            and parsed.value > 0:
        return (baseline[0] / (parsed.value / 1000.0), "kg",
                baseline[1])
    return (baseline[0], "ea", baseline[1])


def _deal_unit_price(deal: dict) -> tuple[float, str] | None:
    """Deal price on its comparison basis: (price, 'kg'|'ea')."""
    price = deal.get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        return None
    unit = (deal.get("unit") or "").lower()
    if unit == "kg":
        return (float(price), "kg")
    return (float(price), "ea")


def _site_price_for(deal: dict,
                    site_catalogues: dict) -> tuple[float, str] | None:
    """(site price, basis) for a Dunya deal from the site catalogue.

    Token-set best match >= MATCH_MIN_RATIO; basis mirrors the deal
    unit. None when no catalogue / no match.
    """
    items = (site_catalogues or {}).get(deal.get("store_key")) or []
    if not items:
        return None
    best_ratio, best = 0.0, None
    for item in items:
        ratio = token_set_ratio(deal.get("item") or "",
                                item.get("name") or "")
        if ratio > best_ratio:
            best_ratio, best = ratio, item
    if best is None or best_ratio < MATCH_MIN_RATIO:
        return None
    price = best.get("regular_price") or best.get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        return None
    basis = "kg" if (deal.get("unit") or "").lower() == "kg" else "ea"
    return (float(price), basis)


def match_and_detect(rows, master_rows, site_catalogues) -> list[MatchResult]:
    """Domain-gated matching + >20% detection (§8).

    Out-of-domain items return in_domain=False, never matched, never
    alerted, never annotated. Bulk/multibuy NEVER enter the maths —
    they render as notes only. Extra-stop aggregation is derived by
    render_post1 from baseline/flyer fields (strictly greater $3.00,
    unit prices only).

    Args:
        rows: flat deal dicts enriched with store_key/store_name.
        master_rows: _load_master_rows() output.
        site_catalogues: {store_key: [normalised catalogue items]}.

    Returns:
        MatchResult list in input (board) order.
    """
    from extractors.fb_flyer_fetch import STORES
    store_names = {s["key"]: s["name"] for s in STORES}
    results: list[MatchResult] = []
    for deal in rows:
        store_key = deal.get("store_key") or ""
        kind = str(deal.get("price_kind") or "single")
        result = MatchResult(
            store_key=store_key,
            store_name=deal.get("store_name")
            or store_names.get(store_key, store_key),
            item_name=str(deal.get("item") or ""),
            in_domain=False,
            deal_kind=kind,
        )
        if kind == "bulk_pack":
            size = deal.get("bulk_size") or ""
            from core.uom import FAMILY_WEIGHT, parse_size
            parsed = parse_size(size)
            per_unit = ""
            if parsed is not None and parsed.family == FAMILY_WEIGHT \
                    and parsed.value > 0 and deal.get("price"):
                per_kg = float(deal["price"]) / (parsed.value / 1000.0)
                per_unit = f" — {_money(per_kg)}/kg"
            result.multibuy_note = (
                f"multi buy {size} for "
                f"{_money(float(deal.get('price') or 0))}{per_unit}")
            if isinstance(deal.get("price"), (int, float)) \
                    and not isinstance(deal.get("price"), bool):
                result.flyer_price = float(deal["price"])
            result.item_name = f"{result.item_name} {size}".strip()
            results.append(result)
            continue
        if kind == "multibuy":
            from core.multibuy import effective_unit_rate
            qty = int(deal.get("multibuy_qty") or 0)
            total = float(deal.get("price") or 0)
            if qty >= 2 and total > 0:
                rate = effective_unit_rate(qty, total)
                result.multibuy_note = (
                    f"multi buy {qty} for {_money(total)} "
                    f"— {_money(rate)}/ea")
            if isinstance(deal.get("price"), (int, float)) \
                    and not isinstance(deal.get("price"), bool):
                result.flyer_price = float(deal["price"])
            results.append(result)
            continue

        store_kind = _store_kind(store_key)
        deal_side = (store_kind in ("butchery", "fruits")
                     and deal.get("category") == store_kind)
        # All single deals carry their printed price (out-of-domain
        # lines render it plainly in Post 2, 04:56 full-board rule).
        if isinstance(deal.get("price"), (int, float)) \
                and not isinstance(deal.get("price"), bool):
            result.flyer_price = float(deal["price"])
        if not deal_side:
            results.append(result)   # out-of-domain: plain, unannotated
            continue
        result.in_domain = True

        # Validity gate (user rule 2026-09-07): a post whose prices
        # have EXPIRED is recorded but never compared or alerted —
        # expired pricing must not look live.
        valid_until = deal.get("valid_until")
        if valid_until is not None:
            if isinstance(valid_until, str):
                try:
                    valid_until = date.fromisoformat(valid_until)
                except ValueError:
                    valid_until = None
            if valid_until is not None \
                    and valid_until < sydney_today():
                result.note = (f"prices expired "
                               f"{valid_until:%a %d %b} — not "
                               f"compared")
                results.append(result)
                continue

        best_ratio, best_master = 0.0, None
        deal_tokens = _item_tokens(deal.get("item") or "")
        candidates: list[tuple[float, dict]] = []
        for master in master_rows:
            if not is_in_domain(store_kind,
                                deal.get("category") or "",
                                master["subcategory"],
                                master["category"]):
                continue
            ratio = token_set_ratio(deal.get("item") or "",
                                    master["name"])
            containment = bool(deal_tokens) and deal_tokens.issubset(
                _item_tokens(master["name"]))
            if ratio >= MATCH_MIN_RATIO or containment:
                candidates.append((ratio, master))

        # Bag-aware selection (user rule 2026-09-07): a deal weighed
        # as a bag ("Onions 5kg Bag") compares PER KILO against the
        # LARGEST matching weight-size master bag — never against a
        # loose each-price (no weight size on the master side).
        from core.uom import FAMILY_WEIGHT, parse_size
        deal_weight_g = _deal_weight_g(
            deal.get("item") or "",
            str(deal.get("bulk_size") or ""))
        bag_override = False
        if deal_weight_g is not None:
            weighted = []
            for ratio, master in candidates:
                parsed = parse_size(master.get("size") or "")
                if parsed is not None \
                        and parsed.family == FAMILY_WEIGHT \
                        and parsed.value > 0:
                    weighted.append((parsed.value, ratio, master))
            if not weighted:
                result.note = ("no comparable bag size at "
                               "Woolworths/Coles")
                results.append(result)
                continue
            weighted.sort(key=lambda t: (-t[0], -t[1]))
            best_master = weighted[0][2]
            bag_override = True
        elif candidates:
            best_ratio, best_master = max(
                candidates, key=lambda t: t[0])

        site = _site_price_for(deal, site_catalogues)
        if site is not None and result.flyer_price:
            site_price, site_basis = site
            denom = max(result.flyer_price, site_price)
            save_pct = round(
                (site_price - result.flyer_price) / denom * 100.0)
            result.site_price_note = (
                f"normal site price {_money(site_price)}/{site_basis}"
                f" — save {save_pct}%")
        elif store_kind == "butchery" and \
                str(deal.get("store_key")) == "dunya":
            result.site_price_note = "normal price unavailable"

        if best_master is None:
            # Distinguish no-match vs unit-family mismatch reporting
            result.note = "no sheet match"
            results.append(result)
            continue
        result.matched_master = best_master["name"]
        if _variety_conflict(deal.get("item") or "",
                             best_master["name"]):
            result.variety_conflict = True
            result.note = "variety differs — verify"
        # Bag path: both sides normalize to $/kg, so the unit-family
        # gate is satisfied by construction (deal bag vs master bag).
        if not bag_override and not _unit_prices_agree(
                deal, best_master):
            result.note = result.note or "unit mismatch"
            results.append(result)
            continue

        master_unit = _master_unit_price(best_master)
        deal_unit = _deal_unit_price(deal)
        if bag_override:
            price_num = deal.get("price")
            deal_unit = (float(price_num)
                         / (deal_weight_g / 1000.0), "kg") \
                if isinstance(price_num, (int, float)) \
                and not isinstance(price_num, bool) else None
        if master_unit is None or deal_unit is None:
            results.append(result)
            continue
        baseline_unit_price, master_basis, baseline_store = master_unit
        flyer_unit_price, flyer_basis = deal_unit
        # Baseline display value: the raw WW D cell (Q20 — the Coles
        # arm is retired with the v2 sheet).
        result.baseline_store = baseline_store
        result.baseline_price = best_master.get("wool_price")
        # Bases must agree: a $/kg flyer needs a $/kg master baseline
        # (the kg->ea pairing was already blocked by
        # _unit_prices_agree above; this is defensive only).
        if flyer_basis == "kg" and \
                not _master_unit_price_is_kg(best_master):
            results.append(result)
            continue
        pct = ((baseline_unit_price - flyer_unit_price)
               / baseline_unit_price * 100.0)
        result.pct = pct
        result._basis = flyer_basis
        if pct > ALERT_PCT and not result.variety_conflict:
            result.alert = True
        results.append(result)
    return results


def _master_unit_price_is_kg(master_row: dict) -> bool:
    """True when the master baseline is on the $/kg basis."""
    from core.uom import FAMILY_WEIGHT, parse_size
    parsed = parse_size(master_row.get("size") or "")
    return parsed is not None and parsed.family == FAMILY_WEIGHT


def _unit_label(result: MatchResult) -> str:
    """'/kg' | '/ea' comparison label for a matched result."""
    return "/kg" if getattr(result, "_basis", "ea") == "kg" else "/ea"


def render_post1(results: list[MatchResult], friday_date: str) -> str:
    """Standouts only (§9). Exact formats of the sample block; the
    'Extra stop worth it: $X.XX total saving on N items' line appears
    once per qualifying store (savings strictly > $3.00, unit prices
    only). Empty -> 'No local standouts this week'.

    Args:
        results: match_and_detect() output.
        friday_date: YYYY-MM-DD label for the header.

    Returns:
        The Post 1 message text (never empty).
    """
    standouts = [r for r in results if r.alert]
    suppressed = [r for r in results if r.in_domain and r.variety_conflict
                  and r.pct is not None and r.pct > ALERT_PCT
                  and not r.alert]
    if not standouts and not suppressed:
        return "No local standouts this week"

    lines: list[str] = [
        f"🚨 LOCAL STANDOUTS — {friday_date} (Mt Druitt)"]
    show = standouts + suppressed
    seen_stores: list[str] = []
    for r in show:
        if r.store_name.upper() not in seen_stores:
            seen_stores.append(r.store_name.upper())
    for store in seen_stores:
        lines.append("")
        lines.append(store)
        for r in show:
            if r.store_name.upper() != store:
                continue
            if not r.alert:
                # variety-suppressed standout: tag replaces the alert
                lines.append(
                    f" • {r.item_name} — {_money(r.flyer_price or 0)}"
                    f"{_unit_label(r)}  (variety differs — verify)")
                continue
            base = _money(r.baseline_price or 0)
            lines.append(
                f" • {r.item_name} — {_money(r.flyer_price or 0)}"
                f"{_unit_label(r)}  ({r.pct:.0f}% < "
                f"{r.baseline_store} {base}{_unit_label(r)})")
    # Extra-stop aggregation per store: strictly > $3.00, alerts only.
    for store in seen_stores:
        store_results = [r for r in standouts
                         if r.store_name.upper() == store]
        savings = sum(
            (r.baseline_price or 0) - (r.flyer_price or 0)
            for r in store_results)
        if savings > DEFAULT_SPLIT_THRESHOLD and store_results:
            lines.append("")
            lines.append(
                f"Extra stop worth it: {_money(savings)} total "
                f"saving on {len(store_results)} items")
    return "\n".join(lines)


def _split_oversized(block: str, store_header: str) -> list[str]:
    """Line-boundary split at MSG_CHAR_LIMIT with '(continued)' and
    the store header repeated on every chunk (§9 hard rule 2).

    Args:
        block: the full store block text.
        store_header: header line repeated on every chunk.

    Returns:
        List of message-sized chunks (>= 1).
    """
    if len(block) <= MSG_CHAR_LIMIT:
        return [block]
    body_lines = block.splitlines()
    body = [ln for ln in body_lines
            if ln.strip() and ln.strip() != store_header.strip()]
    chunks: list[str] = []
    current: list[str] = []
    size = len(store_header) + 2
    for line in body:
        if size + len(line) + 1 > MSG_CHAR_LIMIT - 16:
            chunks.append(store_header + "\n" + "\n".join(current)
                          + "\n(continued)")
            current, size = [], len(store_header) + 2
        current.append(line)
        size += len(line) + 1
    tail = store_header + "\n" + "\n".join(current)
    if current and chunks and len(chunks[-1]) + len(tail) > 0:
        chunks.append(tail)
    elif current:
        chunks.append(tail)
    return chunks or [block]


def render_post2_blocks(results, friday_date) -> list[str]:
    """Intro block (title + ⚠️ no-prices lines) then ONE block per
    store, natural board order, no sorting, EVERYTHING (04:56):
    out-of-domain items as plain unannotated lines. Shopping-list
    rule note appended when any multi-buy exists (B12).

    Args:
        results: match_and_detect() output (board order preserved).
        friday_date: YYYY-MM-DD label for the intro title.

    Returns:
        List of message texts: [intro, store block, ...] (each store
        block pre-split when oversized).
    """
    from extractors.fb_flyer_fetch import STORES
    active_stores = []
    for s in STORES:
        if any(r.store_key == s["key"] for r in results):
            active_stores.append(s)
    missing = [s for s in STORES if s not in active_stores]

    intro = [f"🛒 LOCAL BOARDS — {friday_date} (Mt Druitt)"]
    intro += [f"⚠️ No prices found this week: {s['name']} "
              f"(no new board)" for s in missing]
    if any(r.multibuy_note for r in results):
        intro.append("Shopping-list note: multi-buy items need the "
                     "minimum purchase quantity at checkout.")

    blocks = ["\n".join(intro)]
    for s in STORES:
        store_results = [r for r in results if r.store_key == s["key"]]
        if not store_results:
            continue
        header = s["name"].upper()
        lines = [header]
        any_multibuy = False
        for n, r in enumerate(store_results, 1):
            price = (_money(r.flyer_price)
                     if r.flyer_price is not None else "?")
            if r.deal_kind == "bulk_pack":
                any_multibuy = True
                bracket = r.multibuy_note
                if r.site_price_note:
                    bracket += f" — {r.site_price_note}"
                lines.append(f" {n}. {r.item_name} — {price}")
                lines.append(f"    [{bracket}]")
            elif r.multibuy_note:
                any_multibuy = True
                lines.append(f" {n}. {r.item_name} — {price}"
                             f"  ({r.multibuy_note})")
            else:
                line = f" {n}. {r.item_name} — {price}"
                if r.pct is not None and r.pct > ALERT_PCT \
                        and r.baseline_store:
                    line += (f"  (also {r.pct:.0f}% < "
                             f"{r.baseline_store})")
                if r.site_price_note:
                    line += f"  ({r.site_price_note})"
                lines.append(line)
        block = "\n".join(lines)
        if any_multibuy:
            block += ("\nMulti-buy lines show the bundle total; "
                      "the per-unit rate is in brackets.")
        blocks.extend(_split_oversized(block, header))
    return blocks


def _env_int(name: str) -> int | None:
    """int value of an env var, or None when unset/non-numeric."""
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


# --- the ONE digest per window (user directive 2026-09-11) ---------------
# Sections look like:
#   {"shop_label": "Merjan", "shop": "Merjan Brothers Quality Meats",
#    "posts": [{"code", "file", "valid_txt", "items": [
#        {"name", "price_text", "terms", "till", "was", "per_kg"}],
#      "notice_only": bool, "unreadable": bool}]}
# Questions are local_deals_questions.json entries (S5/P4).

SHORT_SHOP_NAMES = {"dunya": "Dunya", "dunya_fb": "Dunya",
                    "merjan": "Merjan", "fruitopia": "Fruitopia",
                    "abusalim": "Abu Salim"}


def _digest_shop_summary(shop_label: str, posts: list[dict]) -> str:
    """One summary bit for the digest header line, spec wording:
    'Merjan: 3 new items (2 with min-order deals, best $11.00/kg)'
    / 'Fruitopia: notice only, no prices' / unreadable flags."""
    items = [i for p in posts for i in (p.get("items") or [])]
    unreadable = sum(1 for p in posts if p.get("unreadable"))
    expired = [p for p in posts if p.get("expired")]
    if not items:
        if expired and len(expired) == len(posts):
            return f"{shop_label}: board already ended — nothing written"
        if unreadable and unreadable == len(posts):
            return (f"{shop_label}: {unreadable} image(s) unreadable")
        return f"{shop_label}: notice only, no prices"
    bit = f"{shop_label}: {len(items)} new item" \
        f"{'s' if len(items) != 1 else ''}"
    with_terms = [i for i in items if i.get("terms")]
    extras = []
    if with_terms:
        extras.append(f"{len(with_terms)} with min-order deals")
    per_kg = [i["per_kg"] for i in items if i.get("per_kg")]
    if per_kg:
        extras.append(f"best {_money(min(per_kg))}/kg")
    if extras:
        bit += f" ({', '.join(extras)})"
    if unreadable:
        bit += f" · {unreadable} image(s) unreadable"
    return bit


def _render_window_digest(sections: list[dict], questions: list[dict],
                          label: str,
                          standout_lines: list[str] | None = None
                          ) -> list[str]:
    """The ONE combined digest per window (AI-M5). Header summary line
    per spec example, one detail block per shop in post order, the
    standout comparison block, then every open QUESTION. Message
    chunks stay <= MSG_CHAR_LIMIT (split at block boundaries).

    The words 'save the image' and 'done' NEVER appear — the digest
    IS the action; questions are the only thing to answer.
    """
    summary_bits = [_digest_shop_summary(s.get("shop_label", "shop"),
                                         s.get("posts") or [])
                    for s in sections]
    if questions:
        first = questions[0].get("text") or ""
        n = len(questions)
        summary_bits.append(
            f"{n} question{'s' if n != 1 else ''} need"
            f"{'' if n != 1 else 's'} you: {first}")
    blocks: list[str] = []
    header = f"🔍 {label}"
    if summary_bits:
        header += " — " + " · ".join(summary_bits)
    blocks.append(header)

    for sec in sections:
        lines = [f"🔪 {sec.get('shop') or sec.get('shop_label')}"]
        for p in sec.get("posts") or []:
            code = p.get("code") or ""
            if p.get("unreadable"):
                lines.append(f"📷 {code} {p.get('file') or ''} — image "
                             f"unreadable — forward a clearer version "
                             f"or reply with the items as text")
                continue
            if p.get("notice_only"):
                lines.append(f"📋 {code} {p.get('file') or ''} — notice "
                             f"only, no prices")
                continue
            if p.get("expired"):
                lines.append(f"🗑 {code} {p.get('file') or ''} — "
                             f"{p.get('valid_txt') or 'deals ended'}")
                continue
            valid = p.get("valid_txt") or ""
            post_head = f"📄 {code} {p.get('file') or ''}".rstrip()
            if valid:
                post_head += f" · {valid}"
            lines.append(post_head)
            for i in p.get("items") or []:
                line = f"• {i['name']} — {i.get('price_text') or '?'}"
                if i.get("terms"):
                    line += f" (min order {i['terms']})"
                if i.get("till"):
                    line += f" · till {i['till']}"
                if i.get("was") is not None:
                    line += f" — was {_money(i['was'])}"
                lines.append(line)
        blocks.append("\n".join(lines))

    if standout_lines:
        text = "\n".join(standout_lines).strip()
        if text and text != "No local standouts this week":
            blocks.append(text)

    if questions:
        qlines = [f"❓ {len(questions)} question"
                  f"{'s' if len(questions) != 1 else ''} need"
                  f"{'s' if len(questions) == 1 else ''} you:"]
        for q in questions:
            qlines.append(f"• {q.get('text') or ''}")
        blocks.append("\n".join(qlines))

    messages: list[str] = []
    current = ""
    for block in blocks:
        if current and len(current) + 2 + len(block) > MSG_CHAR_LIMIT:
            messages.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}" if current else block
    if current:
        messages.append(current)
    return messages


def _post_digest(messages: list[str]) -> None:
    """Send digest chunks to the local-deals topic (P2)."""
    bot_token = os.getenv("TELEGRAM_CLAW_BOT", "")
    topic_id = _env_int(LOCAL_DEALS_TOPIC_ENV)
    for text in messages:
        receipt = _send_message(bot_token, TELEGRAM_CHAT_ID,
                                text[:MSG_CHAR_LIMIT],
                                thread_id=topic_id or TELEGRAM_CHAT_ID)
        if not receipt.get("ok"):
            print("[digest] telegram delivery failed")


def _env_upsert(key: str, value: str, env_path: Path) -> None:
    """Atomically replace-or-append ONE KEY=VALUE line in .env.

    Non-secret values only. File contents are NEVER printed.
    """
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    replaced = False
    out: list[str] = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}={value}")
    tmp = env_path.with_suffix(".env.tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.replace(tmp, env_path)


def _send_message(bot_token: str, chat_id, text: str,
                  thread_id=None) -> dict:
    """One Telegram sendMessage. Returns the PARSED API response
    ({"ok": bool, "message_id": int|None, "chat_id", "thread_id"})
    — unlike the CLI's bool sender, the receipt gate needs the
    message_id. Never raises; failures print a secret-free line.
    """
    import urllib.error
    import urllib.request

    result = {"ok": False, "message_id": None,
              "chat_id": chat_id, "thread_id": thread_id}
    if not bot_token:
        print("[telegram] no bot token configured — not sent")
        return result
    body: dict = {"chat_id": chat_id, "text": text}
    if thread_id is not None:
        body["message_thread_id"] = thread_id
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        result["ok"] = bool(data.get("ok"))
        msg = data.get("result") or {}
        result["message_id"] = msg.get("message_id")
        chat = msg.get("chat") or {}
        result["chat_id"] = chat.get("id", chat_id)
        return result
    except Exception as exc:  # noqa: BLE001 — delivery is best-effort
        print(f"[telegram] send failed: {exc.__class__.__name__}")
        return result


def deliver_reports(bot_token: str, post1: str,
                    post2_blocks: list[str], topic_id) -> None:
    """Length-check EVERY message <= 4000 BEFORE send (never rely on
    truncation); topic post when topic_id is set, otherwise DM +
    console note. Best-effort; never raises. Prints one secret-free
    receipt line per message:
    '[telegram] ok message_id=<id> chat=<id> thread=<id|dm>' — the
    S32 receipt gate greps these. Writes the first-fire receipt file
    when at least one message was accepted. When EVERY topic send
    fails, a secret-free failure summary still lands in the DM (the
    build never goes silent).
    """
    messages = [post1] + [b for b in (post2_blocks or []) if b]
    route = "topic" if topic_id else "dm"
    receipts: list[dict] = []
    for text in messages:
        if len(text) > MSG_CHAR_LIMIT:
            print(f"[telegram] message exceeds {MSG_CHAR_LIMIT} "
                  f"chars — NOT sent (never truncate)")
            continue
        if route == "topic":
            receipt = _send_message(bot_token, TELEGRAM_CHAT_ID, text,
                                    thread_id=topic_id)
        else:
            receipt = _send_message(bot_token, TELEGRAM_USER_ID, text)
        receipt["chars"] = len(text)
        receipts.append(receipt)
        if receipt["ok"]:
            thread = receipt["thread_id"] if route == "topic" else "dm"
            print(f"[telegram] ok message_id={receipt['message_id']} "
                  f"chat={receipt['chat_id']} thread={thread}")
    if route == "topic" and receipts and \
            not any(r["ok"] for r in receipts):
        print("[telegram] all topic sends failed — paging via DM")
        _send_message(
            bot_token, TELEGRAM_USER_ID,
            f"[local-deals] delivery failed: 0/{len(receipts)} "
            f"messages reached the topic — check the run log.")
    _write_first_fire_receipt(receipts, route)


FIRST_FIRE_PATH = (Path(__file__).resolve().parent.parent / "data"
                   / "local_deals_first_fire.json")


def _write_first_fire_receipt(receipts: list[dict], route: str) -> None:
    """Audit file for the S32 gate: {"fired_at": ISO, "route",
    "messages": [{"message_id", "thread_id", "chars"}]} — written
    only when at least one message got ok=True."""
    oks = [r for r in receipts or [] if r.get("ok")]
    if not oks:
        return
    payload = {
        "fired_at": sydney_now().isoformat(
            timespec="seconds"),
        "route": route,
        "messages": [{"message_id": r.get("message_id"),
                      "thread_id": r.get("thread_id"),
                      "chars": r.get("chars", 0)} for r in oks],
    }
    FIRST_FIRE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIRST_FIRE_PATH.write_text(json.dumps(payload, indent=2),
                               encoding="utf-8")


def provision_local_deals_topic(bot_token: str = "") -> dict:
    """AUTONOMOUS topic provisioning (§9 S31; user revision
    2026-09-05 07:38 — supersedes manual M1).

    Chain (fully automatic, no user action, no deferral):
    1. TELEGRAM_LOCAL_DEALS_TOPIC_ID already set -> verify with one
       test send to that thread; done.
    2. Bot API createForumTopic(chat_id=TELEGRAM_CHAT_ID,
       name='local-deals') -> message_thread_id.
    3. Atomic .env upsert of TELEGRAM_LOCAL_DEALS_TOPIC_ID=<id>
       (non-secret id; contents NEVER printed).
    4. Test send to the new thread; receipt logged.
    5. Rights-blocked creation (HTTP 400 'not enough rights') is NOT
       a stop: route falls back to DM (TELEGRAM_USER_ID), and topic
       creation retries on every later provisioning call.

    Returns {"route": "topic"|"dm", "thread_id": int|None,
    "created": bool, "receipt": <api response>}.
    """
    import urllib.error
    import urllib.request

    bot_token = bot_token or os.getenv("TELEGRAM_CLAW_BOT", "")
    result: dict = {"route": "dm", "thread_id": None,
                    "created": False, "receipt": {}}
    existing = _env_int(LOCAL_DEALS_TOPIC_ENV)
    if existing:
        test = _send_message(bot_token, TELEGRAM_CHAT_ID,
                             "[local-deals] topic check",
                             thread_id=existing)
        result.update(route="topic", thread_id=existing,
                      receipt=test)
        print(f"[local-deals] telegram route: topic "
              f"(thread_id={existing}, created=False)")
        return result
    if not bot_token:
        print("[local-deals] no TELEGRAM_CLAW_BOT token — DM route; "
              "topic creation will retry on the next run")
        return result
    try:
        body = json.dumps({"chat_id": TELEGRAM_CHAT_ID,
                           "name": "local-deals"}).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{bot_token}"
            f"/createForumTopic",
            data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001 — body read is best-effort
            pass
        print(f"[local-deals] topic creation blocked "
              f"(HTTP {exc.code}) — DM fallback; retries next run")
        if detail:
            print(f"[local-deals] api note: "
                  f"{detail.split('description')[-1][:120]}")
        return result
    except Exception as exc:  # noqa: BLE001 — network/transport
        print(f"[local-deals] topic creation failed "
              f"({exc.__class__.__name__}) — DM fallback; retries "
              f"next run")
        return result
    if not data.get("ok"):
        print("[local-deals] topic creation refused by api — "
              "DM fallback; retries next run")
        return result
    thread_id = (data.get("result") or {}).get("message_thread_id")
    if not thread_id:
        print("[local-deals] api returned no thread id — DM fallback")
        return result
    from core.sheets_client import _find_root_env
    _env_upsert(LOCAL_DEALS_TOPIC_ENV, str(thread_id),
                _find_root_env())
    test = _send_message(bot_token, TELEGRAM_CHAT_ID,
                         "[local-deals] local butchery + fruit shop "
                         "deals will post in this topic.",
                         thread_id=thread_id)
    result.update(route="topic", thread_id=thread_id, created=True,
                  receipt=test)
    print(f"[local-deals] telegram route: topic "
          f"(thread_id={thread_id}, created=True)")
    return result


def _process_store_timeline(store: dict, run_dir: Path, today_syd
                            ) -> list[dict]:
    """Timeline pipeline: last-3 posts, text-first, future-only.

    The user's standing rule (TODO Task 2): each store's LAST 3
    posts are in scope; only posts whose validity date is in the
    FUTURE (Sydney) are reported. A post with no date lands in the
    needs-date-review bucket — printed for the user, never silently
    included (§2). Undated image-only posts may still be rescued by
    a vision-parsed valid_until.

    Args:
        store: STORES entry (pipeline == "timeline").
        run_dir: per-run flyer directory.
        today_syd: Sydney date.

    Returns:
        Deal dicts enriched with store_key/store_name/post_ref.

    Raises:
        FetchUnavailable: render failed or zero in-scope deals.
    """
    from extractors.fb_flyer_fetch import FetchUnavailable
    from extractors.deal_text import filter_recent_posts
    from extractors.fb_timeline_fetch import fetch_timeline_posts

    posts = fetch_timeline_posts(store, max_posts=3)
    kept, expired, needs_review = filter_recent_posts(
        posts, today=today_syd)
    for post, end in expired:
        print(f"[local-deals] {store['key']}: post {post.post_ref} "
              f"expired {end} (Sydney) — dropped")
    for post in needs_review:
        print(f"[local-deals] {store['key']}: post {post.post_ref} "
              f"has NO date in text — needs date review, excluded")
    deals: list[dict] = []
    for post, end in kept:
        post_deals, source, vision_until = extract_post_deals(
            post, run_dir, store["key"])
        if source == "vision" and vision_until is not None \
                and vision_until < today_syd:
            print(f"[local-deals] {store['key']}: post "
                  f"{post.post_ref} board expired {vision_until} "
                  f"(vision date) — dropped")
            continue
        # The post's validity rides on every deal so the tab's
        # special cells stamp per post (user rule 2026-09-07);
        # a vision-parsed date (image-only board) refines the text.
        deal_until = (vision_until if source == "vision"
                      and vision_until else end)
        for deal in post_deals:
            deals.append({**deal,
                          "store_key": store["key"],
                          "store_name": store["name"],
                          "post_ref": post.post_ref,
                          "source": source,
                          "valid_until": deal_until})
    if not deals:
        raise FetchUnavailable(
            "no in-scope deals from timeline (last 3 posts)")
    return deals


def _process_store(store: dict, run_dir: Path, today_syd) -> list[dict]:
    """One store: fetch -> per-post extraction -> freshness filter.

    Two pipelines (TODO Tasks 2-4a):
      - "timeline" (fruitopia): last-3 timeline posts, text-first
        per-post extraction (vision only for image-only posts),
        Sydney validity filter; undated posts are printed as
        needs-review and EXCLUDED (never silently included).
      - "photos" (others until their rebuild): the legacy photos-tab
        + vision path, unchanged.

    Raises (FetchUnavailable / VisionUnavailable) on total failure —
    the caller records the store as failed (⚠️ line, exit code).
    Zero parsed deals also raises (no new board = failure by design).

    Args:
        store: STORES entry.
        run_dir: per-run flyer directory (wiped per store inside).
        today_syd: Sydney date for the valid_until freshness drop.

    Returns:
        Deal dicts enriched with store_key/store_name/post_ref.
    """
    if store.get("pipeline") == "timeline":
        deals = _process_store_timeline(store, run_dir, today_syd)
        return _prefix_butcher_deals(store["key"], deals)

    from extractors.fb_flyer_fetch import fetch_store_posts
    from core.flyer_vision import parse_board_images

    posts = fetch_store_posts(store, run_dir)
    deals: list[dict] = []
    for post in posts:
        payload = parse_board_images(post.files)
        valid_until = payload.get("valid_until")
        try:
            board_until = (date.fromisoformat(str(valid_until))
                           if valid_until else None)
        except ValueError:
            board_until = None
        if board_until and board_until < today_syd:
            continue   # expired board — freshness drop (§5)
        for deal in payload.get("deals") or []:
            deals.append({**deal,
                          "store_key": store["key"],
                          "store_name": store["name"],
                          "post_ref": post.post_ref,
                          "valid_until": board_until})
    if not deals:
        from extractors.fb_flyer_fetch import FetchUnavailable
        raise FetchUnavailable("no deals parsed from any post")
    return _prefix_butcher_deals(store["key"], deals)


def extract_post_deals(post, run_dir, store_key: str
                       ) -> tuple[list[dict], str, "date | None"]:
    """Text-first per-post extraction (TODO Task 3).

    Branch rule (the Fruitopia lesson): parse the post TEXT first;
    ONLY a post with no price text falls back to vision — and then on
    the post's OWN timeline-attributed images, never the photos tab.
    Vision's parsed valid_until (often absent) rides along so the
    caller can freshness-check an image-only post.

    Args:
        post: TimelinePost (text + image_urls).
        run_dir: per-run flyer directory for downloaded images.
        store_key: store key (filename prefix).

    Returns:
        tuple: (deals, source, valid_until) with source
        "text" | "vision" | "none"; valid_until is a parsed date or
        None (None means "no date known" — caller asks the user).
    """
    from extractors.deal_text import parse_fruitopia_deals

    deals = parse_fruitopia_deals(post.text)
    if deals:
        return deals, "text", None
    if not post.image_urls:
        return [], "none", None
    from core.flyer_vision import parse_board_images
    from extractors.fb_timeline_fetch import download_post_images
    files = download_post_images(post, run_dir, store_key)
    if not files:
        return [], "none", None
    payload = parse_board_images(files)
    raw_until = payload.get("valid_until")
    try:
        valid_until = (date.fromisoformat(str(raw_until))
                       if raw_until else None)
    except ValueError:
        valid_until = None
    return payload.get("deals") or [], "vision", valid_until


def _to_vision_deal(d: dict, category: str) -> dict:
    """Text-parser deal -> the vision schema build_rows expects.

    Args:
        d: parse_fruitopia_deals() output (item/price/unit/
            multibuy/multibuy_note/raw).
        category: "fruits" | "butchery" | "other" (store kind).

    Returns:
        dict: flyer_vision-schema deal (item, raw_text, price, unit,
        price_kind, multibuy_qty, bulk_size, category, notes).
    """
    qty = d.get("multibuy")
    return {
        "item": d["item"],
        "raw_text": d.get("raw") or d["item"],
        "price": d["price"],
        "unit": d["unit"],
        "price_kind": "multibuy" if qty else "single",
        "multibuy_qty": qty,
        "bulk_size": None,
        "category": category,
        "notes": d.get("multibuy_note") or "",
    }


def _canonical_match_index(grid: list, name: str) -> int | None:
    """Grid-wide FIX-8 match: the first ITEM row whose canonical base
    name equals `name`'s, else None. Structural rows (header,
    validity stamp, section titles) never match. Grid-wide since
    Round 3: new rows bottom-append OUTSIDE their section block
    (Q27), so a section-scoped scan would never re-find them."""

    def _item_row(i: int) -> bool:
        first = str(grid[i][0]).strip()
        if not first or first in SECTION_ORDER:
            return False
        return first != "Prices valid until"

    target = canonical_key(_base_name(name))
    for i in range(1, len(grid)):
        if _item_row(i) and \
                canonical_key(_base_name(grid[i][0])) == target:
            return i
    return None


# ID-2 reuse guard (user directive 2026-09-11): bare unit words carry
# no product identity; size tokens ('5kg') DO — they separate pack
# presentations (S9: a 5kg pack and a /kg row are different lines).
_REUSE_UNIT_WORDS = {"kg", "g", "mg", "ml", "l", "ea", "each", "pack"}


def _reuse_tokens(text: str) -> set:
    """ID-2 matcher tokens: PLURAL-FOLDED, order-free word tokens,
    ignoring unit markers and the source-based 'halal' prefix; size
    tokens ('5kg') are KEPT (pack presentations stay apart, S9)."""
    tokens: set[str] = set()
    for t in similarity_tokens(str(text or "")):
        low = t.lower()
        if re.fullmatch(r"\d+(?:[.,]\d+)?", low):
            continue
        if low in _REUSE_UNIT_WORDS or low in STOPWORDS \
                or low == "halal":
            continue
        tokens.add(_singular(low))
    return tokens


def _reuse_match_index(grid: list, name: str) -> int | None:
    """ID-2 v2-native reuse guard: the row an incoming name REUSES
    instead of auto-creating a near-duplicate.

    Layer 1 — canonical-key equality (the pre-v2 rule, kept: exact
    equivalents always reuse). Layer 2 — token CONTAINMENT either
    direction over _reuse_tokens (plural-folded, unit markers +
    'halal' ignored), allowed only when the SMALLER side carries
    >= 2 tokens (a lone token never reuses); tie-break: most token
    overlap, then the earliest row. Pack presentations stay separate
    (S9): when either side carries size tokens ('5kg'), BOTH must
    carry the SAME size. The proven pair 'Halal Sliced Lamb Neck
    /kg' vs 'Halal Lamb Necks /kg' reuses via layer 2 ({lamb, neck}
    contained, no sizes); 'Goat Curry 5kg' never reuses
    'Goat Curry /kg'; 'Beef Curry' vs 'Lamb Curry' shares no
    containment and stays apart.
    """
    size_re = re.compile(r"\d+(?:[.,]\d+)?\s*(?:kg|g|mg|ml|l)\Z",
                         re.IGNORECASE)

    def _split(tokens: set) -> tuple[set, set]:
        sizes = {t for t in tokens if size_re.fullmatch(t)}
        return tokens - sizes, sizes

    def _item_row(i: int) -> bool:
        first = str(grid[i][0]).strip()
        if not first or first in SECTION_ORDER:
            return False
        return first != "Prices valid until"

    incoming = _reuse_tokens(_base_name(name))
    SIZE_RE = re.compile(r"\d+(?:[.,]\d+)?kg\b")
    incoming_id = {t for t in incoming if not SIZE_RE.fullmatch(t)}
    best_pack: tuple[int, int] | None = None   # (-overlap, row)
    best_id: tuple[int, int] | None = None
    for i in range(1, len(grid)):
        if not _item_row(i):
            continue
        row_name = _base_name(grid[i][0])
        if canonical_key(row_name) == canonical_key(_base_name(name)):
            return i                          # layer 1: exact reuse
        row_tokens = _reuse_tokens(row_name)
        if not incoming or not row_tokens:
            continue
        smaller, larger = sorted((incoming, row_tokens),
                                 key=len)
        pack_hit = len(smaller) >= 2 and smaller.issubset(larger)
        row_id = {t for t in row_tokens if not SIZE_RE.fullmatch(t)}
        smaller_id, larger_id = sorted((incoming_id, row_id),
                                       key=len)
        id_hit = (len(incoming_id) >= 2 and len(smaller_id) >= 2
                  and smaller_id.issubset(larger_id))
        if pack_hit:
            overlap = len(smaller)
            cand = (-overlap, i)
            if best_pack is None or cand < best_pack:
                best_pack = cand
        if id_hit:
            overlap = len(incoming_id & row_id)
            cand = (-overlap, i)
            if best_id is None or cand < best_id:
                best_id = cand
    if best_pack is not None:
        return best_pack[1]               # pack-aware reuse wins
    if best_id is not None:
        return best_id[1]                 # identity-only reuse
    return None


def merge_store_tab(worksheet, store_key: str, deals: list[dict],
                    valid_until=None,
                    master_ws=None) -> tuple[int, list[str]]:
    """Merge ONE store's deals into the existing Local_Deals tab.

    The ingest flow must NOT touch the other stores' cells: the
    current grid is read, matching Product rows (same section, same
    Col A text) get this store's column cell updated, and the FULL
    grid is written back in ONE batch update (layout: header, "Prices
    valid until" row, then per section a title row + item rows).

    v2 (Round 3, Q27 + §18/A2): NEW rows APPEND AT GRID END — a
    mid-tab insert would read as a parity middle_insert hard alert.
    When `master_ws` is given, the SAME operation appends the blank
    13-col master counterpart row (name + Item_Code from
    item_code_registry.json + Sub_Category by domain; price D and
    keyword G stay BLANK per §4.2) and writes the code into the LD
    row's col K — bottom-append parity on BOTH tabs in one
    operation. `master_ws=None` (tests/legacy) skips the master
    mirror; the report still names the rows that WOULD mirror.

    Args:
        worksheet: gspread/Fake worksheet handle for Local_Deals.
        store_key: the store whose column is updated ("dunya" =
            PERMANENT site column; "dunya_fb" / shop keys = the
            shop's SPECIAL column).
        deals: vision-schema deal dicts (see _to_vision_deal). A
            deal may carry its own `valid_until` date — special
            cells are stamped per deal (' (till 12 Sep)'), so two
            posts with different end dates coexist (user rule
            2026-09-07).
        valid_until: optional datetime.date — row-2 summary stamp
            for this store's column (newest dated post). Never
            stamped for the Dunya PERMANENT column (live site
            prices — no validity period).
        master_ws: optional handle for the master tab — enables
            the parity auto-create mirror (spec §4.2).

    Returns:
        (int, list[str]): number of grid rows written (header
        included) + one report line per new (appended) row.
    """
    rows_by_section = build_rows({store_key: deals})
    col, kind = _target_column(store_key)
    comments_col = _grid_col("comments")

    grid = worksheet.get_all_values() or [["Product"] + [
        name for _k, name in TAB_COLUMNS]]
    # Normalise row WIDTH so index assignment never fails.
    grid = [(r + [""] * len(TAB_COLUMNS))[:len(TAB_COLUMNS) + 1]
            for r in grid]
    if not grid or not str(grid[0][0]).strip():
        grid = [["Product"] + [name for _k, name in TAB_COLUMNS]]
    # Canonical row 2: "Prices valid until" (insert for tabs that
    # predate the 2026-09-07 layout).
    if len(grid) < 2 or str(grid[1][0]).strip() != \
            "Prices valid until":
        grid.insert(1, ["Prices valid until", "n/a (live site)",
                        "", "", "", "", "", "", "", "", ""])
    if valid_until is not None and col is not None \
            and kind == "special":
        grid[1][col] = f"valid until {valid_until:%a %d %b}"

    appended: list[list] = []    # NEW rows, in append order
    for section in SECTION_ORDER:
        section_rows = rows_by_section.get(section) or []
        if not section_rows:
            continue
        for row in section_rows:
            # FIX-8 (D4) + ID-2 (v2 reuse guard, 2026-09-11): exact
            # canonical equality first, then plural-folded token
            # containment (unit markers + halal ignored) — the
            # morning's 13 near-duplicate rows came from descriptor
            # drift ("Halal Sliced Lamb Neck" vs "Halal Lamb Necks").
            # Round 3: matching is GRID-WIDE — new rows bottom-append
            # outside their section block (Q27).
            match = _reuse_match_index(grid, row[0])
            if match is None:
                grid.append(list(row))
                appended.append(grid[-1])
            elif col is not None:
                if row[col] != "":
                    grid[match][col] = row[col]
                # FIX-4 (D11): the Comments cell is rebuilt from the
                # NEWEST post — an empty note CLEARS this shop's
                # segment instead of keeping the last promo text.
                incoming = str(row[comments_col])
                raw_note = (_TAG_RE.sub("", incoming, count=1).strip()
                            if incoming else "")
                grid[match][comments_col] = _merge_comment_cell(
                    grid[match][comments_col], store_key, raw_note)

    new_row_lines: list[str] = []
    if appended:
        new_row_lines = _mirror_new_rows(store_key, appended,
                                         master_ws)
    worksheet.clear()
    worksheet.freeze(rows=2)
    worksheet.update(values=grid, range_name=f"A1:K{len(grid)}")
    return len(grid), new_row_lines


def _mirror_new_rows(store_key: str, appended: list,
                     master_ws) -> list[str]:
    """Bottom-append parity (§4.2/§18-A2): one blank 13-col master
    row per appended LD row — name, Item_Code from the registry,
    Sub_Category by domain; D (price) and G (keyword) BLANK. The
    code also lands in the LD row's col K. ONE clear+update on the
    master tab. `master_ws=None` mirrors nothing but still reports
    the rows that WOULD mirror (tests/legacy)."""
    lines: list[str] = []
    if master_ws is None:
        for ld_row in appended:
            lines.append(f"{ld_row[0]} [new row — master mirror "
                         f"skipped (no master handle)]")
        return lines
    from core import item_codes

    master_grid = [list(r) for r in
                   (master_ws.get_all_values() or [])]
    taken = item_codes.retired_codes(item_codes.load_registry())
    for r in master_grid[1:]:
        c = str(r[11]).strip().upper() if len(r) > 11 else ""
        if c:
            taken.add(c)
    sub = "butchery" if _store_kind(store_key) == "butchery" \
        else "fruit & veg"
    sheet_id = item_codes._spreadsheet_id(master_ws)
    pending: list[tuple[str, int]] = []
    for ld_row in appended:
        code = item_codes.generate_codes(
            taken, 1, seed=f"merge:{store_key}:{ld_row[0]}")[0]
        taken.add(code)
        ld_row[10] = code                        # col K
        m_row = [""] * 13
        m_row[0] = str(ld_row[0])
        m_row[10] = sub
        m_row[11] = code
        master_grid.append(m_row)
        pending.append((code, len(master_grid)))  # 1-based sheet row
        lines.append(f"{ld_row[0]} [new row, code {code}]")
    master_ws.clear()
    master_ws.update(values=master_grid,
                     range_name=f"A1:M{len(master_grid)}")
    # Confirm AFTER the write succeeded (item_codes discipline D-IC4).
    for code, row_index in pending:
        item_codes.confirm_code(code, row_index,
                                spreadsheet_id=sheet_id)
    return lines


# --- special-first tab reading (user rule 2026-09-07) --------------------

def tab_store_price(row: list, store_key: str,
                    today: "date | None" = None
                    ) -> tuple[float | None, str]:
    """(price, source) for one shop row: SPECIAL cell first, then
    PERMANENT (user rule 2026-09-07). Expired specials are skipped
    even before the sweep runs; non-numeric cells (bulk offer text)
    return None — bulk/multibuy never enter the maths.

    Args:
        row: one Local_Deals grid row (get_all_values row).
        store_key: shop key ("dunya" ... "abusalim").
        today: injectable Sydney date (tests); default real today.

    Returns:
        (float price or None, "special" | "permanent" | "").
    """
    today = today or sydney_today()
    for col, label in ((_special_column_for(store_key), "special"),
                       (_perm_column_for(store_key), "permanent")):
        if col is None or len(row) <= col:
            continue
        cell = row[col]
        if _special_expired(cell, today):
            continue
        price = _numeric_price(cell)
        if price is not None:
            return price, label
    return None, ""


def sweep_expired_specials(worksheet, today: "date | None" = None
                           ) -> list[str]:
    """Clear SPECIAL cells whose ' (till ...)' date has passed.

    User rule 2026-09-07: a price valid till 6-Sep is removed from
    the sheet on 7-Sep morning. Only DATED cells are removed —
    undated special cells stay until the shop's next post replaces
    them. Rows are KEPT (only the cell is cleared, user decision
    2026-09-07). PERMANENT columns are never touched.

    R2-6 (D21): row-2 summary stamps are RE-DERIVED after the cell
    sweep — from the store's REMAINING live special cells (max
    remaining till date), so a stamp never dies (or goes stale) while
    live specials of that store survive elsewhere (Merjan: row 104
    till 11 Sep lived on while the stamp was cleared). A stamp is
    DELETED only when the store has NO live specials left AND the
    stamp itself is expired. An orphan FUTURE stamp with zero
    specials is deliberately left alone (D12, awaiting user triage).

    Args:
        worksheet: gspread/Fake worksheet handle for Local_Deals.
        today: injectable Sydney date (tests); default real today.

    Returns:
        list[str]: report lines, e.g. "Fruitopia: Carrots 1kg Bag
        /ea — 0.75 (till 6 Sep) removed". Empty when nothing
        expired (or the tab is missing/empty).
    """
    today = today or sydney_today()
    try:
        grid = worksheet.get_all_values() or []
    except Exception:  # noqa: BLE001 — missing tab -> nothing to do
        return []
    if len(grid) < 3:
        return []
    width = len(TAB_COLUMNS) + 1
    grid = [(list(r) + [""] * width)[:width] for r in grid]
    names = {k: name for k, name in STORE_COLUMNS}
    comments_col = _grid_col("comments")
    lines: list[str] = []
    changed = False

    # --- Pass 1: expired special CELLS (rows kept, cell cleared) ----
    for row in grid[2:]:
        name = str(row[0]).strip()
        if not name or name in SECTION_ORDER:
            continue
        for key in SHOP_TAGS:
            col = _special_column_for(key)
            cell = row[col]
            if not _special_expired(cell, today):
                continue
            until = _cell_till_date(cell, today)
            lines.append(
                f"{names[key]}: {name} — {cell} removed "
                f"(expired {until:%d %b})")
            row[col] = ""
            # FIX-4 (user rule 2026-09-09): the shop-tagged comment
            # segment dies WITH its price — other shops' segments stay.
            if comments_col is not None:
                row[comments_col] = _merge_comment_cell(
                    row[comments_col], key, "")
            changed = True

    # --- Pass 2 (R2-6): row-2 stamps re-derived from what REMAINS ---
    # Only EXISTING stamps are re-derived/cleared — a blank stamp cell
    # stays blank (stamps are born in the ingest/set-special writers,
    # not the sweep).
    if str(grid[1][0]).strip() == "Prices valid until":
        for key in SHOP_TAGS:
            col = _special_column_for(key)
            cell = str(grid[1][col] or "")
            if not cell.strip():
                continue
            stamp = _stamp_date(cell, today)
            live_tills: list = []
            any_live = False
            for row in grid[2:]:
                if not str(row[0]).strip() or \
                        str(row[0]).strip() in SECTION_ORDER:
                    continue
                live_cell = str(row[col]) if len(row) > col else ""
                if not live_cell.strip():
                    continue
                any_live = True
                till = _cell_till_date(live_cell, today)
                if till is not None and till >= today:
                    live_tills.append(till)
            if live_tills:
                wanted = f"valid until {max(live_tills):%a %d %b}"
                if cell.strip() != wanted:
                    lines.append(
                        f"{names[key]}: validity stamp re-derived "
                        f"to '{wanted}' (from live specials)")
                    grid[1][col] = wanted
                    changed = True
            elif not any_live and stamp is not None and stamp < today:
                lines.append(f"{names[key]}: validity stamp "
                             f"'{cell.strip()}' removed (expired)")
                grid[1][col] = ""
                changed = True

    if changed:
        worksheet.clear()
        worksheet.update(values=grid, range_name=f"A1:K{len(grid)}")
    return lines


def repair_orphan_comments(worksheet) -> list[str]:
    """Strip shop-tagged Comments segments whose shop has NO price
    left in the row (both the permanent AND special cells blank).

    Round-1 (A7): clears the pre-FIX-4 sweep residue (e.g. '[FRU]
    multi buy 2 for $1.50' on empty cells — Local_Deals rows 115/116).
    Conservative by design: a NON-NUMERIC offer-text cell counts as a
    present price (never stripped); untagged free text is preserved
    verbatim; rows and other columns are never touched. Idempotent —
    a second run reports nothing.

    Args:
        worksheet: gspread/Fake worksheet handle for Local_Deals.

    Returns:
        list[str]: report lines, e.g. "Fruitopia Mt Druitt: Celery
        /ea — orphan comment '[FRU] multi buy …' removed".
    """
    try:
        grid = worksheet.get_all_values() or []
    except Exception:  # noqa: BLE001 — missing tab -> nothing to do
        return []
    if len(grid) < 3:
        return []
    width = len(TAB_COLUMNS) + 1
    grid = [(list(r) + [""] * width)[:width] for r in grid]
    names = {k: name for k, name in STORE_COLUMNS}
    comments_col = _grid_col("comments")
    lines: list[str] = []
    changed = False
    for row in grid[2:]:
        name = str(row[0]).strip()
        if not name or name in SECTION_ORDER:
            continue
        cell = str(row[comments_col] or "")
        if not _TAG_RE.search(cell):
            continue
        kept: list[str] = []
        for seg in cell.split(";"):
            seg = seg.strip()
            if not seg:
                continue
            m = _TAG_RE.match(seg)
            if m is None:
                kept.append(seg)            # free text survives
                continue
            shop = _shop_key_for_tag(m.group(1))
            priced = any(
                col is not None and len(row) > col
                and str(row[col]).strip()
                for col in (_perm_column_for(shop),
                            _special_column_for(shop)))
            if priced:
                kept.append(seg)
            else:
                lines.append(f"{names.get(shop, shop)}: {name} — "
                             f"orphan comment '{seg}' removed")
                changed = True
        rebuilt = "; ".join(kept)
        if rebuilt != cell:
            row[comments_col] = rebuilt
    if changed:
        worksheet.clear()
        worksheet.update(values=grid,
                         range_name=f"A1:K{len(grid)}")
    return lines


# --- manual pricing entry (permanent / special) --------------------------

_BASE_NAME_RE = re.compile(r"\s*/\s*(kg|ea|each)\s*$", re.I)


def _base_name(col_a: str) -> str:
    """Row Col A without its ' /kg' / ' /ea' unit suffix."""
    return _BASE_NAME_RE.sub("", str(col_a or "")).strip()


def set_store_prices(worksheet, store_key: str, kind: str,
                     entries: list[dict],
                     till: "date | None" = None,
                     master_ws=None) -> list[str]:
    """Write PERMANENT or SPECIAL prices for one shop by hand.

    User rule 2026-09-07: chat messages like 'update permanent
    pricing for fruitopia - carrots @ 6.50/kg' land here. Rows are
    matched by EXACT canonical key (the Col A unit suffix ignored,
    grid-wide — matching is not section-scoped any more); a
    non-matching item APPENDS A NEW ROW AT GRID END (Round 3, Q27 —
    never a mid-tab insert). When `master_ws` is given, the SAME
    operation bottom-appends the blank master counterpart (§4.2
    parity auto-create, codes from the registry). Permanent cells
    carry NO validity; special cells are stamped ' (till <d Mon>)'
    when `till` is given. An optional per-entry note is shop-tagged
    into the shared Comments column. Butchery-sourced entries get
    the Q17 'Halal ' prefix at normalization (_prefix_butcher_deals).

    Args:
        worksheet: gspread/Fake worksheet handle for Local_Deals.
        store_key: one of dunya/merjan/fruitopia/abusalim.
        kind: "perm" | "special".
        entries: [{item, price, unit, note?}] — price is the NUMERIC
            rate (multibuy rate precomputed by the caller).
        till: validity end for special entries (optional; undated
            specials are legal but the sweep can never clear them).
        master_ws: optional handle for the master tab — enables
            the parity auto-create mirror for NEW rows.

    Returns:
        list[str]: report lines ("Fruitopia special: Carrots /kg =
        0.75 (till 12 Sep) [row 112, new row]").
    """
    shop = dict(STORE_COLUMNS).get(store_key, store_key)
    kind = "perm" if kind == "perm" else "special"
    col = (_perm_column_for(store_key) if kind == "perm"
           else _special_column_for(store_key))
    comments_col = _grid_col("comments")

    grid = worksheet.get_all_values() or [["Product"] + [
        name for _k, name in TAB_COLUMNS]]
    width = len(TAB_COLUMNS) + 1
    grid = [(list(r) + [""] * width)[:width] for r in grid]
    if len(grid) < 2 or str(grid[1][0]).strip() != \
            "Prices valid until":
        grid.insert(1, ["Prices valid until", "n/a (live site)",
                        "", "", "", "", "", "", "", "", ""])

    entries = _prefix_butcher_deals(store_key, entries)
    lines: list[str] = []
    appended: list[list] = []
    for entry in entries:
        item = str(entry.get("item") or "").strip()
        price = entry.get("price")
        unit = str(entry.get("unit") or "").strip().lower()
        note = str(entry.get("note") or "").strip()
        if not item or not isinstance(price, (int, float)) \
                or price <= 0:
            lines.append(f"{shop}: skipped unreadable entry "
                         f"'{item or '?'}'")
            continue
        display = _display_name({"item": item, "unit": unit,
                                 "price_kind": "single"})
        if unit not in ("kg", "ea"):
            display = item           # no suffix without a unit

        match = _reuse_match_index(grid, display)
        cell = _stamp_validity(round(float(price), 2), till) \
            if kind == "special" else round(float(price), 2)
        if match is None:
            row = [display] + [""] * len(TAB_COLUMNS)
            row[col] = cell
            if note:
                row[comments_col] = _tag_note(store_key, note)
            grid.append(row)
            appended.append(grid[-1])
            lines.append(f"{shop} {kind}: {display} = {cell}"
                         f" [new row]")
        else:
            old = grid[match][col]
            grid[match][col] = cell
            # R1-A4: the newest entry owns the Comments cell — a plain
            # reprice (no note) CLEARS this shop's stale segment, same
            # rule as the ingest merge path (FIX-4).
            grid[match][comments_col] = _merge_comment_cell(
                grid[match][comments_col], store_key, note)
            lines.append(
                f"{shop} {kind}: {display} = {cell}"
                f" — was {old or 'empty'} [row {match + 1}]")
        if kind == "special" and till is not None:
            grid[1][col] = f"valid until {till:%a %d %b}"

    if appended:
        lines.extend(_mirror_new_rows(store_key, appended,
                                      master_ws))
    worksheet.clear()
    worksheet.update(values=grid, range_name=f"A1:K{len(grid)}")
    return lines


_SITE_DASH_RE = re.compile(
    r"\s*[–—-]\s*\d+(?:[.,]\d+)?(?:\s*[-–—]\s*\d+(?:[.,]\d+)?)?\s*"
    r"(?:kg|g|each|ea|pack)?\s*$", re.IGNORECASE)
_SITE_MB_STRIP_RE = re.compile(
    r"\s*[–—-]?\s*(?:buy\s*)?\d{1,2}\s*(?:for|x|×)\s*"
    r"\$?\d{1,4}(?:[.,]\d{1,2})?\s*$", re.IGNORECASE)


def _clean_site_name(name: str) -> str:
    """WooCommerce product name -> clean display/product name.

    Decodes HTML entities ("Lamb Leg Roast &#8211; 2.5-3kg" keeps an
    en dash as text), then drops TRAILING offer/size fragments —
    "– 2.5-3kg" (size) and "2 FOR $30" (multi-buy wording) in any
    order — so the same roast is always ONE Local_Deals row instead
    of sprouting duplicates. Names without such fragments pass
    through unchanged.
    """
    import html as _html

    clean = _html.unescape(str(name or "")).strip()
    clean = re.sub(r"\s+", " ", clean)
    clean = re.sub(r"\s*\(per kg\)|\s*\(each\)", "", clean,
                   flags=re.IGNORECASE)
    for _ in range(3):                 # size and offer can co-exist
        stripped = _SITE_MB_STRIP_RE.sub("", clean)
        stripped = _SITE_DASH_RE.sub("", stripped).strip(" –—-")
        if stripped == clean:
            break
        clean = stripped
    return clean or str(name or "").strip()


_SITE_MULTIBUY_RE = re.compile(
    r"(?:buy\s*)?(\d{1,2})\s*(?:for|x|×)\s*\$?(\d{1,4}(?:[.,]\d{1,2})?)",
    re.IGNORECASE)


def _parse_site_multibuy(name: str) -> tuple[int, float] | None:
    """(qty, bundle_total) when a site product NAME carries a multi-
    buy offer ("2 FOR $20", "BUY 3 FOR 30", "2 x $15"), else None.

    Butchery specials are mostly multi-buys, and the WooCommerce API
    has no dedicated multibuy field — the offer wording lives in the
    product name, so it is parsed here (user rule 2026-09-06: handle
    multibuy discounts in the site sync).
    """
    m = _SITE_MULTIBUY_RE.search(name or "")
    if not m:
        return None
    qty = int(m.group(1))
    total = float(m.group(2).replace(",", "."))
    if qty <= 0 or total <= 0:
        return None
    return qty, round(total, 2)


def sync_dunya_site(dry_run: bool = False, send: bool = True,
                    force: bool = False) -> int:
    """Build/update the Local_Deals tab from dunyabutchery.com.au
    (user-directed 2026-09-06).

    The shop's OWN website (WooCommerce Store API via Scrape.do —
    verified working 2026-09-05) is the source: every catalogue item
    lands in the Dunya column (initial build = full build; later
    runs merge and only change what moved). Discounts are visible
    two ways, both reported: the site's own sale price vs regular
    price, and any cell change vs the previous sync.

    Args:
        dry_run: fetch + print the diff; no sheet write, no Telegram.
        send: post the summary to the local-deals topic.
        force: bypass the site-catalogue cache (28-day).

    Returns:
        int: 0 synced, 1 no catalogue / no items.
    """
    from extractors.shop_site_catalogue import (
        get_normalised_catalogue,
    )
    from core.sheets_client import connect_spreadsheet, _load_env

    _load_env()
    items = get_normalised_catalogue("dunya", force=force)
    items = [i for i in items
             if isinstance(i.get("price"), (int, float))
             and i["price"] > 0]
    if not items:
        print("[dunya-site] no catalogue items (fetch failed?)")
        return 1

    # WC Store API prices are minor units (cents) — verified
    # 2026-09-05: BEEF MINCE (5KG) 6499 -> $64.99. Multi-buy offers
    # ("2 FOR $20") are parsed from the product NAME into
    # price_kind=multibuy (the site's specials are mostly multi-buys,
    # especially meat): the specials cell gets the effective unit
    # rate and the Comments column the bundle note (same as FB posts).
    deals = []
    for i in items:
        name = _clean_site_name(i["name"])
        price = round(i["price"] / 100, 2)
        regular = (round(i["regular_price"] / 100, 2)
                   if i.get("regular_price") else None)
        mb = _parse_site_multibuy(i["name"]) or \
            _parse_site_multibuy(name)
        if mb:
            qty, total = mb
            deals.append({
                "item": name,
                "raw_text": i["name"],
                "price": total,
                "unit": i.get("unit") or "ea",
                "price_kind": "multibuy",
                "multibuy_qty": qty,
                "bulk_size": None,
                "category": "butchery",
                "notes": "",
                "regular_price": regular,
            })
            continue
        deals.append({
            "item": name,
            "raw_text": i["name"],
            "price": price,
            "unit": i.get("unit") or "ea",
            "price_kind": "single",
            "multibuy_qty": None,
            "bulk_size": None,
            "category": "butchery",
            "notes": "",
            "regular_price": regular,
        })

    # Q17: Dunya is a butchery source — every site item is prefixed
    # at normalization (matched rows were renamed at migration, so
    # the prefix is what makes them match).
    deals = _prefix_butcher_deals("dunya", deals)

    on_offer = [d for d in deals
                if d.get("regular_price")
                and d["price"] < d["regular_price"]]

    if dry_run:
        print(f"[dunya-site] {len(deals)} items "
              f"({len(on_offer)} on offer) — dry-run, sheet "
              f"untouched")
        for d in on_offer:
            save = round(d["regular_price"] - d["price"], 2)
            pct = round(100 * save / d["regular_price"])
            print(f"   OFFER: {d['item']} {_money(d['price'])}"
                  f" (was {_money(d['regular_price'])}, "
                  f"save {_money(save)} = {pct}%)")
        return 0

    spreadsheet = connect_spreadsheet()
    worksheet = ensure_local_deals_tab(spreadsheet)
    grid_before = worksheet.get_all_values() or []
    dunya_col = _perm_column_for("dunya")     # site prices column
    before = {str(r[0]).strip(): r[dunya_col]
              for r in grid_before[1:] if len(r) > dunya_col}
    # §18/A1: site items NEVER auto-create rows — the site catalogue
    # was absorbed ONCE at migration; later unmatched items are
    # skipped + reported (add via an FB post or a manual entry).
    matched = [d for d in deals
               if _canonical_match_index(grid_before,
                                         _display_name(d)) is not None]
    skipped = [d for d in deals if d not in matched]
    rows = merge_store_tab(worksheet, "dunya",
                           [{k: v for k, v in d.items()
                             if k != "regular_price"}
                            for d in matched])
    print(f"[dunya-site] synced {len(matched)} items "
          f"({rows} grid rows); {len(on_offer)} on offer")
    for d in skipped:
        print(f"[dunya-site] not tracked — add via an FB post or a "
              f"manual entry: {d['item']}")

    changes = []
    for d in deals:
        # The sheet's Col A is _display_name(item) — diff on THAT.
        prev = before.get(_display_name(d).strip())
        if prev in ("", None) or str(prev) == str(d["price"]):
            continue
        try:
            old = float(str(prev).replace("$", ""))
        except ValueError:
            continue
        if abs(old - d["price"]) >= 0.01:
            changes.append((d["item"], old, d["price"]))

    lines = [f"🐑 Dunya Butchery site sync: {len(matched)} items "
             f"({len(on_offer)} on offer) — Local_Deals updated"]
    if changes:
        lines.append(f"Price changes since last sync: "
                     f"{len(changes)}")
        for name, old, new in changes[:10]:
            arrow = "🔻" if new < old else "🔺"
            lines.append(f"  {arrow} {name}: {_money(old)} -> "
                         f"{_money(new)}")
    if on_offer:
        lines.append("On offer right now (site sale prices):")
        for d in on_offer[:10]:
            save = round(d["regular_price"] - d["price"], 2)
            lines.append(f"  • {d['item']} {_money(d['price'])} "
                         f"(regular {_money(d['regular_price'])}, "
                         f"save {_money(save)})")
    if skipped:
        lines.append("Not tracked — add via an FB post or a manual "
                     "entry:")
        for d in skipped:
            lines.append(f"  • {d['item']}")
    bot_token = os.getenv("TELEGRAM_CLAW_BOT", "")
    topic_id = _env_int(LOCAL_DEALS_TOPIC_ENV)
    receipt = _send_message(bot_token, TELEGRAM_CHAT_ID,
                            "\n".join(lines),
                            thread_id=topic_id or TELEGRAM_CHAT_ID)
    if not receipt.get("ok"):
        print("[dunya-site] telegram delivery failed")
    return 0


def run_local_deals(stores=None, dry_run: bool = False,
                    send_telegram: bool = True,
                    refresh_catalogue: bool = False) -> int:
    """The §5 pipeline. ThreadPoolExecutor(max_workers=4), one future
    per store; posts sequential within a store. Freshness drop after
    vision (valid_until < today Sydney; all-null dates keep posts).
    Sheet rebuild unless dry_run. Telegram unless dry_run or
    send_telegram False (then stdout). Returns 0 success, 1 partial
    failure with report still sent, 2 total failure.

    Args:
        stores: store keys to run (default all four).
        dry_run: fetch+parse+match+report to stdout only.
        send_telegram: deliver the two posts via Telegram.
        refresh_catalogue: force the Dunya site-catalogue walk.
    """
    from concurrent.futures import ThreadPoolExecutor

    from core.sheets_client import _load_env
    _load_env()
    from extractors.fb_flyer_fetch import FLYERS_DIR, STORES
    from extractors.fb_flyer_fetch import FetchUnavailable
    from core.flyer_vision import VisionUnavailable  # noqa: F401

    wanted = {s.strip() for s in (stores or []) if s and s.strip()}
    active = [s for s in STORES if not wanted or s["key"] in wanted]
    if not active:
        print(f"[local-deals] unknown stores: {sorted(wanted)}")
        return 2
    today_syd = sydney_today()
    # §5 bug fix: the report headers carry the RUN's actual Sydney
    # weekday (render functions no longer hardcode "Fri").
    run_label = today_syd.strftime("%a %Y-%m-%d")
    run_dir = FLYERS_DIR / sydney_now().strftime("%Y%m%d_%H%M%S")

    # Dunya site catalogue loads ONCE before the fan-out (D14).
    site_catalogues: dict[str, list[dict]] = {}
    try:
        from extractors.shop_site_catalogue import (
            get_normalised_catalogue,
        )
        catalogue = get_normalised_catalogue(
            "dunya", force=refresh_catalogue)
        if catalogue:
            site_catalogues["dunya"] = catalogue
    except Exception as exc:  # noqa: BLE001 — degrade to no site note
        print(f"[local-deals] site catalogue unavailable: "
              f"{exc.__class__.__name__}")

    store_deals: dict[str, list[dict]] = {}
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {s["key"]: pool.submit(_process_store, s, run_dir,
                                         today_syd)
                   for s in active}
        for key, future in futures.items():
            try:
                store_deals[key] = future.result()
            except Exception as exc:  # noqa: BLE001 — store isolation
                failures.append(key)
                kind = exc.__class__.__name__
                if isinstance(exc, (FetchUnavailable,)):
                    print(f"[local-deals] {key}: {exc}")
                else:
                    print(f"[local-deals] {key}: {kind}")

    # Dunya's FACEBOOK deals write to the "Dunya FB specials"
    # column — the Dunya (site) column belongs to --dunya-site sync
    # (user rule 2026-09-06).
    if "dunya" in store_deals:
        store_deals["dunya_fb"] = store_deals.pop("dunya")

    flat_rows = [d for deals in store_deals.values() for d in deals]
    master_rows: list[dict] = []
    try:
        from core.sheets_client import connect_worksheet
        master_rows = _load_master_rows(connect_worksheet())
    except Exception as exc:  # noqa: BLE001 — matching degrades
        print(f"[local-deals] master read failed "
              f"({exc.__class__.__name__}) — matching degraded")

    results = match_and_detect(flat_rows, master_rows,
                               site_catalogues)

    if not dry_run and store_deals:
        try:
            from core.sheets_client import connect_spreadsheet
            spreadsheet = connect_spreadsheet()
            worksheet = ensure_local_deals_tab(spreadsheet)
            rows_by_section = build_rows(store_deals)
            # Row-2 summary stamp per shop: the NEWEST dated post of
            # the run (per-cell stamps are authoritative; this is
            # readability only).
            validity = {}
            for key, shop_deals in store_deals.items():
                dated = [d["valid_until"] for d in shop_deals
                         if d.get("valid_until")]
                if dated:
                    validity[key] = (f"valid until "
                                     f"{max(dated):%a %d %b}")
            rebuild_tab(worksheet, rows_by_section,
                        list(store_deals.keys()), validity=validity)
        except Exception as exc:  # noqa: BLE001 — tab write is not
            # allowed to kill the report; the run still delivers.
            print(f"[local-deals] tab rebuild failed: "
                  f"{exc.__class__.__name__}")

    post1 = render_post1(results, run_label)
    blocks = render_post2_blocks(results, run_label)
    if dry_run or not send_telegram:
        print(post1)
        print()
        for block in blocks:
            print(block)
            print()
    else:
        bot_token = os.getenv("TELEGRAM_CLAW_BOT", "")
        topic_id = _env_int(LOCAL_DEALS_TOPIC_ENV)
        deliver_reports(bot_token, post1, blocks, topic_id)

    if failures and len(failures) < len(active):
        return 1
    if failures:
        return 2
    return 0
