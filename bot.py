import asyncio
import time
import sqlite3
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# ================= CONFIG =================
TOKEN = "8534771893:AAFrlkVZ1TmD8LDci67r2AVi4HngsAAGzII"
CHANNEL_ID = -1002421941913
ADMIN_ID = 1145276075
CHANNEL_INVITE_LINK = "https://t.me/+gXUhu15L5PU5Njk1"

# ================= DATABASE =================
conn = sqlite3.connect("files.db", check_same_thread=False)
cursor = conn.cursor()

# Files table
cursor.execute("""
CREATE TABLE IF NOT EXISTS files (
    file_id TEXT PRIMARY KEY,
    file_name TEXT
)
""")

# Users table (for Verified Member ID)
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    member_number INTEGER
)
""")

# Search logs table
cursor.execute("""
CREATE TABLE IF NOT EXISTS searches (
    user_id INTEGER,
    query TEXT,
    timestamp TEXT
)
""")

conn.commit()
# ================= MEMORY =================
active_search_messages = {}
pending_searches = {}
user_temp_messages = {}
active_footer_jobs = {}
active_results = {}
# ================= MEMBERSHIP CHECK =================
async def check_membership(user_id, context):
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        print("Membership check error:", e)
        return False
# ================= MATCHING FILES ENGINE =================
def get_matching_files(query):
    from rapidfuzz import fuzz

    cursor.execute("SELECT file_id, file_name FROM files")
    rows = cursor.fetchall()

    matches = []
    query = query.lower().strip()

    if len(query) < 2:
        return []

    for file_id, file_name in rows:
        name = file_name.lower().replace(".pdf", "").strip()
        name_words = name.split()

        # 1️⃣ Exact match
        if query == name:
            matches.append((120, file_id, file_name))
            continue

        # 2️⃣ 3-letter prefix match (controlled)
        if len(query) == 3:
            for word in name_words:
                if word.startswith(query):
                    matches.append((100, file_id, file_name))
                    break
            continue

        # 3️⃣ Word-level exact
        if query in name_words:
            matches.append((105, file_id, file_name))
            continue

        # 4️⃣ Strong contains (length >=4)
        if len(query) >= 4 and query in name:
            matches.append((95, file_id, file_name))
            continue

        # 5️⃣ Strict fuzzy (high threshold)
        score = fuzz.token_set_ratio(query, name)
        if score >= 92:
            matches.append((score, file_id, file_name))

    matches.sort(reverse=True)
    return matches

# ================= MEMBER ID =================
def get_or_create_member(user_id):
    cursor.execute("SELECT member_number FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()

    if row:
        return row[0]

    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    member_number = count + 1

    cursor.execute(
        "INSERT INTO users (user_id, member_number) VALUES (?, ?)",
        (user_id, member_number)
    )
    conn.commit()

    return member_number

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    member_number = get_or_create_member(user.id)

    greeting = await update.message.reply_text(
        f"🌇 <b><i>Good Evening</i></b>\n\n"
        f"👩🏻‍⚕️ <b>Clamy</b>\n"
        f"<i>Personal Assistant of Dr. Rohit Madhukar 🩺</i>\n\n"
        f"🛡 <b>Verified Member ID:</b> #{member_number}\n\n"
        f"🔎 <b>Type any subject or file name to begin.</b>",
        parse_mode="HTML"
    )

    context.user_data["greeting_id"] = greeting.message_id
# ================= ADMIN SEARCH LOG =================
async def notify_admin_search(user, query, context):

    try:
        member_number = get_or_create_member(user.id)

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "━━━━━━━━━━━━━━━━━━\n"
                "🔎 NEW SEARCH ALERT\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 Name: {user.full_name}\n"
                f"🆔 User ID: {user.id}\n"
                f"🛡 Member ID: #{member_number}\n"
                f"📌 Query: {query}\n"
                f"🕒 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
        )

    except Exception as e:
        print("Admin log error:", e)
# ================= INTELLIGENT SEARCH =================
async def search(update, context):

    if not update.message or not update.message.text:
        return

    query = update.message.text.strip().lower()
    user = update.message.from_user
    chat_id = update.effective_chat.id

    if len(query) < 2 or query.startswith("/"):
        return

    # ===== MEMBERSHIP CHECK =====
    joined = await check_membership(user.id, context)

    if not joined:
        pending_searches[user.id] = query

        keyboard = [[
            InlineKeyboardButton("🔔 Join Channel", url=CHANNEL_INVITE_LINK),
            InlineKeyboardButton("✅ I Joined", callback_data="verify_join")
        ]]

        await update.message.reply_text(
            "🔒 Please join the channel to continue.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ===== DELETE PREVIOUS RESULTS =====
    if chat_id in active_results:
        for msg_id in active_results[chat_id]:
            try:
                await context.bot.delete_message(chat_id, msg_id)
            except:
                pass

    # ===== PREMIUM SEARCH ANIMATION =====
    progress_msg = await update.message.reply_text(
        "🧠 Initializing Search Engine\n\n▱▱▱▱▱▱▱▱▱▱ 0%"
    )

    matching_task = asyncio.create_task(
        asyncio.to_thread(get_matching_files, query)
    )

    total_steps = 12
    last_text = ""

    for step in range(total_steps + 1):

        await asyncio.sleep(0.03)

        percent = int((step / total_steps) * 100)
        filled = percent // 10
        bar = "▰" * filled + "▱" * (10 - filled)

        if percent < 15:
            status = "🧠 Initializing Search Engine"
        elif percent < 30:
            status = "🔎 Scanning Indexed Files"
        elif percent < 45:
            status = "📊 Analyzing Similarity Matrix"
        elif percent < 60:
            status = "🧬 Calculating Match Confidence"
        elif percent < 75:
            status = "⚙ Optimizing Result Ranking"
        elif percent < 90:
            status = "🔐 Preparing Secure Dispatch"
        else:
            status = "📤 Sending Files..."

        new_text = f"{status}\n\n{bar} {percent}%"

        if new_text != last_text:
            try:
                await progress_msg.edit_text(new_text)
            except:
                pass
            last_text = new_text

        # Stop early if matching done and nearly complete
        if matching_task.done() and percent >= 85:
            break

    matches = await matching_task

    # ===== NO RESULTS =====
    if not matches:
        try:
            await progress_msg.edit_text(
                "❌ No Results Found\n\n"
                "▱▱▱▱▱▱▱▱▱▱ 0%\n"
                "Check spelling and try again."
            )
        except:
            pass
        return

    await progress_msg.delete()

    matches.sort(reverse=True)
    sent_ids = []

    # ===== SEND FILES =====
    for score, file_id, file_name in matches[:15]:
        try:
            sent = await context.bot.send_document(
                chat_id,
                document=file_id,
                caption=f"📄 {file_name}\n⭐ Match Confidence: {round(score,1)}%"
            )
            sent_ids.append(sent.message_id)
        except:
            continue

    # ===== DELETE GREETING =====
    greeting_id = context.user_data.get("greeting_id")
    if greeting_id:
        try:
            await context.bot.delete_message(chat_id, greeting_id)
        except:
            pass

    # ===== DELETE USER MESSAGE =====
    try:
        await update.message.delete()
    except:
        pass

    # ===== STORE RESULTS =====
    active_results[chat_id] = sent_ids

    # ===== FOOTER =====
    await send_footer(chat_id, context, sent_ids)

    # ===== ADMIN NOTIFY =====
    await notify_admin_search(user, query, context)

    # ===== LOG SEARCH =====
    try:
        cursor.execute(
            "INSERT INTO searches (user_id, query, timestamp) VALUES (?, ?, datetime('now'))",
            (user.id, query)
        )
        conn.commit()
    except:
        pass

# ================= CLEANUP TEMP MESSAGES =================
async def cleanup_messages(context):
    job = context.job
    chat_id = job.data["chat_id"]
    user_id = job.data["user_id"]

    if user_id in user_temp_messages:
        for msg_id in user_temp_messages[user_id]:
            try:
                await context.bot.delete_message(chat_id, msg_id)
            except:
                pass

        user_temp_messages[user_id] = []

# ================= DIRECT SEARCH FLOW =================
async def run_search_flow(chat_id, user, query, context):

    # Animation
    search_msg = await context.bot.send_message(
        chat_id,
        "🧠 Searching...\n\n▰▱▱▱▱▱▱▱▱▱ 10%"
    )

    await asyncio.sleep(0.6)

    matches = get_matching_files(query)

    if not matches:
        await search_msg.edit_text(
            "❌ No relevant matches detected.\n\n▱▱▱▱▱▱▱▱▱▱ 0%"
        )
        return

    await search_msg.edit_text(
        f"📊 {len(matches)} Results Found\n\n▰▰▰▰▰▱▱▱▱▱ 50%"
    )

    await asyncio.sleep(0.6)

    await search_msg.edit_text(
        "📤 Sending Files...\n\n▰▰▰▰▰▰▰▰▰▰ 100%"
    )

    await asyncio.sleep(0.6)

    await search_msg.delete()

    sent_ids = []

    for score, file_id, file_name in matches[:10]:
        try:
            sent = await context.bot.send_document(
                chat_id,
                document=file_id,
                caption=f"📄 {file_name}\n⭐ Match Confidence: {round(score,2)}%"
            )
            sent_ids.append(sent.message_id)
        except:
            continue

    await send_footer(chat_id, context, sent_ids)

# ================= VERIFY JOIN =================
async def verify_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_obj = update.callback_query
    await query_obj.answer()

    user = query_obj.from_user
    chat_id = user.id

    joined = await check_membership(user.id, context)

    if not joined:
        await query_obj.edit_message_text("❌ Membership not detected.")
        return

    await query_obj.edit_message_text(
        "✨ Access Verified\nRunning your previous search..."
    )

    await asyncio.sleep(1)

    if user.id in pending_searches:
        query = pending_searches.pop(user.id)

        # Manually trigger search logic without faking Update
        await run_search_flow(chat_id, user, query, context)

# ================= PREMIUM FOOTER SYSTEM =================

async def send_footer(chat_id, context, sent_ids):

    from datetime import datetime, timedelta
    import random

    # Cancel previous footer job if exists
    if chat_id in active_footer_jobs:
        old_job = active_footer_jobs[chat_id]
        try:
            old_msg_id = old_job.data["message_id"]
            await context.bot.delete_message(chat_id, old_msg_id)
        except:
            pass
        old_job.schedule_removal()

    motivations = [
        "Discipline compounds advantage.",
        "Consistency builds mastery.",
        "Focused effort wins long term.",
        "Precision creates distinction."
    ]

    end_time = datetime.now() + timedelta(minutes=60)
    motivation_line = random.choice(motivations)

    progress_bar = "🟩🟩🟩🟩🟩🟩"
    percent = 100

    panel_text = (
        "🔐 𝐒𝐄𝐂𝐔𝐑𝐄 𝐀𝐂𝐂𝐄𝐒𝐒\n\n"
        f"🧠 {motivation_line}\n\n"
        "⏳ 60:00 remaining\n"
        f"{progress_bar}  {percent}%\n\n"
        "📥 Save or Forward before expiry\n"
        "⚠ Auto-deletes in 60 minutes\n"
        "🏥 Doctor’s Pustakalay 🩺"
    )

    panel = await context.bot.send_message(chat_id, panel_text)
    sent_ids.append(panel.message_id)

    job = context.job_queue.run_repeating(
        update_footer_panel,
        interval=600,  # update every 10 minutes
        first=600,
        data={
            "chat_id": chat_id,
            "message_id": panel.message_id,
            "end_time": end_time,
            "motivation": motivation_line,
            "sent_ids": sent_ids
        }
    )

    active_footer_jobs[chat_id] = job


async def update_footer_panel(context):

    from datetime import datetime

    job = context.job
    chat_id = job.data["chat_id"]
    message_id = job.data["message_id"]
    end_time = job.data["end_time"]
    motivation = job.data["motivation"]
    sent_ids = job.data["sent_ids"]

    total_seconds = 60 * 60
    remaining = int((end_time - datetime.now()).total_seconds())

    # If expired → delete files + footer
    if remaining <= 0:
        for msg_id in sent_ids:
            try:
                await context.bot.delete_message(chat_id, msg_id)
            except:
                pass

        job.schedule_removal()
        active_footer_jobs.pop(chat_id, None)
        return

    mins = remaining // 60
    percent = int((remaining / total_seconds) * 100)

    # 3-phase color logic
    if remaining > 40 * 60:
        progress_bar = "🟩🟩🟩🟩🟩🟩"
    elif remaining > 20 * 60:
        progress_bar = "🟧🟧🟧🟧⬜⬜"
    else:
        progress_bar = "🟥🟥⬜⬜⬜⬜"

    panel_text = (
        "🔐 𝐒𝐄𝐂𝐔𝐑𝐄 𝐀𝐂𝐂𝐄𝐒𝐒\n\n"
        f"🧠 {motivation}\n\n"
        f"⏳ {mins:02d}:00 remaining\n"
        f"{progress_bar}  {percent}%\n\n"
        "📥 Save or Forward before expiry\n"
        "⚠ Auto-deletes in 60 minutes\n"
        "🏥 Doctor’s Pustakalay 🩺"
    )

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=panel_text
        )
    except:
        pass
# ================= AUTO DELETE =================
async def delete_messages(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data["chat_id"]

    for msg_id in job.data["message_ids"]:
        try:
            await context.bot.delete_message(chat_id, msg_id)
        except:
            pass

# ================= SAVE FILE =================
async def save_file(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = update.message or update.channel_post

    if not message:
        return

    if not message.document:
        return

    file_id = message.document.file_id
    file_name = message.document.file_name

    cursor.execute(
        "INSERT OR IGNORE INTO files (file_id, file_name) VALUES (?, ?)",
        (file_id, file_name)
    )
    conn.commit()

    print("Indexed:", file_name)

# ================= DEBUG ALL =================
async def debug_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("UPDATE RECEIVED:", update)


# ================= RUN =================
app = ApplicationBuilder().token(TOKEN).build()

# Start command
app.add_handler(CommandHandler("start", start))

# Save documents (index real file_id)
app.add_handler(MessageHandler(filters.Document.ALL, save_file))

# Search text messages
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search))

# Verify join button
app.add_handler(CallbackQueryHandler(verify_join, pattern="verify_join"))

print("Clamy Premium Bot Running...")
app.run_polling()
