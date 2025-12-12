import streamlit as st
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from PIL import Image
import json
import time

# --- 設定頁面 ---
st.set_page_config(page_title="展覽名片小幫手 (Cloud)", page_icon="☁️")
hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

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
        # 定義連線範圍
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        
        # 從 Secrets 讀取機器人憑證
        creds_dict = dict(st.secrets["gcp_service_account"])
        
        # 處理 private_key 的換行問題 (有時候複製貼上會跑掉)
        if "\\n" in creds_dict["private_key"]:
             creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        # --- 重要：請在這裡輸入您的 Google 試算表名稱 ---
        # 建議直接貼上試算表的「網址」最保險，或者確保檔名完全一致
        # 這裡示範用「開新檔案」的方式，如果找不到檔案會自動建立一個
        try:
            sheet = client.open("Business_Cards_Data").sheet1
        except:
            # 如果找不到，就開一個新的
            sh = client.create("Business_Cards_Data")
            sh.share(st.secrets["gcp_service_account"]["client_email"], perm_type='user', role='writer')
            sheet = sh.sheet1
            # 寫入標題列
            sheet.append_row(["拍攝時間", "姓名", "職稱", "公司", "電話", "Email", "地址"])

        # 準備寫入資料
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
        st.error(f"寫入 Google Sheets 失敗: {e}")
        return False

# --- 3. AI 辨識邏輯 (付費穩定版) ---
def extract_info(image):
    target_model = "gemini-1.5-flash"
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
        st.error(f"辨識錯誤: {e}")
        return None

# --- 主畫面 ---
st.title("☁️ 雲端名片系統")
st.write("拍攝後將直接匯入 Google 試算表。")
st.caption("System v8.0 (Google Sheets Connected)") 

img_file = st.camera_input("點擊下方按鈕拍照", label_visibility="hidden")

if img_file:
    with st.spinner('☁️ 正在辨識並上傳雲端...'):
        image = Image.open(img_file)
        info = extract_info(image)
        
        if info:
            st.info(f"嗨，{info.get('name')}！正在寫入 Google Sheets...")
            success = save_to_google_sheets(info)
            
            if success:
                st.balloons()
                st.success("✅ 資料已成功存入雲端！")
                st.write("畫面將在 2 秒後重置...")
                time.sleep(2)
                st.rerun()
            else:
                st.error("❌ 存檔失敗，請通知工作人員")
