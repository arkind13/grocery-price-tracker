"""Facebook public photo-board fetch for the four Mt Druitt shops.

Scrape.do render (photos tab primary, root fallback) → post-grouped
image files on disk. Logged-out; tested working on all four pages
(pre-arch A1/A4). Signed CDN URLs are downloaded EXACTLY as captured
(only &amp; is unescaped); any other param mutation → 403.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

STORES = [
    {"key": "dunya",     "name": "Dunya Butchery",
     "fb_page_id": "100071472636159", "kind": "butchery",
     "code": "DUNY"},
    {"key": "merjan",    "name": "Merjan Brothers Quality Meats",
     "fb_page_id": "61578274311504",  "kind": "butchery",
     "code": "MERJ"},
    {"key": "fruitopia", "name": "Fruitopia Mt Druitt",
     "fb_page_id": "100092972080784", "kind": "fruits",
     "pipeline": "timeline", "code": "FRUT"},
    {"key": "abusalim",  "name": "Abu Salim Fruit Market",
     "fb_page_id": "61592534263358",  "kind": "fruits",
     "code": "ABSA"},
]

FB_FETCH_MAX_ATTEMPTS = 3     # 5xx/timeout only, fresh session each
SCRAPEDO_RUN_CAP = 40         # per-run credits (FB pages + catalogue)
MIN_RENDITION_PX = 400
MIN_FILE_BYTES = 30_000
POSTS_PER_STORE = 3
SCRAPEDO_TIMEOUT_S = 90.0
DOWNLOAD_TIMEOUT_S = 30.0

SCRAPEDO_BASE = "https://api.scrape.do"

SCONTENT_RE = re.compile(
    r"https://scontent[^\"'\s\\]+?\.(?:jpg|png|webp)[^\"'\s\\]*")
# Real FB basenames: {id}_{big}_{big}[_{n}]_n.jpg (3 numeric groups +
# _n); the plan sketch's 4-group shape kept accepted for tests.
PHOTO_ID_RE = re.compile(
    r"(\d{6,})_(\d+)_([0-9]+)((?:_[0-9]+)?)(?:_n)?"
    r"\.(?:jpg|png|webp)")
CSTP_SIZE_RE = re.compile(r"cstp=mx(\d+)x(\d+)")
POST_MARKER_RE = re.compile(r"top_level_post_id[\"':\s]+(\d+)")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FLYERS_DIR = DATA_DIR / "fb_flyers"


class FetchUnavailable(Exception):
    """Hard fetch failure for one store (attempts exhausted / 4xx)."""


@dataclass
class PostImages:
    """One post's downloaded board images (largest rendition each)."""
    post_ref: str
    files: list[Path] = field(default_factory=list)


_credits_used = 0


def register_scrapedo_credit() -> bool:
    """Count one Scrape.do call; False when the per-run cap is hit."""
    global _credits_used
    if _credits_used >= SCRAPEDO_RUN_CAP:
        print(f"[fb_flyer_fetch] Scrape.do per-run cap "
              f"({SCRAPEDO_RUN_CAP}) reached — skipping call.",
              file=sys.stderr)
        return False
    _credits_used += 1
    return True


def scrapedo_credits_used() -> int:
    """Credits consumed this process run (tests/logging)."""
    return _credits_used


def _unescape_amp(url: str) -> str:
    """Undo HTML &amp; ONLY — signed FB CDN URLs allow no other edit."""
    return url.replace("&amp;", "&")


def _extract_image_urls(html: str) -> dict[str, list[tuple[str, int, int]]]:
    """photo-id basename -> [(url, W, H), ...] from src + srcset.

    Rendition size from cstp=mx{W}x{H} when PLAUSIBLE (both <= 9999
    px — FB also emits degenerate mx params built from its huge
    internal ids, which serve tiny placeholder bytes); otherwise the
    basename's 2nd/3rd numbers when plausible; else (0, 0) so the
    rendition loses every pick and fails the px floor. &amp;-only
    unescape. Mirrors the sandbox test1 harness (reference).
    """
    out: dict[str, list[tuple[str, int, int]]] = {}
    for raw in SCONTENT_RE.findall(html or ""):
        url = _unescape_amp(raw)
        m = PHOTO_ID_RE.search(url)
        if not m:
            continue
        photo_id = m.group(1)
        c = CSTP_SIZE_RE.search(url)
        if c and int(c.group(1)) <= 9999 and int(c.group(2)) <= 9999:
            w, h = int(c.group(1)), int(c.group(2))
        elif int(m.group(2)) <= 9999 and int(m.group(3)) <= 9999:
            w, h = int(m.group(2)), int(m.group(3))
        else:
            w, h = 0, 0
        out.setdefault(photo_id, []).append((url, w, h))
    return out


def _group_by_post(html: str,
                   url_map: dict[str, list[tuple[str, int, int]]]
                   ) -> list[list[str]]:
    """Group photo ids by post container (plan §1.4.7).

    Splits on top_level_post_id markers; images between markers
    belong to the preceding marker. Zero markers → each photo is its
    own post. Returns url lists (largest rendition per photo).
    """
    best: dict[str, str] = {}
    for pid, rends in url_map.items():
        usable = [(u, max(w, h)) for u, w, h in rends
                  if max(w, h) >= MIN_RENDITION_PX]
        if usable:
            best[pid] = max(usable, key=lambda r: r[1])[0]
    if not best:
        return []
    markers = list(POST_MARKER_RE.finditer(html or ""))
    if not markers:
        return [[u] for u in best.values()]
    # Position-based assignment (spec §1.4.7): each image belongs to
    # the marker it FOLLOWS in the document. html.find() supplies the
    # per-image offset; EC1 sandbox fixture (2 markers + 3 images)
    # pins the expected 2+1 split, so buckets advance with positions.
    located: list[tuple[int, str]] = []
    for url in best.values():
        pos = (html or "").find(url)
        located.append((pos, url))
    located.sort(key=lambda t: t[0])
    groups: list[list[str]] = [[] for _ in markers]
    for pos, url in located:
        idx = 0
        for mi, marker in enumerate(markers):
            if marker.start() < pos:
                idx = mi
            else:
                break
        groups[idx].append(url)
    return [g for g in groups if g]

def _build_params(page_id: str, path: str, session_id: str,
                  extra: dict | None = None) -> dict:
    """Scrape.do params for one FB render (sandbox test1 shape).

    Args:
        page_id: the FB page id.
        path: URL path after the page id ("/photos", "" ...).
        session_id: sticky-session id for this attempt.
        extra: optional extra Scrape.do params (e.g. scroll tweaks),
        merged last so they can override the defaults.

    Returns:
        dict: full Scrape.do query params.
    """
    params = {
        "token": os.getenv("SCRAPEDO_API_KEY", ""),
        "url": f"https://www.facebook.com/{page_id}{path}",
        "render": "true",       # FB needs JS
        "geoCode": "au",        # AU exit node
        "country": "au",
        "session": session_id,
    }
    if extra:
        params.update(extra)
    return params


def _fresh_session(n: int) -> str:
    """New sticky-session id per attempt (mirrors coles_extractor)."""
    return f"fb_{int(time.time())}_{n}"


def _fetch_html(page_id: str, path: str,
                extra_params: dict | None = None) -> str:
    """Render one FB URL via Scrape.do with the retry policy.

    Retries ONLY 5xx/timeout (fresh session each); 401/403/400 fail
    immediately. Raises FetchUnavailable on exhaustion.

    Args:
        page_id: the FB page id.
        path: URL path after the page id.
        extra_params: optional extra Scrape.do params for this call.
    """
    for attempt in range(FB_FETCH_MAX_ATTEMPTS):
        if not register_scrapedo_credit():
            raise FetchUnavailable("scrapedo run cap reached")
        try:
            resp = requests.get(
                SCRAPEDO_BASE,
                params=_build_params(page_id, path,
                                     _fresh_session(attempt),
                                     extra_params),
                timeout=SCRAPEDO_TIMEOUT_S,
            )
        except requests.RequestException:
            continue
        if resp.status_code == 200:
            return resp.text or ""
        if resp.status_code in (401, 403, 400):
            raise FetchUnavailable(f"HTTP {resp.status_code} (no retry)")
        # 5xx / other: retry with backoff
        time.sleep(3)
    raise FetchUnavailable(f"{FB_FETCH_MAX_ATTEMPTS} attempts exhausted")


def _download(url: str, dest: Path) -> Path | None:
    """Direct signed GET; None when under MIN_FILE_BYTES."""
    try:
        resp = requests.get(url, timeout=DOWNLOAD_TIMEOUT_S)
        if resp.status_code != 200 or len(resp.content) < MIN_FILE_BYTES:
            return None
        dest.write_bytes(resp.content)
        return dest
    except requests.RequestException:
        return None


def fetch_store_posts(store: dict, run_dir: Path) -> list[PostImages]:
    """FB photos-tab fetch -> post-grouped image files on disk.

    Photos tab primary; root page is the automatic fallback URL when
    the photos tab fails or yields zero images. Folder wiped at run
    start (B7 - no history). Raises FetchUnavailable on hard failure
    (caller prints the no-prices line).
    """
    run_dir = run_dir / store["key"]
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    html = ""
    for path in ("/photos", ""):
        try:
            html = _fetch_html(store["fb_page_id"], path)
        except FetchUnavailable:
            continue
        if SCONTENT_RE.search(html or ""):
            break
    else:
        raise FetchUnavailable("no images from photos tab or root")

    url_map = _extract_image_urls(html)
    groups = _group_by_post(html, url_map)[:POSTS_PER_STORE]
    posts: list[PostImages] = []
    for n, group in enumerate(groups, 1):
        files = [f for f in (
            _download(
                u,
                run_dir / f"{store['key']}_{n}_{i}"
                f"{Path(u).suffix.split('?')[0][:5]}")
            for i, u in enumerate(group, 1)) if f is not None]
        if files:
            posts.append(PostImages(post_ref=f"{store['key']}-p{n}",
                                    files=files))
    if not posts:
        raise FetchUnavailable("all renditions below size floors")
    return posts
