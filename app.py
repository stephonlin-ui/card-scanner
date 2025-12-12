import streamlit as st
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from PIL import Image
import json
import time

# --- 設定頁面 ---
st.set_page_config(page_title="雲端名片系統 (存證版)", page_icon="📸")
hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# --- 初始化相機 Key ---
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

# --- 2. 上傳圖片到 Google Drive ---
def upload_image_to_drive(image_file, file_name, creds):
    try:
        # 建立 Drive 服務
        service = build('drive', 'v3', credentials=creds)
        
        # 設定檔案元數據
        file_metadata = {
            'name': file_name,
            'mimeType': 'image/jpeg'
        }
        
        # 準備上傳 (重置檔案指標)
        image_file.seek(0)
        media = MediaIoBaseUpload(image_file, mimetype='image/jpeg', resumable=True)
        
        # 執行上傳
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        file_id = file.get('id')
        web_view_link = file.get('webViewLink')
        
        # --- 關鍵：設定權限為「知道連結者可檢視」 ---
        # 這樣您在試算表中點擊連結時，才不會出現「存取被拒」
        permission = {
            'type': 'anyone',
            'role': 'reader',
        }
        service.permissions().create(fileId=file_id, body=permission).execute()
        
        return web_view_link
    except Exception as e:
        st.error(f"圖片上傳失敗: {e}")
        return "上傳失敗"

# --- 3. 設定 Google Sheets 連線與寫入 ---
def save_to_google_sheets(data_dict, image_file):
    try:
        if "gcp_service_account" not in st.secrets:
            st.warning("⚠️ 尚未設定 Google Cloud 機器人鑰匙")
            return False

        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        
        if "\\n" in creds_dict["private_key"]:
             creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        # --- 先處理圖片上傳 ---
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        file_name = f"Card_{data_dict.get('name')}_{timestamp}.jpg"
        
        with st.spinner('📸 正在備份原始照片到雲端...'):
            image_link = upload_image_to_drive(image_file, file_name, creds)

        # --- 再處理試算表寫入 ---
        try:
            sheet = client.open("Business_Cards_Data").sheet1
        except:
            try:
                sh = client.create("Business_Cards_Data")
                sh.share(st.secrets["gcp_service_account"]["client_email"], perm_type='user', role='writer')
                sheet = sh.sheet1
                # 新增標題，包含照片連結
                sheet.append_row(["拍攝時間", "姓名", "職稱", "公司", "電話", "Email", "地址", "原始照片連結"])
            except Exception as create_error:
                st.error(f"無法開啟試算表: {create_error}")
                return False

        row = [
            timestamp,
            data_dict.get('name', ''),
            data_dict.get('title', ''),
            data_dict.get('company', ''),
            data_dict.get('phone', ''),
            data_dict.get('email', ''),
            data_dict.get('address', ''),
            image_link  # 這是最後一欄：照片連結
        ]
        
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"寫入失敗: {e}")
        return False

# --- 4. AI 辨識邏輯 ---
def extract_info(image):
    target_model = "models/gemini-2.5-flash"
    try:
        model = genai.GenerativeModel(target_model)
        prompt = """
        你是一個名片辨識專家。請分析這張名片圖片，並擷取以下資訊，輸出成純 JSON 格式：
        {
            "name": "姓名",
            "title": "職稱",
            "company": "公司名稱",
            "phone": "電話號碼(優先抓取手機)",
            "email": "Email",
            "address": "地址"
        }
        如果某個欄位找不到，請留空字串。不要輸出 JSON 以外的任何文字。
        """
        response = model.generate_content([prompt, image])
        text = response.text.strip()
        if text.startswith("```json"): text = text[7:-3]
        elif text.startswith("```"): text = text[3:-3]
        return json.loads(text)
    except Exception as e:
        try:
             fallback = genai.GenerativeModel("models/gemini-2.0-flash-lite")
             response = fallback.generate_content([prompt, image])
             text = response.text.strip()
             if text.startswith("```json"): text = text[7:-3]
             return json.loads(text)
        except:
             return None

# --- 主畫面 ---
st.title("📸 雲端名片系統")
st.write("自動辨識 + 原始圖檔備份")
st.caption("System v12.0 (Image Upload Support)")

img_file = st.camera_input("點擊下方按鈕拍照", label_visibility="hidden", key=f"camera_{st.session_state.camera_key}")

if img_file:
    # 讀取圖片給 AI 用
    image = Image.open(img_file)
    
    with st.spinner('🚀 AI 辨識中...'):
        info = extract_info(image)
        
        if info:
            st.info(f"辨識成功：{info.get('name')}，正在上傳照片與資料...")
            
            # 將原始檔案傳入，以便上傳
            success = save_to_google_sheets(info, img_file)
            
            if success:
                st.balloons()
                st.success(f"✅ 資料與照片已存檔！")
                st.session_state.camera_key += 1
                time.sleep(2)
                st.rerun()
            else:
                st.error("寫入失敗，請重試")
