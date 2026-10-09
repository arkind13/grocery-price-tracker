"""LLM categorisation for the ALDI deal-board feed (2026-10-09, user
ask: "when aldi list comes can you pass it through a llm (z.ai coding
plan GLM-5.3 Flash) to sort all the things into categories").

ONE glm-5.3-flash call per drop, via the z.ai CODING endpoint — FREE on
the user's coding plan (the same model live search uses; never
OpenRouter per the standing GLM-routing rule). The fixed category
vocabulary keeps the board's taxonomy stable; ALDI's own promotion-tree
theme rides along as a hint. ANY failure (no key, timeout, bad parse)
falls back silently to the raw theme — the LLM never blocks the feed.

Env (os.environ or the sibling .env files — same resolution as
board_feed): ZAI_API_KEY + optional ZAI_BASE_URL.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path

DEFAULT_BASE = "https://api.z.ai/api/coding/paas/v4"
MODEL = "glm-5.3-flash"

# Fixed board taxonomy (keep short + grocery/special-buys practical;
# the board's rail tree builds itself from whatever lands in the tab)
CATEGORIES = [
    "Meat & Seafood", "Dairy & Chilled", "Fresh Produce", "Bakery",
    "Pantry & Grocery", "Snacks & Sweets", "Drinks", "Frozen",
    "Household & Cleaning", "Personal Care", "Health & Wellness",
    "Baby & Kids", "Pet", "Clothing & Footwear", "Home & Kitchen",
    "Tools & DIY", "Garden & Outdoor", "Electronics", "Toys & Hobbies",
    "Sports & Leisure", "Auto", "Christmas & Seasonal", "Other",
]

SYSTEM = (
    "You sort ALDI Australia Special Buys items into shopping "
    "categories. For EVERY numbered item reply EXACTLY one line: "
    "'<number>. <category>' where <category> is one of: "
    + ", ".join(CATEGORIES) + ". "
    "Choose by what the product IS (brand and size help; the aldi_theme "
    "hint is usually right when present — but a 'Grocery Specials' or "
    "blank theme means YOU decide). No other text, no markdown, one "
    "line per item, same order as the input."
)


def _env_or_file(name: str) -> str | None:
    val = os.getenv(name)
    if val:
        return val
    here = Path(__file__).resolve().parent
    for env_path in (here.parent / ".env", here.parent.parent / ".env"):
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"')
        except OSError:
            continue
    return None


def parse_categories(text: str, n: int) -> list[str | None]:
    """Model reply -> per-index category (None where unknown/missing).
    Lenient: accepts '1. Cat', '1) Cat', stray bullets, blank lines."""
    lookup = {c.lower(): c for c in CATEGORIES}
    out: list[str | None] = [None] * n
    for line in str(text or "").splitlines():
        m = re.match(r"^\s*(?:[-•*]\s*)?(\d{1,3})\s*[.)]\s*(.+?)\s*$", line)
        if not m:
            continue
        idx = int(m.group(1)) - 1
        cat = lookup.get(m.group(2).strip().lower())
        if 0 <= idx < n:
            out[idx] = cat          # unknown category text -> None
    return out


def categorize(items: list, timeout: float = 30.0) -> list[str | None]:
    """One GLM call for the whole drop; aligned-by-index categories.
    Returns [] on ANY failure (caller falls back to raw themes)."""
    key = _env_or_file("ZAI_API_KEY")
    if not key:
        return []
    base = (_env_or_file("ZAI_BASE_URL") or DEFAULT_BASE).rstrip("/")

    def _s(item, attr) -> str:
        return str(getattr(item, attr, "") or "").strip()

    lines = []
    for i, it in enumerate(items, 1):
        theme = (getattr(it, "_theme_categories", None) or [""])[0]
        parts = [f"{i}. {_s(it, 'raw_name')}"]
        extra = " | ".join(p for p in (
            f"brand={_s(it, 'brand')}" if _s(it, "brand") else "",
            f"size={_s(it, 'size')}" if _s(it, "size") else "",
            f"aldi_theme={theme}" if theme else "",
        ) if p)
        if extra:
            lines.append(f"{parts[0]} ({extra})")
        else:
            lines.append(parts[0])

    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "\n".join(lines)},
        ],
        "temperature": 0,
        # glm-5.3-flash is a REASONING model: without disabling thinking
        # it burns the budget on reasoning_content and content stays ""
        # (live-search lesson, 2026-10-02)
        "thinking": {"type": "disabled"},
        "max_tokens": 1500,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/chat/completions", data=body,
        headers={"authorization": f"Bearer {key}",
                 "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            data = json.loads(res.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"] or ""
        return parse_categories(content, len(items))
    except Exception:               # noqa: BLE001 — never block the feed
        return []
