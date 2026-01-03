# ===============================
# Telegram Exam System Bot
# Single File - Python
# ===============================

import os
import tempfile
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

import pdfplumber
import pytesseract
import openai
from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# ===============================
# CONFIG
# ===============================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY

if not BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("Missing API Keys")

sessions = {}

# ===============================
# PROMPTS
# ===============================

CHAT_PROMPT = """
أنت مساعد ذكي تجيب عن الأسئلة بوضوح وبأسلوب مبسط.
"""

EXAM_PROMPT_TEMPLATE = """
أنت دكتور جامعي متخصص في إعداد الاختبارات الأكاديمية.

التزم حرفيًا بالتعليمات:
- عدد الأسئلة: {question_count}
- مستوى الصعوبة: {difficulty}
- أنواع الأسئلة المطلوبة:
{question_types}

قواعد صارمة:
1. اعتمد فقط على النص المرفق.
2. لا تضف أي سؤال من خارج النص.
3. لا تستخدم معرفة عامة.
4. وزّع الأسئلة بالتساوي بين الأنواع المختارة.
5. صياغة أكاديمية واضحة.
6. في النهاية أضف قسم "الإجابات النموذجية".

النطاق المطلوب:
{scope}

النص المسموح فقط:
====================
{pdf_text}
====================
"""

# ===============================
# UTILITIES
# ===============================

def extract_pdf_text(path):
    text = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            if page.extract_text():
                text += page.extract_text() + "\n"
    return text.strip()

def extract_pdf_ocr(path):
    text = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            img = page.to_image(resolution=300).original
            text += pytesseract.image_to_string(img, lang="ara+eng")
    return text.strip()

def send_pdf_exam(chat_id, student, subject, exam_text):
    filename = f"exam_{chat_id}.pdf"
    c = canvas.Canvas(filename, pagesize=A4)
    w, h = A4
    y = h - 40

    # Header
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(w/2, y, "نموذج امتحان جامعي")
    y -= 40

    c.setFont("Helvetica", 11)
    c.drawRightString(w-40, y, f"اسم الطالب: {student}")
    y -= 20
    c.drawRightString(w-40, y, f"اسم المادة: {subject}")
    y -= 30

    c.line(40, y, w-40, y)
    y -= 30

    c.setFont("Helvetica", 11)

    for line in exam_text.split("\n"):
        if y < 40:
            c.showPage()
            c.setFont("Helvetica", 11)
            y = h - 40
        c.drawRightString(w-40, y, line)
        y -= 14

    c.save()
    return filename

# ===============================
# START
# ===============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🗨️ دردشة مع البوت", callback_data="mode_chat")],
        [InlineKeyboardButton("📝 عمل امتحان", callback_data="mode_exam")]
    ]
    await update.message.reply_text(
        "اختر طريقة الاستخدام:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ===============================
# MODE SELECTION
# ===============================

async def choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    sessions[chat_id] = {
        "mode": query.data,
        "types": [],
    }

    if query.data == "mode_chat":
        await query.message.reply_text("🗨️ تم تفعيل وضع الدردشة. اسأل أي شيء.")
    else:
        await ask_difficulty(query)

# ===============================
# EXAM FLOW
# ===============================

async def ask_difficulty(query):
    keyboard = [
        [InlineKeyboardButton("سهل", callback_data="diff_easy")],
        [InlineKeyboardButton("متوسط", callback_data="diff_medium")],
        [InlineKeyboardButton("صعب", callback_data="diff_hard")]
    ]
    await query.message.reply_text(
        "اختر مستوى الصعوبة:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def set_difficulty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    sessions[chat_id]["difficulty"] = query.data.replace("diff_", "")
    await ask_question_types(query)

async def ask_question_types(query):
    keyboard = [
        [
            InlineKeyboardButton("اختيار من متعدد", callback_data="type_mcq"),
            InlineKeyboardButton("صح / خطأ", callback_data="type_tf")
        ],
        [
            InlineKeyboardButton("مقالي", callback_data="type_essay")
        ],
        [
            InlineKeyboardButton("✅ تم", callback_data="types_done")
        ]
    ]
    await query.message.reply_text(
        "اختر نوع أو أكثر من أنواع الأسئلة:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def toggle_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    t = query.data.replace("type_", "")
    if t not in sessions[chat_id]["types"]:
        sessions[chat_id]["types"].append(t)

async def ask_question_count(query):
    keyboard = [
        [
            InlineKeyboardButton("10", callback_data="count_10"),
            InlineKeyboardButton("20", callback_data="count_20"),
            InlineKeyboardButton("30", callback_data="count_30")
        ],
        [
            InlineKeyboardButton("50", callback_data="count_50"),
            InlineKeyboardButton("100", callback_data="count_100")
        ]
    ]
    await query.message.reply_text(
        "اختر عدد الأسئلة:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def set_question_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    sessions[chat_id]["count"] = int(query.data.replace("count_", ""))
    await query.message.reply_text("✍️ اكتب اسم الفصل أو نطاق الصفحات:")

async def receive_scope(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    sessions[chat_id]["scope"] = update.message.text
    await update.message.reply_text("📘 أرسل ملف PDF الآن")

async def receive_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    file = await update.message.document.get_file()

    await update.message.reply_text("📄 جاري تحليل الملف...")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        await file.download_to_drive(tmp.name)
        path = tmp.name

    text = extract_pdf_text(path)
    if len(text) < 100:
        text = extract_pdf_ocr(path)

    os.unlink(path)

    sessions[chat_id]["pdf"] = text

    await generate_exam(update)

# ===============================
# GENERATE EXAM
# ===============================

async def generate_exam(update: Update):
    chat_id = update.message.chat_id
    s = sessions[chat_id]

    types_text = "\n".join([f"- {t}" for t in s["types"]])

    prompt = EXAM_PROMPT_TEMPLATE.format(
        question_count=s["count"],
        difficulty=s["difficulty"],
        question_types=types_text,
        scope=s["scope"],
        pdf_text=s["pdf"]
    )

    await update.message.reply_text("⚙️ جاري إنشاء الامتحان...")

    res = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2
    )

    exam_text = res.choices[0].message.content

    pdf = send_pdf_exam(
        chat_id,
        student="طالب",
        subject="المادة",
        exam_text=exam_text
    )

    await update.message.reply_document(open(pdf, "rb"))
    os.unlink(pdf)

# ===============================
# CHAT MODE
# ===============================

async def chat_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if sessions.get(chat_id, {}).get("mode") != "mode_chat":
        return

    res = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": CHAT_PROMPT},
            {"role": "user", "content": update.message.text}
        ]
    )

    await update.message.reply_text(res.choices[0].message.content)

# ===============================
# MAIN
# ===============================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(choose_mode, pattern="mode_"))
    app.add_handler(CallbackQueryHandler(set_difficulty, pattern="diff_"))
    app.add_handler(CallbackQueryHandler(toggle_type, pattern="type_"))
    app.add_handler(CallbackQueryHandler(lambda u, c: ask_question_count(u.callback_query), pattern="types_done"))
    app.add_handler(CallbackQueryHandler(set_question_count, pattern="count_"))
    app.add_handler(MessageHandler(filters.Document.PDF, receive_pdf))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_scope))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_mode))

    print("✅ Bot is running")
    app.run_polling()

if __name__ == "__main__":
    main()
