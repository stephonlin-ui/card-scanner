import streamlit as st
import streamlit.components.v1 as components

import time
import json
import re
from io import BytesIO

from PIL import Image

# ---- Optional (for auto crop/deskew) ----
try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except Exception:
    HAS_CV2 = False

import google.generativeai as genai
import gspread

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError


# =========================================================
# Page / UI
# =========================================================
st.set_page_config(page_title="Card Scanner", page_icon="📇", layout="wide")

# IMPORTANT: CSS must be injected with st.markdown(unsafe_allow_html=True)
st.markdown(
    """
<style>
#MainMenu, footer, header {visibility:hidden;}
.block-container{padding:0!important; max-width:100vw!important;}
main > div{padding-left:0!important; padding-right:0!important;}
html, body {background:#0E1117;}

.topbar{
  position: sticky; top:0; z-index:50;
  background: rgba(14,17,23,0.92);
  backdrop-filter: blur(10px);
  padding: 10px 12px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  color:#E9EEF6;
  font-weight:900;
  font-size:14px;
  line-height:1.15;
}
.topbar .sub{
  margin-top:4px;
  font-weight:700;
  font-size:12px;
  color: rgba(233,238,246,0.72);
}

.camera-wrap{
  position: relative;
  width: 100vw;
  background:#000;
  overflow:hidden;
}
.camera-wrap [data-testid="stCameraInput"]{width:100%!important; max-width:100%!important; margin:0!important;}
.camera-wrap video,.camera-wrap img,.camera-wrap canvas{width:100%!important; height:auto!important; border-radius:0!important;}

.guide{
  position:absolute;
  top: 18%;
  left: 5%;
  width: 90%;
  height: 46%;
  border: 4px dashed #FFD400;
  border-radius: 18px;
  box-shadow: 0 0 0 2000px rgba(0,0,0,0.25);
  pointer-events:none;
}
.guide.good{ border-color:#00E676; animation: pop 0.55s ease; }
@keyframes pop{ 0%{transform:scale(0.985);} 60%{transform:scale(1.02);} 100%{transform:scale(1.0);} }

.overlay-text{
  position:absolute;
  top: 8%;
  width: 100%;
  text-align:center;
  color:#fff;
  font-weight:900;
  font-size:13px;
  text-shadow: 0 2px 10px rgba(0,0,0,0.55);
  pointer-events:none;
  line-height:1.2;
}

.bottombar{
  position: fixed;
  left:0; right:0; bottom:0; z-index:60;
  background: rgba(14,17,23,0.90);
  backdrop-filter: blur(10px);
  padding: 10px 12px;
  border-top: 1px solid rgba(255,255,255,0.06);
  color: rgba(233,238,246,0.84);
  font-size: 12px;
  font-weight: 800;
}
div.stButton > button{
  border-radius: 14px !important;
  padding: 12px 14px !important;
  font-weight: 900 !important;
  font-size: 16px !important;
  width: 100% !important;
}
a { color: #7AA7FF; font-weight:900; }
</style>
    """,
    unsafe_allow_html=True
)

# (Optional) force mobile-friendly viewport
components.html(
    '<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">',
    height=0
)

if "camera_key" not in st.session_state:
    st.session_state.camera_key = 0
if "frame_good" not in st.session_state:
    st.session_state.frame_good = False
if "status_msg" not in st.session_state:
    st.session_state.status_msg = "請將名片填滿框線後拍攝｜Fill the frame then capture"


# =========================================================
# Secrets required
# =========================================================
# [google_oauth]
# client_id = "..."
# client_secret = "..."
# redirect_uri = "https://YOUR-APP.streamlit.app/"
#
# GEMINI_API_KEY = "..."
# DRIVE_FOLDER_ID = "..."   # optional (will create in My Drive if empty)
#
# IMPORTANT: Google Cloud OAuth Consent Screen must include these scopes.

REQUIRED_SECRETS = ["google_oauth", "GEMINI_API_KEY"]
for k in REQUIRED_SECRETS:
    if k not in st.secrets:
        st.error(f"❌ Missing secrets: {k}")
        st.stop()

GO = st.secrets["google_oauth"]
for k in ["client_id", "client_secret", "redirect_uri"]:
    if k not in GO:
        st.error(f"❌ Missing secrets: google_oauth.{k}")
        st.stop()

genai.configure(api_key=str(st.secrets["GEMINI_API_KEY"]).strip())

# =========================================================
# OAuth (AUO style) – user login, then write to THEIR Drive/Sheets
# =========================================================
SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]

CLIENT_CONFIG = {
    "web": {
        "client_id": GO["client_id"],
        "client_secret": GO["client_secret"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [GO["redirect_uri"]],
    }
}

def get_oauth_creds():
    # 1) already logged in
    if "oauth_creds_json" in st.session_state:
        creds = Credentials.from_authorized_user_info(json.loads(st.session_state["oauth_creds_json"]), SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            st.session_state["oauth_creds_json"] = creds.to_json()
        return creds

    # 2) returning from Google with code
    params = st.query_params
    if "code" in params:
        code = params["code"]
        flow = Flow.from_client_config(
            CLIENT_CONFIG,
            scopes=SCOPES,
            redirect_uri=GO["redirect_uri"],
        )
        flow.fetch_token(code=code)
        creds = flow.credentials
        st.session_state["oauth_creds_json"] = creds.to_json()
        st.query_params.clear()
        return creds

    # 3) not logged in: show login link
    flow = Flow.from_client_config(
        CLIENT_CONFIG,
        scopes=SCOPES,
        redirect_uri=GO["redirect_uri"],
    )
    auth_url, _ = flow.authorization_url(
        prompt="consent",
        access_type="offline",
        include_granted_scopes="true"
    )

    st.markdown(
        """
<div class="topbar">
  🔐 Login required｜需要登入
  <div class="sub">請先用 Google 登入授權 Drive / Sheets（AUO 模式）</div>
</div>
        """,
        unsafe_allow_html=True
    )

    st.markdown("📷 **建議使用後鏡頭拍攝**（若開到前鏡頭，請在相機介面切換一次，Chrome 會記住）  \n"
                "Please use **rear camera**. If it opens front camera, switch once and Chrome will remember.")

    st.markdown(f"👉 [Login with Google｜使用 Google 登入]({auth_url})")
    st.stop()


# =========================================================
# OpenCV: auto crop & deskew (no AI corners)
# =========================================================
def _order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect

def _four_point_transform(rgb: np.ndarray, pts4: np.ndarray) -> np.ndarray:
    rect = _order_points(pts4.astype("float32"))
    (tl, tr, br, bl) = rect

    widthA = np.linalg.norm(br - bl)
    widthB = np.linalg.norm(tr - tl)
    maxW = int(max(widthA, widthB))

    heightA = np.linalg.norm(tr - br)
    heightB = np.linalg.norm(tl - bl)
    maxH = int(max(heightA, heightB))

    maxW = max(maxW, 600)
    maxH = max(maxH, 350)

    dst = np.array([[0, 0], [maxW - 1, 0], [maxW - 1, maxH - 1], [0, maxH - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(rgb, M, (maxW, maxH))
    return warped

def auto_crop_and_deskew(pil_img: Image.Image):
    # If opencv not available, just return original
    if not HAS_CV2:
        return pil_img, False, "缺少 OpenCV（cv2）｜OpenCV missing"

    rgb = np.array(pil_img.convert("RGB"))
    h, w = rgb.shape[:2]
    img_area = float(w * h)

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    edged = cv2.Canny(gray, 50, 150)
    edged = cv2.dilate(edged, None, iterations=2)
    edged = cv2.erode(edged, None, iterations=1)

    cnts, _ = cv2.findContours(edged.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cnts = sorted(cnts, key=cv2.contourArea, reverse=True)[:25]

    best = None
    best_area = 0.0

    for c in cnts:
        area = cv2.contourArea(c)
        if area < img_area * 0.10:
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) != 4:
            continue

        pts = approx.reshape(4, 2).astype("float32")
        rect = _order_points(pts)
        ww = np.linalg.norm(rect[1] - rect[0])
        hh = np.linalg.norm(rect[3] - rect[0])
        if ww < 20 or hh < 20:
            continue

        aspect = max(ww, hh) / max(1.0, min(ww, hh))
        coverage = (ww * hh) / img_area

        # Safeguards to avoid cropping only a small corner/logo
        if coverage < 0.20:
            continue
        if aspect < 1.15 or aspect > 2.8:
            continue

        if area > best_area:
            best_area = area
            best = rect

    if best is None:
        return pil_img, False, "找不到清楚的名片邊框｜No clear card border"

    warped = _four_point_transform(rgb, best)

    # light enhance for OCR
    wg = cv2.cvtColor(warped, cv2.COLOR_RGB2GRAY)
    wg = cv2.bilateralFilter(wg, 9, 75, 75)
    wrgb = cv2.cvtColor(wg, cv2.COLOR_GRAY2RGB)

    return Image.fromarray(wrgb), True, "OK"


# =========================================================
# Gemini OCR (robust JSON parse)
# =========================================================
def extract_info(card_image: Image.Image):
    model = genai.GenerativeModel("models/gemini-2.5-flash")
    prompt = """
只輸出 JSON（不要 markdown、不要多餘文字）：
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
"""
    res = model.generate_content([prompt, card_image])
    raw = (res.text or "").strip()

    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None, raw

    try:
        data = json.loads(m.group())
        if not isinstance(data, dict):
            return None, raw
        return data, raw
    except Exception:
        return None, raw


# =========================================================
# Drive + Sheets using OAuth creds (AUO mode)
# =========================================================
def drive_service(creds: Credentials):
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def ensure_folder(creds: Credentials, folder_id: str):
    folder_id = (folder_id or "").strip()
    if folder_id:
        return folder_id

    # Create a folder in user's My Drive
    svc = drive_service(creds)
    meta = {
        "name": "BusinessCards",
        "mimeType": "application/vnd.google-apps.folder",
    }
    f = svc.files().create(body=meta, fields="id").execute()
    return f["id"]

def upload_to_drive(creds: Credentials, img_bytes: bytes, filename: str, folder_id: str):
    svc = drive_service(creds)
    folder_id = ensure_folder(creds, folder_id)

    media = MediaIoBaseUpload(BytesIO(img_bytes), mimetype="image/jpeg", resumable=False)
    body = {"name": filename, "parents": [folder_id]}
    f = svc.files().create(body=body, media_body=media, fields="id,webViewLink").execute()
    return f["webViewLink"]

def open_or_create_sheet(creds: Credentials, title="Business_Cards_Data"):
    gc = gspread.authorize(creds)
    try:
        sh = gc.open(title)
    except Exception:
        sh = gc.create(title)
    ws = sh.sheet1
    # Ensure header row exists
    try:
        first = ws.row_values(1)
    except Exception:
        first = []
    if not first:
        ws.append_row(["時間","姓名","職稱","公司","電話","傳真","Email","地址","網址","拍攝的檔案連結"])
    return ws

def append_row(ws, data: dict, link: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    ws.append_row([
        ts,
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


# =========================================================
# Main UI
# =========================================================
creds = get_oauth_creds()

st.markdown(
    """
<div class="topbar">
  📇 名片掃描｜Card Scanner
  <div class="sub">將名片放滿框線後拍攝｜Fill the frame then capture</div>
</div>
    """,
    unsafe_allow_html=True
)

# camera area
st.markdown('<div class="camera-wrap">', unsafe_allow_html=True)
img_file = st.camera_input(" ", label_visibility="collapsed", key=f"cam_{st.session_state.camera_key}")
guide_cls = "guide good" if st.session_state.frame_good else "guide"
st.markdown(f'<div class="{guide_cls}"></div>', unsafe_allow_html=True)
st.markdown('<div class="overlay-text">建議使用後鏡頭｜Use rear camera</div>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

st.markdown(f'<div class="bottombar">{st.session_state.status_msg}</div>', unsafe_allow_html=True)

if img_file:
    st.session_state.frame_good = False
    st.session_state.status_msg = "處理中…｜Processing…"
    time.sleep(0.6)  # give autofocus a moment

    raw_pil = Image.open(img_file).convert("RGB")

    # 1) Auto crop/deskew (OpenCV)
    cropped = raw_pil
    crop_ok = False
    crop_reason = "SKIP"

    if HAS_CV2:
        cropped, crop_ok, crop_reason = auto_crop_and_deskew(raw_pil)
    else:
        crop_ok = False
        crop_reason = "OpenCV missing"

    # If crop fails, fallback to original (still OCR, but tell user)
    if not crop_ok:
        st.session_state.status_msg = f"⚠️ 無法自動裁切（改用原圖）｜Crop failed (use original)"
        cropped = raw_pil
    else:
        st.session_state.frame_good = True
        st.session_state.status_msg = "🟢 OK！裁切校正完成｜Cropped & deskewed"

    # 2) OCR
    with st.spinner("🧠 OCR…"):
        info, raw_text = extract_info(cropped)
    if not info:
        st.session_state.status_msg = "❌ OCR 解析失敗｜OCR parse failed"
        st.error("OCR 回傳不是合法 JSON（已顯示原文方便除錯）")
        st.code(raw_text[:3000])
        st.stop()

    # 3) Upload + Sheet
    with st.spinner("☁️ Upload + Sheet…"):
        try:
            buf = BytesIO()
            cropped.save(buf, format="JPEG", quality=92)
            img_bytes = buf.getvalue()

            folder_id = str(st.secrets.get("DRIVE_FOLDER_ID", "")).strip()
            link = upload_to_drive(creds, img_bytes, f"card_{int(time.time())}.jpg", folder_id)

            ws = open_or_create_sheet(creds, title="Business_Cards_Data")
            append_row(ws, info, link)

        except HttpError as e:
            # Show readable error message instead of redacted crash
            st.session_state.status_msg = "❌ Google API 錯誤｜Google API error"
            status = getattr(e.resp, "status", "unknown")
            content = ""
            try:
                content = e.content.decode("utf-8", errors="ignore")
            except Exception:
                content = str(e)
            st.error(f"Google API HttpError (HTTP {status})")
            st.code(content[:3000])
            st.stop()
        except Exception as e:
            st.session_state.status_msg = "❌ 儲存失敗｜Save failed"
            st.error(str(e))
            st.stop()

    st.session_state.status_msg = "✅ 辨識成功，已自動存檔｜Saved!"
    st.success("✅ 辨識成功，已自動存檔｜Saved!")
    st.image(cropped, use_container_width=True)

    # reset camera
    st.session_state.camera_key += 1
    time.sleep(0.8)
    st.rerun()
