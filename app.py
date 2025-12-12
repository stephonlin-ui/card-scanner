import streamlit as st
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from PIL import Image
import json
import time
from io import BytesIO

# --- 設定頁面 ---
st.set_page_config(page_title="雲端名片系統 (v17.0)", page_icon="🕵️")
hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

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

# --- 2. 智慧型憑證與ID讀取 (v17.0 核心修正) ---
def get_creds_and_folder():
    # 1. 先找憑證
    if "gcp_service_account" not in st.secrets:
        return None, None
    
    creds_dict = dict(st.secrets["gcp_service_account"])
    if "\\n" in creds_dict["private_key"]:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    
    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)

    # 2. 再找 Folder ID (不管藏在哪裡都把它挖出來)
    folder_id = None
    
    # 情況 A: ID 在最外層
    if "DRIVE_FOLDER_ID" in st.secrets:
        folder_id = st.secrets["DRIVE_FOLDER_ID"]
        
    # 情況 B: ID 不小心被貼在 gcp_service_account 裡面
    elif "DRIVE_FOLDER_ID" in creds_dict:
        folder_id = creds_dict["DRIVE_FOLDER_ID"]
        
    return creds, folder_id

# --- 3. 上傳圖片到 Google Drive ---
def upload_image_to_drive(image_bytes, file_name):
    try:
        creds, folder_id = get_creds_and_folder()
        
        if not creds: return "錯誤：無憑證"
        if not folder_id: return "錯誤：找不到 DRIVE_FOLDER_ID (請檢查 Secrets)"

        # --- 偵錯模式：讓您看到程式讀到了什麼 ---
        # st.write(f"正在上傳到資料夾 ID: {folder_id}") 

        service = build('drive', 'v3', credentials=creds)
        
        file_metadata = {
            'name': file_name,
            'mimeType': 'image/jpeg',
            'parents': [folder_id] # 這行最重要，指定父母資料夾
        }
        
        media_stream = BytesIO(image_bytes)
        media = MediaIoBaseUpload(media_stream, mimetype='image/jpeg', resumable=True)
        
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        file_id = file.get('id')
        link = file.get('webViewLink')
        
        try:
            service.permissions().create(
                fileId=file_id, 
                body={'type': 'anyone', 'role': 'reader'}
            ).execute()
        except:
            pass
            
        return link

    except Exception as e:
        error_msg = str(e)
        if "Storage quota" in error_msg:
             return f"空間錯誤: 機器人無法存取資料夾 ID ({folder_id})，請確認該資料夾已共用給機器人。"
        return f"上傳失敗: {error_msg}"

# --- 4. 寫入 Google Sheets ---
def save_to_google_sheets(data_dict, image_bytes):
    try:
        creds, folder_id = get_creds_and_folder()
        if not creds:
            st.warning("⚠️ 尚未設定機器人鑰匙")
            return False

        client = gspread.authorize(creds)
        
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        file_name = f"Card_{data_dict.get('name')}_{timestamp}.jpg"
        
        image_link = ""
        # 顯示目前的 ID 狀態，讓您安心
        st.caption(f"ℹ️ 目標資料夾 ID: {folder_id if folder_id else '未偵測到'}")
        
        with st.spinner('💾 正在備份照片...'):
            image_link = upload_image_to_drive(image_bytes, file_name)
            
            if "錯誤" in image_link or "失敗" in image_link:
                st.error(f"❌ {image_link}")
                return False

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

# --- 5. AI 辨識 ---
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
             fallback = genai.GenerativeModel("models/gemini-2.0-flash-lite")
             response = fallback.generate_content([prompt, image])
             text = response.text.strip()
             if text.startswith("```json"): text = text[7:-3]
             return json.loads(text)
        except:
             return None

# --- 主畫面 ---
st.title("📂 雲端名片系統")
st.caption("System v17.0 (ID Auto-Finder)")

img_file = st.camera_input("拍照", label_visibility="hidden", key=f"camera_{st.session_state.camera_key}")

if img_file:
    img_bytes = img_file.getvalue() 
    image = Image.open(img_file)
    
    with st.spinner('🚀 處理中...'):
        info = extract_info(image)
        if info:
            st.info(f"辨識成功：{info.get('name')}")
            success = save_to_google_sheets(info, img_bytes)
            
            if success:
                st.balloons()
                st.success("✅ 建檔完成！")
                st.session_state.camera_key += 1
                time.sleep(2)
                st.rerun()
