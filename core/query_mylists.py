"""Phase 9.0.b — Query Woolworths /apis/ui/mylists to pin exact list names.

Prints every list name and ID found. Resolves "Price Comparison" vs "Price Compare"
casing ambiguity. Requires WOOLWORTHS_COOKIE in .env.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Env loading (mirror woolworths_extractor pattern)
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent  # core/
_REPO_ROOT = _SCRIPT_DIR.parent  # grocery-price-tracker/
_WORKSPACE_ROOT = _REPO_ROOT.parent  # workspace root (AI related/)


def _load_env():
    try:
        from dotenv import load_dotenv

        env_path = _WORKSPACE_ROOT / ".env"
        if env_path.is_file():
            load_dotenv(dotenv_path=str(env_path), override=True)
            return
    except ImportError:
        pass
    env_path = _WORKSPACE_ROOT / ".env"
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

MYLISTS_API = "https://www.woolworths.com.au/apis/ui/mylists"


def query_mylists():
    """Query Woolworths mylists API and return parsed list data."""
    cookie = os.getenv("WOOLWORTHS_COOKIE", "")
    if not cookie:
        print("ERROR: WOOLWORTHS_COOKIE not set in .env")
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.woolworths.com.au/shop/mylists",
        "Origin": "https://www.woolworths.com.au",
        "Cookie": cookie,
    }

    try:
        resp = requests.get(MYLISTS_API, headers=headers, timeout=30)
        if resp.status_code != 200:
            print(f"ERROR: HTTP {resp.status_code} from {MYLISTS_API}")
            return None
        return resp.json()
    except requests.RequestException as exc:
        print(f"ERROR: request failed — {exc}")
        return None


def main():
    print("=== Woolworths Mylists Query ===")
    data = query_mylists()
    if data is None:
        print("FAILED: Could not retrieve mylists data.")
        return 1

    lists = data.get("Response", data if isinstance(data, list) else [])
    if not lists:
        print("WARNING: No lists found in response.")
        print(f"Raw response keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
        return 1

    print(f"\nFound {len(lists)} list(s):\n")
    for lst in lists:
        name = lst.get("Name", "?")
        list_id = lst.get("ListId", "?")
        item_count = lst.get("ItemCount", lst.get("ProductCount", "?"))
        print(f"  [{list_id}] \"{name}\"  ({item_count} items)")

    # ------------------------------------------------------------------
    # Pin the three target list names
    # ------------------------------------------------------------------
    names_lower = {lst.get("Name", "").strip().lower(): lst for lst in lists}

    print("\n=== TARGET LIST MATCHING ===")

    targets = {
        "WOOL_LIST_PRICE_COMPARE": ["price compare", "price comparison"],
        "WOOL_LIST_SPECIALS": ["specials"],
    }

    pinned: dict[str, str | None] = {}

    for const_name, candidates in targets.items():
        match = None
        for candidate in candidates:
            if candidate in names_lower:
                match = names_lower[candidate]
                break
        if match:
            pinned[const_name] = match.get("Name", "")
            print(f"  {const_name} = \"{pinned[const_name]}\"  (ID: {match.get('ListId')})")
        else:
            pinned[const_name] = None
            print(f"  {const_name} = NOT FOUND (candidates: {candidates})")

    # Dump JSON for use by 9.0.c
    print("\n=== PINNED CONSTANTS (for list_names.py) ===")
    print(json.dumps(pinned, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
