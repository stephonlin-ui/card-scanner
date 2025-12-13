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
# UI 基本設定
# --------------------------------------------------
st.set_page_config(
    page_title="Business Card Scanner｜名片掃描系統",
    page_icon="📇",
    layout="centered"
)

st.markdown("""
<style>
#MainMenu, footer, header {visibility:hidden;}

/* 拍攝區容器 */
.camera-wrapper {
    position: relative;
    max-width: 420px;
    margin: auto;
}

/* 名片引導框 */
.guide-frame {
    position: absolute;
    top: 18%;
    left: 5%;
    width: 90%;
    height: 45%;
    border: 3px dashed #00C2FF;
    border-radius: 12px;
    box-shadow: 0 0 0 2000px rgba(0,0,0,0.35);
    pointer-events: none;
}

/* 引導文字 */
.guide-text {
    position: absolute;
    top: 8%;
    width: 100%;
    text-align: center;
    color: white;
    font-size: 16px;
    font-weight: bold;
    pointer-events: none;
}

/* 拍照提示 */
.capture-hint {
    text-align: center;
    margin-top: 10px;
    font-size: 18px;
    font-weight: bold;
}
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
    st.info("🔐 Please sign in with Google｜請先登入 Google")
    st.markdown(f"[👉 Login / 登入]({auth_url})")
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
        time.strftime("%Y-%m-%d %H:%M:%S"),
        data.get("name",""),
        data.get("title",""),
        data.get("company",""),
        data.get("phone",""),
        data.get("fax",""),
        data.get("email",""),
        data.get("address",""),
        data.get("website",""),
        link
    ])

# --------------------------------------------------
# AI 辨識
# --------------------------------------------------
def extract_info(image):
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    prompt = """
You are a business card OCR assistant.
Output JSON only. No explanation.

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
        return None

    try:
        return json.loads(match.group())
    except:
        return None

# --------------------------------------------------
# Main UI
# --------------------------------------------------
st.title("📇 Business Card Scanner")
st.caption("請將名片完整放入框線中｜Place the card fully inside the frame")

creds = get_creds()

st.markdown('<div class="camera-wrapper">', unsafe_allow_html=True)
img = st.camera_input(
    "📸 拍攝名片｜Take Photo",
    key=f"cam_{st.session_state.camera_key}",
    label_visibility="collapsed"
)
st.markdown("""
<div class="guide-frame"></div>
<div class="guide-text">
請將名片填滿框線<br>
Place the business card inside the frame
</div>
</div>
""", unsafe_allow_html=True)

st.markdown(
    '<div class="capture-hint">⬆️ 點擊上方按鈕拍攝｜Tap button above to capture</div>',
    unsafe_allow_html=True
)

if img:
    img_bytes = img.getvalue()
    image = Image.open(BytesIO(img_bytes))

    with st.spinner("🤖 AI Recognizing｜AI 辨識中..."):
        info = extract_info(image)

    if info:
        with st.spinner("☁️ Saving｜儲存中..."):
            link = upload_drive(img_bytes, f"card_{int(time.time())}.jpg", creds)
            save_sheet(info, link, creds)

        st.success("✅ Completed｜建檔完成")
        st.balloons()
        st.session_state.camera_key += 1
        time.sleep(1.2)
        st.rerun()
