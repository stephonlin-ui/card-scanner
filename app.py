import streamlit as st
import json
import traceback

st.set_page_config(page_title="Card Scanner Debug", page_icon="🧪", layout="centered")
st.title("🧪 Debug Mode｜除錯模式")
st.caption("如果你看到這行文字，表示 Streamlit 有正常執行到 UI。")

def show_fatal(e: Exception):
    st.error("❌ App 發生錯誤（這就是你看到空白頁的原因）")
    st.code("".join(traceback.format_exception(type(e), e, e.__traceback__)))
    st.stop()

# -------------------------
# 1) 檢查 secrets 是否存在
# -------------------------
try:
    st.subheader("1) Secrets 檢查｜Secrets Check")

    if "google_oauth" not in st.secrets:
        st.error("缺少 [google_oauth] in secrets")
        st.code("""你需要：
[google_oauth]
client_id = "..."
client_secret = "..."
redirect_uri = "https://你的app.streamlit.app/"  # 必須與 Google Console 完全一致（含結尾 /）
""")
        st.stop()

    for k in ["client_id", "client_secret", "redirect_uri"]:
        if k not in st.secrets["google_oauth"] or not str(st.secrets["google_oauth"][k]).strip():
            st.error(f"google_oauth.{k} 缺少或是空的")
            st.stop()

    st.success("✅ google_oauth secrets OK")
    st.write("redirect_uri =", st.secrets["google_oauth"]["redirect_uri"])

except Exception as e:
    show_fatal(e)

# -------------------------
# 2) 檢查套件是否齊全（OAuth 必要）
# -------------------------
try:
    st.subheader("2) 套件檢查｜Package Check")

    from google_auth_oauthlib.flow import Flow
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    st.success("✅ google-auth / google-auth-oauthlib OK")

except Exception as e:
    st.error("❌ 缺少 OAuth 套件，請在 requirements.txt 加入：google-auth、google-auth-oauthlib")
    show_fatal(e)

# -------------------------
# 3) OAuth 流程（一定會顯示登入連結）
# -------------------------
try:
    st.subheader("3) OAuth 登入測試｜OAuth Login Test")

    SCOPES = [
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/spreadsheets"
    ]

    CLIENT_CONFIG = {
        "web": {
            "client_id": st.secrets["google_oauth"]["client_id"],
            "client_secret": st.secrets["google_oauth"]["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [st.secrets["google_oauth"]["redirect_uri"]],
        }
    }

    def get_oauth_creds():
        # 有 token 就直接用
        if "credentials" in st.session_state:
            creds = Credentials.from_authorized_user_info(
                json.loads(st.session_state["credentials"]), SCOPES
            )
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                st.session_state["credentials"] = creds.to_json()
            return creds

        # 有 code 就換 token
        params = st.experimental_get_query_params()
        if "code" in params:
            flow = Flow.from_client_config(
                CLIENT_CONFIG,
                scopes=SCOPES,
                redirect_uri=st.secrets["google_oauth"]["redirect_uri"]
            )
            flow.fetch_token(code=params["code"][0])
            creds = flow.credentials
            st.session_state["credentials"] = creds.to_json()
            st.experimental_set_query_params()
            return creds

        # 否則顯示登入連結
        flow = Flow.from_client_config(
            CLIENT_CONFIG,
            scopes=SCOPES,
            redirect_uri=st.secrets["google_oauth"]["redirect_uri"]
        )
        auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
        st.info("尚未登入。請點下面連結進行授權：")
        st.markdown(f"👉 [Login with Google｜使用 Google 登入]({auth_url})")
        return None

    creds = get_oauth_creds()
    if creds:
        st.success("✅ OAuth 已登入完成（已拿到 token）")
        st.write("token expiry:", getattr(creds, "expiry", None))
    else:
        st.warning("等待你點登入連結完成授權。")

except Exception as e:
    show_fatal(e)

st.subheader("4) 下一步｜Next Step")
st.write("如果這頁能正常顯示登入連結，就代表『空白頁』問題已排除。接下來我可以把完整掃描 UX + 裁切校正功能再加回去。")
