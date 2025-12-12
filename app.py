import streamlit as st
import google.generativeai as genai
import pandas as pd
from PIL import Image
import json
import time
import os

# --- 設定頁面 ---
st.set_page_config(page_title="展覽名片小幫手", page_icon="📇")
hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# --- 讀取 API Key ---
try:
    api_key = st.secrets["GEMINI_API_KEY"].strip()
    genai.configure(api_key=api_key)
except Exception as e:
    st.error(f"⚠️ API Key 設定有誤: {e}")

# --- CSV 檔案路徑 ---
CSV_FILE = "business_cards.csv"

# --- 儲存資料函式 ---
def save_to_csv(data_dict):
    if not os.path.exists(CSV_FILE):
        df = pd.DataFrame(columns=["姓名", "職稱", "公司", "電話", "Email", "地址"])
        df.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")
    
    try:
        df = pd.read_csv(CSV_FILE)
    except:
        df = pd.DataFrame(columns=["姓名", "職稱", "公司", "電話", "Email", "地址"])

    new_row = {
        "姓名": data_dict.get('name', ''),
        "職稱": data_dict.get('title', ''),
        "公司": data_dict.get('company', ''),
        "電話": data_dict.get('phone', ''),
        "Email": data_dict.get('email', ''),
        "地址": data_dict.get('address', '')
    }
    
    new_df = pd.DataFrame([new_row])
    df = pd.concat([df, new_df], ignore_index=True)
    df.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")
    return True

# --- 關鍵修正：自動尋找可用模型 ---
def find_valid_model():
    try:
        # 列出所有可用模型
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
        # 優先尋找 flash (速度快且免費)
        for model_name in available_models:
            if "flash" in model_name and "1.5" in model_name:
                return model_name
        
        # 如果沒有 flash，找 pro
        for model_name in available_models:
            if "pro" in model_name and "1.5" in model_name:
                return model_name
                
        # 如果都沒有，就回傳抓到的第一個
        if available_models:
            return available_models[0]
            
        return None
    except Exception as e:
        st.error(f"連線 Google 失敗，請檢查 API Key 是否正確。錯誤: {e}")
        return None

# --- AI 辨識函式 ---
def extract_info(image):
    # 1. 自動取得正確的模型名稱
    model_name = find_valid_model()
    
    if not model_name:
        st.error("❌ 找不到任何可用的 AI 模型，請檢查 API Key 權限。")
        return None
        
    # 2. 開始辨識
    try:
        # st.toast(f"使用模型: {model_name}") # (除錯用，顯示當前使用的模型)
        model = genai.GenerativeModel(model_name)
        
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
        st.error(f"辨識過程發生錯誤 ({model_name}): {e}")
        return None

# --- 管理員後台 ---
with st.sidebar:
    st.header("管理員專區")
    pwd = st.text_input("密碼", type="password")
    if pwd == "admin123":
        if os.path.exists(CSV_FILE):
            with open(CSV_FILE, "rb") as f:
                st.download_button("📥 下載名片資料", f, "visitors_data.csv", "text/csv")
            st.dataframe(pd.read_csv(CSV_FILE))
        
        # 除錯區：顯示目前抓到的模型清單
        if st.button("檢測可用模型"):
             try:
                models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                st.write("您的 API Key 可用模型清單：", models)
             except Exception as e:
                st.error(f"檢測失敗: {e}")

# --- 主畫面 ---
st.title("📇 歡迎參觀！")
st.write("請拍攝名片，系統將自動為您建檔。")

img_file = st.camera_input("點擊下方按鈕拍照", label_visibility="hidden")

if img_file:
    with st.
