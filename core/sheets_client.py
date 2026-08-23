"""Shared headless Google Sheets connection helper.

Promoted from core/name_matcher.py Section C. Used by name_matcher (read),
schema_upgrade, and sheets_sync (write). Never reads credentials.json.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _find_root_env() -> Path:
    """Walk up from this file (core/) to find the workspace .env. Max 6 levels."""
    start = Path(__file__).resolve().parent  # core/
    for _ in range(6):
        candidate = start / ".env"
        if candidate.is_file():
            return candidate
        start = start.parent
    raise FileNotFoundError(
        "Could not find root .env file. "
        "Searched upward from: " + str(Path(__file__).resolve().parent)
    )


def _load_env() -> None:
    """Load .env via python-dotenv if available, else manual KEY=VALUE parse.

    Never prints secret values.
    """
    env_path = _find_root_env()
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=str(env_path), override=True)
    except ImportError:
        # Manual fallback: read .env line by line
        with open(env_path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("\"'")
                os.environ[key] = val


def _build_credentials():
    """Return google-auth Credentials from GROCERY_SERVICE_ACCOUNT_JSON env var.

    Raises RuntimeError with secret-free message on failure (mirror
    test_sheets_conn error wording).
    """
    from google.oauth2.service_account import Credentials

    json_str = os.getenv("GROCERY_SERVICE_ACCOUNT_JSON")
    if not json_str:
        raise RuntimeError(
            "GROCERY_SERVICE_ACCOUNT_JSON is not set in the root .env file."
        )
    try:
        info = json.loads(json_str)
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"Failed to parse GROCERY_SERVICE_ACCOUNT_JSON: {exc}"
        ) from exc


def connect_worksheet(worksheet_name: str = "Products_Master"):
    """Open the worksheet by key (GROCERY_SPREADSHEET_ID) via gspread.

    Calls _load_env() then _build_credentials(). Returns the gspread Worksheet
    object. Raises RuntimeError if env vars missing or connection fails
    (secret-free message). This is the PUBLIC entrypoint (was private
    _connect_worksheet in name_matcher.py).
    """
    _load_env()
    import gspread

    spreadsheet_id = os.getenv("GROCERY_SPREADSHEET_ID")
    if not spreadsheet_id:
        raise RuntimeError(
            "GROCERY_SPREADSHEET_ID is not set in the root .env file."
        )
    try:
        creds = _build_credentials()
        client = gspread.authorize(creds)
        sheet = client.open_by_key(spreadsheet_id)
        return sheet.worksheet(worksheet_name)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to connect to worksheet '{worksheet_name}': {exc}"
        ) from exc
