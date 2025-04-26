import streamlit as st
import os
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

# 1) Your title and env‐var check
st.title("GMC Feed Editor & AI Optimizer")
REDIRECT_URI = os.getenv("REDIRECT_URI")
CLIENT_SECRETS_FILE = os.getenv("CLIENT_SECRETS_FILE","client_secrets.json")
SCOPES = ['https://www.googleapis.com/auth/content',
          'https://www.googleapis.com/auth/gmail.send']

if not REDIRECT_URI:
    st.error("REDIRECT_URI not set")
    st.stop()

# 2) Real authorize() using Flow
def authorize():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    # Save the flow in session_state so we can fetch the token later
    st.session_state['flow'] = flow
    st.session_state['state'] = state
    # Show the real consent link
    st.markdown(f"[Authorize with Google]({auth_url})")
    st.stop()

# 3) Exchange code for credentials
def fetch_credentials():
    params = st.experimental_get_query_params()
    if 'code' in params and 'flow' in st.session_state:
        flow = st.session_state['flow']
        flow.fetch_token(code=params['code'][0])
        creds = flow.credentials
        st.session_state['creds'] = {
            'token': creds.token,
            'refresh_token': creds.refresh_token,
            'token_uri': creds.token_uri,
            'client_id': creds.client_id,
            'client_secret': creds.client_secret,
            'scopes': creds.scopes
        }
        # Clear the URL so it doesn’t keep the code param
        st.experimental_set_query_params()
    if 'creds' not in st.session_state:
        authorize()
    return Credentials(**st.session_state['creds'])

# 4) Kick off the flow
creds = fetch_credentials()
st.success("✅ Authenticated! You can now use the app.")
