"""
Subtask 0.2: Google Sheets Connection Probe.

Verifies read access to AusGrocery_PriceDB -> Products_Master using
credentials loaded from the root .env file (GOOGLE_SERVICE_ACCOUNT_JSON).

Usage:
    python grocery-price-tracker/tests/test_sheets_conn.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Walk-up loader to find root .env (handles running from any subdir)
# ---------------------------------------------------------------------------
def _find_root_env() -> Path:
    """Walk up from this file's directory until we find a .env file."""
    start = Path(__file__).resolve().parent  # grocery-price-tracker/tests/
    for parent in start.parents:
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "Could not find root .env file. "
        "Searched upward from: " + str(start)
    )

def _load_env() -> None:
    """Load root .env into os.environ using python-dotenv if available,
    otherwise fall back to manual KEY=VALUE parsing."""
    env_path = _find_root_env()
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=str(env_path), override=True)
        print(f"[dotenv] Loaded: {env_path}")
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
        print(f"[manual] Loaded: {env_path}")


# ---------------------------------------------------------------------------
# 2. Credential builder (supports JSON string or file path)
# ---------------------------------------------------------------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def _build_credentials():
    """Return google-auth Credentials from GROCERY_SERVICE_ACCOUNT_JSON env var."""
    from google.oauth2.service_account import Credentials

    json_str = os.getenv("GROCERY_SERVICE_ACCOUNT_JSON")
    if not json_str:
        raise RuntimeError(
            "GROCERY_SERVICE_ACCOUNT_JSON is not set in the root .env file."
        )
    info = json.loads(json_str)
    return Credentials.from_service_account_info(info, scopes=SCOPES)


# ---------------------------------------------------------------------------
# 3. Main probe
# ---------------------------------------------------------------------------
TAB_NAME = "Products_Master"

def run_probe() -> None:
    """Connect to Google Sheets and print schema summary."""
    import gspread

    print("=" * 60)
    print("  Google Sheets Connection Probe")
    print("=" * 60)

    # --- Load env ---
    _load_env()

    # --- Build creds ---
    creds = _build_credentials()
    print(f"  Service account: {creds.service_account_email}")

    # --- Connect ---
    spreadsheet_id = os.getenv("GROCERY_SPREADSHEET_ID")
    if not spreadsheet_id:
        raise RuntimeError(
            "GROCERY_SPREADSHEET_ID is not set in the root .env file."
        )
    client = gspread.authorize(creds)

    # Open by ID (more reliable than by name)
    try:
        sheet = client.open_by_key(spreadsheet_id)
    except Exception as exc:
        print(f"\n  [WARN] Could not open sheet by ID '{spreadsheet_id}': {exc}")
        print("  [INFO] Listing spreadsheets visible to this service account...")
        try:
            all_sheets = client.openall()
            if all_sheets:
                print(f"  [INFO] Found {len(all_sheets)} spreadsheet(s):")
                for s in all_sheets:
                    print(f"       - {s.title}  (id: {s.id})")
            else:
                print("  [WARN] No spreadsheets visible. "
                      "Share the sheet with: "
                      f"{creds.service_account_email}")
        except Exception as list_err:
            print(f"  [ERROR] Could not list sheets: {list_err}")
        raise

    ws = sheet.worksheet(TAB_NAME)
    print(f"  Spreadsheet  : {sheet.title}")
    print(f"  SpreadsheetID: {sheet.id}")
    print(f"  Worksheet    : {TAB_NAME}")

    # --- Dimensions ---
    all_values = ws.get_all_values()
    num_rows = len(all_values)
    num_cols = len(all_values[0]) if all_values else 0
    print(f"  Dimensions   : {num_rows} rows x {num_cols} cols")

    # --- Headers ---
    headers = all_values[0] if all_values else []
    print(f"\n  [HEADERS] ({len(headers)} columns):")
    for i, h in enumerate(headers):
        print(f"     Col {chr(65 + i)} (idx {i:>2}): {h}")

    # --- First 2 data rows ---
    data_rows = all_values[1:]  # skip header
    print(f"\n  [DATA] First {min(2, len(data_rows))} data row(s):")
    for row_idx, row in enumerate(data_rows[:2], start=2):
        print(f"     Row {row_idx}: {row[:min(6, len(row))]}{'...' if len(row) > 6 else ''}")

    print("\n[OK] Connection verified successfully.")
    print("=" * 60)


if __name__ == "__main__":
    try:
        run_probe()
    except Exception as exc:
        print(f"\n[FAIL] Probe failed: {exc}", file=sys.stderr)
        sys.exit(1)
