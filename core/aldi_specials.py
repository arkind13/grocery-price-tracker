"""Aldi Special Buys Wed/Sat 5 AM job (spec §4): date-equality gate,
theme-grouped animated render, topic-206 delivery, idempotent state.

Imports ONLY stdlib + aldi_extractor + telegram_format + sydney_time
(spec §4.1). NEVER touches sheets (verdict V1 extends project-wide).
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_HERE = Path(__file__).resolve().parent
_TRACKER = _HERE.parent
DATA_DIR = _TRACKER / "data"
STATE_PATH = DATA_DIR / "aldi_specials_state.json"

SYDNEY_TZ = "Australia/Sydney"
FIRE_HOUR = 5                      # 05:xx Sydney window (verdict V4)
FIRE_WEEKDAYS = (2, 5)             # Wed, Sat (verdict V3)
MAX_MSG_CHARS = 4000               # pre-checked split cap (V8)

TELEGRAM_CHAT_ID = -1004394070843  # Claw Command Center (mirror const)
SPECIALS_TOPIC_ID = 206            # env override TELEGRAM_SPECIALS_TOPIC_ID

THEME_EMOJI = {
    "grocery specials": "🛒",
    "limited time only meat": "🥩",
    "camping": "⛺",
    "technology and entertainment": "💻",
    "home refresh": "🏠",
    "kitchen essentials": "🍳",
    "nutritional supplements": "💪",
    "health & beauty": "💄",
    "sporting equipment": "🏀",
    "travel": "🧳",
    "oktoberfest": "🍻",
    "garden": "🌿",
}
DEFAULT_THEME_EMOJI = "🏷️"


def _topic_id() -> int:
    try:
        return int(os.getenv("TELEGRAM_SPECIALS_TOPIC_ID", "")
                   or SPECIALS_TOPIC_ID)
    except ValueError:
        return SPECIALS_TOPIC_ID


def _load_state() -> dict:
    """Read the posted-dates state; missing/corrupt = {}."""
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def should_fire(now: datetime | None = None,
                state: dict | None = None) -> tuple[bool, str]:
    """(fire, date_iso) — fire only when Sydney hour == 5, weekday in
    {Wed, Sat}, and today's date is not already posted (V3/V4)."""
    now_syd = (now or datetime.now(ZoneInfo(SYDNEY_TZ))) \
        .astimezone(ZoneInfo(SYDNEY_TZ))
    date_iso = now_syd.date().isoformat()
    state = state if state is not None else _load_state()
    fire = (now_syd.hour == FIRE_HOUR
            and now_syd.weekday() in FIRE_WEEKDAYS
            and date_iso not in state)
    return fire, date_iso


def _theme_of(item) -> str:
    """First category name, else 'Special Buys'."""
    cats = getattr(item, "_theme_categories", None)
    if cats:
        return str(cats[0])
    return "Special Buys"


def _theme_emoji(theme: str) -> str:
    return THEME_EMOJI.get(" ".join(str(theme or "")
                                    .lower().split()),
                           DEFAULT_THEME_EMOJI)


def _entry(n: int, item) -> list[str]:
    """Two-line animated entry (V6): name line + 💵 detail line."""
    detail = f"     💵 ${item.price:.2f}"
    for part in (str(item.size or "").strip(),
                 str(item.brand or "").strip()):
        if part:
            detail += f" · {part}"
    return [f"  {n}. {item.raw_name}", detail]


def render_specials_post(items: list, promo_title: str,
                         date_iso: str) -> list[str]:
    """The whole day's list (V7) as message blocks ≤4000 chars each
    (V8). Block 1 carries the header; every block carries its (i/N)
    suffix; theme groups keep the promotion-tree order."""
    if not items:
        return []
    groups: list[tuple[str, list]] = []
    for item in items:
        theme = _theme_of(item)
        if groups and groups[-1][0] == theme:
            groups[-1][1].append(item)
        else:
            groups.append((theme, [item]))

    d = datetime.fromisoformat(date_iso)          # portable day label
    day = f"{d.strftime('%A')} {d.day} {d.strftime('%B')}"
    lines = [f"🔵 ALDI SPECIAL BUYS — {day} 🛒",
             f"🗓️ {promo_title}"]
    n = 0
    for theme, group in groups:
        lines += ["", f"{_theme_emoji(theme)} {theme.upper()}",
                  "─" * 28]
        for item in group:
            n += 1
            lines += _entry(n, item)
    lines += ["", f"📊 {len(items)} special buys · 🗓️ {date_iso}"]
    return _split_blocks("\n".join(lines))


def _split_blocks(text: str) -> list[str]:
    """Prefer paragraph (blank-line) breaks so a theme group is never
    cut; a paragraph longer than the cap falls back to line
    boundaries. Every block ≤ MAX_MSG_CHARS — the cap ALWAYS holds.
    Suffix ' (i/N)' appended after the split (V8).

    Verified 2026-09-11 against: 4-item golden render, a 120-item
    single-theme drop (all items intact, all blocks ≤ 4000), 500-char
    and 2000-char paragraph stress cases, and the 1/N suffix shape.
    """
    def _pack(lns: list[str]) -> list[str]:
        blocks, cur, cur_len = [], [], 0
        for ln in lns:
            need = len(ln) + (1 if cur else 0)
            if cur and cur_len + need > MAX_MSG_CHARS - 12:
                blocks.append("\n".join(cur))
                cur, cur_len = [], 0
            cur.append(ln)
            cur_len += need
        if cur:
            blocks.append("\n".join(cur))
        return blocks

    out: list[str] = []
    for para in text.split("\n\n"):
        blocks = _pack(para.split("\n"))
        if out and len(out[-1]) + len(blocks[0]) + 2 \
                <= MAX_MSG_CHARS - 12:
            out[-1] = out[-1] + "\n\n" + blocks[0]
            blocks = blocks[1:]
        out.extend(blocks)
    if len(out) > 1:
        out = [f"{b} ({i}/{len(out)})" for i, b in enumerate(out, 1)]
    return out


def render_warning(day_name: str, exc: Exception) -> str:
    """V9: exactly ONE visible line — no stack trace, no silence."""
    return (f"⚠️ ALDI specials unavailable today ({day_name}) "
            f"— will retry next drop ({exc.__class__.__name__})")


def _send_message(bot_token: str, text: str, thread_id: int) -> dict:
    """One sendMessage to the topic; parsed response; never raises
    (mirrors local_deals._send_message discipline, stdlib only)."""
    result = {"ok": False}
    if not bot_token:
        print("[aldi-specials] no bot token — not sent")
        return result
    body = {"chat_id": TELEGRAM_CHAT_ID, "text": text,
            "message_thread_id": thread_id}
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        result["ok"] = bool(data.get("ok"))
        result["message_id"] = (data.get("result") or {}) \
            .get("message_id")
    except Exception as exc:                  # noqa: BLE001
        print(f"[aldi-specials] send failed: "
              f"{exc.__class__.__name__}")
    return result


def _send_photo(bot_token: str, photo_url: str, caption: str,
                thread_id: int) -> dict:
    """Hero image (V6 'pics'): ONE sendPhoto by URL. Non-fatal."""
    result = {"ok": False}
    if not bot_token:
        return result
    body = {"chat_id": TELEGRAM_CHAT_ID, "photo": photo_url,
            "caption": caption, "message_thread_id": thread_id}
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{bot_token}/sendPhoto",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        result["ok"] = bool(data.get("ok"))
    except Exception as exc:                  # noqa: BLE001
        print(f"[aldi-specials] hero photo skipped: "
              f"{exc.__class__.__name__}")
    return result


def _hero_url(items: list) -> str:
    """First item's first asset URL at width 640 ('{width}' template,
    '{slug}' -> 'hero'); '' when the item has no assets."""
    for item in items:
        url = str(getattr(item, "_hero_asset", "") or "")
        if url:
            return url.replace("{width}", "640") \
                      .replace("{slug}", "hero")
    return ""


def run_scan(now: datetime | None = None, force: bool = False,
             date_iso: str | None = None, send: bool = True) -> int:
    """Cron entry (spec §4.2/§4.4/§4.5). Returns exit code.

    force bypasses the hour+weekday gates but NOT the per-date
    idempotence; date_iso overrides 'today' (supervised fires);
    send=False prints blocks instead of posting (dry runs).
    """
    from core.sydney_time import sydney_now
    from extractors.aldi_extractor import (
        AldiAPIError, fetch_aldi_specials, find_promotion)

    now = now or sydney_now()
    if not force:
        fire, today = should_fire(now)
        if not fire:
            return 0                      # silent no-op, V3/V4
    else:
        today = date_iso or now.astimezone(
            ZoneInfo(SYDNEY_TZ)).date().isoformat()
    if date_iso:
        today = date_iso
    if today in _load_state():
        print(f"[aldi-specials] {today} already posted — no-op")
        return 0

    try:
        promo = find_promotion(today)
        if promo is None:
            print(f"[aldi-specials] no Aldi drop on {today}")
            return 0
        items = fetch_aldi_specials(today)
    except AldiAPIError as exc:
        day_name = datetime.fromisoformat(today).strftime("%A")
        warning = render_warning(day_name, exc)
        print(warning)                     # log line always
        if send:
            _send_message(os.getenv("TELEGRAM_CLAW_BOT", ""),
                          warning, _topic_id())
        return 1

    if not items:
        print(f"[aldi-specials] drop {today} has no priced items")
        return 0
    blocks = render_specials_post(items,
                                  str(promo.get("title") or ""),
                                  today)
    if not send:
        for b in blocks:
            print(b)
        return 0

    bot_token = os.getenv("TELEGRAM_CLAW_BOT", "")
    thread = _topic_id()
    hero = _hero_url(items)
    if hero:
        _send_photo(bot_token, hero, blocks[0].split("\n")[0], thread)
    for b in blocks:
        receipt = _send_message(bot_token, b, thread)
        print(f"[aldi-specials] {'ok' if receipt.get('ok') else 'FAIL'}"
              f" message_id={receipt.get('message_id')} "
              f"thread={thread}")
    state = _load_state()
    state[today] = {"posted": True}
    _save_state(state)
    return 0
