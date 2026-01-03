# bot.py
# Telegram Exam Bot - Python (Single File)
# PDF + OCR + OpenAI + Word/PDF Export

import os
import re
import tempfile
import subprocess
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
import pdfplumber
import pytesseract
from PIL import Image
import openai
from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# ================== CONFIG ==================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY

if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("❌ Missing TELEGRAM_BOT_TOKEN or OPENAI_API_KEY")

sessions = {}

EXAM_PROMPT_RULES = """
أنت دكتور جامعي متخصص في إعداد الاختبارات الأكاديمية الجامعية.
مهمتك هي إعداد أسئلة مراجعة دقيقة ومطابقة للمحتوى الأكاديمي فقط، دون أي اجتهاد أو معلومات خارج النص.

التعليمات الإلزامية:
1. اعتمد حصريًا على محتوى الفصل المحدد من الكتاب أو ملف PDF فقط.
2. لا تضف أي سؤال من خارج الصفحات المحددة إطلاقًا.
3. لا تستخدم أي معلومات عامة أو معرفة خارجية.
4. الأسئلة مناسبة لطلاب الجامعة (Midterm / Final).
5. صياغة أكاديمية واضحة.
6. كل سؤال يعتمد على نص موجود فعليًا.
7. لا تكرر الأسئلة.
8. غطِّ كل المفاهيم، التواريخ، التعريفات، الجداول.

في النهاية:
- أضف قسم "الإجابات النموذجية".
"""

# ================== HELPERS ==================

def extract_text_pdf(path):
    text = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            if page.extract_text():
                text += page.extract_text() + "\n"
    return text.strip()

def extract_text_ocr(path):
    text = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            img = page.to_image(resolution=300).original
            text += pytesseract.image_to_string(img, lang="ara+eng")
    return text.strip()

def export_word(chat_id, text):
    doc = Document()
    for line in text.split("\n"):
        doc.add_paragraph(line)
    filename = f"exam_{chat_id}.docx"
    doc.save(filename)
    return filename

def export_pdf(chat_id, text):
    filename = f"exam_{chat_id}.pdf"
    c = canvas.Canvas(filename, pagesize=A4)
    width, height = A4
    y = height - 40

    for line in text.split("\n"):
        if y < 40:
            c.showPage()
            y = height - 40
        c.drawRightString(width - 40, y, line)
        y -= 14

    c.save()
    return filename

# ================== HANDLERS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً بك\n\n"
        "📘 أرسل ملف PDF أولًا\n"
        "✍️ ثم أرسل مواصفات الامتحان مثل:\n\n"
        "اسم المادة:\n"
        "الفصل:\n"
        "من صفحة:\n"
        "إلى صفحة:\n"
        "عدد MCQ:\n"
        "عدد صح/خطأ:\n"
        "عدد تعريفات:"
    )

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    file = await update.message.document.get_file()

    await update.message.reply_text("📄 جاري تحميل وتحليل الملف...")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        await file.download_to_drive(tmp.name)
        pdf_path = tmp.name

    text = extract_text_pdf(pdf_path)

    if len(text) < 100:
        await update.message.reply_text("📸 الملف مصور – جاري استخدام OCR...")
        text = extract_text_ocr(pdf_path)

    os.unlink(pdf_path)

    if len(text) < 100:
        await update.message.reply_text("❌ فشل استخراج النص من الملف")
        return

    sessions[chat_id] = {
        "pdf_text": text,
        "exam": ""
    }

    await update.message.reply_text("✅ تم استخراج النص بنجاح\n✍️ أرسل مواصفات الامتحان الآن")

async def handle_specs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id

    if chat_id not in sessions:
        return

    specs = update.message.text

    prompt = f"""
{EXAM_PROMPT_RULES}

بيانات الفصل:
{specs}

النص المسموح فقط:
====================
{sessions[chat_id]['pdf_text']}
====================

ابدأ الآن.
"""

    await update.message.reply_text("⚙️ جاري إنشاء الأسئلة...")

    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    exam_text = response.choices[0].message.content
    sessions[chat_id]["exam"] = exam_text

    await update.message.reply_text(exam_text[:3800])
    await update.message.reply_text("⬇️ اكتب: word أو pdf للتصدير")

async def handle_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    text = update.message.text.lower()

    if chat_id not in sessions or not sessions[chat_id]["exam"]:
        return

    exam = sessions[chat_id]["exam"]

    if "word" in text:
        filename = export_word(chat_id, exam)
        await update.message.reply_document(open(filename, "rb"))
        os.unlink(filename)

    elif "pdf" in text:
        filename = export_pdf(chat_id, exam)
        await update.message.reply_document(open(filename, "rb"))
        os.unlink(filename)

# ================== MAIN ==================

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_specs))
    app.add_handler(MessageHandler(filters.Regex("(?i)word|pdf"), handle_export))

    print("✅ Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
