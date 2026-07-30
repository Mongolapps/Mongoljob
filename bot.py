import logging
import os
import re
from html import escape

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from database import (
    add_job,
    apply_to_job,
    approve_job,
    get_approved_jobs_by_category,
    get_job,
    get_pending_jobs,
    get_user,
    init_db,
    reject_job,
    save_user,
    set_job_plan,
    stats,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN олдсонгүй. .env файлаа шалгана уу.")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

CATEGORIES = [
    "🏥 Эрүүл мэнд", "☕ Үйлчилгээ", "🚗 Жолооч", "🏗 Барилга",
    "💻 IT", "📊 Оффис", "🛒 Худалдаа", "🍔 Ресторан",
    "🏭 Үйлдвэр", "📦 Ложистик", "🎓 Боловсрол", "🔧 Инженер",
]

(
    PROFILE_NAME,
    PROFILE_PHONE,
    PROFILE_PROFESSION,
    PROFILE_EXPERIENCE,
    PROFILE_SALARY,
    JOB_COMPANY,
    JOB_TITLE,
    JOB_CATEGORY,
    JOB_SALARY,
    JOB_LOCATION,
    JOB_DESCRIPTION,
) = range(11)

MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["🔍 Ажил хайх"],
        ["👤 Миний анкет", "📢 Ажлын зар оруулах"],
        ["ℹ️ Тусламж"],
    ],
    resize_keyboard=True,
)

CATEGORY_MENU = ReplyKeyboardMarkup(
    [
        [CATEGORIES[0], CATEGORIES[1]], [CATEGORIES[2], CATEGORIES[3]],
        [CATEGORIES[4], CATEGORIES[5]], [CATEGORIES[6], CATEGORIES[7]],
        [CATEGORIES[8], CATEGORIES[9]], [CATEGORIES[10], CATEGORIES[11]],
        ["🔙 Үндсэн цэс"],
    ], resize_keyboard=True,
)


def job_text(job) -> str:
    plan = job["plan"] if "plan" in job.keys() else "free"
    badge = "👑 <b>VIP ЗАР</b>\n\n" if plan == "vip" else ("⭐ <b>PREMIUM ЗАР</b>\n\n" if plan == "premium" else "")
    category = job["category"] or "📂 Бусад"
    return (
        f"{badge}💼 <b>{escape(job['title']).upper()}</b>\n\n"
        f"🏢 <b>{escape(job['company'])}</b>\n"
        f"📂 {escape(category)}\n"
        f"📍 {escape(job['location'])}\n"
        f"💰 <b>{escape(job['salary'])}</b>\n"
        f"🕐 Бүтэн цаг\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 <b>ТАВИГДАХ ШААРДЛАГА</b>\n\n"
        f"{escape(job['description'])}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🟢 Идэвхтэй зар\n🆔 Зарын дугаар: #{job['id']}"
    )

def admin_review_buttons(job_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Энгийн", callback_data=f"approve_free:{job_id}"),
         InlineKeyboardButton("⭐ Premium 7 хоног", callback_data=f"approve_premium:{job_id}")],
        [InlineKeyboardButton("👑 VIP 30 хоног", callback_data=f"approve_vip:{job_id}"),
         InlineKeyboardButton("❌ Татгалзах", callback_data=f"reject:{job_id}")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🇲🇳 <b>MONGOL JOB</b>\n\n"
        "Ажил хайгч болон ажил олгогчийг холбох ухаалаг платформд тавтай морил. 👋",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_MENU,
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "Үйлдлийг цуцаллаа.",
        reply_markup=MAIN_MENU,
    )
    return ConversationHandler.END


async def profile_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Овог нэрээ оруулна уу:")
    return PROFILE_NAME


async def profile_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["full_name"] = update.message.text.strip()
    await update.message.reply_text("Утасны дугаараа оруулна уу:")
    return PROFILE_PHONE


async def profile_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["phone"] = update.message.text.strip()
    await update.message.reply_text("Мэргэжил эсвэл хийж чадах ажлаа бичнэ үү:")
    return PROFILE_PROFESSION


async def profile_profession(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["profession"] = update.message.text.strip()
    await update.message.reply_text("Ажлын туршлагаа бичнэ үү:")
    return PROFILE_EXPERIENCE


async def profile_experience(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["experience"] = update.message.text.strip()
    await update.message.reply_text("Хүсэж буй цалингаа оруулна уу:")
    return PROFILE_SALARY


async def profile_salary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    context.user_data["desired_salary"] = update.message.text.strip()
    context.user_data["telegram_id"] = user.id
    context.user_data["username"] = user.username

    save_user(context.user_data)
    context.user_data.clear()

    await update.message.reply_text(
        "✅ Таны анкет амжилттай хадгалагдлаа.",
        reply_markup=MAIN_MENU,
    )
    return ConversationHandler.END


async def job_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    context.user_data["employer_id"] = user.id
    context.user_data["employer_username"] = user.username
    await update.message.reply_text("Компанийн нэрээ оруулна уу:")
    return JOB_COMPANY


async def job_company(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["company"] = update.message.text.strip()
    await update.message.reply_text("Ажлын байрны нэр:")
    return JOB_TITLE


async def job_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["title"] = update.message.text.strip()
    await update.message.reply_text("📂 Ангиллаа сонгоно уу:", reply_markup=CATEGORY_MENU)
    return JOB_CATEGORY

async def job_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    selected = update.message.text.strip()
    if selected == "🔙 Үндсэн цэс":
        return await cancel(update, context)
    if selected not in CATEGORIES:
        await update.message.reply_text("Доорх товчнуудаас ангиллаа сонгоно уу.", reply_markup=CATEGORY_MENU)
        return JOB_CATEGORY
    context.user_data["category"] = selected
    await update.message.reply_text("💰 Цалин:")
    return JOB_SALARY


async def job_salary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["salary"] = update.message.text.strip()
    await update.message.reply_text("Ажлын байршил:")
    return JOB_LOCATION


async def job_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["location"] = update.message.text.strip()
    await update.message.reply_text(
        "Ажлын үүрэг болон тавигдах шаардлагыг дэлгэрэнгүй бичнэ үү:"
    )
    return JOB_DESCRIPTION


async def job_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["description"] = update.message.text.strip()
    job_id = add_job(context.user_data)
    job = get_job(job_id)
    context.user_data.clear()

    await update.message.reply_text(
        f"✅ Зар хүлээн авлаа.\n"
        f"Зарын дугаар: #{job_id}\n"
        "Админ баталсны дараа нийтлэгдэнэ.",
        reply_markup=MAIN_MENU,
    )

    if ADMIN_ID and job:
        keyboard = admin_review_buttons(job_id)
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text="🆕 <b>Шинэ ажлын зар</b>\n\n" + job_text(job),
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        except Exception:
            logger.exception("Админд мэдэгдэл хүрсэнгүй")

    return ConversationHandler.END


async def browse_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📂 <b>АЖЛЫН АНГИЛАЛ</b>\n\nСонирхсон салбараа сонгоно уу 👇",
        parse_mode=ParseMode.HTML, reply_markup=CATEGORY_MENU,
    )

async def category_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    category = update.message.text.strip()
    jobs = get_approved_jobs_by_category(category)
    if not jobs:
        await update.message.reply_text(f"{category} ангилалд одоогоор зар алга.", reply_markup=CATEGORY_MENU)
        return
    await update.message.reply_text(f"{category} — {len(jobs)} зар олдлоо.", reply_markup=CATEGORY_MENU)
    for job in jobs:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📨 Анкет илгээх", callback_data=f"apply:{job['id']}")],
            [InlineKeyboardButton("ℹ️ Дэлгэрэнгүй", callback_data=f"detail:{job['id']}"),
             InlineKeyboardButton("⭐ Хадгалах", callback_data=f"save:{job['id']}")]])
        await update.message.reply_text(job_text(job), parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def apply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    job_id = int(query.data.split(":")[1])
    applicant = get_user(query.from_user.id)

    if not applicant:
        await query.answer(
            "Эхлээд 'Миний анкет' хэсэгт анкетаа бөглөнө үү.",
            show_alert=True,
        )
        return

    job = get_job(job_id)
    if not job or job["status"] != "approved":
        await query.answer("Энэ зар идэвхгүй байна.", show_alert=True)
        return

    if not apply_to_job(job_id, query.from_user.id):
        await query.answer(
            "Та энэ ажилд өмнө нь хүсэлт илгээсэн байна.",
            show_alert=True,
        )
        return

    await query.answer("Хүсэлт амжилттай илгээгдлээ!", show_alert=True)

    applicant_text = (
        "📩 <b>Шинэ ажил горилогч</b>\n\n"
        f"💼 {escape(job['title'])}\n"
        f"👤 {escape(applicant['full_name'])}\n"
        f"📞 {escape(applicant['phone'])}\n"
        f"🧰 {escape(applicant['profession'])}\n"
        f"📚 {escape(applicant['experience'])}\n"
        f"💰 {escape(applicant['desired_salary'])}"
    )

    try:
        await context.bot.send_message(
            chat_id=job["employer_id"],
            text=applicant_text,
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        logger.exception("Ажил олгогчид мэдэгдэл хүрсэнгүй")


async def detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    job_id = int(query.data.split(":")[1])
    job = get_job(job_id)

    if not job:
        await query.answer("Зар олдсонгүй.", show_alert=True)
        return

    await query.answer()
    await query.message.reply_text(
        "ℹ️ <b>Дэлгэрэнгүй мэдээлэл</b>\n\n" + job_text(job),
        parse_mode=ParseMode.HTML,
    )


async def save_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("⭐ Хадгаллаа", show_alert=True)


async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("Танд админы эрх байхгүй.", show_alert=True); return
    action, raw_id = query.data.rsplit(":", 1); job_id = int(raw_id); job = get_job(job_id)
    if not job:
        await query.answer("Зар олдсонгүй.", show_alert=True); return
    if action == "approve_free":
        changed = approve_job(job_id, "free"); status_text="✅ Энгийн зар"; msg=f"✅ Таны #{job_id} зар батлагдлаа."
    elif action == "approve_premium":
        changed = approve_job(job_id, "premium", 7); status_text="⭐ Premium 7 хоног"; msg=f"⭐ Таны #{job_id} зар Premium эрхтэйгээр 7 хоног нийтлэгдлээ."
    elif action == "approve_vip":
        changed = approve_job(job_id, "vip", 30); status_text="👑 VIP 30 хоног"; msg=f"👑 Таны #{job_id} зар VIP эрхтэйгээр 30 хоног нийтлэгдлээ."
    else:
        changed = reject_job(job_id); status_text="❌ Татгалзсан"; msg=f"❌ Таны #{job_id} зар татгалзагдлаа."
    if not changed:
        await query.answer("Энэ зар өмнө нь шийдвэрлэгдсэн байна.", show_alert=True); return
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(f"{status_text}: зар #{job_id}")
    await query.answer()
    try: await context.bot.send_message(job["employer_id"], msg)
    except Exception: logger.exception("Ажил олгогчид шийдвэр хүрсэнгүй")

async def premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID: return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Ашиглах: /premium 25"); return
    job_id=int(context.args[0]); job=get_job(job_id)
    if not job or job["status"] != "approved":
        await update.message.reply_text("Батлагдсан зар олдсонгүй."); return
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Энгийн", callback_data=f"plan_free:{job_id}"),
        InlineKeyboardButton("⭐ Premium 7 хоног", callback_data=f"plan_premium:{job_id}")],
        [InlineKeyboardButton("👑 VIP 30 хоног", callback_data=f"plan_vip:{job_id}")]])
    await update.message.reply_text(f"Зар #{job_id}-ийн эрхийг сонгоно уу:", reply_markup=kb)

async def plan_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q=update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer("Танд админы эрх байхгүй.", show_alert=True); return
    action, raw_id=q.data.rsplit(":",1); job_id=int(raw_id)
    if action=="plan_free": changed=set_job_plan(job_id,"free"); msg="Энгийн зар болголоо."
    elif action=="plan_premium": changed=set_job_plan(job_id,"premium",7); msg="Premium 7 хоног идэвхжлээ."
    else: changed=set_job_plan(job_id,"vip",30); msg="VIP 30 хоног идэвхжлээ."
    await q.answer(msg if changed else "Зар олдсонгүй.", show_alert=True)


async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        return

    jobs = get_pending_jobs()
    if not jobs:
        await update.message.reply_text("Хүлээгдэж буй зар алга.")
        return

    for job in jobs:
        keyboard = admin_review_buttons(job["id"])
        await update.message.reply_text(
            job_text(job),
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        return

    data = stats()
    await update.message.reply_text(
        "📊 Ботын статистик\n\n"
        f"👥 Анкет: {data['users']}\n"
        f"📢 Нийт зар: {data['jobs']}\n"
        f"✅ Батлагдсан зар: {data['approved']}\n"
        f"💎 Premium/VIP: {data['premium']}\n"
        f"📩 Хүсэлт: {data['applications']}"
    )


async def help_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👤 Ажил хайгч:\n"
        "1. 'Миний анкет'-аа бөглөнө.\n"
        "2. 'Ажил хайх'-аас зар сонгоно.\n"
        "3. 'Анкет илгээх' товч дарна.\n\n"
        "🏢 Ажил олгогч:\n"
        "1. 'Ажлын зар оруулах' товч дарна.\n"
        "2. Мэдээллээ бөглөнө.\n"
        "3. Админ баталсны дараа зар нийтлэгдэнэ.\n\n"
        "/cancel — одоогийн бөглөлтийг цуцлах"
    )


def main() -> None:
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    profile_conversation = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^👤 Миний анкет$"), profile_start)
        ],
        states={
            PROFILE_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_name)
            ],
            PROFILE_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_phone)
            ],
            PROFILE_PROFESSION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_profession)
            ],
            PROFILE_EXPERIENCE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_experience)
            ],
            PROFILE_SALARY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_salary)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    job_conversation = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^📢 Ажлын зар оруулах$"), job_start)
        ],
        states={
            JOB_COMPANY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, job_company)
            ],
            JOB_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, job_title)
            ],
            JOB_CATEGORY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, job_category)
            ],
            JOB_SALARY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, job_salary)
            ],
            JOB_LOCATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, job_location)
            ],
            JOB_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, job_description)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("pending", pending))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("premium", premium_command))

    app.add_handler(profile_conversation)
    app.add_handler(job_conversation)

    app.add_handler(
        MessageHandler(filters.Regex("^🔍 Ажил хайх$"), browse_jobs)
    )
    app.add_handler(MessageHandler(filters.Regex("^🔙 Үндсэн цэс$"), start))
    app.add_handler(MessageHandler(filters.Regex("^(" + "|".join(map(re.escape, CATEGORIES)) + ")$"), category_jobs))
    app.add_handler(
        MessageHandler(filters.Regex("^ℹ️ Тусламж$"), help_message)
    )

    app.add_handler(
        CallbackQueryHandler(apply_callback, pattern=r"^apply:\d+$")
    )
    app.add_handler(
        CallbackQueryHandler(detail_callback, pattern=r"^detail:\d+$")
    )
    app.add_handler(
        CallbackQueryHandler(save_callback, pattern=r"^save:\d+$")
    )
    app.add_handler(
        CallbackQueryHandler(admin_action, pattern=r"^(approve_free|approve_premium|approve_vip|reject):\d+$")
    )
    app.add_handler(CallbackQueryHandler(plan_action, pattern=r"^(plan_free|plan_premium|plan_vip):\d+$"))

    print("Бот ажиллаж эхэллээ...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
