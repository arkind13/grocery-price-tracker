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
    """Twice-daily new-post detector (user spec 2026-09-06)."""

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

    def test_lifecycle_codes_and_plain_message(self):
        """Backfill notifies all four shops; repeat silent; a post
        created AFTER the last alert gets a fresh timestamped code
        (user rule 2026-09-07: <shop><ddmmyy><HHMM> of the alert).
        Deterministic via an injected advancing clock — also immune
        to running the suite inside a 05/15 scan window."""
        import tempfile as tf
        from datetime import datetime as _dtmod, timedelta as _td
        from zoneinfo import ZoneInfo as _ZI
        from core import local_deals as ld

        class _Clock:
            def __init__(self, start):
                self.now = start

            def __call__(self):
                return self.now

        clock = _Clock(_dtmod(2026, 9, 7, 9, 7,
                              tzinfo=_ZI("Australia/Sydney")))
        refs = {}
        offsets = {}     # ref -> seconds ago it was created

        class _P:
            def __init__(self, ref, created):
                self.post_ref = ref
                self.creation_time = created
                self.text = ("Valid until 12 September\n"
                             "Cos Lettuce \u2013 99\u00a2 each")
                self.image_urls: list = []

        def fake_fetch(store, *, max_posts=1, **kw):
            ref = fake_fetch.ref
            created = clock.now.timestamp() - offsets[ref]
            return [_P(ref, created)]

        sent = []
        with tf.TemporaryDirectory() as tmp:
            with patch.object(ld, "SCAN_STATE_PATH",
                              Path(tmp) / "s.json"), \
                    patch.object(ld, "sydney_now", clock), \
                    patch("extractors.fb_timeline_fetch."
                          "fetch_timeline_posts",
                          side_effect=fake_fetch), \
                    patch.object(ld, "_send_message",
                                 side_effect=lambda *a, **k:
                                 sent.append(a[2] if len(a) > 2
                                             else k.get("text", ""))
                                 or {"ok": True}):
                for key, code in (("fruitopia", "FRU"),
                                  ("merjan", "MER"),
                                  ("dunya", "DUN"),
                                  ("abusalim", "ABS")):
                    refs[key] = f"{code}-p1"
                    offsets[f"{code}-p1"] = 3600.0
                fake_fetch.ref = refs["fruitopia"]
                ld._save_scan_state({})
                ld.run_daily_scan(send=True, force=True)  # backfill
                n_after_first = len(sent)
                clock.now += _td(minutes=1)
                fake_fetch.ref = refs["fruitopia"]
                ld.run_daily_scan(send=True, force=True)  # silent
                n_after_repeat = len(sent)
                clock.now += _td(minutes=9)      # 09:17
                for key in refs:
                    refs[key] = refs[key] + "-new"
                    offsets[refs[key]] = 30.0   # after the last alert
                    fake_fetch.ref = refs[key]
                ld.run_daily_scan(send=True, force=True)  # new codes
        self.assertEqual(n_after_first, 4)
        self.assertEqual(n_after_repeat, n_after_first)
        self.assertEqual(len(sent), 8)
        first = [t for t in sent if "code: FRU0709260907)" in t]
        self.assertEqual(len(first), 1)
        self.assertIn("When posted:", first[0])
        self.assertIn("Valid until: Sat 12 Sep", first[0])
        self.assertIn("ignore FRU0709260907", first[0])
        delta = [t for t in sent if "code: FRU0709260917)" in t]
        self.assertEqual(len(delta), 1)

    def test_first_sighting_older_than_backfill_silent(self):
        import tempfile as tf
        from core import local_deals as ld

        class _P:
            post_ref = "ancient"
            creation_time = 1_000_000_000
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
                rc = ld.run_daily_scan(send=True, force=True)
        self.assertEqual(rc, 0)
        self.assertEqual(sent, [])

    def test_ignore_marks_and_scan_skips(self):
        import tempfile as tf
        from core import local_deals as ld
        from core.sydney_time import sydney_now

        class _P:
            post_ref = "fresh1"
            creation_time = sydney_now().timestamp() - 3600
            text = ""
            image_urls: list = []

        with tf.TemporaryDirectory() as tmp:
            with patch.object(ld, "SCAN_STATE_PATH",
                              Path(tmp) / "s.json"), \
                    patch("extractors.fb_timeline_fetch."
                          "fetch_timeline_posts",
                          return_value=[_P()]):
                ld._save_scan_state({})
                with patch.object(ld, "_send_message",
                                  return_value={"ok": True}):
                    ld.run_daily_scan(send=True, force=True)  # notifies
                code = ld._load_scan_state()["stores"]["fruitopia"][
                    "notified"]["fresh1"]
                rc = ld.ignore_post(code)
                state = ld._load_scan_state()
                ignored = state["stores"]["fruitopia"]["ignored"]
                notified = state["stores"]["fruitopia"]["notified"]
                self.assertEqual(rc, 0)
                self.assertIn("fresh1", ignored)
                self.assertNotIn("fresh1", notified)
                sent = []
                with patch.object(ld, "_send_message",
                                  side_effect=lambda *a, **k:
                                  sent.append(1) or {"ok": True}):
                    ld.run_daily_scan(send=True, force=True)  # quiet
                self.assertEqual(sent, [])

    def test_code_is_alert_time_not_post_time(self):
        """User rule 2026-09-07: the code stamps the ALERT (scan)
        time — FRU0709260907 = Fruitopia alerted 07 Sep 26 09:07 —
        even when the post itself was made hours earlier."""
        import tempfile as tf
        from datetime import datetime as _dtmod
        from zoneinfo import ZoneInfo as _ZI
        from core import local_deals as ld

        posted = _dtmod(2026, 9, 6, 20, 15,
                        tzinfo=_ZI("Australia/Sydney"))

        class _P:
            post_ref = "p-old"
            creation_time = posted.timestamp()
            text = ""
            image_urls: list = []

        def fake_fetch(store, *, max_posts=1, **kw):
            return [_P()]

        sent = []
        with tf.TemporaryDirectory() as tmp:
            with patch.object(ld, "SCAN_STATE_PATH",
                              Path(tmp) / "s.json"), \
                    patch.object(ld, "sydney_now",
                                 lambda: _dtmod(
                                     2026, 9, 7, 9, 7,
                                     tzinfo=_ZI("Australia/Sydney"))), \
                    patch("extractors.fb_timeline_fetch."
                          "fetch_timeline_posts",
                          side_effect=fake_fetch), \
                    patch.object(ld, "_send_message",
                                 side_effect=lambda *a, **k:
                                 sent.append(a[2] if len(a) > 2
                                             else k.get("text", ""))
                                 or {"ok": True}):
                ld._save_scan_state({})
                ld.run_daily_scan(send=True, force=True)
        fru = [t for t in sent if "code: FRU" in t]
        self.assertEqual(len(fru), 1)
        self.assertIn("code: FRU0709260907)", fru[0])   # alert stamp
        self.assertIn("When posted: Sun 06 Sep, 08:15 PM", fru[0])

    def test_missed_window_two_posts_both_notified(self):
        """The user's missed-run scenario: a window is skipped and the
        shop posts TWICE before the next scan — BOTH posts are
        reported (newest first), each with its own unique code."""
        import tempfile as tf
        from datetime import datetime as _dtmod, timedelta as _td
        from zoneinfo import ZoneInfo as _ZI
        from core import local_deals as ld

        class _Clock:
            def __init__(self, start):
                self.now = start

            def __call__(self):
                return self.now

        clock = _Clock(_dtmod(2026, 9, 7, 9, 7,
                              tzinfo=_ZI("Australia/Sydney")))

        class _P:
            def __init__(self, ref, created):
                self.post_ref = ref
                self.creation_time = created
                self.text = ""
                self.image_urls: list = []

        # ref -> seconds before the CURRENT clock it was created
        state_refs = {"p1": 3600.0}

        def fake_fetch(store, *, max_posts=3, **kw):
            # newest first, as the timeline returns them
            return [_P(ref, clock.now.timestamp() - off)
                    for ref, off in state_refs.items()]

        sent = []
        with tf.TemporaryDirectory() as tmp:
            with patch.object(ld, "SCAN_STATE_PATH",
                              Path(tmp) / "s.json"), \
                    patch.object(ld, "sydney_now", clock), \
                    patch("extractors.fb_timeline_fetch."
                          "fetch_timeline_posts",
                          side_effect=fake_fetch), \
                    patch.object(ld, "_send_message",
                                 side_effect=lambda *a, **k:
                                 sent.append(a[2] if len(a) > 2
                                             else k.get("text", ""))
                                 or {"ok": True}):
                ld._save_scan_state({})
                ld.run_daily_scan(send=True, force=True)  # baseline p1
                # Missed windows: the shop posts p3 (14:00) and p2
                # (11:00); the 15:07 scan sees both, none reported.
                clock.now += _td(hours=6)                 # 15:07
                state_refs = {"p3": 4020.0, "p2": 14820.0}
                ld.run_daily_scan(send=True, force=True)
        fru = [t for t in sent if "(code: FRU" in t]
        self.assertEqual(len(fru), 3)      # baseline + two deltas
        self.assertIn("code: FRU0709261507)", fru[1])     # p3 newest
        self.assertIn("code: FRU0709261507_2)", fru[2])   # p2 next


class TestMergeStoreTab(unittest.TestCase):
    """Ingest sheet write: merge, never wipe other stores."""

    class _FakeTab:
        def __init__(self, grid):
            self.grid = grid
            self.updates = []

        def get_all_values(self):
            return [list(r) for r in self.grid]

        def clear(self):
            pass

        def freeze(self, rows=1):
            pass

        def update(self, values, range_name):
            self.grid = values
            self.updates.append(range_name)

    def _existing(self):
        return [
            ["Product", "Dunya (site)", "Dunya FB specials",
             "Merjan Brothers Quality Meats",
             "Fruitopia Mt Druitt", "Abu Salim Fruit Market",
             "Comments"],
            ["FRUITS", "", "", "", "", "", ""],
            ["Apples", "", "", "", 3.2, "", ""],
            ["BUTCHERY", "", "", "", "", "", ""],
            ["Beef Diced", 12.99, "", "", "", "", ""],
        ]

    def test_merge_updates_and_appends_without_wiping(self):
        from core import local_deals as ld
        tab = self._FakeTab(self._existing())
        deals = [
            {"item": "Apples", "raw_text": "Apples 3.2",
             "price": 3.2, "unit": "kg",
             "price_kind": "single", "multibuy_qty": None,
             "bulk_size": None, "category": "fruits",
             "notes": ""},
            {"item": "Cos Lettuce", "raw_text": "Cos Lettuce 99c",
             "price": 0.99, "unit": "ea",
             "price_kind": "single", "multibuy_qty": None,
             "bulk_size": None, "category": "fruits",
             "notes": ""},
        ]
        rows = ld.merge_store_tab(tab, "fruitopia", deals)
        self.assertGreater(rows, 0)
        grid = tab.grid
        apples = next(r for r in grid
                      if r and str(r[0]).strip() == "Apples")
        self.assertEqual(apples[4], 3.2)            # updated (Fruitopia col)
        self.assertEqual(apples[1], "")             # Dunya intact
        beef = next(r for r in grid
                    if r and str(r[0]).strip() == "Beef Diced")
        self.assertEqual(beef[1], 12.99)            # untouched
        lettuce = next(r for r in grid
                       if str(r[0]).strip().startswith("Cos Lettuce"))
        self.assertEqual(lettuce[4], 0.99)          # appended
        idx_f = next(i for i, r in enumerate(grid)
                     if r and r[0] == "FRUITS")
        idx_b = next(i for i, r in enumerate(grid)
                     if r and r[0] == "BUTCHERY")
        idx_l = next(i for i, r in enumerate(grid)
                     if str(r[0]).strip().startswith("Cos Lettuce"))
        self.assertTrue(idx_f < idx_l < idx_b)      # inside block


class TestIngestFlow(unittest.TestCase):
    """ingest_code: newest file, sheet merge, code freed."""

    class _FakeTab:
        def __init__(self, grid):
            self.grid = grid
            self.updates = []

        def get_all_values(self):
            return [list(r) for r in self.grid]

        def clear(self):
            pass

        def freeze(self, rows=1):
            pass

        def update(self, values, range_name):
            self.grid = values
            self.updates.append(range_name)

    def test_ingest_updates_sheet_and_frees_code(self):
        import tempfile as tf
        from core import local_deals as ld

        with tf.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / "FRUT"
            inbox.mkdir(parents=True)
            (inbox / "board.txt").write_text(
                "Valid until 12 September\n"
                "Cos Lettuce \u2013 99\u00a2 each\n", encoding="utf-8")
            state = {"stores": {"fruitopia": {
                "baselined": True,
                "notified": {"p1": "FRUT"}}}}
            with patch.object(ld, "INBOX_DIR", Path(tmp)), \
                    patch.object(ld, "SCAN_STATE_PATH",
                                 Path(tmp) / "s.json"), \
                    patch.object(ld, "_save_scan_state"), \
                    patch.object(ld, "_load_scan_state",
                                 return_value=state), \
                    patch("core.sheets_client."
                          "connect_spreadsheet"), \
                    patch.object(ld, "ensure_local_deals_tab",
                                 return_value=self._FakeTab([])), \
                    patch.object(ld, "merge_store_tab",
                                 return_value=5) as mst, \
                    patch.object(ld, "_send_message",
                                 return_value={"ok": True}):
                rc = ld.ingest_code("FRUT")
        self.assertEqual(rc, 0)
        mst.assert_called_once()
        # legacy 4-letter code still resolves; ingest clears the
        # shop's pending codes (the next alert mints a fresh one)
        self.assertNotIn("p1",
                         state["stores"]["fruitopia"]["notified"])


class TestDunyaSiteSync(unittest.TestCase):
    """--dunya-site: catalogue -> Dunya column, offers + changes."""

    class _FakeTab:
        def __init__(self, grid):
            self.grid = grid
            self.updates = []

        def get_all_values(self):
            return [list(r) for r in self.grid]

        def clear(self):
            pass

        def freeze(self, rows=1):
            pass

        def update(self, values, range_name):
            self.grid = values
            self.updates.append(range_name)

    CATALOGUE = [
        {"name": "BEEF MINCE (5KG)", "price": 6499,
         "regular_price": 6499, "categories": [], "unit": ""},
        {"name": "Chicken Skewer (each)", "price": 299,
         "regular_price": 399, "categories": [], "unit": "ea"},
    ]

    def _sync(self, tab, catalogue=None, dry_run=False):
        from core import local_deals as ld
        sent = []
        with patch("extractors.shop_site_catalogue."
                   "get_normalised_catalogue",
                   return_value=catalogue
                   if catalogue is not None else self.CATALOGUE), \
                patch("core.sheets_client.connect_spreadsheet"), \
                patch.object(ld, "ensure_local_deals_tab",
                             return_value=tab), \
                patch.object(ld, "_send_message",
                             side_effect=lambda *a, **k:
                             sent.append(a[2] if len(a) > 2
                                         else k.get("text", ""))
                             or {"ok": True}):
            rc = ld.sync_dunya_site(dry_run=dry_run)
        return rc, sent

    def test_initial_build_cents_converted(self):
        tab = self._FakeTab([])
        rc, sent = self._sync(tab)
        self.assertEqual(rc, 0)
        grid = tab.grid
        beef = next(r for r in grid
                    if str(r[0]).strip().startswith("BEEF MINCE (5KG)"))
        self.assertEqual(beef[1], 64.99)     # 6499 cents -> $64.99
        self.assertIn("1 on offer", sent[0])
        self.assertIn("Chicken Skewer", sent[0])

    def test_second_run_reports_price_changes(self):
        tab = self._FakeTab([])
        self._sync(tab)
        cheaper = [dict(d) for d in self.CATALOGUE]
        cheaper[0]["price"] = 5999             # mince on sale
        sent = []
        with patch("core.local_deals.os.getenv",
                   return_value="dummy"):
            pass
        tab2 = self._FakeTab(tab.grid)
        rc, sent = self._sync(tab2, catalogue=cheaper)
        self.assertEqual(rc, 0)
        beef = next(r for r in tab2.grid
                    if str(r[0]).strip().startswith("BEEF MINCE (5KG)"))
        self.assertEqual(beef[1], 59.99)       # updated in place
        self.assertIn("Price changes", sent[0])
        self.assertIn("59.99", sent[0])

    def test_dry_run_touches_nothing(self):
        tab = self._FakeTab([])
        rc, _sent = self._sync(tab, dry_run=True)
        self.assertEqual(rc, 0)
        self.assertEqual(tab.grid, [])
        self.assertEqual(tab.updates, [])


    def test_multibuy_site_offers_parsed_from_names(self):
        """Meat specials are mostly multi-buys: '2 FOR $30' in the
        name -> multibuy deal, effective rate in the specials cell,
        bundle note in Comments, offer flagged vs regular."""
        tab = self._FakeTab([])
        catalogue = [
            {"name": "Lamb Leg Roast &#8211; 2.5-3kg 2 FOR $30",
             "price": 3000, "regular_price": 4000,
             "categories": [], "unit": "ea"},
        ]
        rc, sent = self._sync(tab, catalogue=catalogue)
        self.assertEqual(rc, 0)
        grid = tab.grid
        lamb = next(r for r in grid
                    if str(r[0]).strip().startswith("Lamb Leg Roast"))
        # clean name (entity decoded, size fragment dropped)
        self.assertEqual(lamb[0], "Lamb Leg Roast /ea")
        # specials cell = effective unit rate ($30 / 2)
        self.assertEqual(lamb[1], 15.0)
        # comments = the bundle note
        self.assertEqual(lamb[6],
                         "[multi buy 2 for $30.00 — $15.00/ea]")
        self.assertIn("1 on offer", sent[0])


class TestScanWindowsAndCutoff(unittest.TestCase):
    """User rules: hourly tick, scans ONLY at 05:00/15:00 Sydney,
    ongoing alerts report only posts made BETWEEN alerts."""

    class _P:
        def __init__(self, ref, created):
            self.post_ref = ref
            self.creation_time = created
            self.text = ""
            self.image_urls: list = []

    def test_off_window_tick_does_not_contact_facebook(self):
        import tempfile as tf
        from core import local_deals as ld
        from core.sydney_time import sydney_now

        now = sydney_now()
        h = (now.hour + 3) % 24
        if h in (5, 15):
            h = (h + 1) % 24
        outside = now.replace(hour=h)
        calls = []

        def fake_fetch(store, *, max_posts=1, **kw):
            calls.append(1)
            return []

        with tf.TemporaryDirectory() as tmp:
            with patch.object(ld, "SCAN_STATE_PATH",
                              Path(tmp) / "s.json"), \
                    patch("extractors.fb_timeline_fetch."
                          "fetch_timeline_posts",
                          side_effect=fake_fetch), \
                    patch("core.local_deals.sydney_now",
                          return_value=outside):
                rc = ld.run_daily_scan(send=False)
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])   # zero FB contact off-window

    def test_between_alerts_window_enforced(self):
        """A new post created BEFORE the last alert is skipped; one
        created AFTER it is notified."""
        import tempfile as tf
        from core import local_deals as ld
        from core.sydney_time import sydney_now

        # ref -> how many seconds ago the post was created
        created_offsets = {}

        def fake_fetch(store, *, max_posts=1, **kw):
            ref = fake_fetch.ref
            created = sydney_now().timestamp() \
                - created_offsets[ref]
            return [self._P(ref, created)]

        sent = []
        with tf.TemporaryDirectory() as tmp:
            with patch.object(ld, "SCAN_STATE_PATH",
                              Path(tmp) / "s.json"), \
                    patch("extractors.fb_timeline_fetch."
                          "fetch_timeline_posts",
                          side_effect=fake_fetch), \
                    patch.object(ld, "_send_message",
                                 side_effect=lambda *a, **k:
                                 sent.append(a[2] if len(a) > 2
                                             else k.get("text", ""))
                                 or {"ok": True}):
                # Baseline: fresh post -> FRU<stamp> notified, cutoff.
                created_offsets.update({"p1": 3600.0})
                fake_fetch.ref = "p1"
                ld._save_scan_state({})
                ld.run_daily_scan(send=True, force=True)
                n1 = len(sent)
                # A DIFFERENT post created BEFORE that alert: new
                # id, but outside the between-alerts window.
                fake_fetch.ref = "p_old"
                created_offsets["p_old"] = 7200.0
                ld.run_daily_scan(send=True, force=True)
                n2 = len(sent)
                # A post created AFTER the alert: notified.
                fake_fetch.ref = "p_new"
                created_offsets["p_new"] = 0.05
                ld.run_daily_scan(send=True, force=True)
                n3 = len(sent)
        self.assertEqual(n1, 4)      # backfill: one per store
        self.assertEqual(n2, n1)     # pre-alert post: silent
        self.assertEqual(n3, n1 + 4) # between-alerts post: notified


if __name__ == "__main__":
    unittest.main()
