```python
# streamlit_app.py
import streamlit as st
import os
import json
import logging
import time
from datetime import datetime
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import pandas as pd
import openai
import requests
from bs4 import BeautifulSoup
import base64
from email.mime.text import MIMEText

# ----------------------
# Setup
# ----------------------
st.set_page_config(page_title="GMC Feed Editor & AI Optimizer", layout="wide")
logging.basicConfig(
    filename='app.log',
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s:%(message)s'
)
logger = logging.getLogger(__name__)
logger.debug("App starting...")

# OAuth Configuration
SCOPES = [
    'https://www.googleapis.com/auth/content',
    'https://www.googleapis.com/auth/gmail.send'
]
REDIRECT_URI = os.getenv('REDIRECT_URI')
if not REDIRECT_URI:
    st.error("Environment variable REDIRECT_URI is required.")
    st.stop()

# Load OAuth client secrets
# In Streamlit Cloud, place the JSON under "client_secrets" in Secrets; locally, use CLIENT_SECRETS_FILE env var
if 'client_secrets' in st.secrets:
    CLIENT_SECRETS_FILE = 'client_secrets_temp.json'
    with open(CLIENT_SECRETS_FILE, 'w') as f:
        json.dump(st.secrets['client_secrets'], f)
    logger.debug("Loaded client_secrets from st.secrets")
else:
    CLIENT_SECRETS_FILE = os.getenv('CLIENT_SECRETS_FILE', 'client_secrets.json')
    if not os.path.exists(CLIENT_SECRETS_FILE):
        st.error(f"Client secrets file not found: {CLIENT_SECRETS_FILE}")
        st.stop()
    logger.debug(f"Using client_secrets file: {CLIENT_SECRETS_FILE}")

# Rate limit delay\RATE_LIMIT_DELAY = float(os.getenv('RATE_LIMIT_DELAY', '0.2'))

# OpenAI key
openai.api_key = os.getenv('OPENAI_API_KEY')
if not openai.api_key:
    st.warning("OpenAI API key not set; skipping AI optimization.")

# Email recipients
EMAIL_TO = os.getenv('EMAIL_TO')

# Backup directory
BACKUP_DIR = 'backups'
os.makedirs(BACKUP_DIR, exist_ok=True)

# ----------------------
# OAuth Helpers
# ----------------------
def get_flow():
    return Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )

def authorize():
    flow = get_flow()
    auth_url, state = flow.authorization_url(
        access_type='offline', include_granted_scopes='true'
    )
    st.session_state['flow'] = flow
    st.session_state['state'] = state
    st.markdown(f"[Authorize with Google]({auth_url})")
    st.stop()

def fetch_credentials():
    params = st.query_params
    if 'code' in params and 'flow' in st.session_state:
        try:
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
            st.experimental_set_query_params({})
        except Exception as e:
            logger.error(f"OAuth token fetch failed: {e}")
            st.error(f"OAuth error: {e}")
    if 'creds' not in st.session_state:
        authorize()
    return Credentials(**st.session_state['creds'])

# ----------------------
# AI Optimization
# ----------------------
def ai_optimize(field, original, url):
    if not openai.api_key:
        return original
    try:
        resp = requests.get(url, timeout=5)
        soup = BeautifulSoup(resp.text, 'html.parser')
        snippet = soup.get_text(' ', strip=True)[:1000]
    except Exception:
        snippet = ''
    prompt = (
        f"Optimize the {field} for GMC. Original: '{original}'. Page snippet: '{snippet}'. "
        f"Return only the optimized {field}."
    )
    try:
        res = openai.ChatCompletion.create(
            model='gpt-4',
            messages=[{'role':'user','content':prompt}],
            max_tokens=150
        )
        result = res.choices[0].message.content.strip()
    except Exception:
        result = original
    time.sleep(RATE_LIMIT_DELAY)
    return result

# ----------------------
# QA & Email
# ----------------------
def diff_feed(df_old, df_new):
    df = df_old.merge(df_new, on='product_id', suffixes=('_old','_new'))
    changed = df[(df['title_old'] != df['title_new']) |
                 (df['description_old'] != df['description_new']) |
                 (df['productType_old'] != df['productType_new']) |
                 (df['googleProductCategory_old'] != df['googleProductCategory_new'])]
    return changed

def send_email(html, creds):
    if not EMAIL_TO:
        st.error("EMAIL_TO not set")
        return
    svc = build('gmail', 'v1', credentials=creds)
    msg = MIMEText(html, 'html')
    msg['to'] = EMAIL_TO
    msg['subject'] = 'GMC QA Report'
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    svc.users().messages().send(userId='me', body={'raw': raw}).execute()
    st.success("QA report sent.")

# ----------------------
# Main App
# ----------------------
def main():
    st.title("GMC Feed Editor & AI Optimizer")
    creds = fetch_credentials()
    content = build('content', 'v2.1', credentials=creds)

    info = content.accounts().authinfo().execute()
    accounts = info.get('accountIdentifiers', [])
    selected = st.sidebar.selectbox("Select GMC Account", accounts)

    if st.button("Fetch & Backup Feed"):
        products = content.products().list(merchantId=selected).execute().get('resources', [])
        df = pd.json_normalize(products)
        for col in ['id','link','title','description','productType','googleProductCategory']:
            df[col] = df.get(col, '')
        df.rename(columns={'id':'product_id'}, inplace=True)
        st.session_state['df_old'] = df.copy()
        st.session_state['df'] = df.copy()
        st.success(f"Fetched {len(df)} items.")

    if 'df' in st.session_state:
        st.dataframe(st.session_state['df'])
        if st.button("AI Optimize Attributes"):
            df = st.session_state['df']
            total = len(df)
            progress = st.progress(0)
            for i, row in df.iterrows():
                for f in ['title','description','productType','googleProductCategory']:
                    df.at[i,f] = ai_optimize(f, row[f], row.get('link',''))
                progress.progress((i+1)/total)
            st.session_state['df'] = df
            st.success("Optimization done.")
        if st.button("Show QA Report"):
            diff = diff_feed(st.session_state['df_old'], st.session_state['df'])
            if diff.empty:
                st.info("No changes.")
            else:
                st.dataframe(diff)
                if st.button("Email QA Report"):
                    send_email(diff.to_html(index=False), creds)
        if st.button("Sync to GMC"):
            df = st.session_state['df']
            total = len(df)
            progress2 = st.progress(0)
            count=0
            for i, row in df.iterrows():
                content.products().patch(
                    merchantId=selected,
                    productId=row['product_id'],
                    body={f:row[f] for f in ['title','description','productType','googleProductCategory']}
                ).execute()
                count+=1
                progress2.progress(count/total)
            st.success(f"Synced {count} items.")

if __name__ == '__main__':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    main()
```

