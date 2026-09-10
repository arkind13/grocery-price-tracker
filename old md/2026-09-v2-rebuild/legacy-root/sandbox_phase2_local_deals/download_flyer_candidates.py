#!/usr/bin/env python3
"""Sandbox helper — download full-size flyer candidates from the image
URLs recorded by test1 (fb_fetch_findings.json).

- Unescapes HTML entities (&amp; -> &).
- Strips the `stp=` rendition param so Facebook serves the full-size
  original instead of a small crop.
- Dedupes by photo id (the long number before _n.jpg).
- Saves unique candidates to flyer_candidates/ (largest first).

Run: uv run --with requests python download_flyer_candidates.py
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "flyer_candidates"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PHOTO_ID_RE = re.compile(r"/([0-9]{6,}[_0-9]*?_n)\.(?:jpg|png|webp)")
# cstp=mxWxH marks the max rendition size — used to pick the largest
# variant of each photo. NEVER modify the URL itself: the oh= signature
# covers the exact query string, so stripping stp= yields HTTP 403.
RENDITION_RE = re.compile(r"cstp=mx(\d+)x(\d+)")


def unescape_url(url: str) -> str:
    """Unescape HTML entities only — signed CDN URLs must stay intact."""
    return html.unescape(url)


def rendition_px(url: str) -> int:
    """Approximate rendition area (0 when unknown)."""
    m = RENDITION_RE.search(url)
    if not m:
        return 0
    return int(m.group(1)) * int(m.group(2))


def photo_id(url: str) -> str:
    """Stable photo id from a CDN URL (fallback: whole URL)."""
    m = PHOTO_ID_RE.search(url)
    return m.group(1) if m else url


def main() -> int:
    findings = json.loads((HERE / "fb_fetch_findings.json").read_text("utf-8"))
    OUT_DIR.mkdir(exist_ok=True)

    # photo_id -> largest captured rendition URL (exact, signed).
    best: dict[str, str] = {}
    for run in findings["runs"]:
        if run.get("mode") != "scrapedo" or not run.get("ok"):
            continue
        for url in run.get("image_urls", []):
            pid = photo_id(url)
            if pid not in best or rendition_px(url) > rendition_px(best[pid]):
                best[pid] = url

    downloaded = 0
    for pid, url in best.items():
        target = OUT_DIR / f"{pid}.jpg"
        if target.exists():
            continue
        try:
            resp = requests.get(unescape_url(url), timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        except requests.RequestException as exc:
            print(f"SKIP {pid}: {exc.__class__.__name__}")
            continue
        if resp.status_code != 200 or len(resp.content) < 5000:
            print(f"SKIP {pid}: status={resp.status_code} "
                  f"bytes={len(resp.content)}")
            continue
        target.write_bytes(resp.content)
        downloaded += 1
        print(f"OK   {pid}.jpg  {len(resp.content) // 1024} KB")
    print(f"\n{downloaded} new, {len(best)} unique candidates total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
