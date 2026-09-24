"""core.telegram_send — the 2026-09-24 classified sender ('it needs
to understand WHY it failed — if it failed for a valid reason 1000s
of retries will not fix it'): every Telegram transport outcome maps
to a retry vs permanent verdict with the reason attached. Offline —
urlopen mocked; zero network."""
from __future__ import annotations
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core import telegram_send as ts          # noqa: E402

TOKEN = "123:fake"
CHAT = -1004394070843


def _ok_response(message_id=555):
    body = {"ok": True,
            "result": {"message_id": message_id,
                       "chat": {"id": CHAT}}}

    class _Resp:
        def read(self):
            return json.dumps(body).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _Resp()


def _http_error(error_code, description, parameters=None):
    body = {"ok": False, "error_code": error_code,
            "description": description}
    if parameters is not None:
        body["parameters"] = parameters
    return urllib.error.HTTPError(
        "https://api.telegram.org/bot123:fake/sendMessage",
        error_code, description, None,
        io.BytesIO(json.dumps(body).encode("utf-8")))


class TestClassifiedSend(unittest.TestCase):
    def test_success_receipt(self):
        with patch.object(ts.urllib.request, "urlopen",
                          return_value=_ok_response(555)):
            r = ts.send_classified(TOKEN, CHAT, "hello", thread_id=206)
        self.assertTrue(r["ok"])
        self.assertEqual(r["message_id"], 555)
        self.assertEqual(r["error_class"], "")
        self.assertEqual(r["thread_id"], 206)

    def test_flood_wait_429_is_retry_with_seconds_hint(self):
        err = _http_error(429, "Too Many Requests: retry after 17",
                          {"retry_after": 17})
        with patch.object(ts.urllib.request, "urlopen",
                          side_effect=err):
            r = ts.send_classified(TOKEN, CHAT, "hello")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error_class"], "retry")
        self.assertEqual(r["retry_after"], 17)
        self.assertIn("17", r["error"])

    def test_server_5xx_is_retry(self):
        for code in (500, 502, 503):
            err = _http_error(code, "Internal Server Error")
            with patch.object(ts.urllib.request, "urlopen",
                              side_effect=err):
                r = ts.send_classified(TOKEN, CHAT, "hello")
            self.assertEqual(r["error_class"], "retry", str(code))

    def test_bot_kicked_403_is_permanent(self):
        err = _http_error(403, "Forbidden: bot was kicked from "
                               "the supergroup chat")
        with patch.object(ts.urllib.request, "urlopen",
                          side_effect=err):
            r = ts.send_classified(TOKEN, CHAT, "hello")
        self.assertEqual(r["error_class"], "permanent")
        self.assertIn("kicked", r["error"])

    def test_message_too_long_400_is_permanent(self):
        err = _http_error(400, "Bad Request: message is too long")
        with patch.object(ts.urllib.request, "urlopen",
                          side_effect=err):
            r = ts.send_classified(TOKEN, CHAT, "x" * 5000)
        self.assertEqual(r["error_class"], "permanent")
        self.assertIn("too long", r["error"])

    def test_bad_token_401_is_permanent(self):
        err = _http_error(401, "Unauthorized")
        with patch.object(ts.urllib.request, "urlopen",
                          side_effect=err):
            r = ts.send_classified("bad:token", CHAT, "hello")
        self.assertEqual(r["error_class"], "permanent")

    def test_network_error_is_retry(self):
        for exc in (urllib.error.URLError("route broken"),
                    TimeoutError("timed out"),
                    OSError("connection reset")):
            with patch.object(ts.urllib.request, "urlopen",
                              side_effect=exc):
                r = ts.send_classified(TOKEN, CHAT, "hello")
            self.assertEqual(r["error_class"], "retry",
                             exc.__class__.__name__)

    def test_missing_token_is_permanent(self):
        """Retrying without a token configured is pointless."""
        r = ts.send_classified("", CHAT, "hello")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error_class"], "permanent")
        self.assertIn("no bot token", r["error"])

    def test_never_raises(self):
        with patch.object(ts.urllib.request, "urlopen",
                          side_effect=RuntimeError("weird")):
            r = ts.send_classified(TOKEN, CHAT, "hello")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error_class"], "retry")   # unknown -> retry


if __name__ == "__main__":
    unittest.main()
