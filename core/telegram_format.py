#!/usr/bin/env python3
"""Telegram Style Kit — shared message formatting for all Claw skills.

Display-only formatting helpers (spec §2–§3 of "Unified Telegram Message
Formatting"). Every message follows the same skeleton:

    <ICON> <TITLE IN CAPS>
    ━━━━━━━━━━━━━━━━━━━━
    <body: list-style items and/or a fenced monospace block>
    <TAIL: 🏆 result line, ⚠️ warnings>
    ⏱️ <optional timestamp footer>

Golden rule: NO markdown pipe tables (`| col |` + `|---|`) — Telegram
cannot render them. Use list-style item blocks and/or ```-fenced
monospace blocks (manual padding aligns in Telegram's monospace font).

Zero-dependency styling: structure comes from unicode (heavy `━` divider
under main headers, light `─` divider for sub-blocks, `·` inline
separator, CAPS header words), so the layout survives even when the
gateway strips all markdown. No parse_mode is ever required — every
string returned is plain text.

Icon vocabulary (spec §2.3):

    🛒 grocery / basket      🔍 search / lookup
    🏷️ specials / discounts  💰 money / savings
    🏆 cheapest / winner     🏠 Woolworths home brand
    ⚠️ warning               ✅ success / confirmed
    ❌ not available / failed 🟢 Woolworths
    🔴 Coles                 📊 totals / report block
    🧾 recipe                🔄 sync
    🤖 model / LLM pricing   📅 daily digest
    ⏱️ timestamp footer      📋 list / inventory summary

Emoji density is moderate: headers and store lines only, not every line.

This module is stdlib-only and imports nothing from sibling modules (no
import cycles). Width math treats emoji as 2 terminal cells via
``_cells()``.
"""
from __future__ import annotations

import unicodedata
from datetime import datetime

# Width budgets (spec §3): product-name column and fenced-block total.
MAX_NAME_WIDTH = 24
MAX_BLOCK_WIDTH = 34

# Divider vocabulary (spec §2.2).
HEAVY_DIVIDER = "━"
LIGHT_DIVIDER = "─"
HEAVY_DIVIDER_WIDTH = 20
LIGHT_DIVIDER_WIDTH = 10

# Inline separator.
SEP = "·"

# Em dash / minus / ellipsis used across outputs (importable by callers).
EM_DASH = "\u2014"
MINUS = "\u2212"
ELLIPSIS = "\u2026"

# Canonical store icons (user-approved spec §9).
STORE_ICONS = {"woolworths": "🟢", "coles": "🔴"}
# Label column width inside store lines: len("Woolworths").
_STORE_LABEL_WIDTH = 10

# Codepoints that join/variant the previous glyph and occupy no cell.
_ZERO_WIDTH = frozenset({0x200D, 0xFE0E, 0xFE0F})


# ============================================================================
# Width math
# ============================================================================


def _cells(s: str) -> int:
    """Count the visible terminal cells of a string.

    Emoji and other wide glyphs count as 2 cells; variation selectors
    (U+FE0E/U+FE0F) and zero-width joiners count as 0; everything else
    counts as 1.

    Args:
        s: the string to measure (None-safe: treated as "").

    Returns:
        int: visible cell width.
    """
    total = 0
    for ch in str(s or ""):
        cp = ord(ch)
        if cp in _ZERO_WIDTH:
            continue
        if cp >= 0x1F000 or unicodedata.east_asian_width(ch) in ("W", "F"):
            total += 2
        else:
            total += 1
    return total


def truncate(s: str, width: int) -> str:
    """Truncate a string to a visible cell budget with an ellipsis.

    Args:
        s: input string.
        width: maximum visible cells the result may occupy.

    Returns:
        str: ``s`` unchanged when it fits; otherwise a prefix followed by
        "…" whose total cell width is <= ``width`` (character ``len()`` is
        therefore also <= ``width``).
    """
    text = str(s or "")
    if width < 1:
        return ""
    if _cells(text) <= width:
        return text
    prefix = ""
    for ch in text:
        if _cells(prefix) + _cells(ch) + _cells(ELLIPSIS) > width:
            break
        prefix += ch
    return prefix + ELLIPSIS


# ============================================================================
# Skeleton pieces
# ============================================================================


def divider(char: str = LIGHT_DIVIDER, width: int = LIGHT_DIVIDER_WIDTH) -> str:
    """Return a raw divider line (default: light `─` x10).

    Args:
        char: the divider glyph.
        width: repeat count.

    Returns:
        str: ``char`` repeated ``width`` times.
    """
    return char * max(0, width)


def header(title: str, icon: str) -> str:
    """Build a main header: `<ICON> <TITLE>` + heavy divider line.

    Args:
        title: header text (uppercased by this function).
        icon: leading icon glyph from the shared vocabulary.

    Returns:
        str: two lines — title line, then `━` x20.
    """
    return f"{icon} {title.upper()}\n{divider(HEAVY_DIVIDER, HEAVY_DIVIDER_WIDTH)}"


def subheader(title: str, icon: str | None = None) -> str:
    """Build a sub-block label: light divider line + optional-icon label.

    Args:
        title: sub-block label (rendered as given; callers pass CAPS).
        icon: optional leading icon glyph.

    Returns:
        str: two lines — `─` x10, then the label line.
    """
    label = f"{icon} {title}" if icon else title
    return f"{divider(LIGHT_DIVIDER, LIGHT_DIVIDER_WIDTH)}\n{label}"


def kv(label: str, value: str) -> str:
    """Join a label and value with the `·` inline separator.

    Args:
        label: left-hand label.
        value: right-hand value.

    Returns:
        str: "label · value".
    """
    return f"{label} {SEP} {value}"


# Canonical Col C marker for "unit assessed, unknown" (architecture-spec
# §2 — the user's own words, exact lowercase phrase). Blank Col C means
# "legacy, not yet assessed"; both DISPLAY identically via unit_tag().
UNIT_UNAVAILABLE = "unit unavailable"


def unit_tag(size: str | None) -> str:
    """Return the display text for a package size (Rule A, spec §2).

    Args:
        size: raw size string (Col C value, live listing size, or a
            queue entry's "size" key). None-safe.

    Returns:
        str: the trimmed size when one is known; else the canonical
        marker "unit unavailable". Blank, whitespace-only, and the
        marker itself (any case) all map to the marker.
    """
    text = str(size or "").strip()
    if not text or text.lower() == UNIT_UNAVAILABLE:
        return UNIT_UNAVAILABLE
    return text


def unit_suffix(size: str | None) -> str:
    """Return the inline unit segment for a product-mention line.

    Single composition over unit_tag (DRY — one source for the marker).

    Args:
        size: raw size string (None-safe).

    Returns:
        str: " · 1L" for a known size; " · ⚠️ unit unavailable" for an
        unknown one (spec §3 formatting rule — silent omission banned).
    """
    if unit_tag(size) == UNIT_UNAVAILABLE:
        return f" {SEP} ⚠️ {UNIT_UNAVAILABLE}"
    return f" {SEP} {unit_tag(size)}"


def money(n) -> str:
    """Format a dollar amount for display.

    Args:
        n: numeric amount, or None for "no value".

    Returns:
        str: "$4.00" for 4.0, "$0.00" for 0, "—" for None, and
        "−$x.xx" (U+2212 minus) for negative amounts.
    """
    if n is None:
        return EM_DASH
    value = float(n)
    if value < 0:
        return f"{MINUS}${abs(value):.2f}"
    return f"${value:.2f}"


def warn(text: str) -> str:
    """Prefix a warning line with ⚠️."""
    return f"⚠️ {text}"


def ok(text: str) -> str:
    """Prefix a success line with ✅."""
    return f"✅ {text}"


def fail(text: str) -> str:
    """Prefix a failure / unavailable line with ❌."""
    return f"❌ {text}"


def tail(winner: str, savings: float, vs: str | None = None) -> str:
    """Build the 🏆 cheapest-store tail line.

    Args:
        winner: winning store display name.
        savings: dollars saved vs the most expensive store.
        vs: optional competitor store name.

    Returns:
        str: "🏆 Cheapest: Woolworths — you save $2.35" and,
        when ``vs`` is given, a trailing " (vs Coles)".
    """
    line = f"🏆 Cheapest: {winner} {EM_DASH} you save {money(savings)}"
    if vs:
        line += f" (vs {vs})"
    return line


def footer(ts=None) -> str:
    """Build the ⏱️ timestamp footer line.

    Args:
        ts: optional datetime (defaults to now).

    Returns:
        str: "⏱️ YYYY-MM-DD HH:MM".
    """
    moment = ts if ts is not None else datetime.now()
    return f"⏱️ {moment.strftime('%Y-%m-%d %H:%M')}"


# ============================================================================
# Store / item blocks (list style)
# ============================================================================


def store_line(store: str, price: str, was: str | None = None) -> str:
    """Build one store price line with aligned price column.

    Known stores get their brand icon (🟢 Woolworths / 🔴 Coles); the
    store label is padded so the price starts at the same cell offset
    across stores (emoji counted as 2 cells). Unknown stores render
    without an icon, label as given.

    Args:
        store: store id or display name ("woolworths"/"coles"
            case-insensitive).
        price: pre-rendered price string (e.g. "$2.47" or a
            format_discounted_price() string).
        was: optional GENUINE pre-special price string (from a store
            WasPrice); renders " (was $x)". Never use this for the
            always-on Woolworths team discount.

    Returns:
        str: e.g. "🟢 Woolworths  $2.47 (was $2.90)".
    """
    key = (store or "").strip().lower()
    if key in STORE_ICONS:
        icon = STORE_ICONS[key]
        label = key.capitalize()
    else:
        icon = ""
        label = str(store or "")
    pad = max(0, _STORE_LABEL_WIDTH - _cells(label))
    name_part = label + " " * pad
    prefix = f"{icon} {name_part}" if icon else name_part
    line = f"{prefix}  {price}"
    if was:
        line += f" (was {was})"
    return line


def item_block(
    index: int,
    name: str,
    prices: list[str],
    home_brand: bool = False,
    unit: str | None = None,
) -> str:
    """Build one numbered list-style item with indented store lines.

    Args:
        index: 1-based item number.
        name: product name (truncated to MAX_NAME_WIDTH cells).
        prices: pre-rendered store_line() strings, one per store.
        home_brand: append the 🏠 Woolworths home-brand marker.
        unit: package size for the unit tag (Rule A, spec A3/D-U2).
            None = caller manages units elsewhere (NO segment appended);
            any string — including "" — appends unit_suffix(unit) AFTER
            truncation so the tag is never cut off.

    Returns:
        str: multi-line block, e.g.
        "2. Full Cream Milk 2L  🏠 · 1L\\n   🟢 Woolworths  $3.32".
    """
    title = truncate(str(name or ""), MAX_NAME_WIDTH)
    first = f"{index}. {title}"
    if home_brand:
        first += "  🏠"
    if unit is not None:
        first += unit_suffix(unit)
    lines = [first]
    for price_line in prices:
        lines.append(f"   {price_line}")
    return "\n".join(lines)


# ============================================================================
# Fenced monospace table
# ============================================================================


def _is_money(cell: str) -> bool:
    """True when a cell looks like a money/dash value (right-align hint).

    Args:
        cell: cell text.

    Returns:
        bool: True for "—", "$x", "−$x" style values.
    """
    text = cell.strip()
    return (
        text == EM_DASH
        or text.startswith("$")
        or text.startswith(MINUS + "$")
    )


def fenced_table(
    headers: list[str],
    rows: list[list[str]],
    box: bool = False,
) -> str:
    """Render a padded table inside a triple-backtick fence.

    Every content line is padded to the SAME visible cell width, so the
    block aligns in Telegram's monospace font. Text columns are left
    aligned; money columns ("$x", "−$x", "—") are right aligned. Columns
    are shrunk (cells truncated with "…") until the total visible width
    fits MAX_BLOCK_WIDTH.

    Args:
        headers: column header strings (must be non-empty).
        rows: data rows; short rows are padded, long rows truncated to
            the header count.
        box: draw ╔═╗/║/╚╝ borders around the content (used by the
            compare TOTALS block).

    Returns:
        str: fenced block; with ``box=True`` the border lines have the
        same character length as the content lines.

    Raises:
        ValueError: when ``headers`` is empty (fail fast).
    """
    if not headers:
        raise ValueError("fenced_table requires at least one header column")

    ncols = len(headers)
    norm_rows: list[list[str]] = []
    for row in rows:
        cells = ["" if c is None else str(c) for c in list(row)[:ncols]]
        cells += [""] * (ncols - len(cells))
        norm_rows.append(cells)

    # Column-major grid with the header as row 0.
    grid = [[str(h) for h in headers]]
    grid.extend(norm_rows)

    # Right-align a column when EVERY data cell (not the header) is
    # money-shaped.
    right_align: list[bool] = []
    for c in range(ncols):
        data = [r[c] for r in norm_rows if r[c].strip()]
        right_align.append(bool(data) and all(_is_money(d) for d in data))

    # Natural widths, then shrink the widest column until the total fits.
    widths = [
        max(_cells(row[c]) for row in grid) for c in range(ncols)
    ]

    def _budget_used() -> int:
        return sum(widths) + max(0, ncols - 1)

    while _budget_used() > MAX_BLOCK_WIDTH and max(widths) > 1:
        widest = widths.index(max(widths))
        widths[widest] -= 1

    def _fit(cell: str, width: int, right: bool) -> str:
        fitted = truncate(cell, width)
        deficit = width - _cells(fitted)
        if deficit <= 0:
            return fitted
        pad = " " * deficit
        return pad + fitted if right else fitted + pad

    content_lines = []
    for row in grid:
        parts = [
            _fit(row[c], widths[c], right_align[c]) for c in range(ncols)
        ]
        content_lines.append(" ".join(parts))

    fence = "```"
    if box:
        inner = _cells(content_lines[0]) + 2  # one space padding each side
        top = "╔" + "═" * inner + "╗"
        bottom = "╚" + "═" * inner + "╝"
        body = ["║ " + line + " ║" for line in content_lines]
        return fence + "\n" + "\n".join([top] + body + [bottom]) + "\n" + fence
    return fence + "\n" + "\n".join(content_lines) + "\n" + fence
