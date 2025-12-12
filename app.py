import streamlit as st
import google.generativeai as genai
import os

st.set_page_config(page_title="系統診斷", page_icon="🔧")

st.title("🔧 API 模型診斷工具")
st.write("正在檢測您的 API Key 權限...")

# 讀取 Key
try:
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"].strip()
        genai.configure(api_key=api_key)
        st.success("✅ API Key 讀取成功")
    else:
        st.error("❌ 未設定 GEMINI_API_KEY")
        st.stop()
except Exception as e:
    st.error(f"❌ Key 設定錯誤: {e}")
    st.stop()

# 列出模型
try:
    st.write("---")
    st.write("📡 正在向 Google 請求模型清單...")
    
    available_models = []
    for m in genai.list_models():
        # 只列出可以生成文字的模型
        if 'generateContent' in m.supported_generation_methods:
            available_models.append(m.name)
            
    if available_models:
        st.success(f"🎉 檢測成功！共找到 {len(available_models)} 個可用模型：")
        # 直接顯示在畫面上，方便您複製或截圖
        st.code(available_models)
        st.write("請將上面括號內的內容複製或截圖給我。")
    else:
        st.warning("⚠️ 連線成功，但清單是空的（沒有可用模型）。")
        
except Exception as e:
    st.error(f"❌ 連線失敗: {e}")
    st.write("可能原因：API Key 權限不足，或 library 版本過舊。")
