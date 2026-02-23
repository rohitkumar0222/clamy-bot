import asyncio
import time
import sqlite3
from datetime import datetime, timedelta
import random
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
# ================= MAINTENANCE =================
MAINTENANCE_MODE = False

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

RESULTS_PER_PAGE = 10
# ================= MEMBERSHIP CHECK =================
async def check_membership(user_id, context):

    import asyncio

    for _ in range(3):  # retry 3 times to fix first-time join delay
        try:
            member = await context.bot.get_chat_member(CHANNEL_ID, user_id)

            # Only block if explicitly left or kicked
            if member.status not in ["left", "kicked"]:
                return True

        except Exception as e:
            print("Membership check error:", e)

        await asyncio.sleep(1)

    return False
def get_matching_files(query):
    from rapidfuzz import fuzz

    cursor.execute("SELECT file_id, file_name FROM files")
    rows = cursor.fetchall()

    matches = []
    query = query.lower().strip()
    query_words = query.split()

    if len(query) < 2:
        return []

    for file_id, file_name in rows:
        name = file_name.lower().replace(".pdf", "").strip()
        name_words = name.split()

        # 1️⃣ Exact full match
        if query == name:
            matches.append((130, file_id, file_name))
            continue

        # 2️⃣ All words present (strong multi-word match)
        if all(word in name_words for word in query_words):
            matches.append((115, file_id, file_name))
            continue

        # 3️⃣ Partial multi-word overlap (at least 50% words match)
        overlap = len(set(query_words) & set(name_words))
        if overlap >= max(1, len(query_words) // 2):
            matches.append((100 + overlap, file_id, file_name))
            continue

        # 4️⃣ Strong contains
        if query in name:
            matches.append((95, file_id, file_name))
            continue

        # 5️⃣ Fuzzy logic (dynamic threshold)
        score = fuzz.token_set_ratio(query, name)

        # Lower threshold for long queries
        if len(query_words) >= 4:
            threshold = 75
        elif len(query_words) == 3:
            threshold = 85
        else:
            threshold = 92

        if score >= threshold:
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
    chat_id = update.effective_chat.id

    member_number = get_or_create_member(user.id)

    # ⏰ Time Based Greeting
    hour = datetime.now().hour

    if 5 <= hour < 12:
        time_greet = "🌅 Good Morning"
    elif 12 <= hour < 17:
        time_greet = "🌤 Good Afternoon"
    elif 17 <= hour < 21:
        time_greet = "🌇 Good Evening"
    else:
        time_greet = "🌙 Good Night"

    # 🎯 Premium Nicknames
    nicknames = [
        "Future Topper 🩺",
        "Medical Star ✨",
        "Rising Doctor 🔥",
        "Sharp Mind 💡",
        "Champion Scholar 🌟",
        "Clinical Master 💊",
        "Elite Aspirant 🧠"
    ]

    nickname = random.choice(nicknames)

    greeting_text = (
        "━━━━━━━━━━━━━━━━━━\n"
        f"{time_greet}, {nickname}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "👩🏻‍⚕️ <b>Clamy</b>\n"
        "<i>Personal Assistant of Dr. Rohit Madhukar 🩺</i>\n\n"
        f"🛡 <b>Verified Member ID:</b> #{member_number}\n\n"
        "📚 <b>Smart PDF Search Engine Activated</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🔎 <b>Type any subject or file name.</b>\n"
        "I’ll deliver the best matches instantly.\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    msg = await update.message.reply_text(
        greeting_text,
        parse_mode="HTML"
    )

    # Store IDs for later deletion
    context.user_data["greeting_id"] = msg.message_id
    context.user_data["start_msg_id"] = update.message.message_id

# ================= ADMIN LOG SYSTEM =================
async def notify_admin_search(user, query, status, context, delivered_count=0):

    try:
        member_number = get_or_create_member(user.id)
        username = f"@{user.username}" if user.username else "No Username"

        message = (
            "━━━━━━━━━━━━━━━━━━\n"
            "📊 CLAMY SEARCH REPORT\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Name       : {user.full_name}\n"
            f"📛 Username   : {username}\n"
            f"🆔 User ID    : {user.id}\n"
            f"🛡 Member ID  : #{member_number}\n\n"
            f"🔎 Query      : {query}\n\n"
            f"📦 Status     : {status}\n"
            f"📁 Files Sent : {delivered_count}\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=message
        )

    except Exception as e:
        print("Admin log error:", e)

# ================= INTELLIGENT SEARCH =================
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.message.text:
        return

    user = update.message.from_user
    chat_id = update.effective_chat.id
    query_text = update.message.text.strip()

    if len(query_text) < 2 or query_text.startswith("/"):
        return

    # ===== MEMBERSHIP CHECK =====
    joined = await check_membership(user.id, context)

    if not joined:
        pending_searches[user.id] = query_text

        keyboard = [[
            InlineKeyboardButton("🔔 Join Channel", url=CHANNEL_INVITE_LINK),
            InlineKeyboardButton("✅ I Joined", callback_data="verify_join")
        ]]

        join_msg = await update.message.reply_text(
            "🔒 Please join the channel to continue.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        context.user_data["join_msg_id"] = join_msg.message_id
        return

    # If already joined → run search flow
    await run_search_flow(chat_id, user, query_text, update, context)


# ================= DIRECT SEARCH FLOW =================
async def run_search_flow(chat_id, user, query_text, update, context):

    # ================= DELETE TEMP MESSAGES ONLY =================
    greeting_id = context.user_data.get("greeting_id")
    start_id = context.user_data.get("start_msg_id")
    join_id = context.user_data.get("join_msg_id")
    verified_id = context.user_data.get("verified_msg_id")

    for msg_id in [greeting_id, start_id, join_id, verified_id]:
        if msg_id:
            try:
                await context.bot.delete_message(chat_id, msg_id)
            except:
                pass

    # delete user search message
    try:
        if update and update.message:
            await update.message.delete()
    except:
        pass

    # ================= 5 SECOND PREMIUM ANIMATION =================
    stages = [
        ("🧠 Initializing Search Engine...", 20),
        ("🔎 Scanning Library...", 40),
        ("📊 Analyzing Matches...", 60),
        ("🧬 Ranking Results...", 80),
        ("⭐ Finalizing Results...", 100),
    ]

    progress_msg = await context.bot.send_message(chat_id, "Starting...")

    for text, percent in stages:
        bar = "▰" * (percent // 10) + "▱" * (10 - percent // 10)
        try:
            await progress_msg.edit_text(f"{text}\n\n{bar} {percent}%")
        except:
            pass
        await asyncio.sleep(1)

    try:
        await progress_msg.delete()
    except:
        pass

    # ================= FIND MATCHES =================
    matches = get_matching_files(query_text)

    if not matches:
        await notify_admin_search(user, query_text, "❌ No Results", context, 0)

        await context.bot.send_message(
            chat_id,
            "❌ No similar files found."
        )
        return

    matches.sort(reverse=True)

    context.user_data["matches"] = matches
    context.user_data["page"] = 0
    context.user_data["last_query"] = query_text

    await notify_admin_search(user, query_text, "🔎 Search Started", context, 0)

    await send_results_page(chat_id, context)

# ================= SEND RESULTS PAGE =================
async def send_results_page(chat_id, context):

    matches = context.user_data.get("matches", [])
    page = context.user_data.get("page", 0)

    if not matches:
        return

    start = page * RESULTS_PER_PAGE
    end = start + RESULTS_PER_PAGE
    page_matches = matches[start:end]

    buttons = []

    for index, (score, file_id, file_name) in enumerate(page_matches):
        global_index = start + index
        buttons.append([
            InlineKeyboardButton(
                text=file_name[:40],
                callback_data=f"select_{global_index}"
            )
        ])

    nav = []

    if page > 0:
        nav.append(InlineKeyboardButton("⬅ Previous", callback_data="prev_page"))

    if end < len(matches):
        nav.append(InlineKeyboardButton("Next ➡", callback_data="next_page"))

    if nav:
        buttons.append(nav)

    msg = await context.bot.send_message(
        chat_id,
        f"📂 {len(matches)} Results Found\n\nSelect a file:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

    active_results[chat_id] = [msg.message_id]


# ================= HANDLE BUTTON CALLBACKS =================
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query_obj = update.callback_query
    await query_obj.answer()

    chat_id = query_obj.message.chat_id
    data = query_obj.data
    matches = context.user_data.get("matches", [])
    user = query_obj.from_user

    # ----- VERIFY JOIN -----
    if data == "verify_join":
        await verify_join(update, context)
        return

    # ----- NEXT PAGE -----
    if data == "next_page":
        context.user_data["page"] += 1
        await query_obj.message.delete()
        await send_results_page(chat_id, context)
        return

    # ----- PREVIOUS PAGE -----
    if data == "prev_page":
        context.user_data["page"] -= 1
        await query_obj.message.delete()
        await send_results_page(chat_id, context)
        return

    # ----- SELECT FILE -----
    if data.startswith("select_"):

        index = int(data.split("_")[1])

        if index >= len(matches):
            return

        score, file_id, file_name = matches[index]

        # delete result buttons
        if chat_id in active_results:
            for msg_id in active_results[chat_id]:
                try:
                    await context.bot.delete_message(chat_id, msg_id)
                except:
                    pass

        try:
            sent = await context.bot.send_document(
                chat_id,
                file_id,
                caption=f"📄 {file_name}\n⭐ Match Confidence: {round(score,1)}%"
            )

            await notify_admin_search(
                user,
                context.user_data.get("last_query", ""),
                "✅ Delivered",
                context,
                1
            )

            await send_footer(chat_id, context, [sent.message_id])

        except:
            await notify_admin_search(
                user,
                context.user_data.get("last_query", ""),
                "❌ Delivery Failed",
                context,
                0
            )
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


# ================= VERIFY JOIN =================
async def verify_join(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    user = query.from_user
    chat_id = user.id

    joined = await check_membership(user.id, context)

    if not joined:
        await query.edit_message_text(
            "❌ Membership not detected.\n\nPlease join first."
        )
        return

    # Delete join message
    try:
        await query.message.delete()
    except:
        pass

    # Show greeting again
    await context.bot.send_message(chat_id, "✅ Membership Verified.")

    # If pending search exists → run search
    if user.id in pending_searches:
        query_text = pending_searches.pop(user.id)
        await run_search_flow(chat_id, user, query_text, None, context)

# ================= PREMIUM FOOTER SYSTEM =================
async def send_footer(chat_id, context, sent_ids):

    from datetime import datetime, timedelta
    import random

    motivations = [
        "Discipline compounds advantage.",
        "Consistency builds mastery.",
        "Focused effort wins long term.",
        "Precision creates distinction."
    ]

    end_time = datetime.now() + timedelta(minutes=60)
    motivation_line = random.choice(motivations)

    panel_text = (
        "━━━━━━━━━━━━━━━━━━\n"
        "🔐 𝐒𝐄𝐂𝐔𝐑𝐄 𝐀𝐂𝐂𝐄𝐒𝐒 𝐏𝐀𝐍𝐄𝐋\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🧠 {motivation_line}\n\n"
        "⏳ 60:00 remaining\n"
        "🟩🟩🟩🟩🟩🟩 100%\n\n"
        "📥 Save or Forward before expiry\n"
        "⚠ Auto-deletes in 60 minutes\n"
        "🏥 Doctor’s Pustakalay 🩺"
    )

    panel = await context.bot.send_message(chat_id, panel_text)

    # add footer to deletion list
    sent_ids.append(panel.message_id)

    # 🔥 Realtime Update Every 60 Seconds
    context.job_queue.run_repeating(
        update_footer_panel,
        interval=60,
        first=60,
        data={
            "chat_id": chat_id,
            "message_id": panel.message_id,
            "end_time": end_time,
            "sent_ids": sent_ids,
            "motivation": motivation_line
        }
    )
# ================= LIVE FOOTER UPDATER =================
async def update_footer_panel(context):

    from datetime import datetime

    job = context.job
    chat_id = job.data["chat_id"]
    message_id = job.data["message_id"]
    end_time = job.data["end_time"]
    sent_ids = job.data["sent_ids"]
    motivation = job.data["motivation"]

    total_seconds = 60 * 60
    remaining = int((end_time - datetime.now()).total_seconds())

    # ===== EXPIRED =====
    if remaining <= 0:

        for msg_id in sent_ids:
            try:
                await context.bot.delete_message(chat_id, msg_id)
            except:
                pass

        job.schedule_removal()
        return

    # ===== CALCULATE TIME =====
    mins = remaining // 60
    secs = remaining % 60
    percent = int((remaining / total_seconds) * 100)

    # ===== PROGRESS COLOR LOGIC =====
    if remaining > 40 * 60:
        progress_bar = "🟩🟩🟩🟩🟩🟩"
    elif remaining > 20 * 60:
        progress_bar = "🟧🟧🟧🟧⬜⬜"
    else:
        progress_bar = "🟥🟥⬜⬜⬜⬜"

    panel_text = (
        "━━━━━━━━━━━━━━━━━━\n"
        "🔐 𝐒𝐄𝐂𝐔𝐑𝐄 𝐀𝐂𝐂𝐄𝐒𝐒 𝐏𝐀𝐍𝐄𝐋\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🧠 {motivation}\n\n"
        f"⏳ {mins:02d}:{secs:02d} remaining\n"
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

# ================= AUTO DELETE BUTTON PAGE =================
async def auto_delete_results(context):

    job = context.job
    chat_id = job.data["chat_id"]

    if chat_id in active_results:
        for msg_id in active_results[chat_id]:
            try:
                await context.bot.delete_message(chat_id, msg_id)
            except:
                pass

        active_results.pop(chat_id, None)
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

# ================= MAINTENANCE COMMAND =================
async def maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MAINTENANCE_MODE

    if update.effective_user.id != ADMIN_ID:
        return

    if context.args and context.args[0].lower() == "on":
        MAINTENANCE_MODE = True
        await update.message.reply_text("🛠 Maintenance ENABLED")
    else:
        MAINTENANCE_MODE = False
        await update.message.reply_text("✅ Maintenance DISABLED")

# ================= SAVE DOCUMENT =================
async def save_document(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.message.document:
        return

    document = update.message.document
    file_id = document.file_id
    file_name = document.file_name

    try:
        cursor.execute(
            "INSERT OR IGNORE INTO files (file_id, file_name) VALUES (?, ?)",
            (file_id, file_name)
        )
        conn.commit()

        await update.message.reply_text("✅ File indexed successfully.")
        print("Indexed:", file_name)

    except Exception as e:
        print("Index error:", e)

# ================= HARD DELETE FUNCTION =================
async def delete_all_messages(context):
    data = context.job.data
    chat_id = data["chat_id"]
    message_ids = data["message_ids"]

    for msg_id in message_ids:
        try:
            await context.bot.delete_message(chat_id, msg_id)
        except:
            pass

# ================= RUN =================

app = ApplicationBuilder().token(TOKEN).build()

# ---- START COMMAND ----
app.add_handler(CommandHandler("start", start))

# ---- SEARCH TEXT ----
app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        search
    )
)

# ---- VERIFY JOIN BUTTON (only this pattern) ----
app.add_handler(
    CallbackQueryHandler(
        verify_join,
        pattern="^verify_join$"
    )
)

# ---- RESULT BUTTONS (pagination + select) ----
app.add_handler(
    CallbackQueryHandler(
        handle_buttons,
        pattern="^(next_page|prev_page|select_.*|suggest)$"
    )
)

print("Clamy Premium Bot Running...")
app.run_polling()
