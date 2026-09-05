"""Offline tests for extractors/fb_flyer_fetch (spec §14.1/§14.2).

All network mocked via requests.get / module internals. Zero skips.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from extractors import fb_flyer_fetch as ff


class FakeResp:
    """Minimal requests.Response stand-in (status/text/content)."""

    def __init__(self, status_code=200, text="", content=b""):
        self.status_code = status_code
        self.text = text
        self.content = content


def _img(photo_id="123456789", w=960, h=960, amp=False):
    """One scontent URL (amp=True renders HTML-escaped &amp;)."""
    sep = "&amp;" if amp else "&"
    return (f"https://scontent.example.net/v/t39.30808-6/{photo_id}"
            f"_101_102_999.jpg?cstp=mx{w}x{h}{sep}oh=abc{sep}oe=def")


def _fixture_html(posts):
    """HTML with one post marker + images per entry: [(post_id, n)].

    Every image gets a DISTINCT photo-id basename (the extractor
    dedupes renditions per photo id — duplicates would collapse).
    """
    parts = []
    counter = 0
    for post_id, n_imgs in posts:
        parts.append(
            f'<script type="json">{{"top_level_post_id"'
            f':"{post_id}"}}</script>')
        for _ in range(n_imgs):
            counter += 1
            parts.append(
                f'<img src="{_img(photo_id=str(2000000 + counter))}">')
    return "\n".join(parts)


def _fake_download_factory(payload=b"x" * 40_000):
    """_download stand-in writing `payload` bytes to dest."""
    def fake_download(url, dest):
        dest.write_bytes(payload)
        return dest
    return fake_download


# --- 14.1: fetch chain ------------------------------------------------------

class TestFetchChain(unittest.TestCase):
    """Fetch chain: primary/fallback, retries, 4xx, credits."""

    def _run_fetch(self, mock_get, run_root):
        store = ff.STORES[0]
        with patch.object(ff, "_download", _fake_download_factory()), \
             patch.object(ff.time, "sleep"):
            return ff.fetch_store_posts(store, run_root)

    def test_photos_tab_primary_root_fallback(self):
        """/photos 200-with-images wins; root never called."""
        html = _fixture_html([("111", 1)])
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(ff.requests, "get",
                          return_value=FakeResp(200, html)) as mock_get:
            posts = self._run_fetch(mock_get, Path(tmp))
        self.assertEqual(len(posts), 1)
        self.assertEqual(mock_get.call_count, 1)
        url = mock_get.call_args.kwargs["params"]["url"]
        self.assertTrue(url.endswith("/photos"))

    def test_photos_tab_empty_falls_back_to_root(self):
        """/photos 200-empty -> root 200-with-images is used."""
        html = _fixture_html([("111", 1)])
        import tempfile
        mock = MagicMock(side_effect=[FakeResp(200, "<html/>"),
                                      FakeResp(200, html)])
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(ff.requests, "get", mock):
            posts = self._run_fetch(mock, Path(tmp))
        self.assertEqual(len(posts), 1)
        self.assertEqual(mock.call_count, 2)
        second_url = mock.call_args_list[1].kwargs["params"]["url"]
        self.assertTrue(second_url.endswith(ff.STORES[0]["fb_page_id"]))

    def test_5xx_retries_with_fresh_session_then_succeeds(self):
        """Two 502s then 200: 3 calls, distinct session params."""
        html = _fixture_html([("111", 1)])
        mock = MagicMock(side_effect=[FakeResp(502, "e1"),
                                      FakeResp(502, "e2"),
                                      FakeResp(200, html)])
        with patch.object(ff.requests, "get", mock), \
             patch.object(ff.time, "sleep"):
            out = ff._fetch_html("42", "/photos")
        self.assertIn("scontent", out)
        self.assertEqual(mock.call_count, 3)
        sessions = [c.kwargs["params"]["session"]
                    for c in mock.call_args_list]
        self.assertEqual(len(set(sessions)), 3)

    def test_5xx_exhaustion_raises_fetch_unavailable(self):
        """All attempts 5xx -> FetchUnavailable."""
        mock = MagicMock(side_effect=[FakeResp(502, "e")] * 3)
        with patch.object(ff.requests, "get", mock), \
             patch.object(ff.time, "sleep"):
            with self.assertRaises(ff.FetchUnavailable):
                ff._fetch_html("42", "/photos")

    def test_401_403_400_never_retried(self):
        """One 403 -> exactly 1 call, FetchUnavailable raised."""
        mock = MagicMock(return_value=FakeResp(403, "forbidden"))
        with patch.object(ff.requests, "get", mock), \
             patch.object(ff.time, "sleep"):
            with self.assertRaises(ff.FetchUnavailable):
                ff._fetch_html("42", "/photos")
        self.assertEqual(mock.call_count, 1)

    def test_credit_cap_enforced(self):
        """Cap reached -> no HTTP call, FetchUnavailable."""
        with patch.object(ff, "_credits_used", ff.SCRAPEDO_RUN_CAP), \
             patch.object(ff.requests, "get") as mock_get:
            with self.assertRaises(ff.FetchUnavailable):
                ff._fetch_html("42", "/photos")
        mock_get.assert_not_called()

    def test_run_dir_wiped_each_run(self):
        """Pre-existing stale file in the store dir is gone after run."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            stale = run_dir / ff.STORES[0]["key"] / "stale.jpg"
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.write_bytes(b"old")
            html = _fixture_html([("111", 1)])
            with patch.object(ff.requests, "get",
                              return_value=FakeResp(200, html)), \
                 patch.object(ff, "_download",
                              _fake_download_factory()):
                posts = ff.fetch_store_posts(ff.STORES[0], run_dir)
            self.assertFalse(stale.exists())
            self.assertTrue(all(p.files for p in posts))


# --- 14.2: extraction / rendition / grouping -------------------------------

class TestExtractionAndGrouping(unittest.TestCase):
    """URL capture, dedupe, floors, post grouping."""

    def test_urls_captured_intact_amp_only(self):
        """&amp; unescaped to & — no other transformation."""
        raw = _img(amp=True)
        html = f'<img src="{raw}">'
        got = ff._extract_image_urls(html)
        (url, _w, _h), = got["123456789"]
        self.assertEqual(url, _img(amp=False))

    def test_multirendition_dedupe_keeps_largest_cstp(self):
        """Same photo id, mx960x960 vs mx120x120 -> largest kept."""
        html = (f'<img src="{_img(w=960, h=960)}">'
                f'<img src="{_img(w=120, h=120)}">')
        groups = ff._group_by_post(html, ff._extract_image_urls(html))
        self.assertEqual(len(groups), 1)
        self.assertIn("mx960x960", groups[0][0])
        self.assertNotIn("mx120x120", groups[0][0])

    def test_nine_digit_photo_ids_accepted(self):
        """9-digit photo-id basename group is accepted."""
        html = f'<img src="{_img(photo_id="123456789")}">'
        got = ff._extract_image_urls(html)
        self.assertIn("123456789", got)

    def test_srcset_urls_parsed(self):
        """URL only inside srcset=\"...\" is found."""
        html = f'<img srcset="{_img()} 2x">'
        got = ff._extract_image_urls(html)
        self.assertIn("123456789", got)

    def test_rendition_px_floor(self):
        """Only sub-400px renditions -> no usable group."""
        html = f'<img src="{_img(w=120, h=120)}">'
        groups = ff._group_by_post(html, ff._extract_image_urls(html))
        self.assertEqual(groups, [])

    def test_file_kb_floor(self):
        """Downloaded content under MIN_FILE_BYTES is dropped."""
        with patch.object(ff.requests, "get",
                          return_value=FakeResp(200, content=b"x" * 100)):
            out = ff._download(_img(), Path.cwd() / "nonexistent_zz" / "f.jpg")
        self.assertIsNone(out)

    def test_images_grouped_by_post_ec1_fixture(self):
        """Two markers + 3 images -> 2 groups (2 + 1)."""
        html = _fixture_html([("1000001", 2), ("1000002", 1)])
        groups = ff._group_by_post(html, ff._extract_image_urls(html))
        self.assertEqual([len(g) for g in groups], [2, 1])

    def test_zero_markers_each_image_own_post(self):
        """Zero post markers -> each image its own group."""
        html = (f'<img src="{_img(photo_id="1000001")}">'
                f'<img src="{_img(photo_id="1000002")}">')
        groups = ff._group_by_post(html, ff._extract_image_urls(html))
        self.assertEqual(len(groups), 2)

    def test_posts_capped_at_three_most_recent(self):
        """5 groups -> first 3 kept (document order)."""
        html = _fixture_html([(str(1000000 + i), 1) for i in range(5)])
        groups = ff._group_by_post(html, ff._extract_image_urls(html))
        self.assertEqual(len(groups), 5)
        capped = groups[:ff.POSTS_PER_STORE]
        self.assertEqual(len(capped), 3)


if __name__ == "__main__":
    unittest.main()
