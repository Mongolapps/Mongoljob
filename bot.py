import logging
import os
import re
from datetime import datetime, timedelta, timezone
from html import escape

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters,
)

from database import (
    add_job, close_job, create_match, dashboard_counts, get_business,
    get_business_by_owner, get_job, get_match, get_seeker, init_db,
    list_applicant_matches, list_employer_jobs, list_employer_matches,
    list_favorites, list_jobs, save_business, save_seeker, set_business_status,
    set_job_channel_message, set_job_plan, set_job_status, set_match_status,
    set_seeker_plan, set_seeker_status, stats, toggle_favorite,
)

load_dotenv()
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
)
logger = logging.getLogger("servigo")
logging.getLogger("httpx").setLevel(logging.WARNING)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
CHANNEL_ID = os.getenv("CHANNEL_ID", "").strip()
PREMIUM_CONTACT = os.getenv("PREMIUM_CONTACT", "bayanburd").lstrip("@")

(
    S_NAME, S_PROFESSION, S_LOCATION, S_SALARY, S_PHONE, S_EXPERIENCE,
    B_NAME, B_PHONE, B_LOCATION,
    J_TITLE, J_CATEGORY, J_SALARY, J_LOCATION, J_SCHEDULE, J_REQUIREMENTS,
) = range(15)

JOB_CATEGORIES = [
    "☕ Үйлчилгээ", "🚗 Жолооч", "🏗 Барилга", "💻 IT",
    "📊 Оффис", "🛒 Худалдаа", "🍔 Ресторан", "🏭 Үйлдвэр",
    "📦 Ложистик", "🎓 Боловсрол", "🔧 Инженер", "🏥 Эрүүл мэнд",
]

ROLE_MENU = ReplyKeyboardMarkup(
    [["👤 Ажил хайгч", "🏢 Ажил олгогч"]], resize_keyboard=True
)
SEEKER_MENU = ReplyKeyboardMarkup(
    [
        ["💼 Байнгын ажил", "⏰ Цагийн ажил"],
        ["👤 Миний анкет", "📊 Миний самбар"],
        ["❤️ Хадгалсан", "⭐ VIP зар"],
        ["🔄 Горим солих"],
    ], resize_keyboard=True,
)
EMPLOYER_MENU = ReplyKeyboardMarkup(
    [
        ["🏢 Байгууллага бүртгэх"],
        ["➕ Байнгын ажлын зар", "➕ Цагийн ажлын зар"],
        ["📋 Миний зарууд", "📨 Ирсэн хүсэлтүүд"],
        ["📊 Миний самбар", "⭐ VIP зар"],
        ["🔄 Горим солих"],
    ], resize_keyboard=True,
)
CANCEL_MENU = ReplyKeyboardMarkup([["❌ Цуцлах"]], resize_keyboard=True)
CONTACT_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("📱 Утас хуваалцах", request_contact=True)], ["❌ Цуцлах"]],
    resize_keyboard=True, one_time_keyboard=True,
)
CATEGORY_MENU = ReplyKeyboardMarkup(
    [JOB_CATEGORIES[i:i + 2] for i in range(0, len(JOB_CATEGORIES), 2)] + [["❌ Цуцлах"]],
    resize_keyboard=True,
)

TEXT_INPUT = filters.TEXT & ~filters.COMMAND & ~filters.Regex(r"^❌ Цуцлах$")
PHONE_INPUT = filters.CONTACT | TEXT_INPUT


def expires_after(days: int = 0, hours: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days, hours=hours)).isoformat()


def validate_config() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN тохируулаагүй байна")
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", BOT_TOKEN):
        raise RuntimeError("BOT_TOKEN буруу форматтай байна. BotFather-оос авсан token оруулна уу")
    if ADMIN_ID <= 0:
        raise RuntimeError("ADMIN_ID-д админы Telegram numeric ID оруулна уу")


def remaining_text(value: str | None) -> str:
    if not value:
        return ""
    try:
        end = datetime.fromisoformat(value.replace("Z", "+00:00"))
        seconds = int((end - datetime.now(timezone.utc)).total_seconds())
        if seconds <= 0:
            return "⌛ Хугацаа дууссан"
        days, rem = divmod(seconds, 86400)
        hours = rem // 3600
        return f"⏳ {days} өдөр {hours} цаг үлдсэн" if days else f"⏳ {hours} цаг үлдсэн"
    except ValueError:
        return ""


def role_menu(context: ContextTypes.DEFAULT_TYPE):
    return EMPLOYER_MENU if context.user_data.get("role") == "employer" else SEEKER_MENU


def seeker_text(row) -> str:
    badge = "⭐ <b>VIP АНКЕТ</b>\n" if row["plan"] != "free" else "👤 <b>АЖИЛ ХАЙГЧ</b>\n"
    timer = remaining_text(row["premium_expires_at"])
    return (
        f"{badge}{timer + chr(10) if timer else ''}\n"
        f"👤 <b>{escape(row['full_name'])}</b>\n"
        f"💼 {escape(row['profession'])}\n"
        f"📍 {escape(row['location'])}\n"
        f"💰 {escape(row['desired_salary'])}\n"
        f"📚 {escape(row['experience'] or 'Туршлага оруулаагүй')}\n"
        f"📌 Төлөв: <b>{escape(row['status'])}</b>"
    )


def job_text(row, include_contact: bool = False) -> str:
    badge = "👑 <b>VIP ЗАР</b>\n" if row["plan"] == "vip" else ("⭐ <b>PREMIUM ЗАР</b>\n" if row["plan"] == "premium" else "")
    timer = remaining_text(row["premium_expires_at"])
    verified = " ✅" if row["business_verified"] else ""
    type_label = "⏰ Цагийн ажил" if row["job_type"] == "part_time" else "💼 Байнгын ажил"
    contact = f"\n☎️ {escape(row['business_phone'])}" if include_contact else ""
    return (
        f"{badge}{timer + chr(10) if timer else ''}\n"
        f"🏢 <b>{escape(row['company'])}</b>{verified}\n"
        f"💼 <b>{escape(row['title'])}</b>\n\n"
        f"{type_label}\n"
        f"💰 <b>{escape(row['salary'])}</b>\n"
        f"📍 {escape(row['location'])}\n"
        f"🕒 {escape(row['schedule'])}\n"
        f"📂 {escape(row['category'])}\n\n"
        f"📌 <b>Шаардлага</b>\n{escape(row['requirements'])}"
        f"{contact}\n\n🆔 Зар #{row['id']} · 👀 {row['views']}"
    )


def match_score(seeker, job) -> tuple[int, str]:
    profession_words = set(re.findall(r"[\wА-Яа-яӨөҮү]{3,}", seeker["profession"].lower()))
    job_words = set(re.findall(r"[\wА-Яа-яӨөҮү]{3,}", f"{job['title']} {job['requirements']} {job['category']}".lower()))
    overlap = profession_words & job_words
    score = 20
    reasons = []
    if overlap:
        score += min(45, len(overlap) * 15)
        reasons.append("✅ Мэргэжил/ур чадвар ойролцоо")
    else:
        reasons.append("⚠️ Мэргэжлийн түлхүүр үг таараагүй")
    if seeker["location"].lower() in job["location"].lower() or job["location"].lower() in seeker["location"].lower():
        score += 20
        reasons.append("✅ Байршил тохирч байна")
    desired = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", seeker["desired_salary"])]
    offered = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", job["salary"])]
    if desired and offered and max(offered) >= min(desired):
        score += 15
        reasons.append("✅ Цалингийн хүлээлт боломжтой")
    return min(score, 95), "\n".join(reasons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if args and args[0].startswith("job_"):
        await show_job(update, context, int(args[0].split("_", 1)[1]))
        return
    await update.message.reply_text(
        "🚀 <b>ServiGo</b>\n\nАжил хайгч, ажил олгогчийг хурдан бөгөөд аюулгүй холбоно.\n\nТа аль хэлбэрээр ашиглах вэ?",
        parse_mode=ParseMode.HTML, reply_markup=ROLE_MENU,
    )


async def choose_seeker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear(); context.user_data["role"] = "seeker"
    await update.message.reply_text("👤 Ажил хайгчийн хэсэг", reply_markup=SEEKER_MENU)


async def choose_employer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear(); context.user_data["role"] = "employer"
    await update.message.reply_text("🏢 Ажил олгогчийн хэсэг", reply_markup=EMPLOYER_MENU)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    role = context.user_data.get("role")
    context.user_data.clear()
    if role:
        context.user_data["role"] = role
    await update.message.reply_text("Үйлдлийг цуцаллаа.", reply_markup=role_menu(context))
    return ConversationHandler.END


async def seeker_start(update, context):
    context.user_data["draft"] = {}
    await update.message.reply_text("👤 Таны нэр?", reply_markup=CANCEL_MENU); return S_NAME
async def seeker_name(update, context):
    context.user_data["draft"]["full_name"] = update.message.text.strip()
    await update.message.reply_text("💼 Ямар ажил хийдэг вэ?"); return S_PROFESSION
async def seeker_profession(update, context):
    context.user_data["draft"]["profession"] = update.message.text.strip()
    await update.message.reply_text("📍 Хаана ажиллах вэ?"); return S_LOCATION
async def seeker_location(update, context):
    context.user_data["draft"]["location"] = update.message.text.strip()
    await update.message.reply_text("💰 Хүсэж буй цалин?"); return S_SALARY
async def seeker_salary(update, context):
    context.user_data["draft"]["desired_salary"] = update.message.text.strip()
    await update.message.reply_text("📱 Утасны дугаар?", reply_markup=CONTACT_MENU); return S_PHONE
async def seeker_phone(update, context):
    if update.message.contact and update.message.contact.user_id not in (None, update.effective_user.id):
        await update.message.reply_text("Өөрийн утасны дугаарыг хуваалцана уу.", reply_markup=CONTACT_MENU)
        return S_PHONE
    phone = update.message.contact.phone_number if update.message.contact else update.message.text.strip()
    context.user_data["draft"]["phone"] = phone
    await update.message.reply_text("📚 Туршлага? (ж: 2 жил, эсвэл Байхгүй)", reply_markup=CANCEL_MENU); return S_EXPERIENCE
async def seeker_experience(update, context):
    user = update.effective_user
    data = context.user_data["draft"]
    data.update(telegram_id=user.id, username=user.username, experience=update.message.text.strip())
    save_seeker(data)
    row = get_seeker(user.id)
    context.user_data.pop("draft", None)
    await update.message.reply_text("✅ Анкет илгээгдлээ. Админ шалгасны дараа мэдэгдэнэ.", reply_markup=SEEKER_MENU)
    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID, "🆕 <b>Шинэ анкет</b>\n\n" + seeker_text(row), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Батлах", callback_data=f"admin_seeker_yes:{user.id}"),
                InlineKeyboardButton("❌ Татгалзах", callback_data=f"admin_seeker_no:{user.id}"),
            ]]),
        )
    return ConversationHandler.END


async def business_start(update, context):
    context.user_data["draft"] = {}
    await update.message.reply_text("🏢 Байгууллагын нэр?", reply_markup=CANCEL_MENU); return B_NAME
async def business_name(update, context):
    context.user_data["draft"]["name"] = update.message.text.strip()
    await update.message.reply_text("📱 Холбоо барих утас?", reply_markup=CONTACT_MENU); return B_PHONE
async def business_phone(update, context):
    if update.message.contact and update.message.contact.user_id not in (None, update.effective_user.id):
        await update.message.reply_text("Өөрийн утасны дугаарыг хуваалцана уу.", reply_markup=CONTACT_MENU)
        return B_PHONE
    context.user_data["draft"]["phone"] = update.message.contact.phone_number if update.message.contact else update.message.text.strip()
    await update.message.reply_text("📍 Байршил?", reply_markup=CANCEL_MENU); return B_LOCATION
async def business_location(update, context):
    user = update.effective_user; data = context.user_data["draft"]
    data.update(owner_id=user.id, owner_username=user.username, location=update.message.text.strip())
    business_id = save_business(data); business = get_business(business_id)
    context.user_data.pop("draft", None)
    await update.message.reply_text("✅ Байгууллагын мэдээлэл илгээгдлээ.", reply_markup=EMPLOYER_MENU)
    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            f"🆕 <b>Шинэ байгууллага</b>\n\n🏢 {escape(business['name'])}\n📍 {escape(business['location'])}\n☎️ {escape(business['phone'])}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Батлах", callback_data=f"admin_business_yes:{business_id}"),
                InlineKeyboardButton("❌ Татгалзах", callback_data=f"admin_business_no:{business_id}"),
            ]]),
        )
    return ConversationHandler.END


async def job_start(update, context, job_type: str):
    business = get_business_by_owner(update.effective_user.id)
    if not business or business["status"] != "approved":
        await update.message.reply_text("Эхлээд байгууллагаа бүртгүүлж, батлуулна уу.", reply_markup=EMPLOYER_MENU)
        return ConversationHandler.END
    context.user_data["draft"] = {"job_type": job_type, "business_id": business["id"], "employer_id": update.effective_user.id}
    await update.message.reply_text("💼 Ажлын байрны нэр?", reply_markup=CANCEL_MENU); return J_TITLE
async def job_start_full(update, context): return await job_start(update, context, "full_time")
async def job_start_part(update, context): return await job_start(update, context, "part_time")
async def job_title(update, context):
    context.user_data["draft"]["title"] = update.message.text.strip()
    await update.message.reply_text("📂 Ангилал?", reply_markup=CATEGORY_MENU); return J_CATEGORY
async def job_category(update, context):
    if update.message.text not in JOB_CATEGORIES:
        await update.message.reply_text("Доорх ангиллаас сонгоно уу."); return J_CATEGORY
    context.user_data["draft"]["category"] = update.message.text
    await update.message.reply_text("💰 Цалин?", reply_markup=CANCEL_MENU); return J_SALARY
async def job_salary(update, context):
    context.user_data["draft"]["salary"] = update.message.text.strip()
    await update.message.reply_text("📍 Ажлын байршил?"); return J_LOCATION
async def job_location(update, context):
    context.user_data["draft"]["location"] = update.message.text.strip()
    await update.message.reply_text("🕒 Ажлын цаг?"); return J_SCHEDULE
async def job_schedule(update, context):
    context.user_data["draft"]["schedule"] = update.message.text.strip()
    await update.message.reply_text("📌 Гол шаардлага? (1–3 өгүүлбэр)"); return J_REQUIREMENTS
async def job_requirements(update, context):
    data = context.user_data["draft"]; data["requirements"] = update.message.text.strip()
    job_id = add_job(data); job = get_job(job_id)
    context.user_data.pop("draft", None)
    await update.message.reply_text("✅ Зар илгээгдлээ. Батлагдсаны дараа нийтлэгдэнэ.", reply_markup=EMPLOYER_MENU)
    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID, "🆕 <b>Шинэ ажлын зар</b>\n\n" + job_text(job), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Энгийн", callback_data=f"admin_job_free:{job_id}"),
                 InlineKeyboardButton("⭐ Premium 24ц", callback_data=f"admin_job_premium:{job_id}")],
                [InlineKeyboardButton("👑 VIP 30 хоног", callback_data=f"admin_job_vip:{job_id}"),
                 InlineKeyboardButton("❌ Татгалзах", callback_data=f"admin_job_no:{job_id}")],
            ]),
        )
    return ConversationHandler.END


async def show_job(update: Update, context: ContextTypes.DEFAULT_TYPE, job_id: int):
    job = get_job(job_id, increment_view=True)
    if not job or job["status"] != "approved":
        target = update.callback_query.message if update.callback_query else update.message
        await target.reply_text("Энэ зар идэвхгүй эсвэл олдсонгүй.")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤝 Сонирхож байна", callback_data=f"apply:{job_id}"),
         InlineKeyboardButton("❤️ Хадгалах", callback_data=f"favorite:{job_id}")],
    ])
    target = update.callback_query.message if update.callback_query else update.message
    await target.reply_text(job_text(job), parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def browse_jobs(update, context, job_type: str):
    rows = list_jobs(job_type=job_type, limit=10)
    if not rows:
        await update.message.reply_text("Одоогоор тохирох зар алга.", reply_markup=SEEKER_MENU); return
    await update.message.reply_text(f"🔎 {len(rows)} зар олдлоо", reply_markup=SEEKER_MENU)
    for row in rows:
        await update.message.reply_text(
            job_text(row), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🤝 Сонирхож байна", callback_data=f"apply:{row['id']}"),
                InlineKeyboardButton("❤️", callback_data=f"favorite:{row['id']}"),
            ]]),
        )


async def browse_full(update, context): await browse_jobs(update, context, "full_time")
async def browse_part(update, context): await browse_jobs(update, context, "part_time")


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    if data.startswith("apply:"):
        job_id = int(data.split(":")[1]); seeker = get_seeker(query.from_user.id); job = get_job(job_id)
        if not seeker:
            await query.message.reply_text("Эхлээд 👤 Миний анкет хэсгээр анкетаа үүсгэнэ үү.", reply_markup=SEEKER_MENU); return
        if seeker["status"] != "approved":
            await query.message.reply_text("Таны анкет хараахан батлагдаагүй байна."); return
        if not job or job["status"] != "approved":
            await query.message.reply_text("Энэ зар идэвхгүй болсон байна."); return
        score, reason = match_score(seeker, job)
        match, created = create_match(job_id, query.from_user.id, score, reason)
        if not created:
            await query.message.reply_text("Та энэ зар руу өмнө нь хүсэлт илгээсэн байна."); return
        await query.message.reply_text(f"✅ Хүсэлт илгээгдлээ.\n\n🤝 Тохирох үнэлгээ: <b>{score}%</b>\n{reason}", parse_mode=ParseMode.HTML)
        await context.bot.send_message(
            job["employer_id"],
            f"🔔 <b>Шинэ хүсэлт</b>\n\n💼 {escape(job['title'])}\n👤 {escape(seeker['full_name'])}\n🧰 {escape(seeker['profession'])}\n🤝 Тохирох үнэлгээ: <b>{score}%</b>\n\n{reason}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Зөвшөөрөх", callback_data=f"match_yes:{match['id']}"),
                InlineKeyboardButton("❌ Татгалзах", callback_data=f"match_no:{match['id']}")
            ]]),
        )
        return
    if data.startswith("favorite:"):
        seeker = get_seeker(query.from_user.id)
        if not seeker:
            await query.message.reply_text("Эхлээд анкетаа үүсгэнэ үү."); return
        saved = toggle_favorite(query.from_user.id, int(data.split(":")[1]))
        await query.answer("Хадгаллаа" if saved else "Хадгалснаас хаслаа", show_alert=True); return
    if data.startswith("match_yes:") or data.startswith("match_no:"):
        match_id = int(data.split(":")[1]); match = get_match(match_id)
        if not match or match["employer_id"] != query.from_user.id:
            await query.answer("Эрх хүрэхгүй", show_alert=True); return
        if match["status"] != "waiting_employer":
            await query.answer("Энэ хүсэлтийг шийдсэн байна", show_alert=True); return
        if data.startswith("match_no:"):
            set_match_status(match_id, "rejected")
            await query.edit_message_reply_markup(None)
            await context.bot.send_message(match["applicant_id"], f"Таны <b>{escape(match['title'])}</b> ажлын хүсэлт энэ удаад зөвшөөрөгдсөнгүй.", parse_mode=ParseMode.HTML)
            return
        set_match_status(match_id, "connected")
        await query.edit_message_reply_markup(None)
        await context.bot.send_message(
            match["applicant_id"],
            f"🎉 <b>Match боллоо!</b>\n\n🏢 {escape(match['company'])}\n💼 {escape(match['title'])}\n☎️ {escape(match['employer_phone'])}",
            parse_mode=ParseMode.HTML,
        )
        await context.bot.send_message(
            match["employer_id"],
            f"🎉 <b>Match боллоо!</b>\n\n👤 {escape(match['full_name'])}\n🧰 {escape(match['profession'])}\n☎️ {escape(match['applicant_phone'])}",
            parse_mode=ParseMode.HTML,
        )
        return
    if data.startswith("close_job:"):
        job_id = int(data.split(":")[1])
        if close_job(job_id, query.from_user.id):
            await query.edit_message_reply_markup(None)
            await query.message.reply_text("⛔ Зар хаагдлаа.", reply_markup=EMPLOYER_MENU)
        else:
            await query.answer("Зар хаах эрхгүй эсвэл зар олдсонгүй", show_alert=True)
        return
    if data.startswith("admin_"):
        if query.from_user.id != ADMIN_ID:
            await query.answer("Админы эрх шаардлагатай", show_alert=True); return
        action, raw_id = data.rsplit(":", 1); item_id = int(raw_id)
        if action == "admin_seeker_yes":
            set_seeker_status(item_id, "approved"); await context.bot.send_message(item_id, "✅ Таны анкет батлагдлаа.", reply_markup=SEEKER_MENU)
        elif action == "admin_seeker_no":
            set_seeker_status(item_id, "rejected"); await context.bot.send_message(item_id, "❌ Таны анкет батлагдсангүй. Мэдээллээ засаж дахин илгээнэ үү.")
        elif action == "admin_business_yes":
            set_business_status(item_id, "approved", True); b = get_business(item_id); await context.bot.send_message(b["owner_id"], "✅ Байгууллага баталгаажлаа.", reply_markup=EMPLOYER_MENU)
        elif action == "admin_business_no":
            set_business_status(item_id, "rejected"); b = get_business(item_id); await context.bot.send_message(b["owner_id"], "❌ Байгууллагын бүртгэл батлагдсангүй.")
        elif action.startswith("admin_job_"):
            job = get_job(item_id)
            if action == "admin_job_no":
                set_job_status(item_id, "rejected"); await context.bot.send_message(job["employer_id"], "❌ Таны зар батлагдсангүй.")
            else:
                plan = action.removeprefix("admin_job_")
                expiry = None
                if plan == "premium": expiry = expires_after(hours=24)
                if plan == "vip": expiry = expires_after(days=30)
                set_job_status(item_id, "approved"); set_job_plan(item_id, plan, expiry)
                job = get_job(item_id)
                await context.bot.send_message(job["employer_id"], f"✅ Таны зар батлагдлаа. Төлөв: {plan.upper()}", reply_markup=EMPLOYER_MENU)
                if CHANNEL_ID:
                    me = await context.bot.get_me()
                    sent = await context.bot.send_message(
                        CHANNEL_ID, job_text(job), parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🤝 Сонирхож байна", url=f"https://t.me/{me.username}?start=job_{item_id}")]]),
                    )
                    set_job_channel_message(item_id, sent.message_id)
        await query.edit_message_reply_markup(None)
        await query.answer("Хадгаллаа", show_alert=True)


async def profile(update, context):
    row = get_seeker(update.effective_user.id)
    if not row:
        await update.message.reply_text("Анкет байхгүй. Доорх асуултаар хурдан үүсгэнэ үү."); return await seeker_start(update, context)
    await update.message.reply_text(seeker_text(row), parse_mode=ParseMode.HTML, reply_markup=SEEKER_MENU)


async def seeker_dashboard(update, context):
    c = dashboard_counts(update.effective_user.id, "seeker")
    await update.message.reply_text(f"📊 <b>Миний самбар</b>\n\n⏳ Хариу хүлээж буй: {c['waiting']}\n🎉 Match болсон: {c['connected']}\n❤️ Хадгалсан: {c['favorites']}", parse_mode=ParseMode.HTML, reply_markup=SEEKER_MENU)


async def employer_dashboard(update, context):
    c = dashboard_counts(update.effective_user.id, "employer")
    await update.message.reply_text(f"📊 <b>Миний самбар</b>\n\n📢 Идэвхтэй зар: {c['jobs']}\n📨 Шинэ хүсэлт: {c['waiting']}\n🎉 Match болсон: {c['connected']}", parse_mode=ParseMode.HTML, reply_markup=EMPLOYER_MENU)


async def favorites(update, context):
    rows = list_favorites(update.effective_user.id)
    if not rows: await update.message.reply_text("Хадгалсан зар алга.", reply_markup=SEEKER_MENU); return
    for row in rows: await update.message.reply_text(job_text(row), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🤝 Сонирхож байна", callback_data=f"apply:{row['id']}")]]))


async def my_jobs(update, context):
    rows = list_employer_jobs(update.effective_user.id)
    if not rows: await update.message.reply_text("Таны зар алга.", reply_markup=EMPLOYER_MENU); return
    for row in rows:
        status = {"approved":"🟢 Идэвхтэй", "pending":"🟡 Хүлээгдэж буй", "closed":"⚫ Хаагдсан", "rejected":"🔴 Татгалзсан"}.get(row["status"], row["status"])
        await update.message.reply_text(f"💼 <b>{escape(row['title'])}</b>\n{status}\n📨 Хүсэлт: {row['application_count']}\n👀 Үзэлт: {row['views']}", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⛔ Зар хаах", callback_data=f"close_job:{row['id']}")]]))


async def incoming(update, context):
    rows = list_employer_matches(update.effective_user.id, "waiting_employer")
    if not rows: await update.message.reply_text("Шинэ хүсэлт алга.", reply_markup=EMPLOYER_MENU); return
    for row in rows:
        await update.message.reply_text(f"📨 <b>{escape(row['title'])}</b>\n👤 {escape(row['full_name'])}\n🧰 {escape(row['profession'])}\n🤝 {row['score']}%", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Зөвшөөрөх", callback_data=f"match_yes:{row['id']}"), InlineKeyboardButton("❌ Татгалзах", callback_data=f"match_no:{row['id']}")]]))


async def vip_info(update, context):
    await update.message.reply_text(
        "👑 <b>VIP ЗАР — 35,000₮ / 30 хоног</b>\n\n✅ Жагсаалтын эхэнд\n✅ VIP тэмдэг, онцгой дизайн\n✅ Match саналд давуу эрэмбэ\n✅ Channel-д онцлон нийтлэх\n✅ Үзэлт ба хүсэлтийн статистик\n\nТөлбөр болон идэвхжүүлэлт:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 Админтай холбогдох", url=f"https://t.me/{PREMIUM_CONTACT}")]]),
    )


async def admin_stats(update, context):
    if update.effective_user.id != ADMIN_ID: return
    s = stats(); await update.message.reply_text("📊 <b>ServiGo статистик</b>\n\n" + "\n".join(f"{k}: {v}" for k,v in s.items()), parse_mode=ParseMode.HTML)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try: await update.effective_message.reply_text("Түр алдаа гарлаа. Дахин оролдоно уу.")
        except Exception: logger.exception("Could not notify user")


def build_app() -> Application:
    validate_config()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^👤 Миний анкет$"), profile)],
        states={
            S_NAME:[MessageHandler(TEXT_INPUT, seeker_name)],
            S_PROFESSION:[MessageHandler(TEXT_INPUT, seeker_profession)],
            S_LOCATION:[MessageHandler(TEXT_INPUT, seeker_location)],
            S_SALARY:[MessageHandler(TEXT_INPUT, seeker_salary)],
            S_PHONE:[MessageHandler(PHONE_INPUT, seeker_phone)],
            S_EXPERIENCE:[MessageHandler(TEXT_INPUT, seeker_experience)],
        }, fallbacks=[MessageHandler(filters.Regex(r"^❌ Цуцлах$"), cancel)], allow_reentry=True,
    ))
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^🏢 Байгууллага бүртгэх$"), business_start)],
        states={B_NAME:[MessageHandler(TEXT_INPUT, business_name)], B_PHONE:[MessageHandler(PHONE_INPUT, business_phone)], B_LOCATION:[MessageHandler(TEXT_INPUT, business_location)]},
        fallbacks=[MessageHandler(filters.Regex(r"^❌ Цуцлах$"), cancel)], allow_reentry=True,
    ))
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^➕ Байнгын ажлын зар$"), job_start_full), MessageHandler(filters.Regex(r"^➕ Цагийн ажлын зар$"), job_start_part)],
        states={J_TITLE:[MessageHandler(TEXT_INPUT, job_title)], J_CATEGORY:[MessageHandler(TEXT_INPUT, job_category)], J_SALARY:[MessageHandler(TEXT_INPUT, job_salary)], J_LOCATION:[MessageHandler(TEXT_INPUT, job_location)], J_SCHEDULE:[MessageHandler(TEXT_INPUT, job_schedule)], J_REQUIREMENTS:[MessageHandler(TEXT_INPUT, job_requirements)]},
        fallbacks=[MessageHandler(filters.Regex(r"^❌ Цуцлах$"), cancel)], allow_reentry=True,
    ))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.Regex(r"^👤 Ажил хайгч$"), choose_seeker))
    app.add_handler(MessageHandler(filters.Regex(r"^🏢 Ажил олгогч$"), choose_employer))
    app.add_handler(MessageHandler(filters.Regex(r"^🔄 Горим солих$"), start))
    app.add_handler(MessageHandler(filters.Regex(r"^💼 Байнгын ажил$"), browse_full))
    app.add_handler(MessageHandler(filters.Regex(r"^⏰ Цагийн ажил$"), browse_part))
    app.add_handler(MessageHandler(filters.Regex(r"^📊 Миний самбар$"), lambda u,c: employer_dashboard(u,c) if c.user_data.get("role") == "employer" else seeker_dashboard(u,c)))
    app.add_handler(MessageHandler(filters.Regex(r"^❤️ Хадгалсан$"), favorites))
    app.add_handler(MessageHandler(filters.Regex(r"^📋 Миний зарууд$"), my_jobs))
    app.add_handler(MessageHandler(filters.Regex(r"^📨 Ирсэн хүсэлтүүд$"), incoming))
    app.add_handler(MessageHandler(filters.Regex(r"^⭐ VIP зар$"), vip_info))
    app.add_error_handler(error_handler)
    return app


if __name__ == "__main__":
    validate_config()
    init_db()
    logger.info("ServiGo started")
    build_app().run_polling(drop_pending_updates=True)
