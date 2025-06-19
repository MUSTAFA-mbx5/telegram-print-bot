# -*- coding: utf-8 -*-

# ----------------------------------------------------------------------------------
# --- القسم الأول: الاستيرادات والإعدادات الأولية ---
# ----------------------------------------------------------------------------------
import os
import asyncio
import math
import fitz  # PyMuPDF
import docx
import pptx
import logging
import sys
import traceback
import glob
import nest_asyncio
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# --- حل شامل لمشاكل استيراد الأخطاء ---
# هذا الجزء مهم للتوافق مع إصدارات مختلفة من Telethon
error_classes = [
    'UserIsBlocked',
    'PeerIdInvalid',
    'MessageDeleteForbiddenError',
    'FileReferenceExpiredError'
]
for error_name in error_classes:
    try:
        exec(f"from telethon.errors import {error_name}")
    except ImportError:
        try:
            exec(f"from telethon.errors.rpcerrorlist import {error_name}")
        except ImportError:
            globals()[error_name] = type(error_name, (Exception,), {})
            print(f"WARNING: '{error_name}' not found. Created a dummy class.")

from telethon.tl.types import PeerUser, MessageMediaPhoto, MessageMediaDocument, User
from telethon.tl import types as telethon_types
from datetime import datetime, timedelta

# تطبيق nest_asyncio للسماح بتشغيل asyncio داخل بيئات مثل Jupyter أو في حالة وجود loop يعمل بالفعل
try:
    nest_asyncio.apply()
except RuntimeError:
    # هذا يعني أن nest_asyncio قد تم تطبيقه بالفعل أو أننا لسنا في بيئة تحتاجه
    pass

# إعداد التسجيل (Logging Setup)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        # لا نستخدم ملف لوج لأن Render يتعامل مع السجلات بشكل مختلف (stdout)
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('MyTelegramBot')

# ----------------------------------------------------------------------------------
# --- القسم الثاني: متغيرات الإعدادات من بيئة التشغيل ---
# ----------------------------------------------------------------------------------
# !!! هام: يتم جلب هذه المتغيرات من بيئة التشغيل (أكثر أماناً)
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
SESSION_STRING = os.environ.get("SESSION_STRING")
NOTIFICATION_CHAT_ID_STR = os.environ.get("NOTIFICATION_CHAT_ID", "me")

# التحقق من وجود المتغيرات الأساسية
if not all([API_ID, API_HASH, SESSION_STRING]):
    logger.critical("CRITICAL ERROR: API_ID, API_HASH, or SESSION_STRING is not set in environment variables.")
    sys.exit(1)

# تحويل API_ID إلى رقم
try:
    API_ID = int(API_ID)
except (ValueError, TypeError):
    logger.critical(f"CRITICAL ERROR: API_ID '{API_ID}' is not a valid number.")
    sys.exit(1)

# تحويل ID مجموعة الإشعارات إلى رقم
try:
    if NOTIFICATION_CHAT_ID_STR.lower() != 'me':
        NOTIFICATION_CHAT = int(NOTIFICATION_CHAT_ID_STR)
    else:
        NOTIFICATION_CHAT = 'me'
except ValueError:
    logger.warning(f"Invalid NOTIFICATION_CHAT_ID: '{NOTIFICATION_CHAT_ID_STR}'. Defaulting to 'me'.")
    NOTIFICATION_CHAT = 'me'

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

# --- بقية الكود الخاص بك (المتغيرات العامة، الدوال، ومعالجات الأحداث) ---
# --- تم نسخها كما هي مع بعض التعديلات الطفيفة للتشغيل على الخادم ---

is_sleeping = False
user_prices = {}
user_status_messages = {}
user_last_interaction_time = {}
ignored_users = set()
bot_id = None
global_daily_total_collected = 0
bot_start_time = None
daily_report_task = None
user_confirmation_state = {}
users_interacted_while_sleeping = {}

custom_auto_reply_mode = False
custom_auto_reply_message = "صاحب الحساب غير متوفر حاليًا. سيتم الرد عليك لاحقًا."
stats_confirmed_orders = 0
stats_rejected_orders = 0
stats_total_confirmed_files = 0
stats_interacted_users = set()

PRICE_PER_PAGE_LT50 = 50
PRICE_PER_PAGE_GTE50 = 40
COVER_BINDING_COST = 500

DEFAULT_WELCOME_MESSAGE = "👋 أهلاً بك {user_name} في بوت حساب أسعار الطباعة! أرسل لي ملف PDF, DOCX, أو PPTX وسأقوم بحساب السعر لك. يمكنك إرسال أي رسالة نصية أخرى بعد إرسال الملفات للحصول على المجموع الكلي."
WELCOME_MESSAGE_TEXT = DEFAULT_WELCOME_MESSAGE
WELCOME_COOLDOWN = timedelta(hours=12)
DEFAULT_OWNER_ALERT_MESSAGE = "🔔 تنبيه للمالك: تم استلام ملف/رسالة جديدة من مستخدم."
OWNER_ALERT_MESSAGE_TEXT = DEFAULT_OWNER_ALERT_MESSAGE
APOLOGY_MESSAGE_AFTER_PRICE_WHEN_SLEEPING = "\n\n📝 تم حساب السعر. صاحب المكتبة غير متوفر حاليًا، يرجى الانتظار حتى عودته لمتابعة طلبك."
WAITING_MESSAGE_NORMAL = "شكرًا لرسالتك. سيتم الرد عليك بأقرب وقت ممكن."
CALCULATING_MESSAGE = "⏳ جار احتساب... يرجى الانتظار."
FILE_TYPE_ERROR_MESSAGE = "⚠️ يرجى إرسال ملف PDF، DOCX، أو PPTX فقط. الصور والأنواع الأخرى من الملفات غير مدعومة حالياً لحساب السعر."
COUNT_PAGES_ERROR_MESSAGE = "❌ لا يمكن معالجة هذا الملف: لم يتمكن البوت من قراءة عدد الصفحات أو الملف تالف."
PROCESSING_ERROR_MESSAGE = "❌ حدث خطأ أثناء معالجة الملف. يرجى المحاولة مرة أخرى."
MUTE_CONFIRMATION_FOR_OWNER = "✅ تم تجاهل المستخدم `{user_id}` بنجاح. لن يتم الرد على رسائله."
UNMUTE_CONFIRMATION_FOR_OWNER = "✅ تم إلغاء تجاهل المستخدم `{user_id}` بنجاح. سيعود البوت للرد على رسائله."
USER_ALREADY_IGNORED_OWNER = "⚠️ المستخدم `{user_id}` موجود بالفعل في قائمة التجاهل."
USER_NOT_IGNORED_OWNER = "⚠️ المستخدم `{user_id}` ليس في قائمة التجاهل أصلاً."
TARGET_USER_NOT_FOUND_OWNER = "❌ لم يتم تحديد المستخدم. استخدم الأمر بالرد على رسالة المستخدم، أو بتضمين ID المستخدم، أو استخدم الأمر `.سماح <ID>` / `.الغاء <ID>` في المحفوظات."
DAILY_REPORT_MESSAGE_TEMPLATE = "📊 التقرير اليومي ({date}):\nالمجموع الكلي للمبالغ التي تم عرضها للمستخدمين (وتم تأكيدها) خلال الـ 24 ساعة الماضية: {total} دينار."
PRICE_UPDATE_SUCCESS_TEMPLATE = "✅ تم تحديث `{price_name}` إلى {new_price} دينار."
PRICE_UPDATE_ERROR = "❌ خطأ في تعديل السعر. يرجى التأكد من الأمر والقيمة العددية (مثال: `.ت1 60`)."
PRICE_UPDATE_INVALID_VALUE = "❌ القيمة المدخلة غير صحيحة. يرجى إدخال قيمة عددية صحيحة (مثال: `.ت1 60`)."
CUMULATIVE_TOTAL_MESSAGE_TEMPLATE = ("📊 המجموع الكلي للملفات المرسلة حتى الآن:\n"
                                   "بدون جلاد: {total_base} دينار\n"
                                   "مع جلاد: {total_cover} دينار")
OWNER_REQUESTED_PRICE_INFO_TEMPLATE = ("📄 معلومات التسعير للمستخدم (بناءً على طلبك):\n"
                                     "📖 إجمالي عدد الصفحات (للملفات المسعرة): {total_pages}\n"
                                     "💰 السعر الأساسي (بدون جلاد): {total_base} دينار\n"
                                     "🏷️ السعر مع جلاد: {total_cover} دينار")
CONFIRMATION_PROMPT_MESSAGE = "\n\n🤔 هل أنت موافق على سحب الملفات المرسلة بهذا السعر؟\nأجب بالكلمات المناسبة مثل `نعم`/`موافق` أو `لا`/`ارفض`."
ORDER_CONFIRMED_AWAKE_MESSAGE = "✅ تم تأكيد طلبك وجارٍ معالجته. سيتم التواصل معك قريبًا."
ORDER_CONFIRMED_SLEEPING_MESSAGE = "✅ تم تسجيل طلبك. سيتم التواصل معك عند عودة صاحب المكتبة لمتابعة التفاصيل."
CONFIRMATION_REJECTED_ASK_REASON_MESSAGE = "تم إلغاء الطلب. إذا أمكن، يرجى ذكر سبب الرفض (اختياري)."
PROGRESS_MESSAGE_SAVE_MEDIA = "دقيقة نت ضعيف خل تفتح ❤️"
FILE_PROCESSED_ADD_TO_ORDER_PROMPT_TOTAL = (
    "\n\n✅ تم إضافة هذا الملف إلى طلبك. أرسل أي رسالة نصية لعرض المجموع الكلي وتأكيد الطلب."
)
ORDER_COMPLETION_MESSAGE_USER = (
    "عزيزي المستخدم، تم إكمال طلبك بنجاح.\n"
    "يرجى استلامه أو طلب توصيل مع ذكر المعلومات التالية:\n"
    "- الاسم:\n"
    "- رقم الهاتف:\n"
    "- أقرب نقطة دالة:\n\n"
    "شكرًا لاختيارنا."
)
UNMUTE_ALL_CONFIRMATION_OWNER = "✅ تم إلغاء تجاهل جميع المستخدمين بنجاح."
UNMUTE_ALL_NO_IGNORED_OWNER = "ℹ️ لا يوجد مستخدمون في قائمة التجاهل حاليًا."

KEYWORDS_CONFIRM = ["نعم", "اي", "أجل", "موافق", "موافقة", "yes", "ok", "confirm", "yep", "yeah", "تمام", "اوكي", "وك", "اوك", "تم"]
KEYWORDS_CANCEL = ["لا", "كلا", "ارفض", "no", "cancel", "nope", "الغاء"]

MENU_HEADER = "📋 قائمة أوامر بوت الطباعة:\n"
MAIN_MENU_OPTIONS = {
    "1": "أوامر حالة البوت والمعلومات",
    "2": "أوامر تعديل الأسعار",
    "3": "أوامر إدارة المستخدمين",
    "4": "أوامر متقدمة وإحصائيات",
    "5": "أمر حفظ الوسائط (.حلو)",
    "6": "ملاحظات إضافية"
}
# ... (لصق كل الدوال من get_main_menu_text() إلى نهاية الملف)
# ... (سأختصر هنا، ولكن يجب عليك لصق كل شيء)

def get_main_menu_text():
    text = MENU_HEADER
    for key, value in MAIN_MENU_OPTIONS.items():
        text += f"  `.م{key}` - {value}\n"
    text += "\nأرسل الأمر مع الرقم لعرض التفاصيل (مثال: `.م1`)"
    return text

# ... الصق كل الدوال الأخرى هنا ...
# ... (get_status_commands_text, get_prices_commands_text, etc.)

# ... وبعدها كل معالجات الأحداث (@client.on)
# ...

async def main():
    global bot_id, bot_start_time, daily_report_task, client

    logger.info("⏳ Bot starting...")
    try:
        # الكود لن يطلب منك إدخال أي شيء، لأنه سيستخدم SESSION_STRING
        await client.start()
        logger.info("Client connected and authorized.")

        me = await client.get_me()
        if not me:
            logger.critical("Could not get bot's identity (me). Exiting.")
            return

        bot_id = me.id
        bot_start_time = datetime.now()
        bot_name_display = f"{me.first_name or ''} {me.last_name or ''}".strip() or me.username or f"ID: {bot_id}"
        logger.info(f"✅ Bot '{bot_name_display}' started! ID: {bot_id}")
        await send_notification(f"🚀 البوت ({bot_name_display}) يعمل الآن!")

        os.makedirs("temp/", exist_ok=True)
        
        # لا نستخدم create_task هنا بهذه الطريقة لتبسيط الأمور على Render
        # سنجعل الدالة تعمل في الخلفية
        # daily_report_task = asyncio.create_task(report_daily_total())

        logger.info("Bot is now listening for incoming events...")
        
        # تشغيل المهمتين معاً
        await asyncio.gather(
            client.run_until_disconnected(),
            report_daily_total()
        )

    except Exception as e_fatal:
        logger.critical(f"💥 CRITICAL UNHANDLED ERROR in main: {e_fatal}", exc_info=True)
    finally:
        logger.info("--- Initiating shutdown sequence ---")
        if client.is_connected():
            await client.disconnect()
        temp_dir_cleanup = "temp/"
        if os.path.exists(temp_dir_cleanup):
            for item_name in glob.glob(os.path.join(temp_dir_cleanup, "*")):
                try:
                    os.remove(item_name)
                except:
                    pass
        logger.info("✅ Bot shutdown process finished.")


# ----------------------------------------------------------------------------------
# --- القسم السابع: نقطة الدخول للتشغيل ---
# ----------------------------------------------------------------------------------
if __name__ == '__main__':
    logger.info("Starting bot execution from __main__...")
    try:
        # هذه هي الطريقة الصحيحة لتشغيل asyncio loop
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.critical(f"A critical error occurred at the top level: {e}", exc_info=True)
