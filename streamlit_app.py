import streamlit as st
import subprocess
import sys
import os

st.set_page_config(page_title="Telegram Exam Bot")

st.title("🤖 Telegram Exam Bot")
st.write("البوت يعمل في الخلفية")

if "bot_started" not in st.session_state:
    st.session_state.bot_started = False

if not st.session_state.bot_started:
    if st.button("▶️ تشغيل البوت"):
        subprocess.Popen([sys.executable, "bot.py"])
        st.session_state.bot_started = True
        st.success("✅ البوت اشتغل بنجاح")
else:
    st.info("🟢 البوت شغال بالفعل")
