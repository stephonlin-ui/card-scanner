import streamlit as st
import google.generativeai as genai
import pandas as pd
from PIL import Image
import json
import time
import os

# --- 設定頁面 ---
st.set_page_config(page_title="展覽名片小幫手", page_icon="📇")

# --- 隱藏 Streamlit 介面 ---
hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# --- 1. 設定與讀取 API Key (新增防呆機制) ---
try:
    # 這裡加了 .strip()，如果您複製時不小心多複製了空白鍵，程式會自動刪掉
    api_key = st.secrets["GEMINI_API_KEY"].strip()
    genai.configure(api_key=api_key)
except Exception as e:
    st.error(f"⚠️ API Key 設定有誤，請檢查 Secrets 設定。錯誤訊息: {e}")

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
        # 如果檔案壞掉，重新建立
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

# --- AI 辨識函式 (改回標準模型名稱) ---
def extract_info(image):
    try:
        # 使用最穩定的標準名稱
        model = genai.GenerativeModel('gemini-1.5-flash')
        
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
        
        # 清理 JSON 格式
        if text.startswith("```json"):
            text = text[7:-3]
        elif text.startswith("```"):
            text = text[3:-3]
            
        return json.loads(text)
    except Exception as e:
        # 如果出錯，印出錯誤到畫面上方便除錯
        st.error(f"辨識失敗: {e}")
        return None

# --- 管理員後台 ---
with st.sidebar:
    st.header("管理員專區")
    pwd = st.text_input("密碼", type="password")
    if pwd == "admin123":
        if os.path.exists(CSV_FILE):
            with open(CSV_FILE, "rb") as f:
                st.download_button(
                    label="📥 下載名片資料",
                    data=f,
                    file_name="visitors_data.csv",
                    mime="text/csv"
                )
            st.dataframe(pd.read_csv(CSV_FILE))

# --- 主畫面 ---
st.title("📇 歡迎參觀！")
st.write("請拍攝名片，系統將自動為您建檔。")

img_file = st.camera_input("點擊下方按鈕拍照", label_visibility="hidden")

if img_file:
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
