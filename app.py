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
# OpenCV: detect card + perspective correction
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

def four_point_transform(image_bgr: np.ndarray, rect: np.ndarray) -> np.ndarray:
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
    warped = cv2.warpPerspective(image_bgr, M, (maxW, maxH))
    return warped

def detect_and_warp_card(pil_img: Image.Image):
    """
    return:
      warped_pil (or original), ok(bool), coverage_ratio(float)
    """
    rgb = np.array(pil_img.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    edged = cv2.Canny(gray, 60, 160)
    edged = cv2.dilate(edged, None, iterations=1)

    contours, _ = cv2.findContours(edged, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return pil_img, False, 0.0

    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:12]

    img_area = float(bgr.shape[0] * bgr.shape[1])
    best = None
    best_area = 0.0

    for c in contours:
        area = cv2.contourArea(c)
        if area < img_area * 0.05:
            continue

        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            if area > best_area:
                best_area = area
                best = approx.reshape(4, 2)

    if best is None:
        return pil_img, False, 0.0

    coverage = best_area / img_area
    rect = order_points(best.astype("float32"))
    warped = four_point_transform(bgr, rect)
    warped_rgb = cv2.cvtColor(warped, cv2.COLOR_BGR2RGB)
    warped_pil = Image.fromarray(warped_rgb)

    # 合理占比門檻（可依你手機畫面微調）
    ok = (coverage >= 0.22) and (coverage <= 0.95)

    return warped_pil, ok, float(coverage)

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
# Main UI
# ==================================================
st.title("📇 Business Card Scanner｜名片掃描")
st.markdown('<div class="panel">', unsafe_allow_html=True)
st.markdown("**拍照前：** 讓名片盡量填滿框線（越滿越準）  \n**Before capture:** Fill the frame with the card for best OCR.")
st.markdown('<span class="badge">Mobile-friendly • Touch UI • Simple</span>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

creds = get_oauth_creds()

st.markdown('<div class="panel">', unsafe_allow_html=True)
st.subheader("📸 Take Photo｜拍攝")

st.markdown('<div class="camera-wrap">', unsafe_allow_html=True)
img = st.camera_input(
    "Take photo｜拍照",
    key=f"cam_{st.session_state.camera_key}",
    label_visibility="collapsed"
)

frame_class = "guide good" if st.session_state.frame_good else "guide"
st.markdown(f"""
<div class="{frame_class}"></div>
<div class="guide-text">
請把名片放滿框線<br/>Place the card inside the frame
</div>
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="big-note">拍完後會自動裁切＋校正，再送 AI 辨識並寫入表單。<br/>After capture: auto crop + deskew, then OCR and save.</div>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

# ==================================================
# After capture: crop + deskew + green animation + touch CTA
# ==================================================
if img:
    st.session_state.frame_good = False

    raw_pil = Image.open(img).convert("RGB")
    warped_pil, ok, coverage = detect_and_warp_card(raw_pil)
    st.session_state.frame_good = bool(ok)

    st.markdown('<div class="panel">', unsafe_allow_html=True)
    if ok:
        st.success(f"✅ 距離良好｜Good distance  (card coverage: {coverage:.0%})")
    else:
        st.warning(f"⚠️ 建議再靠近一點或置中｜Move closer / center the card  (coverage: {coverage:.0%})")

    st.write("🖼️ Crop Preview｜裁切預覽")
    st.image(warped_pil, use_container_width=True)

    st.markdown('<hr class="soft"/>', unsafe_allow_html=True)
    col1, col2 = st.columns([1, 1])
    with col1:
        proceed = st.button("✅ Process & Save｜辨識並儲存", type="primary", use_container_width=True)
    with col2:
        retry = st.button("🔄 Retake｜重拍", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

    if retry:
        st.session_state.camera_key += 1
        st.session_state.frame_good = False
        st.rerun()

    if proceed:
        with st.spinner("🤖 OCR & Saving｜辨識與儲存中..."):
            info, raw_text = extract_info(warped_pil)
            if not info:
                st.error("❌ AI 回傳格式異常，無法解析 JSON｜Failed to parse AI JSON")
                st.code(raw_text)
                st.stop()

            buf = BytesIO()
            warped_pil.save(buf, format="JPEG", quality=92)
            img_bytes = buf.getvalue()

            try:
                link = upload_drive(img_bytes, f"card_{int(time.time())}.jpg", creds)
            except HttpError as e:
                st.error("❌ Google Drive 上傳失敗｜Drive upload failed")
                status = getattr(e.resp, "status", "unknown")
                content = e.content.decode("utf-8", errors="ignore") if getattr(e, "content", None) else str(e)
                st.code(f"HTTP {status}\n{content[:2000]}")
                st.stop()

            try:
                save_sheet(info, link, creds)
            except Exception as e:
                st.error("❌ Google Sheets 寫入失敗｜Sheets write failed")
                st.code(str(e))
                st.stop()

        st.success("✅ 完成｜Saved Successfully")
        st.balloons()
        st.session_state.camera_key += 1
        st.session_state.frame_good = False
        time.sleep(1.0)
        st.rerun()
