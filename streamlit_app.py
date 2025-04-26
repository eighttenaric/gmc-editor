# streamlit_app.py
import streamlit as st
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import pandas as pd
import os
import logging
from datetime import datetime
import openai
import requests
from bs4 import BeautifulSoup
import base64
from email.mime.text import MIMEText
import time

# ----------------------
# Setup
# ----------------------
st.set_page_config(page_title="GMC Feed Editor & AI Optimizer", layout="wide")

# Logging configuration
logging.basicConfig(
    filename='app.log',
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s:%(message)s'
)
logger = logging.getLogger(__name__)
logger.debug("App starting...")

# OAuth and API configuration
CLIENT_SECRETS_FILE = os.getenv('CLIENT_SECRETS_FILE', 'client_secrets.json')
SCOPES = [
    'https://www.googleapis.com/auth/content',
    'https://www.googleapis.com/auth/gmail.send'
]
REDIRECT_URI = os.getenv('REDIRECT_URI')
if not REDIRECT_URI:
    logger.error("REDIRECT_URI missing")
    st.error("Environment variable REDIRECT_URI is required.")
    st.stop()

# Rate limiting delay (seconds)
RATE_LIMIT_DELAY = float(os.getenv('RATE_LIMIT_DELAY', '0.2'))
logger.debug(f"Rate limit delay set to {RATE_LIMIT_DELAY}s")

# OpenAI configuration
openai.api_key = os.getenv('OPENAI_API_KEY')
if not openai.api_key:
    logger.warning("No OpenAI key: AI optimization disabled.")
    st.warning("OpenAI key missing; optimizations will be skipped.")

# Email recipients
EMAIL_TO = os.getenv('EMAIL_TO')

# Backup folder
BACKUP_DIR = 'backups'
os.makedirs(BACKUP_DIR, exist_ok=True)
logger.debug(f"Backup folder: {BACKUP_DIR}")

# ----------------------
# OAuth Helpers
# ----------------------
def get_flow():
    return Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI
    )

def authorize():
    flow = get_flow()
    auth_url, state = flow.authorization_url(
        access_type='offline', include_granted_scopes='true'
    )
    st.session_state['flow'] = flow
    st.session_state['flow_state'] = state
    st.markdown(f"[Authorize with Google]({auth_url})")
    logger.debug(f"Redirecting to: {auth_url}")
    st.stop()

def fetch_credentials():
    params = st.experimental_get_query_params()
    logger.debug(f"OAuth callback params: {params}")
    if 'code' in params and 'flow' in st.session_state:
        try:
            flow = st.session_state['flow']
            flow.fetch_token(code=params['code'][0])
            creds = flow.credentials
            st.session_state['creds'] = creds_to_dict(creds)
            st.experimental_set_query_params()
            logger.debug("Credentials fetched and stored")
        except Exception as e:
            logger.error(f"Error fetching token: {e}")
            st.error(f"OAuth error: {e}")
    if 'creds' not in st.session_state:
        authorize()
    return Credentials(**st.session_state['creds'])

def creds_to_dict(creds):
    return {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': creds.scopes
    }

# ----------------------
# AI Optimization
# ----------------------
def ai_optimize(field_name, original, url):
    if not openai.api_key:
        return original
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        text = BeautifulSoup(resp.text, 'html.parser').get_text(' ', strip=True)[:1000]
        logger.debug(f"Fetched page content for {url}")
    except Exception as e:
        logger.warning(f"Fetching page failed: {e}")
        text = ''
    prompt = (
        f"Optimize the {field_name} for Google Merchant Center. "
        f"Original {field_name}: '{original}'. "
        f"Product page content (snippet): '{text}'. "
        f"Return only the new {field_name}."
    )
    try:
        res = openai.ChatCompletion.create(
            model='gpt-4',
            messages=[{'role':'user','content':prompt}],
            max_tokens=150
        )
        optimized = res.choices[0].message.content.strip()
        logger.debug(f"Optimized {field_name}: {optimized}")
    except Exception as e:
        logger.error(f"OpenAI error optimizing {field_name}: {e}")
        optimized = original
    time.sleep(RATE_LIMIT_DELAY)
    return optimized

# ----------------------
# QA & Email via Gmail
# ----------------------
def diff_feed(df1, df2):
    df = df1.merge(df2, on='product_id', suffixes=('_orig','_new'))
    mask = (
        (df['title_orig'] != df['title_new']) |
        (df['description_orig'] != df['description_new']) |
        (df['productType_orig'] != df['productType_new']) |
        (df['googleProductCategory_orig'] != df['googleProductCategory_new'])
    )
    diff = df[mask]
    logger.debug(f"Diff count: {len(diff)}")
    return diff

def send_email(html, creds):
    if not EMAIL_TO:
        logger.error("EMAIL_TO not set")
        st.error("EMAIL_TO environment variable required for email.")
        return
    try:
        svc = build('gmail', 'v1', credentials=creds)
        msg = MIMEText(html, 'html')
        msg['to'] = EMAIL_TO
        msg['subject'] = 'GMC Feed QA Report'
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc.users().messages().send(userId='me', body={'raw': raw}).execute()
        logger.debug("Email sent successfully")
        st.success("Sent QA Report")
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        st.error(f"Failed to send email: {e}")

# ----------------------
# Main Application Flow
# ----------------------
def main():
    logger.debug("Starting main flow")
    st.title("GMC Feed Editor & AI Optimizer")
    creds = fetch_credentials()
    try:
        content = build('content', 'v2.1', credentials=creds)
    except Exception as e:
        logger.error(f"Content API init failed: {e}")
        st.error(f"Could not connect to Content API: {e}")
        return

    # Dynamically fetch accessible Merchant Center accounts via authinfo
    try:
        authinfo = content.accounts().authinfo().execute()
        account_ids = authinfo.get('accountIdentifiers', [])
        logger.debug(f"Accessible accounts via authinfo: {account_ids}")
    except Exception as e:
        logger.error(f"AuthInfo failed: {e}")
        st.error(f"Could not retrieve accessible Merchant Center accounts: {e}")
        return
    merchant_map = {acc_id: '' for acc_id in account_ids}
    selected = st.sidebar.selectbox(
        "Merchant Center Account",
        options=account_ids,
        format_func=lambda x: f"{x}"
    )
    logger.debug(f"Selected account: {selected}")

    # Fetch & Backup
    if st.button("Fetch & Backup Feed"):
        logger.debug(f"Fetch initiated for account {selected}")
        try:
            products = content.products().list(merchantId=selected).execute().get('resources', [])
            logger.debug(f"Fetched {len(products)} products")
        except Exception as e:
            logger.error(f"Fetch products failed: {e}")
            st.error(f"Fetch failed: {e}")
            return
        df = pd.json_normalize(products)
        for col in ['id', 'link', 'title', 'description', 'productType', 'googleProductCategory']:
            df[col] = df.get(col, '')
        df.rename(columns={'id': 'product_id'}, inplace=True)
        st.session
