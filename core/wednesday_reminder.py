"""Wednesday Woolworths-sync reminder — v2 rebuild of the Phase-9.1
telegram_gateway job (2026-09-24: that script's crontab entry was
lost when the grocery crons moved into the container, and its v1
text told the user to run machinery that no longer exists).

Weekly Wednesday-morning Telegram nudge: paste instructions + the
items still missing a Woolworths price + a read-only row-parity
verdict, posted to the weekly-lists topic (208).

Design rulings (user ask 2026-09-24 — 'what I'm worried about is
the message hitting my Telegram at the right time'):
- Delivery truth: the week is marked sent ONLY when Telegram's API
  returns ok. A TRANSIENT failure (network, flood wait, 5xx) leaves
  the state untouched, so the hourly cron retries through the same
  Wednesday morning window (first attempt 05:xx Sydney, last
  10:xx). A PERMANENT failure (core.telegram_send: bad token, bot
  kicked, topic gone, text too long) is terminal: retries stop, the
  reason lands in the state where --status shows it, exit code 2.
- The sheet is READ-ONLY here: no writes, no repairs. The parity
  verdict mirrors tools/parity_audit — the same audit the Wednesday
  run acts on.
- Every log line is timestamped (Sydney) so a missed message is
  diagnosable from the cron log alone.

Stdlib + project imports only; Python 3.11 (VPS container).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_HERE = Path(__file__).resolve().parent
_TRACKER = _HERE.parent
DATA_DIR = _TRACKER / "data"
STATE_PATH = DATA_DIR / "wednesday_reminder_state.json"

SYDNEY_TZ = "Australia/Sydney"
FIRE_WEEKDAY = 2                # Wednesday (Monday=0)
FIRST_HOUR = 5                  # first attempt 05:xx Sydney
LAST_HOUR = 10                  # last retry attempt 10:xx Sydney
WEEKLY_TOPIC_ID = 208           # env override TELEGRAM_WEEKLY_TOPIC_ID

MAX_MSG_CHARS = 4000            # Telegram hard cap is 4096
LIST_LINE_CAPS = (20, 10, 0)    # missing-list shrink ladder
PARITY_LINE_CAP = 8

INSTRUCTIONS_TEXT = (
    "\U0001F4C5 WEDNESDAY WOOLWORTHS SYNC\n"
    "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"
    "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
    "\n"
    "1. Copy your Woolworths list into Woolworths.docx\n"
    "2. Copy the specials into Woolworths_Specials.docx\n"
    "3. Run on the PC (workspace root):\n"
    "    python grocery_price_cli.py wednesday\n"
    "\n"
    "It overwrites prices, posts the specials to the specials "
    "topic and your list to the weekly-lists topic (~15 s).\n"
    "No reply needed."
)

SHEET_DOWN_TEXT = (
    "\n\n\u26A0\uFE0F Couldn't read the sheet just now \u2014 the "
    "missing-list and row-sync sections were skipped. "
    "Send 'list' anytime for the current state."
)

EMPTY_LIST_TEXT = ("The missing list is empty \u2014 every local "
                   "price is at Woolworths.")


def _topic_id() -> int:
    try:
        return int(os.getenv("TELEGRAM_WEEKLY_TOPIC_ID", "")
                   or WEEKLY_TOPIC_ID)
    except ValueError:
        return WEEKLY_TOPIC_ID


def _load_state() -> dict:
    """Read the sent-weeks state; missing/corrupt = {}."""
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def week_key(now_syd: datetime) -> str:
    """ISO week key, e.g. '2026-W39' — unique per week."""
    iso = now_syd.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def should_fire(now_syd: datetime, state: dict | None = None) -> bool:
    """Wednesday, 05:xx-10:xx Sydney, week not already confirmed."""
    state = state if state is not None else _load_state()
    return (now_syd.weekday() == FIRE_WEEKDAY
            and FIRST_HOUR <= now_syd.hour <= LAST_HOUR
            and week_key(now_syd) not in state)


def _log(msg: str, now_syd: datetime) -> None:
    stamp = now_syd.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[wed-reminder {stamp} Sydney] {msg}")


def _parse_rows(master_grid: list, ld_grid: list) -> tuple:
    """(master_rows, ld_rows) parsed with the v2_read readers."""
    from core.v2_read import parse_ld_row, parse_master_row

    master = [parsed for i, row in enumerate(master_grid[1:], start=2)
              if (parsed := parse_master_row(i, row))]
    ld = [parsed for i, row in enumerate(ld_grid, start=1)
          if (parsed := parse_ld_row(i, row))]
    return master, ld


def _missing_section(master_rows: list, ld_rows: list,
                     cap: int) -> tuple[str, int]:
    """'Still missing a Woolworths price' block + the item count.
    cap limits the inline entries; the count always shows the
    true total (the `list` verb has the full render)."""
    from core.v2_read import _shop_label, missing_list

    items = missing_list(master_rows, ld_rows)
    if not items:
        return EMPTY_LIST_TEXT, 0
    lines = []
    for item in items[:cap]:
        best = item.get("best_local")
        best_txt = ""
        if best:
            price, shop = best
            label = _shop_label(shop)
            best_txt = f" \u2014 best ${price:.2f} ({label})"
        lines.append(f"[{item['code']}] {item['name']}{best_txt}")
    hidden = len(items) - min(len(items), cap)
    if hidden > 0:
        lines.append(f"(+{hidden} more \u2014 send 'list' for all)")
    header = (f"\U0001F6D2 STILL MISSING A WOOLWORTHS PRICE "
              f"({len(items)})")
    return "\n".join([header] + lines), len(items)


def _parity_section(master_grid: list, ld_grid: list) -> str:
    """Read-only row-sync verdict via tools/parity_audit (the same
    audit the Wednesday run acts on — never writes here)."""
    from tools.parity_audit import audit, format_report

    result = audit(master_grid, ld_grid)
    report = format_report(result)
    if result.get("status") == "aligned":
        master_n = sum(1 for r in master_grid[1:]
                       if str(r[0]).strip()) if master_grid else 0
        return (f"\U0001F517 ROW SYNC: \u2705 ALIGNED \u2014 "
                f"{master_n} item rows on each tab")
    lines = report.splitlines()[:PARITY_LINE_CAP]
    if len(report.splitlines()) > PARITY_LINE_CAP:
        lines.append(f"  (+{len(report.splitlines()) - PARITY_LINE_CAP}"
                     " more lines)")
    status = str(result.get("status") or "DRIFT")
    return "\n".join(
        [f"\U0001F517 ROW SYNC: \u26A0\uFE0F {status.upper()} "
         "(Wednesday's run will repair bottom-appends; a middle "
         "insert needs a manual move)"] + lines)


def _no_local_count(ld_rows: list) -> int:
    """Local_Deals rows with no price from any shop (Woolworths-only
    mirrors — reported as a count, never a wall of names)."""
    return sum(1 for row in ld_rows if not row.get("prices"))


def build_message(master_grid: list, ld_grid: list,
                  now_syd: datetime | None = None) -> str:
    """The full reminder text: instructions + live sheet sections.
    The missing list shrinks (20 -> 10 -> 0 entries) if the whole
    message would pass the Telegram cap."""
    master_rows, ld_rows = _parse_rows(master_grid, ld_grid)
    parity = _parity_section(master_grid, ld_grid)
    no_local = _no_local_count(ld_rows)
    counts_line = (f"\U0001F3F7\uFE0F NO LOCAL PRICE YET: {no_local} "
                   f"item(s) \u2014 Woolworths-only rows (normal)")

    for cap in LIST_LINE_CAPS:
        missing, _n = _missing_section(master_rows, ld_rows, cap)
        text = (f"{INSTRUCTIONS_TEXT}\n\n{missing}\n\n{counts_line}"
                f"\n{parity}")
        if len(text) <= MAX_MSG_CHARS:
            return text
    return text            # cap 0 already fits (instructions alone)


def _read_grids() -> tuple:
    """ONE sheet connection -> (master_grid, ld_grid), raw values."""
    from core.local_deals import TAB_NAME
    from core.sheets_client import connect_spreadsheet
    from core.v2_wednesday import MASTER_TAB

    spreadsheet = connect_spreadsheet()
    master_grid = [list(r) for r in
                   (spreadsheet.worksheet(MASTER_TAB)
                    .get_all_values() or [])]
    ld_grid = [list(r) for r in
               (spreadsheet.worksheet(TAB_NAME)
                .get_all_values() or [])]
    return master_grid, ld_grid


def run_scan(now: datetime | None = None, force: bool = False,
             send: bool = True) -> int:
    """Cron entry. Returns exit code.

    force bypasses the weekday/hour/week gates (supervised fires);
    send=False prints the message instead of posting (dry runs).
    The week is marked sent ONLY on a Telegram-ok receipt — a
    failed send returns 1 and the state stays clean so the next
    hourly cron retries inside the Wednesday window.
    """
    from core.local_deals import TELEGRAM_CHAT_ID
    from core.sydney_time import sydney_now
    from core.telegram_send import send_classified

    now_syd = (now or sydney_now()).astimezone(ZoneInfo(SYDNEY_TZ))
    if not force and not should_fire(now_syd):
        return 0                      # silent no-op outside the window

    key = week_key(now_syd)
    if not force and key in _load_state():
        return 0                      # already confirmed this week

    try:
        master_grid, ld_grid = _read_grids()
        text = build_message(master_grid, ld_grid, now_syd)
        sheet_ok = True
    except Exception as exc:                    # noqa: BLE001
        # Instructions are the time-critical payload: send them with
        # a warning rather than losing the morning to sheet retries.
        text = INSTRUCTIONS_TEXT + SHEET_DOWN_TEXT
        sheet_ok = False
        _log(f"sheet read failed ({exc.__class__.__name__}) \u2014 "
             "sending instructions without sheet sections", now_syd)

    if not send:
        print(text)
        return 0

    receipt = send_classified(os.getenv("TELEGRAM_CLAW_BOT", ""),
                              TELEGRAM_CHAT_ID, text,
                              thread_id=_topic_id())
    if receipt.get("ok"):
        _log(f"ok week={key} message_id={receipt.get('message_id')} "
             f"thread={_topic_id()} sheet={'ok' if sheet_ok else 'down'}",
             now_syd)
        state = _load_state()
        state[key] = {"sent": True,
                      "message_id": receipt.get("message_id"),
                      "sent_at": now_syd.isoformat(
                          timespec="seconds"),
                      "sheet_ok": sheet_ok}
        _save_state(state)
        return 0
    reason = str(receipt.get("error") or "unknown")
    if receipt.get("error_class") == "permanent":
        # 2026-09-24 user ruling: a real error (bad token, bot
        # kicked, topic gone, text too long) will not heal — STOP
        # retrying, record the reason where --status shows it.
        _log(f"PERMANENT week={key} \u2014 no retry, reason: "
             f"{reason}", now_syd)
        state = _load_state()
        state[key] = {"sent": False, "terminal": True,
                      "error": reason,
                      "failed_at": now_syd.isoformat(
                          timespec="seconds")}
        _save_state(state)
        return 2
    hint = ""
    if receipt.get("retry_after"):
        hint = f" (telegram says retry after " \
               f"{receipt.get('retry_after')}s)"
    _log(f"RETRYABLE week={key} \u2014 {reason}{hint}; hourly cron "
         f"retries until {LAST_HOUR}:59 Sydney", now_syd)
    return 1


def print_status() -> None:
    """Ops view: Sydney clock, window verdict, last sent weeks."""
    from core.sydney_time import sydney_now

    now_syd = sydney_now().astimezone(ZoneInfo(SYDNEY_TZ))
    state = _load_state()
    print(f"[wed-reminder] now={now_syd.isoformat(timespec='seconds')}")
    print(f"[wed-reminder] window: Wednesday "
          f"{FIRST_HOUR}:00-{LAST_HOUR}:59 Sydney, topic "
          f"{_topic_id()}")
    print(f"[wed-reminder] this week ({week_key(now_syd)}): "
          f"{'SENT' if week_key(now_syd) in state else 'pending'}")
    for key in sorted(state)[-3:]:
        entry = state[key]
        if entry.get("terminal"):
            print(f"[wed-reminder] {key}: TERMINAL FAIL \u2014 "
                  f"{entry.get('error')}")
        else:
            print(f"[wed-reminder] {key}: sent={entry.get('sent')} "
                  f"message_id={entry.get('message_id')} "
                  f"sheet_ok={entry.get('sheet_ok')}")
