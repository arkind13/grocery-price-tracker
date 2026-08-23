#!/usr/bin/env python3
"""Playwright Auto-Login Auth Manager with 2FA-via-Telegram and compulsory logout.

Orchestrates headless browser login to Woolworths and Coles, handles 2FA
via a polling file (GROCERY_2FA_PATH), caches session cookies in memory
(or encrypted on disk with GROCERY_COOKIE_KEY), and enforces a **compulsory
logout** after every extraction session via a ``finally`` block.

Usage:
    from extractors.auth_manager import AuthManager
    am = AuthManager()
    items = am.fetch_list("woolworths", "Price Compare")
    # logout is automatic in fetch_list's finally block
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Path setup: allow import from repo root
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent  # grocery-price-tracker root
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("auth_manager")

# ---------------------------------------------------------------------------
# Store login configuration
# ---------------------------------------------------------------------------
STORE_LOGIN_CONFIG = {
    "woolworths": {
        "login_url": "https://www.woolworths.com.au/shop/login",
        "username_field": "#loginEmail",
        "password_field": "#loginPassword",
        "submit_button": 'button[type="submit"]',
        "logout_url": "https://www.woolworths.com.au/shop/logout",
        "env_user": "WOOLWORTHS_USER",
        "env_pass": "WOOLWORTHS_PASS",
    },
    "coles": {
        "login_url": "https://www.coles.com.au/login",
        "username_field": "#email",
        "password_field": "#password",
        "submit_button": 'button[type="submit"]',
        "logout_url": "https://www.coles.com.au/logout",
        "env_user": "COLES_USER",
        "env_pass": "COLES_PASS",
    },
}

SUPPORTED_STORES = tuple(STORE_LOGIN_CONFIG.keys())

# 2FA polling defaults
DEFAULT_2FA_TIMEOUT_SEC = 300  # 5 minutes
DEFAULT_2FA_POLL_INTERVAL = 2  # seconds


def _load_env() -> None:
    """Load root .env via dotenv if available, else manual parse.

    Mirrors sheets_client._load_env to avoid circular imports.
    Never prints secret values.
    """
    try:
        from dotenv import load_dotenv

        env_path = _REPO_ROOT / ".env"
        if env_path.is_file():
            load_dotenv(dotenv_path=str(env_path), override=True)
            return
    except ImportError:
        pass

    # Manual fallback
    env_path = _REPO_ROOT / ".env"
    if not env_path.is_file():
        return
    with open(env_path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("\"'")
            os.environ[key] = val


_load_env()


def _get_2fa_path(store: str) -> str:
    """Return the 2FA code polling file path for *store*.

    Reads from env var ``GROCERY_2FA_PATH`` with fallback to
    ``/tmp/grocery_2fa_<store>.txt``.
    """
    base = os.getenv("GROCERY_2FA_PATH", "")
    if base:
        return f"{base}_{store}.txt"
    return f"/tmp/grocery_2fa_{store}.txt"


def _get_cookie_key() -> Optional[bytes]:
    """Return the Fernet-compatible cookie encryption key, or None."""
    raw = os.getenv("GROCERY_COOKIE_KEY", "")
    if raw:
        return raw.encode("utf-8")
    return None


# ============================================================================
# AuthManager
# ============================================================================


class AuthManager:
    """Headless browser login, 2FA, cookie cache, and compulsory logout.

    Attributes:
        store_names (tuple): Supported store identifiers (``"woolworths"``,
            ``"coles"``).
    """

    def __init__(self):
        """Initialize AuthManager.

        Reads credential env vars (``WOOLWORTHS_USER``, ``WOOLWORTHS_PASS``,
        ``COLES_USER``, ``COLES_PASS``) from .env. Does **not** fail on init
        if a credential is missing — the failure happens when that store is
        first requested.

        Cookie encryption key is loaded from ``GROCERY_COOKIE_KEY`` if set.
        """
        self.store_names = SUPPORTED_STORES
        # In-memory cookie cache: {store: cookie_string}
        self._cookie_cache: dict[str, str] = {}
        self._cookie_key = _get_cookie_key()
        logger.debug(
            "AuthManager initialised. Cookie encryption: %s",
            "enabled" if self._cookie_key else "disabled (in-memory only)",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def login(self, store: str) -> bool:
        """Launch headless Playwright browser and log in to *store*.

        Handles 2FA by printing a machine-readable prompt to stdout and
        polling the 2FA code file at ``GROCERY_2FA_PATH`` (default
        ``/tmp/grocery_2fa_<store>.txt``).

        On success, extracts session cookies and caches them in-memory
        (or encrypted on disk if ``GROCERY_COOKIE_KEY`` is set).

        Args:
            store: ``"woolworths"`` or ``"coles"``.

        Returns:
            True if login succeeded and cookies were extracted.

        Raises:
            ValueError: Unknown store name.
            RuntimeError: Credentials missing for the requested store.
        """
        config = self._get_config(store)
        username = os.getenv(config["env_user"], "")
        password = os.getenv(config["env_pass"], "")

        if not username or not password:
            raise RuntimeError(
                f"Credentials missing for {store}. "
                f"Set {config['env_user']} and {config['env_pass']} in .env"
            )

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning(
                "playwright not available — attempting stealth import"
            )
            try:
                from playwright_stealth.sync_api import sync_playwright  # type: ignore[no-redef]
            except ImportError:
                logger.error(
                    "Neither playwright nor playwright-stealth available. "
                    "Cannot log in."
                )
                return False

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()

            try:
                logger.info("Navigating to %s login page…", store)
                page.goto(config["login_url"], timeout=30000)
                page.wait_for_load_state("networkidle")

                # Fill credentials
                page.fill(config["username_field"], username)
                page.fill(config["password_field"], password)

                # Submit
                page.click(config["submit_button"])
                page.wait_for_load_state("networkidle")

                # Detect 2FA step
                twofa_detected = self._detect_2fa(page, store)
                if twofa_detected:
                    logger.info("2FA challenge detected for %s", store)
                    print(
                        f"2FA_REQUIRED|{store}|"
                        f"Enter the one-time code sent to your phone"
                    )
                    code = self._poll_2fa_code(store)
                    if code is None:
                        logger.error("2FA timed out for %s — aborting", store)
                        return False
                    # Fill 2FA code — common selectors across stores
                    self._submit_2fa(page, code)
                    page.wait_for_load_state("networkidle")

                # Extract cookies
                cookies = context.cookies()
                cookie_str = "; ".join(
                    f"{c['name']}={c['value']}" for c in cookies
                )
                self._cache_cookies(store, cookie_str)
                logger.info("Login to %s successful", store)
                return True

            except Exception as exc:
                logger.error("Login to %s failed: %s", store, exc)
                return False
            finally:
                browser.close()

    def logout(self, store: str) -> None:
        """Navigate to the store logout URL and discard cached cookies.

        **Mandatory** — called after every extraction session. If the
        logout request itself fails, a critical log is emitted and the
        exception is re-raised so the caller cannot silently skip logout.

        Args:
            store: ``"woolworths"`` or ``"coles"``.

        Raises:
            RuntimeError: Logout navigation failed.
            ValueError: Unknown store name.
        """
        config = self._get_config(store)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            try:
                from playwright_stealth.sync_api import sync_playwright
            except ImportError:
                logger.critical(
                    "Cannot log out of %s — playwright unavailable", store
                )
                raise RuntimeError(
                    f"Cannot log out of {store}: playwright not available"
                )

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            # Restore cookies so the logout endpoint recognises the session
            cached = self._get_cached_cookies(store)
            if cached:
                from playwright.sync_api import Cookie

                parsed: list[dict] = []
                for part in cached.split(";"):
                    part = part.strip()
                    if "=" in part:
                        key, _, val = part.partition("=")
                        parsed.append(
                            {
                                "name": key.strip(),
                                "value": val.strip(),
                                "domain": f".{store.lower()}.com.au",
                                "path": "/",
                            }
                        )
                context.add_cookies(parsed)  # type: ignore[arg-type]

            try:
                logger.info("Logging out of %s…", store)
                resp = page.goto(config["logout_url"], timeout=15000)
                page.wait_for_load_state("networkidle")
                status = resp.status if resp else 0
                logger.info(
                    "Logout from %s returned HTTP %d", store, status
                )
            except Exception as exc:
                logger.critical(
                    "Logout from %s FAILED: %s", store, exc
                )
                raise RuntimeError(
                    f"Compulsory logout from {store} failed: {exc}"
                ) from exc
            finally:
                # Discard cached cookies regardless of logout outcome
                self._clear_cookies(store)
                browser.close()

    def fetch_list(
        self,
        store: str,
        list_name: str = "Price Compare",
    ) -> list[dict]:
        """Fetch the shopping list from *store* with a live browser session.

        Orchestrates: ensure session → call existing extractor →
        **compulsory logout** in ``finally`` block.

        If the session cookie is rejected mid-extraction, attempts a
        single auto-relogin and retry.

        Args:
            store: ``"woolworths"`` or ``"coles"``.
            list_name: Name of the list to fetch.

        Returns:
            list of item dicts (same format as existing extractors).

        Raises:
            RuntimeError: Login or logout failed irrecoverably.
            ValueError: Unknown store name.
        """
        config = self._get_config(store)
        relogin_attempted = False

        try:
            # Ensure we have a live session
            if not self._has_live_session(store):
                logger.info("No live session for %s — logging in", store)
                if not self.login(store):
                    raise RuntimeError(f"Login to {store} failed")

            # Delegate to the existing extractor
            items = self._run_extractor(store, list_name)
            return items

        except Exception as exc:
            # Auto-relogin once if cookie was rejected
            if not relogin_attempted and self._is_auth_error(exc):
                relogin_attempted = True
                logger.info(
                    "Session rejected for %s — attempting relogin", store
                )
                self._clear_cookies(store)
                if self.login(store):
                    items = self._run_extractor(store, list_name)
                    return items
            raise

        finally:
            # Compulsory logout — always runs, even on error
            try:
                self.logout(store)
            except Exception as logout_err:
                logger.critical(
                    "Compulsory logout from %s failed after extraction: %s",
                    store,
                    logout_err,
                )
                raise

    # ------------------------------------------------------------------
    # Cookie cache
    # ------------------------------------------------------------------

    def _cache_cookies(self, store: str, cookie_str: str) -> None:
        """Store cookies for *store* in memory (or encrypted on disk).

        Args:
            store: Store identifier.
            cookie_str: Raw cookie header string.
        """
        if self._cookie_key:
            self._write_encrypted_cookies(store, cookie_str)
        else:
            self._cookie_cache[store] = cookie_str

    def _get_cached_cookies(self, store: str) -> Optional[str]:
        """Retrieve cached cookies for *store*.

        Args:
            store: Store identifier.

        Returns:
            Cookie string or None if not cached.
        """
        if self._cookie_key:
            return self._read_encrypted_cookies(store)
        return self._cookie_cache.get(store)

    def _clear_cookies(self, store: str) -> None:
        """Discard cached cookies for *store*.

        Args:
            store: Store identifier.
        """
        self._cookie_cache.pop(store, None)
        if self._cookie_key:
            cookie_path = self._encrypted_cookie_path(store)
            if cookie_path.exists():
                cookie_path.unlink(missing_ok=True)

    def _encrypted_cookie_path(self, store: str) -> Path:
        """Return filesystem path for encrypted cookie storage.

        Args:
            store: Store identifier.

        Returns:
            Path to the encrypted cookie file.
        """
        return Path(f"/tmp/.grocery_cookies_{store}.enc")

    def _write_encrypted_cookies(self, store: str, cookie_str: str) -> None:
        """Write cookies encrypted to disk.

        Uses ``cryptography.fernet`` with key from ``GROCERY_COOKIE_KEY``.

        Args:
            store: Store identifier.
            cookie_str: Raw cookie string to encrypt.
        """
        try:
            from cryptography.fernet import Fernet

            key = self._cookie_key
            if not key:
                return
            # Key must be 32 base64-encoded bytes
            cipher = Fernet(key)
            encrypted = cipher.encrypt(cookie_str.encode("utf-8"))
            self._encrypted_cookie_path(store).write_bytes(encrypted)
        except Exception as exc:
            logger.warning(
                "Failed to write encrypted cookies for %s: %s", store, exc
            )
            # Fall back to in-memory
            self._cookie_cache[store] = cookie_str

    def _read_encrypted_cookies(self, store: str) -> Optional[str]:
        """Read and decrypt cookies from disk.

        Args:
            store: Store identifier.

        Returns:
            Decrypted cookie string or None.
        """
        try:
            from cryptography.fernet import Fernet, InvalidToken

            key = self._cookie_key
            if not key:
                return None
            cipher = Fernet(key)
            cookie_path = self._encrypted_cookie_path(store)
            if not cookie_path.exists():
                return None
            encrypted = cookie_path.read_bytes()
            return cipher.decrypt(encrypted).decode("utf-8")
        except (InvalidToken, Exception) as exc:
            logger.warning(
                "Failed to decrypt cookies for %s: %s", store, exc
            )
            return None

    # ------------------------------------------------------------------
    # 2FA handling
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_2fa(page: object, store: str) -> bool:
        """Detect if a 2FA challenge page is shown after login.

        Checks for common 2FA indicators (SMS code field, MFA prompt,
        "verify your identity" text, etc.).

        Args:
            page: Playwright page object.
            store: Store identifier (unused but kept for extensibility).

        Returns:
            True if a 2FA challenge is detected.
        """
        try:
            # Common 2FA indicators
            twofa_selectors = [
                'input[type="tel"]',
                'input[name*="code"]',
                'input[id*="code"]',
                'input[id*="otp"]',
                'input[id*="mfa"]',
                'input[id*="twofa"]',
                'input[id*="2fa"]',
                'input[autocomplete="one-time-code"]',
                "text=Enter the code",
                "text=verification code",
                "text=one-time code",
                "text=two-factor",
                "text=authenticator",
                "text=sent to your phone",
                "text=sent to your mobile",
                '[data-testid*="mfa"]',
                '[data-testid*="otp"]',
            ]
            for selector in twofa_selectors:
                try:
                    el = page.wait_for_selector(
                        selector, timeout=3000
                    )
                    if el and el.is_visible():
                        return True
                except Exception:
                    continue
            return False
        except Exception:
            return False

    @staticmethod
    def _poll_2fa_code(store: str) -> Optional[str]:
        """Poll the 2FA code file for up to 5 minutes.

        The 2FA file path is determined by ``GROCERY_2FA_PATH`` env var
        (default ``/tmp/grocery_2fa_<store>.txt``). The file is deleted
        after successful read.

        Args:
            store: Store identifier.

        Returns:
            The 2FA code string, or None if timed out.
        """
        path = _get_2fa_path(store)
        deadline = time.time() + DEFAULT_2FA_TIMEOUT_SEC

        print(
            f"2FA_REQUIRED|{store}|"
            f"Enter the one-time code sent to your phone"
        )
        print(
            f"Write the code to {path} within "
            f"{DEFAULT_2FA_TIMEOUT_SEC} seconds",
            file=sys.stderr,
        )

        while time.time() < deadline:
            if os.path.isfile(path):
                try:
                    with open(path, "r") as f:
                        code = f.read().strip()
                    os.remove(path)
                    if code:
                        return code
                except (OSError, IOError) as exc:
                    logger.warning(
                        "Error reading 2FA code file: %s", exc
                    )
            time.sleep(DEFAULT_2FA_POLL_INTERVAL)

        logger.error("2FA polling timed out for %s", store)
        return None

    @staticmethod
    def _submit_2fa(page: object, code: str) -> None:
        """Fill the 2FA code into the page and submit.

        Tries common input selectors in order.

        Args:
            page: Playwright page object.
            code: The 2FA code string to enter.
        """
        selectors = [
            'input[autocomplete="one-time-code"]',
            'input[type="tel"]',
            'input[name*="code"]',
            'input[id*="code"]',
            'input[id*="otp"]',
            'input[id*="mfa"]',
            'input[id*="twofa"]',
            'input[id*="2fa"]',
        ]
        for selector in selectors:
            try:
                el = page.wait_for_selector(selector, timeout=2000)
                if el and el.is_visible():
                    el.fill(code)
                    # Try to submit (press Enter)
                    page.keyboard.press("Enter")
                    return
            except Exception:
                continue

    # ------------------------------------------------------------------
    # Session / extractor helpers
    # ------------------------------------------------------------------

    def _has_live_session(self, store: str) -> bool:
        """Check whether we have a cached (non-expired) session for *store*.

        If cookies are cached, does a lightweight HTTP check using the
        existing ``SessionManager``.

        Args:
            store: Store identifier.

        Returns:
            True if a live session is available.
        """
        cached = self._get_cached_cookies(store)
        if not cached:
            return False

        # Use SessionManager to validate
        try:
            from extractors.session_manager import SessionManager

            sm = SessionManager()
            # Temporarily inject our cookie into the env for validation
            cookie_env = (
                "WOOLWORTHS_COOKIE"
                if store == "woolworths"
                else "COLES_COOKIE"
            )
            orig = os.getenv(cookie_env, "")
            os.environ[cookie_env] = cached
            try:
                return sm.is_session_alive(store)
            finally:
                if orig:
                    os.environ[cookie_env] = orig
                else:
                    os.environ.pop(cookie_env, None)
        except Exception:
            return False

    @staticmethod
    def _run_extractor(store: str, list_name: str) -> list[dict]:
        """Delegate list extraction to the existing store-specific extractor.

        Args:
            store: ``"woolworths"`` or ``"coles"``.
            list_name: Name of the shopping list to fetch.

        Returns:
            list of item dicts from the extractor.
        """
        if store == "woolworths":
            from extractors.woolworths_extractor import (  # type: ignore[import-untyped]
                fetch_woolworths_list,
            )

            return fetch_woolworths_list(list_name)
        elif store == "coles":
            from extractors.coles_extractor import (  # type: ignore[import-untyped]
                fetch_coles_list,
            )

            return fetch_coles_list(list_name)
        else:
            raise ValueError(f"Unsupported store: {store}")

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        """Heuristic to check if an exception is auth-related.

        Args:
            exc: The exception to inspect.

        Returns:
            True if the error message suggests an auth failure.
        """
        msg = str(exc).lower()
        keywords = [
            "401",
            "403",
            "unauthori",
            "forbidden",
            "session",
            "cookie",
            "login",
            "auth",
            "token",
        ]
        return any(k in msg for k in keywords)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_config(store: str) -> dict:
        """Look up store login configuration.

        Args:
            store: Store name (case-insensitive).

        Returns:
            Configuration dict for the store.

        Raises:
            ValueError: Unknown store name.
        """
        store = store.lower().strip()
        if store not in STORE_LOGIN_CONFIG:
            raise ValueError(
                f"Unknown store '{store}'. "
                f"Supported: {', '.join(SUPPORTED_STORES)}"
            )
        return STORE_LOGIN_CONFIG[store]


# ============================================================================
# Quick self-test
# ============================================================================
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )
    am = AuthManager()
    print("=== AuthManager Status ===")
    print(f"Supported stores: {', '.join(am.store_names)}")

    for store in am.store_names:
        cfg = STORE_LOGIN_CONFIG[store]
        user = os.getenv(cfg["env_user"], "")
        pw = os.getenv(cfg["env_pass"], "")
        has_creds = bool(user and pw)
        cached = am._get_cached_cookies(store)
        print(f"  {store}: credentials={'✅' if has_creds else '❌'} "
              f"cached={'✅' if cached else '❌'}")

    print("\nAuthManager loaded OK")
