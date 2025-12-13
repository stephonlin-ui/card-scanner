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
import re
import cv2
import numpy as np

# ==================================================
# Page / Mobile UX
# ==================================================
st.set_page_config(
    page_title="Business Card Scanner",
    page_icon="📇",
    layout="centered"
)

st.markdown("""
<style>
#MainMenu, footer, header {visibility:hidden;}

body {
    background-color: #0E1117;
}

.camera-box {
    position: relative;
    max-width: 420px;
    margin: auto;
}

.frame {
    position: absolute;
    top: 18%;
    left: 5%;
    width: 90%;
    height: 45%;
    border: 4px dashed #FFD400;
    border-radius: 18px;
    box-shadow: 0 0 0 2000px rgba(0,0,0,0.45);
    pointer-events: none;
    transition: border-color 0.4s ease;
}

.frame.good {
    border-color: #00E676;
}

.hint {
    position: absolute;
    top: 6%;
    width: 100%;
    text-align: center;
    font-size: 16px;
    font-weight: bold;
    color: white;
    pointer-events: none;
}

.take-btn {
    background: #0066FF;
    color: white;
    font-size: 20px;
    padding: 16px;
    border-radius: 16px;
    text-align: center;
    margin-top: 16px;
    font-weight: bold;
}
</style>
""", unsafe_allow_html=True)

if "camera_key" not in st.session_state:
    st.session_state.camera_key = 0

# ==================================================
# Gemini
# ==================================================
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# ==================================================
# Google credentials (Service Account)
# ==================================================
def get_creds_and_folder():
    creds_dict = dict(st.secrets["gcp_service_account"])
    if "\\n" in creds_dict["private_key"]:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    scopes = [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets"
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    folder_id = st.secrets["DRIVE_FOLDER_ID"]
    return creds, folder_id

# ==================================================
# OpenCV: detect + crop + perspective correction
# ==================================================
def auto_crop_card(pil_img: Image.Image) -> Image.Image:
    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5,5), 0)
    edged = cv2.Canny(blur, 75, 200)

    contours, _ = cv2.findContours(edged, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    for c in contours:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            pts = approx.reshape(4,2)
            rect = order_points(pts)
            return four_point_transform(img, rect)

    return pil_img

def order_points(pts):
    rect = np.zeros((4,2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect

def four_point_transform(image, rect):
    (tl,tr,br,bl) = rect
    widthA = np.linalg.norm(br - bl)
    widthB = np.linalg.norm(tr - tl)
    maxW = int(max(widthA, widthB))
    heightA = np.linalg.norm(tr - br)
    heightB = np.linalg.norm(tl - bl)
    maxH = int(max(heightA, heightB))

    dst = np.array([
        [0,0],[maxW-1,0],[maxW-1,maxH-1],[0,maxH-1]
    ], dtype="float32")

    M = cv2.getPerspectiveTransform(rect, dst)
    warp = cv2.warpPerspective(image, M, (maxW, maxH))
    return Image.fromarray(cv2.cvtColor(warp, cv2.COLOR_BGR2RGB))

# ==================================================
# Gemini OCR
# ==================================================
def extract_info(image):
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    prompt = """
Return JSON only.
{name,title,company,phone,fax,email,address,website}
"""
    res = model.generate_content([prompt, image])
    m = re.search(r"\{[\s\S]*\}", res.text)
    return json.loads(m.group()) if m else None

# ==================================================
# Upload / Sheet
# ==================================================
def upload_drive(img_bytes, filename, creds, folder_id):
    service = build("drive", "v3", credentials=creds)
    media = MediaIoBaseUpload(BytesIO(img_bytes), mimetype="image/jpeg")
    file = service.files().create(
        body={"name": filename, "parents":[folder_id]},
        media_body=media,
        fields="webViewLink"
    ).execute()
    return file["webViewLink"]

def save_sheet(data, link, creds):
    gc = gspread.authorize(creds)
    try:
        sheet = gc.open("Business_Cards_Data").sheet1
    except:
        sh = gc.create("Business_Cards_Data")
        sheet = sh.sheet1
        sheet.append_row(
            ["時間","姓名","職稱","公司","電話","傳真","Email","地址","網址","照片連結"]
        )

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

# ==================================================
# UI
# ==================================================
st.title("📇 Business Card Scanner")
st.caption("請將名片放入框線內｜Place card inside frame")

st.markdown('<div class="camera-box">', unsafe_allow_html=True)
img = st.camera_input(
    "Take Photo",
    key=f"cam_{st.session_state.camera_key}",
    label_visibility="collapsed"
)
st.markdown("""
<div class="frame"></div>
<div class="hint">
調整距離直到名片填滿<br>
Adjust distance until card fills frame
</div>
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="take-btn">📸 Take Photo｜拍攝</div>', unsafe_allow_html=True)

# ==================================================
# After capture
# ==================================================
if img:
    creds, folder_id = get_creds_and_folder()

    raw_img = Image.open(img)
    cropped = auto_crop_card(raw_img)

    st.markdown("""
    <script>
    document.querySelector('.frame')?.classList.add('good');
    </script>
    """, unsafe_allow_html=True)

    with st.spinner("🤖 AI Processing｜辨識中"):
        info = extract_info(cropped)

    if info:
        buf = BytesIO()
        cropped.save(buf, format="JPEG")
        link = upload_drive(buf.getvalue(), f"card_{int(time.time())}.jpg", creds, folder_id)
        save_sheet(info, link, creds)

        st.success("✅ 完成｜Saved Successfully")
        st.balloons()
        st.session_state.camera_key += 1
        time.sleep(1)
        st.rerun()
