"""Deal-post text parsing: validity dates + Fruitopia deal lines.

Pure functions (no network) for the text-first local-deals pipeline
(TODO-local-deals-gaps Tasks 2-3). The grammar is pinned against the
REAL Fruitopia anniversary post (2026-09-04: "📅 Saturday & Sunday,
5 & 6 September" + 24 "Emoji Item – price" lines) and the REAL
undated-board incident post FRU2209260507 (2026-09-22: the text said
"valid for 22nd and 23rd Sep" — ordinal suffix + abbreviated month —
but the parser only knew bare-day + full-month forms, so the sweep
asked the user a question the post had already answered).

All date comparisons use SYDNEY dates — pass ``today=sydney_today()``.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}
# Month words accepted in post text / date replies: full names PLUS
# 3- and 4-letter abbreviations ("Sep", "Sept"). Longest-first so the
# alternation prefers 'september' over 'sept' over 'sep'.
_MONTH_WORDS = sorted(
    set(MONTHS) | {"jan", "feb", "mar", "apr", "jun", "jul", "aug",
                   "sep", "sept", "oct", "nov", "dec"},
    key=len, reverse=True)
_MONTH_RE = "|".join(_MONTH_WORDS)
# Captured month word (full or abbreviated) -> month number; every
# accepted word has a unique 3-letter prefix, so slicing to 3 works.
_MONTH_NUM = {name[:3]: num for name, num in MONTHS.items()}
# "22nd" / "23rd" / "1st" / "2nd" — real boards write ordinal suffixes.
_ORDINAL_RE = r"(?:st|nd|rd|th)?"
# "5 & 6 September" / "22nd and 23rd Sep" / "22nd-23rd Sep" /
# "5-6 September" / "6 September" / "23rd Sep" / "3rd of October"
# (optionally preceded by weekday words — captured as a whole match
# so callers can show the phrase; only day numbers + month matter).
VALIDITY_RE = re.compile(
    rf"\b(\d{{1,2}}){_ORDINAL_RE}\s*(?:&|and|,|-|–|to)\s*"
    rf"(\d{{1,2}}){_ORDINAL_RE}\s+(?:of\s+)?({_MONTH_RE})\b"
    rf"|\b(\d{{1,2}}){_ORDINAL_RE}\s+(?:of\s+)?({_MONTH_RE})\b",
    re.IGNORECASE)

# "Weekend Special" boards (user directive 2026-09-22): a post that
# says "weekend" and shows NO explicit date ends on the coming Sunday
# — the user is never asked for a date the post already implies.
_WEEKEND_RE = re.compile(r"\bweekend\b", re.IGNORECASE)

# "Item – price" / "Item - price" (FB uses the en dash).
DEAL_LINE_RE = re.compile(r"^\s*[^\w&()]*\s*(.+?)\s*[–—-]\s*(.+?)\s*$")
MULTIBUY_RE = re.compile(
    r"^(\d+)\s+for\s+\$(\d+(?:\.\d{1,2})?)$", re.IGNORECASE)
# Caption deal lines (the 2026-09-13 Dunya video post): "Beef Sirloin
# - only $24.99 per kg when you buy the whole slab!" — an "only/just"
# lead-in and a trailing CONDITION ("when you buy the whole slab")
# around an explicit-unit price. The trailing text is accepted ONLY
# when the price carries an explicit unit (per kg / /kg / each / ea)
# and stays short — a bare "$5 off this week" (no unit) must never
# become a deal.
_ONLY_PREFIX_RE = re.compile(r"^(?:only|just)\s+", re.IGNORECASE)
_TRAILING_PUNCT_RE = re.compile(r"[\s!.,;:…\-–—]+$")
_MAX_TERMS_CHARS = 60
_DOLLAR_PRICE_RE = re.compile(
    r"^\$(\d+(?:\.\d{1,2})?)"
    r"\s*(?:(/\s*kg\b|per\s+kg\b)|(?:\b(each|ea)\b))?"
    r"\s*(.*)$", re.IGNORECASE)


def parse_validity_end(text: str, *, today: date) -> date | None:
    """Latest validity date mentioned in a post's text.

    Extracts day-month phrases ("5 & 6 September" -> ends 6 Sep;
    "valid for 22nd and 23rd Sep" -> ends 23 Sep; "23rd Sep" ->
    23 Sep; "3rd of October" -> 3 Oct) — ordinals, abbreviated
    months and an "of" between day and month are all accepted.
    The year is today's Sydney year, rolled forward when that would
    land more than 180 days in the past (posts live ~1 week; this
    only guards a December post read in January).

    "Weekend" boards (user directive 2026-09-22): when the text has
    NO explicit date but says "weekend" (e.g. "Weekend Special"),
    the end date is the coming Sunday (today, when today IS Sunday).
    An explicit date phrase always wins over the weekend rule.

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
        if m.group(1):                      # "22nd and 23rd Sep" shape
            days = [int(m.group(1)), int(m.group(2))]
            month = _MONTH_NUM[m.group(3)[:3].lower()]
        else:                               # "23rd Sep" shape
            days = [int(m.group(4))]
            month = _MONTH_NUM[m.group(5)[:3].lower()]
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
    if end is None and _WEEKEND_RE.search(text or ""):
        end = today + timedelta(days=(6 - today.weekday()) % 7)
    return end


def _parse_price_part(part: str) -> dict | None:
    """Parse the right side of a deal line into a price dict.

    Accepts: "99¢ each" / "99¢/kg" / "99¢" / "$2.99" / "$2.99/kg" /
    "$1.80 each" / "2 for $2.99" — and, since the 2026-09-13 Dunya
    video post, caption forms with a lead-in and a trailing
    CONDITION: "only $24.99 per kg when you buy the whole slab!"
    (optional "only"/"just" prefix; the trailing text is captured as
    "terms" ONLY when the price carries an explicit unit — per kg,
    /kg, each, ea — and stays under _MAX_TERMS_CHARS, so a bare
    "$5 off this week" never becomes a deal).

    Returns:
        dict | None: {"price": float (2dp) — the BUNDLE TOTAL for
        multibuy deals (FIX-3: same convention as the vision schema;
        core.local_deals._cell_for is the ONLY divider), per-unit
        otherwise; "unit_price": display-only per-unit rate
        (multibuy only); "unit": "ea"|"kg", "multibuy": int|None,
        "multibuy_note": str|None, "terms": str|None — the caption
        condition text}, or None when the part holds no parseable
        price.
    """
    part = part.strip().replace("\u00a0", " ")
    part = _ONLY_PREFIX_RE.sub("", part, count=1).strip()
    mb = MULTIBUY_RE.match(part)
    if mb:
        qty = int(mb.group(1))
        bundle = round(float(mb.group(2)), 2)
        return {"price": bundle,
                "unit_price": round(bundle / qty, 2),
                "unit": "ea",
                "multibuy": qty,
                "multibuy_note": f"{qty} for ${bundle:.2f}",
                "terms": None}
    unit_tail = r"(?:\s*(?:/\s*)?(kg|each))?"
    cents = re.match(r"^(\d+(?:\.\d{1,2})?)\s*¢" + unit_tail + r"$",
                     part, re.IGNORECASE)
    if cents:
        unit = (cents.group(2) or "ea").lower()
        return {"price": round(float(cents.group(1)) / 100, 2),
                "unit": "kg" if unit == "kg" else "ea",
                "multibuy": None, "multibuy_note": None,
                "terms": None}
    dol = _DOLLAR_PRICE_RE.match(part)
    if dol:
        price = round(float(dol.group(1)), 2)
        per_kg, each, rest = dol.group(2), dol.group(3), \
            (dol.group(4) or "")
        rest = _TRAILING_PUNCT_RE.sub("", rest).strip()
        if rest and (not (per_kg or each)
                     or len(rest) > _MAX_TERMS_CHARS):
            # trailing words on a unit-less price ("$5 off this
            # week") or a run-on sentence — never a deal
            return None
        return {"price": price,
                "unit": "kg" if per_kg else "ea",
                "multibuy": None, "multibuy_note": None,
                "terms": rest or None}
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
        list[dict]: {"item", "price", "unit_price", "unit",
        "multibuy", "multibuy_note", "raw"} in post order. price is
        the BUNDLE TOTAL for multibuy deals (single divider:
        core.local_deals._cell_for — FIX-3); unit_price is the
        display-only per-unit rate.
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
