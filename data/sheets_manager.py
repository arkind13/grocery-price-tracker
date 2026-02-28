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

    def get_products_master(self) -> List[Dict]:
        """
        Fetch all products from the master sheet and return as list of dictionaries.
        
        Returns:
            List of dictionaries representing each product row
        """
        try:
            df = SheetsManager.get_data(self.config.spreadsheet_id, self.config.worksheet_name)
            # Convert DataFrame to list of dictionaries
            return df.to_dict('records')
        except Exception as e:
            print(f"Error fetching products master: {e}")
            return []


    def update_price(self, product_name: str, retailer: str, price: float):
        """
        Update price for a given product in the master sheet.
        
        Args:
            product_name: Name of the product
            retailer: 'Woolworths', 'Coles', or 'Aldi'
            price: New price value
        """
        try:
            sheet = self.get_spreadsheet()
            worksheet = sheet.worksheet("Products_Master")
            
            # Find the row index
            all_data = worksheet.get_all_values()
            header = all_data[0]
            product_index = None
            
            for i, row in enumerate(all_data[1:], start=1):  # Skip header row
                if row[header.index('Product_Name')] == product_name:
                    product_index = i
                    break
                    
            if product_index:
                # Update the appropriate column
                col_index = header.index(f'{retailer}_Price') + 1  # Convert to 1-based index
                worksheet.update_cell(product_index, col_index, price)
                
                # Update Last_Updated
                last_updated_col = header.index('Last_Updated') + 1
                worksheet.update_cell(product_index, last_updated_col, datetime.now().strftime('%Y-%m-%d'))
                
        except Exception as e:
            print(f"Error updating price for {product_name}: {e}")


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

# This creates a global instance that other files can import
manager = SheetsManager()
