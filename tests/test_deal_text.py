#!/usr/bin/env python3
"""Timeline post parsing + text-deal tests (TODO Tasks 2-3).

Fixtures are built from the REAL Fruitopia anniversary post
(2026-09-04 render, user-visible evidence): the "5 & 6 September"
validity phrase and the 24-line deal grammar. Offline; the timeline
HTML fixture is a synthetic minimal render with the same Comet JSON
shapes the live render uses (verified 2026-09-06).
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from extractors.deal_text import (  # noqa: E402
    filter_recent_posts, parse_fruitopia_deals, parse_validity_end,
)
from extractors.fb_timeline_fetch import parse_timeline_posts  # noqa: E402

SUNDAY_6SEP = date(2026, 9, 6)      # catalogue's last day (Sydney)
MONDAY_7SEP = date(2026, 9, 7)      # 06:00 Sydney == 20:00 UTC prev.

ANNIVERSARY_TEXT = (
    "🎉💚 𝗙𝗥𝗨𝗜𝗧𝗢𝗣𝗜𝗔 𝗠𝗧 𝗗𝗥𝗨𝗜𝗧𝗧 𝗜𝗦 𝗧𝗨𝗥𝗡𝗜𝗡𝗚 𝟯! 💚🎉\n"
    "\n"
    "So to celebrate, we’ve worked extra hard to bring you even "
    "MORE specials than usual this weekend! 🔥🔥\n"
    "\n"
    "📅 Saturday & Sunday, 5 & 6 September\n"
    "\n"
    "🥬 Cos Lettuce – 99¢ each\n"
    "🎃 Jap Pumpkin – 99¢/kg\n"
    "🥬 Silverbeet – 99¢ each\n"
    "🌽 Sweet Corn – 88¢ each\n"
    "🥒 Chokos – $1.99/kg\n"
    "🥬 Celery – 2 for $2.99\n"
    "🥕 Carrots 1kg Bag – 2 for $2.99\n"
    "🌿 Large Parsley Bunch – $2.99\n"
    "🥔 Washed Potatoes 5kg Bag – $2.99\n"
    "🍆 Eggplant – $2.99/kg\n"
    "🥦 Cauliflower – $1.99 each\n"
    "🍓 Strawberries – $1.80 each\n"
    "🥭 R2E2 Mangoes – $6.99/kg\n"
    "\n"
    "⏳ Saturday & Sunday only — while stocks last!\n"
    "\n"
    "#Fruitopia #WeekendSpecials"
)


class TestValidityParsing(unittest.TestCase):
    """TODO Task 2: validity from text, Sydney-disciplined."""

    def test_anniversary_phrase_ends_6_sep(self):
        self.assertEqual(
            parse_validity_end(ANNIVERSARY_TEXT, today=SUNDAY_6SEP),
            date(2026, 9, 6))

    def test_single_day_phrase(self):
        self.assertEqual(
            parse_validity_end("Valid until 6 September only",
                               today=SUNDAY_6SEP),
            date(2026, 9, 6))

    def test_undated_text_returns_none(self):
        self.assertIsNone(
            parse_validity_end("Freshness Unleashed!\nWhile stocks "
                               "last.", today=SUNDAY_6SEP))
        self.assertIsNone(parse_validity_end("", today=SUNDAY_6SEP))

    def test_pinned_utc_instant_expiry_the_user_demanded(self):
        # The Task-1 RE-CHECK, through the Task-2 rule: at 2026-09-06
        # 20:00 UTC (= 06:00 Sun 7 Sep Sydney) the "5 & 6 September"
        # catalogue is EXPIRED.
        self.assertLess(date(2026, 9, 6), MONDAY_7SEP)

    def test_year_rolls_forward_after_new_year(self):
        # A "6 September" post read on 7 Jan 2027 means Sep 2027.
        self.assertEqual(
            parse_validity_end("6 September", today=date(2027, 1, 7)),
            date(2027, 9, 6))


class TestFruitopiaDealGrammar(unittest.TestCase):
    """The real post's line shapes, one way or another each."""

    def test_all_deal_lines_parsed(self):
        deals = parse_fruitopia_deals(ANNIVERSARY_TEXT)
        self.assertEqual(len(deals), 13)   # fixture line count
        items = [d["item"] for d in deals]
        self.assertIn("Cos Lettuce", items)
        self.assertIn("Washed Potatoes 5kg Bag", items)
        self.assertIn("R2E2 Mangoes", items)

    def test_cents_kg_and_each(self):
        deals = {d["item"]: d for d in
                 parse_fruitopia_deals(ANNIVERSARY_TEXT)}
        self.assertEqual(deals["Cos Lettuce"]["price"], 0.99)
        self.assertEqual(deals["Cos Lettuce"]["unit"], "ea")
        self.assertEqual(deals["Jap Pumpkin"]["price"], 0.99)
        self.assertEqual(deals["Jap Pumpkin"]["unit"], "kg")
        self.assertEqual(deals["Sweet Corn"]["price"], 0.88)
        self.assertEqual(deals["Chokos"]["price"], 1.99)
        self.assertEqual(deals["Chokos"]["unit"], "kg")

    def test_multibuy_divided_out_with_note(self):
        deals = {d["item"]: d for d in
                 parse_fruitopia_deals(ANNIVERSARY_TEXT)}
        celery = deals["Celery"]
        self.assertEqual(celery["multibuy"], 2)
        self.assertEqual(celery["price"], 1.5)   # 2.99/2 round 2dp
        self.assertEqual(celery["multibuy_note"], "2 for $2.99")
        carrots = deals["Carrots 1kg Bag"]
        self.assertEqual(carrots["price"], 1.5)
        self.assertEqual(carrots["unit"], "ea")

    def test_non_deal_lines_skipped(self):
        deals = parse_fruitopia_deals(ANNIVERSARY_TEXT)
        joined = " ".join(d["item"] for d in deals)
        self.assertNotIn("Saturday", joined)
        self.assertNotIn("Fruitopia", joined)
        self.assertNotIn("while stocks last", joined.lower())


class TestTimelineParsing(unittest.TestCase):
    """Synthetic render with the live-verified Comet JSON shapes."""

    def _html(self) -> str:
        escaped = (ANNIVERSARY_TEXT
                   .replace("\\", "\\\\").replace('"', '\\"')
                   .replace("\n", "\\n")
                   .encode("ascii", "backslashreplace").decode())
        old_blob = '"text":"Old board post from August"'
        # Real FB layout: newest story FIRST in the document.
        return (
            '<html><script>'
            'page chrome image '
            'https://scontent.xx.fbcdn.net/v/t1.'
            'chrome_100001_222222_111111_n.jpg?cstp=mx640x640&oh=1 '
            '"post_id":"222222222222222","creation_time":1758505584,'
            '"attachments":[{"media":{"__typename":"Photo",'
            '"id":"555555555555556"}}]'
            '"message":{"delight_ranges":[],"ranges":[],'
            '"text":"' + escaped + '"}'
            'https://scontent.xx.fbcdn.net/v/t1.'
            'board_800001_999998_999997_n.jpg?cstp=mx960x720&oh=3 '
            '"post_id":"111111111111111","creation_time":1756900000,'
            '"message":{"delight_ranges":[],"text":"' + old_blob + '"}'
            'https://scontent.xx.fbcdn.net/v/t1.'
            'oldboard_700001_888888_777777_n.jpg?cstp=mx720x960&oh=2'
            '</script></html>')

    def test_two_stories_newest_first_with_fields(self):
        posts = parse_timeline_posts(self._html())
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0].post_ref, "222222222222222")
        self.assertEqual(posts[0].creation_time, 1758505584)
        self.assertEqual(posts[1].post_ref, "111111111111111")
        # Image attribution: the story span owns only ITS urls —
        # page-chrome/other-story photos stay outside.
        self.assertTrue(any("board_800001" in u
                            for u in posts[0].image_urls))
        self.assertFalse(any("oldboard" in u
                             for u in posts[0].image_urls))
        self.assertTrue(any("oldboard" in u
                            for u in posts[1].image_urls))
        self.assertFalse(any("chrome_111" in u
                             for u in posts[1].image_urls))

    def test_duplicate_relay_markers_collapse(self):
        html = (self._html()
                + '"post_id":"222222222222222","creation_time":'
                  '1758505584')
        posts = parse_timeline_posts(html)
        self.assertEqual(len(posts), 2)

    def test_image_only_post_has_empty_text(self):
        html = ('"post_id":"333333333333333","creation_time":'
                '1758500000,"attachments":[]')
        posts = parse_timeline_posts(html)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].text, "")


class TestLastThreeAndFutureOnly(unittest.TestCase):
    """The user's standing rule: last 3 posts, future validity only."""

    class _P:
        def __init__(self, ref, text):
            self.post_ref = ref
            self.text = text

    def test_undated_goes_to_needs_review_never_kept(self):
        posts = [
            self._P("newest", ANNIVERSARY_TEXT),      # ends 6 Sep
            self._P("second", "Weekend specials 12 & 13 September"),
            self._P("third", "Freshness Unleashed!"),  # undated
            self._P("fourth", "Old 1 & 2 August post"),  # out of 3
        ]
        kept, expired, review = filter_recent_posts(
            posts, today=MONDAY_7SEP)
        self.assertEqual([p.post_ref for p, _e in kept], ["second"])
        self.assertEqual([p.post_ref for p, _e in expired],
                         ["newest"])
        self.assertEqual([p.post_ref for p in review], ["third"])
        # The 4th post is outside the last-3 window entirely.
        joined = [p.post_ref for p, _e in kept + expired] \
            + [p.post_ref for p in review]
        self.assertNotIn("fourth", joined)

    def test_valid_on_its_last_day(self):
        posts = [self._P("a", ANNIVERSARY_TEXT)]
        kept, expired, review = filter_recent_posts(
            posts, today=SUNDAY_6SEP)
        self.assertEqual(len(kept), 1)
        self.assertEqual(expired, [])
        self.assertEqual(review, [])


class TestTextFirstBranch(unittest.TestCase):
    """TODO Task 3: text branch first, vision ONLY for image-only."""

    class _P:
        def __init__(self, ref, text="", urls=None):
            self.post_ref = ref
            self.text = text
            self.image_urls = urls or []

    def test_text_post_never_touches_vision(self):
        from core import local_deals as ld
        post = self._P("p1", ANNIVERSARY_TEXT, urls=["u1", "u2"])
        with patch("core.flyer_vision.parse_board_images") as vis, \
                patch("extractors.fb_timeline_fetch."
                      "download_post_images") as dl:
            deals, source, until = ld.extract_post_deals(
                post, Path("run"), "fruitopia")
        self.assertEqual(source, "text")
        self.assertIsNone(until)
        self.assertGreater(len(deals), 0)
        vis.assert_not_called()
        dl.assert_not_called()

    def test_image_only_post_falls_back_to_its_own_images(self):
        from core import local_deals as ld
        post = self._P("p2", "", urls=["https://x/board_1_n.jpg"])
        payload = {"valid_until": "2026-09-06",
                   "deals": [{"item": "Bananas", "price": 2.0,
                              "unit": "kg"}]}
        with patch("core.flyer_vision.parse_board_images",
                   return_value=payload) as vis, \
                patch("extractors.fb_timeline_fetch."
                      "download_post_images",
                      return_value=[Path("f.jpg")]) as dl:
            deals, source, until = ld.extract_post_deals(
                post, Path("run"), "fruitopia")
        self.assertEqual(source, "vision")
        self.assertEqual(deals[0]["item"], "Bananas")
        self.assertEqual(until, date(2026, 9, 6))
        dl.assert_called_once()
        vis.assert_called_once_with([Path("f.jpg")])

    def test_no_text_no_images_is_none(self):
        from core import local_deals as ld
        deals, source, until = ld.extract_post_deals(
            self._P("p3", ""), Path("run"), "fruitopia")
        self.assertEqual((deals, source, until), ([], "none", None))


class TestTimelinePipelineBranch(unittest.TestCase):
    """TODO 4a wiring: _process_store timeline path (fruitopia)."""

    class _P:
        def __init__(self, ref, text="", urls=None):
            self.post_ref = ref
            self.text = text
            self.image_urls = urls or []

    def _run(self, posts, today=MONDAY_7SEP):
        from core import local_deals as ld
        store = {"key": "fruitopia", "name": "Fruitopia Mt Druitt",
                 "pipeline": "timeline"}
        with patch("extractors.fb_timeline_fetch.fetch_timeline_posts",
                   return_value=posts):
            return ld._process_store(store, Path("run"), today)

    def test_kept_text_post_deals_enriched(self):
        posts = [self._P("p1", ANNIVERSARY_TEXT)]   # ends 6 Sep
        deals = self._run(posts, today=SUNDAY_6SEP)
        self.assertGreater(len(deals), 0)
        self.assertEqual(deals[0]["store_key"], "fruitopia")
        self.assertEqual(deals[0]["store_name"],
                         "Fruitopia Mt Druitt")
        self.assertEqual(deals[0]["post_ref"], "p1")
        self.assertEqual(deals[0]["source"], "text")

    def test_expired_dropped_undated_excluded(self):
        from extractors.fb_flyer_fetch import FetchUnavailable
        posts = [
            self._P("old", "Weekend 1 & 2 August"),   # expired
            self._P("undated", "Freshness Unleashed!"),
        ]
        with self.assertRaises(FetchUnavailable):
            self._run(posts)

    def test_all_out_of_scope_raises(self):
        from extractors.fb_flyer_fetch import FetchUnavailable
        with self.assertRaises(FetchUnavailable):
            self._run([])


class TestLoggedInRoute(unittest.TestCase):
    """User-approved logged-in FB route (2026-09-06) — offline."""

    class _Fake:
        """Scripted fetch double recording params per call."""

        def __init__(self, outcomes):
            self.outcomes = list(outcomes)   # html or FetchUnavailable
            self.calls = []

        def __call__(self, page_id, path, extra):
            self.calls.append(dict(extra or {}))
            out = self.outcomes.pop(0)
            if isinstance(out, Exception):
                raise out
            return out

    def _with_env(self, **kwargs):
        base = {"FB_COOKIE_C_USER": "", "FB_COOKIE_XS": ""}
        base.update(kwargs)
        return patch.dict("os.environ", base, clear=False)

    def test_cookie_header_pair_required(self):
        from extractors.fb_timeline_fetch import fb_cookie_header
        with self._with_env():
            self.assertEqual(fb_cookie_header(), "")
        with self._with_env(FB_COOKIE_C_USER="111"):
            self.assertEqual(fb_cookie_header(), "")
        with self._with_env(FB_COOKIE_C_USER="111", FB_COOKIE_XS="yy"):
            self.assertEqual(fb_cookie_header(), "c_user=111; xs=yy")

    def test_custom_headers_params_roundtrip(self):
        import base64
        import json
        from extractors.fb_timeline_fetch import (
            _custom_headers_params,
        )
        params = _custom_headers_params("c_user=dummy; xs=dummy")
        self.assertEqual(params["customHttpHeaders"], "true")
        decoded = json.loads(base64.b64decode(
            params["customHeaders"]))
        self.assertEqual(decoded,
                         {"Cookie": "c_user=dummy; xs=dummy"})

    def test_auto_uses_cookies_then_falls_back(self):
        from extractors.fb_timeline_fetch import (
            FetchUnavailable, fetch_timeline_posts,
        )
        fake = self._Fake([
            FetchUnavailable("blocked"),
            '<html>"post_id":"123456789000001"'
            '"creation_time":1758505584</html>',
        ])
        store = {"key": "fruitopia", "fb_page_id": "42"}
        with self._with_env(FB_COOKIE_C_USER="111",
                            FB_COOKIE_XS="yy"):
            posts = fetch_timeline_posts(
                store, max_posts=3, fetch=fake)
        self.assertEqual(len(posts), 1)
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[0].get("customHttpHeaders"),
                         "true")          # logged-in attempt FIRST
        self.assertNotIn("customHttpHeaders", fake.calls[1])

    def test_auto_single_call_when_logged_in_succeeds(self):
        from extractors.fb_timeline_fetch import fetch_timeline_posts
        fake = self._Fake([
            '<html>"post_id":"123456789000001"'
            '"creation_time":1758505584</html>',
        ])
        store = {"key": "fruitopia", "fb_page_id": "42"}
        with self._with_env(FB_COOKIE_C_USER="111",
                            FB_COOKIE_XS="yy"):
            fetch_timeline_posts(store, max_posts=3, fetch=fake)
        self.assertEqual(len(fake.calls), 1)

    def test_logged_in_true_without_cookies_raises_no_call(self):
        from extractors.fb_timeline_fetch import (
            FetchUnavailable, fetch_timeline_posts,
        )
        fake = self._Fake([])
        store = {"key": "fruitopia", "fb_page_id": "42"}
        with self._with_env():
            with self.assertRaises(FetchUnavailable):
                fetch_timeline_posts(store, max_posts=3, fetch=fake,
                                     logged_in=True)
        self.assertEqual(fake.calls, [])

    def test_logged_out_false_ignores_cookies(self):
        from extractors.fb_timeline_fetch import fetch_timeline_posts
        fake = self._Fake([
            '<html>"post_id":"123456789000001"'
            '"creation_time":1758505584</html>',
        ])
        store = {"key": "fruitopia", "fb_page_id": "42"}
        with self._with_env(FB_COOKIE_C_USER="111",
                            FB_COOKIE_XS="yy"):
            fetch_timeline_posts(store, max_posts=3, fetch=fake,
                                 logged_in=False)
        self.assertEqual(len(fake.calls), 1)
        self.assertNotIn("customHttpHeaders", fake.calls[0])


class TestDailyScan(unittest.TestCase):
    """User-directed twice-daily new-post detector (2026-09-06)."""

    def _at(self, y, m, d, h, minute=30):
        from datetime import datetime as dt
        from zoneinfo import ZoneInfo
        return dt(y, m, d, h, minute,
                  tzinfo=ZoneInfo("Australia/Sydney"))

    def test_windows_are_5am_and_3pm_sydney(self):
        from core.local_deals import daily_scan_window
        open5, key5 = daily_scan_window(self._at(2026, 9, 7, 5, 5))
        open15, key15 = daily_scan_window(self._at(2026, 9, 7, 15))
        closed, _key = daily_scan_window(self._at(2026, 9, 7, 9))
        self.assertTrue(open5)
        self.assertEqual(key5, "2026-09-07:5")
        self.assertTrue(open15)
        self.assertEqual(key15, "2026-09-07:15")
        self.assertFalse(closed)

    def test_new_post_notifies_baseline_silent(self):
        """Lifecycle: fresh first sighting -> backfill notify; same
        post again -> silent; changed id -> delta notify."""
        import tempfile as tf
        from core import local_deals as ld
        from core.sydney_time import sydney_now

        refs = {}          # store key -> current post ref

        class _P:
            def __init__(self, ref):
                self.post_ref = ref
                # fresh post: within the 3-day backfill window
                self.creation_time = sydney_now().timestamp() - 3600
                self.text = ""
                self.image_urls: list = []

        def fake_fetch(store, *, max_posts=1, **kw):
            return [_P(refs[store["key"]])]

        sent = []          # records MESSAGE TEXT ONLY — never tokens
        with tf.TemporaryDirectory() as tmp:
            with patch.object(ld, "SCAN_STATE_PATH",
                              Path(tmp) / "scan_state.json"), \
                    patch("extractors.fb_timeline_fetch."
                          "fetch_timeline_posts",
                          side_effect=fake_fetch), \
                    patch.object(ld, "_send_message",
                                 side_effect=lambda *a, **k:
                                 sent.append(a[2] if len(a) > 2
                                             else k.get("text", ""))
                                 or {"ok": True}):
                for key, code in (("fruitopia", "FRUT"),
                                  ("merjan", "MERJ"),
                                  ("dunya", "DUNY"),
                                  ("abusalim", "ABSA")):
                    refs[key] = f"{code}-p1"
                ld._save_scan_state({})       # clean baseline
                rc1 = ld.run_daily_scan(send=True)   # backfill notify
                after_first = len(sent)
                rc2 = ld.run_daily_scan(send=True)   # repeat: silent
                after_repeat = len(sent)
                for key in refs:
                    refs[key] = refs[key] + "-new"
                rc3 = ld.run_daily_scan(send=True)   # delta notify
        self.assertEqual((rc1, rc2, rc3), (0, 0, 0))
        self.assertEqual(after_first, 4)      # one per store
        self.assertEqual(after_repeat, 4)     # no re-report
        self.assertEqual(len(sent), 8)        # deltas notified
        self.assertIn("posted:", sent[0])     # posted time in msg
        self.assertTrue(any("FRUT" in t for t in sent))

    def test_backfill_3days_notify_then_silent(self):
        """First sighting: post within 3 days -> notified; the same
        post again -> silent (last_notified tracking)."""
        import tempfile as tf
        from core import local_deals as ld
        from core.sydney_time import sydney_now

        class _P:
            post_ref = "fresh1"
            creation_time = sydney_now().timestamp() - 86400
            text = ("📅 Valid until 12 September\n"
                    "🥬 Cos Lettuce – 99¢ each")
            image_urls: list = []

        sent = []
        with tf.TemporaryDirectory() as tmp:
            with patch.object(ld, "SCAN_STATE_PATH",
                              Path(tmp) / "s.json"), \
                    patch("extractors.fb_timeline_fetch."
                          "fetch_timeline_posts",
                          return_value=[_P()]), \
                    patch.object(ld, "_send_message",
                                 side_effect=lambda *a, **k:
                                 sent.append(a[2] if len(a) > 2
                                             else k.get("text", ""))
                                 or {"ok": True}):
                ld._save_scan_state({})
                rc = ld.run_daily_scan(send=True)
        self.assertEqual(rc, 0)
        self.assertEqual(len(sent), 4)      # one per store
        self.assertIn("valid until:", sent[0])
        self.assertIn("posted:", sent[0])   # posted time remembered
        self.assertIn("ignore", sent[0])    # skip instruction

    def test_first_sighting_older_than_backfill_silent(self):
        import tempfile as tf
        from core import local_deals as ld

        class _P:
            post_ref = "ancient"
            creation_time = 1_000_000_000   # decades old
            text = ""
            image_urls: list = []

        sent = []
        with tf.TemporaryDirectory() as tmp:
            with patch.object(ld, "SCAN_STATE_PATH",
                              Path(tmp) / "s.json"), \
                    patch("extractors.fb_timeline_fetch."
                          "fetch_timeline_posts",
                          return_value=[_P()]), \
                    patch.object(ld, "_send_message",
                                 side_effect=lambda *a, **k:
                                 sent.append(a[2] if len(a) > 2
                                             else k.get("text", ""))
                                 or {"ok": True}):
                ld._save_scan_state({})
                rc = ld.run_daily_scan(send=True)
        self.assertEqual(rc, 0)
        self.assertEqual(sent, [])          # too old: silent baseline

    def test_ignore_marks_and_scan_skips(self):
        import tempfile as tf
        from core import local_deals as ld

        class _P:
            post_ref = "fresh1"
            creation_time = None
            text = ""
            image_urls: list = []

        with tf.TemporaryDirectory() as tmp:
            with patch.object(ld, "SCAN_STATE_PATH",
                              Path(tmp) / "s.json"), \
                    patch("extractors.fb_timeline_fetch."
                          "fetch_timeline_posts",
                          return_value=[_P()]):
                # baseline with a notified post (simulate: notify
                # then overwrite notified ref via state surgery)
                ld._save_scan_state({})
                with patch.object(ld, "_send_message",
                                  return_value={"ok": True}):
                    ld.run_daily_scan(send=True)
                state = ld._load_scan_state()
                for store in state["stores"].values():
                    store["last_notified_ref"] = "fresh1"
                ld._save_scan_state(state)

                rc = ld.ignore_post("FRUT")
                state = ld._load_scan_state()
                ignored = state["stores"]["fruitopia"]["ignored"]
        self.assertEqual(rc, 0)
        self.assertIn("fresh1", ignored)

    def test_ingest_picks_newest_text_file(self):
        import tempfile as tf
        from core import local_deals as ld
        code = "FRUT"
        with tf.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / code
            inbox.mkdir(parents=True)
            (inbox / "old.txt").write_text(
                "Old post, nothing parseable here", encoding="utf-8")
            newer = inbox / "new.txt"
            newer.write_text(
                "📅 Valid 5 & 6 September\n"
                "🥬 Cos Lettuce – 99¢ each\n", encoding="utf-8")
            import os
            os.utime(inbox / "old.txt", (1, 1))
            with patch.object(ld, "INBOX_DIR", Path(tmp)), \
                    patch.object(ld, "_send_message",
                                 return_value={"ok": True}):
                rc = ld.ingest_code(code)
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
