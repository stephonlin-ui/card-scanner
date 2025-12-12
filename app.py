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
        st.warning("⚠️ 尚未設定 API Key")
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

# --- AI 辨識函式 (智慧輪詢版) ---
def extract_info(image):
    # 這是我們的生存名單，依照「成功率」與「額度」排序
    priority_models = [
        "models/gemini-2.0-flash-exp",   # 實驗版：通常免費額度最敢給
        "models/gemini-flash-latest",    # 通用版：系統自動指派
        "models/gemini-2.5-flash",       # 保底版：雖然只有5次，但確定存在
        "models/gemini-exp-1206"         # 備用實驗版
    ]
    
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

    last_error = ""

    # 開始輪詢，直到成功
    for model_name in priority_models:
        try:
            # st.toast(f"嘗試模型: {model_name}...") # (測試用)
            model = genai.GenerativeModel(model_name)
            response = model.generate_content([prompt, image])
            text = response.text.strip()
            
            if text.startswith("```json"):
                text = text[7:-3]
            elif text.startswith("```"):
                text = text[3:-3]
                
            return json.loads(text) # 成功！直接回傳，結束迴圈
            
        except Exception as e:
            error_msg = str(e)
            last_error = error_msg
            
            # 如果是 Limit 0 (不能用) 或 404 (找不到)，就直接試下一個，不浪費時間
            if "limit: 0" in error_msg or "404" in error_msg:
                continue
            
            # 如果是 429 (速度太快)，稍微停一下再試下一個
            if "429" in error_msg:
                time.sleep(1)
                continue
                
    # 迴圈跑完還是沒人救得了
    st.error(f"很抱歉，所有可用模型都忙碌中或額度已滿。最後錯誤: {last_error}")
    st.warning("建議：請稍等 1 分鐘後再試，或更換 Google 帳號申請新的 API Key。")
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

# --- 主畫面 ---
st.title("📇 歡迎參觀！")
st.write("請拍攝名片，系統將自動為您建檔。")
st.caption("System v6.0 (Auto-Fallback Mode)") 

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
