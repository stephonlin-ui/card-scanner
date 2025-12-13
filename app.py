import streamlit as st
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from PIL import Image
from io import BytesIO
import json
import time

# -------------------------------
# Page config
# -------------------------------
st.set_page_config(
    page_title="Card Scanner",
    page_icon="📇",
    layout="wide"
)

# -------------------------------
# Minimal mobile-first CSS
# -------------------------------
st.markdown("""
<style>
#MainMenu, footer, header {visibility:hidden;}
.block-container {padding:0!important;}
main > div {padding:0!important;}

.camera-wrap video,
.camera-wrap img {
    width:100%!important;
    height:auto!important;
}

.hint {
    font-size:14px;
    color:#ddd;
    padding:8px 12px;
    background:#111;
}

.result-ok {color:#00e676;font-weight:700;}
.result-ng {color:#ff5252;font-weight:700;}

button {
    font-size:18px!important;
    font-weight:700!important;
    padding:14px!important;
}
</style>
""", unsafe_allow_html=True)

# -------------------------------
# Gemini setup
# -------------------------------
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
MODEL = genai.GenerativeModel("models/gemini-2.0-flash")

# -------------------------------
# Google credentials
# -------------------------------
def get_creds():
    info = dict(st.secrets["gcp_service_account"])
    if "\\n" in info["private_key"]:
        info["private_key"] = info["private_key"].replace("\\n", "\n")
    scopes = [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets"
    ]
    return Credentials.from_service_account_info(info, scopes=scopes)

# -------------------------------
# Upload image to Drive
# -------------------------------
def upload_to_drive(img_bytes, filename):
    creds = get_creds()
    service = build("drive", "v3", credentials=creds)

    media = MediaIoBaseUpload(BytesIO(img_bytes), mimetype="image/jpeg")
    file = service.files().create(
        body={
            "name": filename,
            "parents": [st.secrets["DRIVE_FOLDER_ID"]]
        },
        media_body=media,
        fields="id,webViewLink",
        supportsAllDrives=True
    ).execute()

    return file["webViewLink"]

# -------------------------------
# Save to Google Sheets
# -------------------------------
def save_to_sheet(data, image_link):
    creds = get_creds()
    client = gspread.authorize(creds)

    try:
        sh = client.open("Business_Cards_Data")
        sheet = sh.sheet1
    except:
        sh = client.create("Business_Cards_Data")
        sheet = sh.sheet1
        sheet.append_row([
            "時間","姓名","職稱","公司","電話","傳真",
            "Email","地址","網址","照片連結"
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
        image_link
    ])

# -------------------------------
# AI-only extraction
# -------------------------------
def extract_with_ai(image: Image.Image):
    prompt = """
你會看到一張手機拍攝的照片，可能包含名片。

請你：
1. 判斷畫面中是否存在「可辨識的名片資訊」
2. 忽略背景、桌面、手指、裝飾圖形
3. 只輸出你「有信心正確」的文字
4. 如果無法可靠辨識，ok=false 並說明原因

請輸出 JSON：
{
  "ok": true/false,
  "reason": "",
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
    res = MODEL.generate_content([prompt, image])
    text = res.text.strip()
    text = text.replace("```json","").replace("```","")
    return json.loads(text)

# -------------------------------
# UI
# -------------------------------
st.markdown("### 📇 名片掃描｜Card Scanner")
st.markdown(
    '<div class="hint">請讓名片文字清楚可見後拍照<br/>Make sure the text is clear before capture</div>',
    unsafe_allow_html=True
)

img_file = st.camera_input("拍攝名片 | Take Photo", label_visibility="collapsed")

if img_file:
    image = Image.open(img_file)
    img_bytes = img_file.getvalue()

    with st.spinner("AI 辨識中…"):
        result = extract_with_ai(image)

    if not result.get("ok"):
        st.markdown(
            f'<p class="result-ng">❌ 無法辨識：{result.get("reason","")}</p>',
            unsafe_allow_html=True
        )
    else:
        st.markdown('<p class="result-ok">✅ 辨識成功，已自動存檔</p>', unsafe_allow_html=True)

        filename = f"card_{int(time.time())}.jpg"
        link = upload_to_drive(img_bytes, filename)
        save_to_sheet(result, link)

        st.success("已寫入 Google Sheets")
