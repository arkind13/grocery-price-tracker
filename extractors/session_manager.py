#!/usr/bin/env python3
"""Authentication & Cookie Session Handler for supermarket extraction.

Manages session cookies and HTTP headers for Woolworths and Coles.
Reads credentials from root .env (WOOLWORTHS_COOKIE, COLES_COOKIE).
Supports fallback mode for offline/pasted HTML/JSON payload injection.

Usage:
    from extractors.session_manager import SessionManager
    sm = SessionManager()
    headers = sm.get_headers("woolworths")
    cookies = sm.get_cookies("woolworths")
    sm.is_session_alive("woolworths")  # bool
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# ---------------------------------------------------------------------------
# Path setup: allow import from repo root
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WOOLWORTHS_COOKIE_ENV = "WOOLWORTHS_COOKIE"
COLES_COOKIE_ENV = "COLES_COOKIE"

WOOLWORTHS_SESSION_CHECK = (
    "https://www.woolworths.com.au/apis/ui/lists"
)
COLES_SESSION_CHECK = "https://www.coles.com.au/api/customers/v2/me"

STORE_CONFIGS = {
    "woolworths": {
        "cookie_env": WOOLWORTHS_COOKIE_ENV,
        "session_check_url": WOOLWORTHS_SESSION_CHECK,
        "session_check_method": "GET",
        "base_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.woolworths.com.au/shop/list",
            "Origin": "https://www.woolworths.com.au",
        },
        "fallback_payload_dir": None,  # set during init
    },
    "coles": {
        "cookie_env": COLES_COOKIE_ENV,
        "session_check_url": COLES_SESSION_CHECK,
        "session_check_method": "GET",
        "base_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.coles.com.au/browse/dairy",
            "Origin": "https://www.coles.com.au",
        },
        "fallback_payload_dir": None,
    },
}


def _load_env():
    """Load root .env if available."""
    if not load_dotenv:
        return
    env_path = os.path.join(_REPO_ROOT, ".env")
    if os.path.isfile(env_path):
        load_dotenv(env_path)


_load_env()


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------
class SessionManager:
    """Manages authentication sessions for supermarket scrapers.

    Reads cookies from environment variables and provides HTTP headers
    for authenticated requests. Supports offline fallback mode where
    pre-saved HTML/JSON payloads can be injected instead of live fetching.

    Attributes:
        store_names (tuple): Supported store identifiers.
        fallback_dir (str): Path to fallback payload directory.
    """

    def __init__(self, fallback_dir: Optional[str] = None):
        """Initialize SessionManager.

        Args:
            fallback_dir: Optional path to directory containing saved
                HTML/JSON payload files. If None, defaults to
                ``extractors/fallback_payloads/``.
        """
        self.store_names = tuple(STORE_CONFIGS.keys())
        if fallback_dir:
            self.fallback_dir = fallback_dir
        else:
            self.fallback_dir = os.path.join(_HERE, "fallback_payloads")

    # ------------------------------------------------------------------
    # Cookie retrieval
    # ------------------------------------------------------------------
    def get_cookies(self, store: str) -> dict:
        """Parse the cookie string from .env into a dict.

        Args:
            store: ``"woolworths"`` or ``"coles"``.

        Returns:
            dict of cookie key-value pairs. Empty dict if no cookie set.

        Raises:
            ValueError: Unknown store name.
        """
        config = self._get_config(store)
        raw = os.getenv(config["cookie_env"], "")
        if not raw:
            return {}
        return self._parse_cookie_string(raw)

    def get_cookie_string(self, store: str) -> str:
        """Return the raw cookie string from .env (unparsed).

        Args:
            store: ``"woolworths"`` or ``"coles"``.

        Returns:
            str: The raw cookie header value, or ``""`` if not set.
        """
        config = self._get_config(store)
        return os.getenv(config["cookie_env"], "")

    def has_cookie(self, store: str) -> bool:
        """Check if a session cookie is configured for the given store.

        Args:
            store: ``"woolworths"`` or ``"coles"``.

        Returns:
            True if the cookie environment variable is non-empty.
        """
        return bool(self.get_cookie_string(store))

    # ------------------------------------------------------------------
    # Header construction
    # ------------------------------------------------------------------
    def get_headers(self, store: str, extra: Optional[dict] = None) -> dict:
        """Build HTTP headers dict for the given store.

        If a session cookie is available, it is included as the
        ``Cookie`` header.

        Args:
            store: ``"woolworths"`` or ``"coles"``.
            extra: Optional additional headers to merge in.

        Returns:
            dict of HTTP headers.
        """
        config = self._get_config(store)
        headers = dict(config["base_headers"])
        cookie_str = self.get_cookie_string(store)
        if cookie_str:
            headers["Cookie"] = cookie_str
        if extra:
            headers.update(extra)
        return headers

    # ------------------------------------------------------------------
    # Session validation
    # ------------------------------------------------------------------
    def is_session_alive(
        self, store: str, timeout: int = 10
    ) -> bool:
        """Check whether the stored session cookie is still valid.

        Sends a lightweight request to the store's session-check
        endpoint. A 2xx response means the session is alive; 401/403
        or connection error means it is dead or missing.

        Args:
            store: ``"woolworths"`` or ``"coles"``.
            timeout: Request timeout in seconds.

        Returns:
            True if the session responded with HTTP 2xx.
        """
        config = self._get_config(store)
        url = config["session_check_url"]
        method = config["session_check_method"]
        headers = self.get_headers(store)

        if not self.has_cookie(store):
            return False

        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, timeout=timeout)
            elif method == "POST":
                resp = requests.post(url, headers=headers, timeout=timeout)
            else:
                return False
            return resp.status_code < 400
        except requests.RequestException:
            return False

    def validate_all_sessions(
        self, timeout: int = 10
    ) -> dict:
        """Check session health for all configured stores.

        Args:
            timeout: Request timeout in seconds per store.

        Returns:
            dict mapping store name to bool (alive or not).
        """
        result = {}
        for store in self.store_names:
            result[store] = self.is_session_alive(store, timeout=timeout)
        return result

    # ------------------------------------------------------------------
    # Fallback / offline mode
    # ------------------------------------------------------------------
    def get_fallback_payload_path(self, store: str) -> str:
        """Return the expected path for a saved payload file.

        Args:
            store: ``"woolworths"`` or ``"coles"``.

        Returns:
            str: Absolute path to ``<store>_payload.html`` or
                ``<store>_payload.json``.
        """
        return os.path.join(self.fallback_dir, f"{store}_payload.json")

    def has_fallback_payload(self, store: str) -> bool:
        """Check if a saved payload file exists for the given store.

        Args:
            store: ``"woolworths"`` or ``"coles"``.

        Returns:
            True if a fallback payload file exists.
        """
        json_path = self.get_fallback_payload_path(store)
        html_path = json_path.replace(".json", ".html")
        return os.path.isfile(json_path) or os.path.isfile(html_path)

    def load_fallback_payload(self, store: str) -> Optional[str]:
        """Load a saved HTML/JSON payload from disk.

        Useful for testing or when live extraction is unavailable.

        Args:
            store: ``"woolworths"`` or ``"coles"``.

        Returns:
            str: The raw payload content, or None if no file found.
        """
        json_path = self.get_fallback_payload_path(store)
        html_path = json_path.replace(".json", ".html")

        for path in (json_path, html_path):
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
        return None

    # ------------------------------------------------------------------
    # Status summary
    # ------------------------------------------------------------------
    def summary(self) -> dict:
        """Return a structured summary of session state for all stores.

        Returns:
            dict with keys:
                - ``cookies_configured``: list of stores with cookies
                - ``cookies_missing``: list of stores without cookies
                - ``fallback_available``: list of stores with payloads
                - ``session_alive``: dict of store -> bool (or None if
                  no cookie configured)
        """
        alive = {}
        for store in self.store_names:
            if self.has_cookie(store):
                alive[store] = self.is_session_alive(store)
            else:
                alive[store] = None

        return {
            "cookies_configured": [
                s for s in self.store_names if self.has_cookie(s)
            ],
            "cookies_missing": [
                s for s in self.store_names if not self.has_cookie(s)
            ],
            "fallback_available": [
                s for s in self.store_names if self.has_fallback_payload(s)
            ],
            "session_alive": alive,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_config(self, store: str) -> dict:
        """Look up store configuration.

        Args:
            store: Store name (case-insensitive).

        Returns:
            Configuration dict for the store.

        Raises:
            ValueError: Unknown store name.
        """
        store = store.lower().strip()
        if store not in STORE_CONFIGS:
            raise ValueError(
                f"Unknown store '{store}'. Supported: {', '.join(self.store_names)}"
            )
        return STORE_CONFIGS[store]

    @staticmethod
    def _parse_cookie_string(cookie_str: str) -> dict:
        """Parse a raw Cookie header string into a dict.

        Args:
            cookie_str: Raw cookie string (e.g. ``"key1=val1; key2=val2"``).

        Returns:
            dict of cookie key-value pairs.
        """
        cookies = {}
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                key, _, value = part.partition("=")
                cookies[key.strip()] = value.strip()
        return cookies


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sm = SessionManager()
    print("=== SessionManager Status ===")
    print(f"Supported stores: {', '.join(sm.store_names)}")
    print(f"Cookies configured: {', '.join(sm.summary()['cookies_configured']) or 'NONE'}")
    print(f"Cookies missing: {', '.join(sm.summary()['cookies_missing']) or 'NONE'}")
    print(f"Fallback available: {', '.join(sm.summary()['fallback_available']) or 'NONE'}")

    # Validate sessions
    for store in sm.store_names:
        alive = sm.is_session_alive(store)
        if alive:
            print(f"  [OK] {store}: session alive")
        elif sm.has_cookie(store):
            print(f"  [!!] {store}: session cookie set but NOT alive")
        else:
            print(f"  [--] {store}: no cookie configured")

    print("\nSessionManager loaded successfully.")
