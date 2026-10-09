"""Deal Board feed writers — derived sheet tabs the /shopping/board
site reads live (2026-10-09 pattern).

- ALDI_Specials_Feed: written by the aldi-specials cron at fetch time
  (core/aldi_specials.run_scan delegates here so THAT module keeps
  zero sheet code — verdict V1, enforced by test_no_sheet_imports).
- WW_Specials_Feed: the Woolworths twin lives in core/v2_wednesday.py
  (the Wednesday run is already a sheet-writing job).

Layout (A..L): Deal | Price | Size | Brand | UnitPrice | Terms |
Theme | Drop_Date | Ends_Date | Promo_Title | Image_URL | Category
(the GLM categorisation — core.board_llm — blank on any failure, the
app then falls back to the raw Theme). Full rewrite per drop —
derived data, safe to regenerate any time.
"""
from __future__ import annotations

from datetime import date, timedelta

ALDI_FEED_TAB = "ALDI_Specials_Feed"
ALDI_FEED_HEADER = ["Deal", "Price", "Size", "Brand", "UnitPrice",
                    "Terms", "Theme", "Drop_Date", "Ends_Date",
                    "Promo_Title", "Image_URL", "Category"]

# ALDI product photos live on their public Scene7 CDN — the board
# hotlinks them straight from the item's asset URL template ({width}
# and {slug} placeholders). NOTHING is stored on the VPS, so there is
# nothing to clean up when the drop ends (the feed row itself is
# replaced by the next drop).
ALDI_IMG_WIDTH = 640


def aldi_image_url(item) -> str:
    """Resolved CDN URL ('' when the item has no assets): {width}->640,
    {slug}->'hero' (Scene7 ignores the slug segment)."""
    raw = str(getattr(item, "_hero_asset", "") or "").strip()
    if not raw:
        return ""
    return (raw.replace("{width}", str(ALDI_IMG_WIDTH))
               .replace("{slug}", "hero"))


def next_drop_after(promos: list, date_iso: str) -> str | None:
    """Earliest promotion key strictly AFTER date_iso (ISO) or None."""
    later = [str(p.get("key") or "") for p in promos
             if str(p.get("key") or "") > date_iso]
    return min(later) if later else None


def drop_end_date(promos: list, drop_iso: str) -> str:
    """A drop runs until the next drop: the day before the next
    promotion's key; when no later promotion is listed, +6 days."""
    nxt = next_drop_after(promos, drop_iso)
    base = date.fromisoformat(drop_iso)
    if nxt:
        return (date.fromisoformat(nxt) - timedelta(days=1)).isoformat()
    return (base + timedelta(days=6)).isoformat()


def build_aldi_feed_rows(items: list, promo_title: str, drop_iso: str,
                         ends_iso: str | None,
                         categories: list | None = None) -> list[list]:
    """Pure items -> feed rows (offline-testable). Theme = the item's
    first promotion-tree category (raw ALDI); Category (col L) = the
    GLM categorisation when available (core.board_llm), blank on any
    failure — the app prefers col L and falls back to the theme."""
    def _s(item, attr) -> str:
        return str(getattr(item, attr, "") or "").strip()

    rows: list[list] = []
    cats = list(categories or [])
    for i, item in enumerate(items):
        price = getattr(item, "price", None)
        # same default as the Telegram render's _theme_of (many search
        # items carry no categories — 47 of the real 84 on 2026-10-07)
        theme = (getattr(item, "_theme_categories", None) or [""])[0] \
            or "Special Buys"
        llm_cat = cats[i] if i < len(cats) and cats[i] else ""
        rows.append([
            _s(item, "raw_name"),
            f"{price:.2f}" if price is not None else "",
            _s(item, "size"),
            _s(item, "brand"),
            _s(item, "unit_price"),
            _s(item, "special_desc"),
            str(theme),
            drop_iso,
            ends_iso or "",
            promo_title,
            aldi_image_url(item),
            llm_cat,
        ])
    return rows


def write_aldi_feed(items: list, promo: dict, today: str) -> int:
    """(Re)write the ALDI_Specials_Feed tab: header + one row per item.
    Never raises into the caller's Telegram flow — returns the row
    count, or -1 on failure (logged by the caller)."""
    from extractors.aldi_extractor import fetch_promotion_tree

    promos = fetch_promotion_tree()
    ends_iso = drop_end_date(promos, today)
    # one GLM call per drop (glm-5.3-flash, z.ai coding plan — free);
    # silent fallback to raw themes on any failure, never blocks
    try:
        from core.board_llm import categorize
        cats = categorize(items)
        print(f"[board-feed] llm categories: "
              f"{sum(1 for c in cats if c)}/{len(items)}")
    except Exception as exc:          # noqa: BLE001
        cats = []
        print(f"[board-feed] llm categories skipped: {exc}")
    rows = build_aldi_feed_rows(
        items, str(promo.get("title") or ""), today, ends_iso, cats)
    try:
        from core.sheets_client import connect_spreadsheet
        ss = connect_spreadsheet()
    except Exception as exc:
        print(f"[board-feed] sheet connect failed: {exc}")
        return -1
    try:
        ws = ss.worksheet(ALDI_FEED_TAB)
    except Exception:
        ws = ss.add_worksheet(title=ALDI_FEED_TAB,
                              rows=max(60, len(rows) + 1), cols=12)
    values = [ALDI_FEED_HEADER] + rows
    ws.clear()
    ws.update(values=values, range_name=f"A1:L{len(values)}")
    return len(rows)
