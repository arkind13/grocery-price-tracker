import streamlit as st
import pandas as pd
import json
from datetime import datetime

# Page configuration
st.set_page_config(
    page_title="Aussie Grocery Price Tracker",
    page_icon="🛒",
    layout="wide"
)

@st.cache_data(ttl=3600)  # Cache for 1 hour
def load_grocery_data():
    """Load grocery price data from Google Sheets"""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        
        # Define the scope
        scope = [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive'
        ]
        
        # Load credentials from Streamlit secrets
        creds_json = st.secrets["GSHEETS_CREDENTIALS_JSON"]
        creds_dict = json.loads(creds_json)
        
        # Create credentials
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        
        # Connect to Google Sheets
        gc = gspread.authorize(creds)
        sheet = gc.open('AusGrocery_PriceDB')
        worksheet = sheet.sheet1
        
        # Get all data
        data = worksheet.get_all_values()
        
        if len(data) > 1:
            headers = data[0]
            rows = data[1:]
            df = pd.DataFrame(rows, columns=headers)
            
            # Clean and convert price columns
            price_columns = ['Woolworths_Price', 'Coles_Price', 'Aldi_Price']
            for col in price_columns:
                if col in df.columns:
                    # Remove $ and convert to float
                    df[col] = pd.to_numeric(
                        df[col].astype(str).str.replace('$', '').str.replace(',', ''), 
                        errors='coerce'
                    )
            
            return df
        else:
            return pd.DataFrame()
            
    except Exception as e:
        st.error(f"Failed to load data: {str(e)}")
        st.error("Please check your Google Sheets credentials and sheet name.")
        return pd.DataFrame()

def update_prices(product_name, retailer, new_price):
    """Update price for a specific product and retailer"""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        
        # Define the scope
        scope = [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive'
        ]
        
        # Load credentials
        creds_json = st.secrets["GSHEETS_CREDENTIALS_JSON"]
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        
        # Connect
        gc = gspread.authorize(creds)
        sheet = gc.open('AusGrocery_PriceDB')
        worksheet = sheet.sheet1
        
        # Get all data
        all_values = worksheet.get_all_values()
        headers = all_values[0]
        
        # Find column indices
        product_col_idx = headers.index('Product_Name')
        price_col_idx = headers.index(f'{retailer}_Price')
        
        # Find date column if exists
        date_col_idx = None
        if 'Last_Updated' in headers:
            date_col_idx = headers.index('Last_Updated')
        
        # Find product row
        for i, row in enumerate(all_values[1:], start=2):
            if row[product_col_idx] == product_name:
                # Update price (column indices are 1-based in gspread)
                worksheet.update_cell(i, price_col_idx + 1, f"${new_price:.2f}")
                
                # Update date if column exists
                if date_col_idx is not None:
                    worksheet.update_cell(i, date_col_idx + 1, datetime.now().strftime('%Y-%m-%d'))
                
                return True
                
        return False
        
    except Exception as e:
        st.error(f"Failed to update price: {str(e)}")
        return False

def test_connection():
    """Test Google Sheets connection"""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        
        scope = [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive'
        ]
        
        creds_json = st.secrets["GSHEETS_CREDENTIALS_JSON"]
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        
        gc = gspread.authorize(creds)
        sheet = gc.open('AusGrocery_PriceDB')
        worksheet = sheet.sheet1
        
        data = worksheet.get_all_values()
        
        st.success(f"✅ Connection successful! Found {len(data)} rows.")
        st.info(f"📧 Service Account: {creds_dict.get('client_email', 'Unknown')}")
        
        if len(data) > 0:
            st.write("**Headers found:**", data[0])
        
        return True
        
    except Exception as e:
        st.error(f"❌ Connection failed: {str(e)}")
        return False

def main():
    st.title("🛒 **Aussie Grocery Price Tracker**")
    st.markdown("*Compare prices across Woolworths, Coles & ALDI*")
    
    # Connection test button
    if st.button("🔧 Test Connection", help="Test Google Sheets connection"):
        test_connection()
        return
    
    # Load data
    with st.spinner("Loading grocery data..."):
        df = load_grocery_data()
    
    if df.empty:
        st.warning("📋 No data loaded. Please check your connection.")
        st.info("👆 Click 'Test Connection' to troubleshoot.")
        return
    
    st.success(f"✅ Loaded {len(df)} products")
    
    # Sidebar filters
    with st.sidebar:
        st.header("🔍 Filters")
        
        # Category filter if available
        if 'Category' in df.columns:
            categories = ['All'] + sorted(df['Category'].dropna().unique().tolist())
            selected_category = st.selectbox("📂 Category", categories)
        else:
            selected_category = 'All'
        
        # Store filter
        available_stores = []
        if 'Woolworths_Price' in df.columns:
            available_stores.append('Woolworths')
        if 'Coles_Price' in df.columns:
            available_stores.append('Coles')
        if 'Aldi_Price' in df.columns:
            available_stores.append('ALDI')
        
        if available_stores:
            show_stores = st.multiselect(
                "🏪 Show Stores", 
                available_stores, 
                default=available_stores
            )
    
    # Filter data
    filtered_df = df.copy()
    
    if selected_category != 'All' and 'Category' in df.columns:
        filtered_df = filtered_df[filtered_df['Category'] == selected_category]
    
    # Main tabs
    tab1, tab2, tab3 = st.tabs(["📊 Price Comparison", "✏️ Update Prices", "📈 Analytics"])
    
    with tab1:
        st.subheader("🏪 Current Prices")
        
        if not filtered_df.empty:
            # Create price comparison
            price_cols = []
            if 'Woolworths' in show_stores and 'Woolworths_Price' in filtered_df.columns:
                price_cols.append('Woolworths_Price')
            if 'Coles' in show_stores and 'Coles_Price' in filtered_df.columns:
                price_cols.append('Coles_Price')
            if 'ALDI' in show_stores and 'Aldi_Price' in filtered_df.columns:
                price_cols.append('Aldi_Price')
            
            if price_cols:
                for idx, row in filtered_df.iterrows():
                    # Product info
                    st.write(f"**{row.get('Product_Name', 'Unknown Product')}**")
                    
                    if 'Brand' in row and pd.notna(row['Brand']):
                        st.caption(f"Brand: {row['Brand']}")
                    
                    # Price comparison
                    cols = st.columns(len(price_cols) + 1)
                    
                    prices = {}
                    for i, price_col in enumerate(price_cols):
                        store_name = price_col.replace('_Price', '')
                        price = row.get(price_col, 0)
                        
                        if pd.notna(price) and price > 0:
                            prices[store_name] = price
                            
                            with cols[i]:
                                st.metric(store_name, f"${price:.2f}")
                    
                    # Best price indicator
                    if prices:
                        best_store = min(prices, key=prices.get)
                        best_price = prices[best_store]
                        
                        with cols[-1]:
                            st.success(f"🏆 Best: {best_store}")
                            if len(prices) > 1:
                                max_price = max(prices.values())
                                savings = max_price - best_price
                                if savings > 0:
                                    st.info(f"💰 Save: ${savings:.2f}")
                    
                    st.divider()
            else:
                st.info("Select at least one store to compare prices.")
        else:
            st.info("No products found matching your filters.")
    
    with tab2:
        st.subheader("✏️ Manual Price Updates")
        st.info("💡 Update Woolworths & Coles prices manually. ALDI prices update automatically.")
        
        if not df.empty and 'Product_Name' in df.columns:
            col1, col2, col3 = st.columns(3)
            
            with col1:
                products = sorted(df['Product_Name'].dropna().tolist())
                selected_product = st.selectbox("📦 Select Product", products)
            
            with col2:
                update_stores = [store for store in ['Woolworths', 'Coles'] 
                               if f'{store}_Price' in df.columns]
                selected_retailer = st.selectbox("🏪 Retailer", update_stores)
            
            with col3:
                new_price = st.number_input("💰 New Price ($)", min_value=0.01, step=0.01, format="%.2f")
            
            if st.button("🔄 Update Price", type="primary"):
                with st.spinner("Updating price..."):
                    if update_prices(selected_product, selected_retailer, new_price):
                        st.success(f"✅ Updated {selected_product} - {selected_retailer}: ${new_price:.2f}")
                        st.cache_data.clear()  # Clear cache
                        st.rerun()
                    else:
                        st.error("❌ Failed to update price. Please check the product name.")
    
    with tab3:
        st.subheader("📈 Price Analytics")
        
        if not filtered_df.empty:
            price_cols = [col for col in ['Woolworths_Price', 'Coles_Price', 'Aldi_Price'] 
                         if col in filtered_df.columns]
            
            if len(price_cols) >= 2:
                # Average prices by store
                avg_prices = {}
                for col in price_cols:
                    store_name = col.replace('_Price', '')
                    valid_prices = filtered_df[col].dropna()
                    valid_prices = valid_prices[valid_prices > 0]
                    
                    if len(valid_prices) > 0:
                        avg_prices[store_name] = valid_prices.mean()
                
                if avg_prices:
                    st.write("**Average Prices by Store**")
                    
                    chart_data = pd.DataFrame(list(avg_prices.items()), 
                                            columns=['Store', 'Average Price'])
                    st.bar_chart(chart_data.set_index('Store'))
                    
                    # Show the numbers too
                    for store, avg_price in avg_prices.items():
                        st.metric(f"{store} Average", f"${avg_price:.2f}")

if __name__ == "__main__":
    main()
