import streamlit as st
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from PIL import Image
import json
import time

# --- 設定頁面 ---
st.set_page_config(page_title="雲端名片系統 (2.5 Pro)", page_icon="🚀")
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
        # 檢查是否已設定機器人 Secrets
        if "gcp_service_account" not in st.secrets:
            st.warning("⚠️ 尚未設定 Google Cloud 機器人鑰匙，資料僅顯示於螢幕。")
            return False

        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        
        # 修正 Private Key 換行問題
        if "\\n" in creds_dict["private_key"]:
             creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        # 開啟試算表
        try:
            sheet = client.open("Business_Cards_Data").sheet1
        except:
            # 找不到就嘗試建立
            try:
                sh = client.create("Business_Cards_Data")
                sh.share(st.secrets["gcp_service_account"]["client_email"], perm_type='user', role='writer')
                sheet = sh.sheet1
                sheet.append_row(["拍攝時間", "姓名", "職稱", "公司", "電話", "Email", "地址"])
            except Exception as create_error:
                st.error(f"無法開啟試算表，請確認您已建立名為 'Business_Cards_Data' 的檔案。錯誤: {create_error}")
                return False

        # 寫入資料
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

# --- 3. AI 辨識邏輯 (使用最新 2.5 Flash) ---
def extract_info(image):
    # 指定您清單中最新的 2.5 版本
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
        
        if text.startswith("```json"):
            text = text[7:-3]
        elif text.startswith("```"):
            text = text[3:-3]
            
        return json.loads(text)
        
    except Exception as e:
        error_msg = str(e)
        st.error(f"辨識錯誤 ({target_model}): {error_msg}")
        
        # 如果 2.5 發生 429 (限速) 或 404，自動降級到 2.0 Lite 以保證運作
        if "429" in error_msg or "404" in error_msg:
            try:
                st.warning("⚠️ 2.5 版忙碌中，自動切換至 2.0 Lite 備援...")
                fallback_model = genai.GenerativeModel("models/gemini-2.0-flash-lite")
                response = fallback_model.generate_content([prompt, image])
                text = response.text.strip()
                if text.startswith("```json"): text = text[7:-3]
                return json.loads(text)
            except:
                return None
        return None

# --- 主畫面 ---
st.title("🚀 雲端名片系統 (Pro)")
st.write("使用最新 Gemini 2.5 引擎 + Google Sheets")
st.caption("System v10.0 (Model: 2.5-Flash)") 

img_file = st.camera_input("點擊下方按鈕拍照", label_visibility="hidden")

if img_file:
    with st.spinner('🚀 正在使用 Gemini 2.5 極速辨識...'):
        image = Image.open(img_file)
        info = extract_info(image)
        
        if info:
            st.success(f"辨識成功：{info.get('name')} / {info.get('company')}")
            st.info("正在上傳 Google Sheets...")
            
            # 嘗試寫入 Google Sheets
            success = save_to_google_sheets(info)
            
            if success:
                st.balloons()
                st.success("✅ 資料已成功寫入雲端試算表！")
            else:
                st.warning("⚠️ 辨識成功但寫入失敗 (請檢查 Secrets 設定)")
            
            st.write("畫面將在 2 秒後重置...")
            time.sleep(2)
            st.rerun()
