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


# --- Pack-guard (open-fix #0, closed 2026-09-27) ---------------------
# The Merjan weekend boards print the MINIMUM-PURCHASE quantity BEFORE
# the item name ("2KG THIGH FILLET $21.99" = $21.99 buys the whole
# 2kg, ~$11.00/kg). The vision model flip-flops BETWEEN RUNS on the
# same image (2026-09-11: 14 of 23 tiles mistyped; 2026-09-27: all 20
# mistyped; a same-day replay: all correct) — a prompt can never pin
# behaviour the model varies on. These regexes re-derive the pack
# semantics from raw_text (the verbatim tile line, which the model
# transcribes reliably) so code, not model mood, owns the maths.
_QTY_KG_PREFIX_RE = re.compile(       # "2KG THIGH FILLET" / "5 kg beef"
    r"^\s*(\d+(?:[.,]\d+)?)\s*kg\b[\s.:\-–—]*",
    re.IGNORECASE | re.MULTILINE)
_QTY_COUNT_PREFIX_RE = re.compile(    # "2 STEAMER CHICKENS" (counted)
    r"^\s*(\d{1,2})\s+(?=[a-z(])", re.IGNORECASE | re.MULTILINE)
_MIN_WEIGHT_RE = re.compile(          # "min 2kg" / "MINIMUM 1.9 KG"
    r"\bmin(?:imum)?\s*[.:]?\s*(\d+(?:[.,]\d+)?)\s*kg\b", re.IGNORECASE)
_KG_FOR_PRICE_RE = re.compile(        # "3kg for $32.99"
    r"\b(\d+(?:[.,]\d+)?)\s*kg\s+(?:for|@)\s*\$", re.IGNORECASE)
_COUNT_FOR_PRICE_RE = re.compile(     # "5 for $34.99" (counted birds)
    r"\b(\d{1,2})\s+for\s+\$", re.IGNORECASE)
_PER_KG_MARKER_RE = re.compile(       # explicit rate marker on the line
    r"per\s*kg|/\s*kg", re.IGNORECASE)
_UNIT_WORDS_RE = re.compile(r"^(?:kg|kgs|g|gram|grams|ml|l|litre|ea|each"
                            r"|pack|packs|box|bucket|tray)s?\b$",
                            re.IGNORECASE)
# Fractional-weight bundles ("1.9kg for $X") become bulk_pack (schema
# demands an integer >= 2 for multibuy_qty); "min" weights on /ea items
# are bird-size SPECS ("Whole Chicken min 1.9kg"), never bundles.


def _as_number(txt: str) -> float | None:
    try:
        return float(txt.replace(",", "."))
    except ValueError:
        return None


def _strip_qty_prefix(name: str) -> str:
    """Remove a quantity prefix ("2KG THIGH FILLET" -> "THIGH FILLET";
    "2 STEAMER CHICKENS" -> "STEAMER CHICKENS") so row reuse lands on
    the plain /kg row (ID-1: the rate + terms belong THERE)."""
    name = _QTY_KG_PREFIX_RE.sub("", name, count=1)
    name = _QTY_COUNT_PREFIX_RE.sub("", name, count=1)
    return name.strip()


def normalise_pack_deal(deal: dict) -> dict:
    """Re-derive pack semantics for ONE vision-schema deal (in place).

    Only touches price_kind == "single" deals whose line carries a
    quantity the classify step may have dropped. Precedence:
      1. an explicit per-kg marker ("$24.99 per kg", "/kg") — the
         price IS the rate; never touched.
      2. a LEADING weight ("2KG THIGH FILLET $21.99") or "Nkg for $X"
         anywhere — always a bundle: integer qty >= 2 -> multibuy
         (qty, bundle total, unit kg); fractional -> bulk_pack
         ("1.9kg") so the per-kg rate stays derivable.
      3. unit kg + any other weight token ("min 2kg") — bundle too
         (the vision prompt's own "min 2kg" rule).
      4. unit ea: "min N.Nkg" ("Whole Chicken min 1.9kg") is a
         bird-SIZE spec — stays single/ea, weight rides `notes`;
         a leading COUNT ("2 STEAMER CHICKENS $11.99") is a counted
         bundle -> multibuy (qty, bundle total, unit ea).

    Returns the (possibly mutated) deal. Pure text maths — no network.
    """
    if deal.get("price_kind") != "single":
        return deal
    raw_text = str(deal.get("raw_text") or "").strip()
    raw = f"{raw_text} {deal.get('item') or ''}"
    if _PER_KG_MARKER_RE.search(raw):
        return deal              # the line itself says the price is /kg
    unit = (deal.get("unit") or "").lower()
    price = deal.get("price")
    min_m = _MIN_WEIGHT_RE.search(raw)
    # Prefix quantities anchor to the VERBATIM tile text only — the
    # model's item field may legitimately start with a number that is
    # part of the product name ("4 Star Beef"), never a bundle count.
    m = (_QTY_KG_PREFIX_RE.search(raw_text)
         or _KG_FOR_PRICE_RE.search(raw))
    if not m and min_m and unit != "ea":
        # "min Nkg" on weighted meat — same bundle semantics
        m = min_m
    if m and isinstance(price, (int, float)) and price > 0:
        qty = _as_number(m.group(1))
        if qty and qty > 0:
            deal["item"] = _strip_qty_prefix(
                str(deal.get("item") or "")).strip() or deal["item"]
            deal["unit"] = "kg"
            if qty >= 2 and float(qty).is_integer():
                deal["price_kind"] = "multibuy"
                deal["multibuy_qty"] = int(qty)
                deal["bulk_size"] = None
            else:
                deal["price_kind"] = "bulk_pack"
                deal["bulk_size"] = f"{qty:g}kg"
                deal["multibuy_qty"] = None
            return deal
    if min_m and unit == "ea":
        # bird-size spec — keep per-ea, surface the weight
        note = f"min {min_m.group(1)}kg"
        deal["notes"] = (f"{deal['notes']} · {note}"
                         if deal.get("notes") else note)
        return deal
    # counted-bundle prefix on an /ea deal ("2 STEAMER CHICKENS") —
    # anchored to the verbatim tile text (see the note above) and the
    # word after the count must be a PLURAL ("CHICKENS"); a bare
    # number + word at line start can be part of the product name
    # ("4 STAR BEEF" — a grade, never "4 for $30")
    cm = _QTY_COUNT_PREFIX_RE.search(raw_text)
    if cm and unit == "ea" and not _UNIT_WORDS_RE.match(
            str(deal.get("item") or "").strip()):
        # name words between the count and the price; a counted
        # bundle names a PLURAL ("2 STEAMER CHICKENS"), a numbered
        # product name does not ("4 STAR BEEF" — a grade)
        name_part = re.split(r"[$–—-]", raw_text[cm.end():])[0]
        name_words = [w for w in name_part.split()
                      if not _UNIT_WORDS_RE.match(w)]
        plural = any(len(w) > 2 and w.lower().endswith("s")
                     for w in name_words)
        qty = _as_number(cm.group(1))
        if plural and qty and 2 <= qty <= 20 and float(qty).is_integer():
            deal["item"] = _strip_qty_prefix(
                str(deal.get("item") or "")).strip() or deal["item"]
            if isinstance(price, (int, float)) and price > 0:
                deal["price_kind"] = "multibuy"
                deal["multibuy_qty"] = int(qty)
        return deal
    fm = _COUNT_FOR_PRICE_RE.search(raw_text)
    if fm and unit == "ea":
        qty = _as_number(fm.group(1))
        if qty and 2 <= qty <= 20 and float(qty).is_integer():
            deal["price_kind"] = "multibuy"
            deal["multibuy_qty"] = int(qty)
    return deal


def normalise_pack_deals(deals: list) -> list:
    """normalise_pack_deal over a deal list (the vision payload or the
    text-parser conversion) — the ONE pack-guard entry both ingestion
    paths share (image boards AND text posts)."""
    for d in deals or []:
        normalise_pack_deal(d)
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
