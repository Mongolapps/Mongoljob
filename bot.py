import logging
import os
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
    get_approved_jobs,
    get_job,
    get_pending_jobs,
    get_user,
    init_db,
    reject_job,
    save_user,
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

(
    PROFILE_NAME,
    PROFILE_PHONE,
    PROFILE_PROFESSION,
    PROFILE_EXPERIENCE,
    PROFILE_SALARY,
    JOB_COMPANY,
    JOB_TITLE,
    JOB_SALARY,
    JOB_LOCATION,
    JOB_DESCRIPTION,
) = range(10)

MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["🔍 Ажил хайх"],
        ["👤 Миний анкет", "📢 Ажлын зар оруулах"],
        ["ℹ️ Тусламж"],
    ],
    resize_keyboard=True,
)


def job_text(job) -> str:
    return (
        f"💼 <b>{escape(job['title']).upper()}</b>\n\n"
        f"🏢 Компани: {escape(job['company'])}\n"
        f"💰 Цалин: {escape(job['salary'])}\n"
        f"📍 Байршил: {escape(job['location'])}\n"
        f"🕐 Ажлын төрөл: Бүтэн цаг\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 <b>Шаардлага</b>\n"
        f"{escape(job['description'])}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 Зарын дугаар: #{job['id']}\n\n"
        f"👇 Доорх товчоор анкетаа илгээнэ үү."
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Сайн байна уу! 👋\n\n"
        "Ажил хайгч болон ажил олгогчийг холбох ботод тавтай морил.",
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
    await update.message.reply_text("Цалин:")
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
        keyboard = InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("✅ Батлах", callback_data=f"approve:{job_id}"),
                InlineKeyboardButton("❌ Татгалзах", callback_data=f"reject:{job_id}"),
            ]]
        )
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
    jobs = get_approved_jobs()

    if not jobs:
        await update.message.reply_text("Одоогоор батлагдсан ажлын зар алга.")
        return

    for job in jobs:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📨 Анкет илгээх",
                        callback_data=f"apply:{job['id']}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "ℹ️ Дэлгэрэнгүй",
                        callback_data=f"detail:{job['id']}",
                    ),
                    InlineKeyboardButton(
                        "⭐ Хадгалах",
                        callback_data=f"save:{job['id']}",
                    ),
                ],
            ]
        )

        await update.message.reply_text(
            job_text(job),
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )


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
        await query.answer("Танд админы эрх байхгүй.", show_alert=True)
        return

    action, raw_id = query.data.split(":")
    job_id = int(raw_id)
    job = get_job(job_id)

    if not job:
        await query.answer("Зар олдсонгүй.", show_alert=True)
        return

    if action == "approve":
        changed = approve_job(job_id)
        status_text = "✅ Батлагдсан"
        employer_message = f"✅ Таны #{job_id} дугаартай ажлын зар батлагдлаа."
    else:
        changed = reject_job(job_id)
        status_text = "❌ Татгалзсан"
        employer_message = f"❌ Таны #{job_id} дугаартай ажлын зар татгалзагдлаа."

    if not changed:
        await query.answer(
            "Энэ зар өмнө нь шийдвэрлэгдсэн байна.",
            show_alert=True,
        )
        return

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(f"{status_text}: зар #{job_id}")
    await query.answer()

    try:
        await context.bot.send_message(job["employer_id"], employer_message)
    except Exception:
        logger.exception("Ажил олгогчид шийдвэр хүрсэнгүй")


async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        return

    jobs = get_pending_jobs()
    if not jobs:
        await update.message.reply_text("Хүлээгдэж буй зар алга.")
        return

    for job in jobs:
        keyboard = InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("✅ Батлах", callback_data=f"approve:{job['id']}"),
                InlineKeyboardButton("❌ Татгалзах", callback_data=f"reject:{job['id']}"),
            ]]
        )
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

    app.add_handler(profile_conversation)
    app.add_handler(job_conversation)

    app.add_handler(
        MessageHandler(filters.Regex("^🔍 Ажил хайх$"), browse_jobs)
    )
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
        CallbackQueryHandler(admin_action, pattern=r"^(approve|reject):\d+$")
    )

    print("Бот ажиллаж эхэллээ...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
