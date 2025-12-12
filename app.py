import streamlit as st
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from PIL import Image
import json
import time

# --- 設定頁面 ---
st.set_page_config(page_title="雲端名片系統 (防重複版)", page_icon="🛡️")
hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# --- 關鍵修正：初始化相機的 Key ---
# 我們利用這個 Key 來強制重置相機元件，防止無限迴圈
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

# --- 2. 設定 Google Sheets 連線 ---
def save_to_google_sheets(data_dict):
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
        
        try:
            sheet = client.open("Business_Cards_Data").sheet1
        except:
            try:
                sh = client.create("Business_Cards_Data")
                sh.share(st.secrets["gcp_service_account"]["client_email"], perm_type='user', role='writer')
                sheet = sh.sheet1
                sheet.append_row(["拍攝時間", "姓名", "職稱", "公司", "電話", "Email", "地址"])
            except Exception as create_error:
                st.error(f"無法開啟試算表: {create_error}")
                return False

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        row = [
            timestamp,
            data_dict.get('name', ''),
            data_dict.get('title', ''),
            data_dict.get('company', ''),
            data_dict.get('phone', ''),
            data_dict.get('email', ''),
            data_dict.get('address', '')
        ]
        
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"寫入失敗: {e}")
        return False

# --- 3. AI 辨識邏輯 ---
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
        # 自動備援機制
        try:
             fallback = genai.GenerativeModel("models/gemini-2.0-flash-lite")
             response = fallback.generate_content([prompt, image])
             text = response.text.strip()
             if text.startswith("```json"): text = text[7:-3]
             return json.loads(text)
        except:
             return None

# --- 主畫面 ---
st.title("🛡️ 雲端名片系統")
st.write("已啟用防重複發送機制")
st.caption("System v11.0 (No-Loop Fix)")

# 關鍵：給 camera_input 一個變動的 key
# 當 key 改變時，相機元件會被「銷毀並重建」，藉此清除裡面的照片
img_file = st.camera_input("點擊下方按鈕拍照", label_visibility="hidden", key=f"camera_{st.session_state.camera_key}")

if img_file:
    with st.spinner('🚀 處理中...'):
        image = Image.open(img_file)
        info = extract_info(image)
        
        if info:
            st.info("正在上傳...")
            success = save_to_google_sheets(info)
            
            if success:
                st.balloons()
                st.success(f"✅ 成功寫入：{info.get('name')}")
                
                # --- 關鍵修正：這裡做兩件事 ---
                # 1. 更改 Key 的值，確保下次重啟時相機是乾淨的
                st.session_state.camera_key += 1
                
                # 2. 等待 2 秒讓用戶看清楚
                time.sleep(2)
                
                # 3. 重新整理頁面 (這時因為 Key 變了，相機內容會被清空)
                st.rerun()
            else:
                st.error("寫入失敗，請重試")
