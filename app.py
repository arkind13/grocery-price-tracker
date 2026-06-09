import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json
from data.sheets_manager import SheetsManager

# ... (existing constants, CSS, helper functions remain unchanged) ...

def display_product_comparison(df, sort_mode=None):
    """Display product comparison with savings analysis, optionally sorted by store pair savings"""
    if df.empty:
        st.warning("No product data available")
        return

    # --- Sorting by selected store pair ---
    if sort_mode and sort_mode != "None":
        # sort_mode is like "Woolworths > Coles"
        store1, store2 = sort_mode.split(" > ")  # e.g., "Woolworths > Coles" -> ["Woolworths", "Coles"]
        price_col1 = f"{store1}_Price"
        price_col2 = f"{store2}_Price"

        # Ensure both price columns exist
        if price_col1 in df.columns and price_col2 in df.columns:
            # Compute numeric prices
            p1 = pd.to_numeric(df[price_col1].astype(str).str.replace('$', '').str.replace(',', ''), errors='coerce')
            p2 = pd.to_numeric(df[price_col2].astype(str).str.replace('$', '').str.replace(',', ''), errors='coerce')

            # Savings = price1 - price2 (positive when store1 is cheaper)
            savings_col = p1 - p2
            df = df.copy()
            df['_sort_diff'] = savings_col.fillna(0)  # Replace NaN with 0 (or drop?)
            df = df.sort_values('_sort_diff', ascending=False)  # Biggest saving first
            # Remove temporary column
            df = df.drop(columns=['_sort_diff'])
            st.info(f"📊 Sorted by savings when buying at **{store1}** instead of **{store2}** (largest savings first)")

    # --- Existing search and filter ---
    col1, col2 = st.columns([2, 1])

    with col1:
        search_term = st.text_input("🔍 Search products:", placeholder="Enter product name...")

    with col2:
        categories = ['All'] + sorted(df['Category'].dropna().unique().tolist()) if 'Category' in df.columns else ['All']
        selected_category = st.selectbox("🏷️ Filter by category:", categories)

    # Filter data
    filtered_df = df.copy()

    if search_term:
        filtered_df = filtered_df[
            filtered_df['Product_Name'].str.contains(search_term, case=False, na=False)
        ]

    if selected_category != 'All':
        filtered_df = filtered_df[filtered_df['Category'] == selected_category]

    if filtered_df.empty:
        st.warning("No products match your search criteria")
        return

    # Display products
    st.subheader("🛒 Price Comparison")
    # ... rest of the display logic (unchanged) ...

def main():
    """Main application"""
    st.markdown('<h1 class="main-header">🛒 Aussie Grocery Price Tracker</h1>', unsafe_allow_html=True)

    # Sidebar Controls
    with st.sidebar:
        st.header("🎛️ Controls")
        
        if st.button("🔄 Refresh Data", type="primary"):
            st.cache_data.clear()
            st.rerun()
        
        if st.button("🧪 Test Connection"):
            manager = get_sheets_manager()
            if manager:
                st.success("✅ Connected to Google Sheets!")

    # Main content
    df = load_grocery_data()

    if not df.empty:
        st.success(f"📊 Successfully loaded {len(df)} products!")

        # Summary metrics (unchanged)
        col1, col2, col3, col4 = st.columns(4)
        # ... existing metric code ...

        # --- Sort Buttons ---
        st.subheader("🔽 Sort by Max Savings")
        # Define store pairs (6 directions)
        pairs = [
            ("Woolworths > Coles", "🅰️ WW > Coles"),
            ("Woolworths > Aldi", "🅱️ WW > Aldi"),
            ("Coles > Woolworths", "🅲 Coles > WW"),
            ("Coles > Aldi", "🅳 Coles > Aldi"),
            ("Aldi > Woolworths", "🅴 Aldi > WW"),
            ("Aldi > Coles", "🅵 Aldi > Coles"),
        ]

        # Initialize session_state for sort_mode if not present
        if "sort_mode" not in st.session_state:
            st.session_state.sort_mode = None

        # Create a row of 6 columns (adjust widths if needed)
        cols = st.columns(len(pairs) + 1)  # extra column for reset

        # Place buttons in each column
        for i, (mode, label) in enumerate(pairs):
            with cols[i]:
                if st.button(label):
                    st.session_state.sort_mode = mode
                    st.rerun()  # force rerun to apply sorting

        # Reset button
        with cols[-1]:
            if st.button("🔁 Reset"):
                st.session_state.sort_mode = None
                st.rerun()

        # Display product comparison with current sort mode
        display_product_comparison(df, st.session_state.sort_mode)

    else:
        st.warning("📭 No product data found. Please check your Google Sheets connection and data.")
        # ... info text ...

if __name__ == "__main__":
    main()
