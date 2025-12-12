import streamlit as st
import google.generativeai as genai
import pandas as pd
from PIL import Image
import json
import time
import os

# --- 設定頁面 ---
st.set_page_config(page_title="展覽名片小幫手", page_icon="📇")

# --- 隱藏 Streamlit 預設介面 ---
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
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
except:
    st.warning("⚠️ 請先在 Streamlit 後台設定 GEMINI_API_KEY")

# --- CSV 檔案路徑 ---
CSV_FILE = "business_cards.csv"

# --- 儲存資料函式 ---
def save_to_csv(data_dict):
    if not os.path.exists(CSV_FILE):
        df = pd.DataFrame(columns=["姓名", "職稱", "公司", "電話", "Email", "地址"])
        df.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")
    
    df = pd.read_csv(CSV_FILE)
    
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

# --- AI 辨識函式 ---
def extract_info(image):
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
    try:
        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:-3]
        return json.loads(text)
    except:
        return None

# --- 管理員後台 ---
with st.sidebar:
    st.header("管理員專區")
    pwd = st.text_input("密碼", type="password")
    if pwd == "admin123":
        if os.path.exists(CSV_FILE):
            with open(CSV_FILE, "rb") as f:
                st.download_button(
                    label="📥 下載名片資料 (Excel/CSV)",
                    data=f,
                    file_name="visitors_data.csv",
                    mime="text/csv"
                )
            st.write("目前資料預覽：")
            st.dataframe(pd.read_csv(CSV_FILE))
        else:
            st.write("尚無資料")

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
        else:
            st.error("無法辨識，請再試一次。")
