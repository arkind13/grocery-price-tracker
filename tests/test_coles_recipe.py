#!/usr/bin/env python3
"""Unit tests for the Coles Scrape.do credit-guard recipe (spec B4).

Covers plan matrix C-1..C-16 plus the IN-6 product-id probes. No real
network: requests.get and time.sleep are mocked; the breaker health
file lives in a temp dir; the clock is injected via ce._now.
"""
from __future__ import annotations
import io
import json
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from extractors import coles_extractor as ce  # noqa: E402
from extractors import woolworths_extractor as wwe  # noqa: E402


class FakeResponse:
    """Minimal requests.Response stand-in."""

    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


def next_data_html(results):
    """Wrap Coles search results in a __NEXT_DATA__ HTML page."""
    payload = {
        "props": {"pageProps": {"searchResults": {"results": results}}}
    }
    return (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload)}</script></html>"
    )


def make_product(name="Coles Full Cream Milk 2L", price=3.80, was=0,
                 size="2L", pid="998877"):
    """Build one raw Coles search-result product dict."""
    pricing = {"now": price}
    if was:
        pricing["was"] = was
    return {
        "_type": "PRODUCT",
        "name": name,
        "size": size,
        "pricing": pricing,
        "id": pid,
    }


class ColesRecipeTestCase(unittest.TestCase):
    """Base: isolates health file, key, counter, sleep; mocks HTTP."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.health_path = Path(self._tmp.name) / "scrapedo_health.json"
        self._patchers = [
            patch.object(ce, "SCRAPEDO_HEALTH_PATH", self.health_path),
            patch.object(ce, "SCRAPEDO_API_KEY", "testtoken"),
            patch.object(ce, "_calls_this_run", 0),
            patch.object(ce, "_session_seq", 0),
        ]
        for p in self._patchers:
            p.start()
        self.sleeps = []
        self._sleep_patcher = patch.object(
            ce.time, "sleep", side_effect=self.sleeps.append)
        self._sleep_patcher.start()

    def tearDown(self):
        self._sleep_patcher.stop()
        for p in reversed(self._patchers):
            p.stop()
        self._tmp.cleanup()

    def http_mock(self, side_effect):
        """Patch ce.requests.get; returns the mock."""
        mock = patch.object(ce.requests, "get", side_effect=side_effect)
        mocked = mock.start()
        self.addCleanup(mock.stop)
        return mocked


class TestParamsAndSessions(ColesRecipeTestCase):
    """C-1..C-3: param shape + session uniqueness."""

    def test_c1_params_include_super_geocode_session(self):
        """C-1: params include super=true, geoCode=au, session, token."""
        params = ce._build_scrapedo_params("milk", "coles_123_7")
        self.assertEqual(params["super"], "true")
        self.assertEqual(params["geoCode"], "au")
        self.assertEqual(params["session"], "coles_123_7")
        self.assertEqual(params["token"], "testtoken")
        self.assertIn("search?q=milk", params["url"])

    def test_c2_params_have_no_render_country_wait(self):
        """C-2: params contain NO render / country / wait keys."""
        params = ce._build_scrapedo_params("milk", "coles_123_7")
        self.assertNotIn("render", params)
        self.assertNotIn("country", params)
        self.assertNotIn("wait", params)

    def test_c3_sessions_unique_per_call(self):
        """C-3: two calls -> distinct coles_<epoch>_<n> session ids."""
        import re
        s1 = ce._fresh_session()
        s2 = ce._fresh_session()
        self.assertNotEqual(s1, s2)
        for s in (s1, s2):
            self.assertRegex(s, r"^coles_\d+_\d+$")


class TestRetryChain(ColesRecipeTestCase):
    """C-4..C-9: retry + backoff + auth-fail semantics."""

    def test_c4_5xx_retries_with_new_session_then_succeeds(self):
        """C-4: 5xx attempt 1 -> retry NEW session; success on 2."""
        ok = FakeResponse(200, next_data_html([make_product()]))
        mock = self.http_mock(side_effect=[FakeResponse(500), ok])
        items, status = ce.fetch_coles_search_status("milk")
        self.assertEqual(status, "ok")
        self.assertEqual(len(items), 1)
        self.assertEqual(mock.call_count, 2)
        sessions = [c.kwargs["params"]["session"]
                    for c in mock.call_args_list]
        self.assertNotEqual(sessions[0], sessions[1])

    def test_c5_backoff_sequence_exactly_3_then_6(self):
        """C-5: backoff sequence exactly sleep(3), sleep(6)."""
        self.http_mock(side_effect=lambda *a, **k: FakeResponse(500))
        ce.fetch_coles_search_status("milk")
        self.assertEqual(self.sleeps, [3, 6])

    def test_c6_all_3_attempts_fail_unavailable(self):
        """C-6: all 3 attempts 5xx -> unavailable, [], exactly 3 calls."""
        mock = self.http_mock(side_effect=lambda *a, **k: FakeResponse(500))
        items, status = ce.fetch_coles_search_status("milk")
        self.assertEqual(status, "unavailable")
        self.assertEqual(items, [])
        self.assertEqual(mock.call_count, 3)

    def test_c7_401_never_retried(self):
        """C-7: 401 -> NO retry (exactly 1 call), unavailable."""
        mock = self.http_mock(side_effect=lambda *a, **k: FakeResponse(401))
        items, status = ce.fetch_coles_search_status("milk")
        self.assertEqual(status, "unavailable")
        self.assertEqual(mock.call_count, 1)
        self.assertEqual(self.sleeps, [])

    def test_c8_403_never_retried(self):
        """C-8: 403 -> NO retry (exactly 1 call)."""
        mock = self.http_mock(side_effect=lambda *a, **k: FakeResponse(403))
        _, status = ce.fetch_coles_search_status("milk")
        self.assertEqual(status, "unavailable")
        self.assertEqual(mock.call_count, 1)

    def test_c9_timeout_exception_retries_like_5xx(self):
        """C-9: requests.RequestException retries (3 total, [3,6])."""
        mock = self.http_mock(
            side_effect=ce.requests.ConnectionError("timed out"))
        items, status = ce.fetch_coles_search_status("milk")
        self.assertEqual(status, "unavailable")
        self.assertEqual(items, [])
        self.assertEqual(mock.call_count, 3)
        self.assertEqual(self.sleeps, [3, 6])


class TestBreakerAndCap(ColesRecipeTestCase):
    """C-10..C-13, C-16: breaker + per-run cap."""

    def _fail_chain(self):
        """One all-500 chain; returns (status, call_count_delta)."""
        before = self._calls()

        def fail_once():
            with patch.object(ce, "_calls_this_run", ce._calls_this_run):
                mock = self.http_mock(
                    side_effect=lambda *a, **k: FakeResponse(500))
                status = ce.fetch_coles_search_status("milk")[1]
                count = mock.call_count
            return status, count
        return fail_once()

    def _calls(self):
        """Current module HTTP-attempt counter value."""
        return ce._calls_this_run

    def test_c10_breaker_opens_after_3_failed_chains(self):
        """C-10: 3 consecutive failed chains -> open; next call: 0 HTTP."""
        total = 0
        for _ in range(3):
            mock = self.http_mock(
                side_effect=lambda *a, **k: FakeResponse(500))
            status = ce.fetch_coles_search_status("milk")[1]
            self.assertEqual(status, "unavailable")
            total += mock.call_count
        # Breaker now open: next call makes ZERO HTTP requests.
        mock = self.http_mock(
            side_effect=lambda *a, **k: FakeResponse(500))
        items, status = ce.fetch_coles_search_status("milk")
        self.assertEqual(status, "breaker_open")
        self.assertEqual(items, [])
        self.assertEqual(mock.call_count, 0)
        state = json.loads(self.health_path.read_text(encoding="utf-8"))
        self.assertGreater(state["open_until"], 0)

    def test_c11_breaker_closes_after_cooldown(self):
        """C-11: open breaker + _now advanced 601 s -> closed again."""
        self.http_mock(side_effect=lambda *a, **k: FakeResponse(500))
        for _ in range(3):
            ce.fetch_coles_search_status("milk")
        with patch.object(ce, "_now", return_value=ce._now() + 601):
            ok = FakeResponse(200, next_data_html([make_product()]))
            self.http_mock(side_effect=lambda *a, **k: ok)
            items, status = ce.fetch_coles_search_status("milk")
        self.assertEqual(status, "ok")
        self.assertEqual(len(items), 1)

    def test_c12_success_resets_fail_streak(self):
        """C-12: fail, fail, success, fail, fail -> still closed."""
        ok = FakeResponse(200, next_data_html([make_product()]))
        chains = ([FakeResponse(500), FakeResponse(500)],
                  [ok],
                  [FakeResponse(500), FakeResponse(500)])
        for chain in chains:
            for response in chain:
                self.http_mock(side_effect=lambda *a, _r=response, **k: _r)
                status = ce.fetch_coles_search_status("milk")[1]
                self.assertIn(status, ("ok", "unavailable"))
                self.assertNotEqual(status, "breaker_open")
        # Streak was reset by the success: breaker still closed.
        self.assertFalse(ce._breaker_is_open())

    def test_c13_per_run_cap(self):
        """C-13: cap reached -> cap_exceeded with message, no HTTP."""
        ok = FakeResponse(200, next_data_html([make_product()]))
        with patch.object(ce, "SCRAPEDO_MAX_CALLS_PER_RUN", 2):
            mock = self.http_mock(side_effect=lambda *a, **k: ok)
            s1 = ce.fetch_coles_search_status("milk")[1]
            s2 = ce.fetch_coles_search_status("milk")[1]
            err = io.StringIO()
            with redirect_stderr(err):
                items, s3 = ce.fetch_coles_search_status("milk")
        self.assertEqual((s1, s2), ("ok", "ok"))
        self.assertEqual(s3, "cap_exceeded")
        self.assertEqual(items, [])
        self.assertEqual(mock.call_count, 2)  # no HTTP on the capped call
        self.assertIn(
            "Scrape.do per-run cap (2) reached — stopping Coles calls.",
            err.getvalue())

    def test_c16_corrupt_health_file_treated_healthy(self):
        """C-16: corrupt breaker file -> closed/streak 0, no raise."""
        self.health_path.write_text("{not json", encoding="utf-8")
        self.assertFalse(ce._breaker_is_open())
        mock = self.http_mock(side_effect=lambda *a, **k: FakeResponse(500))
        items, status = ce.fetch_coles_search_status("milk")
        self.assertEqual(status, "unavailable")
        self.assertEqual(items, [])
        self.assertEqual(mock.call_count, 3)


class TestParseAndWrappers(ColesRecipeTestCase):
    """C-14..C-15 + IN-6 probes."""

    def test_c14_status_parses_next_data_fixture(self):
        """C-14: __NEXT_DATA__ fixture -> ProductItems w/ price/special/size."""
        results = [
            make_product(name="Coles Milk 2L", price=3.80, was=4.50,
                         size="2L", pid="111222"),
            {"_type": "BANNER", "name": "Half price sale"},
        ]
        self.http_mock(
            side_effect=lambda *a, **k: FakeResponse(
                200, next_data_html(results)))
        items, status = ce.fetch_coles_search_status("milk")
        self.assertEqual(status, "ok")
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.store, "coles")
        self.assertEqual(item.raw_name, "Coles Milk 2L")
        self.assertEqual(item.price, 3.80)
        self.assertTrue(item.is_special)
        self.assertEqual(item.special_desc, "Was $4.50")
        self.assertEqual(item.size, "2L")
        self.assertEqual(item.product_id, "111222")

    def test_c15_legacy_wrapper_returns_plain_list(self):
        """C-15: fetch_coles_search still returns a plain list."""
        results = [make_product(), make_product(name="Coles Milk 3L",
                                                pid="445566")]
        self.http_mock(
            side_effect=lambda *a, **k: FakeResponse(
                200, next_data_html(results)))
        items = ce.fetch_coles_search("milk")
        self.assertIsInstance(items, list)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[1].product_id, "445566")

    def test_c15b_empty_result_set_is_empty_status(self):
        """IN-1: search OK but 0 hits -> status 'empty' (not unavailable)."""
        self.http_mock(side_effect=lambda *a, **k: FakeResponse(
            200, next_data_html([])))
        items, status = ce.fetch_coles_search_status("xyzzy")
        self.assertEqual(status, "empty")
        self.assertEqual(items, [])

    def test_ww_search_probe_captures_stockcode(self):
        """IN-6: WW search parser probes ArticleId/Stockcode."""
        payload = {"Products": [{"Products": [{
            "Stockcode": 123456,
            "DisplayName": "Woolworths Milk 2L",
            "Price": 3.10,
            "PackageSize": "2L",
        }]}]}

        class FakeCffiResp:
            status_code = 200

            def json(self):
                return payload

        fake_requests = types.SimpleNamespace(
            get=lambda *a, **k: FakeCffiResp())
        fake_curl_cffi = types.SimpleNamespace(requests=fake_requests)
        with patch.dict(sys.modules, {"curl_cffi": fake_curl_cffi}):
            items = wwe.fetch_woolworths_search_noauth("milk", page_size=5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].product_id, "123456")
        self.assertEqual(items[0].size, "2L")

    def test_coles_parse_probe_key_variants(self):
        """IN-6/IN-10: id / productId / _id probes; absence stays ''."""
        base = {"name": "Coles Milk 2L", "pricing": {"now": 3.1}}
        self.assertEqual(ce._parse_search_result(
            {**base, "productId": "A1"}).product_id, "A1")
        self.assertEqual(ce._parse_search_result(
            {**base, "_id": "X9"}).product_id, "X9")
        self.assertEqual(
            ce._parse_search_result(dict(base)).product_id, "")


if __name__ == "__main__":
    unittest.main()
