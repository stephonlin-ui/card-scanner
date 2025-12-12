import streamlit as st
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from PIL import Image
import json
import time

# --- 設定頁面 ---
st.set_page_config(page_title="雲端名片系統 (Google Drive版)", page_icon="📂")
hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# 初始化相機 Key (防重複)
if 'camera_key' not in st.session_state:
    st.session_state.camera_key = 0

# --- 1. 設定 Gemini API ---
try:
    if "GEMINI_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"].strip())
    else:
        st.error("⚠️ 未設定 GEMINI_API_KEY")
except Exception as e:
    st.error(f"⚠️ API Key 設定錯誤: {e}")

# --- 共用憑證函式 ---
def get_creds():
    if "gcp_service_account" not in st.secrets:
        return None
    creds_dict = dict(st.secrets["gcp_service_account"])
    if "\\n" in creds_dict["private_key"]:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    
    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)

# --- 2. 上傳圖片到 Google Drive (指定資料夾) ---
def upload_image_to_drive(image_file, file_name):
    try:
        creds = get_creds()
        if not creds: return "無憑證"

        # 檢查是否有設定資料夾 ID
        if "DRIVE_FOLDER_ID" not in st.secrets:
            return "錯誤：未設定 DRIVE_FOLDER_ID (請在 Secrets 新增)"
        
        folder_id = st.secrets["DRIVE_FOLDER_ID"]
        service = build('drive', 'v3', credentials=creds)
        
        # 設定檔案元數據 (關鍵：parents 指定資料夾ID，解決空間不足問題)
        file_metadata = {
            'name': file_name,
            'mimeType': 'image/jpeg',
            'parents': [folder_id] 
        }
        
        # 準備上傳
        image_file.seek(0)
        media = MediaIoBaseUpload(image_file, mimetype='image/jpeg', resumable=True)
        
        # 執行上傳
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        file_id = file.get('id')
        link = file.get('webViewLink')
        
        # 設定權限為「知道連結者可檢視」(避免點連結看圖片時需要登入機器人)
        try:
            service.permissions().create(
                fileId=file_id, 
                body={'type': 'anyone', 'role': 'reader'}
            ).execute()
        except:
            pass 
            
        return link

    except Exception as e:
        # 如果還是失敗，回傳詳細錯誤
        return f"上傳失敗: {str(e)}"

# --- 3. 寫入 Google Sheets ---
def save_to_google_sheets(data_dict, image_file):
    try:
        creds = get_creds()
        if not creds:
            st.warning("⚠️ 尚未設定機器人鑰匙")
            return False

        client = gspread.authorize(creds)
        
        # 上傳圖片
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        file_name = f"Card_{data_dict.get('name')}_{timestamp}.jpg"
        
        image_link = "上傳中..."
        with st.spinner('📂 正在備份照片到 Google Drive...'):
            image_link = upload_image_to_drive(image_file, file_name)
            if "上傳失敗" in image_link:
                st.error(image_link) # 顯示錯誤但不中斷流程

        # 寫入 Sheet
        try:
            sheet = client.open("Business_Cards_Data").sheet1
        except:
            sh = client.create("Business_Cards_Data")
            sh.share(st.secrets["gcp_service_account"]["client_email"], perm_type='user', role='writer')
            sheet = sh.sheet1
            sheet.append_row(["拍攝時間", "姓名", "職稱", "公司", "電話", "Email", "地址", "照片連結"])

        row = [
            timestamp,
            data_dict.get('name', ''),
            data_dict.get('title', ''),
            data_dict.get('company', ''),
            data_dict.get('phone', ''),
            data_dict.get('email', ''),
            data_dict.get('address', ''),
            image_link
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"寫入失敗: {e}")
        return False

# --- 4. AI 辨識 ---
def extract_info(image):
    target_model = "models/gemini-2.5-flash"
    try:
        model = genai.GenerativeModel(target_model)
        prompt = "請辨識名片資訊並輸出 JSON: {name, title, company, phone, email, address}"
        response = model.generate_content([prompt, image])
        text = response.text.strip()
        if text.startswith("```json"): text = text[7:-3]
        elif text.startswith("```"): text = text[3:-3]
        return json.loads(text)
    except:
        try:
             # 備援
             fallback = genai.GenerativeModel("models/gemini-2.0-flash-lite")
             response = fallback.generate_content([prompt, image])
             text = response.text.strip()
             if text.startswith("```json"): text = text[7:-3]
             return json.loads(text)
        except:
             return None

# --- 主畫面 ---
st.title("📂 雲端名片系統 (Drive版)")
st.caption("System v15.0 (Folder Fixed)")

# 使用 key 機制防止重複上傳
img_file = st.camera_input("拍照", label_visibility="hidden", key=f"camera_{st.session_state.camera_key}")

if img_file:
    image = Image.open(img_file)
    with st.spinner('🚀 處理中...'):
        info = extract_info(image)
        if info:
            st.info(f"辨識成功：{info.get('name')}")
            success = save_to_google_sheets(info, img_file)
            if success:
                st.balloons()
                st.success("✅ 建檔完成！")
                st.session_state.camera_key += 1
                time.sleep(2)
                st.rerun()
