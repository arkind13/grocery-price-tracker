# cd C:\Users\User\Grocery_Project - folder of my script
# # python name_importer.py - to run .py code
# "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\temp\chrome_scout" - to open a fresh connection run this on local comand prompt
# taskkill /F /IM chrome.exe /T - to kill all open chromes on local comand prompt
# http://127.0.0.1:9222/json/version - verify if th version is working in chrome

import os
import re
import gspread
from docx import Document
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
CREDENTIALS_PATH = "credentials/service_account.json"
SHEET_NAME = "AusGrocery_PriceDB"
TAB_NAME = "Products_Master"

DOCS = {
    "Woolworths": "Woolworths.docx",
    "Coles": "Coles.docx",
    "Aldi": "Aldi.docx"
}

def extract_names_from_docx(file_path):
    """Only extracts a name if it is immediately followed by a price line."""
    if not os.path.exists(file_path): return set()
    doc = Document(file_path)
    names = set()
    
    # Get all non-empty lines
    lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    
    # Expanded exclusion list for Australian supermarket UI text
    ignore_list = [
        "total", "estimated", "footer", "value of done", "special buys", 
        "toggle", "search", "hi, ", "delivery to", "sort by", "view cart", 
        "items available", "you’ll save up to", "more from colesaccountlists", 
        "products value", "you'll collect", "pts", "back to top", "my account",
        "specials only", "categorise", "price compare", "add all to cart"
    ]

    for i in range(len(lines) - 1):
        current_line = lines[i]
        next_line = lines[i+1]
        
        # Check if the NEXT line contains a price (e.g. $4.50 or A$4.50)
        has_price_following = re.search(r"(?:A\$|\$)\s*\d+\.\d+", next_line)
        
        if has_price_following and len(current_line) > 5 and "$" not in current_line:
            # Final check against UI ignore list (case-insensitive)
            if not any(x in current_line.lower() for x in ignore_list):
                names.add(current_line)
                
    return names

def run_importer():
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME).worksheet(TAB_NAME)
    except Exception as e:
        print(f"❌ Auth Error: {e}")
        return

    print("📊 Loading Master Sheet...")
    all_data = sheet.get_all_values()
    rows = all_data[1:] # Skip header

    # Exact General Names (Col A)
    existing_general = {row[0].strip().lower(): i+2 for i, row in enumerate(rows) if row[0]}
    
    # Existing Mappings in I(8), J(9), K(10)
    existing_store_names = {
        "Woolworths": {row[8].lower().strip() for row in rows if len(row) > 8},
        "Coles":      {row[9].lower().strip() for row in rows if len(row) > 9},
        "Aldi":       {row[10].lower().strip() for row in rows if len(row) > 10}
    }

    for shop_name, file_path in DOCS.items():
        print(f"\n--- Scanning {shop_name} for REAL products ---")
        found_names = extract_names_from_docx(file_path)
        
        for name in found_names:
            if name.lower().strip() not in existing_store_names[shop_name]:
                print(f"\n🛒 NEW PRODUCT DETECTED: '{name}'")
                print(f"Action: [1] Type exact Name from Col A to link.")
                print(f"        [2] Type 'NEW' to create a new row.")
                print(f"        [3] Enter to skip.")
                
                user_input = input(f"Input: ").strip()
                if not user_input: continue

                col_idx = {"Woolworths": 9, "Coles": 10, "Aldi": 11}[shop_name]
                
                if user_input.lower() in existing_general:
                    target_row = existing_general[user_input.lower()]
                    print(f"🔗 Linking to existing product...")
                    sheet.update_cell(target_row, col_idx, name)
                elif user_input.upper() == "NEW":
                    gen_name = input("Enter General Name: ").strip()
                    if gen_name:
                        new_row = [""] * 11
                        new_row[0] = gen_name
                        new_row[col_idx-1] = name
                        sheet.append_row(new_row)
                        existing_general[gen_name.lower()] = len(sheet.get_all_values())
    
    print("\n✅ Mapping session complete!")

if __name__ == "__main__":
    run_importer()