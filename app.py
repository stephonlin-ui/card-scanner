import streamlit as st
import google.generativeai as genai
import gspread
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from PIL import Image
from io import BytesIO
import json, time, re

# --------------------------------------------------
# UI
# --------------------------------------------------
st.set_page_config(page_title="📇 雲端名片系統", page_icon="📇")
st.markdown("""
<style>
#MainMenu {visibility:hidden;}
footer {visibility:hidden;}
header {visibility:hidden;}
</style>
""", unsafe_allow_html=True)

if "camera_key" not in st.session_state:
    st.session_state.camera_key = 0

# --------------------------------------------------
# Gemini
# --------------------------------------------------
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# --------------------------------------------------
# OAuth
# --------------------------------------------------
SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets"
]

CLIENT_CONFIG = {
    "web": {
        "client_id": st.secrets["google_oauth"]["client_id"],
        "client_secret": st.secrets["google_oauth"]["client_secret"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [st.secrets["google_oauth"]["redirect_uri"]],
    }
}

def get_creds():
    if "credentials" in st.session_state:
        creds = Credentials.from_authorized_user_info(
            json.loads(st.session_state["credentials"]), SCOPES
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            st.session_state["credentials"] = creds.to_json()
        return creds

    params = st.experimental_get_query_params()
    if "code" in params:
        flow = Flow.from_client_config(
            CLIENT_CONFIG,
            scopes=SCOPES,
            redirect_uri=st.secrets["google_oauth"]["redirect_uri"]
        )
        flow.fetch_token(code=params["code"][0])
        creds = flow.credentials
        st.session_state["credentials"] = creds.to_json()
        st.experimental_set_query_params()
        return creds

    flow = Flow.from_client_config(
        CLIENT_CONFIG,
        scopes=SCOPES,
        redirect_uri=st.secrets["google_oauth"]["redirect_uri"]
    )
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
    st.info("請先登入 Google 帳號")
    st.markdown(f"[👉 點我登入]({auth_url})")
    st.stop()

# --------------------------------------------------
# Drive
# --------------------------------------------------
def upload_drive(img_bytes, filename, creds):
    service = build("drive", "v3", credentials=creds)
    media = MediaIoBaseUpload(BytesIO(img_bytes), mimetype="image/jpeg")
    file = service.files().create(
        body={"name": filename},
        media_body=media,
        fields="webViewLink"
    ).execute()
    return file["webViewLink"]

# --------------------------------------------------
# Sheets
# --------------------------------------------------
def save_sheet(data, link, creds):
    gc = gspread.authorize(creds)
    try:
        sheet = gc.open("Business_Cards_Data").sheet1
    except:
        sh = gc.create("Business_Cards_Data")
        sheet = sh.sheet1
        sheet.append_row([
            "時間","姓名","職稱","公司","電話","傳真",
            "Email","地址","網址","拍攝檔案連結"
        ])

    sheet.append_row([
        time.strftime("%Y-%m-%d %H:%M:%S"),   # A
        data.get("name",""),                  # B
        data.get("title",""),                 # C
        data.get("company",""),               # D
        data.get("phone",""),                 # E
        data.get("fax",""),                   # F
        data.get("email",""),                 # G
        data.get("address",""),               # H
        data.get("website",""),               # I
        link                                  # J
    ])

# --------------------------------------------------
# AI 名片辨識（已擴充欄位）
# --------------------------------------------------
def extract_info(image):
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    prompt = """
你是名片 OCR 助手。
請「只輸出 JSON」，不要任何說明或 markdown。
若沒有資料請填空字串。

{
  "name": "",
  "title": "",
  "company": "",
  "phone": "",
  "fax": "",
  "email": "",
  "address": "",
  "website": ""
}
"""
    res = model.generate_content([prompt, image])
    raw = res.text.strip()

    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        st.error("❌ Gemini 沒有回傳有效 JSON")
        st.code(raw)
        return None

    try:
        return json.loads(match.group())
    except:
        st.error("❌ JSON 解析失敗")
        st.code(match.group())
        return None

# --------------------------------------------------
# Main
# --------------------------------------------------
st.title("📇 雲端名片系統")

creds = get_creds()

img = st.camera_input(
    "拍照",
    key=f"cam_{st.session_state.camera_key}",
    label_visibility="hidden"
)

if img:
    img_bytes = img.getvalue()
    image = Image.open(BytesIO(img_bytes))
    st.image(image, use_column_width=True)

    with st.spinner("🤖 名片辨識中..."):
        info = extract_info(image)

    if info:
        st.success(f"辨識成功：{info.get('name','')}")
        with st.spinner("☁️ 儲存中..."):
            link = upload_drive(img_bytes, f"card_{int(time.time())}.jpg", creds)
            save_sheet(info, link, creds)

        st.balloons()
        st.session_state.camera_key += 1
        time.sleep(1.5)
        st.rerun()
