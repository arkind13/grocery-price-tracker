import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json
from data.sheets_manager import SheetsManager

# Page config
st.set_page_config(
    page_title="🛒 Aussie Grocery Price Tracker",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        color: #2E8B57;
        text-align: center;
        margin-bottom: 2rem;
    }
    .metric-container {
        background-color: #f0f8f0;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .price-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .savings-positive {
        color: #28a745;
        font-weight: bold;
    }
    .savings-negative {
        color: #dc3545;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=300)
def get_sheets_manager(): return SheetsManager()
    """Establish connection to Google Sheets using service account"""
    try:
        # Get credentials from Streamlit secrets
        credentials_dict = dict(st.secrets["gcp_service_account"])
        
        # Create credentials object
        credentials = Credentials.from_service_account_info(
            credentials_dict,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
        )
        
        # Create gspread client
        gc = gspread.authorize(credentials)
        
        return gc, credentials_dict.get('client_email', 'Unknown')
        
    except Exception as e:
        st.error(f"Failed to connect to Google Sheets: {str(e)}")
        return None, None

@st.cache_data(ttl=300)
def load_grocery_data():
    """Load grocery price data from Google Sheets"""
    try:
        manager = get_sheets_manager()
        if manager is None:
            return pd.DataFrame()
        
        # Open the spreadsheet
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
                    df[col] = pd.to_numeric(
                        df[col].astype(str).str.replace('$', '').str.replace(',', ''), 
                        errors='coerce'
                    )
            
            # Convert Last_Updated to datetime
            if 'Last_Updated' in df.columns:
                df['Last_Updated'] = pd.to_datetime(df['Last_Updated'], errors='coerce')
            
            return df
        else:
            return pd.DataFrame()
            
    except Exception as e:
        st.error(f"Failed to load data: {str(e)}")
        return pd.DataFrame()

def load_shopping_lists():
    """Load shopping lists from Google Sheets"""
    try:
        manager = get_sheets_manager()
        if manager is None:
            return pd.DataFrame()
        
        sheet = gc.open('AusGrocery_PriceDB')
        
        # Try to get shopping lists worksheet
        try:
            worksheet = sheet.worksheet('User_Shopping_Lists')
            data = worksheet.get_all_values()
            
            if len(data) > 1:
                headers = data[0]
                rows = data[1:]
                df = pd.DataFrame(rows, columns=headers)
                
                # Convert quantity to numeric
                if 'Quantity' in df.columns:
                    df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce')
                
                # Convert date
                if 'Created_Date' in df.columns:
                    df['Created_Date'] = pd.to_datetime(df['Created_Date'], errors='coerce')
                
                return df
            else:
                return pd.DataFrame()
                
        except gspread.WorksheetNotFound:
            # Create the worksheet if it doesn't exist
            worksheet = sheet.add_worksheet(
                title='User_Shopping_Lists',
                rows=100,
                cols=4
            )
            # Add headers
            worksheet.update('A1:D1', [['List_Name', 'Product_Name', 'Quantity', 'Created_Date']])
            return pd.DataFrame()
            
    except Exception as e:
        st.error(f"Failed to load shopping lists: {str(e)}")
        return pd.DataFrame()

def load_price_history():
    """Load price history from Google Sheets"""
    try: manager = get_sheets_manager()
        if manager is None:
            return pd.DataFrame()
        
        sheet = gc.open('AusGrocery_PriceDB')
        
        # Try to get price history worksheet
        try:
            worksheet = sheet.worksheet('Price_History')
            data = worksheet.get_all_values()
            
            if len(data) > 1:
                headers = data[0]
                rows = data[1:]
                df = pd.DataFrame(rows, columns=headers)
                
                # Convert price to numeric
                if 'Price' in df.columns:
                    df['Price'] = pd.to_numeric(
                        df['Price'].astype(str).str.replace('$', '').str.replace(',', ''), 
                        errors='coerce'
                    )
                
                # Convert date
                if 'Date' in df.columns:
                    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
                
                return df
            else:
                return pd.DataFrame()
                
        except gspread.WorksheetNotFound:
            # Create the worksheet if it doesn't exist
            worksheet = sheet.add_worksheet(
                title='Price_History',
                rows=1000,
                cols=4
            )
            # Add headers
            worksheet.update('A1:D1', [['Product_Name', 'Store', 'Price', 'Date']])
            return pd.DataFrame()
            
    except Exception as e:
        st.error(f"Failed to load price history: {str(e)}")
        return pd.DataFrame()

def calculate_savings(row):
    """Calculate savings and best deals for a product"""
    prices = {}
    stores = ['Woolworths', 'Coles', 'Aldi']
    
    for store in stores:
        price_col = f"{store}_Price"
        if price_col in row.index and pd.notna(row[price_col]) and row[price_col] > 0:
            prices[store] = float(row[price_col])
    
    if not prices:
        return None, None, None
    
    min_price = min(prices.values())
    max_price = max(prices.values())
    best_store = min(prices, key=prices.get)
    
    savings = max_price - min_price
    savings_percent = (savings / max_price) * 100 if max_price > 0 else 0
    
    return best_store, savings, savings_percent

def display_product_comparison(df):
    """Display product comparison with savings analysis"""
    if df.empty:
        st.warning("No product data available")
        return
    
    # Add search and filter options
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
    
    for idx, row in filtered_df.iterrows():
        with st.expander(f"🏷️ {row['Product_Name']}", expanded=True):
            col1, col2, col3, col4 = st.columns(4)
            
            # Price display
            stores = [
                ('Woolworths', 'Woolworths_Price', '#0066CC'),
                ('Coles', 'Coles_Price', '#FF0000'), 
                ('Aldi', 'Aldi_Price', '#FF6600')
            ]
            
            prices = {}
            for store_name, price_col, color in stores:
                price = row.get(price_col, 0)
                if pd.notna(price) and price > 0:
                    prices[store_name] = float(price)
            
            if prices:
                best_store, savings, savings_percent = calculate_savings(row)
                
                # Display prices
                for i, (store_name, price_col, color) in enumerate(stores):
                    with [col1, col2, col3][i]:
                        price = row.get(price_col, 0)
                        if pd.notna(price) and price > 0:
                            price_float = float(price)
                            is_best = store_name == best_store
                            
                            st.markdown(f"""
                            <div style="background-color: {'#e8f5e8' if is_best else '#f8f9fa'}; 
                                        border: {'3px solid #28a745' if is_best else '1px solid #dee2e6'};
                                        padding: 1rem; border-radius: 0.5rem; text-align: center;">
                                <h4 style="color: {color}; margin: 0;">{store_name}</h4>
                                <h2 style="margin: 0.5rem 0;">${price_float:.2f}</h2>
                                {'<span style="color: #28a745; font-weight: bold;">✅ BEST DEAL</span>' if is_best else ''}
                            </div>
                            """, unsafe_allow_html=True)
                        else:
                            st.markdown(f"""
                            <div style="background-color: #f8f9fa; border: 1px solid #dee2e6;
                                        padding: 1rem; border-radius: 0.5rem; text-align: center;">
                                <h4 style="color: {color}; margin: 0;">{store_name}</h4>
                                <h2 style="margin: 0.5rem 0; color: #6c757d;">N/A</h2>
                            </div>
                            """, unsafe_allow_html=True)
                
                # Savings information
                with col4:
                    if savings > 0:
                        st.markdown(f"""
                        <div style="background-color: #d4edda; border: 1px solid #c3e6cb;
                                    padding: 1rem; border-radius: 0.5rem; text-align: center;">
                            <h4 style="color: #155724; margin: 0;">💰 Potential Savings</h4>
                            <h3 style="margin: 0.5rem 0; color: #28a745;">${savings:.2f}</h3>
                            <p style="margin: 0; color: #155724;">({savings_percent:.1f}% off)</p>
                            <small>Choose {best_store} instead</small>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown(f"""
                        <div style="background-color: #f8f9fa; border: 1px solid #dee2e6;
                                    padding: 1rem; border-radius: 0.5rem; text-align: center;">
                            <h4 style="color: #6c757d; margin: 0;">📊 Same Price</h4>
                            <p style="margin: 0;">All stores match</p>
                        </div>
                        """, unsafe_allow_html=True)
            
            # Additional info
            if 'Category' in row.index and pd.notna(row['Category']):
                st.caption(f"📂 Category: {row['Category']}")
            
            if 'Last_Updated' in row.index and pd.notna(row['Last_Updated']):
                st.caption(f"🕒 Last updated: {row['Last_Updated']}")

def main():
    """Main application"""
    st.markdown('<h1 class="main-header">🛒 Aussie Grocery Price Tracker</h1>', unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.header("🎛️ Controls")
        
        # Data refresh
        if st.button("🔄 Refresh Data", type="primary"):
            st.cache_data.clear()
            st.rerun()
        
        # Connection test
    if st.button("🧪 Test Connection"):
        manager = get_sheets_manager()
        try:
            # test read of products sheet
            df_test = manager.get_products_master()
            st.success("✅ Connected and Products_Master loaded")
            st.success(f"✅ Data loaded successfully: {len(df_test)} rows")
        except Exception as e:
            st.error(f"❌ Sheet access failed: {str(e)}")
            else:
                st.error("❌ Connection failed")
    
    # Main content
    df = load_grocery_data()
    
    if not df.empty:
        st.success(f"📊 Successfully loaded {len(df)} products!")
        
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            total_products = len(df)
            st.metric("🏷️ Total Products", total_products)
        
        with col2:
            if 'Category' in df.columns:
                categories = df['Category'].nunique()
                st.metric("📂 Categories", categories)
        
        with col3:
            # Calculate average price
            price_cols = ['Woolworths_Price', 'Coles_Price', 'Aldi_Price']
            all_prices = []
            for col in price_cols:
                if col in df.columns:
                    prices = pd.to_numeric(df[col], errors='coerce').dropna()
                    all_prices.extend(prices.tolist())
            
            if all_prices:
                avg_price = sum(all_prices) / len(all_prices)
                st.metric("💰 Avg Price", f"${avg_price:.2f}")
        
        with col4:
            # Calculate total potential savings
            total_savings = 0
            for _, row in df.iterrows():
                _, savings, _ = calculate_savings(row)
                if savings:
                    total_savings += savings
            
            st.metric("💸 Total Savings Available", f"${total_savings:.2f}")
        
        # Display product comparison
        display_product_comparison(df)
        
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

# Add this button temporarily to clear cache
if st.button("🔄 Clear Cache & Reload"):
    st.cache_data.clear()
    st.rerun()
