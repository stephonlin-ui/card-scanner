import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.auth.transport.requests import Request
from PIL import Image
from io import BytesIO
import json
import time
import gspread

# --- Settings / Scopes ---
SCOPES = [
    "https://www.googleapis.com/auth/drive.file",   # 允許上傳/管理應用建立的檔案（適合個人應用）
    "https://www.googleapis.com/auth/spreadsheets"  # 若要寫入 Sheets
]

# 從 streamlit secrets 讀取 client config
if "google_oauth" not in st.secrets:
    st.error("請先在 Streamlit secrets 填入 google_oauth.client_id 與 client_secret")
    st.stop()

client_id = st.secrets["google_oauth"]["client_id"]
client_secret = st.secrets["google_oauth"]["client_secret"]
redirect_uri = st.secrets["google_oauth"].get("redirect_uri", "http://localhost:8501/")

CLIENT_CONFIG = {
    "web": {
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [redirect_uri]
    }
}

st.set_page_config(page_title="OAuth Drive Upload Example")

def get_flow(state=None):
    flow = Flow.from_client_config(
        CLIENT_CONFIG,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    return flow

def ensure_credentials():
    # 如果 session 有 credentials，檢查是否過期或可刷新
    creds = st.session_state.get("credentials")
    if creds:
        creds = Credentials.from_authorized_user_info(json.loads(creds), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            st.session_state["credentials"] = creds.to_json()
        return creds

    # 如果 URL 上有 code（被 redirect 回來），交換 token
    params = st.experimental_get_query_params()
    if "code" in params:
        code = params["code"][0]
        state = params.get("state", [None])[0]
        flow = get_flow(state=state)
        try:
            flow.fetch_token(code=code)
            creds = flow.credentials
            st.session_state["credentials"] = creds.to_json()
            # 清掉 query params（避免重複）
            st.experimental_set_query_params()
            return creds
        except Exception as e:
            st.error(f"授權交換 token 失敗: {e}")
            return None

    return None

def start_oauth_flow():
    flow = get_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )
    # 保存 state 以作驗證（可選）
    st.session_state["oauth_state"] = state
    st.markdown(f"[點此用 Google 帳號授權]({auth_url})")

def build_drive_service(creds):
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def upload_image_to_drive_with_oauth(image_bytes, file_name, creds):
    service = build_drive_service(creds)
    media = MediaIoBaseUpload(BytesIO(image_bytes), mimetype="image/jpeg")
    file_metadata = {"name": file_name}
    file = service.files().create(body=file_metadata, media_body=media, fields="id,webViewLink").execute()
    return file.get("webViewLink")

def save_to_sheets_with_oauth(data_dict, image_link, creds):
    # 使用 gspread + oauth credentials
    gc = gspread.authorize(creds)
    try:
        sh = gc.open("Business_Cards_Data")
    except gspread.SpreadsheetNotFound:
        sh = gc.create("Business_Cards_Data")
        # 分享給自己（已授權的帳戶）是必要的嗎？通常不需要
    ws = sh.sheet1
    # 如果是新建立的表，第一次加入 header
    if ws.row_count == 0 or ws.get_all_values() == []:
        ws.append_row(["拍攝時間", "姓名", "職稱", "公司", "電話", "Email", "地址", "照片連結"])
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    row = [
        timestamp,
        data_dict.get("name",""),
        data_dict.get("title",""),
        data_dict.get("company",""),
        data_dict.get("phone",""),
        data_dict.get("email",""),
        data_dict.get("address",""),
        image_link
    ]
    ws.append_row(row)

# --- UI ---
st.title("📷 使用 OAuth 上傳到個人 Google Drive (方案 A)")
st.caption("第一次會跳 Google 授權頁面（同一瀏覽器）")

creds = ensure_credentials()
if not creds:
    st.info("請先授權應用存取您的 Google Drive / Sheets")
    start_oauth_flow()
    st.stop()

# 到這裡已取得 creds（google.oauth2.credentials.Credentials 物件）
# 範例相機輸入（你原本用的 camera_input）
img_file = st.camera_input("拍照", label_visibility="hidden")

if img_file:
    img_bytes = img_file.getvalue()
    # 你可以用 PIL 顯示
    image = Image.open(BytesIO(img_bytes))
    st.image(image, use_column_width=True)

    with st.spinner("上傳圖片到你自己的 Google Drive..."):
        try:
            fname = f"Card_{int(time.time())}.jpg"
            link = upload_image_to_drive_with_oauth(img_bytes, fname, creds)
            st.success("上傳成功！")
            st.write("檔案連結：", link)

            # 如果你也要存到 Sheets
            # 範例假資料（請改成你 extract_info 的結果）
            data_dict = {"name":"測試","title":"職稱","company":"公司","phone":"09xx","email":"a@b.com","address":"地址"}
            save_to_sheets_with_oauth(data_dict, link, creds)

        except Exception as e:
            st.error(f"上傳失敗: {e}")
