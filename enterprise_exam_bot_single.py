# ============================================================
# ENTERPRISE TELEGRAM EXAM & CHAT BOT (SINGLE FILE VERSION)
# - Streamlit Compatible
# - Threaded Telegram Bot
# - Strict Scope Enforcement
# - Semantic + Deterministic Deduplication
# - ToC AI Scope Resolution
# - Arabic RTL PDF Output
# ============================================================

# ===================== IMPORTS =====================
import os
import re
import json
import math
import asyncio
import threading
import signal
import sys
from enum import Enum, auto
from difflib import SequenceMatcher
from dotenv import load_dotenv

import streamlit as st
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from openai import AsyncOpenAI
import PyPDF2

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.colors import black, grey
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import arabic_reshaper
from bidi.algorithm import get_display

# ===================== CONFIG =====================
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

STRICT_SCOPE_MODE = True
OCR_SUPPORTED = False

ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# ===================== STATES =====================
class State(Enum):
    IDLE = auto()
    CHAT_ACTIVE = auto()
    EXAM_DIFFICULTY = auto()
    EXAM_TYPE = auto()
    EXAM_COUNT = auto()
    EXAM_SCOPE = auto()
    EXAM_UPLOAD_PDF = auto()
    CONFIRMATION = auto()
    GENERATING = auto()

# ===================== UI CONSTANTS =====================
BTN_CHAT = "💬 Chat with AI"
BTN_EXAM = "📝 Create Exam"

CB_DIFF_EASY = "diff_easy"
CB_DIFF_MEDIUM = "diff_medium"
CB_DIFF_HARD = "diff_hard"

CB_TYPE_MCQ = "type_mcq"
CB_TYPE_TF = "type_tf"
CB_TYPE_ESSAY = "type_essay"
CB_TYPE_DONE = "type_done"

CB_CONFIRM_YES = "yes"
CB_CONFIRM_NO = "no"

# ===================== UTILITIES =====================
def rtl(text: str) -> str:
    try:
        return get_display(arabic_reshaper.reshape(text))
    except:
        return text

def parse_numeric_range(scope_text: str):
    match = re.search(r'(\d+)\s*(?:-|to)\s*(\d+)', scope_text)
    if match:
        s, e = map(int, match.groups())
        if s > 0 and e >= s:
            return (s - 1, e)
    return None

def is_scanned_pdf(text: str, pages: int) -> bool:
    if pages == 0:
        return True
    return (len(text.strip()) / pages) < 50

def is_duplicate(new_q: str, existing_qs: list, threshold=0.8) -> bool:
    for q in existing_qs:
        if SequenceMatcher(None, new_q, q).ratio() > threshold:
            return True
    return False

# ===================== AI ENGINE =====================
class AIEngine:
    def __init__(self):
        self.client = ai_client

    async def analyze_scope_range(self, toc_text, scope_query):
        prompt = (
            f"Table of Contents:\n{toc_text[:10000]}\n\n"
            f"User wants: {scope_query}\n"
            "Return JSON ONLY: {\"start\": int, \"end\": int, \"confidence\": float}"
        )
        try:
            res = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            data = json.loads(res.choices[0].message.content)
            if data.get("confidence", 0) >= 0.7:
                return (data["start"] - 1, data["end"])
        except:
            pass
        return None

    def chunk_text(self, text, size=12000):
        return [text[i:i+size] for i in range(0, len(text), size)]

    async def chat(self, history, message, context=None):
        msgs = [{"role": "system", "content": "You are an academic assistant."}]
        if context:
            msgs.append({"role": "system", "content": f"PDF CONTEXT:\n{context[:10000]}"})
        msgs.extend(history)
        msgs.append({"role": "user", "content": message})

        res = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=msgs
        )
        return res.choices[0].message.content

    async def create_exam(self, text, cfg):
        chunks = self.chunk_text(text)
        total = int(cfg["count"])
        per_chunk = math.ceil(total / len(chunks))

        all_qs = []
        seen_questions = []

        for chunk in chunks:
            if len(all_qs) >= total:
                break

            res = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content":
                     f"University examiner. Difficulty: {cfg['difficulty']}. "
                     f"Types: {cfg['types']}. Scope: {cfg['scope']}."},
                    {"role": "user", "content":
                     f"Generate {per_chunk + 2} questions from:\n{chunk[:15000]}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.3
            )

            data = json.loads(res.choices[0].message.content)
            batch = []
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        batch = v
                        break

            for q in batch:
                qt = q.get("question", "")
                if not is_duplicate(qt, seen_questions):
                    all_qs.append(q)
                    seen_questions.append(qt)

        return all_qs[:total]

# ===================== PDF ENGINE =====================
class PDFEngine:
    def __init__(self, font_path="fonts/arial.ttf"):
        self.font = "Helvetica"
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont("Arabic", font_path))
                self.font = "Arabic"
            except:
                pass
        self.ai = AIEngine()

    async def extract_text_smart(self, path, scope):
        reader = PyPDF2.PdfReader(path)
        total_pages = len(reader.pages)

        page_range = parse_numeric_range(scope)

        if not page_range:
            toc_text = ""
            for i in range(min(20, total_pages)):
                toc_text += reader.pages[i].extract_text() or ""
            if toc_text.strip():
                page_range = await self.ai.analyze_scope_range(toc_text, scope)

        if STRICT_SCOPE_MODE and not page_range and scope.lower() != "all":
            return "", "❌ Strict Scope Mode: Please specify page numbers."

        start, end = page_range if page_range else (0, total_pages)
        text = ""
        for i in range(start, min(end, total_pages)):
            text += reader.pages[i].extract_text() or ""

        if is_scanned_pdf(text, end - start):
            return "", "❌ Scanned PDF detected. OCR not supported."

        return text, None

    def generate_pdf(self, file, cfg, questions, answers=False):
        c = canvas.Canvas(file, pagesize=A4)
        w, h = A4
        y = h - 50

        c.setFont(self.font, 16)
        c.drawRightString(w - 50, y, rtl("Final Exam" if not answers else "Model Answers"))
        y -= 40

        c.setFont(self.font, 12)
        for i, q in enumerate(questions, 1):
            if y < 80:
                c.showPage()
                y = h - 50
                c.setFont(self.font, 12)

            c.drawRightString(w - 50, y, rtl(f"{i}. {q['question']}"))
            y -= 20

            if answers:
                c.setFillColor(grey)
                c.drawRightString(w - 50, y, rtl(f"Ans: {q.get('answer','')}"))
                c.setFillColor(black)
                y -= 20
            else:
                if q.get("type") == "MCQ":
                    for opt in q.get("options", []):
                        c.drawString(70, y, rtl(f"- {opt}"))
                        y -= 15
                elif q.get("type") == "Essay":
                    y -= 40

            y -= 15

        c.save()

# ===================== BOT HANDLERS =====================
pdf_engine = PDFEngine()
ai_engine = AIEngine()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["state"] = State.IDLE
    kb = [[BTN_CHAT, BTN_EXAM]]
    await update.message.reply_text(
        "🎓 Academic Exam System",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    state = context.user_data.get("state", State.IDLE)

    if text == BTN_CHAT:
        context.user_data["state"] = State.CHAT_ACTIVE
        context.user_data["history"] = []
        await update.message.reply_text("💬 Chat Mode")
        return

    if text == BTN_EXAM:
        context.user_data["config"] = {}
        context.user_data["state"] = State.EXAM_DIFFICULTY
        await update.message.reply_text(
            "Select Difficulty",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Easy", callback_data=CB_DIFF_EASY)],
                [InlineKeyboardButton("Medium", callback_data=CB_DIFF_MEDIUM)],
                [InlineKeyboardButton("Hard", callback_data=CB_DIFF_HARD)]
            ])
        )
        return

    if state == State.CHAT_ACTIVE:
        hist = context.user_data.get("history", [])
        pdf = context.user_data.get("pdf_text")
        wait = await update.message.reply_text("⏳ ...")
        ans = await ai_engine.chat(hist, text, pdf)
        hist.append({"role": "user", "content": text})
        hist.append({"role": "assistant", "content": ans})
        context.user_data["history"] = hist[-6:]
        await wait.edit_text(ans)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    cfg = context.user_data.setdefault("config", {})

    if data in (CB_DIFF_EASY, CB_DIFF_MEDIUM, CB_DIFF_HARD):
        cfg["difficulty"] = data.split("_")[1].title()
        cfg["types"] = []
        context.user_data["state"] = State.EXAM_TYPE
        await q.edit_message_text(
            "Select Types",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("MCQ", callback_data=CB_TYPE_MCQ)],
                [InlineKeyboardButton("True/False", callback_data=CB_TYPE_TF)],
                [InlineKeyboardButton("Essay", callback_data=CB_TYPE_ESSAY)],
                [InlineKeyboardButton("DONE", callback_data=CB_TYPE_DONE)]
            ])
        )
        return

    if data in (CB_TYPE_MCQ, CB_TYPE_TF, CB_TYPE_ESSAY):
        t = {"type_mcq": "MCQ", "type_tf": "TF", "type_essay": "Essay"}[data]
        if t not in cfg["types"]:
            cfg["types"].append(t)
        return

    if data == CB_TYPE_DONE:
        context.user_data["state"] = State.EXAM_COUNT
        await q.edit_message_text("Enter question count (5-100):")
        return

    if context.user_data["state"] == State.CONFIRMATION and data == CB_CONFIRM_YES:
        await q.edit_message_text("⏳ Generating exam...")
        questions = await ai_engine.create_exam(
            context.user_data["pdf_text"],
            context.user_data["config"]
        )
        uid = q.from_user.id
        os.makedirs("output", exist_ok=True)
        exam = f"output/exam_{uid}.pdf"
        ans = f"output/answers_{uid}.pdf"
        pdf_engine.generate_pdf(exam, cfg, questions, False)
        pdf_engine.generate_pdf(ans, cfg, questions, True)
        await context.bot.send_document(uid, open(exam, "rb"))
        await context.bot.send_document(uid, open(ans, "rb"))
        context.user_data["state"] = State.IDLE

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    f = await doc.get_file()
    path = f"tmp_{doc.file_id}.pdf"
    await f.download_to_drive(path)

    scope = context.user_data.get("config", {}).get("scope", "all")
    text, err = await pdf_engine.extract_text_smart(path, scope)
    os.remove(path)

    if err:
        await update.message.reply_text(err)
        return

    context.user_data["pdf_text"] = text
    context.user_data["state"] = State.CONFIRMATION
    await update.message.reply_text(
        "Confirm generation?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Yes", callback_data=CB_CONFIRM_YES)],
            [InlineKeyboardButton("No", callback_data=CB_CONFIRM_NO)]
        ])
    )

# ===================== STREAMLIT ENTRY =====================
def bot_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

def shutdown_handler(sig, frame):
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

st.set_page_config("Enterprise Exam Bot", layout="wide")
st.title("🤖 Enterprise Exam Bot")

if "bot_running" not in st.session_state:
    if not TELEGRAM_TOKEN:
        st.error("Missing TELEGRAM_BOT_TOKEN")
        st.stop()
    t = threading.Thread(target=bot_thread, daemon=True)
    t.start()
    st.session_state.bot_running = True
    st.success("Bot running in background thread.")
else:
    st.info("Bot already running.")
