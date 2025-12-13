import streamlit as st
import google.generativeai as genai
import gspread
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError
from PIL import Image
from io import BytesIO
import json
import time
import re
import cv2
import numpy as np

# ==================================================
# Page / Mobile-first UI
# ==================================================
st.set_page_config(
    page_title="Business Card Scanner｜名片掃描",
    page_icon="📇",
    layout="centered",
)

st.markdown("""
<style>
#MainMenu, footer, header {visibility:hidden;}
.block-container {padding-top: 1rem; padding-bottom: 2rem; max-width: 560px;}

:root{
  --card:#151A23;
  --muted:#AAB4C0;
  --yellow:#FFD400;
  --green:#00E676;
}

.panel{
  background: var(--card);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 18px;
  padding: 14px;
}

.camera-wrap{ position: relative; margin-top: 10px; }
.guide{
  position:absolute;
  top: 14%;
  left: 6%;
  width: 88%;
  height: 52%;
  border: 4px dashed var(--yellow);
  border-radius: 18px;
  box-shadow: 0 0 0 2000px rgba(0,0,0,0.35);
  pointer-events:none;
  transition: border-color 0.35s ease, transform 0.35s ease;
}
.guide.good{
  border-color: var(--green);
  animation: pop 0.55s ease;
}
@keyframes pop{
  0% {transform: scale(0.98);}
  60%{transform: scale(1.02);}
  100%{transform: scale(1.0);}
}
.guide-text{
  position:absolute;
  top: 4%;
  width: 100%;
  text-align:center;
  font-weight: 800;
  color: white;
  pointer-events:none;
  text-shadow: 0 2px 10px rgba(0,0,0,0.55);
  line-height: 1.25;
}

.badge{
  display:inline-block;
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(255,255,255,0.08);
  color: var(--muted);
  margin-top: 6px;
}

.big-note{
  font-size: 14px;
  color: var(--muted);
  margin-top: 8px;
  line-height: 1.35;
}

hr.soft{
  border: none;
  border-top: 1px solid rgba(255,255,255,0.08);
  margin: 12px 0;
}
</style>
""", unsafe_allow_html=True)

if "camera_key" not in st.session_state:
    st.session_state.camera_key = 0
if "frame_good" not in st.session_state:
    st.session_state.frame_good = False

# ==================================================
# Gemini
# ==================================================
if "GEMINI_API_KEY" not in st.secrets:
    st.error("缺少 GEMINI_API_KEY in secrets")
    st.stop()
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# ==================================================
# OAuth (Personal Google Account)
# ==================================================
SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]

if "google_oauth" not in st.secrets:
    st.error("缺少 [google_oauth] 設定（client_id/client_secret/redirect_uri）")
    st.stop()

CLIENT_CONFIG = {
    "web": {
        "client_id": st.secrets["google_oauth"]["client_id"],
        "client_secret": st.secrets["google_oauth"]["client_secret"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [st.secrets["google_oauth"]["redirect_uri"]],
    }
}

def get_oauth_creds():
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

    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("🔐 Sign in｜登入")
    st.write("請先登入 Google 才能上傳到 Drive 並寫入 Sheets。")
    st.markdown(f"[👉 Login with Google｜使用 Google 登入]({auth_url})")
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

# ==================================================
# Geometry helpers (OpenCV warp)
# ==================================================
def order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]  # tl
    rect[2] = pts[np.argmax(s)]  # br
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # tr
    rect[3] = pts[np.argmax(diff)]  # bl
    return rect

def four_point_transform_rgb(rgb: np.ndarray, pts4: np.ndarray) -> np.ndarray:
    # rgb shape: (H,W,3), pts4: 4x2 float32 in image pixel coords
    rect = order_points(pts4.astype("float32"))
    (tl, tr, br, bl) = rect

    widthA = np.linalg.norm(br - bl)
    widthB = np.linalg.norm(tr - tl)
    maxW = int(max(widthA, widthB))

    heightA = np.linalg.norm(tr - br)
    heightB = np.linalg.norm(tl - bl)
    maxH = int(max(heightA, heightB))

    maxW = max(maxW, 240)
    maxH = max(maxH, 140)

    dst = np.array([
        [0, 0],
        [maxW - 1, 0],
        [maxW - 1, maxH - 1],
        [0, maxH - 1]
    ], dtype="float32")

    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(rgb, M, (maxW, maxH))
    return warped

def clamp_point(p, w, h):
    x = float(p[0]); y = float(p[1])
    x = max(0.0, min(x, float(w - 1)))
    y = max(0.0, min(y, float(h - 1)))
    return [x, y]

# ==================================================
# Gemini: Card QA + corners (PIXEL coords)
# ==================================================
def gemini_find_card_corners_and_quality(pil_img: Image.Image):
    """
    Returns:
      {
        ok: bool,
        reason: str,
        coverage: float,
        corners: { tl:[x,y], tr:[x,y], br:[x,y], bl:[x,y] }
      }, raw_text
    """
    model = genai.GenerativeModel("models/gemini-2.0-flash")

    # Tell Gemini we need PIXEL coords based on image size.
    w, h = pil_img.size
    prompt = f"""
You are a business card framing assistant.
Analyze the photo and return JSON only (no markdown, no explanation).
Task:
1) Determine if the card is well-framed (fills enough of the image, not cut off, not too tilted/blurred).
2) If a card is present, return the 4 card corners in PIXEL coordinates relative to the image.

Image size:
width={w}, height={h}

Rules:
- corners must be numbers (pixels).
- Use these keys: tl, tr, br, bl.
- If you cannot confidently find corners, set ok=false and corners=null.
- coverage is approximate fraction of image area occupied by the card (0..1).
- reason: short reason in English or Chinese.

Return exactly:
{{
  "ok": true/false,
  "reason": "",
  "coverage": 0.0,
  "corners": {{
    "tl": [0,0],
    "tr": [0,0],
    "br": [0,0],
    "bl": [0,0]
  }} or null
}}
"""
    res = model.generate_content([prompt, pil_img])
    raw = (res.text or "").strip()

    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None, raw

    try:
        data = json.loads(m.group())
        return data, raw
    except:
        return None, m.group()

# ==================================================
# Gemini OCR (robust JSON)
# ==================================================
def extract_info(card_image: Image.Image):
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    prompt = """
You are a business card OCR assistant.
Output JSON only. No markdown, no explanation.
If unknown, use empty string.

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
    res = model.generate_content([prompt, card_image])
    raw = (res.text or "").strip()
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None, raw
    try:
        return json.loads(m.group()), raw
    except:
        return None, m.group()

# ==================================================
# Drive + Sheets (OAuth)
# ==================================================
def upload_drive(img_bytes: bytes, filename: str, creds: Credentials) -> str:
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    media = MediaIoBaseUpload(BytesIO(img_bytes), mimetype="image/jpeg", resumable=False)
    body = {"name": filename}

    folder_id = ""
    if "DRIVE_FOLDER_ID" in st.secrets:
        folder_id = str(st.secrets["DRIVE_FOLDER_ID"]).strip()
    if folder_id:
        body["parents"] = [folder_id]

    file = service.files().create(body=body, media_body=media, fields="id,webViewLink").execute()
    return file["webViewLink"]

def save_sheet(data: dict, link: str, creds: Credentials):
    gc = gspread.authorize(creds)
    try:
        sheet = gc.open("Business_Cards_Data").sheet1
    except:
        sh = gc.create("Business_Cards_Data")
        sheet = sh.sheet1
        sheet.append_row(["時間","姓名","職稱","公司","電話","傳真","Email","地址","網址","拍攝的檔案連結"])

    sheet.append_row([
        time.strftime("%Y-%m-%d %H:%M:%S"),  # A
        data.get("name",""),                 # B
        data.get("title",""),                # C
        data.get("company",""),              # D
        data.get("phone",""),                # E
        data.get("fax",""),                  # F
        data.get("email",""),                # G
        data.get("address",""),              # H
        data.get("website",
