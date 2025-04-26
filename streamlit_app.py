import streamlit as st
import os

st.write("✅ Streamlit is running and environment variables load correctly")

REDIRECT_URI = os.getenv("REDIRECT_URI")
if not REDIRECT_URI:
    st.error("❌ REDIRECT_URI not set")
else:
    st.success(f"🔑 REDIRECT_URI = {REDIRECT_URI}")
