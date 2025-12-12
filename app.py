{\rtf1\ansi\ansicpg950\cocoartf2709
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\fswiss\fcharset0 Helvetica;}
{\colortbl;\red255\green255\blue255;}
{\*\expandedcolortbl;;}
\paperw11900\paperh16840\margl1440\margr1440\vieww11520\viewh8400\viewkind0
\pard\tx720\tx1440\tx2160\tx2880\tx3600\tx4320\tx5040\tx5760\tx6480\tx7200\tx7920\tx8640\pardirnatural\partightenfactor0

\f0\fs24 \cf0 import streamlit as st\
import google.generativeai as genai\
import pandas as pd\
from PIL import Image\
import json\
import time\
import os\
\
# --- \uc0\u35373 \u23450 \u38913 \u38754  ---\
st.set_page_config(page_title="\uc0\u23637 \u35261 \u21517 \u29255 \u23567 \u24171 \u25163 ", page_icon="\u55357 \u56519 ")\
\
# --- \uc0\u38577 \u34255 \u19981 \u24517 \u35201 \u30340 \u20171 \u38754 \u65292 \u35731 \u23427 \u20687  App ---\
hide_streamlit_style = """\
            <style>\
            #MainMenu \{visibility: hidden;\}\
            footer \{visibility: hidden;\}\
            header \{visibility: hidden;\}\
            </style>\
            """\
st.markdown(hide_streamlit_style, unsafe_allow_html=True)\
\
# --- 1. \uc0\u35373 \u23450  Google Gemini AI ---\
# \uc0\u35531 \u22312  Streamlit Cloud \u24460 \u21488  Secrets \u35373 \u23450  GEMINI_API_KEY\
try:\
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])\
except:\
    st.warning("\uc0\u9888 \u65039  \u35531 \u20808 \u22312 \u24460 \u21488 \u35373 \u23450  GEMINI_API_KEY \u25165 \u33021 \u38283 \u22987 \u36776 \u35672 ")\
\
# --- CSV \uc0\u27284 \u26696 \u36335 \u24465  ---\
CSV_FILE = "business_cards.csv"\
\
# --- \uc0\u20786 \u23384 \u36039 \u26009 \u21040  CSV \u30340 \u20989 \u24335  ---\
def save_to_csv(data_dict):\
    # \uc0\u22914 \u26524 \u27284 \u26696 \u19981 \u23384 \u22312 \u65292 \u20808 \u24314 \u31435 \u27161 \u38988 \
    if not os.path.exists(CSV_FILE):\
        df = pd.DataFrame(columns=["\uc0\u22995 \u21517 ", "\u32887 \u31281 ", "\u20844 \u21496 ", "\u38651 \u35441 ", "Email", "\u22320 \u22336 "])\
        df.to_csv(CSV_FILE, index=False, encoding="utf-8-sig") # utf-8-sig \uc0\u36991 \u20813  Excel \u25171 \u38283 \u20098 \u30908 \
    \
    # \uc0\u35712 \u21462 \u33290 \u36039 \u26009 \
    df = pd.read_csv(CSV_FILE)\
    \
    # \uc0\u26032 \u22686 \u19968 \u31558 \
    new_row = \{\
        "\uc0\u22995 \u21517 ": data_dict.get('name', ''),\
        "\uc0\u32887 \u31281 ": data_dict.get('title', ''),\
        "\uc0\u20844 \u21496 ": data_dict.get('company', ''),\
        "\uc0\u38651 \u35441 ": data_dict.get('phone', ''),\
        "Email": data_dict.get('email', ''),\
        "\uc0\u22320 \u22336 ": data_dict.get('address', '')\
    \}\
    \
    # \uc0\u20351 \u29992  concat \u21462 \u20195  append (\u22240 \u28858  append \u21363 \u23559 \u34987 \u26820 \u29992 )\
    new_df = pd.DataFrame([new_row])\
    df = pd.concat([df, new_df], ignore_index=True)\
    \
    # \uc0\u23384 \u27284 \
    df.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")\
    return True\
\
# --- AI \uc0\u36776 \u35672 \u37007 \u36655  (\u21516 \u21069 ) ---\
def extract_info(image):\
    model = genai.GenerativeModel('gemini-1.5-flash')\
    prompt = """\
    \uc0\u20320 \u26159 \u19968 \u20491 \u21517 \u29255 \u36776 \u35672 \u23560 \u23478 \u12290 \u35531 \u20998 \u26512 \u36889 \u24373 \u21517 \u29255 \u22294 \u29255 \u65292 \u20006 \u25847 \u21462 \u20197 \u19979 \u36039 \u35338 \u65292 \u36664 \u20986 \u25104 \u32020  JSON \u26684 \u24335 \u65306 \
    \{\
        "name": "\uc0\u22995 \u21517 ",\
        "title": "\uc0\u32887 \u31281 ",\
        "company": "\uc0\u20844 \u21496 \u21517 \u31281 ",\
        "phone": "\uc0\u38651 \u35441 \u34399 \u30908 (\u20778 \u20808 \u25235 \u21462 \u25163 \u27231 )",\
        "email": "Email",\
        "address": "\uc0\u22320 \u22336 "\
    \}\
    \uc0\u22914 \u26524 \u26576 \u20491 \u27396 \u20301 \u25214 \u19981 \u21040 \u65292 \u35531 \u30041 \u31354 \u23383 \u20018 \u12290 \u19981 \u35201 \u36664 \u20986  JSON \u20197 \u22806 \u30340 \u20219 \u20309 \u25991 \u23383 \u12290 \
    """\
    response = model.generate_content([prompt, image])\
    try:\
        text = response.text.strip()\
        if text.startswith("```json"):\
            text = text[7:-3]\
        return json.loads(text)\
    except:\
        return None\
\
# --- \uc0\u31649 \u29702 \u21729 \u24460 \u21488  (\u20596 \u37002 \u27396 ) ---\
with st.sidebar:\
    st.header("\uc0\u31649 \u29702 \u21729 \u23560 \u21312 ")\
    st.write("\uc0\u36664 \u20837 \u23494 \u30908 \u19979 \u36617 \u36039 \u26009 ")\
    pwd = st.text_input("\uc0\u23494 \u30908 ", type="password")\
    if pwd == "admin123": # \uc0\u24744 \u21487 \u20197 \u33258 \u24049 \u25913 \u23494 \u30908 \
        if os.path.exists(CSV_FILE):\
            with open(CSV_FILE, "rb") as f:\
                st.download_button(\
                    label="\uc0\u55357 \u56549  \u19979 \u36617 \u21517 \u29255 \u36039 \u26009  (Excel/CSV)",\
                    data=f,\
                    file_name="visitors_data.csv",\
                    mime="text/csv"\
                )\
            # \uc0\u39023 \u31034 \u38928 \u35261 \
            st.write("\uc0\u30446 \u21069 \u36039 \u26009 \u38928 \u35261 \u65306 ")\
            st.dataframe(pd.read_csv(CSV_FILE))\
        else:\
            st.write("\uc0\u30446 \u21069 \u36996 \u27794 \u26377 \u36039 \u26009 \u12290 ")\
\
# --- \uc0\u20027 \u20171 \u38754  ---\
st.title("\uc0\u55357 \u56519  \u27489 \u36814 \u21443 \u35264 \u65281 ")\
st.write("\uc0\u35531 \u25293 \u25885 \u21517 \u29255 \u65292 \u31995 \u32113 \u23559 \u33258 \u21205 \u28858 \u24744 \u24314 \u27284 \u12290 ")\
\
# \uc0\u21855 \u21205 \u30456 \u27231  (iPhone \u19978 \u26371 \u33258 \u21205 \u21628 \u21483 \u21069 \u37857 \u38957 \u25110 \u24460 \u37857 \u38957 \u65292 \u20171 \u38754 \u19978 \u26377 \u25353 \u37397 \u21487 \u20999 \u25563 )\
img_file = st.camera_input("\uc0\u40670 \u25802 \u19979 \u26041 \u25353 \u37397 \u25293 \u29031 ", label_visibility="hidden")\
\
if img_file:\
    with st.spinner('\uc0\u55358 \u56598  \u27491 \u22312 \u35712 \u21462 \u21517 \u29255 \u36039 \u26009 ...'):\
        image = Image.open(img_file)\
        info = extract_info(image)\
        \
        if info:\
            st.info(f"\uc0\u21992 \u65292 \{info.get('name')\}\u65281 \u36039 \u26009 \u20786 \u23384 \u20013 ...")\
            save_to_csv(info)\
            st.balloons()\
            st.success("\uc0\u9989  \u24314 \u27284 \u25104 \u21151 \u65281 ")\
            st.write("\uc0\u30059 \u38754 \u23559 \u22312  3 \u31186 \u24460 \u33258 \u21205 \u37325 \u32622 ...")\
            time.sleep(3)\
            st.rerun()\
        else:\
            st.error("\uc0\u28961 \u27861 \u36776 \u35672 \u65292 \u35531 \u20877 \u35430 \u19968 \u27425 \u12290 ")}