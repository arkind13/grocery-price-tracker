import streamlit as st
import pandas as pd
import json

# Page configuration
st.set_page_config(
    page_title="Grocery Price Tracker",
    page_icon="🛒",
    layout="wide"
)

def test_google_sheets_connection():
    """Test if we can connect to Google Sheets using JSON credentials"""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        
        # Define the scope
        scope = [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive'
        ]
        
        # Try to load credentials from Streamlit secrets as JSON string
        try:
            # Get the JSON string from secrets
            json_string = st.secrets["google_sheets_json"]
            credentials_dict = json.loads(json_string)
            
            # Create credentials object
            creds = Credentials.from_service_account_info(credentials_dict, scopes=scope)
            
            st.info("🔐 Using Streamlit Secrets (JSON format)")
            
        except Exception as secret_error:
            st.error(f"Failed to load from secrets: {secret_error}")
            return False
        
        # Authorize and connect
        client = gspread.authorize(creds)
        
        # Try to open the spreadsheet
        sheet = client.open('AusGrocery_PriceDB')
        worksheet = sheet.sheet1
        
        # Try to read data
        all_values = worksheet.get_all_values()
        
        st.success("✅ SUCCESS! Connected to Google Sheets")
        st.info(f"📊 Found {len(all_values)} rows in your spreadsheet")
        st.info(f"🔐 Service Account: {credentials_dict['client_email']}")
        
        # Show first few rows
        if len(all_values) > 0:
            st.write("**First few rows of your data:**")
            df = pd.DataFrame(all_values[1:], columns=all_values[0])
            st.dataframe(df.head())
        
        return True
        
    except Exception as e:
        st.error(f"❌ Connection failed: {str(e)}")
        return False

def main():
    st.title("🛒 Grocery Price Tracker")
    st.markdown("*Testing Google Sheets Connection with JSON Format*")
    
    st.header("🔧 Connection Test")
    
    if st.button("Test Google Sheets Connection", type="primary"):
        with st.spinner("Connecting to Google Sheets..."):
            test_google_sheets_connection()
    
    st.markdown("---")
    st.info("🔐 **Security Note:** Credentials stored securely in Streamlit Secrets")

if __name__ == "__main__":
    main()
