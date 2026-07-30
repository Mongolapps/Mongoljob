import logging
import os
import re
from datetime import datetime, timezone
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
    approve_job,
    create_or_get_match,
    get_approved_jobs_by_category,
    get_job,
    get_match,
    get_pending_jobs,
    get_user,
    init_db,
    mark_match_paid,
    reject_job,
    save_user,
    set_employer_decision,
    set_job_plan,
    set_payment_requested,
    stats,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
MATCH_PRICE = int(os.getenv("MATCH_PRICE", "3000"))
PAYMENT_INSTRUCTIONS = os.getenv(
    "PAYMENT_INSTRUCTIONS",
    "Данс: ТӨЛБӨРИЙН ДАНСАА .env файлд PAYMENT_INSTRUCTIONS утгаар оруулна уу.",
).strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN олдсонгүй. Railway Variables эсвэл .env файлаа шалгана уу.")

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
    ],
    resize_keyboard=True,
)


def _premium_remaining(expires_at: str | None) -> str:
    if not expires_at:
        return ""
    try:
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        seconds = int((expires - now).total_seconds())
    except (TypeError, ValueError):
        return ""

    if seconds <= 0:
        return "🔴 Premium хугацаа дууссан"
    days, rem = divmod(seconds, 86400)
    hours = rem // 3600
    if days == 0 and hours <= 24:
        return f"🔴 Premium үлдсэн: {max(hours, 1)} цаг"
    if days <= 2:
        return f"🟡 Premium үлдсэн: {days} хоног {hours} цаг"
    return f"🟢 Premium үлдсэн: {days} хоног {hours} цаг"


def job_text(job) -> str:
    plan = job["plan"] if "plan" in job.keys() else "free"
    active_premium = plan in {"premium", "vip"} and bool(
        job["premium_expires_at"] and _premium_remaining(job["premium_expires_at"])
        != "🔴 Premium хугацаа дууссан"
    )
    badge = ""
    if active_premium:
        badge = "👑 <b>VIP ЗАР</b>\n\n" if plan == "vip" else "⭐ <b>PREMIUM ЗАР</b>\n\n"

    category = job["category"] or "📂 Бусад"
    remaining = _premium_remaining(job["premium_expires_at"]) if active_premium else ""

    lines = [
        badge.rstrip(),
        f"🏢 <b>{escape(job['company'])}</b>",
        "",
        f"💼 Албан тушаал: <b>{escape(job['title'])}</b>",
        f"📂 {escape(category)}",
        f"📍 {escape(job['location'])}",
        f"💰 <b>{escape(job['salary'])}</b> / сар",
        "🕒 Бүтэн цаг",
        "",
        "📌 <b>Шаардлага</b>",
        escape(job["description"]),
        "",
        "🟢 Идэвхтэй",
    ]
    if remaining:
        lines.append(remaining)
    lines.append(f"🆔 Зар #{job['id']}")
    return "\n".join(line for line in lines if line is not None)


def calculate_match_score(applicant, job) -> int:
    """Эхний хувилбарын тайлбарлагдахуйц энгийн Match алгоритм."""
    score = 40
    profession = applicant["profession"].lower()
    title = job["title"].lower()
    description = job["description"].lower()
    location = job["location"].lower()
    desired_salary = applicant["desired_salary"].lower()

    profession_words = {w for w in re.findall(r"\w+", profession) if len(w) >= 3}
    job_words = {w for w in re.findall(r"\w+", title + " " + description) if len(w) >= 3}
    overlap = len(profession_words & job_words)
    score += min(overlap * 10, 30)

    if any(word in location for word in re.findall(r"\w+", profession)):
        score += 5

    applicant_numbers = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", desired_salary)]
    job_numbers = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", job["salary"])]
    if applicant_numbers and job_numbers:
        desired = max(applicant_numbers)
        offered = max(job_numbers)
        if offered >= desired:
            score += 20
        elif offered >= desired * 0.8:
            score += 10

    experience_numbers = [int(x) for x in re.findall(r"\d+", applicant["experience"])]
    requirement_numbers = [int(x) for x in re.findall(r"(\d+)\s*\+?\s*жил", description)]
    if not requirement_numbers:
        score += 10
    elif experience_numbers and max(experience_numbers) >= max(requirement_numbers):
        score += 10

    return max(50, min(score, 99))


def admin_review_buttons(job_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Энгийн", callback_data=f"approve_free:{job_id}"),
            InlineKeyboardButton("⭐ Premium 7 хоног", callback_data=f"approve_premium:{job_id}"),
        ],
        [
            InlineKeyboardButton("👑 VIP 30 хоног", callback_data=f"approve_vip:{job_id}"),
            InlineKeyboardButton("❌ Татгалзах", callback_data=f"reject:{job_id}"),
        ],
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
    await update.message.reply_text("Үйлдлийг цуцаллаа.", reply_markup=MAIN_MENU)
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
    context.user_data.update(
        desired_salary=update.message.text.strip(),
        telegram_id=user.id,
        username=user.username,
    )
    save_user(context.user_data)
    context.user_data.clear()
    await update.message.reply_text("✅ Таны анкет амжилттай хадгалагдлаа.", reply_markup=MAIN_MENU)
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
    await update.message.reply_text("Ажлын үүрэг болон тавигдах шаардлагыг дэлгэрэнгүй бичнэ үү:")
    return JOB_DESCRIPTION


async def job_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["description"] = update.message.text.strip()
    job_id = add_job(context.user_data)
    job = get_job(job_id)
    context.user_data.clear()

    await update.message.reply_text(
        f"✅ Зар хүлээн авлаа.\nЗарын дугаар: #{job_id}\nАдмин баталсны дараа нийтлэгдэнэ.",
        reply_markup=MAIN_MENU,
    )
    if ADMIN_ID and job:
        try:
            await context.bot.send_message(
                ADMIN_ID,
                "🆕 <b>Шинэ ажлын зар</b>\n\n" + job_text(job),
                parse_mode=ParseMode.HTML,
                reply_markup=admin_review_buttons(job_id),
            )
        except Exception:
            logger.exception("Админд мэдэгдэл хүрсэнгүй")
    return ConversationHandler.END


async def browse_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📂 <b>АЖЛЫН АНГИЛАЛ</b>\n\nСонирхсон салбараа сонгоно уу 👇",
        parse_mode=ParseMode.HTML,
        reply_markup=CATEGORY_MENU,
    )


async def category_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    category = update.message.text.strip()
    jobs = get_approved_jobs_by_category(category)
    if not jobs:
        await update.message.reply_text(f"{category} ангилалд одоогоор зар алга.", reply_markup=CATEGORY_MENU)
        return

    await update.message.reply_text(f"{category} — {len(jobs)} зар олдлоо.", reply_markup=CATEGORY_MENU)
    for job in jobs:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🤝 Match шалгах", callback_data=f"matchcheck:{job['id']}")],
            [InlineKeyboardButton("✅ Сонирхож байна", callback_data=f"interest:{job['id']}")],
            [
                InlineKeyboardButton("ℹ️ Дэлгэрэнгүй", callback_data=f"detail:{job['id']}"),
                InlineKeyboardButton("⭐ Хадгалах", callback_data=f"save:{job['id']}"),
            ],
        ])
        await update.message.reply_text(job_text(job), parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def match_check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    applicant = get_user(query.from_user.id)
    job_id = int(query.data.split(":")[1])
    job = get_job(job_id)

    if not applicant:
        await query.answer("Эхлээд 'Миний анкет' хэсэгт анкетаа бөглөнө үү.", show_alert=True)
        return
    if not job or job["status"] != "approved":
        await query.answer("Энэ зар идэвхгүй байна.", show_alert=True)
        return

    score = calculate_match_score(applicant, job)
    await query.answer()
    await query.message.reply_text(
        "🤖 <b>ТАНЫ MATCH ҮЗҮҮЛЭЛТ</b>\n\n"
        f"⭐ Match: <b>{score}%</b>\n\n"
        "✅ Мэргэжил ба шаардлагын нийцэл\n"
        "✅ Цалингийн нөхцөл\n"
        "✅ Туршлагын мэдээлэл\n\n"
        "Сонирхож байвал доорх товчийг дарна уу.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Сонирхож байна", callback_data=f"interest:{job_id}")]
        ]),
    )


async def interest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    applicant = get_user(query.from_user.id)
    job_id = int(query.data.split(":")[1])
    job = get_job(job_id)

    if not applicant:
        await query.answer("Эхлээд анкетаа бөглөнө үү.", show_alert=True)
        return
    if not job or job["status"] != "approved":
        await query.answer("Энэ зар идэвхгүй байна.", show_alert=True)
        return
    if query.from_user.id == job["employer_id"]:
        await query.answer("Өөрийн зар дээр Match хийх боломжгүй.", show_alert=True)
        return

    score = calculate_match_score(applicant, job)
    match_id, created = create_or_get_match(job_id, query.from_user.id, score)
    await query.answer(
        "Сонирхлоо илгээлээ." if created else "Та өмнө нь сонирхлоо илгээсэн байна.",
        show_alert=True,
    )

    if created:
        hidden_candidate = (
            "🤖 <b>ШИНЭ MATCH САНАЛ</b>\n\n"
            f"💼 {escape(job['title'])}\n"
            f"👤 {escape(applicant['full_name'])}\n"
            f"🧰 {escape(applicant['profession'])}\n"
            f"📚 {escape(applicant['experience'])}\n"
            f"💰 Хүссэн цалин: {escape(applicant['desired_salary'])}\n"
            f"⭐ Match: <b>{score}%</b>\n\n"
            "🔒 Утас болон Telegram мэдээлэл одоогоор нууц."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Ярилцлагад урих", callback_data=f"employer_yes:{match_id}")],
            [InlineKeyboardButton("❌ Татгалзах", callback_data=f"employer_no:{match_id}")],
        ])
        try:
            await context.bot.send_message(
                job["employer_id"],
                hidden_candidate,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        except Exception:
            logger.exception("Ажил олгогчид Match санал хүрсэнгүй")


async def employer_decision_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    action, raw_match_id = query.data.split(":")
    match_id = int(raw_match_id)
    match = get_match(match_id)

    if not match or query.from_user.id != match["employer_id"]:
        await query.answer("Энэ үйлдэлд эрхгүй.", show_alert=True)
        return

    accepted = action == "employer_yes"
    changed = set_employer_decision(match_id, accepted)
    if not changed:
        await query.answer("Энэ Match өмнө нь шийдвэрлэгдсэн.", show_alert=True)
        return

    await query.edit_message_reply_markup(reply_markup=None)
    if not accepted:
        await query.answer("Match-ийг татгалзлаа.", show_alert=True)
        try:
            await context.bot.send_message(match["applicant_id"], "ℹ️ Ажил олгогч энэ удаагийн Match саналыг үргэлжлүүлээгүй.")
        except Exception:
            logger.exception("Ажил хайгчид татгалзсан мэдэгдэл хүрсэнгүй")
        return

    await query.answer("Та зөвшөөрлөө. Админд мэдэгдэл очлоо.", show_alert=True)
    admin_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"💳 {MATCH_PRICE:,}₮ нэхэмжлэх", callback_data=f"admin_invoice:{match_id}")],
        [InlineKeyboardButton("❌ Match цуцлах", callback_data=f"admin_cancel:{match_id}")],
    ])
    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            "🔔 <b>ХОЁР ТАЛ ЗӨВШӨӨРСӨН MATCH</b>\n\n"
            f"🆔 Match #{match_id}\n"
            f"🏢 {escape(match['company'])}\n"
            f"💼 {escape(match['title'])}\n"
            f"👤 {escape(match['full_name'])}\n"
            f"⭐ Match: {match['score']}%\n\n"
            "Статус: ⏳ Төлбөр эхлүүлэхэд бэлэн",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_keyboard,
        )


async def admin_match_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("Танд админы эрх байхгүй.", show_alert=True)
        return

    action, raw_match_id = query.data.split(":")
    match_id = int(raw_match_id)
    match = get_match(match_id)
    if not match:
        await query.answer("Match олдсонгүй.", show_alert=True)
        return

    if action == "admin_cancel":
        set_employer_decision(match_id, False, force=True)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.answer("Match цуцлагдлаа.", show_alert=True)
        return

    changed = set_payment_requested(match_id, MATCH_PRICE)
    if not changed:
        await query.answer("Нэхэмжлэл өмнө нь илгээгдсэн эсвэл төлөгдсөн.", show_alert=True)
        return

    payment_text = (
        "💳 <b>ХОЛБОЛТЫН ТӨЛБӨР</b>\n\n"
        f"🆔 Match #{match_id}\n"
        f"💰 Төлөх дүн: <b>{MATCH_PRICE:,}₮</b>\n\n"
        f"{escape(PAYMENT_INSTRUCTIONS)}\n\n"
        "Гүйлгээний утга дээр Match дугаараа бичнэ үү.\n"
        "Төлсний дараа админ төлбөрийг баталгаажуулж, хоёр талын холбоо барих мэдээллийг нээнэ."
    )
    employer_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Төлбөр хийсэн", callback_data=f"payment_sent:{match_id}")]
    ])
    await context.bot.send_message(
        match["employer_id"],
        payment_text,
        parse_mode=ParseMode.HTML,
        reply_markup=employer_keyboard,
    )
    await query.edit_message_reply_markup(
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Төлбөр батлах", callback_data=f"admin_paid:{match_id}")]
        ])
    )
    await query.answer("3,000₮-ийн төлбөрийн заавар ажил олгогчид илгээгдлээ.", show_alert=True)


async def payment_sent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    match_id = int(query.data.split(":")[1])
    match = get_match(match_id)
    if not match or query.from_user.id != match["employer_id"]:
        await query.answer("Энэ төлбөрт эрхгүй.", show_alert=True)
        return

    await query.answer("Админд шалгуулах хүсэлт илгээгдлээ.", show_alert=True)
    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            f"💸 Match #{match_id}-ийн ажил олгогч төлбөр хийсэн гэж мэдэгдлээ.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Төлбөр батлах", callback_data=f"admin_paid:{match_id}")]
            ]),
        )


async def admin_paid_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("Танд админы эрх байхгүй.", show_alert=True)
        return

    match_id = int(query.data.split(":")[1])
    match = get_match(match_id)
    if not match:
        await query.answer("Match олдсонгүй.", show_alert=True)
        return
    if not mark_match_paid(match_id):
        await query.answer("Энэ төлбөр өмнө нь баталгаажсан.", show_alert=True)
        return

    applicant_username = f"@{match['applicant_username']}" if match["applicant_username"] else "байхгүй"
    employer_username = f"@{match['employer_username']}" if match["employer_username"] else "байхгүй"

    employer_text = (
        "🎉 <b>ТӨЛБӨР БАТАЛГААЖЛАА</b>\n\n"
        f"👤 {escape(match['full_name'])}\n"
        f"☎️ {escape(match['phone'])}\n"
        f"💬 Telegram: {escape(applicant_username)}\n"
        f"🧰 {escape(match['profession'])}\n"
        f"📚 {escape(match['experience'])}"
    )
    applicant_text = (
        "🎉 <b>MATCH АМЖИЛТТАЙ</b>\n\n"
        f"🏢 {escape(match['company'])}\n"
        f"💼 {escape(match['title'])}\n"
        f"💬 Ажил олгогчийн Telegram: {escape(employer_username)}\n\n"
        "Ажил олгогч таны холбоо барих мэдээллийг нээлээ."
    )

    await context.bot.send_message(match["employer_id"], employer_text, parse_mode=ParseMode.HTML)
    await context.bot.send_message(match["applicant_id"], applicant_text, parse_mode=ParseMode.HTML)
    await query.edit_message_reply_markup(reply_markup=None)
    await query.answer("Төлбөр баталгаажиж, холбоо барих мэдээлэл нээгдлээ.", show_alert=True)


async def detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    job = get_job(int(query.data.split(":")[1]))
    if not job:
        await query.answer("Зар олдсонгүй.", show_alert=True)
        return
    await query.answer()
    await query.message.reply_text(job_text(job), parse_mode=ParseMode.HTML)


async def save_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer("⭐ Хадгаллаа", show_alert=True)


async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("Танд админы эрх байхгүй.", show_alert=True)
        return

    action, raw_id = query.data.rsplit(":", 1)
    job_id = int(raw_id)
    job = get_job(job_id)
    if not job:
        await query.answer("Зар олдсонгүй.", show_alert=True)
        return

    if action == "approve_free":
        changed = approve_job(job_id, "free")
        status_text, msg = "✅ Энгийн зар", f"✅ Таны #{job_id} зар батлагдлаа."
    elif action == "approve_premium":
        changed = approve_job(job_id, "premium", 7)
        status_text, msg = "⭐ Premium 7 хоног", f"⭐ Таны #{job_id} зар Premium эрхтэйгээр 7 хоног нийтлэгдлээ."
    elif action == "approve_vip":
        changed = approve_job(job_id, "vip", 30)
        status_text, msg = "👑 VIP 30 хоног", f"👑 Таны #{job_id} зар VIP эрхтэйгээр 30 хоног нийтлэгдлээ."
    else:
        changed = reject_job(job_id)
        status_text, msg = "❌ Татгалзсан", f"❌ Таны #{job_id} зар татгалзагдлаа."

    if not changed:
        await query.answer("Энэ зар өмнө нь шийдвэрлэгдсэн.", show_alert=True)
        return
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(f"{status_text}: зар #{job_id}")
    await query.answer()
    try:
        await context.bot.send_message(job["employer_id"], msg)
    except Exception:
        logger.exception("Ажил олгогчид шийдвэр хүрсэнгүй")


async def premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Ашиглах: /premium 25")
        return
    job_id = int(context.args[0])
    job = get_job(job_id)
    if not job or job["status"] != "approved":
        await update.message.reply_text("Батлагдсан зар олдсонгүй.")
        return
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Энгийн", callback_data=f"plan_free:{job_id}"),
            InlineKeyboardButton("⭐ Premium 7 хоног", callback_data=f"plan_premium:{job_id}"),
        ],
        [InlineKeyboardButton("👑 VIP 30 хоног", callback_data=f"plan_vip:{job_id}")],
    ])
    await update.message.reply_text(f"Зар #{job_id}-ийн эрхийг сонгоно уу:", reply_markup=kb)


async def plan_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("Танд админы эрх байхгүй.", show_alert=True)
        return
    action, raw_id = query.data.rsplit(":", 1)
    job_id = int(raw_id)
    if action == "plan_free":
        changed, msg = set_job_plan(job_id, "free"), "Энгийн зар болголоо."
    elif action == "plan_premium":
        changed, msg = set_job_plan(job_id, "premium", 7), "Premium 7 хоног идэвхжлээ."
    else:
        changed, msg = set_job_plan(job_id, "vip", 30), "VIP 30 хоног идэвхжлээ."
    await query.answer(msg if changed else "Зар олдсонгүй.", show_alert=True)


async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        return
    jobs = get_pending_jobs()
    if not jobs:
        await update.message.reply_text("Хүлээгдэж буй зар алга.")
        return
    for job in jobs:
        await update.message.reply_text(
            job_text(job),
            parse_mode=ParseMode.HTML,
            reply_markup=admin_review_buttons(job["id"]),
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
        f"🤝 Нийт Match: {data['matches']}\n"
        f"⏳ Төлбөр хүлээж буй: {data['payment_pending']}\n"
        f"✅ Төлөгдсөн Match: {data['paid_matches']}\n"
        f"💰 Match орлого: {data['revenue']:,}₮"
    )


async def help_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👤 Ажил хайгч:\n"
        "1. Анкетаа бөглөнө.\n"
        "2. Зар дээр Match шалгана.\n"
        "3. 'Сонирхож байна' дарна.\n\n"
        "🏢 Ажил олгогч:\n"
        "1. Match саналыг зөвшөөрнө.\n"
        f"2. Хоёр тал зөвшөөрвөл {MATCH_PRICE:,}₮ төлнө.\n"
        "3. Админ баталгаажуулсны дараа холбоо барих мэдээлэл нээгдэнэ."
    )


def main() -> None:
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    profile_conversation = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^👤 Миний анкет$"), profile_start)],
        states={
            PROFILE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_name)],
            PROFILE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_phone)],
            PROFILE_PROFESSION: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_profession)],
            PROFILE_EXPERIENCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_experience)],
            PROFILE_SALARY: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_salary)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    job_conversation = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 Ажлын зар оруулах$"), job_start)],
        states={
            JOB_COMPANY: [MessageHandler(filters.TEXT & ~filters.COMMAND, job_company)],
            JOB_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, job_title)],
            JOB_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, job_category)],
            JOB_SALARY: [MessageHandler(filters.TEXT & ~filters.COMMAND, job_salary)],
            JOB_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, job_location)],
            JOB_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, job_description)],
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

    app.add_handler(MessageHandler(filters.Regex("^🔍 Ажил хайх$"), browse_jobs))
    app.add_handler(MessageHandler(filters.Regex("^🔙 Үндсэн цэс$"), start))
    app.add_handler(MessageHandler(filters.Regex("^(" + "|".join(map(re.escape, CATEGORIES)) + ")$"), category_jobs))
    app.add_handler(MessageHandler(filters.Regex("^ℹ️ Тусламж$"), help_message))

    app.add_handler(CallbackQueryHandler(match_check_callback, pattern=r"^matchcheck:\d+$"))
    app.add_handler(CallbackQueryHandler(interest_callback, pattern=r"^interest:\d+$"))
    app.add_handler(CallbackQueryHandler(employer_decision_callback, pattern=r"^employer_(yes|no):\d+$"))
    app.add_handler(CallbackQueryHandler(admin_match_callback, pattern=r"^admin_(invoice|cancel):\d+$"))
    app.add_handler(CallbackQueryHandler(payment_sent_callback, pattern=r"^payment_sent:\d+$"))
    app.add_handler(CallbackQueryHandler(admin_paid_callback, pattern=r"^admin_paid:\d+$"))
    app.add_handler(CallbackQueryHandler(detail_callback, pattern=r"^detail:\d+$"))
    app.add_handler(CallbackQueryHandler(save_callback, pattern=r"^save:\d+$"))
    app.add_handler(CallbackQueryHandler(admin_action, pattern=r"^(approve_free|approve_premium|approve_vip|reject):\d+$"))
    app.add_handler(CallbackQueryHandler(plan_action, pattern=r"^(plan_free|plan_premium|plan_vip):\d+$"))

    print("Бот ажиллаж эхэллээ...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
