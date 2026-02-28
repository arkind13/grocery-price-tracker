# aldi_scraper.py
import re
from playwright.sync_api import sync_playwright
from typing import List, Dict, Optional
# Replace with proper imports:
import sys
import os
from playwright.sync_api import sync_playwright
from typing import List, Dict, Optional
# Fix the import path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
try:
    from data.sheets_manager import manager
    print("✓ Successfully imported manager")
except ImportError as e:
    print(f"✗ Failed to import manager: {e}")
    # Create mock for debugging
    class MockManager:
        def get_products_master(self):
            return []
        def update_price(self, product_name, retailer, price):
            pass
    manager = MockManager()



# Define home brands used by Aldi Australia
ALDI_HOME_BRANDS = [
    "choceur", "westacre", "blackstone", "mamia", "bakers life", 
    "farmdale", "remano", "dairy fine", "logix", "trimat", "cowbelle", "emporium selection", "brooklea", "yoguri", "bramwells",
    "goldenvale", "imperial grain", "asia green garden", "sprinters", "belmont", "knoppers", "nutoka",
    "broad oak frams", "berg", "ironbark", "ocean rise", "tandil", "di-san", "power force", "confidence", "just organic"
]

def find_best_aldi_match(results: List[Dict], target_size: float, brand_type: str) -> Optional[Dict]:
    """
    Find the best matching Aldi product based on size and brand criteria.
    
    Args:
        results: List of dictionaries with keys 'title', 'price'
        target_size: Target size in grams (float)
        brand_type: Either 'Home Brand' or 'Specific'
        
    Returns:
        Dictionary containing the best match or None if no valid matches
    """
    best_match = None
    min_diff = float('inf')
    
    for res in results:
        # Extract size from title
        sizes = re.findall(r'(\d+(?:\.\d+)?)', res['title'].lower())
        if not sizes:
            continue
            
        try:
            res_size = float(sizes[0])
        except ValueError:
            continue  # Skip invalid sizes
            
        # Apply brand filters
        title_lower = res['title'].lower()
        
        if brand_type == 'Home Brand':
            # Check if any home brand is in the title
            if not any(brand.lower() in title_lower for brand in ALDI_HOME_BRANDS):
                continue
        elif brand_type == 'Specific':
            # For specific brand searches, we expect the keyword to be part of the title
            # This is handled outside this function in the calling logic
            pass  # We will trust that the caller passed only relevant results
        
        # Compute size difference
        diff = abs(res_size - target_size)
        if diff < min_diff:
            min_diff = diff
            best_match = res
            
    return best_match

def scrape_aldi_search(page, keyword: str) -> List[Dict]:
    """
    Perform a search on Aldi Australia website and extract product info.
    
    Args:
        page: Playwright Page object
        keyword: Search term (e.g., 'milk')
        
    Returns:
        List of product dictionaries with 'title' and 'price'
    """
    url = f"https://www.aldi.com.au/en/search-results/?q={keyword}"
    
    try:
        page.goto(url, timeout=30000)
        page.wait_for_selector('.product-tile', timeout=10000)
    except Exception as e:
        print(f"[ERROR] Failed to load search page for '{keyword}': {e}")
        return []
    
    products = []
    elems = page.query_selector_all('.product-tile')
    
    # Process top 5 results (adjustable)
    for elem in elems[:5]:
        try:
            title_elem = elem.query_selector('.product-name')
            title = title_elem.inner_text() if title_elem else ""
            
            price_elem = elem.query_selector('.price')
            price_str = price_elem.inner_text() if price_elem else ""
            
            # Clean and convert price to float
            price_clean = price_str.strip('$').replace(',', '')
            price = float(price_clean) if price_clean.replace('.', '').isdigit() else 0.0
            
            products.append({
                'title': title,
                'price': price
            })
        except Exception as e:
            print(f"[WARNING] Could not parse product from element: {e}")
            continue
            
    return products

def run_aldi_scraper():
    """
    Main scraper function that fetches products, searches Aldi, finds best matches,
    and updates the spreadsheet with new prices.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()
        
        products_master = manager.get_products_master()
        
        for prod in products_master:
            product_name = prod['Product_Name']
            keyword = prod['Search_Keyword_Aldi']
            target_size = prod['Size']
            brand_type = prod['Brand_Type']
            
            # Skip empty keywords
            if not keyword:
                continue
                
            results = scrape_aldi_search(page, keyword)
            best = find_best_aldi_match(results, target_size, brand_type)
            
            if best:
                manager.update_price(product_name, 'Aldi', best['price'])
                
        browser.close()

