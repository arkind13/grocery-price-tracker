import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json
from data.sheets_manager import SheetsManager

# --- 1. CONFIGURATION / CONSTANTS ---
ALDI_HOME_BRANDS = [
    "choceur", "westacre", "blackstone", "mamia", "bakers life", 
    "farmdale", "remano", "dairy fine", "logix", "trimat"
]

# Page config
st.set_page_config(
    page_title="🛒 Aussie Grocery Price Tracker",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS (unchanged)
st.markdown("""
<style>
    .main-header { font-size: 2.5rem; color: #2E8B57; text-align: center; margin-bottom: 2rem; }
    .metric-container { background-color: #f0f8f0; padding: 1rem; border-radius: 0.5rem; margin: 0.5rem 0; }
    .price-card { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 1rem; border-radius: 0.5rem; margin: 0.5rem 0; }
    .savings-positive { color: #28a745; font-weight: bold; }
    .savings-negative { color: #dc3545; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=300)
def get_sheets_manager():
    """Initialize SheetsManager with Google Sheets ID from secrets."""
    try:
        spreadsheet_id = st.secrets["google_sheets"]["spreadsheet_id"]
        return SheetsManager(spreadsheet_id=spreadsheet_id)
    except Exception as e:
        st.error(f"❌ Failed to initialize SheetsManager: {e}")
        return None

@st.cache_data(ttl=300)
def load_grocery_data():
    """Load grocery price data from Google Sheets."""
    try:
        manager = get_sheets_manager()
        if manager is None:
            return pd.DataFrame()

        sheet = manager.get_spreadsheet('AusGrocery_PriceDB')
        worksheet = sheet.sheet1
        data = worksheet.get_all_values()

        if len(data) > 1:
            headers = data[0]
            rows = data[1:]
            df = pd.DataFrame(rows, columns=headers)

            # Clean price columns
            price_columns = ['Woolworths_Price', 'Coles_Price', 'Aldi_Price']
            for col in price_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(
                        df[col].astype(str).str.replace('$', '').str.replace(',', ''), 
                        errors='coerce'
                    )

            # Convert date
            if 'Last_Updated' in df.columns:
                df['Last_Updated'] = pd.to_datetime(df['Last_Updated'], errors='coerce')

            return df
        else:
            return pd.DataFrame()

    except Exception as e:
        st.error(f"❌ Failed to load data: {e}")
        return pd.DataFrame()

def calculate_savings(row):
    """Calculate best store and savings for a row."""
    prices = {}
    for store in ['Woolworths', 'Coles', 'Aldi']:
        price_col = f"{store}_Price"
        if price_col in row.index and pd.notna(row[price_col]):
            try:
                p = float(row[price_col])
            except (ValueError, TypeError):
                try:
                    p = float(str(row[price_col]).replace('$', '').replace(',', ''))
                except:
                    continue
            if p > 0:
                prices[store] = p

    if not prices:
        return None, 0.0, 0.0

    min_price = min(prices.values())
    max_price = max(prices.values())
    best_store = min(prices, key=prices.get)
    savings = max_price - min_price
    savings_percent = (savings / max_price) * 100 if max_price > 0 else 0

    return best_store, savings, savings_percent

def display_product_comparison(df, sort_mode=None):
    """Display product comparison with savings analysis, optionally sorted by store pair."""
    if df.empty:
        st.warning("No product data available")
        return

    # --- Sorting by selected store pair ---
    if sort_mode and sort_mode != "None":
        store1, store2 = sort_mode.split(" > ")  # e.g., "Woolworths > Coles"
        price_col1 = f"{store1}_Price"
        price_col2 = f"{store2}_Price"

        if price_col1 in df.columns and price_col2 in df.columns:
            p1 = pd.to_numeric(df[price_col1].astype(str).str.replace('$', '').str.replace(',', ''), errors='coerce')
            p2 = pd.to_numeric(df[price_col2].astype(str).str.replace('$', '').str.replace(',', ''), errors='coerce')

            df = df.copy()
            df['_sort_diff'] = p1.fillna(0) - p2.fillna(0)
            df = df.sort_values('_sort_diff', ascending=False)
            df = df.drop(columns=['_sort_diff'])
            st.info(f"📊 Sorted by savings when buying at **{store1}** instead of **{store2}** (largest savings first)")

    # Search and filter
    col1, col2 = st.columns([2, 1])
    with col1:
        search_term = st.text_input("🔍 Search products:", placeholder="Enter product name...")
    with col2:
        categories = ['All'] + sorted(df['Category'].dropna().unique().tolist()) if 'Category' in df.columns else ['All']
        selected_category = st.selectbox("🏷️ Filter by category:", categories)

    filtered_df = df.copy()
    if search_term:
        filtered_df = filtered_df[filtered_df['Product_Name'].str.contains(search_term, case=False, na=False)]
    if selected_category != 'All':
        filtered_df = filtered_df[filtered_df['Category'] == selected_category]

    if filtered_df.empty:
        st.warning("No products match your search criteria")
        return

    st.subheader("🛒 Price Comparison")
    # (The rest of the display code remains exactly as you had it in your original snippet)
    # I'll omit it here for brevity, but you should include the expander loop and price cards.
    # For full code, see your original `display_product_comparison` after line ~150.
    # I will keep a placeholder.
    st.write("Displaying products... (add your original expander logic here)")

def load_shopping_lists():
    # ... unchanged (your existing function) ...
    pass

def load_price_history():
    # ... unchanged ...
    pass

def main():
    st.markdown('<h1 class="main-header">🛒 Aussie Grocery Price Tracker</h1>', unsafe_allow_html=True)

    with st.sidebar:
        st.header("🎛️ Controls")
        if st.button("🔄 Refresh Data", type="primary"):
            st.cache_data.clear()
            st.rerun()
        if st.button("🧪 Test Connection"):
            manager = get_sheets_manager()
            if manager:
                st.success("✅ Connected to Google Sheets!")

    df = load_grocery_data()

    if not df.empty:
        st.success(f"📊 Successfully loaded {len(df)} products!")

        # Summary metrics (your existing code)
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("🏷️ Total Products", len(df))
        with col2:
            if 'Category' in df.columns:
                st.metric("📂 Categories", df['Category'].nunique())
        with col3:
            price_cols = ['Woolworths_Price', 'Coles_Price', 'Aldi_Price']
            all_prices = []
            for col in price_cols:
                if col in df.columns:
                    prices = pd.to_numeric(df[col], errors='coerce').dropna()
                    all_prices.extend(prices.tolist())
            if all_prices:
                st.metric("💰 Avg Price", f"${sum(all_prices)/len(all_prices):.2f}")
        with col4:
            total_savings = 0.0
            for _, row in df.iterrows():
                _, savings, _ = calculate_savings(row)
                if savings:
                    total_savings += float(savings)
            st.metric("💸 Total Savings Available", f"${total_savings:.2f}")

        # --- Sort Buttons ---
        st.subheader("🔽 Sort by Max Savings")
        pairs = [
            ("Woolworths > Coles", "🅰️ WW > Coles"),
            ("Woolworths > Aldi", "🅱️ WW > Aldi"),
            ("Coles > Woolworths", "🅲 Coles > WW"),
            ("Coles > Aldi", "🅳 Coles > Aldi"),
            ("Aldi > Woolworths", "🅴 Aldi > WW"),
            ("Aldi > Coles", "🅵 Aldi > Coles"),
        ]

        if "sort_mode" not in st.session_state:
            st.session_state.sort_mode = None

        cols = st.columns(len(pairs) + 1)
        for i, (mode, label) in enumerate(pairs):
            with cols[i]:
                if st.button(label):
                    st.session_state.sort_mode = mode
                    st.rerun()
        with cols[-1]:
            if st.button("🔁 Reset"):
                st.session_state.sort_mode = None
                st.rerun()

        display_product_comparison(df, st.session_state.sort_mode)

    else:
        st.warning("📭 No product data found. Please check your Google Sheets connection and data.")
        st.info("""
        **Expected sheet structure:**
        - Product_Name
        - Category
        - Size
        - Woolworths_Price
        - Coles_Price
        - Aldi_Price
        - Last_Updated
        """)

if __name__ == "__main__":
    main()
