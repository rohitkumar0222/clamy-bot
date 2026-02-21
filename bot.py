import sqlite3
import time
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters

TOKEN = "8534771893:AAFrlkVZ1TmD8LDci67r2AVi4HngsAAGzII"
ADMIN_ID = 6589920283

CHANNEL_NAME = "Doctor’s Pustakalay 🩺"
CHANNEL_ID = -1002421941913
CHANNEL_INVITE_LINK = "https://t.me/+gXUhu15L5PU5Njk1"

# Database setup
conn = sqlite3.connect("files.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS files (
    file_id TEXT PRIMARY KEY,
    file_name TEXT,
    added_at TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS searches (
    user_id INTEGER,
    query TEXT,
    searched_at TEXT
)
""")

conn.commit()

user_last_search = {}

# ================= START COMMAND =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        f"Welcome to {CHANNEL_NAME}\n\n"
        f"I am Clamy, Dr. Rohit's personal assistant.\n\n"
        f"How this works:\n"
        f"• Join our official channel.\n"
        f"• Send any book name or keyword.\n"
        f"• I will deliver matching PDFs instantly.\n"
        f"• Each file will automatically delete after 1 hour.\n\n"
        f"Please download important files before the time limit expires.\n\n"
        f"How can I assist you today?"
    )
    await update.message.reply_text(welcome_text)

# ================= CHECK MEMBERSHIP =================
async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)

        if member.status in ["member", "administrator", "creator"]:
            return True

        if member.status in ["left", "kicked"]:
            return False

        return False

    except Exception as e:
        print("Membership check error:", e)
        return False

# ================= CHANNEL CAPTURE =================
async def capture_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.channel_post and update.channel_post.document:
        doc = update.channel_post.document
        file_id = doc.file_id
        file_name = doc.file_name.lower()

        cursor.execute(
            "INSERT OR IGNORE INTO files (file_id, file_name, added_at) VALUES (?, ?, ?)",
            (file_id, file_name, str(datetime.now()))
        )
        conn.commit()

        print(f"Indexed: {file_name}")

# ================= SEARCH FUNCTION =================
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.lower()
    user = update.message.from_user

    joined = await check_membership(update, context)

    # Inform only (no blocking)
    if not joined:
        keyboard = [
            [InlineKeyboardButton("Join Channel", url=CHANNEL_INVITE_LINK)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"You are not currently a member of {CHANNEL_NAME}.\n\n"
            f"You can still search, but joining is recommended.",
            reply_markup=reply_markup
        )

    # Rate limit (3 seconds)
    now = time.time()
    if user.id in user_last_search:
        if now - user_last_search[user.id] < 3:
            await update.message.reply_text("Please wait a few seconds before searching again.")
            return

    user_last_search[user.id] = now

    cursor.execute(
        "SELECT file_id, file_name FROM files WHERE file_name LIKE ? LIMIT 5",
        ('%' + query + '%',)
    )

    results = cursor.fetchall()

    if results:
        for file_id, file_name in results:
            sent_message = await update.message.reply_document(file_id)

            warning_message = await update.message.reply_text(
                "Notice: This file will be automatically deleted in 1 hour."
            )

            context.job_queue.run_once(
                delete_messages,
                3600,
                data={
                    "chat_id": update.effective_chat.id,
                    "file_message_id": sent_message.message_id,
                    "warning_message_id": warning_message.message_id
                }
            )
    else:
        await update.message.reply_text("No matching files found.")

    # Log search
    cursor.execute(
        "INSERT INTO searches (user_id, query, searched_at) VALUES (?, ?, ?)",
        (user.id, query, str(datetime.now()))
    )
    conn.commit()

    # Notify admin
    log_message = (
        f"New Search\n"
        f"User: {user.full_name}\n"
        f"Username: @{user.username}\n"
        f"User ID: {user.id}\n"
        f"Query: {query}\n"
        f"Time: {datetime.now()}"
    )

    await context.bot.send_message(chat_id=ADMIN_ID, text=log_message)

# ================= DELETE FUNCTION =================
async def delete_messages(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    file_message_id = job_data["file_message_id"]
    warning_message_id = job_data["warning_message_id"]

    try:
        await context.bot.delete_message(chat_id, file_message_id)
        await context.bot.delete_message(chat_id, warning_message_id)
    except:
        pass

# ================= RUN BOT =================
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.ChatType.CHANNEL, capture_channel))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search))

print("Clamy Production Bot Running...")
app.run_polling()