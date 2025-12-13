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
# Android Chrome: camera-first UI (FULL FILE)
# ==================================================
st.set_page_config(page_title="Card Scanner", page_icon="📇", layout="wide")

# ✅ Use components.html to inject CSS (prevents CSS showing as text)
components.html(
    """
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<style>
#MainMenu, footer, header {visibility:hidden;}

/* Remove Streamlit padding so camera can be near full screen */
.block-container{
  padding: 0 !important;
  max-width: 100vw !important;
}
main > div{
  padding-left: 0 !important;
  padding-right: 0 !important;
}

/* Android Chrome address bar collapses/expands: prefer dvh when supported */
:root{
  --yellow:#FFD400;
  --green:#00E676;
  --bg:#0E1117;
  --bar: 54px;     /* top bar height */
  --bar2: 54px;    /* bottom bar height */
}

@supports (height: 100dvh){
  .camera-shell{
    height: calc(100dvh - var(--bar) - var(--bar2));
  }
}
@supports not (height: 100dvh){
  .camera-shell{
    height: calc(100vh - var(--bar) - var(--bar2));
  }
}

/* Top thin bar */
.topbar{
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(14,17,23,0.78);
  backdrop-filter: blur(10px);
  padding: 8px 12px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  height: var(--bar);
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
}
.topbar .title{
  font-size: 13px;
  font-weight: 900;
  color: #E9EEF6;
  line-height: 1.1;
}
.topbar .sub{
  font-size: 11px;
  color: rgba(233,238,246,0.70);
  line-height: 1.2;
}

/* Camera shell: full width, full remaining height */
.camera-shell{
  position: relative;
  width: 100vw;
  background: var(--bg);
  overflow: hidden;
}

/* Make Streamlit camera component fill width */
.camera-shell [data-testid="stCameraInput"]{
  width: 100% !important;
  max-width: 100% !important;
  margin: 0 !important;
}

/* Ensure preview fills width */
.camera-shell video,
.camera-shell img,
.camera-shell canvas{
  width: 100% !important;
  height: auto !important;
  border-radius: 0 !important;
}

/* Guide box */
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

/* Bottom thin status bar */
.bottombar{
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 60;
  background: rgba(14,17,23,0.82);
  backdrop-filter: blur(10px);
  padding: 8px 12px;
  border-top: 1px solid rgba(255,255,255,0.06);
  height: var(--bar2);
  box-sizing: border-box;
  display: flex;
  align-items: center;
}
.bottombar .msg{
  font-size: 11.5px;
  color: rgba(233,238,246,0.82);
  line-height: 1.25;
}

/* Touch-friendly button */
div.stButton > button{
  border-radius: 14px !important;
  padding: 12px 14px !important;
  font-weight: 900 !important;
  font-size: 16px !important;
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

    st.markdown(
        """
        <div class="topbar">
          <div class="title">🔐 Login required｜需要登入</div>
          <div class="sub">請先登入 Google 才能上傳 Drive / 寫入 Sheets</div>
        </div>
        """,
        unsafe_allow_html=True
    )
    st.markdown(f"[👉 Login with Google｜使用 Google 登入]({auth_url})")
    st.stop()

# ==================================================
# OpenCV warp helpers
# ==================================================
def order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect

def clamp_point(p, w, h):
    x = float(p[0]); y = float(p[1])
    x = max(0.0, min(x, float(w - 1)))
    y = max(0.0, min(y, float(h - 1)))
    return [x, y]

def four_point_transform_rgb(rgb: np.ndarray, pts4: np.ndarray) -> np.ndarray:
    rect = order_points(pts4.astype("float32"))
    (tl, tr, br, bl) = rect

    widthA = np.linalg.norm(br - bl)
    widthB = np.linalg.norm(tr - tl)
    maxW = int(max(widthA, widthB))

    heightA = np.linalg.norm(tr - br)
    heightB = np.linalg.norm(tl - bl)
    maxH = int(max(heightA, heightB))

    maxW = max(maxW, 280)
    maxH = max(maxH, 170)

    dst = np.array([
        [0, 0],
        [maxW - 1, 0],
        [maxW - 1, maxH - 1],
        [0, maxH - 1]
    ], dtype="float32")

    M = cv2.getPerspectiveTransform(rect.astype("float32"), dst)
    warped = cv2.warpPerspective(rgb, M, (maxW, maxH))
    return warped

# ==================================================
# Gemini: corners + quality (PIXELS)
# ==================================================
def gemini_find_card_corners_and_quality(pil_img: Image.Image):
    model = genai.GenerativeModel("models/gemini-2.0-flash")
    w, h = pil_img.size
    prompt = f"""
Return JSON only.

Image size: width={w}, height={h}

Decide if card is readable & well-framed.
If OK: provide 4 corners in PIXEL coords.
If not OK: ok=false, corners=null.

Format:
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
        return json.loads(m.group()), raw
    except:
        return None, m.group()

# ==================================================
# Gemini OCR
# ==================================================
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
      <div class="title">📇 名片掃描｜Card Scanner</div>
      <div class="sub">把名片放滿框線後拍照｜Fill the frame then capture</div>
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
    <div class="guide-text">請把名片放滿框線<br/>Fill the frame</div>
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
# ==================================================
if img:
    st.session_state.frame_good = False
    st.session_state.last_msg = "🧠 AI 判斷中…｜Checking…"

    raw_pil = Image.open(img).convert("RGB")
    W, H = raw_pil.size

    with st.spinner("AI checking…"):
        qa, qa_raw = gemini_find_card_corners_and_quality(raw_pil)
        if not qa:
            st.session_state.last_msg = "❌ AI JSON 解析失敗｜Parse failed"
            st.error("❌ AI 回傳格式異常（無法解析 JSON）")
            st.code(qa_raw)
            st.stop()

    ok = bool(qa.get("ok", False))
    reason = str(qa.get("reason", "")).strip()
    corners = qa.get("corners", None)

    if not corners or not isinstance(corners, dict):
        ok = False

    if not ok:
        st.session_state.frame_good = False
        st.session_state.last_msg = "⚠️ 重拍：靠近/置中/避免反光｜Retake: closer/center/avoid glare"
        if reason:
            st.session_state.last_msg += f"（AI：{reason}）"
        if st.button("🔄 Retake｜重拍", use_container_width=True):
            st.session_state.camera_key += 1
            st.rerun()
        st.stop()

    st.session_state.frame_good = True
    st.session_state.last_msg = "🟢 OK！自動裁切校正 → 辨識 → 儲存…｜Auto processing…"

    with st.spinner("Processing…"):
        warped_pil = raw_pil
        warp_ok = False
        try:
            tl = corners.get("tl"); tr = corners.get("tr"); br = corners.get("br"); bl = corners.get("bl")
            if all(isinstance(p, (list, tuple)) and len(p) == 2 for p in [tl, tr, br, bl]):
                pts = np.array([
                    clamp_point(tl, W, H),
                    clamp_point(tr, W, H),
                    clamp_point(br, W, H),
                    clamp_point(bl, W, H),
                ], dtype="float32")
                rgb = np.array(raw_pil.convert("RGB"))
                warped_rgb = four_point_transform_rgb(rgb, pts)
                warped_pil = Image.fromarray(warped_rgb)
                warp_ok = True
        except:
            warp_ok = False

        ocr_img = warped_pil if warp_ok else raw_pil
        info, ocr_raw = extract_info(ocr_img)
        if not info:
            st.session_state.last_msg = "❌ OCR JSON 解析失敗｜OCR parse failed"
            st.error("❌ OCR 回傳格式異常（無法解析 JSON）")
            st.code(ocr_raw)
            st.stop()

        out_img = warped_pil if warp_ok else raw_pil
        buf = BytesIO()
        out_img.save(buf, format="JPEG", quality=92)
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
