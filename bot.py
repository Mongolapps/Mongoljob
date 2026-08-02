import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from html import escape

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters,
)

from database import (
    add_business, add_job, add_service, approve_business, approve_job, create_booking,
    create_or_get_match, get_approved_jobs, get_booking, get_business, get_business_by_owner,
    get_businesses_by_category, get_job, get_match, get_pending_businesses, get_pending_jobs,
    get_service, get_services_by_business, get_user, init_db, reject_job,
    approve_user, get_notifiable_users, get_promoted_jobs, get_promoted_users, reject_user,
    save_user, set_booking_status, set_employer_decision, set_job_channel_message,
    set_user_channel_message, stats, toggle_notifications,
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = os.getenv("CHANNEL_ID", "@servigomgl").strip()
PREMIUM_CONTACT = os.getenv("PREMIUM_CONTACT", "bayanburd").lstrip("@").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN олдсонгүй.")

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

SERVICE_CATEGORIES = ["🏥 Эрүүл мэнд", "💇 Гоо сайхан", "🍽 Хоол", "🏋 Фитнес", "🚗 Авто", "🎓 Сургалт", "🛠 Засвар", "📦 Хүргэлт"]
JOB_CATEGORIES = ["☕ Үйлчилгээ", "🚗 Жолооч", "🏗 Барилга", "💻 IT", "📊 Оффис", "🛒 Худалдаа", "🍔 Ресторан", "🏭 Үйлдвэр", "📦 Ложистик", "🎓 Боловсрол", "🔧 Инженер", "🏥 Эрүүл мэнд"]

(
    P_NAME, P_PHONE, P_PROFESSION, P_EXPERIENCE, P_SALARY,
    B_NAME, B_CATEGORY, B_PHONE, B_LOCATION, B_DESCRIPTION,
    S_TITLE, S_PRICE, S_DURATION, S_DESCRIPTION,
    J_TITLE, J_TYPE, J_CATEGORY, J_SALARY, J_SCHEDULE, J_LOCATION, J_DESCRIPTION,
    BK_TIME, BK_NOTE,
) = range(23)

MAIN_MENU = ReplyKeyboardMarkup([
    ["🔎 Үйлчилгээ хайх", "💼 Байнгын ажил"],
    ["⏰ Цагийн ажил", "👤 Миний анкет"],
    ["🏢 Байгууллагын хэсэг", "⭐ Premium үйлчилгээ"],
    ["🔔 Мэдэгдэл", "ℹ️ Тусламж"],
], resize_keyboard=True)

BUSINESS_MENU = ReplyKeyboardMarkup([
    ["🏢 Байгууллага бүртгэх", "➕ Үйлчилгээ нэмэх"],
    ["📢 Байнгын ажилтан хайх", "⏰ Цагийн ажилтан хайх"],
    ["📋 Миний үйлчилгээ", "🔙 Үндсэн цэс"],
], resize_keyboard=True)

SERVICE_MENU = ReplyKeyboardMarkup([[SERVICE_CATEGORIES[i], SERVICE_CATEGORIES[i+1]] for i in range(0, len(SERVICE_CATEGORIES), 2)] + [["🔙 Үндсэн цэс"]], resize_keyboard=True)
JOB_MENU = ReplyKeyboardMarkup([[JOB_CATEGORIES[i], JOB_CATEGORIES[i+1]] for i in range(0, len(JOB_CATEGORIES), 2)] + [["🔙 Үндсэн цэс"]], resize_keyboard=True)
JOB_TYPE_MENU = ReplyKeyboardMarkup([["💼 Байнгын ажил", "⏰ Цагийн ажил"], ["🔙 Үндсэн цэс"]], resize_keyboard=True)



def remaining_text(expires_at):
    if not expires_at:
        return ""
    try:
        end = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        seconds = max(0, int((end - datetime.now(timezone.utc)).total_seconds()))
        if seconds <= 0:
            return "⌛ Хугацаа дууссан"
        days, rem = divmod(seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        if days:
            return f"⏳ Үлдсэн: {days} өдөр {hours} цаг"
        return f"⏳ Үлдсэн: {hours:02d}:{minutes:02d}"
    except (TypeError, ValueError):
        return ""


def user_text(u):
    badge = "⭐ <b>PREMIUM АНКЕТ</b>\n" if u["plan"] == "premium" else "👤 <b>АЖИЛ ХАЙЖ БАЙНА</b>\n"
    timer = remaining_text(u["premium_expires_at"])
    timer_line = f"{timer}\n\n" if timer else "\n"
    username = f"@{u['username']}" if u["username"] else "Нууц"
    return (
        f"{badge}{timer_line}"
        f"👤 <b>{escape(u['full_name'])}</b>\n"
        f"🧰 {escape(u['profession'] or '-')}\n"
        f"📚 {escape(u['experience'] or '-')}\n"
        f"💰 Хүсэж буй цалин: {escape(u['desired_salary'] or '-')}\n"
        f"💬 Telegram: {escape(username)}"
    )


def business_text(b):
    badge = "✅ <b>VERIFIED</b>\n" if b["status"] == "approved" else ""
    return (f"{badge}🏢 <b>{escape(b['name'])}</b>\n"
            f"📂 {escape(b['category'])}\n📍 {escape(b['location'])}\n"
            f"☎️ {escape(b['phone'])}\n\n{escape(b['description'])}\n\n🆔 Байгууллага #{b['id']}")


def service_text(s):
    return (f"🏢 <b>{escape(s['business_name'])}</b>\n\n"
            f"🛍 <b>{escape(s['title'])}</b>\n💰 {escape(s['price'])}\n"
            f"⏱ {escape(s['duration'])}\n📍 {escape(s['location'])}\n\n"
            f"{escape(s['description'])}\n\n🆔 Үйлчилгээ #{s['id']}")


def job_text(j):
    badge = "👑 <b>VIP ЗАР</b>\n" if j["plan"] == "vip" else ("⭐ <b>PREMIUM ЗАР</b>\n" if j["plan"] == "premium" else "")
    timer = remaining_text(j["premium_expires_at"]) if j["plan"] in {"premium", "vip"} else ""
    timer_line = f"{timer}\n\n" if timer else ("\n" if badge else "")
    type_label = "⏰ Цагийн ажил" if j["job_type"] == "part_time" else "💼 Байнгын ажил"
    return (f"{badge}{timer_line}🏢 <b>{escape(j['company'])}</b>\n\n"
            f"{type_label}\n💼 <b>{escape(j['title'])}</b>\n📂 {escape(j['category'])}\n"
            f"💰 {escape(j['salary'])}\n🕒 {escape(j['schedule'])}\n📍 {escape(j['location'])}\n\n"
            f"📌 <b>Шаардлага</b>\n{escape(j['description'])}\n\n🆔 Зар #{j['id']}")


def match_score(user, job):
    score = 50
    words = set(re.findall(r"\w{3,}", (user["profession"] or "").lower()))
    target = set(re.findall(r"\w{3,}", (job["title"] + " " + job["description"]).lower()))
    score += min(len(words & target) * 10, 30)
    desired = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", user["desired_salary"] or "")]
    offered = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", job["salary"])]
    if desired and offered and max(offered) >= max(desired): score += 15
    return min(score, 99)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("browse_job_type", None)
    await update.message.reply_text("🚀 <b>ServiGo</b>\n\nҮйлчилгээ, байнгын ажил, цагийн ажлыг нэг дороос.", parse_mode=ParseMode.HTML, reply_markup=MAIN_MENU)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Үйлдлийг цуцаллаа.", reply_markup=MAIN_MENU)
    return ConversationHandler.END


# ----- Хэрэглэгчийн анкет -----
async def profile_start(update, context): await update.message.reply_text("Овог нэрээ оруулна уу:"); return P_NAME
async def p_name(update, context): context.user_data["full_name"] = update.message.text.strip(); await update.message.reply_text("Утасны дугаар:"); return P_PHONE
async def p_phone(update, context): context.user_data["phone"] = update.message.text.strip(); await update.message.reply_text("Мэргэжил, хийж чадах ажил:"); return P_PROFESSION
async def p_prof(update, context): context.user_data["profession"] = update.message.text.strip(); await update.message.reply_text("Туршлага:"); return P_EXPERIENCE
async def p_exp(update, context): context.user_data["experience"] = update.message.text.strip(); await update.message.reply_text("Хүсэж буй цалин:"); return P_SALARY
async def p_salary(update, context):
    u = update.effective_user
    context.user_data.update(desired_salary=update.message.text.strip(), telegram_id=u.id, username=u.username)
    save_user(context.user_data)
    saved = get_user(u.id)
    context.user_data.clear()
    await update.message.reply_text("✅ Анкет хүлээн авлаа. Админ шалгаж батална.", reply_markup=MAIN_MENU)
    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            "🆕 <b>Шинэ ажил хайгчийн анкет</b>\n\n" + user_text(saved),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Энгийн", callback_data=f"user_free:{u.id}"),
                    InlineKeyboardButton("⭐ Premium 24ц / 3,000₮", callback_data=f"user_premium:{u.id}"),
                ],
                [
                    InlineKeyboardButton("❌ Татгалзах", callback_data=f"user_no:{u.id}"),
                    InlineKeyboardButton("💬 @bayanburd", url=f"https://t.me/{PREMIUM_CONTACT}"),
                ],
            ]),
        )
    return ConversationHandler.END


# ----- Байгууллага -----
async def business_menu(update, context): await update.message.reply_text("🏢 Байгууллагын удирдлага", reply_markup=BUSINESS_MENU)
async def business_start(update, context):
    context.user_data["owner_id"] = update.effective_user.id; context.user_data["owner_username"] = update.effective_user.username
    await update.message.reply_text("Байгууллагын нэр:"); return B_NAME
async def b_name(update, context): context.user_data["name"] = update.message.text.strip(); await update.message.reply_text("Ангилал:", reply_markup=SERVICE_MENU); return B_CATEGORY
async def b_cat(update, context):
    if update.message.text not in SERVICE_CATEGORIES: await update.message.reply_text("Ангиллаа товчоор сонгоно уу."); return B_CATEGORY
    context.user_data["category"] = update.message.text; await update.message.reply_text("Утас:"); return B_PHONE
async def b_phone(update, context): context.user_data["phone"] = update.message.text.strip(); await update.message.reply_text("Байршил:"); return B_LOCATION
async def b_location(update, context): context.user_data["location"] = update.message.text.strip(); await update.message.reply_text("Товч танилцуулга:"); return B_DESCRIPTION
async def b_desc(update, context):
    context.user_data["description"] = update.message.text.strip(); bid = add_business(context.user_data); b = get_business(bid); context.user_data.clear()
    await update.message.reply_text(f"✅ Байгууллага #{bid} хүлээн авлаа. Админ батална.", reply_markup=BUSINESS_MENU)
    if ADMIN_ID:
        await context.bot.send_message(ADMIN_ID, "🆕 <b>Шинэ байгууллага</b>\n\n" + business_text(b), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Батлах", callback_data=f"biz_yes:{bid}"), InlineKeyboardButton("❌ Татгалзах", callback_data=f"biz_no:{bid}")]]))
    return ConversationHandler.END


# ----- Үйлчилгээ нэмэх -----
async def service_start(update, context):
    b = get_business_by_owner(update.effective_user.id)
    if not b or b["status"] != "approved":
        await update.message.reply_text("Эхлээд байгууллагаа бүртгүүлж, админаар батлуулна уу.", reply_markup=BUSINESS_MENU); return ConversationHandler.END
    context.user_data["business_id"] = b["id"]; await update.message.reply_text("Үйлчилгээний нэр:"); return S_TITLE
async def s_title(update, context): context.user_data["title"] = update.message.text.strip(); await update.message.reply_text("Үнэ:"); return S_PRICE
async def s_price(update, context): context.user_data["price"] = update.message.text.strip(); await update.message.reply_text("Үргэлжлэх хугацаа:"); return S_DURATION
async def s_duration(update, context): context.user_data["duration"] = update.message.text.strip(); await update.message.reply_text("Тайлбар:"); return S_DESCRIPTION
async def s_desc(update, context):
    context.user_data["description"] = update.message.text.strip(); sid = add_service(context.user_data); context.user_data.clear()
    await update.message.reply_text(f"✅ Үйлчилгээ #{sid} нэмэгдлээ.", reply_markup=BUSINESS_MENU); return ConversationHandler.END


# ----- Ажлын зар -----
async def job_start_full(update, context): context.user_data["preset_job_type"] = "full_time"; return await job_start(update, context)
async def job_start_part(update, context): context.user_data["preset_job_type"] = "part_time"; return await job_start(update, context)
async def job_start(update, context):
    b = get_business_by_owner(update.effective_user.id)
    if not b or b["status"] != "approved":
        await update.message.reply_text("Ажлын зар оруулахын өмнө баталгаажсан байгууллагатай байна уу.", reply_markup=BUSINESS_MENU); return ConversationHandler.END
    context.user_data.update(employer_id=update.effective_user.id, employer_username=update.effective_user.username, business_id=b["id"], company=b["name"])
    if context.user_data.get("preset_job_type"):
        context.user_data["job_type"] = context.user_data.pop("preset_job_type")
        await update.message.reply_text("Ажлын байрны нэр:"); return J_TITLE
    await update.message.reply_text("Ажлын байрны нэр:"); return J_TITLE
async def j_title(update, context):
    context.user_data["title"] = update.message.text.strip()
    if "job_type" not in context.user_data: await update.message.reply_text("Ажлын төрлөө сонгоно уу:", reply_markup=JOB_TYPE_MENU); return J_TYPE
    await update.message.reply_text("Ангилал:", reply_markup=JOB_MENU); return J_CATEGORY
async def j_type(update, context):
    if update.message.text == "💼 Байнгын ажил": context.user_data["job_type"] = "full_time"
    elif update.message.text == "⏰ Цагийн ажил": context.user_data["job_type"] = "part_time"
    else: await update.message.reply_text("Төрлөө сонгоно уу."); return J_TYPE
    await update.message.reply_text("Ангилал:", reply_markup=JOB_MENU); return J_CATEGORY
async def j_cat(update, context):
    if update.message.text not in JOB_CATEGORIES: await update.message.reply_text("Ангиллаа товчоор сонгоно уу."); return J_CATEGORY
    context.user_data["category"] = update.message.text; await update.message.reply_text("Цалин/хөлс:"); return J_SALARY
async def j_salary(update, context): context.user_data["salary"] = update.message.text.strip(); await update.message.reply_text("Ажлын цаг, хуваарь:"); return J_SCHEDULE
async def j_schedule(update, context): context.user_data["schedule"] = update.message.text.strip(); await update.message.reply_text("Байршил:"); return J_LOCATION
async def j_location(update, context): context.user_data["location"] = update.message.text.strip(); await update.message.reply_text("Үүрэг, шаардлага:"); return J_DESCRIPTION
async def j_desc(update, context):
    context.user_data["description"] = update.message.text.strip(); jid = add_job(context.user_data); j = get_job(jid); context.user_data.clear()
    await update.message.reply_text(f"✅ Зар #{jid} хүлээн авлаа. Админ батална.", reply_markup=BUSINESS_MENU)
    if ADMIN_ID:
        await context.bot.send_message(ADMIN_ID, "🆕 <b>Шинэ ажлын зар</b>\n\n" + job_text(j), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Энгийн", callback_data=f"job_free:{jid}"), InlineKeyboardButton("⭐ Premium 24ц / 5,000₮", callback_data=f"job_premium:{jid}")], [InlineKeyboardButton("👑 VIP 30хон / 35,000₮", callback_data=f"job_vip:{jid}"), InlineKeyboardButton("❌ Татгалзах", callback_data=f"job_no:{jid}")]]))
    return ConversationHandler.END


# ----- Хайлт -----
async def browse_services(update, context):
    context.user_data.pop("browse_job_type", None)
    await update.message.reply_text("Үйлчилгээний ангилал сонгоно уу:", reply_markup=SERVICE_MENU)
async def browse_full(update, context): context.user_data["browse_job_type"] = "full_time"; await update.message.reply_text("Байнгын ажлын ангилал:", reply_markup=JOB_MENU)
async def browse_part(update, context): context.user_data["browse_job_type"] = "part_time"; await update.message.reply_text("Цагийн ажлын ангилал:", reply_markup=JOB_MENU)
async def service_category(update, context):
    businesses = get_businesses_by_category(update.message.text)
    if not businesses: await update.message.reply_text("Одоогоор байгууллага алга.", reply_markup=SERVICE_MENU); return
    for b in businesses:
        services = get_services_by_business(b["id"])
        await update.message.reply_text(business_text(b), parse_mode=ParseMode.HTML)
        for s0 in services:
            s = get_service(s0["id"])
            await update.message.reply_text(service_text(s), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📅 Цаг захиалах", callback_data=f"book:{s['id']}")]]))
async def job_category(update, context):
    job_type = context.user_data.get("browse_job_type")
    if not job_type: return
    jobs = get_approved_jobs(job_type, update.message.text)
    if not jobs: await update.message.reply_text("Одоогоор зар алга.", reply_markup=JOB_MENU); return
    for j in jobs:
        await update.message.reply_text(job_text(j), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🤝 Match шалгах", callback_data=f"match:{j['id']}"), InlineKeyboardButton("✅ Сонирхож байна", callback_data=f"interest:{j['id']}")]]))

async def category_router(update, context):
    category = update.message.text
    if context.user_data.get("browse_job_type") and category in JOB_CATEGORIES:
        await job_category(update, context)
    elif category in SERVICE_CATEGORIES:
        await service_category(update, context)
    else:
        await update.message.reply_text("Эхлээд Үйлчилгээ, Байнгын ажил эсвэл Цагийн ажил хэсгээ сонгоно уу.", reply_markup=MAIN_MENU)


# ----- Захиалга -----
async def book_callback(update, context):
    q = update.callback_query; s = get_service(int(q.data.split(":")[1]))
    if not s or s["business_status"] != "approved": await q.answer("Үйлчилгээ идэвхгүй.", show_alert=True); return ConversationHandler.END
    context.user_data["booking_service_id"] = s["id"]
    await q.answer(); await q.message.reply_text("Хүсэж буй өдөр, цагаа бичнэ үү. Жишээ: 2026-08-02 15:00")
    return BK_TIME
async def bk_time(update, context): context.user_data["requested_time"] = update.message.text.strip(); await update.message.reply_text("Нэмэлт тайлбар (байхгүй бол - гэж бичнэ үү):"); return BK_NOTE
async def bk_note(update, context):
    sid = context.user_data.pop("booking_service_id"); requested = context.user_data.pop("requested_time"); note = update.message.text.strip()
    bid, created = create_booking(sid, update.effective_user.id, requested, note)
    b = get_booking(bid)
    await update.message.reply_text("✅ Захиалгын хүсэлт илгээгдлээ." if created else "Энэ цагийн хүсэлт өмнө бүртгэгдсэн байна.", reply_markup=MAIN_MENU)
    if created:
        await context.bot.send_message(b["owner_id"], f"📅 <b>ШИНЭ ЗАХИАЛГА</b>\n\n🏢 {escape(b['business_name'])}\n🛍 {escape(b['service_title'])}\n👤 {escape(b['full_name'] or str(b['customer_id']))}\n☎️ {escape(b['phone'] or 'Анкетгүй')}\n🕒 {escape(b['requested_time'])}\n📝 {escape(b['note'] or '-')}", parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Батлах", callback_data=f"booking_yes:{bid}"), InlineKeyboardButton("❌ Татгалзах", callback_data=f"booking_no:{bid}")]]))
    return ConversationHandler.END


# ----- Match -----
async def match_callback(update, context):
    q = update.callback_query; user = get_user(q.from_user.id); job = get_job(int(q.data.split(":")[1]))
    if not user: await q.answer("Эхлээд анкетаа бөглөнө үү.", show_alert=True); return
    score = match_score(user, job); await q.answer(); await q.message.reply_text(f"🤖 Таны Match: <b>{score}%</b>", parse_mode=ParseMode.HTML)
async def interest_callback(update, context):
    q = update.callback_query; user = get_user(q.from_user.id); job = get_job(int(q.data.split(":")[1]))
    if not user: await q.answer("Эхлээд анкетаа бөглөнө үү.", show_alert=True); return
    if q.from_user.id == job["employer_id"]: await q.answer("Өөрийн зар дээр хүсэлт өгөхгүй.", show_alert=True); return
    score = match_score(user, job); mid, created = create_or_get_match(job["id"], q.from_user.id, score)
    await q.answer("Сонирхлоо илгээлээ." if created else "Өмнө илгээсэн байна.", show_alert=True)
    if created:
        await context.bot.send_message(job["employer_id"], f"🤝 <b>ШИНЭ MATCH</b>\n\n💼 {escape(job['title'])}\n👤 {escape(user['full_name'])}\n🧰 {escape(user['profession'] or '-') }\n📚 {escape(user['experience'] or '-') }\n⭐ {score}%\n\n🔒 Холбоо барих мэдээлэл нууц.", parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Зөвшөөрөх", callback_data=f"emp_yes:{mid}"), InlineKeyboardButton("❌ Татгалзах", callback_data=f"emp_no:{mid}")]]))


# ----- Callback admin/decision -----
async def business_admin(update, context):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID: await q.answer("Админ эрхгүй.", show_alert=True); return
    action, raw = q.data.split(":"); bid = int(raw); b = get_business(bid); ok = approve_business(bid, action == "biz_yes")
    await q.answer("Шийдвэр хадгалагдлаа." if ok else "Өмнө шийдвэрлэсэн.", show_alert=True); await q.edit_message_reply_markup(None)
    if ok: await context.bot.send_message(b["owner_id"], "✅ Байгууллага батлагдлаа." if action == "biz_yes" else "❌ Байгууллагын бүртгэл татгалзагдлаа.")
async def publish_job_to_channel(context, job):
    bot_username = (await context.bot.get_me()).username
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📄 Анкет илгээх", url=f"https://t.me/{bot_username}?start=job_{job['id']}"),
        InlineKeyboardButton("💬 Premium захиалах", url=f"https://t.me/{PREMIUM_CONTACT}"),
    ]])
    message = await context.bot.send_message(
        CHANNEL_ID,
        job_text(job),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    set_job_channel_message(job["id"], message.message_id)


async def job_admin(update, context):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer("Админ эрхгүй.", show_alert=True)
        return
    action, raw = q.data.split(":")
    jid = int(raw)
    before = get_job(jid)
    if action == "job_free":
        ok = approve_job(jid, "free")
    elif action == "job_premium":
        ok = approve_job(jid, "premium", 1)
    elif action == "job_vip":
        ok = approve_job(jid, "vip", 30)
    else:
        ok = reject_job(jid)
    await q.answer("Шийдвэр хадгалагдлаа." if ok else "Өмнө шийдвэрлэсэн.", show_alert=True)
    await q.edit_message_reply_markup(None)
    if not ok:
        return
    if action == "job_no":
        await context.bot.send_message(before["employer_id"], "❌ Ажлын зар татгалзагдлаа.")
        return
    job = get_job(jid)
    try:
        await publish_job_to_channel(context, job)
    except Exception:
        logger.exception("Channel нийтлэл амжилтгүй: job_id=%s", jid)
        await context.bot.send_message(ADMIN_ID, f"⚠️ Зар #{jid}-г {CHANNEL_ID} channel-д нийтэлж чадсангүй. Bot админ эсэхийг шалгана уу.")
    await context.bot.send_message(job["employer_id"], "✅ Ажлын зар батлагдаж channel-д нийтлэгдлээ.")
    for row in get_notifiable_users(exclude_id=job["employer_id"]):
        try:
            await context.bot.send_message(row["telegram_id"], f"🔔 <b>Шинэ ажлын зар</b>\n\n{job_text(job)}", parse_mode=ParseMode.HTML)
        except Exception:
            logger.debug("Мэдэгдэл хүрсэнгүй: %s", row["telegram_id"])


async def user_admin(update, context):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer("Админ эрхгүй.", show_alert=True)
        return
    action, raw = q.data.split(":")
    uid = int(raw)
    if action == "user_free":
        ok = approve_user(uid, "free")
    elif action == "user_premium":
        ok = approve_user(uid, "premium", 24)
    else:
        ok = reject_user(uid)
    await q.answer("Шийдвэр хадгалагдлаа." if ok else "Өмнө шийдвэрлэсэн.", show_alert=True)
    await q.edit_message_reply_markup(None)
    if not ok:
        return
    if action == "user_no":
        await context.bot.send_message(uid, "❌ Таны анкет татгалзагдлаа.")
        return
    user = get_user(uid)
    contact_url = f"https://t.me/{user['username']}" if user["username"] else f"tg://user?id={uid}"
    try:
        msg = await context.bot.send_message(
            CHANNEL_ID,
            user_text(user),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 Холбогдох", url=contact_url)]]),
        )
        set_user_channel_message(uid, msg.message_id)
    except Exception:
        logger.exception("Анкет channel-д нийтлэхэд алдаа гарлаа: %s", uid)
    await context.bot.send_message(uid, "✅ Таны анкет батлагдаж channel-д нийтлэгдлээ.")


async def booking_decision(update, context):
    q = update.callback_query; action, raw = q.data.split(":"); bid = int(raw); b = get_booking(bid)
    ok = set_booking_status(bid, q.from_user.id, "approved" if action == "booking_yes" else "rejected")
    await q.answer("Шийдвэр хадгалагдлаа." if ok else "Өмнө шийдвэрлэсэн.", show_alert=True); await q.edit_message_reply_markup(None)
    if ok: await context.bot.send_message(b["customer_id"], f"{'✅' if action == 'booking_yes' else '❌'} {b['business_name']} таны {b['requested_time']} цагийн захиалгыг {'баталлаа' if action == 'booking_yes' else 'татгалзлаа'}.")
async def employer_decision(update, context):
    q = update.callback_query
    action, raw = q.data.split(":")
    mid = int(raw)
    m = get_match(mid)
    if not m or q.from_user.id != m["employer_id"]:
        await q.answer("Эрхгүй.", show_alert=True)
        return

    accepted = action == "emp_yes"
    ok = set_employer_decision(mid, accepted)
    await q.answer("Шийдвэр хадгалагдлаа." if ok else "Өмнө шийдвэрлэсэн.", show_alert=True)
    await q.edit_message_reply_markup(None)
    if not ok:
        return
    if not accepted:
        await context.bot.send_message(
            m["applicant_id"],
            "ℹ️ Ажил олгогч Match хүсэлтийг үргэлжлүүлээгүй.",
        )
        return

    applicant_username = f"@{m['applicant_username']}" if m["applicant_username"] else "байхгүй"
    employer_username = f"@{m['employer_username']}" if m["employer_username"] else "байхгүй"

    await context.bot.send_message(
        m["employer_id"],
        "🎉 <b>MATCH АМЖИЛТТАЙ</b>\n\n"
        f"👤 {escape(m['full_name'])}\n"
        f"☎️ {escape(m['phone'])}\n"
        f"💬 Telegram: {escape(applicant_username)}\n"
        f"🧰 {escape(m['profession'] or '-')}\n"
        f"📚 {escape(m['experience'] or '-')}",
        parse_mode=ParseMode.HTML,
    )
    await context.bot.send_message(
        m["applicant_id"],
        "🎉 <b>MATCH АМЖИЛТТАЙ</b>\n\n"
        f"🏢 {escape(m['company'])}\n"
        f"💼 {escape(m['title'])}\n"
        f"💬 Ажил олгогчийн Telegram: {escape(employer_username)}",
        parse_mode=ParseMode.HTML,
    )
    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            f"✅ Match #{mid}: хоёр тал холбогдлоо.",
        )


async def my_services(update, context):
    b = get_business_by_owner(update.effective_user.id)
    if not b: await update.message.reply_text("Байгууллага олдсонгүй.", reply_markup=BUSINESS_MENU); return
    services = get_services_by_business(b["id"])
    if not services: await update.message.reply_text("Үйлчилгээ бүртгээгүй байна.", reply_markup=BUSINESS_MENU); return
    for s0 in services: await update.message.reply_text(service_text(get_service(s0["id"])), parse_mode=ParseMode.HTML)


async def admin_stats(update, context):
    if update.effective_user.id != ADMIN_ID: return
    d = stats(); await update.message.reply_text("📊 ServiGo статистик\n\n" + "\n".join([
        f"👥 Хэрэглэгч: {d['users']}", f"🏢 Байгууллага: {d['businesses']}", f"✅ Батлагдсан: {d['approved_businesses']}",
        f"🛍 Үйлчилгээ: {d['services']}", f"📅 Захиалга: {d['bookings']}", f"💼 Ажлын зар: {d['jobs']}",
        f"⏰ Цагийн ажил: {d['part_time_jobs']}", f"🤝 Match: {d['matches']}"
    ]))


async def premium_info(update, context):
    await update.message.reply_text(
        "⭐ <b>ServiGo Premium үйлчилгээ</b>\n\n"
        "🏢 Байгууллагын Premium зар\n⏰ 24 цаг — <b>5,000₮</b>\n\n"
        "👑 VIP зар\n📅 30 хоног — <b>35,000₮</b>\n\n"
        "👤 Ажил хайгчийн Premium анкет\n⏰ 24 цаг — <b>3,000₮</b>\n\n"
        "Төлбөр болон идэвхжүүлэлт: @bayanburd",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 @bayanburd", url=f"https://t.me/{PREMIUM_CONTACT}")]]),
    )


async def notification_toggle(update, context):
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Эхлээд анкетаа бөглөнө үү.", reply_markup=MAIN_MENU)
        return
    enabled = toggle_notifications(update.effective_user.id)
    await update.message.reply_text("🔔 Мэдэгдэл асаалаа." if enabled else "🔕 Мэдэгдэл унтраалаа.", reply_markup=MAIN_MENU)


async def refresh_promoted_posts(application):
    while True:
        await asyncio.sleep(300)
        for job in get_promoted_jobs():
            try:
                await application.bot.edit_message_text(
                    chat_id=CHANNEL_ID,
                    message_id=job["channel_message_id"],
                    text=job_text(job),
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 Premium захиалах", url=f"https://t.me/{PREMIUM_CONTACT}")]]),
                )
            except Exception:
                logger.debug("Зарын цаг шинэчилж чадсангүй: %s", job["id"])
        for user in get_promoted_users():
            try:
                await application.bot.edit_message_text(
                    chat_id=CHANNEL_ID,
                    message_id=user["channel_message_id"],
                    text=user_text(user),
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                logger.debug("Анкетын цаг шинэчилж чадсангүй: %s", user["telegram_id"])


async def post_init(application):
    application.create_task(refresh_promoted_posts(application))


async def help_message(update, context):
    await update.message.reply_text("ServiGo дээр та:\n• Үйлчилгээ хайж цаг захиална\n• Байнгын болон цагийн ажил хайна\n• Байгууллага бүртгэж үйлчилгээ, ажлын зар байршуулна\n• Match амжилттай бол холбоо нээгдэнэ")


def main():
    init_db(); app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start)); app.add_handler(CommandHandler("cancel", cancel)); app.add_handler(CommandHandler("stats", admin_stats))

    app.add_handler(ConversationHandler(entry_points=[MessageHandler(filters.Regex("^👤 Миний анкет$"), profile_start)], states={P_NAME:[MessageHandler(filters.TEXT & ~filters.COMMAND,p_name)],P_PHONE:[MessageHandler(filters.TEXT & ~filters.COMMAND,p_phone)],P_PROFESSION:[MessageHandler(filters.TEXT & ~filters.COMMAND,p_prof)],P_EXPERIENCE:[MessageHandler(filters.TEXT & ~filters.COMMAND,p_exp)],P_SALARY:[MessageHandler(filters.TEXT & ~filters.COMMAND,p_salary)]}, fallbacks=[CommandHandler("cancel",cancel)]))
    app.add_handler(ConversationHandler(entry_points=[MessageHandler(filters.Regex("^🏢 Байгууллага бүртгэх$"), business_start)], states={B_NAME:[MessageHandler(filters.TEXT & ~filters.COMMAND,b_name)],B_CATEGORY:[MessageHandler(filters.TEXT & ~filters.COMMAND,b_cat)],B_PHONE:[MessageHandler(filters.TEXT & ~filters.COMMAND,b_phone)],B_LOCATION:[MessageHandler(filters.TEXT & ~filters.COMMAND,b_location)],B_DESCRIPTION:[MessageHandler(filters.TEXT & ~filters.COMMAND,b_desc)]}, fallbacks=[CommandHandler("cancel",cancel)]))
    app.add_handler(ConversationHandler(entry_points=[MessageHandler(filters.Regex("^➕ Үйлчилгээ нэмэх$"), service_start)], states={S_TITLE:[MessageHandler(filters.TEXT & ~filters.COMMAND,s_title)],S_PRICE:[MessageHandler(filters.TEXT & ~filters.COMMAND,s_price)],S_DURATION:[MessageHandler(filters.TEXT & ~filters.COMMAND,s_duration)],S_DESCRIPTION:[MessageHandler(filters.TEXT & ~filters.COMMAND,s_desc)]}, fallbacks=[CommandHandler("cancel",cancel)]))
    app.add_handler(ConversationHandler(entry_points=[MessageHandler(filters.Regex("^📢 Байнгын ажилтан хайх$"), job_start_full), MessageHandler(filters.Regex("^⏰ Цагийн ажилтан хайх$"), job_start_part)], states={J_TITLE:[MessageHandler(filters.TEXT & ~filters.COMMAND,j_title)],J_TYPE:[MessageHandler(filters.TEXT & ~filters.COMMAND,j_type)],J_CATEGORY:[MessageHandler(filters.TEXT & ~filters.COMMAND,j_cat)],J_SALARY:[MessageHandler(filters.TEXT & ~filters.COMMAND,j_salary)],J_SCHEDULE:[MessageHandler(filters.TEXT & ~filters.COMMAND,j_schedule)],J_LOCATION:[MessageHandler(filters.TEXT & ~filters.COMMAND,j_location)],J_DESCRIPTION:[MessageHandler(filters.TEXT & ~filters.COMMAND,j_desc)]}, fallbacks=[CommandHandler("cancel",cancel)]))
    app.add_handler(ConversationHandler(entry_points=[CallbackQueryHandler(book_callback, pattern=r"^book:\d+$")], states={BK_TIME:[MessageHandler(filters.TEXT & ~filters.COMMAND,bk_time)],BK_NOTE:[MessageHandler(filters.TEXT & ~filters.COMMAND,bk_note)]}, fallbacks=[CommandHandler("cancel",cancel)], per_message=False))

    app.add_handler(MessageHandler(filters.Regex("^🏢 Байгууллагын хэсэг$"), business_menu)); app.add_handler(MessageHandler(filters.Regex("^⭐ Premium үйлчилгээ$"), premium_info)); app.add_handler(MessageHandler(filters.Regex("^🔔 Мэдэгдэл$"), notification_toggle)); app.add_handler(MessageHandler(filters.Regex("^🔎 Үйлчилгээ хайх$"), browse_services)); app.add_handler(MessageHandler(filters.Regex("^💼 Байнгын ажил$"), browse_full)); app.add_handler(MessageHandler(filters.Regex("^⏰ Цагийн ажил$"), browse_part)); app.add_handler(MessageHandler(filters.Regex("^📋 Миний үйлчилгээ$"), my_services)); app.add_handler(MessageHandler(filters.Regex("^🔙 Үндсэн цэс$"), start)); app.add_handler(MessageHandler(filters.Regex("^ℹ️ Тусламж$"), help_message))
    all_categories = sorted(set(SERVICE_CATEGORIES + JOB_CATEGORIES))
    app.add_handler(MessageHandler(filters.Regex("^(" + "|".join(map(re.escape, all_categories)) + ")$"), category_router))

    app.add_handler(CallbackQueryHandler(match_callback, pattern=r"^match:\d+$")); app.add_handler(CallbackQueryHandler(interest_callback, pattern=r"^interest:\d+$")); app.add_handler(CallbackQueryHandler(business_admin, pattern=r"^biz_(yes|no):\d+$")); app.add_handler(CallbackQueryHandler(job_admin, pattern=r"^job_(free|premium|vip|no):\d+$")); app.add_handler(CallbackQueryHandler(user_admin, pattern=r"^user_(free|premium|no):\d+$")); app.add_handler(CallbackQueryHandler(booking_decision, pattern=r"^booking_(yes|no):\d+$")); app.add_handler(CallbackQueryHandler(employer_decision, pattern=r"^emp_(yes|no):\d+$"))

    print("ServiGo bot ажиллаж эхэллээ..."); app.run_polling(drop_pending_updates=True)


if __name__ == "__main__": main()
