import logging, os
from html import escape
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from database import *

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip()
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
if not BOT_TOKEN:
    raise RuntimeError('BOT_TOKEN олдсонгүй. .env файлаа шалгана уу.')

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

(PROFILE_NAME, PROFILE_PHONE, PROFILE_PROFESSION, PROFILE_EXPERIENCE, PROFILE_SALARY,
 JOB_COMPANY, JOB_TITLE, JOB_SALARY, JOB_LOCATION, JOB_DESCRIPTION) = range(10)

MAIN_MENU = ReplyKeyboardMarkup([
    ['🔍 Ажил хайх'],
    ['👤 Миний анкет', '📢 Ажлын зар оруулах'],
    ['ℹ️ Тусламж']
], resize_keyboard=True)

def job_text(job) -> str:    return (        f"💼 <b>{escape(job['title']).upper()}</b>\n\n"        f"🏢 Компани: {escape(job['company'])}\n"        f"💰 Цалин: {escape(job['salary'])}\n"        f"📍 Байршил: {escape(job['location'])}\n"        f"📋 Ажлын төрөл: Бүтэн цаг\n\n"        f"📌 <b>Шаардлага</b>\n"        f"{escape(job['description'])}\n\n"        f"━━━━━━━━━━━━━━\n"        f"🆔 Зарын дугаар: #{job['id']}\n\n"        f"👇 Доорх товчоор анкетаа илгээнэ үү."    )(job) -> str:    return (        f"💼 <b>{escape(job['title']).upper()}</b>\n\n"        f"🏢 Компани: {escape(job['company'])}\n"        f"💰 Цалин: {escape(job['salary'])}\n"        f"📍 Байршил: {escape(job['location'])}\n"        f"💼 Ажлын төрөл: Бүтэн цаг\n\n"        f"━━━━━━━━━━━━━━━━━━\n\n"        f"📋 <b>Шаардлага</b>\n"        f"{escape(job['description'])}\n\n"        f"━━━━━━━━━━━━━━━━━━\n\n"        f"🆔 Зарын дугаар: #{job['id']}\n\n"        f"👇 Доорх товчоор анкетаа илгээнэ үү."    )(job):
    return (f"💼 <b>{escape(job['title'])}</b>\n🏢 {escape(job['company'])}\n"
            f"💰 {escape(job['salary'])}\n📍 {escape(job['location'])}\n\n"
            f"{escape(job['description'])}\n\nЗарын дугаар: #{job['id']}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Сайн байна уу! 👋\n\nАжил хайгч болон ажил олгогчийг холбох ботод тавтай морил.', reply_markup=MAIN_MENU)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text('Үйлдлийг цуцаллаа.', reply_markup=MAIN_MENU)
    return ConversationHandler.END

async def profile_start(update, context):
    await update.message.reply_text('Овог нэрээ оруулна уу:'); return PROFILE_NAME
async def profile_name(update, context):
    context.user_data['full_name']=update.message.text.strip(); await update.message.reply_text('Утасны дугаараа оруулна уу:'); return PROFILE_PHONE
async def profile_phone(update, context):
					    context.user_data['phone']=update.message.text.strip(); await update.message.reply_text('Мэргэжил эсвэл хийж чадах ажлаа бичнэ үү:'); return PROFILE_PROFESSION
async def profile_profession(update, context):
    context.user_data['profession']=update.message.text.strip(); await update.message.reply_text('Ажлын туршлагаа бичнэ үү:'); return PROFILE_EXPERIENCE
async def profile_experience(update, context):
    context.user_data['experience']=update.message.text.strip(); await update.message.reply_text('Хүсэж буй цалингаа оруулна уу:'); return PROFILE_SALARY
async def profile_salary(update, context):
    u=update.effective_user
    context.user_data.update({'desired_salary':update.message.text.strip(),'telegram_id':u.id,'username':u.username})
    save_user(context.user_data); context.user_data.clear()
    await update.message.reply_text('✅ Таны анкет хадгалагдлаа.', reply_markup=MAIN_MENU)
    return ConversationHandler.END

async def job_start(update, context):
    u=update.effective_user; context.user_data.update({'employer_id':u.id,'employer_username':u.username})
    await update.message.reply_text('Компанийн нэрээ оруулна уу:'); return JOB_COMPANY
async def job_company(update, context):
    context.user_data['company']=update.message.text.strip(); await update.message.reply_text('Ажлын байрны нэр:'); return JOB_TITLE
async def job_title(update, context):
    context.user_data['title']=update.message.text.strip(); await update.message.reply_text('Цалин:'); return JOB_SALARY
async def job_salary(update, context):
    context.user_data['salary']=update.message.text.strip(); await update.message.reply_text('Ажлын байршил:'); return JOB_LOCATION
async def job_location(update, context):
    context.user_data['location']=update.message.text.strip(); await update.message.reply_text('Ажлын үүрэг болон шаардлагыг дэлгэрэнгүй бичнэ үү:'); return JOB_DESCRIPTION
async def job_description(update, context):
    context.user_data['description']=update.message.text.strip(); job_id=add_job(context.user_data); job=get_job(job_id); context.user_data.clear()
    await update.message.reply_text(f'✅ Зар хүлээн авлаа.\nЗарын дугаар: #{job_id}\nАдмин баталсны дараа нийтлэгдэнэ.', reply_markup=MAIN_MENU)
    if ADMIN_ID and job:
        kb=InlineKeyboardMarkup([[InlineKeyboardButton('✅ Батлах',callback_data=f'approve:{job_id}'),InlineKeyboardButton('❌ Татгалзах',callback_data=f'reject:{job_id}')]])
        try: await context.bot.send_message(ADMIN_ID,'🆕 <b>Шинэ ажлын зар</b>\n\n'+job_text(job),parse_mode=ParseMode.HTML,reply_markup=kb)
        except Exception: logger.exception('Админд мэдэгдэл хүрсэнгүй')
    return ConversationHandler.END

async def browse_jobs(update, context):
    jobs=get_approved_jobs()
    if not jobs: await update.message.reply_text('Одоогоор батлагдсан ажлын зар алга.'); return
    for job in jobs:
        kb=InlineKeyboardMarkup([[InlineKeyboardButton('📩 Хүсэлт илгээх',callback_data=f"apply:{job['id']}")]])
        await update.message.reply_text(job_text(job),parse_mode=ParseMode.HTML,reply_markup=kb)

async def apply_callback(update, context):
    q=update.callback_query; job_id=int(q.data.split(':')[1]); applicant=get_user(q.from_user.id)
    if not applicant: await q.answer("Эхлээд 'Миний анкет' хэсэгт анкетаа бөглөнө үү.",show_alert=True); return
    job=get_job(job_id)
    if not job or job['status']!='approved': await q.answer('Энэ зар идэвхгүй байна.',show_alert=True); return
    if not apply_to_job(job_id,q.from_user.id): await q.answer('Та өмнө нь хүсэлт илгээсэн байна.',show_alert=True); return
    await q.answer('Хүсэлт амжилттай илгээгдлээ!',show_alert=True)
    text=(f"📩 <b>Шинэ ажил горилогч</b>\n\n💼 {escape(job['title'])}\n👤 {escape(applicant['full_name'])}\n"
          f"📞 {escape(applicant['phone'])}\n🧰 {escape(applicant['profession'])}\n📚 {escape(applicant['experience'])}\n💰 {escape(applicant['desired_salary'])}")
    try: await context.bot.send_message(job['employer_id'],text,parse_mode=ParseMode.HTML)
    except Exception: logger.exception('Ажил олгогчид мэдэгдэл хүрсэнгүй')

async def admin_action(update, context):
    q=update.callback_query
    if q.from_user.id!=ADMIN_ID: await q.answer('Танд админы эрх байхгүй.',show_alert=True); return
    action,raw_id=q.data.split(':'); job_id=int(raw_id); job=get_job(job_id)
    if not job: await q.answer('Зар олдсонгүй.',show_alert=True); return
    changed=approve_job(job_id) if action=='approve' else reject_job(job_id)
    if not changed: await q.answer('Энэ зар өмнө нь шийдвэрлэгдсэн байна.',show_alert=True); return
    await q.edit_message_reply_markup(reply_markup=None)
    await q.message.reply_text(('✅ Батлагдсан' if action=='approve' else '❌ Татгалзсан')+f': зар #{job_id}')
    await q.answer()
    try: await context.bot.send_message(job['employer_id'],('✅ Батлагдлаа.' if action=='approve' else '❌ Татгалзлаа.')+f' Зар #{job_id}')
    except Exception: logger.exception('Шийдвэр хүрсэнгүй')

async def pending(update, context):
    if update.effective_user.id!=ADMIN_ID: return
    jobs=get_pending_jobs()
    if not jobs: await update.message.reply_text('Хүлээгдэж буй зар алга.'); return
    for job in jobs:
        kb=InlineKeyboardMarkup([[InlineKeyboardButton('✅ Батлах',callback_data=f"approve:{job['id']}"),InlineKeyboardButton('❌ Татгалзах',callback_data=f"reject:{job['id']}")]])
        await update.message.reply_text(job_text(job),parse_mode=ParseMode.HTML,reply_markup=kb)

async def stats_cmd(update, context):
    if update.effective_user.id!=ADMIN_ID: return
    s=stats(); await update.message.reply_text(f"📊 Статистик\n\n👥 Анкет: {s['users']}\n📢 Нийт зар: {s['jobs']}\n✅ Батлагдсан: {s['approved']}\n📩 Хүсэлт: {s['applications']}")

async def help_msg(update, context):
    await update.message.reply_text("👤 Ажил хайгч: анкетаа бөглөж, зар сонгоод хүсэлт илгээнэ.\n\n🏢 Ажил олгогч: зар оруулж, админ батлуулна.\n\n/cancel — үйлдэл цуцлах")

def main():
    init_db(); app=Application.builder().token(BOT_TOKEN).build()
    profile=ConversationHandler(entry_points=[MessageHandler(filters.Regex('^👤 Миний анкет$'),profile_start)],states={PROFILE_NAME:[MessageHandler(filters.TEXT&~filters.COMMAND,profile_name)],PROFILE_PHONE:[MessageHandler(filters.TEXT&~filters.COMMAND,profile_phone)],PROFILE_PROFESSION:[MessageHandler(filters.TEXT&~filters.COMMAND,profile_profession)],PROFILE_EXPERIENCE:[MessageHandler(filters.TEXT&~filters.COMMAND,profile_experience)],PROFILE_SALARY:[MessageHandler(filters.TEXT&~filters.COMMAND,profile_salary)]},fallbacks=[CommandHandler('cancel',cancel)])
    job=ConversationHandler(entry_points=[MessageHandler(filters.Regex('^📢 Ажлын зар оруулах$'),job_start)],states={JOB_COMPANY:[MessageHandler(filters.TEXT&~filters.COMMAND,job_company)],JOB_TITLE:[MessageHandler(filters.TEXT&~filters.COMMAND,job_title)],JOB_SALARY:[MessageHandler(filters.TEXT&~filters.COMMAND,job_salary)],JOB_LOCATION:[MessageHandler(filters.TEXT&~filters.COMMAND,job_location)],JOB_DESCRIPTION:[MessageHandler(filters.TEXT&~filters.COMMAND,job_description)]},fallbacks=[CommandHandler('cancel',cancel)])
    app.add_handler(CommandHandler('start',start)); app.add_handler(CommandHandler('cancel',cancel)); app.add_handler(CommandHandler('pending',pending)); app.add_handler(CommandHandler('stats',stats_cmd)); app.add_handler(profile); app.add_handler(job); app.add_handler(MessageHandler(filters.Regex('^🔍 Ажил хайх$'),browse_jobs)); app.add_handler(MessageHandler(filters.Regex('^ℹ️ Тусламж$'),help_msg)); app.add_handler(CallbackQueryHandler(apply_callback,pattern=r'^apply:\d+$')); app.add_handler(CallbackQueryHandler(admin_action,pattern=r'^(approve|reject):\d+$'))
    print('Бот ажиллаж эхэллээ...'); app.run_polling(drop_pending_updates=True)

if __name__=='__main__': main()
