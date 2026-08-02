import asyncio
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from textwrap import wrap

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
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
    add_business,
    add_job,
    approve_business,
    approve_job,
    approve_user,
    create_or_get_match,
    get_approved_jobs,
    get_business,
    get_business_by_owner,
    get_job,
    get_jobs_by_employer,
    get_match,
    get_promoted_jobs,
    get_promoted_users,
    get_user,
    init_db,
    reject_job,
    reject_user,
    save_user,
    set_employer_decision,
    set_job_channel_message,
    set_user_channel_message,
    stats,
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = os.getenv("CHANNEL_ID", "@servigomgl").strip()
PREMIUM_CONTACT = os.getenv("PREMIUM_CONTACT", "bayanburd").lstrip("@").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN олдсонгүй.")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

JOB_CATEGORIES = [
    "☕ Үйлчилгээ",
    "🚗 Жолооч",
    "🏗 Барилга",
    "💻 IT",
    "📊 Оффис",
    "🛒 Худалдаа",
    "🍔 Ресторан",
    "🏭 Үйлдвэр",
    "📦 Ложистик",
    "🎓 Боловсрол",
    "🔧 Инженер",
    "🏥 Эрүүл мэнд",
]

(
    P_NAME,
    P_PHONE,
    P_PROFESSION,
    P_EXPERIENCE,
    P_SALARY,
    B_NAME,
    B_CATEGORY,
    B_PHONE,
    B_LOCATION,
    B_DESCRIPTION,
    J_TITLE,
    J_CATEGORY,
    J_SALARY,
    J_SCHEDULE,
    J_LOCATION,
    J_DESCRIPTION,
) = range(16)

ROLE_MENU = ReplyKeyboardMarkup(
    [["👤 Ажил хайгч", "🏢 Ажил олгогч"]],
    resize_keyboard=True,
)

JOB_SEEKER_MENU = ReplyKeyboardMarkup(
    [
        ["💼 Байнгын ажил", "⏰ Цагийн ажил"],
        ["👤 Миний анкет", "⭐ VIP зар"],
        ["🔄 Горим солих"],
    ],
    resize_keyboard=True,
)

EMPLOYER_MENU = ReplyKeyboardMarkup(
    [
        ["🏢 Байгууллага бүртгэх"],
        ["➕ Байнгын ажлын зар", "➕ Цагийн ажлын зар"],
        ["📋 Миний зарууд", "⭐ VIP зар"],
        ["🔄 Горим солих"],
    ],
    resize_keyboard=True,
)

JOB_MENU = ReplyKeyboardMarkup(
    [[JOB_CATEGORIES[i], JOB_CATEGORIES[i + 1]] for i in range(0, len(JOB_CATEGORIES), 2)]
    + [["🔙 Буцах"]],
    resize_keyboard=True,
)

CARD_DIR = Path(tempfile.gettempdir()) / "servigo_cards"
CARD_DIR.mkdir(parents=True, exist_ok=True)
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def font(size: int, bold: bool = False):
    path = FONT_BOLD_PATH if bold else FONT_PATH
    return ImageFont.truetype(path, size)


def remaining_text(expires_at):
    if not expires_at:
        return ""
    try:
        end = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        seconds = max(0, int((end - datetime.now(timezone.utc)).total_seconds()))
        if seconds <= 0:
            return "Хугацаа дууссан"
        days, rem = divmod(seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        if days:
            return f"{days} өдөр {hours} цаг"
        return f"{hours:02d}:{minutes:02d}"
    except (TypeError, ValueError):
        return ""


def user_text(u):
    badge = "⭐ <b>PREMIUM АНКЕТ</b>\n" if u["plan"] == "premium" else "👤 <b>АЖИЛ ХАЙЖ БАЙНА</b>\n"
    timer = remaining_text(u["premium_expires_at"])
    timer_line = f"⏳ Үлдсэн: {timer}\n\n" if timer else "\n"
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
    badge = "✅ <b>БАТАЛГААЖСАН</b>\n" if b["status"] == "approved" else ""
    return (
        f"{badge}🏢 <b>{escape(b['name'])}</b>\n"
        f"📂 {escape(b['category'])}\n"
        f"📍 {escape(b['location'])}\n"
        f"☎️ {escape(b['phone'])}\n\n"
        f"{escape(b['description'])}\n\n"
        f"🆔 Байгууллага #{b['id']}"
    )


def job_text(j):
    badge = "👑 <b>VIP ЗАР</b>" if j["plan"] == "vip" else ("⭐ <b>PREMIUM ЗАР</b>" if j["plan"] == "premium" else "💼 <b>АЖЛЫН ЗАР</b>")
    timer = remaining_text(j["premium_expires_at"]) if j["plan"] in {"premium", "vip"} else ""
    timer_line = f"\n⏳ Үлдсэн: <b>{timer}</b>" if timer else ""
    type_label = "⏰ Цагийн ажил" if j["job_type"] == "part_time" else "💼 Байнгын ажил"
    return (
        f"{badge}{timer_line}\n\n"
        f"🏢 <b>{escape(j['company'])}</b>\n"
        f"{type_label}\n"
        f"💼 <b>{escape(j['title'])}</b>\n"
        f"📂 {escape(j['category'])}\n"
        f"💰 {escape(j['salary'])}\n"
        f"🕒 {escape(j['schedule'])}\n"
        f"📍 {escape(j['location'])}\n\n"
        f"📌 <b>Шаардлага</b>\n{escape(j['description'])}\n\n"
        f"🆔 Зар #{j['id']}"
    )


def _rounded(draw, xy, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _fit_text(draw, text, max_width, start_size=58, min_size=28, bold=True):
    for size in range(start_size, min_size - 1, -2):
        fnt = font(size, bold)
        box = draw.textbbox((0, 0), text, font=fnt)
        if box[2] - box[0] <= max_width:
            return fnt
    return font(min_size, bold)


def _draw_wrapped(draw, text, xy, max_chars, fnt, fill, line_gap=10, max_lines=4):
    x, y = xy
    lines = wrap(text or "-", width=max_chars)[:max_lines]
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill)
        y += fnt.size + line_gap
    return y


def create_job_card(job) -> Path:
    """VIP/Premium зарын өнгөлөг PNG карт үүсгэнэ."""
    width, height = 1080, 1420
    img = Image.new("RGB", (width, height), "#06152b")
    draw = ImageDraw.Draw(img)

    # Градиент суурь
    for y in range(height):
        ratio = y / height
        r = int(8 + 10 * ratio)
        g = int(18 + 4 * ratio)
        b = int(48 + 18 * ratio)
        draw.line((0, y, width, y), fill=(r, g, b))

    # Неон хүрээ
    border = "#ffcc22" if job["plan"] == "vip" else "#8e5bff"
    _rounded(draw, (34, 34, width - 34, height - 34), 42, "#071c35", border, 7)
    _rounded(draw, (50, 50, width - 50, height - 50), 34, "#07182d", "#e82da8", 2)

    # Гарчиг тууз
    title_fill = "#ffc928" if job["plan"] == "vip" else "#8e5bff"
    _rounded(draw, (72, 74, 410, 160), 20, title_fill)
    draw.text((102, 94), "👑 VIP ЗАР" if job["plan"] == "vip" else "⭐ PREMIUM", font=font(43, True), fill="#08111f")

    timer = remaining_text(job["premium_expires_at"]) or "Идэвхтэй"
    _rounded(draw, (720, 74, 1006, 190), 24, "#ffbd18")
    draw.text((754, 91), "⏱ Үлдэх хугацаа", font=font(24, True), fill="#101827")
    timer_font = _fit_text(draw, timer, 220, 48, 32, True)
    draw.text((752, 127), timer, font=timer_font, fill="#101827")

    # Company, title
    company_font = _fit_text(draw, str(job["company"]), 830, 55, 30, True)
    draw.text((78, 230), str(job["company"]), font=company_font, fill="white")
    _rounded(draw, (78, 310, 410, 376), 18, "#6f38c7")
    type_label = "⏰ Цагийн ажил" if job["job_type"] == "part_time" else "💼 Байнгын ажил"
    draw.text((105, 326), type_label, font=font(30, True), fill="white")

    title_font = _fit_text(draw, str(job["title"]), 880, 74, 38, True)
    draw.text((78, 420), str(job["title"]), font=title_font, fill="white")

    # Цалин
    _rounded(draw, (78, 535, 1002, 665), 28, "#082b24", "#29d75f", 3)
    draw.text((112, 560), "💰", font=font(48, True), fill="#67ef54")
    salary_font = _fit_text(draw, str(job["salary"]), 760, 66, 34, True)
    draw.text((205, 558), str(job["salary"]), font=salary_font, fill="#68e94d")

    # Мэдээллийн 3 блок
    info_y = 705
    col_w = 300
    info = [
        ("🕒 Ажлын цаг", str(job["schedule"]), "#32a9ff"),
        ("📍 Байршил", str(job["location"]), "#c85cff"),
        ("📂 Ангилал", str(job["category"]), "#ff9f1c"),
    ]
    for i, (head, value, color) in enumerate(info):
        x = 78 + i * 310
        _rounded(draw, (x, info_y, x + col_w, info_y + 175), 22, "#0a213d", color, 2)
        draw.text((x + 22, info_y + 20), head, font=font(24, True), fill=color)
        _draw_wrapped(draw, value, (x + 22, info_y + 66), 17, font(25, True), "white", 7, 3)

    # Шаардлага
    req_y = 920
    _rounded(draw, (78, req_y, 1002, 1215), 26, "#0a213a", "#fa4f9c", 2)
    draw.text((108, req_y + 24), "🎯 ШААРДЛАГА", font=font(34, True), fill="#ff5ca8")
    description = str(job["description"] or "-").replace("•", "").strip()
    lines = re.split(r"[\n;]+", description)
    y = req_y + 86
    for raw in lines:
        for line in wrap(raw.strip(), width=58):
            if not line:
                continue
            draw.ellipse((112, y + 7, 130, y + 25), fill="#ff4f9c")
            draw.text((146, y), line, font=font(26), fill="white")
            y += 43
            if y > req_y + 250:
                break
        if y > req_y + 250:
            break

    # Footer
    _rounded(draw, (78, 1250, 1002, 1345), 22, "#172755", "#895cff", 2)
    draw.text((118, 1275), f"🚀 ServiGo  •  Зар #{job['id']}  •  Ажилтай холбогдох шинэ боломж", font=font(28, True), fill="white")

    path = CARD_DIR / f"job_{job['id']}_{int(datetime.now().timestamp())}.png"
    img.save(path, "PNG", optimize=True)
    return path


def match_score(user, job):
    score = 50
    words = set(re.findall(r"\w{3,}", (user["profession"] or "").lower()))
    target = set(re.findall(r"\w{3,}", (job["title"] + " " + job["description"]).lower()))
    score += min(len(words & target) * 10, 30)
    desired = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", user["desired_salary"] or "")]
    offered = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", job["salary"])]
    if desired and offered and max(offered) >= max(desired):
        score += 15
    return min(score, 99)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    # Channel-аас "Анкет илгээх" дарж орсон хэрэглэгчид тухайн зарыг нээнэ.
    if context.args and context.args[0].startswith("job_"):
        try:
            job_id = int(context.args[0].split("_", 1)[1])
            job = get_job(job_id)
            if job and job["status"] == "approved":
                await update.message.reply_text(
                    job_text(job),
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(
                        [[
                            InlineKeyboardButton("🤝 Match шалгах", callback_data=f"match:{job_id}"),
                            InlineKeyboardButton("📨 Сонирхож байна", callback_data=f"interest:{job_id}"),
                        ]]
                    ),
                )
                return
        except (ValueError, IndexError):
            pass

    await update.message.reply_text(
        "🚀 <b>ServiGo-д тавтай морил!</b>\n\nТа аль хэсгээр үргэлжлүүлэх вэ?",
        parse_mode=ParseMode.HTML,
        reply_markup=ROLE_MENU,
    )


async def open_job_seeker_menu(update, context):
    context.user_data.clear()
    context.user_data["role"] = "job_seeker"
    await update.message.reply_text(
        "👤 <b>Ажил хайгчийн хэсэг</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=JOB_SEEKER_MENU,
    )


async def open_employer_menu(update, context):
    context.user_data.clear()
    context.user_data["role"] = "employer"
    business = get_business_by_owner(update.effective_user.id)
    if business and business["status"] == "approved":
        text = f"🏢 <b>Ажил олгогчийн хэсэг</b>\n\nБайгууллага: <b>{escape(business['name'])}</b>"
    elif business:
        text = "🏢 <b>Ажил олгогчийн хэсэг</b>\n\nТаны байгууллагын бүртгэл админы шийдвэрийг хүлээж байна."
    else:
        text = "🏢 <b>Ажил олгогчийн хэсэг</b>\n\nЭхлээд байгууллагаа бүртгүүлнэ үү."
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=EMPLOYER_MENU)


async def change_role(update, context):
    context.user_data.clear()
    await update.message.reply_text("Та аль хэсгээр үргэлжлүүлэх вэ?", reply_markup=ROLE_MENU)


async def cancel(update, context):
    role = context.user_data.get("role")
    context.user_data.clear()
    menu = JOB_SEEKER_MENU if role == "job_seeker" else EMPLOYER_MENU if role == "employer" else ROLE_MENU
    if role:
        context.user_data["role"] = role
    await update.message.reply_text("Үйлдлийг цуцаллаа.", reply_markup=menu)
    return ConversationHandler.END


# ----- Хэрэглэгчийн анкет -----
async def profile_start(update, context):
    context.user_data["role"] = "job_seeker"
    await update.message.reply_text("Овог нэрээ оруулна уу:")
    return P_NAME


async def p_name(update, context):
    context.user_data["full_name"] = update.message.text.strip()
    await update.message.reply_text("Утасны дугаар:")
    return P_PHONE


async def p_phone(update, context):
    context.user_data["phone"] = update.message.text.strip()
    await update.message.reply_text("Мэргэжил, хийж чадах ажил:")
    return P_PROFESSION


async def p_prof(update, context):
    context.user_data["profession"] = update.message.text.strip()
    await update.message.reply_text("Туршлага:")
    return P_EXPERIENCE


async def p_exp(update, context):
    context.user_data["experience"] = update.message.text.strip()
    await update.message.reply_text("Хүсэж буй цалин:")
    return P_SALARY


async def p_salary(update, context):
    u = update.effective_user
    context.user_data.update(
        desired_salary=update.message.text.strip(),
        telegram_id=u.id,
        username=u.username,
    )
    save_user(context.user_data)
    saved = get_user(u.id)
    context.user_data.clear()
    context.user_data["role"] = "job_seeker"
    await update.message.reply_text(
        "✅ Анкет хүлээн авлаа. Админ шалгаж батална.",
        reply_markup=JOB_SEEKER_MENU,
    )
    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            "🆕 <b>Шинэ ажил хайгчийн анкет</b>\n\n" + user_text(saved),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("✅ Энгийн", callback_data=f"user_free:{u.id}"),
                        InlineKeyboardButton("⭐ Premium 24ц / 3,000₮", callback_data=f"user_premium:{u.id}"),
                    ],
                    [
                        InlineKeyboardButton("❌ Татгалзах", callback_data=f"user_no:{u.id}"),
                        InlineKeyboardButton("💬 Админ", url=f"https://t.me/{PREMIUM_CONTACT}"),
                    ],
                ]
            ),
        )
    return ConversationHandler.END


# ----- Байгууллага -----
async def business_start(update, context):
    context.user_data.clear()
    context.user_data.update(
        role="employer",
        owner_id=update.effective_user.id,
        owner_username=update.effective_user.username,
    )
    await update.message.reply_text("Байгууллагын нэр:")
    return B_NAME


async def b_name(update, context):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text("Үйл ажиллагааны чиглэл:", reply_markup=JOB_MENU)
    return B_CATEGORY


async def b_cat(update, context):
    if update.message.text not in JOB_CATEGORIES:
        await update.message.reply_text("Ангиллаа товчоор сонгоно уу.")
        return B_CATEGORY
    context.user_data["category"] = update.message.text
    await update.message.reply_text("Утас:")
    return B_PHONE


async def b_phone(update, context):
    context.user_data["phone"] = update.message.text.strip()
    await update.message.reply_text("Байршил:")
    return B_LOCATION


async def b_location(update, context):
    context.user_data["location"] = update.message.text.strip()
    await update.message.reply_text("Байгууллагын товч танилцуулга:")
    return B_DESCRIPTION


async def b_desc(update, context):
    context.user_data["description"] = update.message.text.strip()
    bid = add_business(context.user_data)
    b = get_business(bid)
    context.user_data.clear()
    context.user_data["role"] = "employer"
    await update.message.reply_text(
        f"✅ Байгууллага #{bid} хүлээн авлаа. Админ батална.",
        reply_markup=EMPLOYER_MENU,
    )
    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            "🆕 <b>Шинэ байгууллага</b>\n\n" + business_text(b),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton("✅ Батлах", callback_data=f"biz_yes:{bid}"),
                    InlineKeyboardButton("❌ Татгалзах", callback_data=f"biz_no:{bid}"),
                ]]
            ),
        )
    return ConversationHandler.END


# ----- Ажлын зар -----
async def job_start_full(update, context):
    return await job_start(update, context, "full_time")


async def job_start_part(update, context):
    return await job_start(update, context, "part_time")


async def job_start(update, context, job_type):
    b = get_business_by_owner(update.effective_user.id)
    if not b or b["status"] != "approved":
        await update.message.reply_text(
            "⚠️ Ажлын зар оруулахын өмнө байгууллагаа бүртгүүлж, админаар батлуулна уу.",
            reply_markup=EMPLOYER_MENU,
        )
        return ConversationHandler.END
    context.user_data.clear()
    context.user_data.update(
        role="employer",
        job_type=job_type,
        employer_id=update.effective_user.id,
        employer_username=update.effective_user.username,
        business_id=b["id"],
        company=b["name"],
    )
    await update.message.reply_text("Ажлын байрны нэр:")
    return J_TITLE


async def j_title(update, context):
    context.user_data["title"] = update.message.text.strip()
    await update.message.reply_text("Ангилал:", reply_markup=JOB_MENU)
    return J_CATEGORY


async def j_cat(update, context):
    if update.message.text not in JOB_CATEGORIES:
        await update.message.reply_text("Ангиллаа товчоор сонгоно уу.")
        return J_CATEGORY
    context.user_data["category"] = update.message.text
    await update.message.reply_text("Цалин/хөлс: (жишээ: 3,000,000₮ / сар)")
    return J_SALARY


async def j_salary(update, context):
    context.user_data["salary"] = update.message.text.strip()
    await update.message.reply_text("Ажлын цаг, хуваарь:")
    return J_SCHEDULE


async def j_schedule(update, context):
    context.user_data["schedule"] = update.message.text.strip()
    await update.message.reply_text("Байршил:")
    return J_LOCATION


async def j_location(update, context):
    context.user_data["location"] = update.message.text.strip()
    await update.message.reply_text("Үүрэг, шаардлага:")
    return J_DESCRIPTION


async def j_desc(update, context):
    context.user_data["description"] = update.message.text.strip()
    jid = add_job(context.user_data)
    j = get_job(jid)
    context.user_data.clear()
    context.user_data["role"] = "employer"
    await update.message.reply_text(
        f"✅ Зар #{jid} хүлээн авлаа. Админ батална.",
        reply_markup=EMPLOYER_MENU,
    )
    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            "🆕 <b>Шинэ ажлын зар</b>\n\n" + job_text(j),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("✅ Энгийн", callback_data=f"job_free:{jid}"),
                        InlineKeyboardButton("⭐ Premium 24ц / 5,000₮", callback_data=f"job_premium:{jid}"),
                    ],
                    [
                        InlineKeyboardButton("👑 VIP 30 хоног / 35,000₮", callback_data=f"job_vip:{jid}"),
                        InlineKeyboardButton("❌ Татгалзах", callback_data=f"job_no:{jid}"),
                    ],
                ]
            ),
        )
    return ConversationHandler.END


# ----- Ажил хайх -----
async def browse_full(update, context):
    context.user_data["role"] = "job_seeker"
    context.user_data["browse_job_type"] = "full_time"
    await update.message.reply_text("Байнгын ажлын ангилал:", reply_markup=JOB_MENU)


async def browse_part(update, context):
    context.user_data["role"] = "job_seeker"
    context.user_data["browse_job_type"] = "part_time"
    await update.message.reply_text("Цагийн ажлын ангилал:", reply_markup=JOB_MENU)


async def job_category(update, context):
    job_type = context.user_data.get("browse_job_type")
    if not job_type:
        return
    jobs = get_approved_jobs(job_type, update.message.text)
    if not jobs:
        await update.message.reply_text("Одоогоор зар алга.", reply_markup=JOB_MENU)
        return
    for job in jobs:
        await update.message.reply_text(
            job_text(job),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton("🤝 Match шалгах", callback_data=f"match:{job['id']}"),
                    InlineKeyboardButton("📨 Сонирхож байна", callback_data=f"interest:{job['id']}"),
                ]]
            ),
        )


async def category_router(update, context):
    if update.message.text in JOB_CATEGORIES and context.user_data.get("browse_job_type"):
        await job_category(update, context)
    else:
        await update.message.reply_text("Эхлээд Байнгын ажил эсвэл Цагийн ажил хэсгээ сонгоно уу.", reply_markup=JOB_SEEKER_MENU)


async def back_menu(update, context):
    role = context.user_data.get("role")
    context.user_data.pop("browse_job_type", None)
    await update.message.reply_text(
        "Үндсэн хэсэг рүү буцлаа.",
        reply_markup=JOB_SEEKER_MENU if role == "job_seeker" else EMPLOYER_MENU,
    )


# ----- Match -----
async def match_callback(update, context):
    q = update.callback_query
    user = get_user(q.from_user.id)
    job = get_job(int(q.data.split(":")[1]))
    if not user:
        await q.answer("Эхлээд анкетаа бөглөнө үү.", show_alert=True)
        return
    score = match_score(user, job)
    await q.answer()
    await q.message.reply_text(f"🤖 Таны Match: <b>{score}%</b>", parse_mode=ParseMode.HTML)


async def interest_callback(update, context):
    q = update.callback_query
    user = get_user(q.from_user.id)
    job = get_job(int(q.data.split(":")[1]))
    if not user:
        await q.answer("Эхлээд анкетаа бөглөнө үү.", show_alert=True)
        return
    if q.from_user.id == job["employer_id"]:
        await q.answer("Өөрийн зар дээр хүсэлт өгөхгүй.", show_alert=True)
        return
    score = match_score(user, job)
    mid, created = create_or_get_match(job["id"], q.from_user.id, score)
    await q.answer("Сонирхлоо илгээлээ." if created else "Өмнө илгээсэн байна.", show_alert=True)
    if created:
        await context.bot.send_message(
            job["employer_id"],
            f"🤝 <b>ШИНЭ MATCH</b>\n\n"
            f"💼 {escape(job['title'])}\n"
            f"👤 {escape(user['full_name'])}\n"
            f"🧰 {escape(user['profession'] or '-')}\n"
            f"📚 {escape(user['experience'] or '-')}\n"
            f"⭐ {score}%\n\n"
            "🔒 Холбоо барих мэдээлэл нууц.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton("✅ Зөвшөөрөх", callback_data=f"emp_yes:{mid}"),
                    InlineKeyboardButton("❌ Татгалзах", callback_data=f"emp_no:{mid}"),
                ]]
            ),
        )


# ----- Channel нийтлэл -----
def employer_contact_url(job):
    if job["employer_username"]:
        return f"https://t.me/{job['employer_username']}"
    return f"tg://user?id={job['employer_id']}"


def channel_keyboard(job, bot_username):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📨 Анкет илгээх", url=f"https://t.me/{bot_username}?start=job_{job['id']}"),
                InlineKeyboardButton("💬 Ажил олгогчтой холбогдох", url=employer_contact_url(job)),
            ],
            [
                InlineKeyboardButton("👑 VIP зар нийтлэх", url=f"https://t.me/{PREMIUM_CONTACT}"),
            ],
        ]
    )


async def publish_job_to_channel(context, job):
    bot_username = (await context.bot.get_me()).username
    keyboard = channel_keyboard(job, bot_username)

    # Premium/VIP зарыг өнгөлөг зурагтай, энгийн зарыг текстээр нийтэлнэ.
    if job["plan"] in {"premium", "vip"}:
        card_path = create_job_card(job)
        with card_path.open("rb") as image_file:
            message = await context.bot.send_photo(
                CHANNEL_ID,
                photo=image_file,
                caption=f"🏢 <b>{escape(job['company'])}</b> • {escape(job['title'])}\n🆔 Зар #{job['id']}",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
    else:
        message = await context.bot.send_message(
            CHANNEL_ID,
            job_text(job),
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    set_job_channel_message(job["id"], message.message_id)


# ----- Admin -----
async def business_admin(update, context):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer("Админ эрхгүй.", show_alert=True)
        return
    action, raw = q.data.split(":")
    bid = int(raw)
    b = get_business(bid)
    ok = approve_business(bid, action == "biz_yes")
    await q.answer("Шийдвэр хадгалагдлаа." if ok else "Өмнө шийдвэрлэсэн.", show_alert=True)
    await q.edit_message_reply_markup(None)
    if ok:
        await context.bot.send_message(
            b["owner_id"],
            "✅ Байгууллага батлагдлаа." if action == "biz_yes" else "❌ Байгууллагын бүртгэл татгалзагдлаа.",
        )


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
        await context.bot.send_message(
            ADMIN_ID,
            f"⚠️ Зар #{jid}-г {CHANNEL_ID} channel-д нийтэлж чадсангүй. Bot channel-ийн админ эсэхийг шалгана уу.",
        )
    await context.bot.send_message(job["employer_id"], "✅ Ажлын зар батлагдаж channel-д нийтлэгдлээ.")


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
    msg = await context.bot.send_message(
        CHANNEL_ID,
        user_text(user),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 Холбогдох", url=contact_url)]]),
    )
    set_user_channel_message(uid, msg.message_id)
    await context.bot.send_message(uid, "✅ Таны анкет батлагдаж channel-д нийтлэгдлээ.")


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
        await context.bot.send_message(m["applicant_id"], "ℹ️ Ажил олгогч Match хүсэлтийг үргэлжлүүлээгүй.")
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


async def my_jobs(update, context):
    jobs = get_jobs_by_employer(update.effective_user.id)
    if not jobs:
        await update.message.reply_text("Одоогоор зар оруулаагүй байна.", reply_markup=EMPLOYER_MENU)
        return
    for job in jobs:
        status = {"pending": "⏳ Хүлээгдэж байна", "approved": "✅ Батлагдсан", "rejected": "❌ Татгалзсан"}.get(job["status"], job["status"])
        await update.message.reply_text(
            job_text(job) + f"\n\nТөлөв: <b>{status}</b>",
            parse_mode=ParseMode.HTML,
        )


async def premium_info(update, context):
    await update.message.reply_text(
        "👑 <b>ServiGo VIP зар</b>\n\n"
        "⭐ Premium ажлын зар\n⏰ 24 цаг — <b>5,000₮</b>\n\n"
        "👑 VIP ажлын зар\n📅 30 хоног — <b>35,000₮</b>\n\n"
        "👤 Ажил хайгчийн Premium анкет\n⏰ 24 цаг — <b>3,000₮</b>\n\n"
        f"Төлбөр болон идэвхжүүлэлт: @{PREMIUM_CONTACT}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("💬 VIP захиалах", url=f"https://t.me/{PREMIUM_CONTACT}")]]
        ),
    )


async def admin_stats(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    d = stats()
    await update.message.reply_text(
        "📊 ServiGo статистик\n\n"
        + "\n".join(
            [
                f"👥 Хэрэглэгч: {d['users']}",
                f"🏢 Байгууллага: {d['businesses']}",
                f"✅ Батлагдсан байгууллага: {d['approved_businesses']}",
                f"💼 Ажлын зар: {d['jobs']}",
                f"⏰ Цагийн ажил: {d['part_time_jobs']}",
                f"🤝 Match: {d['matches']}",
            ]
        )
    )


async def refresh_promoted_posts(application):
    """VIP/Premium картын үлдэх хугацааг 5 минут тутам шинэчилнэ."""
    await asyncio.sleep(10)
    while True:
        for job in get_promoted_jobs():
            try:
                if not job["channel_message_id"]:
                    continue
                bot_username = (await application.bot.get_me()).username
                card_path = create_job_card(job)
                with card_path.open("rb") as image_file:
                    await application.bot.edit_message_media(
                        chat_id=CHANNEL_ID,
                        message_id=job["channel_message_id"],
                        media=InputMediaPhoto(
                            media=image_file,
                            caption=f"🏢 <b>{escape(job['company'])}</b> • {escape(job['title'])}\n🆔 Зар #{job['id']}",
                            parse_mode=ParseMode.HTML,
                        ),
                        reply_markup=channel_keyboard(job, bot_username),
                    )
            except Exception:
                logger.debug("Зарын зураг/цаг шинэчилж чадсангүй: %s", job["id"], exc_info=True)

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
        await asyncio.sleep(300)


async def post_init(application):
    application.create_task(refresh_promoted_posts(application))


def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("stats", admin_stats))

    app.add_handler(
        ConversationHandler(
            entry_points=[MessageHandler(filters.Regex(r"^👤 Миний анкет$"), profile_start)],
            states={
                P_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, p_name)],
                P_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, p_phone)],
                P_PROFESSION: [MessageHandler(filters.TEXT & ~filters.COMMAND, p_prof)],
                P_EXPERIENCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, p_exp)],
                P_SALARY: [MessageHandler(filters.TEXT & ~filters.COMMAND, p_salary)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )
    app.add_handler(
        ConversationHandler(
            entry_points=[MessageHandler(filters.Regex(r"^🏢 Байгууллага бүртгэх$"), business_start)],
            states={
                B_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, b_name)],
                B_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, b_cat)],
                B_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, b_phone)],
                B_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, b_location)],
                B_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, b_desc)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )
    app.add_handler(
        ConversationHandler(
            entry_points=[
                MessageHandler(filters.Regex(r"^➕ Байнгын ажлын зар$"), job_start_full),
                MessageHandler(filters.Regex(r"^➕ Цагийн ажлын зар$"), job_start_part),
            ],
            states={
                J_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, j_title)],
                J_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, j_cat)],
                J_SALARY: [MessageHandler(filters.TEXT & ~filters.COMMAND, j_salary)],
                J_SCHEDULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, j_schedule)],
                J_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, j_location)],
                J_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, j_desc)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )

    app.add_handler(MessageHandler(filters.Regex(r"^👤 Ажил хайгч$"), open_job_seeker_menu))
    app.add_handler(MessageHandler(filters.Regex(r"^🏢 Ажил олгогч$"), open_employer_menu))
    app.add_handler(MessageHandler(filters.Regex(r"^🔄 Горим солих$"), change_role))
    app.add_handler(MessageHandler(filters.Regex(r"^💼 Байнгын ажил$"), browse_full))
    app.add_handler(MessageHandler(filters.Regex(r"^⏰ Цагийн ажил$"), browse_part))
    app.add_handler(MessageHandler(filters.Regex(r"^📋 Миний зарууд$"), my_jobs))
    app.add_handler(MessageHandler(filters.Regex(r"^⭐ VIP зар$"), premium_info))
    app.add_handler(MessageHandler(filters.Regex(r"^🔙 Буцах$"), back_menu))

    categories_pattern = "^(" + "|".join(map(re.escape, JOB_CATEGORIES)) + ")$"
    app.add_handler(MessageHandler(filters.Regex(categories_pattern), category_router))

    app.add_handler(CallbackQueryHandler(match_callback, pattern=r"^match:\d+$"))
    app.add_handler(CallbackQueryHandler(interest_callback, pattern=r"^interest:\d+$"))
    app.add_handler(CallbackQueryHandler(business_admin, pattern=r"^biz_(yes|no):\d+$"))
    app.add_handler(CallbackQueryHandler(job_admin, pattern=r"^job_(free|premium|vip|no):\d+$"))
    app.add_handler(CallbackQueryHandler(user_admin, pattern=r"^user_(free|premium|no):\d+$"))
    app.add_handler(CallbackQueryHandler(employer_decision, pattern=r"^emp_(yes|no):\d+$"))

    print("ServiGo bot ажиллаж эхэллээ...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
