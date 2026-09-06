"""Deal-post text parsing: validity dates + Fruitopia deal lines.

Pure functions (no network) for the text-first local-deals pipeline
(TODO-local-deals-gaps Tasks 2-3). The grammar is pinned against the
REAL Fruitopia anniversary post (2026-09-04: "📅 Saturday & Sunday,
5 & 6 September" + 24 "Emoji Item – price" lines).

All date comparisons use SYDNEY dates — pass ``today=sydney_today()``.
"""
from __future__ import annotations

import re
from datetime import date

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}
_MONTH_RE = "|".join(MONTHS)
# "5 & 6 September" / "5-6 September" / "6 September"
# (optionally preceded by weekday words — captured as a whole match
# so callers can show the phrase; only day numbers + month matter).
VALIDITY_RE = re.compile(
    rf"\b(\d{{1,2}})\s*(?:&|and|-|–|to)\s*(\d{{1,2}})\s+({_MONTH_RE})"
    rf"\b|\b(\d{{1,2}})\s+({_MONTH_RE})\b", re.IGNORECASE)

# "Item – price" / "Item - price" (FB uses the en dash).
DEAL_LINE_RE = re.compile(r"^\s*[^\w&()]*\s*(.+?)\s*[–—-]\s*(.+?)\s*$")
MULTIBUY_RE = re.compile(
    r"^(\d+)\s+for\s+\$(\d+(?:\.\d{1,2})?)$", re.IGNORECASE)


def parse_validity_end(text: str, *, today: date) -> date | None:
    """Latest validity date mentioned in a post's text.

    Extracts day-month phrases ("5 & 6 September" -> ends 6 Sep);
    the year is today's Sydney year, rolled forward when that would
    land more than 180 days in the past (posts live ~1 week; this
    only guards a December post read in January).

    Args:
        text: the decoded post text (may be "").
        today: Sydney date used for year inference and comparisons.

    Returns:
        date | None: the end (latest) validity date, or None when the
        text carries NO date — the caller must treat that as
        "needs date review", never silently include.
    """
    end: date | None = None
    for m in VALIDITY_RE.finditer(text or ""):
        if m.group(1):                      # "5 & 6 September" shape
            days = [int(m.group(1)), int(m.group(2))]
            month = MONTHS[m.group(3).lower()]
        else:                               # "6 September" shape
            days = [int(m.group(4))]
            month = MONTHS[m.group(5).lower()]
        for day in days:
            try:
                candidate = date(today.year, month, day)
            except ValueError:              # impossible day number
                continue
            if candidate < today and (today - candidate).days > 180:
                # Rollover: "6 September" read on 7 Jan means 2027.
                try:
                    candidate = date(today.year + 1, month, day)
                except ValueError:
                    continue
            if end is None or candidate > end:
                end = candidate
    return end


def _parse_price_part(part: str) -> dict | None:
    """Parse the right side of a deal line into a price dict.

    Accepts: "99¢ each" / "99¢/kg" / "99¢" / "$2.99" / "$2.99/kg" /
    "$1.80 each" / "2 for $2.99".

    Returns:
        dict | None: {"price": per-unit float (2dp), "unit": "ea"|
        "kg", "multibuy": int|None, "multibuy_note": str|None},
        or None when the part holds no parseable price.
    """
    part = part.strip().replace("\u00a0", " ")
    mb = MULTIBUY_RE.match(part)
    if mb:
        qty = int(mb.group(1))
        bundle = round(float(mb.group(2)), 2)
        return {"price": round(bundle / qty, 2), "unit": "ea",
                "multibuy": qty,
                "multibuy_note": f"{qty} for ${bundle:.2f}"}
    unit_tail = r"(?:\s*(?:/\s*)?(kg|each))?"
    cents = re.match(r"^(\d+(?:\.\d{1,2})?)\s*¢" + unit_tail + r"$",
                     part, re.IGNORECASE)
    if cents:
        unit = (cents.group(2) or "ea").lower()
        return {"price": round(float(cents.group(1)) / 100, 2),
                "unit": "kg" if unit == "kg" else "ea",
                "multibuy": None, "multibuy_note": None}
    dol = re.match(r"^\$(\d+(?:\.\d{1,2})?)" + unit_tail + r"$",
                   part, re.IGNORECASE)
    if dol:
        unit = (dol.group(2) or "ea").lower()
        return {"price": round(float(dol.group(1)), 2),
                "unit": "kg" if unit == "kg" else "ea",
                "multibuy": None, "multibuy_note": None}
    return None


def parse_fruitopia_deals(text: str) -> list[dict]:
    """Parse deal lines from a Fruitopia (or similar) post text.

    Line grammar (pinned on the 2026-09-04 anniversary post):
    "Emoji Item Name – PRICE" with PRICE one of the forms accepted
    by _parse_price_part. Lines without an en-dash price part
    (titles, promos, hashtags) are skipped.

    Args:
        text: the decoded post text.

    Returns:
        list[dict]: {"item", "price", "unit", "multibuy",
        "multibuy_note", "raw"} in post order. Price is per-unit
        (multibuy bundles are divided out and carried in the note).
    """
    deals: list[dict] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = DEAL_LINE_RE.match(line)
        if not m:
            continue
        name = re.sub(r"^[^\w&()]+", "", m.group(1)).strip()
        if not name:
            continue
        price = _parse_price_part(m.group(2))
        if price is None:
            continue
        deals.append({"item": name, **price, "raw": line})
    return deals


def filter_recent_posts(posts: list, *, today: date, keep: int = 3,
                        ) -> tuple[list, list, list]:
    """The user's standing rule (TODO Task 2): last N posts, and of
    those only posts whose validity date is in the future (Sydney).

    Args:
        posts: TimelinePost-like objects, NEWEST FIRST (timeline
            order), each with .text.
        today: Sydney date.
        keep: how many recent posts are in scope (default 3).

    Returns:
        tuple: (kept, expired, needs_review) —
          kept: posts with validity end >= today, as
                (post, end_date) pairs;
          expired: (post, end_date) pairs with end < today;
          needs_review: posts with NO date in the text (the user is
                asked — never silently included).
    """
    kept, expired, needs_review = [], [], []
    for post in posts[:keep]:
        end = parse_validity_end(post.text, today=today)
        if end is None:
            needs_review.append(post)
        elif end >= today:
            kept.append((post, end))
        else:
            expired.append((post, end))
    return kept, expired, needs_review
