from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import pandas as pd
import streamlit as st
import gspread
from gspread.exceptions import APIError, WorksheetNotFound
from google.oauth2.service_account import Credentials
from scrapers.aldi_scraper import batch_update_aldi_products

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

@dataclass(frozen=True)
class SheetsConfig:
    spreadsheet_id: str
    worksheet_name: str = "Products_Master"

class SheetsManager:
    def __init__(self, spreadsheet_id: Optional[str] = None, worksheet_name: str = "Products_Master"):
        # 1. Resolve ID from secrets
        if not spreadsheet_id:
            try:
                if "google_sheets" in st.secrets:
                    spreadsheet_id = st.secrets["google_sheets"]["spreadsheet_id"]
                else:
                    spreadsheet_id = st.secrets.get("spreadsheet_id")
            except (KeyError, TypeError):
                spreadsheet_id = None

        if not spreadsheet_id:
            raise ValueError("Missing spreadsheet_id. Set st.secrets['google_sheets']['spreadsheet_id']")

        self.config = SheetsConfig(spreadsheet_id=spreadsheet_id, worksheet_name=worksheet_name)

    # --- INTERNAL HELPERS ---
    def _get_credentials(self) -> Credentials:
        try:
            sa_info: Dict[str, Any] = dict(st.secrets["gcp_service_account"])
            return Credentials.from_service_account_info(sa_info, scopes=SCOPES)
        except Exception as e:
            raise RuntimeError(f"Failed to build Google credentials: {e}")

    def _get_client(self) -> gspread.Client:
        return gspread.authorize(self._get_credentials())

    def _get_worksheet(self) -> gspread.Worksheet:
        client = self._get_client()
        sh = client.open_by_key(self.config.spreadsheet_id)
        return sh.worksheet(self.config.worksheet_name)

    @staticmethod
    def _norm(s: str) -> str:
        return str(s).strip().lower()

    @staticmethod
    def _now_iso_utc() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _get_header_map(self, ws: gspread.Worksheet) -> Dict[str, int]:
        headers = ws.row_values(1)
        if not headers:
            raise RuntimeError("Header row (row 1) is empty.")
        return {self._norm(h): i + 1 for i, h in enumerate(headers)}

    # --- PUBLIC METHODS (CRUD) ---
    
    def get_spreadsheet(self, name_or_id: Optional[str] = None) -> gspread.Spreadsheet:
        """FIXED: Accepts arg to match app.py. Returns live connection."""
        client = self._get_client()
        return client.open_by_key(self.config.spreadsheet_id)

    @staticmethod
    @st.cache_data(ttl=600)
    def get_data(spreadsheet_id: str, worksheet_name: str = "Products_Master") -> pd.DataFrame:
        sa_info: Dict[str, Any] = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
        client = gspread.authorize(creds)
        ws = client.open_by_key(spreadsheet_id).worksheet(worksheet_name)
        return pd.DataFrame(ws.get_all_records())

    def get_products_master(self) -> pd.DataFrame:
        return SheetsManager.get_data(self.config.spreadsheet_id, self.config.worksheet_name)

    def update_price(self, product_name: str, store_name: str, new_price: Any) -> None:
        """Updates Price and Last_Updated timestamp."""
        ws = self._get_worksheet()
        header_map = self._get_header_map(ws)
        
        product_col = header_map.get(self._norm("Product_Name"))
        last_updated_col = header_map.get(self._norm("Last_Updated"))
        
        store_key = self._norm(store_name)
        store_to_colname = {"woolworths": "Woolworths_Price", "coles": "Coles_Price", "aldi": "Aldi_Price"}
        price_col = header_map.get(self._norm(store_to_colname.get(store_key, "")))

        if not all([product_col, last_updated_col, price_col]):
            raise ValueError("Required columns missing in sheet.")

        col_values = ws.col_values(product_col)
        target_row = next((idx for idx, val in enumerate(col_values[1:], start=2) if self._norm(val) == self._norm(product_name)), None)

        if target_row:
            ws.update(
                [gspread.utils.rowcol_to_a1(target_row, price_col), gspread.utils.rowcol_to_a1(target_row, last_updated_col)],
                [[new_price], [self._now_iso_utc()]],
                value_input_option="USER_ENTERED"
            )

    def add_product(self, product_name: str, category: str = "", size: str = "") -> None:
        """Appends a new product row."""
        ws = self._get_worksheet()
        header_map = self._get_header_map(ws)
        headers = ws.row_values(1)
        row = [""] * len(headers)

        for col_name, val in [("Product_Name", product_name), ("Category", category), ("Size", size), ("Last_Updated", self._now_iso_utc())]:
            col_idx = header_map.get(self._norm(col_name))
            if col_idx: row[col_idx - 1] = val
        
        ws.append_row(row, value_input_option="USER_ENTERED")

# --- TEST BLOCK ---
if __name__ == "__main__":
    try:
        sm = SheetsManager()
        print(f"✅ Connection OK. Found {len(sm.get_products_master())} products.")
    except Exception as e:
        print(f"❌ Test failed: {e}")
