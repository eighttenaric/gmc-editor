import streamlit as st
from google_auth_oauthlib.flow import Flow
import os

st.title("GMC Feed Editor & AI Optimizer")

REDIRECT_URI = os.getenv("REDIRECT_URI")
if not REDIRECT_URI:
    st.error("REDIRECT_URI missing")
    st.stop()

# … continue with get_flow(), authorize(), fetch_credentials() definitions …

if "creds" not in st.session_state:
    st.write("↪ Need to authorize…")
    authorize()
else:
    st.success("✔️ Credentials loaded")
