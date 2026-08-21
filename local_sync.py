# python local_sync.py

# cd C:\Users\User\Grocery_Project - folder of my script
# pip install gspread - to install gspread library
# "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\temp\chrome_scout" - to open a fresh connection
# taskkill /F /IM chrome.exe /T - to kill all open chromes on local command prompt

import os
import re
import gspread
from datetime import datetime
from docx import Document
from google.oauth2.service_account import Credentials
from rapidfuzz import process, fuzz

# --- CONFIGURATION ---
CREDENTIALS_PATH = "credentials/service_account.json"
SHEET_NAME = "AusGrocery_PriceDB"
TAB_NAME = "Products_Master"

# Mapping Update (using 0-based index for logic):
# Col A=0, B=1, C=2, D=3(Woolworths_Price), E=4(Coles_Price), F=5(Aldi_Price), 
# G=6(Brand_Type), H=7(Last_Updated), I=8(Search_Keyword_Woolworths), 
# J=9(Search_Keyword_Coles), K=10(Search_Keyword_Aldi), L=11(Aldi_Refresh)
DOCS = {
    "Woolworths": {"file": "Woolworths.docx", "search_idx": 8, "price_idx": 3},
    "Coles":      {"file": "Coles.docx",      "search_idx": 9, "price_idx": 4},
    "Aldi":       {"file": "Aldi.docx",       "search_idx": 10, "price_idx": 5}
}

def clean_price(price_str):
    """Extract price from various price formats like $5.99 or A$5.99"""
    if not price_str: 
        return None
    matches = re.findall(r"(?:A\$|\$)\s*(\d+\.\d+)", str(price_str))
    return float(matches[-1]) if matches else None

def extract_from_docx(file_path):
    """Read prices from Word document into a cache dictionary"""
    if not os.path.exists(file_path): 
        return {}
    doc = Document(file_path)
    cache, current_item = {}, None
    ignore_list = ["total", "estimated", "footer", "value of done", "special buys"]
    
    for p in doc.paragraphs:
        line = p.text.strip()
        if not line: 
            continue
        price = clean_price(line)
        if price is not None:
            if current_item:
                cache[current_item] = price
                current_item = None
        else:
            if len(line) > 4 and not any(x in line.lower() for x in ignore_list):
                current_item = line.lower()
    return cache

def run_scout():
    """Main synchronization function"""
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME).worksheet(TAB_NAME)
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return

    print("📂 Reading Word documents...")
    shop_caches = {shop: extract_from_docx(config["file"]) for shop, config in DOCS.items()}
    
    # 1. Pull the ENTIRE sheet into memory
    all_data = sheet.get_all_values()
    headers = all_data[0]
    rows = all_data[1:]  # This is our local "copy" of the data

    print(f"🚀 Precision Sync active at {datetime.now().strftime('%H:%M:%S')}")
    print(f"📊 Processing {len(rows)} data rows from {len(headers)} columns")

    # 2. Update our local "copy" (no API calls here, so it's super fast)
    for row in rows:
        now_ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        updated_any = False

        for shop, config in DOCS.items():
            cache = shop_caches.get(shop)
            # Safe index check for each shop
            try:
                if len(row) > config["search_idx"]:
                    search_key = row[config["search_idx"]].lower().strip()
                    
                    if cache and search_key:
                        match = process.extractOne(search_key, cache.keys(), scorer=fuzz.token_set_ratio)
                        
                        if match and match[1] >= 95:
                            price = cache.get(match[0])
                            if price is not None and price > 0:
                                # Update local row list
                                row[config["price_idx"]] = price
                                updated_any = True
                                
                                # Update Aldi Refresh Column L (Index 11)
                                if shop == "Aldi" and len(row) >= 12:
                                    row[11] = now_ts
            except (IndexError, KeyError):
                continue

        # Update Overall Timestamp Column H (Index 7)
        if updated_any and len(row) >= 8:
            row[7] = now_ts

    # 3. Send the entire updated list back in ONE request
    print("📤 Sending all updates to Google Sheets...")
    try:
        if rows:
            # FIX: Use dynamic range based on maximum column index in data
            max_row_idx = len(rows)
            max_col_idx = max(len(row) for row in rows)  # Get actual data columns
            
            # Build column letter (e.g., L = column 12)
            max_col_letter = chr(ord('A') + max_col_idx)  # e.g., 'L'
            
            # Use a range that covers all columns in your data
            range_name = f'A2:{max_col_letter}{max_row_idx + 1}'
            
            # FIX: Use named arguments to fix deprecation warning
            sheet.update(values=rows, range_name=range_name)
        
            print(f"✅ Successfully wrote {len(rows)} rows to {range_name}")
            print("\n" + "="*45)
            print("🏁 BATCH SYNC COMPLETE - No Quota Issues!")
            print("="*45)
        else:
            print("\n⚠️  No data rows to update")
            
    except Exception as e:
        print(f"❌ Error during batch update: {e}")

if __name__ == "__main__":
    run_scout()