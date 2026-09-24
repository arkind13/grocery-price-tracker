"""Classified Telegram sender for the scheduled jobs (2026-09-24
user ruling: 'it needs to understand why it failed — if it failed
for a valid reason, 1000s of retries will not fix it').

One sendMessage with a VERDICT, not just ok/failed:

  receipt["error_class"] ==
    "retry"     — transient (network, timeout, Telegram 429 flood
                  wait, 5xx): the caller's hourly retry window is
                  the right cure. retry_after carries Telegram's own
                  seconds hint when present.
    "permanent" — a real error retrying cannot fix: bad token (401),
                  bot blocked/kicked (403), chat/topic not found,
                  message too long (400). The caller must STOP
                  retrying, record the reason, and surface it.

Never raises; never prints (the callers own timestamped logging).
Stdlib only; Python 3.11 (VPS container).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 30

RETRYABLE_HTTP = {429, 500, 502, 503, 504}


def _receipt(ok: bool = False, message_id=None, error_class="",
             error="", retry_after=None, chat_id=None,
             thread_id=None) -> dict:
    return {"ok": ok, "message_id": message_id,
            "error_class": error_class, "error": error,
            "retry_after": retry_after, "chat_id": chat_id,
            "thread_id": thread_id}


def classify_api_error(error_code, description, parameters) -> dict:
    """Telegram's JSON error body -> classified receipt (no send)."""
    code = int(error_code or 0)
    desc = str(description or "").strip()
    retry_after = None
    if isinstance(parameters, dict) \
            and parameters.get("retry_after") is not None:
        try:
            retry_after = int(parameters["retry_after"])
        except (TypeError, ValueError):
            retry_after = None
    if code == 429:
        hint = f"flood wait {retry_after}s" if retry_after \
            else "flood wait"
        return _receipt(error_class="retry", retry_after=retry_after,
                        error=f"429 {hint}: {desc}")
    if code in RETRYABLE_HTTP:
        return _receipt(error_class="retry",
                        error=f"{code} {desc}")
    # 400 (message too long / thread not found / chat not found),
    # 401 (bad token), 403 (bot blocked or kicked) and any other
    # 4xx: retrying cannot change the outcome.
    return _receipt(error_class="permanent",
                    error=f"{code} {desc}".strip())


def classify_exception(exc: Exception) -> dict:
    """Transport-level failure (no HTTP body) -> classified receipt."""
    if isinstance(exc, urllib.error.HTTPError):
        body = {}
        try:
            body = json.loads(
                exc.read().decode("utf-8", "replace")) or {}
        except Exception:                      # noqa: BLE001
            body = {}
        return classify_api_error(
            body.get("error_code", exc.code),
            body.get("description") or str(exc.reason or exc),
            body.get("parameters"))
    if isinstance(exc, (urllib.error.URLError, TimeoutError,
                        OSError)):
        return _receipt(error_class="retry",
                        error=f"network: "
                              f"{exc.__class__.__name__}")
    return _receipt(error_class="retry",
                    error=f"unexpected: "
                          f"{exc.__class__.__name__}")


def send_classified(bot_token: str, chat_id, text: str,
                    thread_id=None) -> dict:
    """One sendMessage; a classified receipt whatever happens.

    An absent token is PERMANENT (retrying without a token is
    pointless) — mirrors the 'no bot token — not sent' line the old
    senders printed, but as a machine-checkable verdict.
    """
    if not bot_token:
        return _receipt(error_class="permanent",
                        error="no bot token configured",
                        chat_id=chat_id, thread_id=thread_id)
    body: dict = {"chat_id": chat_id, "text": text}
    if thread_id is not None:
        body["message_thread_id"] = thread_id
    try:
        req = urllib.request.Request(
            "https://api.telegram.org/bot"
            f"{bot_token}/sendMessage",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(
                req, timeout=TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:                   # noqa: BLE001
        receipt = classify_exception(exc)
        receipt["chat_id"] = chat_id
        receipt["thread_id"] = thread_id
        return receipt
    if data.get("ok"):
        msg = data.get("result") or {}
        return _receipt(ok=True,
                        message_id=msg.get("message_id"),
                        chat_id=(msg.get("chat") or {}).get("id",
                                                           chat_id),
                        thread_id=thread_id)
    receipt = classify_api_error(data.get("error_code"),
                                 data.get("description"),
                                 data.get("parameters"))
    receipt["chat_id"] = chat_id
    receipt["thread_id"] = thread_id
    return receipt
