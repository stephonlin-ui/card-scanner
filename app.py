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
import json
import time

# --------------------------------------------------
# 基本設定
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
# Gemini 設定
# --------------------------------------------------
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# --------------------------------------------------
# OAuth 設定
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

def get_oauth_credentials():
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
    auth_url, _ = flow.authorization_url(
        prompt="consent",
        access_type="offline"
    )
    st.info("請先授權 Google Drive / Sheets")
    st.markdown(f"👉 [使用 Google 帳號登入]({auth_url})")
    st.stop()

# --------------------------------------------------
# Google Drive 上傳
# --------------------------------------------------
def upload_image_to_drive(image_bytes, filename, creds):
    service = build("drive", "v3", credentials=creds)
    media = MediaIoBaseUpload(BytesIO(image_bytes), mimetype="image/jpeg")
    file = service.files().create(
        body={"name": filename},
        media_body=media,
        fields="id, webViewLink"
    ).execute()
    return file["webViewLink"]

# --------------------------------------------------
# Google Sheets 寫入
# --------------------------------------------------
def save_to_sheets(data, image_link, creds):
    gc = gspread.authorize(creds)

    try:
        sheet = gc.open("Business_Cards_Data").sheet1
    except:
        sh = gc.create("Business_Cards_Data")
        sheet = sh.sheet1
        sheet.append_row([
            "拍攝時間", "姓名", "職稱", "公司",
            "電話", "Email", "地址", "照片連結"
        ])

    row = [
        time.strftime("%Y-%m-%d %H:%M:%S"),
        data.get("name",""),
        data.get("title",""),
        data.get("company",""),
        data.get("phone",""),
        data.get("email",""),
        data.get("address",""),
        image_link
    ]
    sheet.append_row(row)

# --------------------------------------------------
# Gemini 名片辨識
# --------------------------------------------------
def extract_info(image):
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    prompt = """
請從名片圖片中擷取資訊，並只輸出 JSON：
{
  "name": "",
  "title": "",
  "company": "",
  "phone": "",
  "email": "",
  "address": ""
}
"""
    response = model.generate_content([prompt, image])
    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
    return json.loads(text)

# --------------------------------------------------
# 主畫面
# --------------------------------------------------
st.title("📇 雲端名片系統（OAuth 版）")

creds = get_oauth_credentials()

img_file = st.camera_input(
    "拍照",
    key=f"camera_{st.session_state.camera_key}",
    label_visibility="hidden"
)

if img_file:
    img_bytes = img_file.getvalue()
    image = Image.open(BytesIO(img_bytes))
    st.image(image, use_column_width=True)

    with st.spinner("🤖 AI 辨識中..."):
        info = extract_info(image)

    if info:
        st.success(f"辨識成功：{info.get('name','')}")
        with st.spinner("☁️ 上傳雲端並寫入 Sheet..."):
            filename = f"Card_{int(time.time())}.jpg"
            link = upload_image_to_drive(img_bytes, filename, creds)
            save_to_sheets(info, link, creds)

        st.balloons()
        st.success("✅ 建檔完成")
        st.session_state.camera_key += 1
        time.sleep(2)
        st.rerun()
