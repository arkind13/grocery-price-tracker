import streamlit as st
import pandas as pd
from datetime import datetime

# Page configuration
st.set_page_config(
    page_title="Aussie Grocery Price Tracker",
    page_icon="🛒",
    layout="wide"
)

def get_google_sheets_connection():
    """Create Google Sheets connection from Streamlit secrets"""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        
        # Define the scope
        scope = [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive'
        ]
        
        # Load credentials from Streamlit secrets
        credentials_dict = {
            "type": st.secrets["gcp_service_account"]["type"],
            "project_id": st.secrets["gcp_service_account"]["project_id"],
            "private_key_id": st.secrets["gcp_service_account"]["private_key_id"],
            "private_key": st.secrets["gcp_service_account"]["private_key"],
            "client_email": st.secrets["gcp_service_account"]["client_email"],
            "client_id": st.secrets["gcp_service_account"]["client_id"],
            "auth_uri": st.secrets["gcp_service_account"]["auth_uri"],
            "token_uri": st.secrets["gcp_service_account"]["token_uri"],
            "auth_provider_x509_cert_url": st.secrets["gcp_service_account"]["auth_provider_x509_cert_url"]
        }
        
        # Create credentials
        creds = Credentials.from_service_account_info(credentials_dict, scopes=scope)
        
        # Connect to Google Sheets
        gc = gspread.authorize(creds)
        
        return gc, credentials_dict["client_email"]
        
    except Exception as e:
        st.error(f"Failed to create connection: {str(e)}")
        return None, None

def test_connection():
    """Test Google Sheets connection and show detailed info"""
    st.subheader("🔧 Connection Diagnostics")
    
    try:
        # Test credentials loading
        with st.spinner("Loading credentials..."):
            gc, client_email = get_google_sheets_connection()
        
        if gc is None:
            st.error("❌ Failed to load credentials")
            return False
            
        st.success(f"✅ Credentials loaded successfully")
        st.info(f"📧 Service Account: {client_email}")
        
        # Test sheet access
        with st.spinner("Testing sheet access..."):
            try:
                sheet = gc.open('AusGrocery_PriceDB')
                st.success("✅ Sheet 'AusGrocery_PriceDB' found and accessible")
                
                # Test data reading
                worksheet = sheet.sheet1
                data = worksheet.get_all_values()
                
                st.success(f"✅ Data loaded successfully: {len(data)} rows")
                
                if len(data) > 0:
                    st.write("**Sheet Headers:**", data[0])
                    
                    if len(data) > 1:
                        st.write("**Sample Data (first row):**", data[1])
                else:
                    st.warning("⚠️ Sheet is empty")
                
                return True
                
            except Exception as sheet_error:
                st.error(f"❌ Cannot access sheet: {str(sheet_error)}")
                st.error("**Possible issues:**")
                st.error("- Sheet name 'AusGrocery_PriceDB' doesn't exist")
                st.error("- Service account doesn't have access to the sheet")
                st.error("- Sheet is not shared with the service account")
                
                return False
                
    except Exception as e:
        st.error(f"❌ Connection test failed: {str(e)}")
        
        if "Invalid control character" in str(e):
            st.error("**Private Key Formatting Issue:**")
            st.code("""
The private key in your secrets has formatting problems.

In your Streamlit Secrets, make sure the private_key line looks exactly like this:
private_key = "-----BEGIN PRIVATE KEY-----\\nMIIEv...YOUR_KEY...\\n-----END PRIVATE KEY-----\\n"

Keep the \\n characters as-is from your JSON file.
            """)
        
        return False

@st.cache_data(ttl=3600)  # Cache for 1 hour
def load_grocery_data():
    """Load grocery price data from Google Sheets"""
    try:
        gc, client_email = get_google_sheets_connection()
        
        if gc is None:
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
        return pd.DataFrame()

def update_prices(product_name, retailer, new_price):
    """Update price for a specific product and retailer"""
    try:
        gc, client_email = get_google_sheets_connection()
        
        if gc is None:
            return False
        
        # Open sheet
        sheet = gc.open('AusGrocery_PriceDB')
        worksheet = sheet.sheet1
        
        # Get all data
        all_values = worksheet.get_all_values()
        headers = all_values[0]
        
        # Find column indices
        if 'Product_Name' not in headers:
            st.error("'Product_Name' column not found in sheet")
            return False
            
        product_col_idx = headers.index('Product_Name')
        
        price_col_name = f'{retailer}_Price'
        if price_col_name not in headers:
            st.error(f"'{price_col_name}' column not found in sheet")
            return False
            
        price_col_idx = headers.index(price_col_name)
        
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
                
        st.error(f"Product '{product_name}' not found in sheet")
        return False
        
    except Exception as e:
        st.error(f"Failed to update price: {str(e)}")
        return False

def main():
    st.title("🛒 **Aussie Grocery Price Tracker**")
    st.markdown("*Compare prices across Woolworths, Coles & ALDI*")
    
    # Add connection test section
    with st.expander("🔧 Connection Test & Diagnostics", expanded=False):
        if st.button("Test Google Sheets Connection", type="primary"):
            test_connection()
    
    # Load data
    with st.spinner("Loading grocery data..."):
        df = load_grocery_data()
    
    if df.empty:
        st.warning("📋 No data loaded from Google Sheets")
        st.info("👆 Use the Connection Test above to diagnose issues")
        
        st.markdown("---")
        st.subheader("📝 Setup Checklist")
        st.markdown("""
        **Make sure you have:**
        1. ✅ Created a service account in Google Cloud Console
        2. ✅ Downloaded the JSON credentials file
        3. ✅ Added credentials to Streamlit Secrets (proper TOML format)
        4. ✅ Created a Google Sheet named **'AusGrocery_PriceDB'**
        5. ✅ Shared the sheet with your service account email
        6. ✅ Added proper column headers (Product_Name, Woolworths_Price, etc.)
        """)
        
        return
    
    st.success(f"✅ Loaded {len(df)} products from Google Sheets")
    
    # Show data structure info
    if st.checkbox("📊 Show data info"):
        st.write("**Columns in your sheet:**", list(df.columns))
        st.write("**First few rows:**")
        st.dataframe(df.head())
    
    # Main functionality (same as before but simplified for now)
    st.subheader("🏪 Price Comparison")
    
    price_cols = [col for col in ['Woolworths_Price', 'Coles_Price', 'Aldi_Price'] if col in df.columns]
    
    if price_cols:
        for idx, row in df.iterrows():
            st.write(f"**{row.get('Product_Name', 'Unknown Product')}**")
            
            cols = st.columns(len(price_cols))
            
            for i, price_col in enumerate(price_cols):
                store_name = price_col.replace('_Price', '')
                price = row.get(price_col, 0)
                
                with cols[i]:
                    if pd.notna(price) and price > 0:
                        st.metric(store_name, f"${price:.2f}")
                    else:
                        st.metric(store_name, "N/A")
            
            st.divider()
    else:
        st.info("No price columns found. Expected: Woolworths_Price, Coles_Price, Aldi_Price")

if __name__ == "__main__":
    main()
