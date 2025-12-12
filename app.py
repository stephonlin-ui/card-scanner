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
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"].strip()
        genai.configure(api_key=api_key)
    else:
        st.warning("⚠️ 尚未設定 API Key，請至 Secrets 設定")
except Exception as e:
    st.error(f"⚠️ API Key 設定錯誤: {e}")

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

# --- 自動尋找可用模型函式 ---
def find_valid_model():
    try:
        # 列出所有支援 generateContent 的模型
        valid_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                valid_models.append(m.name)
        
        # 1. 優先找 Flash 版本 (快且免費)
        for m in valid_models:
            if "flash" in m and "1.5" in m:
                return m
        
        # 2. 其次找 Pro 版本
        for m in valid_models:
            if "pro" in m and "1.5" in m:
                return m
                
        # 3. 如果都沒有，回傳第一個抓到的
        if valid_models:
            return valid_models[0]
            
        return None
    except Exception as e:
        # 如果連 list_models 都失敗，通常是 Key 有問題
        return None

# --- AI 辨識函式 ---
def extract_info(image):
    # 自動抓取模型名稱
    model_name = find_valid_model()
    
    # 如果抓不到模型，強迫使用一個預設值試試看
    if not model_name:
        model_name = "models/gemini-1.5-flash"
        
    try:
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
        st.error(f"辨識失敗 (使用模型: {model_name}): {e}")
        return None

# --- 管理員後台 (側邊欄) ---
with st.sidebar:
    st.header("管理員專區")
    pwd = st.text_input("密碼", type="password")
    if pwd == "admin123":
        if os.path.exists(CSV_FILE):
            with open(CSV_FILE, "rb") as f:
                st.download_button("📥 下載名片資料", f, "visitors_data.csv", "text/csv")
            st.write("---")
            st.write("資料預覽：")
            st.dataframe(pd.read_csv(CSV_FILE))
        
        if st.button("檢測模型連線"):
            try:
                models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                st.success(f"連線成功！可用模型: {models}")
            except Exception as e:
                st.error(f"連線失敗: {e}")

# --- 主畫面 ---
st.title("📇 歡迎參觀！")
st.write("請拍攝名片，系統將自動為您建檔。")

img_file = st.camera_input("點擊下方按鈕拍照", label_visibility="hidden")

if img_file:
    # 這裡就是剛才出錯的地方，請確保這行完整
    with st.spinner('🤖 正在讀取名片資料...'):
        image = Image.open(img_file)
        info = extract_info(image)
        
        if info:
            st.info(f"嗨，{info.get('name')}！資料儲存中...")
            save_to_csv(info)
            st.balloons()
            st.success("✅ 建檔成功！")
            st.write("畫面將在 3 秒後自動重置...")
            time.sleep(3)
            st.rerun()
        else:
            st.error("無法辨識，請再試一次。")
