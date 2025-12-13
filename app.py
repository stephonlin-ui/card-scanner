import streamlit as st
import streamlit.components.v1 as components
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
# ✅ 建議 requirements.txt 加這行（Streamlit Cloud 最穩）
# opencv-python-headless
# ==================================================

# ==================================================
# Android Chrome: camera-first UI
# ==================================================
st.set_page_config(page_title="Card Scanner", page_icon="📇", layout="wide")

components.html(
    """
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<style>
#MainMenu, footer, header {visibility:hidden;}
html, body { height: 100%; background:#0E1117; }

.block-container{ padding: 0 !important; max-width: 100vw !important; }
main > div{ padding-left: 0 !important; padding-right: 0 !important; }

:root{
  --yellow:#FFD400;
  --green:#00E676;
  --bg:#0E1117;
  --top: 54px;
  --bottom: 54px;
}

@supports (height: 100dvh){
  .camera-shell{ height: calc(100dvh - var(--top) - var(--bottom)); }
}
@supports not (height: 100dvh){
  .camera-shell{ height: calc(100svh - var(--top) - var(--bottom)); }
}

.topbar{
  position: sticky; top: 0; z-index: 50;
  background: rgba(14,17,23,0.80);
  backdrop-filter: blur(10px);
  padding: 8px 12px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  height: var(--top);
  box-sizing: border-box;
  display:flex; align-items:center; justify-content:space-between; gap:10px;
}
.topbar .left{ display:flex; flex-direction:column; gap:2px; }
.topbar .title{ font-size: 13px; font-weight: 900; color: #E9EEF6; line-height: 1.05; }
.topbar .sub{ font-size: 11px; color: rgba(233,238,246,0.72); line-height: 1.1; }
.topbar .hint{ font-size: 11px; color: rgba(233,238,246,0.60); white-space: nowrap; }

.camera-shell{
  position: relative;
  width: 100vw;
  background: var(--bg);
  overflow: hidden;
}
.camera-shell [data-testid="stCameraInput"]{
  width: 100% !important;
  max-width: 100% !important;
  margin: 0 !important;
}
.camera-shell video, .camera-shell img, .camera-shell canvas{
  width: 100% !important;
  height: auto !important;
  border-radius: 0 !important;
}

/* guide box */
.guide{
  position:absolute;
  top: 18%;
  left: 5%;
  width: 90%;
  height: 46%;
  border: 4px dashed var(--yellow);
  border-radius: 18px;
  box-shadow: 0 0 0 2000px rgba(0,0,0,0.25);
  pointer-events:none;
  transition: border-color 0.35s ease, transform 0.35s ease;
}
.guide.good{
  border-color: var(--green);
  animation: pop 0.55s ease;
}
@keyframes pop{
  0% {transform: scale(0.985);}
  60%{transform: scale(1.02);}
  100%{transform: scale(1.0);}
}
.guide-text{
  position:absolute;
  top: 8%;
  width: 100%;
  text-align:center;
  font-weight: 900;
  font-size: 13px;
  color: #fff;
  pointer-events:none;
  text-shadow: 0 2px 10px rgba(0,0,0,0.55);
  line-height: 1.2;
}

.bottombar{
  position: fixed;
  left: 0; right: 0; bottom: 0;
  z-index: 60;
  background: rgba(14,17,23,0.86);
  backdrop-filter: blur(10px);
  padding: 8px 12px;
  border-top: 1px solid rgba(255,255,255,0.06);
  height: var(--bottom);
  box-sizing: border-box;
  display:flex; align-items:center;
}
.bottombar .msg{
  font-size: 11.5px;
  color: rgba(233,238,246,0.84);
  line-height: 1.25;
}

div.stButton > button{
  border-radius: 14px !important;
  padding: 10px 12px !important;
  font-weight: 900 !important;
  font-size: 14px !important;
  width: 100% !important;
}
</style>
    """,
    height=0,
    width=0,
)

# ==================================================
# Session State
# ==================================================
if "camera_key" not in st.session_state:
    st.session_state.camera_key = 0
if "frame_good" not in st.session_state:
    st.session_state.frame_good = False
if "last_msg" not in st.session_state:
    st.session_state.last_msg = "請將名片填滿框線｜Fill the frame with the card"

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
            CLIENT_CONFIG, scopes=SCOPES, redirect_uri=st.secrets["google_oauth"]["redirect_uri"]
        )
        flow.fetch_token(code=params["code"][0])
        creds = flow.credentials
        st.session_state["credentials"] = creds.to_json()
        st.experimental_set_query_params()
        return creds

    flow = Flow.from_client_config(
        CLIENT_CONFIG, scopes=SCOPES, redirect_uri=st.secrets["google_oauth"]["redirect_uri"]
    )
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")

    st.markdown(
        """
        <div class="topbar">
          <div class="left">
            <div class="title">🔐 Login required｜需要登入</div>
            <div class="sub">請先登入 Google 才能上傳 Drive / 寫入 Sheets</div>
          </div>
          <div class="hint">Android Chrome</div>
        </div>
        """,
        unsafe_allow_html=True
    )
    st.markdown(f"[👉 Login with Google｜使用 Google 登入]({auth_url})")
    st.stop()

# ==================================================
# OpenCV: detect & crop business card (NO AI CORNERS)
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

def four_point_transform(rgb: np.ndarray, pts4: np.ndarray) -> np.ndarray:
    rect = order_points(pts4.astype("float32"))
    (tl, tr, br, bl) = rect

    widthA = np.linalg.norm(br - bl)
    widthB = np.linalg.norm(tr - tl)
    maxW = int(max(widthA, widthB))

    heightA = np.linalg.norm(tr - br)
    heightB = np.linalg.norm(tl - bl)
    maxH = int(max(heightA, heightB))

    maxW = max(maxW, 500)
    maxH = max(maxH, 300)

    dst = np.array([
        [0, 0],
        [maxW - 1, 0],
        [maxW - 1, maxH - 1],
        [0, maxH - 1]
    ], dtype="float32")

    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(rgb, M, (maxW, maxH))
    return warped

def detect_card_quad(rgb: np.ndarray):
    """
    Return (quad_pts, debug_dict) or (None, debug_dict)
    quad_pts shape: (4,2)
    """
    debug = {}
    h, w = rgb.shape[:2]
    debug["img_w"] = w
    debug["img_h"] = h

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    # Try Canny + morphology
    edged = cv2.Canny(gray, 50, 150)
    edged = cv2.dilate(edged, None, iterations=2)
    edged = cv2.erode(edged, None, iterations=1)

    cnts, _ = cv2.findContours(edged.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cnts = sorted(cnts, key=cv2.contourArea, reverse=True)[:25]

    best = None
    best_area = 0

    for c in cnts:
        area = cv2.contourArea(c)
        if area < (w * h) * 0.08:  # too small
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)

        if len(approx) == 4:
            pts = approx.reshape(4, 2).astype("float32")
            rect = order_points(pts)
            # aspect check (business card usually ~1.4~2.0, allow wider)
            ww = np.linalg.norm(rect[1] - rect[0])
            hh = np.linalg.norm(rect[3] - rect[0])
            if ww < 10 or hh < 10:
                continue
            asp = max(ww, hh) / max(1.0, min(ww, hh))
            if 1.2 <= asp <= 2.6:
                if area > best_area:
                    best_area = area
                    best = rect

    debug["best_area"] = float(best_area)
    debug["best_coverage"] = float(best_area / (w * h))

    if best is None:
        return None, debug
    return best, debug

def auto_crop_and_deskew(pil_img: Image.Image):
    """
    Returns (cropped_pil, ok, reason)
    """
    rgb = np.array(pil_img.convert("RGB"))
    h, w = rgb.shape[:2]

    quad, dbg = detect_card_quad(rgb)
    if quad is None:
        return pil_img, False, "找不到名片邊框｜No card border detected"

    # Compute coverage by warped size approximation
    ww = np.linalg.norm(quad[1] - quad[0])
    hh = np.linalg.norm(quad[3] - quad[0])
    coverage = (ww * hh) / (w * h)

    # Strong safeguards
    asp = max(ww, hh) / max(1.0, min(ww, hh))
    if coverage < 0.18:
        return pil_img, False, "名片太小，請靠近一點｜Card too small, move closer"
    if asp < 1.2 or asp > 2.8:
        return pil_img, False, "角度/框線不清楚，請調整｜Bad angle/edges unclear"

    warped = four_point_transform(rgb, quad)

    # Light enhance for OCR
    warped_gray = cv2.cvtColor(warped, cv2.COLOR_RGB2GRAY)
    warped_gray = cv2.bilateralFilter(warped_gray, 9, 75, 75)
    warped_rgb = cv2.cvtColor(warped_gray, cv2.COLOR_GRAY2RGB)

    return Image.fromarray(warped_rgb), True, "OK"

# ==================================================
# Gemini: only judge OK/NG + OCR (NO CORNERS)
# ==================================================
def gemini_quality_ok(pil_img: Image.Image):
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    w, h = pil_img.size
    prompt = f"""
Return JSON only.

You are checking if a BUSINESS CARD photo is readable enough for OCR.
If readable: ok=true.
If not: ok=false and give a short reason in Chinese + English.

Image size: {w}x{h}

Format:
{{
  "ok": true/false,
  "reason_zh": "",
  "reason_en": ""
}}
"""
    res = model.generate_content([prompt, pil_img])
    raw = (res.text or "").strip()
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return {"ok": False, "reason_zh": "AI 回傳格式錯誤", "reason_en": "Bad AI response"}, raw
    try:
        return json.loads(m.group()), raw
    except:
        return {"ok": False, "reason_zh": "AI JSON 解析失敗", "reason_en": "JSON parse failed"}, m.group()

def extract_info(card_image: Image.Image):
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    prompt = """
Output JSON only.

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
# Drive + Sheets
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
creds = get_oauth_creds()

st.markdown(
    """
    <div class="topbar">
      <div class="left">
        <div class="title">📇 名片掃描｜Card Scanner</div>
        <div class="sub">把名片放滿框線後拍照｜Fill the frame then capture</div>
      </div>
      <div class="hint">Auto-crop: OpenCV</div>
    </div>
    """,
    unsafe_allow_html=True
)

st.markdown('<div class="camera-shell">', unsafe_allow_html=True)
img = st.camera_input(" ", key=f"cam_{st.session_state.camera_key}", label_visibility="collapsed")

frame_class = "guide good" if st.session_state.frame_good else "guide"
st.markdown(
    f"""
    <div class="{frame_class}"></div>
    <div class="guide-text">讓名片盡量填滿框線｜Fill the frame</div>
    </div>
    """,
    unsafe_allow_html=True
)

st.markdown(
    f"""
    <div class="bottombar">
      <div class="msg">{st.session_state.last_msg}</div>
    </div>
    """,
    unsafe_allow_html=True
)

# ==================================================
# Auto pipeline on capture
#   1) OpenCV detect & crop/deskew
#   2) Gemini only decides OK/NG (no corners)
#   3) Gemini OCR -> Drive -> Sheets
# ==================================================
if img:
    st.session_state.frame_good = False
    st.session_state.last_msg = "📐 自動裁切校正中…｜Auto crop & deskew…"

    raw_pil = Image.open(img).convert("RGB")

    with st.spinner("Auto crop & deskew…"):
        cropped, crop_ok, crop_reason = auto_crop_and_deskew(raw_pil)

    if not crop_ok:
        st.session_state.last_msg = f"⚠️ {crop_reason}"
        if st.button("🔄 Retake｜重拍", use_container_width=True):
            st.session_state.camera_key += 1
            st.rerun()
        st.stop()

    st.session_state.last_msg = "🧠 AI 檢查清晰度…｜AI readability check…"
    with st.spinner("AI check…"):
        q, q_raw = gemini_quality_ok(cropped)

    if not bool(q.get("ok", False)):
        zh = (q.get("reason_zh") or "不夠清楚，請重拍").strip()
        en = (q.get("reason_en") or "Not clear enough, please retake").strip()
        st.session_state.last_msg = f"⚠️ {zh}｜{en}"
        if st.button("🔄 Retake｜重拍", use_container_width=True):
            st.session_state.camera_key += 1
            st.rerun()
        st.stop()

    # OK -> green frame + OCR + save
    st.session_state.frame_good = True
    st.session_state.last_msg = "🟢 OK！辨識 → 儲存…｜OCR → Save…"

    with st.spinner("OCR → Save…"):
        info, ocr_raw = extract_info(cropped)
        if not info:
            st.session_state.last_msg = "❌ OCR JSON 解析失敗｜OCR parse failed"
            st.error("❌ OCR 回傳格式異常（無法解析 JSON）")
            st.code(ocr_raw)
            st.stop()

        # Save cropped image (the corrected one)
        buf = BytesIO()
        cropped.save(buf, format="JPEG", quality=92)
        img_bytes = buf.getvalue()

        try:
            link = upload_drive(img_bytes, f"card_{int(time.time())}.jpg", creds)
        except HttpError as e:
            st.session_state.last_msg = "❌ Drive 上傳失敗｜Upload failed"
            st.error("❌ Google Drive 上傳失敗")
            status = getattr(e.resp, "status", "unknown")
            content = e.content.decode("utf-8", errors="ignore") if getattr(e, "content", None) else str(e)
            st.code(f"HTTP {status}\n{content[:2000]}")
            st.stop()

        try:
            save_sheet(info, link, creds)
        except Exception as e:
            st.session_state.last_msg = "❌ Sheets 寫入失敗｜Write failed"
            st.error("❌ Google Sheets 寫入失敗")
            st.code(str(e))
            st.stop()

    st.session_state.last_msg = "✅ 已儲存｜Saved! 1 秒後回到相機…"
    st.balloons()
    st.session_state.camera_key += 1
    time.sleep(1.0)
    st.rerun()
