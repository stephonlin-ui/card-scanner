import streamlit as st
import time
import json
import numpy as np
import cv2
from PIL import Image
from io import BytesIO

import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# =========================
# Page config
# =========================
st.set_page_config(
    page_title="Card Scanner",
    page_icon="📇",
    layout="wide"
)

# =========================
# CSS (一定要 unsafe_allow_html)
# =========================
st.markdown(
    """
    <style>
    #MainMenu, footer, header {visibility:hidden;}

    .block-container{
      padding: 0 !important;
      max-width: 100vw !important;
    }

    main > div{
      padding-left: 0 !important;
      padding-right: 0 !important;
    }

    .topbar{
      padding:8px 12px;
      font-size:13px;
      font-weight:700;
      background:#0E1117;
      color:#E9EEF6;
      text-align:center;
    }

    .hint{
      font-size:12px;
      color:#B0B7C3;
      margin-top:2px;
    }

    .camera-wrap{
      width:100vw;
      background:#000;
    }

    .camera-wrap video,
    .camera-wrap img,
    .camera-wrap canvas{
      width:100% !important;
      height:auto !important;
      border-radius:0 !important;
    }

    .guide{
      position:absolute;
      top:20%;
      left:5%;
      width:90%;
      height:45%;
      border:4px dashed #FFD400;
      border-radius:16px;
      box-shadow:0 0 0 2000px rgba(0,0,0,0.25);
      pointer-events:none;
    }

    .bottombar{
      padding:10px;
    }

    .stButton > button{
      width:100%;
      padding:14px;
      font-size:16px;
      font-weight:800;
      border-radius:14px;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# =========================
# Secrets & API
# =========================
if "GEMINI_API_KEY" not in st.secrets:
    st.stop()

genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

def get_creds():
    creds_dict = dict(st.secrets["gcp_service_account"])
    if "\\n" in creds_dict["private_key"]:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    scopes = [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets"
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return creds

DRIVE_FOLDER_ID = st.secrets.get("DRIVE_FOLDER_ID", "").strip()

# =========================
# OpenCV crop (穩定版)
# =========================
def auto_crop_card(pil_img):
    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5,5), 0)
    edges = cv2.Canny(blur, 60, 120)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    h, w = gray.shape
    img_area = h * w

    for cnt in contours[:5]:
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)

        if len(approx) == 4:
            area = cv2.contourArea(approx)
            if area / img_area < 0.2:
                continue

            pts = approx.reshape(4,2)
            rect = cv2.minAreaRect(pts)
            box = cv2.boxPoints(rect)
            box = np.int0(box)

            width = int(rect[1][0])
            height = int(rect[1][1])

            if width < height:
                width, height = height, width

            dst = np.array([
                [0,0],
                [width-1,0],
                [width-1,height-1],
                [0,height-1]
            ], dtype="float32")

            src = np.array(box, dtype="float32")
            M = cv2.getPerspectiveTransform(src, dst)
            warp = cv2.warpPerspective(img, M, (width, height))
            return Image.fromarray(cv2.cvtColor(warp, cv2.COLOR_BGR2RGB))

    return pil_img

# =========================
# Gemini OCR
# =========================
def extract_info(pil_img):
    model = genai.GenerativeModel("models/gemini-2.5-flash")
    prompt = """
    請從名片圖片中擷取資訊，輸出 JSON：
    {
      "name":"",
      "title":"",
      "company":"",
      "phone":"",
      "fax":"",
      "email":"",
      "address":"",
      "website":""
    }
    只輸出 JSON
    """
    res = model.generate_content([prompt, pil_img])
    txt = res.text.strip()

    if txt.startswith("```"):
        txt = txt.strip("`")
        txt = txt.replace("json", "").strip()

    return json.loads(txt)

# =========================
# Drive upload
# =========================
def upload_drive(img_bytes, filename):
    creds = get_creds()
    service = build("drive", "v3", credentials=creds)

    media = MediaIoBaseUpload(BytesIO(img_bytes), mimetype="image/jpeg", resumable=False)
    file = service.files().create(
        body={"name": filename, "parents":[DRIVE_FOLDER_ID]},
        media_body=media,
        fields="id,webViewLink",
        supportsAllDrives=True
    ).execute()
    return file["webViewLink"]

# =========================
# Sheet write
# =========================
def write_sheet(data, link):
    creds = get_creds()
    client = gspread.authorize(creds)

    try:
        sh = client.open("Business_Cards_Data")
    except:
        sh = client.create("Business_Cards_Data")

    ws = sh.sheet1
    if ws.row_count == 0:
        ws.append_row([
            "時間","姓名","職稱","公司","電話","傳真",
            "Email","地址","網址","照片連結"
        ])

    ws.append_row([
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

# =========================
# UI
# =========================
st.markdown(
    "<div class='topbar'>📇 名片掃描｜Card Scanner<div class='hint'>請將名片放入框線內後拍攝</div></div>",
    unsafe_allow_html=True
)

cam = st.camera_input(
    " ",
    label_visibility="collapsed",
    facing_mode="environment"
)

if cam:
    raw_img = Image.open(cam)
    time.sleep(0.6)

    with st.spinner("🧠 辨識中..."):
        cropped = auto_crop_card(raw_img)
        info = extract_info(cropped)

        buf = BytesIO()
        cropped.save(buf, format="JPEG")
        link = upload_drive(buf.getvalue(), f"card_{int(time.time())}.jpg")
        write_sheet(info, link)

    st.success("✅ 完成")
    st.image(cropped, use_column_width=True)
