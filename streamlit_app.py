import streamlit as st
import subprocess
import sys

st.set_page_config(page_title="Telegram Exam Bot")

st.title("🤖 Telegram Exam Bot")
st.write("اضغط الزر لتشغيل البوت في الخلفية")

if "started" not in st.session_state:
    st.session_state.started = False

if not st.session_state.started:
    if st.button("▶️ تشغيل البوت"):
        subprocess.Popen([sys.executable, "bot.py"])
        st.session_state.started = True
        st.success("✅ البوت اشتغل بنجاح")
else:
    st.info("🟢 البوت شغال بالفعل")
