import streamlit as st
import pandas as pd

# Page configuration
st.set_page_config(
    page_title="Grocery Price Tracker",
    page_icon="🛒",
    layout="wide"
)

def test_google_sheets_connection():
    """Test if we can connect to Google Sheets using Streamlit Secrets"""
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
            "type": st.secrets["connections"]["gsheets"]["type"],
            "project_id": st.secrets["connections"]["gsheets"]["project_id"],
            "private_key_id": st.secrets["connections"]["gsheets"]["private_key_id"],
            "private_key": st.secrets["connections"]["gsheets"]["private_key"],
            "client_email": st.secrets["connections"]["gsheets"]["client_email"],
            "client_id": st.secrets["connections"]["gsheets"]["client_id"],
            "auth_uri": st.secrets["connections"]["gsheets"]["auth_uri"],
            "token_uri": st.secrets["connections"]["gsheets"]["token_uri"],
            "auth_provider_x509_cert_url": st.secrets["connections"]["gsheets"]["auth_provider_x509_cert_url"]
        }
        
        # Create credentials object
        creds = Credentials.from_service_account_info(credentials_dict, scopes=scope)
        
        # Authorize and connect
        client = gspread.authorize(creds)
        
        # Try to open the spreadsheet
        sheet = client.open('AusGrocery_PriceDB')
        worksheet = sheet.sheet1
        
        # Try to read data
        all_values = worksheet.get_all_values()
        
        st.success("✅ SUCCESS! Connected to Google Sheets securely using Streamlit Secrets")
        st.info(f"📊 Found {len(all_values)} rows in your spreadsheet")
        
        # Show service account being used
        st.info(f"🔐 Service Account: {credentials_dict['client_email']}")
        
        # Show first few rows
        if len(all_values) > 0:
            st.write("**First few rows of your data:**")
            df = pd.DataFrame(all_values[1:], columns=all_values[0])  # First row as headers
            st.dataframe(df.head())
        
        return True
        
    except Exception as e:
        st.error(f"❌ Connection failed: {str(e)}")
        st.info("Please check your Streamlit Secrets configuration")
        return False

def main():
    st.title("🛒 Grocery Price Tracker")
    st.markdown("*Testing Secure Google Sheets Connection*")
    
    st.header("🔧 Connection Test")
    
    if st.button("Test Google Sheets Connection", type="primary"):
        with st.spinner("Connecting to Google Sheets..."):
            test_google_sheets_connection()
    
    st.markdown("---")
    st.success("🔐 **Security Note:** Your API credentials are now stored securely in Streamlit Secrets, not in your public GitHub repository!")

if __name__ == "__main__":
    main()
