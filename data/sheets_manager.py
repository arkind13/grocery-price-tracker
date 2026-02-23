from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

import gspread
from gspread.exceptions import APIError, WorksheetNotFound
from google.oauth2.service_account import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


@dataclass(frozen=True)
class SheetsConfig:
    spreadsheet_id: str
    worksheet_name: str = "Products_Master"


class SheetsManager:
    """
    Uses:
      - st.secrets["gcp_service_account"]  (TOML dict)
      - st.secrets["spreadsheet_id"]       (Google Sheet ID)
    """

    def __init__(self, spreadsheet_id: Optional[str] = None, worksheet_name: str = "Products_Master"):
        spreadsheet_id = spreadsheet_id or st.secrets.get("spreadsheet_id")
        if not spreadsheet_id:
            raise ValueError("Missing spreadsheet id. Set st.secrets['spreadsheet_id'] or pass spreadsheet_id=...")

        self.config = SheetsConfig(spreadsheet_id=spreadsheet_id, worksheet_name=worksheet_name)

    # -------------------------
    # Auth / Client / Worksheet
    # -------------------------
    def _get_credentials(self) -> Credentials:
        try:
            sa_info: Dict[str, Any] = dict(st.secrets["gcp_service_account"])
            return Credentials.from_service_account_info(sa_info, scopes=SCOPES)
        except KeyError as e:
            raise RuntimeError("Missing st.secrets['gcp_service_account'] in Streamlit secrets.") from e
        except Exception as e:
            raise RuntimeError(f"Failed to build Google credentials: {e}") from e

    def _get_client(self) -> gspread.Client:
        try:
            return gspread.authorize(self._get_credentials())
        except Exception as e:
            raise RuntimeError(f"Failed to authorize gspread client: {e}") from e

    def _get_worksheet(self) -> gspread.Worksheet:
        try:
            client = self._get_client()
            sh = client.open_by_key(self.config.spreadsheet_id)
            return sh.worksheet(self.config.worksheet_name)
        except WorksheetNotFound as e:
            raise RuntimeError(f"Worksheet '{self.config.worksheet_name}' not found.") from e
        except (APIError, OSError) as e:
            raise RuntimeError(f"Google Sheets API/connection error: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Unexpected error opening worksheet: {e}") from e

    # -------------------------
    # Read (R) - cached
    # -------------------------
    @staticmethod
    @st.cache_data(ttl=600)
    def get_data(spreadsheet_id: str, worksheet_name: str = "Products_Master") -> pd.DataFrame:
        try:
            sa_info: Dict[str, Any] = dict(st.secrets["gcp_service_account"])
            creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
            client = gspread.authorize(creds)
            ws = client.open_by_key(spreadsheet_id).worksheet(worksheet_name)

            records = ws.get_all_records()
            return pd.DataFrame(records)

        except (APIError, OSError) as e:
            raise RuntimeError(f"Google Sheets API/connection error while reading: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Unexpected error while reading sheet: {e}") from e

    def get_products_master(self) -> pd.DataFrame:
        return SheetsManager.get_data(self.config.spreadsheet_id, self.config.worksheet_name)

    # -------------------------
    # Helpers
    # -------------------------
    @staticmethod
    def _norm(s: str) -> str:
        return str(s).strip().lower()

    @staticmethod
    def _now_iso_utc() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _get_header_map(self, ws: gspread.Worksheet) -> Dict[str, int]:
        """
        Returns: normalized_header -> 1-based column index
        """
        headers = ws.row_values(1)
        if not headers:
            raise RuntimeError("Header row (row 1) is empty.")
        return {self._norm(h): i + 1 for i, h in enumerate(headers)}

    # -------------------------
    # Update (U)
    # -------------------------
    def update_price(self, product_name: str, store_name: str, new_price: Any) -> None:
        """
        Updates one of:
          - Woolworths_Price
          - Coles_Price
          - Aldi_Price
        and also updates Last_Updated.

        store_name accepted (case-insensitive): woolworths, coles, aldi
        """
        try:
            ws = self._get_worksheet()
            header_map = self._get_header_map(ws)

            # Required columns by your sheet
            product_col = header_map.get(self._norm("Product_Name"))
            last_updated_col = header_map.get(self._norm("Last_Updated"))

            if not product_col:
                raise ValueError("Column 'Product_Name' not found.")
            if not last_updated_col:
                raise ValueError("Column 'Last_Updated' not found.")

            store_key = self._norm(store_name)
            store_to_colname = {
                "woolworths": "Woolworths_Price",
                "coles": "Coles_Price",
                "aldi": "Aldi_Price",
            }
            if store_key not in store_to_colname:
                raise ValueError("store_name must be one of: woolworths, coles, aldi")

            price_colname = store_to_colname[store_key]
            price_col = header_map.get(self._norm(price_colname))
            if not price_col:
                raise ValueError(f"Column '{price_colname}' not found.")

            # Find product row by scanning Product_Name column
            col_values = ws.col_values(product_col)
            target_row = None
            for idx, val in enumerate(col_values[1:], start=2):  # skip header
                if self._norm(val) == self._norm(product_name):
                    target_row = idx
                    break

            if target_row is None:
                raise ValueError(f"Product '{product_name}' not found in 'Product_Name' column.")

            # Update price + timestamp (batch update)
            ws.update(
                [
                    gspread.utils.rowcol_to_a1(target_row, price_col),
                    gspread.utils.rowcol_to_a1(target_row, last_updated_col),
                ],
                [[new_price], [self._now_iso_utc()]],
                value_input_option="USER_ENTERED",
            )

        except (APIError, OSError) as e:
            raise RuntimeError(f"Google Sheets API/connection error while updating: {e}") from e
        except Exception:
            raise

    # -------------------------
    # Create (C)
    # -------------------------
    def add_product(self, product_name: str, category: str = "", size: str = "") -> None:
        """
        Appends a new row respecting your headers.
        Prices are left blank; Last_Updated is set to now (UTC).
        """
        try:
            ws = self._get_worksheet()
            header_map = self._get_header_map(ws)

            # Build an empty row in header order
            headers = ws.row_values(1)
            row = [""] * len(headers)

            def set_if_exists(col_name: str, value: Any):
                col = header_map.get(self._norm(col_name))
                if col:
                    row[col - 1] = value

            set_if_exists("Product_Name", product_name)
            set_if_exists("Category", category)
            set_if_exists("Size", size)
            set_if_exists("Last_Updated", self._now_iso_utc())

            ws.append_row(row, value_input_option="USER_ENTERED")

        except (APIError, OSError) as e:
            raise RuntimeError(f"Google Sheets API/connection error while appending: {e}") from e
        except Exception:
            raise


# -------------------------
# Connection Testing
# -------------------------
if __name__ == "__main__":
    """
    Run this via Streamlit so st.secrets loads:
      streamlit run data/sheets_manager.py
    """
    try:
        sm = SheetsManager()
        df = sm.get_products_master()
        print("✅ Connection OK.")
        print("Rows:", len(df))
        print(df.head(5).to_string(index=False))
    except Exception as e:
        print("❌ Connection test failed:")
        print(e)

