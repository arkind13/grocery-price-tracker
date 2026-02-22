import streamlit as st
import pandas as pd

# Page configuration
st.set_page_config(
    page_title="Grocery Price Tracker",
    page_icon="🛒",
    layout="wide"
)

def test_google_sheets_connection():
    """Test if we can connect to Google Sheets"""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        
        # Define the scope
        scope = [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive'
        ]
        
        # Load credentials
        creds = Credentials.from_service_account_file('credentials.json', scopes=scope)
        client = gspread.authorize(creds)
        
        # Try to open the spreadsheet
        sheet = client.open('AusGrocery_PriceDB')
        worksheet = sheet.sheet1
        
        # Try to read data
        all_values = worksheet.get_all_values()
        
        st.success("✅ SUCCESS! Connected to Google Sheets")
        st.info(f"📊 Found {len(all_values)} rows in your spreadsheet")
        
        # Show first few rows
        if len(all_values) > 0:
            st.write("**First few rows of your data:**")
            df = pd.DataFrame(all_values[1:], columns=all_values[0])  # First row as headers
            st.dataframe(df.head())
        
        return True
        
    except FileNotFoundError:
        st.error("❌ credentials.json file not found")
        st.info("Make sure you uploaded the credentials file to your GitHub repository")
        return False
        
    except Exception as e:
        st.error(f"❌ Connection failed: {str(e)}")
        st.info("Check that you've shared your Google Sheet with the service account email")
        return False

def main():
    st.title("🛒 Grocery Price Tracker")
    st.markdown("*Testing Google Sheets Connection*")
    
    st.header("🔧 Connection Test")
    
    if st.button("Test Google Sheets Connection", type="primary"):
        with st.spinner("Connecting to Google Sheets..."):
            test_google_sheets_connection()
    
    st.markdown("---")
    st.info("👆 Click the button above to test if your Google Sheets API is working correctly!")

if __name__ == "__main__":
    main()
