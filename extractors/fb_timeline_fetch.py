"""FB timeline (root page) fetch: last-N posts with text + images.

Complements fb_flyer_fetch (photos tab) for the text-first pipeline
(TODO-local-deals-gaps Tasks 2-3): the logged-out timeline render
embeds each story as Comet JSON —
  "post_id":"<id>","creation_time":<unix>,
  "message":{"delight_ranges":...,"text":"<escaped text>"},
  "attachments":[...{"__typename":"Photo",...}]
Verified against the live Fruitopia render 2026-09-06: post texts use
the strict '"message":{"delight_ranges"' shape (comments and page
info do NOT), and scontent CDN urls are position-associable with the
story that contains them.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from extractors.fb_flyer_fetch import (
    POSTS_PER_STORE, FetchUnavailable, _fetch_html, _unescape_amp,
)

STORY_ID_RE = re.compile(r'"post_id":"(\d+)"')
CREATION_RE = re.compile(r'"creation_time":(\d{10})')
# Strict post-message shape — comments/page chrome do not match this.
MESSAGE_RE = re.compile(
    r'"message":\{"delight_ranges":[^\n]{0,8000}?"text":"'
    r'((?:[^"\\]|\\.)*)"')
SCONTENT_SPAN_RE = re.compile(
    r"https://scontent[^\"'\s\\]+?\.(?:jpg|png|webp)[^\"'\s\\]*")
PHOTO_ID_RE = re.compile(r"(\d{6,})_\d+_\d+")
CSTP_SIZE_RE = re.compile(r"cstp=mx(\d+)x(\d+)")

# Logged-in route (user-approved 2026-09-06): the FB session pair
# from the user's browser, set as .env keys by the USER (secrets —
# never printed, never committed). c_user alone identifies the
# account; xs is the session secret — BOTH are required by FB.
FB_COOKIE_ENV_PAIR = (
    ("FB_COOKIE_C_USER", "c_user"),
    ("FB_COOKIE_XS", "xs"),
)


@dataclass
class TimelinePost:
    """One timeline story: id, text, images (largest rendition each).

    Attributes:
        post_ref: the FB post id (top_level_post_id).
        text: decoded message text ("" for image-only posts).
        creation_time: unix epoch seconds, or None when absent.
        image_urls: largest plausible rendition per photo, in
            document order, belonging to THIS story.
    """
    post_ref: str
    text: str = ""
    creation_time: int | None = None
    image_urls: list[str] = field(default_factory=list)


def _decode(blob: str) -> str:
    """Decode a JSON string body (handles \\uXXXX and \\n escapes)."""
    try:
        return json.loads('"' + blob + '"')
    except ValueError:
        return blob.encode("utf-8", "replace").decode("unicode_escape")


def _rendition_px(url: str) -> int:
    """Plausible max dimension of one rendition (0 when unknown)."""
    c = CSTP_SIZE_RE.search(url)
    if c and int(c.group(1)) <= 9999 and int(c.group(2)) <= 9999:
        return max(int(c.group(1)), int(c.group(2)))
    return 0


def _best_rendition(urls: list[str]) -> str:
    """Largest plausible rendition among duplicates of one photo."""
    best, best_px = urls[0], -1
    for url in urls:
        px = _rendition_px(url)
        if px > best_px:
            best, best_px = url, px
    return best


def parse_timeline_posts(html: str) -> list[TimelinePost]:
    """Parse a timeline render into ordered, deduplicated stories.

    Stories are spanned in first-marker document order (FB renders
    newest-first); a story owns the document up to the next DISTINCT
    story id (duplicate Relay markers stay inside the span). Message
    blobs and scontent urls attach to the containing span.

    Args:
        html: the rendered root-page HTML.

    Returns:
        list[TimelinePost]: stories found, newest first.
    """
    spans: list[list] = []          # [start, end, post_id]
    index_by_id: dict[str, int] = {}
    for m in STORY_ID_RE.finditer(html):
        pid = m.group(1)
        if pid in index_by_id:
            continue
        index_by_id[pid] = len(spans)
        spans.append([m.start(), len(html), pid])
    for i, span in enumerate(spans[:-1]):
        span[1] = spans[i + 1][0]
    posts = [TimelinePost(post_ref=span[2]) for span in spans]

    for si, (start, end, _pid) in enumerate(spans):
        c = CREATION_RE.search(html, start, end)
        if c:
            posts[si].creation_time = int(c.group(1))
        for m in MESSAGE_RE.finditer(html, start, end):
            text = _decode(m.group(1))
            if not text:
                continue
            if posts[si].text and text not in posts[si].text:
                posts[si].text += "\n" + text
            elif not posts[si].text:
                posts[si].text = text
        per_photo: dict[str, list[str]] = {}
        for im in SCONTENT_SPAN_RE.finditer(html, start, end):
            url = _unescape_amp(im.group(0))
            pid_m = PHOTO_ID_RE.search(url)
            if pid_m:
                per_photo.setdefault(pid_m.group(1), []).append(url)
        posts[si].image_urls = [_best_rendition(urls)
                                for urls in per_photo.values()]
    # Newest first: creation_time desc where every story carries a
    # stamp (render variance must not reorder the last-3 window);
    # otherwise trust document order.
    if posts and all(p.creation_time is not None for p in posts):
        posts.sort(key=lambda p: p.creation_time, reverse=True)
    return posts


def fb_cookie_header() -> str:
    """Build a Cookie header from the .env FB session pair.

    Reads FB_COOKIE_C_USER / FB_COOKIE_XS (values NEVER logged).

    Returns:
        str: "c_user=…; xs=…" when both are set, "" otherwise.
    """
    import os

    parts = []
    for env, name in FB_COOKIE_ENV_PAIR:
        val = os.getenv(env, "").strip()
        if val:
            parts.append(f"{name}={val}")
    return "; ".join(parts) if len(parts) == len(FB_COOKIE_ENV_PAIR) \
        else ""


def _custom_headers_params(cookie_header: str) -> dict:
    """Scrape.do params carrying a Cookie header (b64 JSON body).

    Args:
        cookie_header: the Cookie header value (secret).

    Returns:
        dict: {"customHttpHeaders": "true", "customHeaders": b64}.
        The b64 blob contains the secret — params are NEVER printed
        anywhere in this module (requests exceptions surface only
        class names via the retry policy in fb_flyer_fetch).
    """
    import base64
    import json

    raw = json.dumps({"Cookie": cookie_header})
    return {"customHttpHeaders": "true",
            "customHeaders": base64.b64encode(
                raw.encode("utf-8")).decode("ascii")}


def fetch_timeline_posts(store: dict, *,
                         max_posts: int = POSTS_PER_STORE,
                         extra_params: dict | None = None,
                         fetch=None,
                         logged_in: str | bool = "auto",
                         ) -> list[TimelinePost]:
    """Render the page timeline and return up to max_posts stories.

    Route policy (user-approved logged-in route, 2026-09-06):
      logged_in="auto"  — when the FB_COOKIE_* pair is set, try the
        logged-in render FIRST (more stories visible); on failure
        fall back to the logged-out render (max 2 credits).
      logged_in=True    — logged-in ONLY (no fallback); raises
        immediately when the cookie pair is unset.
      logged_in=False   — logged-out only (single credit).

    Args:
        store: STORES entry (fb_page_id + key).
        max_posts: keep at most this many stories (newest first).
        extra_params: extra Scrape.do params (e.g. scroll tweaks);
        merged under the per-attempt params.
        fetch: injectable HTML fetcher (tests); default _fetch_html.
        logged_in: route policy (see above).

    Returns:
        list[TimelinePost]: newest-first stories (may be fewer than
        max_posts — the render exposes what it exposes).

    Raises:
        FetchUnavailable: every attempt failed or no stories parsed.
    """
    fetch = fetch or _fetch_html
    cookie = fb_cookie_header()
    attempts: list[dict] = []
    if logged_in is True or logged_in == "auto":
        if not cookie:
            if logged_in is True:
                raise FetchUnavailable(
                    "logged-in route requested but FB_COOKIE_C_USER"
                    "/FB_COOKIE_XS are not set")
        else:
            attempts.append(_custom_headers_params(cookie))
    if logged_in is False or logged_in == "auto":
        attempts.append({})          # logged-out (or the fallback)

    last_err: Exception | None = None
    for attempt in attempts:
        merged = {**(extra_params or {}), **attempt}
        try:
            html = fetch(store["fb_page_id"], "", merged)
        except FetchUnavailable as exc:
            last_err = exc
            if len(attempts) > 1:
                print(f"[fb_timeline] render attempt failed "
                      f"({exc}) — trying next route")
            continue
        posts = parse_timeline_posts(html)[:max_posts]
        if posts:
            return posts
        last_err = FetchUnavailable("no stories in timeline render")
    raise last_err or FetchUnavailable("no stories in timeline render")


def download_post_images(post: TimelinePost, run_dir, store_key: str,
                         *, max_images: int = 4) -> list:
    """Download a post's OWN timeline images (signed URL, as-captured).

    Args:
        post: the TimelinePost whose image_urls are downloaded.
        run_dir: per-run flyer directory (a store subdir is added).
        store_key: store key for the filename prefix.
        max_images: cap (vision cost bound — the live anniversary
            render exposed up to 10 renditions for ONE photo).

    Returns:
        list[Path]: successfully downloaded files (>= MIN_FILE_BYTES).
    """
    from pathlib import Path

    from extractors.fb_flyer_fetch import _download

    dest_dir = Path(run_dir) / store_key
    dest_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for i, url in enumerate(post.image_urls[:max_images], 1):
        ext = Path(url.split("?")[0]).suffix[:5] or ".jpg"
        name = f"{store_key}_{post.post_ref}_{i}{ext}"
        f = _download(url, dest_dir / name)
        if f is not None:
            files.append(f)
    return files
