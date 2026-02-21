import streamlit as st

# Basic configuration
st.set_page_config(
    page_title="Grocery Price Tracker",
    page_icon="🛒"
)

# Simple app content
st.title("🛒 Grocery Price Tracker")
st.write("Welcome to your grocery price comparison app!")

st.success("✅ App is working! You've successfully deployed to Streamlit Cloud.")

# Basic interaction
name = st.text_input("Enter your name:")
if name:
    st.write(f"Hello, {name}! Ready to save money on groceries?")

st.info("This is a test version. We'll add more features in the next steps.")
