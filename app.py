import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

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
        from streamlit_gsheets import connect
        
        # Connect using Streamlit's native method
        gc = connect()
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
                    df[col] = pd.to_numeric(df[col].str.replace('$', ''), errors='coerce')
            
            return df
        else:
            return pd.DataFrame()
            
    except Exception as e:
        st.error(f"Failed to load data: {str(e)}")
        return pd.DataFrame()

def update_prices(product_name, retailer, new_price):
    """Update price for a specific product and retailer"""
    try:
        import gspread
        from streamlit_gsheets import connect
        
        gc = connect()
        sheet = gc.open('AusGrocery_PriceDB')
        worksheet = sheet.sheet1
        
        # Find the product row and update price
        all_values = worksheet.get_all_values()
        headers = all_values[0]
        
        # Find column indices
        product_col = headers.index('Product_Name') + 1
        price_col = headers.index(f'{retailer}_Price') + 1
        date_col = headers.index('Last_Updated') + 1
        
        # Find product row
        for i, row in enumerate(all_values[1:], start=2):
            if row[product_col-1] == product_name:
                worksheet.update_cell(i, price_col, f"${new_price:.2f}")
                worksheet.update_cell(i, date_col, datetime.now().strftime('%Y-%m-%d'))
                break
                
        return True
        
    except Exception as e:
        st.error(f"Failed to update price: {str(e)}")
        return False

def main():
    st.title("🛒 **Aussie Grocery Price Tracker**")
    st.markdown("*Compare prices across Woolworths, Coles & ALDI*")
    
    # Load data
    df = load_grocery_data()
    
    if df.empty:
        st.warning("📋 No data loaded. Check your Google Sheets connection.")
        return
    
    # Sidebar for filtering
    with st.sidebar:
        st.header("🔍 Filters")
        
        # Category filter
        if 'Category' in df.columns:
            categories = ['All'] + list(df['Category'].unique())
            selected_category = st.selectbox("Category", categories)
        else:
            selected_category = 'All'
        
        # Price range filter
        if any(col in df.columns for col in ['Woolworths_Price', 'Coles_Price', 'Aldi_Price']):
            price_cols = [col for col in ['Woolworths_Price', 'Coles_Price', 'Aldi_Price'] if col in df.columns]
            max_price = df[price_cols].max().max()
            min_price = df[price_cols].min().min()
            
            price_range = st.slider(
                "Price Range ($)", 
                float(min_price), 
                float(max_price), 
                (float(min_price), float(max_price))
            )
    
    # Filter data
    filtered_df = df.copy()
    
    if selected_category != 'All' and 'Category' in df.columns:
        filtered_df = filtered_df[filtered_df['Category'] == selected_category]
    
    # Main content tabs
    tab1, tab2, tab3 = st.tabs(["📊 Price Comparison", "📝 Manual Update", "📈 Analytics"])
    
    with tab1:
        st.subheader("🏪 Current Prices")
        
        if not filtered_df.empty:
            # Calculate best prices
            price_cols = [col for col in ['Woolworths_Price', 'Coles_Price', 'Aldi_Price'] if col in filtered_df.columns]
            
            if price_cols:
                filtered_df['Best_Price'] = filtered_df[price_cols].min(axis=1)
                filtered_df['Best_Store'] = filtered_df[price_cols].idxmin(axis=1).str.replace('_Price', '')
                
                # Display with color coding
                for idx, row in filtered_df.iterrows():
                    col1, col2, col3, col4, col5 = st.columns([3, 1.5, 1.5, 1.5, 2])
                    
                    with col1:
                        st.write(f"**{row.get('Product_Name', 'Unknown')}**")
                        if 'Brand' in row:
                            st.caption(row['Brand'])
                    
                    # Price columns with highlighting
                    prices = {}
                    for store_col in price_cols:
                        store_name = store_col.replace('_Price', '')
                        price = row.get(store_col, 0)
                        prices[store_name] = price
                    
                    best_price = min(prices.values()) if prices.values() else 0
                    
                    with col2:
                        if 'Woolworths' in prices:
                            price = prices['Woolworths']
                            if price == best_price and price > 0:
                                st.success(f"🏆 ${price:.2f}")
                            else:
                                st.write(f"${price:.2f}" if price > 0 else "N/A")
                    
                    with col3:
                        if 'Coles' in prices:
                            price = prices['Coles']
                            if price == best_price and price > 0:
                                st.success(f"🏆 ${price:.2f}")
                            else:
                                st.write(f"${price:.2f}" if price > 0 else "N/A")
                    
                    with col4:
                        if 'Aldi' in prices:
                            price = prices['Aldi']
                            if price == best_price and price > 0:
                                st.success(f"🏆 ${price:.2f}")
                            else:
                                st.write(f"${price:.2f}" if price > 0 else "N/A")
                    
                    with col5:
                        if best_price > 0:
                            savings = max(prices.values()) - best_price
                            if savings > 0:
                                st.metric("Save", f"${savings:.2f}")
                    
                    st.divider()
        else:
            st.info("No products match your filter criteria.")
    
    with tab2:
        st.subheader("✏️ Update Prices (Woolworths & Coles)")
        st.info("💡 ALDI prices are updated automatically weekly")
        
        if not df.empty and 'Product_Name' in df.columns:
            col1, col2, col3 = st.columns(3)
            
            with col1:
                product = st.selectbox("Select Product", df['Product_Name'].tolist())
            
            with col2:
                retailer = st.selectbox("Retailer", ["Woolworths", "Coles"])
            
            with col3:
                new_price = st.number_input("New Price ($)", min_value=0.01, step=0.01)
            
            if st.button("🔄 Update Price", type="primary"):
                if update_prices(product, retailer, new_price):
                    st.success(f"✅ Updated {product} - {retailer}: ${new_price:.2f}")
                    st.cache_data.clear()  # Clear cache to reload data
                    st.rerun()
    
    with tab3:
        st.subheader("📈 Price Analytics")
        
        if not filtered_df.empty:
            price_cols = [col for col in ['Woolworths_Price', 'Coles_Price', 'Aldi_Price'] if col in filtered_df.columns]
            
            if len(price_cols) >= 2:
                # Average prices by store
                avg_prices = {}
                for col in price_cols:
                    store_name = col.replace('_Price', '')
                    avg_price = filtered_df[col].mean()
                    avg_prices[store_name] = avg_price
                
                st.bar_chart(avg_prices)
                
                # Savings summary
                if len(price_cols) >= 2:
                    for idx, row in filtered_df.iterrows():
                        prices = [row[col] for col in price_cols if row[col] > 0]
                        if len(prices) >= 2:
                            max_price = max(prices)
                            min_price = min(prices)
                            potential_savings = max_price - min_price
                            
                            if potential_savings > 0:
                                st.metric(
                                    f"{row.get('Product_Name', 'Product')}", 
                                    f"${min_price:.2f}", 
                                    f"-${potential_savings:.2f}"
                                )

if __name__ == "__main__":
    main()
