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

from core.basket_optimizer import DEFAULT_SPLIT_THRESHOLD  # noqa: F401
from core.name_matcher import similarity_tokens, token_set_ratio
from core.subcategory import normalize_subcategory
from core.sydney_time import SYDNEY_TZ, sydney_now, sydney_today

ALERT_PCT = 20.0                # strictly greater (20.0 -> no alert)
MATCH_MIN_RATIO = 0.65          # master-match threshold (§1.4.3)
MSG_CHAR_LIMIT = 4000           # hard pre-send check (4096 budget)
STATE_PATH = (Path(__file__).resolve().parent.parent / "data"
              / "local_deals_cron_state.json")
SCAN_STATE_PATH = (Path(__file__).resolve().parent.parent / "data"
                   / "local_deals_scan_state.json")
SCAN_WINDOWS = (5, 15)          # Sydney hours: 05:00 and 15:00
INBOX_DIRNAME = "local_deals_inbox"
INBOX_DIR = (Path(__file__).resolve().parent.parent / "data"
             / INBOX_DIRNAME)

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


def canonical_key(item_name: str) -> tuple:
    """Variety-aware canonical grouping key (RF1, sandbox test3 18/18).

    Word-order-insensitive tokens via name_matcher.similarity_tokens,
    stopwords + pure numbers stripped; a variety qualifier is REQUIRED
    in the key when present ("Beef Diced" == "Diced Beef"; "Royal
    Gala" never merges with "Pink Lady"). Returns (base, variety).

    Args:
        item_name: raw product/deal name.

    Returns:
        (base, variety) — both sorted token tuples; variety phrases
        contribute their component words to neither part twice.
    """
    name = (item_name or "").lower()
    tokens = {t for t in similarity_tokens(name)
              if t not in STOPWORDS and not re.fullmatch(r"\d+(\.\d+)?", t)}
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


def run_daily_scan(dry_run: bool = False, send: bool = True,
                   max_posts: int = 1, backfill_days: int = 3,
                   ) -> int:
    """Twice-daily new-post detector (user-directed 2026-09-06).

    OWNERSHIP: the VPS cron is the only scanner. Running this on a
    second machine duplicates notifications (it keeps its own seen-
    state). Local runs: --dry-run for testing only.

    Flow: render each public page logged out, take the newest post,
    and give every NEW post a code — the shop's base code for the
    first unhandled post, then FRUT_1, FRUT_2, ... while earlier
    ones stay unhandled. The user's notification is plain language:
    shop, code, posted time (Sydney), validity date parsed from the
    post text, the inbox folder, and the exact replies ("CODE" to
    process, "ignore CODE" to skip). 'ingest' removes the pending
    code; 'ignore' retires it forever.

    Args:
        dry_run: print instead of sending Telegram; state untouched.
        send: send the notification via Telegram (topic 594).
        max_posts: posts inspected per store (newest only).
        backfill_days: max age of a first-sighting post to report.

    Returns:
        int: 0 all stores checked, 1 partial failure, 2 total.
    """
    from datetime import datetime as _dt

    from extractors.fb_flyer_fetch import FetchUnavailable
    from extractors.fb_timeline_fetch import fetch_timeline_posts

    open_now, window_key = daily_scan_window()
    state = _load_scan_state()
    windows = state.setdefault("windows", {})
    if open_now and not dry_run and windows.get(window_key) == "done":
        return 0                      # this window already serviced

    print(f"[daily-scan] window={window_key or 'off-schedule'}"
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
        newest = posts[0]
        seen = stores.get(store["key"], {})
        notified = seen.get("notified", {})      # post_ref -> code
        ignored = seen.get("ignored", [])
        age_days = ((now_syd.timestamp() - (newest.creation_time or 0))
                    / 86400) if newest.creation_time else 999

        if newest.post_ref in ignored:
            print(f"[daily-scan] {store['key']}: post ignored — "
                  f"skipped")
            continue
        if newest.post_ref in notified:
            print(f"[daily-scan] {store['key']}: already reported "
                  f"({notified[newest.post_ref]})")
            continue

        # New post: assign the next free code for this shop.
        base = store["code"]
        used = {c for c in notified.values() if c == base
                or c.startswith(base + "_")}
        if base not in used:
            code = base
        else:
            n = 0
            while f"{base}_{n + 1}" in used:
                n += 1
            code = f"{base}_{n + 1}"

        posted_line = "when posted: unknown"
        if newest.creation_time:
            posted = _dt.fromtimestamp(
                newest.creation_time, ZoneInfo(SYDNEY_TZ))
            posted_line = f"When posted: {posted:%a %d %b, %I:%M %p}"
        from extractors.deal_text import parse_validity_end
        valid_end = parse_validity_end(newest.text, today=now_syd.date())
        valid_line = (f"Valid until: {valid_end:%a %d %b}"
                      if valid_end
                      else "Valid until: not written in the post — "
                           "I will ask you for the date")

        first_sighting = not seen.get("baselined")
        if first_sighting and age_days > backfill_days:
            seen["baselined"] = True
            stores[store["key"]] = seen     # persist baseline flag
            print(f"[daily-scan] {store['key']}: newest post is "
                  f"{age_days:.0f}d old — nothing from the last "
                  f"{backfill_days} days, staying quiet")
            continue

        seen["baselined"] = True
        seen["notified"] = {**notified, newest.post_ref: code}
        seen["last_post_ref"] = newest.post_ref
        seen["last_creation"] = newest.creation_time
        seen["last_cutoff"] = now_syd.isoformat(timespec="seconds")
        stores[store["key"]] = seen     # persist the store entry
        new_posts.append((store, newest, code,
                          f"{posted_line}\n{valid_line}"))
        print(f"[daily-scan] {store['key']}: new post -> code "
              f"{code}")

    if not dry_run:
        if open_now:
            windows[window_key] = "done"
        _save_scan_state(state)

    for store, post, code, detail in new_posts:
        text = (
            f"🆕 New post from {store['name']} (code: {code})\n"
            f"\n{detail}\n"
            f"\nWant these prices?\n"
            f"  1. Save the post's picture or text into:\n"
            f"     grocery-price-tracker\\data\\{INBOX_DIRNAME}"
            f"\\{code}\n"
            f"  2. Then send me:  {code}\n"
            f"\nNot interested?  Just send:  ignore {code}")
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


def _store_and_entry_for_code(code: str) -> tuple[dict | None, dict,
                                                  str | None]:
    """Resolve a possibly-suffixed code (FRUT, FRUT_1, ...) to its
    store and the pending notified entry {post_ref: code}."""
    from extractors.fb_flyer_fetch import STORES

    code = code.strip().upper()
    base = code.split("_")[0]
    store = next((s for s in STORES if s.get("code") == base), None)
    if store is None:
        return None, {}, None
    state = _load_scan_state()
    seen = state.setdefault("stores", {}).get(store["key"], {})
    notified = seen.get("notified", {})
    ref = next((r for r, c in notified.items() if c == code), None)
    return store, seen, ref


def ignore_post(code: str) -> int:
    """'ignore <CODE>' — retire that post (scan never re-reports it).

    Args:
        code: the post's code (FRUT, FRUT_1, ...).

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


def inbox_dir_for(code: str) -> Path:
    """The per-code inbox folder, created on demand."""
    d = INBOX_DIR / code.strip().upper()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _newest_inbox_file(folder: Path) -> Path | None:
    """Newest non-hidden file in the folder (mtime), or None."""
    files = [p for p in folder.iterdir()
             if p.is_file() and not p.name.startswith(".")]
    return max(files, key=lambda p: p.stat().st_mtime) if files \
        else None


def ingest_code(code: str, dry_run: bool = False) -> int:
    """Process the newest file in data/local_deals_inbox/<CODE>/.

    The user copies a post's content into the inbox and replies with
    the code. Text files (.txt/.text/.md) run through the deal-line
    parser; images (.jpg/.jpeg/.png/.webp) through the vision chain.
    On success the Local_Deals tab is UPDATED for this store only
    (other stores' rows untouched — merge, not wipe) and a reader-
    friendly summary is posted to the local-deals topic.

    Args:
        code: the post's code from the notification (FRUT, FRUT_1...).
        dry_run: parse and print only; no sheet write, no Telegram.

    Returns:
        int: 0 processed, 1 no file / no deals / bad code.
    """
    from extractors.deal_text import (
        parse_fruitopia_deals, parse_validity_end,
    )
    from extractors.fb_flyer_fetch import STORES
    from core.sydney_time import sydney_today

    code = code.strip().upper()
    base = code.split("_")[0]
    store = next((s for s in STORES if s.get("code") == base), None)
    if store is None:
        print(f"[ingest] unknown code: {code}")
        return 1
    folder = inbox_dir_for(code)
    path = _newest_inbox_file(folder)
    if path is None:
        print(f"[ingest] no file in {folder}")
        return 1
    print(f"[ingest] {code}: processing {path.name}")
    today = sydney_today()

    if path.suffix.lower() in (".txt", ".text", ".md"):
        text = path.read_text(encoding="utf-8", errors="replace")
        deals = parse_fruitopia_deals(text)
        source = "text"
        valid_until = parse_validity_end(text, today=today)
    elif path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
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
        print(f"[ingest] unsupported file type: {path.suffix}")
        return 1

    if not deals:
        print(f"[ingest] I could not read any prices from "
              f"{path.name} — check the file and try again")
        return 1

    print(f"[ingest] read {len(deals)} items "
          f"({source}; valid until {valid_until or 'UNKNOWN'})")
    for d in deals:
        note = f" ({d['multibuy_note']})" if d.get("multibuy_note") \
            else ""
        print(f"   - {d['item']} — {_money(d['price'])}"
              f"/{d['unit']}{note}")
    if valid_until is None:
        print("[ingest] no validity date found — reply with the date "
              "(e.g. 'valid until 12 September') and I will record it")

    # Convert to the sheet schema and update the Local_Deals tab for
    # THIS store only (merge — other stores' rows are untouched).
    category = _store_kind(store["key"]) or "other"
    vision_deals = [_to_vision_deal(d, category) for d in deals]
    if dry_run:
        print("[ingest] dry-run: sheet write + summary skipped")
        return 0

    from core.sheets_client import connect_spreadsheet
    spreadsheet = connect_spreadsheet()
    worksheet = ensure_local_deals_tab(spreadsheet)
    # FB-post ingest targets the shop's FB specials column (Dunya:
    # "dunya_fb"); the site column is --dunya-site's.
    col_store = ("dunya_fb" if store["key"] == "dunya"
                 else store["key"])
    rows = merge_store_tab(worksheet, col_store, vision_deals)
    print(f"[ingest] Local_Deals tab updated ({rows} rows incl. "
          f"headers)")

    bot_token = os.getenv("TELEGRAM_CLAW_BOT", "")
    topic_id = _env_int(LOCAL_DEALS_TOPIC_ENV)
    valid_txt = (f"valid until {valid_until:%a %d %b}" if valid_until
                 else "valid until — date to confirm")
    lines = [f"📥 {store['name']} board saved ({len(deals)} items, "
             f"{valid_txt}):"]
    for d in deals:
        note = f" ({d['multibuy_note']})" if d.get("multibuy_note") \
            else ""
        lines.append(f"• {d['item']} — {_money(d['price'])}"
                     f"/{d['unit']}{note}")
    receipt = _send_message(bot_token, TELEGRAM_CHAT_ID,
                            "\n".join(lines),
                            thread_id=topic_id or TELEGRAM_CHAT_ID)
    if not receipt.get("ok"):
        print("[ingest] telegram delivery failed")

    # This post is handled: free its code (the next new post from
    # this shop reuses the base code).
    state = _load_scan_state()
    seen = state.setdefault("stores", {}).setdefault(store["key"], {})
    notified = seen.get("notified", {})
    ref = next((r for r, c in notified.items() if c == code), None)
    if ref is not None:
        notified.pop(ref)
        _save_scan_state(state)
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

TAB_COLUMNS = [  # Local_Deals tab layout (user rule 2026-09-06)
    ("dunya", "Dunya (site)"),      # dunyabutchery.com.au prices
    ("dunya_fb", "Dunya FB specials"),  # Facebook post prices
    ("merjan", "Merjan Brothers Quality Meats"),
    ("fruitopia", "Fruitopia Mt Druitt"),
    ("abusalim", "Abu Salim Fruit Market"),
    ("comments", "Comments"),       # multi-buy / bulk notes
]
# Kept for callers that reason about the four physical shops.
STORE_COLUMNS = [
    ("dunya", "Dunya (site)"),
    ("merjan", "Merjan Brothers Quality Meats"),
    ("fruitopia", "Fruitopia Mt Druitt"),
    ("abusalim", "Abu Salim Fruit Market"),
]
TAB_NAME = "Local_Deals"


def _column_for(store_key: str) -> int | None:
    """1-based grid column for a store key ('comments' -> 6)."""
    return next((i + 1 for i, (k, _n) in enumerate(TAB_COLUMNS)
                 if k == store_key), None)


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
                                         cols=7)
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
    math, read-only reuse of core.multibuy semantics)."""
    from core.multibuy import effective_unit_rate
    qty = int(deal.get("multibuy_qty") or 0)
    total = float(deal.get("price") or 0)
    rate = effective_unit_rate(qty, total)
    return (f"[multi buy {qty} for {_money(total)} "
            f"— {_money(rate)}/ea]")


def _cell_for(deal: dict) -> tuple:
    """(price cell, comments cell) for one deal.

    Price cell: single deals -> the price; multibuy -> the effective
    UNIT rate (comparable number); bulk -> the bundle price. Comments
    cell: the multi-buy/bulk note text (the user asked for specials
    pricing and multi-buy comments in separate columns —
    2026-09-06). None when the price is missing entirely.
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
    return cell, note


def build_rows(all_store_deals: dict) -> dict:
    """{section: [[Product, Dunya(site), Dunya FB specials, Merjan,
    Fruitopia, Abu Salim, Comments], ...]}.

    Canonical rows (RF1): equivalent IN-DOMAIN items share ONE row
    keyed by canonical_key; the numeric specials price sits in the
    store's column while multi-buy/bulk NOTE text goes to the
    Comments column (user rule 2026-09-06). Dunya has TWO columns:
    site prices (dunyabutchery.com.au, `--dunya-site`) and Facebook
    specials (DUNY ingest), side by side. Out-of-domain items NEVER
    merge into domain rows (Oreo rule) — standalone rows under OTHER.

    Args:
        all_store_deals: {store_key: [deal dicts with category +
            price_kind fields from the vision schema]}. store_key
            "dunya" targets the SITE column; "dunya_fb" targets the
            Facebook specials column.

    Returns:
        section -> grid rows (7 cells each, "" for absent stores).
    """
    rows_by_section: dict[str, list[list]] = {
        s: [] for s in SECTION_ORDER}
    row_index: dict[tuple, int] = {}
    for store_key, deals in all_store_deals.items():
        in_domain_kind = _store_kind(store_key)
        for deal in deals:
            in_domain = deal.get("category") == in_domain_kind
            if not in_domain:
                section = "OTHER"
                key = ("od", store_key,
                       canonical_key(deal.get("item") or ""))
            else:
                # One row per canonical base: the numeric specials
                # price sits in the store column and any multi-buy/
                # bulk note goes to Comments (never mixed).
                section = _section_for(deal)
                key = canonical_key(deal.get("item") or "")
            cell, comment = _cell_for(deal)
            display = _display_name(deal)
            slot = row_index.get((section, key))
            if slot is None:
                grid_row = [display] + [""] * 6
                rows_by_section[section].append(grid_row)
                row_index[(section, key)] = \
                    len(rows_by_section[section]) - 1
                slot = row_index[(section, key)]
            col = _column_for(store_key)
            if col is not None and cell is not None:
                rows_by_section[section][slot][col] = cell
            if col is not None and comment:
                rows_by_section[section][slot][6] = comment
    return {s: rows for s, rows in rows_by_section.items() if rows}


def rebuild_tab(worksheet, rows_by_section: dict,
                store_keys: list[str]) -> None:
    """Wipe + rewrite the tab (idempotent). Freeze row 1. ONE batch
    update A1:G{N} (gspread update(values=..., range_name=...)).

    Args:
        worksheet: gspread/Fake worksheet handle for Local_Deals.
        rows_by_section: build_rows() output.
        store_keys: stores in THIS run (other columns stay blank).
    """
    active = {k.strip() for k in (store_keys or [])
              if k and k.strip()} or {k for k, _n in TAB_COLUMNS}
    grid = [["Product"] + [name for _k, name in TAB_COLUMNS]]
    for section in SECTION_ORDER:
        section_rows = rows_by_section.get(section) or []
        if not section_rows:
            continue
        grid.append([section] + [""] * 6)
        for row in section_rows:
            row = list(row)
            for i, (k, _n) in enumerate(TAB_COLUMNS, start=1):
                if k not in active:
                    row[i] = ""  # columns not in this run stay blank
            grid.append(row)
    worksheet.clear()
    worksheet.freeze(rows=1)
    worksheet.update(values=grid, range_name=f"A1:G{len(grid)}")


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
    first (the rate IS the cell's price). Marker cells (N/A <date>,
    unavailable <date>, GONE, blank) return None.
    """
    if isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell) if cell > 0 else None
    text = str(cell or "").strip()
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
    """READ-ONLY Products_Master scan.

    Returns {row_index, name, category, size, wool_price,
    coles_price, subcategory} (numeric-decoded D/E). Fixed indices
    per the documented layout: A name, B coarse category, C size,
    D Woolworths, E Coles, Q Sub_Category. Never writes.
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
            "coles_price": _numeric_price(_cell(row, 4)),
            "subcategory": normalize_subcategory(_cell(row, 16)),
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
    """Master baseline on its comparison basis.

    Returns (unit_price, basis, store_name) — $/kg when the size
    parses as weight, else the raw unit price on the 'ea' basis, from
    the cheaper numeric D/E cell. None when no numeric baseline.
    """
    from core.uom import FAMILY_WEIGHT, parse_size
    baseline = None
    for store, key in (("Woolworths", "wool_price"),
                       ("Coles", "coles_price")):
        price = master_row.get(key)
        if price is not None and (baseline is None
                                  or price < baseline[0]):
            baseline = (price, store)
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

        best_ratio, best_master = 0.0, None
        deal_tokens = similarity_tokens(deal.get("item") or "")
        for master in master_rows:
            if not is_in_domain(store_kind,
                                deal.get("category") or "",
                                master["subcategory"],
                                master["category"]):
                continue
            ratio = token_set_ratio(deal.get("item") or "",
                                    master["name"])
            containment = bool(deal_tokens) and deal_tokens.issubset(
                similarity_tokens(master["name"]))
            if (ratio >= MATCH_MIN_RATIO or containment) \
                    and ratio > best_ratio:
                best_ratio, best_master = ratio, master

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
        if not _unit_prices_agree(deal, best_master):
            result.note = result.note or "unit mismatch"
            results.append(result)
            continue

        master_unit = _master_unit_price(best_master)
        deal_unit = _deal_unit_price(deal)
        if master_unit is None or deal_unit is None:
            results.append(result)
            continue
        baseline_unit_price, master_basis, baseline_store = master_unit
        flyer_unit_price, flyer_basis = deal_unit
        # Baseline display value: the chosen store's raw cell.
        result.baseline_store = baseline_store
        result.baseline_price = (
            best_master.get("wool_price")
            if baseline_store == "Woolworths"
            else best_master.get("coles_price"))
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
    for post, _end in kept:
        post_deals, source, vision_until = extract_post_deals(
            post, run_dir, store["key"])
        if source == "vision" and vision_until is not None \
                and vision_until < today_syd:
            print(f"[local-deals] {store['key']}: post "
                  f"{post.post_ref} board expired {vision_until} "
                  f"(vision date) — dropped")
            continue
        for deal in post_deals:
            deals.append({**deal,
                          "store_key": store["key"],
                          "store_name": store["name"],
                          "post_ref": post.post_ref,
                          "source": source})
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
        return _process_store_timeline(store, run_dir, today_syd)

    from extractors.fb_flyer_fetch import fetch_store_posts
    from core.flyer_vision import parse_board_images

    posts = fetch_store_posts(store, run_dir)
    deals: list[dict] = []
    for post in posts:
        payload = parse_board_images(post.files)
        valid_until = payload.get("valid_until")
        if valid_until:
            try:
                if date.fromisoformat(str(valid_until)) < today_syd:
                    continue   # expired board — freshness drop (§5)
            except ValueError:
                pass           # unparseable date keeps the post
        for deal in payload.get("deals") or []:
            deals.append({**deal,
                          "store_key": store["key"],
                          "store_name": store["name"],
                          "post_ref": post.post_ref})
    if not deals:
        from extractors.fb_flyer_fetch import FetchUnavailable
        raise FetchUnavailable("no deals parsed from any post")
    return deals


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


def merge_store_tab(worksheet, store_key: str, deals: list[dict],
                    ) -> int:
    """Merge ONE store's deals into the existing Local_Deals tab.

    Unlike rebuild_tab (wipe + rewrite for a full run), the ingest
    flow must NOT touch the other stores' rows: the current grid is
    read, matching Product rows (same section, same Col A text) get
    this store's column cell updated, unmatched rows are appended
    inside their section block, and the FULL grid is written back in
    ONE batch update (same layout as rebuild_tab: header, then per
    section a title row + item rows).

    Args:
        worksheet: gspread/Fake worksheet handle for Local_Deals.
        store_key: the store whose column is updated ("dunya" =
            site column, "dunya_fb" = FB specials column).
        deals: vision-schema deal dicts (see _to_vision_deal).

    Returns:
        int: number of grid rows written (header included).
    """
    rows_by_section = build_rows({store_key: deals})
    col = _column_for(store_key)

    grid = worksheet.get_all_values() or [["Product"] + [
        name for _k, name in TAB_COLUMNS]]
    # Normalise row WIDTH so index assignment never fails.
    grid = [(r + [""] * len(TAB_COLUMNS))[:len(TAB_COLUMNS) + 1]
            for r in grid]
    if not grid or not str(grid[0][0]).strip():
        grid = [["Product"] + [name for _k, name in TAB_COLUMNS]]

    for section in SECTION_ORDER:
        section_rows = rows_by_section.get(section) or []
        if not section_rows:
            continue
        # Locate this section's title row and its block extent.
        title_idx = next((i for i, row in enumerate(grid)
                          if row and str(row[0]).strip() == section),
                         None)
        if title_idx is None:
            title_idx = len(grid)
            grid.append([section] + [""] * 6)
            block_end = title_idx + 1
        else:
            block_end = title_idx + 1
            while block_end < len(grid):
                first = str(grid[block_end][0]).strip()
                if first and first in SECTION_ORDER:
                    break                      # next section starts
                block_end += 1
        for row in section_rows:
            match = next(
                (i for i in range(title_idx + 1, block_end)
                 if str(grid[i][0]).strip()
                 == str(row[0]).strip()),
                None)
            if match is None:
                grid.insert(block_end, list(row))
                block_end += 1
            elif col is not None:
                if row[col] != "":
                    grid[match][col] = row[col]
                if row[6] != "":
                    grid[match][6] = row[6]
    worksheet.clear()
    worksheet.freeze(rows=1)
    worksheet.update(values=grid, range_name=f"A1:G{len(grid)}")
    return len(grid)


_SITE_DASH_RE = re.compile(
    r"\s*[–—-]\s*\d+(?:[.,]\d+)?(?:\s*[-–—]\s*\d+(?:[.,]\d+)?)?\s*"
    r"(?:kg|g|each|ea|pack)?\s*$", re.IGNORECASE)


def _clean_site_name(name: str) -> str:
    """WooCommerce product name -> clean display/product name.

    Decodes HTML entities ("Lamb Leg Roast &#8211; 2.5-3kg" keeps an
    en dash as text), then drops a TRAILING "– 2.5-3kg" size fragment
    after a dash so the same roast is always ONE Local_Deals row
    instead of sprouting size-specific duplicates. Names without a
    size fragment pass through unchanged.
    """
    import html as _html

    clean = _html.unescape(str(name or "")).strip()
    clean = re.sub(r"\s+", " ", clean)
    clean = re.sub(r"\s*\(per kg\)|\s*\(each\)", "", clean,
                   flags=re.IGNORECASE)
    clean = _SITE_DASH_RE.sub("", clean).strip(" –—-")
    return clean or str(name or "").strip()


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
    # 2026-09-05: BEEF MINCE (5KG) 6499 -> $64.99.
    deals = []
    for i in items:
        name = _clean_site_name(i["name"])
        deals.append({
            "item": name,
            "raw_text": i["name"],
            "price": round(i["price"] / 100, 2),
            "unit": i.get("unit") or "ea",
            "price_kind": "single",
            "multibuy_qty": None,
            "bulk_size": None,
            "category": "butchery",
            "notes": "",
            "regular_price": (round(i["regular_price"] / 100, 2)
                              if i.get("regular_price") else None),
        })

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
    dunya_col = next(i for i, (k, _n) in enumerate(STORE_COLUMNS)
                     if k == "dunya") + 1
    before = {str(r[0]).strip(): r[dunya_col]
              for r in grid_before[1:] if len(r) > dunya_col}
    rows = merge_store_tab(worksheet, "dunya",
                           [{k: v for k, v in d.items()
                             if k != "regular_price"}
                            for d in deals])
    print(f"[dunya-site] synced {len(deals)} items "
          f"({rows} grid rows); {len(on_offer)} on offer")

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

    lines = [f"🐑 Dunya Butchery site sync: {len(deals)} items "
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
            rebuild_tab(worksheet, rows_by_section,
                        list(store_deals.keys()))
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
