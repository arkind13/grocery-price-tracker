# cd C:\Users\User\Grocery_Project - folder of my script
# # python Woolworths_Historical.py - to run .py code

import pandas as pd
from docx import Document
import re

# --- CONFIGURATION ---
INPUT_FILE = 'woolworths_list.docx'
OUTPUT_FILE = 'woolworths_master_comparison.csv'

def parse_product_details(exact_name):
    """
    Logic to break down a Woolworths string into components.
    Example: 'Oatly Barista Edition Oat Milk 1l'
    """
    # 1. Extract Size (e.g., 1L, 500g, 1.5kg, 12pk, 400ml)
    size_pattern = r'(\d+\.?\d*\s?(?:kg|g|l|ml|pk|pack|ea|units|oz)\b)'
    size_match = re.search(size_pattern, exact_name, re.IGNORECASE)
    size = size_match.group(0) if size_match else "N/A"
    
    # 2. Extract Brand (Usually the first 1-2 words)
    # Common Woolworths brands to help the logic
    brands = ['Woolworths', 'Macro', 'Oatly', 'Devondale', 'A2', 'Bega', 'Huggies']
    found_brand = "Other"
    for b in brands:
        if b.lower() in exact_name.lower():
            found_brand = b
            break
    
    # If not in the list, we'll assume the first word is the brand
    if found_brand == "Other":
        found_brand = exact_name.split()[0]

    # 3. Derive Generic Name
    # Remove the size and the brand from the string to get the core product
    generic = exact_name.replace(size, "").replace(found_brand, "").strip()
    
    # 4. Guess Category (Simple Logic)
    category = "General"
    if any(x in exact_name.lower() for x in ['milk', 'cheese', 'yogurt']): category = "Dairy"
    elif any(x in exact_name.lower() for x in ['apple', 'banana', 'potato', 'onion']): category = "Fruit & Veg"
    elif any(x in exact_name.lower() for x in ['bread', 'wrap', 'loaf']): category = "Bakery"
    elif any(x in exact_name.lower() for x in ['chicken', 'beef', 'lamb', 'mince']): category = "Meat"

    return found_brand, generic, size, category

def process_word_doc(file_path):
    doc = Document(file_path)
    # Extract lines, keeping everything that isn't price/UI noise
    raw_names = []
    for p in doc.paragraphs:
        line = p.text.strip()
        if line and not any(x in line for x in ['$', 'Add to', 'Save', 'Stock', 'Out of']):
            if len(line) > 3: # Ignore tiny fragments
                raw_names.append(line)
    
    # Remove duplicates but keep the "Exact Name" variants (like different sizes)
    unique_names = list(dict.fromkeys(raw_names))
    
    data_list = []
    for name in unique_names:
        brand, generic, size, cat = parse_product_details(name)
        data_list.append({
            'Woolworths Exact Name': name,
            'Brand': brand,
            'Generic Name': generic,
            'Size': size,
            'Category': cat
        })
    
    return pd.DataFrame(data_list)

# --- EXECUTION ---
try:
    df = process_word_doc(INPUT_FILE)
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"Success! Created {OUTPUT_FILE} with {len(df)} products.")
except Exception as e:
    print(f"Error: {e}")