from fastapi import APIRouter, Request, Form
from aiogram import Bot, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router, Dispatcher
from aiogram.filters import Command
import os
from config import SETTINGS_BOT_TOKEN, API_URL, SERVER_URL, DEEPSEEK_API_KEY, TRIAL_DAYS, TRIAL_PROJECTS, PAID_PROJECTS, PAYMENT_AMOUNT, PAYMENT_CARD_NUMBER, MAIN_TELEGRAM_ID, DISCOUNT_PAYMENT_AMOUNT
from database import create_project, get_project_by_id, create_user, get_projects_by_user, update_project_name, update_project_business_info, append_project_business_info, delete_project, get_project_by_token, check_project_name_exists, get_user_by_id, get_users_with_expired_trial, delete_all_projects_for_user, set_user_paid, get_user_projects, log_message_stat, add_feedback, update_project_token, get_users_with_expired_paid_month, set_trial_expired_notified, log_payment
from analytics import log_project_created, log_form_created
from utils import set_webhook, delete_webhook
from aiogram.fsm.context import FSMContext
from settings_states import SettingsStates
from settings_business import process_business_file_with_deepseek, clean_markdown, clean_business_text, get_text_from_message
from settings_utils import handle_command_in_state, log_fsm_state
from settings_feedback import handle_feedback_command, handle_feedback_text, handle_feedback_rating_callback, handle_feedback_change_rating
from settings_payment import handle_pay_command, handle_pay_callback, handle_payment_check, handle_payment_check_document, handle_payment_check_document_any, handle_payment_check_photo_any
from settings_middleware import trial_middleware, clear_asking_bot_cache
from database import log_message_stat
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import traceback
import time
import datetime

router = APIRouter()

SETTINGS_WEBHOOK_PATH = "/webhook/settings"
SETTINGS_WEBHOOK_URL = f"{SERVER_URL}{SETTINGS_WEBHOOK_PATH}"

settings_bot = Bot(token=SETTINGS_BOT_TOKEN)
settings_storage = MemoryStorage()
settings_router = Router()
settings_dp = Dispatcher(storage=settings_storage)
settings_dp.include_router(settings_router)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

async def check_expired_trials():
    users = await get_users_with_expired_trial()
    logging.info(f"[TRIAL] Найдено пользователей с истекшим trial: {len(users)}")
    for user in users:
        telegram_id = user.get('telegram_id')
        logging.info(f"[TRIAL] Проверяю пользователя: {user}")
        try:
            projects = await get_user_projects(telegram_id)
            logging.info(f"[TRIAL] У пользователя {telegram_id} найдено проектов: {len(projects)}")
            for project in projects:
                try:
                    await delete_webhook(project['token'])
                    logging.info(f"[TRIAL] Вебхук удалён для проекта {project['id']} (token={project['token']})")
                except Exception as e:
                    logging.error(f"[TRIAL] Ошибка при удалении вебхука: {e}")
            try:
                pay_kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="Оплатить", callback_data="pay")],
                        [InlineKeyboardButton(text="Удалить проекты", callback_data="delete_trial_projects")]
                    ]
                )
                await settings_bot.send_message(
                    telegram_id,
                    f"Пробный период завершён!\n\nДля продолжения работы оплатите {DISCOUNT_PAYMENT_AMOUNT} рублей за первый месяц или удалите проекты.",
                    reply_markup=pay_kb
                )
                logging.info(f"[TRIAL] Пользователь {telegram_id} — trial истёк, уведомление отправлено")
                await set_trial_expired_notified(telegram_id, True)
            except Exception as e:
                logging.error(f"[TRIAL] Ошибка при отправке уведомления: {e}")
        except Exception as e:
            logging.error(f"[TRIAL] Ошибка при обработке пользователя {telegram_id}: {e}")

async def check_expired_paid_month():
    users = await get_users_with_expired_paid_month()
    logging.info(f"[PAID_MONTH] Найдено пользователей с истекшим первым оплачиваемым месяцем: {len(users)}")
    for user in users:
        telegram_id = user.get('telegram_id')
        logging.info(f"[PAID_MONTH] Проверяю пользователя: {user}")
        try:
            pay_kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Оплатить", callback_data="pay")]
                ]
            )
            await settings_bot.send_message(
                telegram_id,
                "Первый оплаченный месяц завершён!\n\nДля продолжения работы оплатите полную стоимость подписки.",
                reply_markup=pay_kb
            )
            logging.info(f"[PAID_MONTH] Пользователь {telegram_id} — первый оплаченный месяц истёк, уведомление отправлено")
        except Exception as e:
            logging.error(f"[PAID_MONTH] Ошибка при отправке уведомления: {e}")

scheduler.add_job(check_expired_trials, 'interval', minutes=1)
scheduler.add_job(check_expired_paid_month, 'interval', minutes=1)
scheduler.start()

# --- Middleware для перехвата команд, если trial истёк ---
async def trial_middleware(message: types.Message, state: FSMContext, handler):
    user = await get_user_by_id(str(message.from_user.id))
    logger.info(f"[TRIAL_MW] user: {user}")
    if user and not user['paid']:
        start_date = user['start_date']
        logger.info(f"[TRIAL_MW] start_date raw: {start_date} (type: {type(start_date)})")
        if isinstance(start_date, str):
            from dateutil.parser import parse
            start_date = parse(start_date)
            logger.info(f"[TRIAL_MW] start_date parsed: {start_date} (type: {type(start_date)})")
        # Приводим к naive datetime (без tzinfo)
        if hasattr(start_date, 'tzinfo') and start_date.tzinfo is not None:
            start_date = start_date.replace(tzinfo=None)
            logger.info(f"[TRIAL_MW] start_date made naive: {start_date} (type: {type(start_date)})")
        now = datetime.datetime.utcnow()
        logger.info(f"[TRIAL_MW] now: {now} (type: {type(now)})")
        diff = now - start_date
        diff_days = diff.total_seconds() / 86400
        logger.info(f"[TRIAL_MW] now - start_date: {diff}, days: {diff.days}, diff_days: {diff_days}")
        logger.info(f"[TRIAL_MW] TRIAL_DAYS: {TRIAL_DAYS}, paid: {user['paid']}")
        if diff_days >= TRIAL_DAYS:
            logger.info(f"[TRIAL_MW] TRIAL EXPIRED: diff_days >= TRIAL_DAYS")
            # Показываем меню оплаты/удаления
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Оплатить", callback_data="pay_trial")],
                    [InlineKeyboardButton(text="Удалить проекты", callback_data="delete_trial_projects")]
                ]
            )
            await message.answer(
                f"Пробный период завершён!\n\nДля продолжения работы оплатите {DISCOUNT_PAYMENT_AMOUNT} рублей за первый месяц или удалите проекты.\n\nВыберите действие:",
                reply_markup=kb
            )
            return  # Не передаём управление дальше
    await handler(message, state)

# --- Обработка команд с middleware ---
@settings_router.message(Command("start"))
async def start_with_trial_middleware(message: types.Message, state: FSMContext):
    await trial_middleware(message, state, _start_inner)

def _get_trial_and_paid_limits(user):
    trial_limit = TRIAL_PROJECTS
    paid_limit = PAID_PROJECTS
    is_paid = user and user.get("paid")
    return trial_limit, paid_limit, is_paid

async def _start_inner(message: types.Message, state: FSMContext):
    telegram_id = str(message.from_user.id)
    logging.info(f"[START] _start_inner: начало обработки для пользователя {telegram_id}")
    
    try:
        from database import get_projects_by_user, get_user_by_id, create_user
        
        # Проверяем, есть ли реферальный параметр в команде /start
        referrer_id = None
        if message.text and message.text.startswith('/start'):
            parts = message.text.split()
            if len(parts) > 1 and parts[1].startswith('ref'):
                referrer_id = parts[1][3:]  # Убираем 'ref' из начала
                logging.info(f"[REFERRAL] _start_inner: пользователь {telegram_id} пришел по реферальной ссылке от {referrer_id}")
        
        try:
            user = await get_user_by_id(telegram_id)
            logging.info(f"[START] _start_inner: получен пользователь: {user is not None}")
        except Exception as user_error:
            logging.error(f"[START] _start_inner: ❌ ОШИБКА при получении пользователя: {user_error}")
            raise user_error
        
        if not user:
            try:
                await create_user(str(message.from_user.id), referrer_id)
                user = await get_user_by_id(telegram_id)
                logging.info(f"[START] _start_inner: ✅ пользователь {telegram_id} создан")
                if referrer_id:
                    logging.info(f"[REFERRAL] _start_inner: пользователь {telegram_id} создан с реферером {referrer_id}")
            except Exception as create_error:
                logging.error(f"[START] _start_inner: ❌ ОШИБКА при создании пользователя: {create_error}")
                raise create_error
        elif referrer_id and not user.get('referrer_id'):
            # Если пользователь уже существует, но пришел по реферальной ссылке и у него нет реферера
            try:
                from database import update_user_referrer
                await update_user_referrer(telegram_id, referrer_id)
                logging.info(f"[REFERRAL] _start_inner: пользователю {telegram_id} добавлен реферер {referrer_id}")
            except Exception as referrer_error:
                logging.error(f"[START] _start_inner: ❌ ОШИБКА при добавлении реферера: {referrer_error}")
                raise referrer_error
        
        # Показываем приветствие и главное меню
        welcome_text = """
🤖 **Добро пожаловать в AI-бот для бизнеса!**

Здесь вы можете:
• 📋 Управлять проектами и создавать новые
• 💰 Оплачивать подписку и продлевать доступ
• 📊 Просматривать статистику и аналитику
• 💬 Оставлять отзывы о сервисе
• 🔗 Участвовать в реферальной программе
• ❓ Получать помощь и справку

**Доступные функции:**
• Создание умных ботов для вашего бизнеса
• Настройка ответов на основе ваших данных
• Сбор заявок от клиентов через формы
• Анализ статистики и эффективности

Выберите действие из меню ниже:
        """
        
        try:
            await message.bot.send_chat_action(message.chat.id, "typing")
            logging.info(f"[START] _start_inner: ✅ отправлен typing action для пользователя {telegram_id}")
        except Exception as typing_error:
            logging.error(f"[START] _start_inner: ❌ ОШИБКА при отправке typing action: {typing_error}")
        
        try:
            # Создаем inline-клавиатуру для главного меню
            start_menu_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="📋 Проекты", callback_data="start_projects"),
                        InlineKeyboardButton(text="➕ Создать проект", callback_data="start_new_project")
                    ],
                    [
                        InlineKeyboardButton(text="💰 Оплата", callback_data="start_payment"),
                        InlineKeyboardButton(text="📊 Статистика", callback_data="start_stats")
                    ],
                    [
                        InlineKeyboardButton(text="❓ Помощь", callback_data="start_help"),
                        InlineKeyboardButton(text="🔗 Реферальная программа", callback_data="start_referral")
                    ],
                    [
                        InlineKeyboardButton(text="💬 Оставить отзыв", callback_data="start_feedback"),
                    ]
                ]
            )
            
            # Отправляем сообщение с inline-кнопками
            await message.answer(welcome_text, reply_markup=start_menu_keyboard)
            logging.info(f"[START] _start_inner: ✅ отправлено приветственное сообщение с inline-меню для пользователя {telegram_id}")
            

        except Exception as message_error:
            logging.error(f"[START] _start_inner: ❌ ОШИБКА при отправке приветственного сообщения: {message_error}")
            raise message_error
        
        try:
            await state.clear()
            logging.info(f"[START] _start_inner: ✅ состояние очищено для пользователя {telegram_id}")
        except Exception as state_error:
            logging.error(f"[START] _start_inner: ❌ ОШИБКА при очистке состояния: {state_error}")
        
        logging.info(f"[START] _start_inner: ✅ обработка завершена успешно для пользователя {telegram_id}")
        
    except Exception as e:
        logging.error(f"[START] _start_inner: ❌ ОШИБКА при обработке: {e}")
        import traceback
        logging.error(f"[START] _start_inner: полный traceback: {traceback.format_exc()}")
        raise

@settings_router.message(Command("help"))
async def help_with_trial_middleware(message: types.Message, state: FSMContext):
    await trial_middleware(message, state, handle_help_command)

@settings_router.message(Command("new"))
async def new_project_command(message: types.Message, state: FSMContext):
    """Команда для создания нового проекта"""
    await trial_middleware(message, state, handle_new_project)

async def handle_new_project(message: types.Message, state: FSMContext):
    """Обработчик создания нового проекта"""
    telegram_id = str(message.from_user.id)
    from database import get_projects_by_user, get_user_by_id
    
    user = await get_user_by_id(telegram_id)
    projects = await get_projects_by_user(telegram_id)
    trial_limit, paid_limit, is_paid = _get_trial_and_paid_limits(user)
    
    if not is_paid and len(projects) >= trial_limit:
        # Trial limit reached
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Оплатить", callback_data="pay_trial")],
                [InlineKeyboardButton(text="Проекты", callback_data="projects_menu")]
            ]
        )
        await message.answer(
            f"Ваш пробный период ограничен {trial_limit} проектами.\n"
            f"Чтобы создать до {paid_limit} проектов, оплатите подписку.\n"
            f"Или вы можете изменить существующий проект под другой бизнес.",
            reply_markup=keyboard
        )
        return
    
    # Если лимит не превышен — начинаем создание проекта
    await state.clear()
    await message.answer(
        "Создание нового проекта\n\nВведите имя вашего проекта:",
        reply_markup=main_menu
    )
    await state.set_state(SettingsStates.waiting_for_project_name)

@settings_router.message(Command("projects"))
async def projects_with_trial_middleware(message: types.Message, state: FSMContext):
    await trial_middleware(message, state, handle_projects_command)

# Обработчики кнопок главного меню
@settings_router.message(lambda message: message.text == "📋 Проекты")
async def handle_projects_button(message: types.Message, state: FSMContext):
    """Обработчик кнопки 'Проекты'"""
    telegram_id = str(message.from_user.id)
    logging.info(f"[BUTTON] handle_projects_button: пользователь {telegram_id} нажал кнопку '📋 Проекты'")
    try:
        await handle_projects_command(message, state)
        logging.info(f"[BUTTON] handle_projects_button: ✅ обработка завершена для пользователя {telegram_id}")
    except Exception as e:
        logging.error(f"[BUTTON] handle_projects_button: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
        raise

@settings_router.message(lambda message: message.text == "➕ Создать проект")
async def handle_new_project_button(message: types.Message, state: FSMContext):
    """Обработчик кнопки 'Создать проект'"""
    telegram_id = str(message.from_user.id)
    logging.info(f"[BUTTON] handle_new_project_button: пользователь {telegram_id} нажал кнопку '➕ Создать проект'")
    try:
        await handle_new_project(message, state)
        logging.info(f"[BUTTON] handle_new_project_button: ✅ обработка завершена для пользователя {telegram_id}")
    except Exception as e:
        logging.error(f"[BUTTON] handle_new_project_button: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
        raise

@settings_router.message(lambda message: message.text == "💰 Оплата")
async def handle_payment_button(message: types.Message, state: FSMContext):
    """Обработчик кнопки 'Оплата'"""
    telegram_id = str(message.from_user.id)
    logging.info(f"[BUTTON] handle_payment_button: пользователь {telegram_id} нажал кнопку '💰 Оплата'")
    try:
        await handle_pay_command(message, state)
        logging.info(f"[BUTTON] handle_payment_button: ✅ обработка завершена для пользователя {telegram_id}")
    except Exception as e:
        logging.error(f"[BUTTON] handle_payment_button: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
        raise

# @settings_router.message(lambda message: message.text == "📊 Статистика")
# async def handle_stats_button(message: types.Message, state: FSMContext):
#     """Обработчик кнопки 'Статистика'"""
#     await message.answer("📊 Статистика доступна по адресу:\nhttps://multik.onrender.com/stats")

@settings_router.message(lambda message: message.text == "❓ Помощь")
async def handle_help_button(message: types.Message, state: FSMContext):
    """Обработчик кнопки 'Помощь'"""
    telegram_id = str(message.from_user.id)
    logging.info(f"[BUTTON] handle_help_button: пользователь {telegram_id} нажал кнопку '❓ Помощь'")
    try:
        await handle_help_command(message, state)
        logging.info(f"[BUTTON] handle_help_button: ✅ обработка завершена для пользователя {telegram_id}")
    except Exception as e:
        logging.error(f"[BUTTON] handle_help_button: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
        raise

@settings_router.message(lambda message: message.text == "🔗 Реферальная программа")
async def handle_referral_button(message: types.Message, state: FSMContext):
    """Обработчик кнопки 'Реферальная программа'"""
    telegram_id = str(message.from_user.id)
    logging.info(f"[BUTTON] handle_referral_button: пользователь {telegram_id} нажал кнопку '🔗 Реферальная программа'")
    try:
        await handle_referral_command(message, state)
        logging.info(f"[BUTTON] handle_referral_button: ✅ обработка завершена для пользователя {telegram_id}")
    except Exception as e:
        logging.error(f"[BUTTON] handle_referral_button: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
        raise

@settings_router.message(lambda message: message.text == "📊 Статистика")
async def handle_stats_button(message: types.Message, state: FSMContext):
    """Обработчик кнопки 'Статистика'"""
    telegram_id = str(message.from_user.id)
    logging.info(f"[BUTTON] handle_stats_button: пользователь {telegram_id} нажал кнопку '📊 Статистика'")
    try:
        await message.answer("📊 Статистика доступна по адресу:\nhttps://multik.onrender.com/stats", reply_markup=main_menu)
        logging.info(f"[BUTTON] handle_stats_button: ✅ обработка завершена для пользователя {telegram_id}")
    except Exception as e:
        logging.error(f"[BUTTON] handle_stats_button: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
        raise

@settings_router.message(lambda message: message.text == "💬 Оставить отзыв")
async def handle_feedback_button(message: types.Message, state: FSMContext):
    """Обработчик кнопки 'Оставить отзыв'"""
    telegram_id = str(message.from_user.id)
    logging.info(f"[BUTTON] handle_feedback_button: пользователь {telegram_id} нажал кнопку '💬 Оставить отзыв'")
    try:
        from settings_feedback import handle_feedback_command
        await handle_feedback_command(message, state)
        logging.info(f"[BUTTON] handle_feedback_button: ✅ обработка завершена для пользователя {telegram_id}")
    except Exception as e:
        logging.error(f"[BUTTON] handle_feedback_button: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
        raise

# Обработчики inline-кнопок для команды /start
@settings_router.callback_query(lambda c: c.data == "start_projects")
async def handle_start_projects(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик inline-кнопки 'Проекты' из стартового меню"""
    telegram_id = str(callback_query.from_user.id)
    logging.info(f"[INLINE] handle_start_projects: пользователь {telegram_id} нажал inline-кнопку '📋 Проекты'")
    try:
        await handle_projects_command(callback_query.message, state)
        await callback_query.answer()
        logging.info(f"[INLINE] handle_start_projects: ✅ обработка завершена для пользователя {telegram_id}")
    except Exception as e:
        logging.error(f"[INLINE] handle_start_projects: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
        await callback_query.answer("Произошла ошибка при получении проектов")
        raise

@settings_router.callback_query(lambda c: c.data == "start_new_project")
async def handle_start_new_project(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик inline-кнопки 'Создать проект' из стартового меню"""
    telegram_id = str(callback_query.from_user.id)
    logging.info(f"[INLINE] handle_start_new_project: пользователь {telegram_id} нажал inline-кнопку '➕ Создать проект'")
    try:
        await handle_new_project(callback_query.message, state)
        await callback_query.answer()
        logging.info(f"[INLINE] handle_start_new_project: ✅ обработка завершена для пользователя {telegram_id}")
    except Exception as e:
        logging.error(f"[INLINE] handle_start_new_project: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
        await callback_query.answer("Произошла ошибка при создании проекта")
        raise

@settings_router.callback_query(lambda c: c.data == "start_payment")
async def handle_start_payment(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик inline-кнопки 'Оплата' из стартового меню"""
    telegram_id = str(callback_query.from_user.id)
    logging.info(f"[INLINE] handle_start_payment: пользователь {telegram_id} нажал inline-кнопку '💰 Оплата'")
    try:
        await handle_pay_command(callback_query.message, state)
        await callback_query.answer()
        logging.info(f"[INLINE] handle_start_payment: ✅ обработка завершена для пользователя {telegram_id}")
    except Exception as e:
        logging.error(f"[INLINE] handle_start_payment: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
        await callback_query.answer("Произошла ошибка при обработке оплаты")
        raise

@settings_router.callback_query(lambda c: c.data == "start_stats")
async def handle_start_stats(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик inline-кнопки 'Статистика' из стартового меню"""
    telegram_id = str(callback_query.from_user.id)
    logging.info(f"[INLINE] handle_start_stats: пользователь {telegram_id} нажал inline-кнопку '📊 Статистика'")
    try:
        await callback_query.message.answer("📊 Статистика доступна по адресу:\nhttps://multik.onrender.com/stats", reply_markup=main_menu)
        await callback_query.answer()
        logging.info(f"[INLINE] handle_start_stats: ✅ обработка завершена для пользователя {telegram_id}")
    except Exception as e:
        logging.error(f"[INLINE] handle_start_stats: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
        await callback_query.answer("Произошла ошибка при получении статистики")
        raise

@settings_router.callback_query(lambda c: c.data == "start_help")
async def handle_start_help(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик inline-кнопки 'Помощь' из стартового меню"""
    telegram_id = str(callback_query.from_user.id)
    logging.info(f"[INLINE] handle_start_help: пользователь {telegram_id} нажал inline-кнопку '❓ Помощь'")
    try:
        await handle_help_command(callback_query.message, state)
        await callback_query.answer()
        logging.info(f"[INLINE] handle_start_help: ✅ обработка завершена для пользователя {telegram_id}")
    except Exception as e:
        logging.error(f"[INLINE] handle_start_help: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
        await callback_query.answer("Произошла ошибка при получении справки")
        raise

@settings_router.callback_query(lambda c: c.data == "start_referral")
async def handle_start_referral(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик inline-кнопки 'Реферальная программа' из стартового меню"""
    telegram_id = str(callback_query.from_user.id)
    logging.info(f"[INLINE] handle_start_referral: пользователь {telegram_id} нажал inline-кнопку '🔗 Реферальная программа'")
    try:
        await handle_referral_command(callback_query.message, state)
        await callback_query.answer()
        logging.info(f"[INLINE] handle_start_referral: ✅ обработка завершена для пользователя {telegram_id}")
    except Exception as e:
        logging.error(f"[INLINE] handle_start_referral: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
        await callback_query.answer("Произошла ошибка при получении реферальной ссылки")
        raise

@settings_router.callback_query(lambda c: c.data == "start_feedback")
async def handle_start_feedback(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработчик inline-кнопки 'Оставить отзыв' из стартового меню"""
    telegram_id = str(callback_query.from_user.id)
    logging.info(f"[INLINE] handle_start_feedback: пользователь {telegram_id} нажал inline-кнопку '💬 Оставить отзыв'")
    try:
        from settings_feedback import handle_feedback_command
        await handle_feedback_command(callback_query.message, state)
        await callback_query.answer()
        logging.info(f"[INLINE] handle_start_feedback: ✅ обработка завершена для пользователя {telegram_id}")
    except Exception as e:
        logging.error(f"[INLINE] handle_start_feedback: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
        await callback_query.answer("Произошла ошибка при отправке отзыва")
        raise

async def handle_pay_command(message: types.Message, state: FSMContext):
    """Обработчик команды оплаты"""
    from database import get_payments
    from config import DISCOUNT_PAYMENT_AMOUNT, PAYMENT_AMOUNT, PAYMENT_CARD_NUMBER
    
    telegram_id = str(message.from_user.id)
    payments = await get_payments()
    user_payments = [p for p in payments if str(p['telegram_id']) == telegram_id]
    
    if len(user_payments) <= 1:
        payment_text = f"💳 **Оплата подписки**\n\nДля оплаты переведите {DISCOUNT_PAYMENT_AMOUNT} рублей на карту:\n`{PAYMENT_CARD_NUMBER}`\n\nПосле оплаты отправьте чек сюда (фото/скриншот)."
    else:
        payment_text = f"💳 **Продление подписки**\n\nДля продления переведите {PAYMENT_AMOUNT} рублей на карту:\n`{PAYMENT_CARD_NUMBER}`\n\nПосле оплаты отправьте чек сюда (фото/скриншот)."
    
    await message.answer(payment_text, reply_markup=main_menu)
    await state.set_state(SettingsStates.waiting_for_payment_check)

@settings_router.message(SettingsStates.waiting_for_project_name)
async def handle_project_name(message: types.Message, state: FSMContext):
    await log_fsm_state(message, state)
    logging.info(f"[BOT] waiting_for_project_name: user={message.from_user.id}, text={message.text}")
    # Проверяем команды через универсальную функцию
    if await handle_command_in_state(message, state):
        return
    
    logger.info(f"Project name received from user {message.from_user.id}: {message.text}")
    telegram_id = str(message.from_user.id)
    from database import check_project_name_exists
    if await check_project_name_exists(telegram_id, message.text):
        await message.answer(f"❌ Проект с именем '{message.text}' уже существует. Пожалуйста, выберите другое имя.")
        await state.clear()
        return
    await state.update_data(project_name=message.text)
    await message.answer("Теперь введите API токен для Telegram-бота.")
    await state.set_state(SettingsStates.waiting_for_token)

@settings_router.message(SettingsStates.waiting_for_token)
async def handle_token(message: types.Message, state: FSMContext):
    await log_fsm_state(message, state)
    logging.info(f"[BOT] waiting_for_token: user={message.from_user.id}, text={message.text}")
    # Проверяем команды через универсальную функцию
    if await handle_command_in_state(message, state):
        return
    
    logger.info(f"Token received from user {message.from_user.id}: {message.text}")
    from database import get_project_by_token
    if await get_project_by_token(message.text):
        await message.answer(f"❌ Проект с таким токеном уже существует. Пожалуйста, введите другой токен.")
        await state.clear()
        return
    await state.update_data(token=message.text)
    await message.answer(
        "Теперь отправьте информацию о вашем бизнесе одним из способов:\n"
        "1️⃣ Загрузите файл (txt, docx, pdf)\n"
        "2️⃣ Просто отправьте текст сообщением\n"
        "3️⃣ Или отправьте голосовое сообщение (мы преобразуем его в текст)"
    )
    await state.set_state(SettingsStates.waiting_for_business_file)

@settings_router.message(SettingsStates.waiting_for_business_file)
async def handle_business_file(message: types.Message, state: FSMContext):
    await log_fsm_state(message, state)
    logging.info(f"[BOT] waiting_for_business_file: user={message.from_user.id}")
    if message.text and await handle_command_in_state(message, state):
        return
    logger.info(f"Business data received from user {message.from_user.id}")
    t0 = time.monotonic()
    try:
        logger.info("[LOAD] Получение данных пользователя...")
        t1 = time.monotonic()
        text_content = await get_text_from_message(message, settings_bot)
        logger.info(f"[LOAD] Получение данных пользователя завершено за {time.monotonic() - t1:.2f} сек")
    except ValueError as ve:
        await message.answer(str(ve))
        await state.clear()
        return
    except RuntimeError as re:
        await message.answer(str(re))
        await state.clear()
        return
    logger.info(f"[LOAD] Длина бизнес-данных: {len(text_content)} символов")
    if len(text_content) > 1000:
        logger.info("[LOAD] Отправка данных в Deepseek...")
        t2 = time.monotonic()
        await message.bot.send_chat_action(message.chat.id, "typing")
        await message.answer("Обрабатываю информацию о Вашем бизнесе с помощью Ai (ориентировочно займёт 1 минуту)...")
        processed_business_info = await process_business_file_with_deepseek(text_content)
        logger.info(f"[LOAD] Deepseek завершён за {time.monotonic() - t2:.2f} сек")
        processed_business_info = clean_markdown(processed_business_info)
    else:
        logger.info("[LOAD] Deepseek не используется, сохраняем текст как есть.")
        processed_business_info = text_content
    data = await state.get_data()
    project_name = data.get("project_name")
    token = data.get("token")
    telegram_id = str(message.from_user.id)
    try:
        logger.info("[LOAD] Запись проекта в БД...")
        t3 = time.monotonic()
        project_id = await create_project(telegram_id, project_name, processed_business_info, token)
        logger.info(f"[LOAD] Запись в БД завершена за {time.monotonic() - t3:.2f} сек")
        
        # Логируем создание проекта в аналитику
        await log_project_created(telegram_id, project_id, project_name)
        
    except ValueError as e:
        await message.answer(f"❌ Ошибка: {str(e)}\n\nПожалуйста, выберите другое название для проекта.")
        await state.clear()
        return
    logger.info("[LOAD] Установка вебхука...")
    t4 = time.monotonic()
    webhook_result = await set_webhook(token, project_id)
    logger.info(f"[LOAD] Установка вебхука завершена за {time.monotonic() - t4:.2f} сек")
    logger.info(f"[LOAD] ВСЕГО времени на загрузку: {time.monotonic() - t0:.2f} сек")
    if webhook_result.get("ok"):
        await message.answer(f"Спасибо! Проект создан.\n\nПроект: {project_name}\nТокен: {token}\nВебхук успешно установлен!\n\nБот готов к работе!")
    else:
        await message.answer(f"Проект создан, но не удалось установить вебхук: {webhook_result}")
    await state.clear()

@settings_router.message(Command("projects"))
async def handle_projects_command(message: types.Message, state: FSMContext, telegram_id: str = None):
    """Показывает список проектов пользователя"""
    logger.info(f"/projects received from user {message.from_user.id}")
    try:
        # Сохраняем telegram_id в состояние
        if telegram_id is None:
            telegram_id = str(message.from_user.id)
        await state.update_data(telegram_id=telegram_id)
        # Сбрасываем только выбор проекта
        await state.update_data(selected_project_id=None, selected_project=None)
        projects = await get_projects_by_user(telegram_id)
        if not projects:
            await message.answer("У вас пока нет проектов. Создайте первый проект командой /new", reply_markup=main_menu)
            return
        # 1. Сначала формируем список кнопок
        buttons = []
        for project in projects:
            buttons.append([
                types.InlineKeyboardButton(
                    text=project["project_name"],
                    callback_data=f"project_{project['id']}"
                )
            ])
        # 2. Только потом создаём клавиатуру (если есть кнопки)
        if buttons:
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
            await message.answer("Выберите проект для управления:", reply_markup=main_menu)
            await message.answer("Список проектов:", reply_markup=keyboard)
        else:
            await message.answer("Нет доступных проектов.", reply_markup=main_menu)
    except Exception as e:
        logger.error(f"Error in handle_projects_command: {e}")
        await message.answer("Произошла ошибка при получении списка проектов", reply_markup=main_menu)

@settings_router.callback_query(lambda c: c.data.startswith('project_'))
async def handle_project_selection(callback_query: types.CallbackQuery, state: FSMContext):
    logging.info(f"[BOT] handle_project_selection: user={callback_query.from_user.id}, data={callback_query.data}")
    project_id = callback_query.data.replace('project_', '')
    logger.info(f"Project selected: {project_id}")
    try:
        project = await get_project_by_id(project_id)
        if not project:
            await callback_query.answer("Проект не найден")
            return
        # Сохраняем выбранный проект в состоянии
        await state.update_data(selected_project_id=project_id, selected_project=project)
        
        # Проверяем, есть ли форма у проекта
        from database import get_project_form
        form = await get_project_form(project_id)
        
        # Создаем меню управления проектом
        buttons = [
            [types.InlineKeyboardButton(text="Показать данные", callback_data="show_data")],
            [types.InlineKeyboardButton(text="Переименовать", callback_data="rename_project")],
            [types.InlineKeyboardButton(text="Изменить токен", callback_data="change_token")],
            [types.InlineKeyboardButton(text="Добавить данные", callback_data="add_data")],
            [types.InlineKeyboardButton(text="Изменить данные", callback_data="change_data")]
        ]
        
        # Добавляем кнопку формы в зависимости от наличия формы
        if form:
            buttons.append([types.InlineKeyboardButton(text="Форма", callback_data="manage_form")])
        else:
            buttons.append([types.InlineKeyboardButton(text="Создать форму", callback_data="create_form")])
        
        buttons.append([types.InlineKeyboardButton(text="Удалить проект", callback_data="delete_project")])
        buttons.append([types.InlineKeyboardButton(text="Назад к списку", callback_data="back_to_projects")])
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback_query.message.edit_text(
            f"Проект: {project['project_name']}\n\nВыберите действие:",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error in handle_project_selection: {e}")
        await callback_query.answer("Произошла ошибка")

@settings_router.callback_query(lambda c: c.data == "back_to_projects")
async def handle_back_to_projects(callback_query: types.CallbackQuery, state: FSMContext):
    """Возврат к списку проектов (использует telegram_id из состояния)"""
    data = await state.get_data()
    telegram_id = data.get("telegram_id")
    if not telegram_id:
        telegram_id = str(callback_query.from_user.id)
    # Очищаем только выбор проекта
    await state.update_data(selected_project_id=None, selected_project=None)
    await handle_projects_command(callback_query.message, state, telegram_id=telegram_id)

@settings_router.callback_query(lambda c: c.data == "rename_project")
async def handle_rename_project(callback_query: types.CallbackQuery, state: FSMContext):
    logging.info(f"[BOT] handle_rename_project: user={callback_query.from_user.id}")
    await callback_query.message.edit_text("Введите новое название проекта:")
    await state.set_state(SettingsStates.waiting_for_new_project_name)

@settings_router.message(SettingsStates.waiting_for_new_project_name)
async def handle_new_project_name(message: types.Message, state: FSMContext):
    await log_fsm_state(message, state)
    logging.info(f"[BOT] waiting_for_new_project_name: user={message.from_user.id}, text={message.text}")
    # Проверяем команды через универсальную функцию
    if await handle_command_in_state(message, state):
        return
    
    """Обрабатывает новое название проекта"""
    try:
        data = await state.get_data()
        project_id = data.get("selected_project_id")
        
        if not project_id:
            await message.answer("Ошибка: проект не выбран")
            await state.clear()
            return
        
        success = await update_project_name(project_id, message.text)
        if success:
            await message.answer(f"Название проекта успешно изменено на: {message.text}")
        else:
            await message.answer("Ошибка при изменении названия проекта")
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Error in handle_new_project_name: {e}")
        await message.answer("Произошла ошибка при изменении названия проекта")
        await state.clear()

@settings_router.callback_query(lambda c: c.data == "add_data")
async def handle_add_data(callback_query: types.CallbackQuery, state: FSMContext):
    logging.info(f"[BOT] handle_add_data: user={callback_query.from_user.id}")
    await callback_query.message.edit_text(
        "Отправьте дополнительные данные о бизнесе одним из способов:\n"
        "1️⃣ Загрузите файл (txt, docx, pdf)\n"
        "2️⃣ Просто отправьте текст сообщением\n"
        "3️⃣ Или отправьте голосовое сообщение (мы преобразуем его в текст)"
    )
    await state.set_state(SettingsStates.waiting_for_additional_data_file)

@settings_router.message(SettingsStates.waiting_for_additional_data_file)
async def handle_additional_data_file(message: types.Message, state: FSMContext):
    await log_fsm_state(message, state)
    logging.info(f"[BOT] waiting_for_additional_data_file: user={message.from_user.id}")
    if message.text and await handle_command_in_state(message, state):
        return
    t0 = time.monotonic()
    try:
        data = await state.get_data()
        project_id = data.get("selected_project_id")
        if not project_id:
            await message.answer("Ошибка: проект не выбран")
            await state.clear()
            return
        logger.info("[ADD] Получение данных пользователя...")
        t1 = time.monotonic()
        text_content = await get_text_from_message(message, settings_bot)
        logger.info(f"[ADD] Получение данных пользователя завершено за {time.monotonic() - t1:.2f} сек")
    except ValueError as ve:
        await message.answer(str(ve))
        await state.clear()
        return
    except RuntimeError as re:
        await message.answer(str(re))
        await state.clear()
        return
    logger.info(f"[ADD] Длина бизнес-данных: {len(text_content)} символов")
    if len(text_content) > 1000:
        logger.info("[ADD] Отправка данных в Deepseek...")
        t2 = time.monotonic()
        await message.bot.send_chat_action(message.chat.id, "typing")
        await message.answer("Обрабатываю дополнительные данные...")
        processed_additional_info = await process_business_file_with_deepseek(text_content)
        logger.info(f"[ADD] Deepseek завершён за {time.monotonic() - t2:.2f} сек")
        processed_additional_info = clean_markdown(processed_additional_info)
    else:
        logger.info("[ADD] Deepseek не используется, сохраняем текст как есть.")
        processed_additional_info = text_content
    logger.info("[ADD] Запись в БД...")
    t3 = time.monotonic()
    success = await append_project_business_info(project_id, processed_additional_info)
    logger.info(f"[ADD] Запись в БД завершена за {time.monotonic() - t3:.2f} сек")
    logger.info(f"[ADD] ВСЕГО времени на добавление: {time.monotonic() - t0:.2f} сек")
    if success:
        project = await get_project_by_id(project_id)
        if project:
            await clear_asking_bot_cache(project["token"])
        await message.answer("Дополнительные данные успешно добавлены к проекту!")
    else:
        await message.answer("Ошибка при добавлении дополнительных данных")
    await state.clear()

@settings_router.callback_query(lambda c: c.data == "change_data")
async def handle_change_data(callback_query: types.CallbackQuery, state: FSMContext):
    logging.info(f"[BOT] handle_change_data: user={callback_query.from_user.id}")
    await callback_query.message.edit_text(
        "Отправьте новые данные о бизнесе одним из способов:\n"
        "1️⃣ Загрузите файл (txt, docx, pdf)\n"
        "2️⃣ Просто отправьте текст сообщением\n"
        "3️⃣ Или отправьте голосовое сообщение (мы преобразуем его в текст)\n"
        "Старые данные будут полностью заменены новыми."
    )
    await state.set_state(SettingsStates.waiting_for_new_data_file)

@settings_router.message(SettingsStates.waiting_for_new_data_file)
async def handle_new_data_file(message: types.Message, state: FSMContext):
    await log_fsm_state(message, state)
    logging.info(f"[BOT] waiting_for_new_data_file: user={message.from_user.id}")
    if message.text and await handle_command_in_state(message, state):
        return
    t0 = time.monotonic()
    try:
        data = await state.get_data()
        project_id = data.get("selected_project_id")
        if not project_id:
            await message.answer("Ошибка: проект не выбран")
            await state.clear()
            return
        logger.info("[REPLACE] Получение данных пользователя...")
        t1 = time.monotonic()
        text_content = await get_text_from_message(message, settings_bot)
        logger.info(f"[REPLACE] Получение данных пользователя завершено за {time.monotonic() - t1:.2f} сек")
    except ValueError as ve:
        await message.answer(str(ve))
        await state.clear()
        return
    except RuntimeError as re:
        await message.answer(str(re))
        await state.clear()
        return
    logger.info(f"[REPLACE] Длина бизнес-данных: {len(text_content)} символов")
    if len(text_content) > 1000:
        logger.info("[REPLACE] Отправка данных в Deepseek...")
        t2 = time.monotonic()
        await message.bot.send_chat_action(message.chat.id, "typing")
        await message.answer("Обрабатываю новые данные...")
        processed_new_info = await process_business_file_with_deepseek(text_content)
        logger.info(f"[REPLACE] Deepseek завершён за {time.monotonic() - t2:.2f} сек")
        processed_new_info = clean_markdown(processed_new_info)
    else:
        logger.info("[REPLACE] Deepseek не используется, сохраняем текст как есть.")
        processed_new_info = text_content
    logger.info("[REPLACE] Запись в БД...")
    t3 = time.monotonic()
    success = await update_project_business_info(project_id, processed_new_info)
    logger.info(f"[REPLACE] Запись в БД завершена за {time.monotonic() - t3:.2f} сек")
    logger.info(f"[REPLACE] ВСЕГО времени на замену: {time.monotonic() - t0:.2f} сек")
    if success:
        project = await get_project_by_id(project_id)
        if project:
            await clear_asking_bot_cache(project["token"])
        await message.answer("Данные проекта успешно обновлены!")
    else:
        await message.answer("Ошибка при обновлении данных проекта")
    await state.clear()

@settings_router.callback_query(lambda c: c.data == "delete_project")
async def handle_delete_project_request(callback_query: types.CallbackQuery, state: FSMContext):
    logging.info(f"[BOT] handle_delete_project_request: user={callback_query.from_user.id}")
    """Запрашивает подтверждение удаления проекта"""
    data = await state.get_data()
    project = data.get("selected_project")
    
    buttons = [
        [types.InlineKeyboardButton(text="Да, удалить", callback_data="confirm_delete")],
        [types.InlineKeyboardButton(text="Отмена", callback_data="cancel_delete")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback_query.message.edit_text(
        f"Вы уверены, что хотите удалить проект '{project['project_name']}'?\n"
        "Это действие нельзя отменить. Бот будет остановлен и webhook отключен.",
        reply_markup=keyboard
    )

@settings_router.callback_query(lambda c: c.data == "cancel_delete")
async def handle_cancel_delete(callback_query: types.CallbackQuery, state: FSMContext):
    logging.info(f"[BOT] handle_cancel_delete: user={callback_query.from_user.id}")
    """Отменяет удаление проекта"""
    data = await state.get_data()
    project = data.get("selected_project")
    
    buttons = [
        [types.InlineKeyboardButton(text="Переименовать", callback_data="rename_project")],
        [types.InlineKeyboardButton(text="Добавить данные", callback_data="add_data")],
        [types.InlineKeyboardButton(text="Изменить данные", callback_data="change_data")],
        [types.InlineKeyboardButton(text="Удалить проект", callback_data="delete_project")],
        [types.InlineKeyboardButton(text="Назад к списку", callback_data="back_to_projects")]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback_query.message.edit_text(
        f"Проект: {project['project_name']}\n\nВыберите действие:",
        reply_markup=keyboard
    )

@settings_router.callback_query(lambda c: c.data == "confirm_delete")
async def handle_confirm_delete(callback_query: types.CallbackQuery, state: FSMContext):
    logging.info(f"[BOT] handle_confirm_delete: user={callback_query.from_user.id}")
    """Подтверждает удаление проекта"""
    try:
        data = await state.get_data()
        project_id = data.get("selected_project_id")
        project = data.get("selected_project")
        
        if not project_id:
            await callback_query.answer("Ошибка: проект не найден")
            return
        
        # Отключаем webhook
        webhook_result = await delete_webhook(project["token"])
        logger.info(f"Webhook deletion result: {webhook_result}")
        
        # Удаляем проект из базы данных
        delete_result = await delete_project(project_id)
        
        if delete_result:
            await callback_query.message.edit_text(
                f"Проект '{project['project_name']}' успешно удален!\n"
                "Webhook отключен, бот остановлен."
            )
        else:
            await callback_query.message.edit_text(
                "Ошибка при удалении проекта из базы данных."
            )
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Error in handle_confirm_delete: {e}")
        await callback_query.message.edit_text("Произошла ошибка при удалении проекта")
        await state.clear()

@router.post(SETTINGS_WEBHOOK_PATH)
async def process_settings_webhook(request: Request):
    logger.info("Received webhook call for settings bot")
    try:
        update_data = await request.json()
        logger.info(f"Update data: {update_data}")
        update = types.Update.model_validate(update_data)
        await settings_dp.feed_update(settings_bot, update)
        logger.info("Update processed successfully")
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error in process_settings_webhook: {e}\n{traceback.format_exc()}")
        return {"ok": False, "error": str(e), "trace": traceback.format_exc()}

@router.post("/create_project_meta")
async def create_project_meta(
    telegram_id: str = Form(...),
    project_name: str = Form(...),
    business_info: str = Form(...),
    token: str = Form(...)
):
    logs = []
    try:
        project_id = await create_project(telegram_id, project_name, business_info, token)
        logs.append(f"[STEP] Проект создан: {project_id}")
        webhook_result = await set_webhook(token, project_id)
        if webhook_result.get("ok"):
            logs.append(f"[STEP] Вебхук успешно установлен для project_id={project_id}")
        else:
            logs.append(f"[ERROR] Не удалось установить вебхук: {webhook_result}")
        return {"status": "ok", "project_id": project_id, "logs": logs}
    except Exception as e:
        logs.append(f"[ERROR] Ошибка при создании проекта: {str(e)}")
        return {"status": "error", "message": str(e), "logs": logs}

async def set_settings_webhook():
    await settings_bot.set_webhook(SETTINGS_WEBHOOK_URL)

@settings_router.callback_query(lambda c: c.data == "show_data")
async def handle_show_data(callback_query: types.CallbackQuery, state: FSMContext):
    """Показывает бизнес-данные выбранного проекта"""
    data = await state.get_data()
    project = data.get("selected_project")
    if not project:
        await callback_query.answer("Проект не выбран", show_alert=True)
        return
    business_info = project.get("business_info")
    if not business_info:
        await callback_query.message.answer("Нет данных о бизнесе для этого проекта.")
    else:
        # Если данных много, делим на части по 4096 символов (лимит Telegram)
        max_len = 4096
        for i in range(0, len(business_info), max_len):
            await callback_query.message.answer(business_info[i:i+max_len])
    await callback_query.answer()

@settings_router.callback_query(lambda c: c.data == "pay_trial")
async def handle_pay_trial(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.message.answer(
        f"Для оплаты переведите {DISCOUNT_PAYMENT_AMOUNT} рублей на карту: {PAYMENT_CARD_NUMBER}\n\nПосле оплаты отправьте чек сюда (фото/скриншот)."
    )
    await state.set_state(SettingsStates.waiting_for_payment_check)
    await callback_query.answer()

@settings_router.callback_query(lambda c: c.data == "projects_menu")
async def handle_projects_menu(callback_query: types.CallbackQuery, state: FSMContext):
    telegram_id = str(callback_query.from_user.id)
    await handle_projects_command(callback_query.message, state, telegram_id=telegram_id)
    await callback_query.answer()

@settings_router.callback_query(lambda c: c.data == "delete_trial_projects")
async def handle_delete_trial_projects(callback_query: types.CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, удалить", callback_data="confirm_delete_trial_projects")],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel_delete_trial_projects")]
        ]
    )
    await callback_query.message.answer(
        "Вы уверены, что хотите удалить все проекты? Восстановить их будет невозможно!",
        reply_markup=kb
    )
    await callback_query.answer()

@settings_router.callback_query(lambda c: c.data == "confirm_delete_trial_projects")
async def handle_confirm_delete_trial_projects(callback_query: types.CallbackQuery, state: FSMContext):
    telegram_id = str(callback_query.from_user.id)
    await delete_all_projects_for_user(telegram_id)
    await callback_query.message.answer("Все ваши проекты удалены. Вы можете начать заново с пробным периодом или оплатить для расширения возможностей.")
    await callback_query.answer()

@settings_router.callback_query(lambda c: c.data == "cancel_delete_trial_projects")
async def handle_cancel_delete_trial_projects(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.message.answer("Удаление отменено.")
    await callback_query.answer()

@settings_router.message(Command("pay"))
async def pay_command(message: types.Message, state: FSMContext):
    await handle_pay_command(message, state)

@settings_router.callback_query(lambda c: c.data == "pay")
async def pay_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await handle_pay_callback(callback_query, state)
    await callback_query.answer()

@settings_router.message(lambda m: m.photo and m.caption and "чек" in m.caption.lower())
async def payment_check(message: types.Message, state: FSMContext):
    await handle_payment_check(message, state)

@settings_router.message(lambda m: m.document and m.caption and "чек" in m.caption.lower())
async def payment_check_document(message: types.Message, state: FSMContext):
    await handle_payment_check_document(message, state)

@settings_router.message(lambda m: m.document)
async def payment_check_document_any(message: types.Message, state: FSMContext):
    await handle_payment_check_document_any(message, state)

@settings_router.message(lambda m: m.photo)
async def payment_check_photo_any(message: types.Message, state: FSMContext):
    await handle_payment_check_photo_any(message, state)

@settings_router.message(Command("feedback"))
async def feedback_command(message: types.Message, state: FSMContext):
    await handle_feedback_command(message, state)

@settings_router.callback_query(lambda c: c.data.startswith("feedback_rate:"))
async def feedback_rating_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await handle_feedback_rating_callback(callback_query, state)

@settings_router.callback_query(lambda c: c.data == "feedback_change_rating")
async def feedback_change_rating(callback_query: types.CallbackQuery, state: FSMContext):
    await handle_feedback_change_rating(callback_query, state)

@settings_router.message(SettingsStates.waiting_for_feedback_text)
async def feedback_text(message: types.Message, state: FSMContext):
    await handle_feedback_text(message, state)

@settings_router.callback_query(lambda c: c.data == "change_token")
async def handle_change_token(callback_query: types.CallbackQuery, state: FSMContext):
    logging.info(f"[BOT] handle_change_token: user={callback_query.from_user.id}")
    await callback_query.message.edit_text("Введите новый API токен для этого проекта:")
    await state.set_state(SettingsStates.waiting_for_new_token)

@settings_router.message(SettingsStates.waiting_for_new_token)
async def handle_new_token(message: types.Message, state: FSMContext):
    await log_fsm_state(message, state)
    logging.info(f"[BOT] waiting_for_new_token: user={message.from_user.id}, text={message.text}")
    if await handle_command_in_state(message, state):
        return
    from database import update_project_token, get_project_by_token
    data = await state.get_data()
    project_id = data.get("selected_project_id")
    if not project_id:
        await message.answer("Ошибка: проект не выбран")
        await state.clear()
        return
    # Проверка уникальности токена
    existing = await get_project_by_token(message.text)
    if existing and existing["id"] != project_id:
        await message.answer("❌ Проект с таким токеном уже существует. Пожалуйста, введите другой токен.")
        return
    success = await update_project_token(project_id, message.text)
    if success:
        await message.answer(f"Токен проекта успешно изменён на: {message.text}")
    else:
        await message.answer("Ошибка при изменении токена проекта")
    await state.clear() 

@settings_router.message(Command("referral"))
async def referral_command(message: types.Message, state: FSMContext):
    await handle_referral_command(message, state)

@settings_router.callback_query(lambda c: c.data == "referral")
async def referral_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await handle_referral_command(callback_query.message, state)
    await callback_query.answer()

async def handle_referral_command(message, state):
    """Обработчик команды /referral"""
    telegram_id = str(message.from_user.id)
    logging.info(f"[REFERRAL] handle_referral_command: пользователь {telegram_id} запросил реферальную ссылку")
    
    from database import get_referral_link, get_user_by_id
    user = await get_user_by_id(telegram_id)
    
    if not user:
        await message.answer("Сначала создайте аккаунт командой /start")
        return
    
    referral_link = await get_referral_link(telegram_id)
    
    referral_text = f"""
🎁 Ваша реферальная ссылка:

{referral_link}

📊 Как это работает:
• Отправьте эту ссылку друзьям
• Когда они зарегистрируются и оплатят подписку
• Вы получите +10 дней к пользованию за каждого реферала

💡 Просто скопируйте ссылку и поделитесь с друзьями!
    """
    
    await message.answer(referral_text)

@settings_router.message()
async def handle_any_message(message: types.Message, state: FSMContext):
    await trial_middleware(message, state, _handle_any_message_inner)

async def _handle_any_message_inner(message: types.Message, state: FSMContext):
    await log_fsm_state(message, state)
    logging.info(f"[BOT] handle_any_message: user={message.from_user.id}, text={message.text}")
    # --- Обработка подтверждения/отклонения оплаты админом ---
    if message.text and message.text.lower().startswith("оплатил ") and str(message.from_user.id) == str(MAIN_TELEGRAM_ID):
        parts = message.text.strip().split()
        if len(parts) == 2 and parts[1].isdigit():
            paid_telegram_id = parts[1]
            logging.info(f"[PAYMENT] Обработка подтверждения оплаты для пользователя {paid_telegram_id}")
            
            # Подтверждаем pending платеж
            from database import confirm_payment, get_pending_payments
            success = await confirm_payment(paid_telegram_id)
            
            if not success:
                logging.warning(f"[PAYMENT] Не найден pending платеж для пользователя {paid_telegram_id}")
                await message.answer(f"⚠️ Не найден pending платеж для пользователя {paid_telegram_id}")
                return
            
            logging.info(f"[PAYMENT] Платеж подтвержден для пользователя {paid_telegram_id}")
            
            await set_user_paid(paid_telegram_id, True)
            
            # Обработка реферальной системы
            from database import process_referral_payment
            # Используем None для username - функция сама обработает это
            referral_result = await process_referral_payment(paid_telegram_id, None)
            
            # Восстановить вебхуки на все проекты пользователя
            projects = await get_user_projects(paid_telegram_id)
            restored = 0
            for project in projects:
                try:
                    await set_webhook(project['token'], project['id'])
                    restored += 1
                except Exception as e:
                    logger.error(f"[PAYMENT] Ошибка при восстановлении вебхука: {e}")
            
            # Уведомить пользователя
            try:
                await settings_bot.send_message(paid_telegram_id, f"Оплата подтверждена! Ваши проекты снова активны. Теперь вы можете создавать до {PAID_PROJECTS} проектов.")
            except Exception as e:
                logger.error(f"[PAYMENT] Не удалось отправить сообщение пользователю: {e}")
            
            # Уведомить реферера, если есть
            if referral_result:
                try:
                    await settings_bot.send_message(referral_result['referrer_id'], referral_result['message'])
                    logging.info(f"[REFERRAL] Отправлено уведомление рефереру {referral_result['referrer_id']}")
                except Exception as e:
                    logging.error(f"[REFERRAL] Не удалось отправить уведомление рефереру: {e}")
            
            await message.answer(f"Пользователь {paid_telegram_id} отмечен как оплативший. Вебхуки восстановлены для {restored} проектов.")
            return
    
    # --- Обработка отклонения оплаты админом ---
    if message.text and message.text.lower().startswith("отклонить ") and str(message.from_user.id) == str(MAIN_TELEGRAM_ID):
        parts = message.text.strip().split()
        if len(parts) == 2 and parts[1].isdigit():
            rejected_telegram_id = parts[1]
            logging.info(f"[PAYMENT] Обработка отклонения оплаты для пользователя {rejected_telegram_id}")
            
            # Отклоняем pending платеж
            from database import reject_payment
            success = await reject_payment(rejected_telegram_id)
            
            if not success:
                logging.warning(f"[PAYMENT] Не найден pending платеж для отклонения пользователя {rejected_telegram_id}")
                await message.answer(f"⚠️ Не найден pending платеж для отклонения пользователя {rejected_telegram_id}")
                return
            
            logging.info(f"[PAYMENT] Платеж отклонен для пользователя {rejected_telegram_id}")
            
            # Уведомить пользователя об отклонении
            try:
                await settings_bot.send_message(rejected_telegram_id, "❌ Ваш платеж был отклонен. Пожалуйста, проверьте правильность чека и попробуйте снова.")
            except Exception as e:
                logger.error(f"[PAYMENT] Не удалось отправить сообщение об отклонении пользователю: {e}")
            
            await message.answer(f"Платеж пользователя {rejected_telegram_id} отклонен. Пользователь уведомлен.")
            return
    
    # --- Просмотр pending платежей админом ---
    if message.text and message.text.lower() == "pending" and str(message.from_user.id) == str(MAIN_TELEGRAM_ID):
        logging.info(f"[PAYMENT] Запрос на просмотр pending платежей от админа")
        
        from database import get_pending_payments
        pending_payments = await get_pending_payments()
        
        if not pending_payments:
            await message.answer("📋 Нет pending платежей")
            return
        
        response = "📋 Pending платежи:\n\n"
        for i, payment in enumerate(pending_payments, 1):
            response += f"{i}. Пользователь {payment['telegram_id']} - {payment['amount']} руб.\n"
        
        response += "\n💡 Для подтверждения: оплатил [ID]\n💡 Для отклонения: отклонить [ID]"
        
        await message.answer(response)
        return

    user = await get_user_by_id(str(message.from_user.id))
    is_trial = user and not user['paid']
    is_paid = user and user['paid']
    await log_message_stat(
        telegram_id=str(message.from_user.id),
        is_command=bool(message.text and message.text.startswith('/')),
        is_reply=bool(message.reply_to_message),
        response_time=None,
        project_id=None,
        is_trial=is_trial,
        is_paid=is_paid
    )

# Главное меню с кнопками
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Проекты"), KeyboardButton(text="➕ Создать проект")],
        [KeyboardButton(text="💰 Оплата"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="❓ Помощь"), KeyboardButton(text="🔗 Реферальная программа")],
        [KeyboardButton(text="💬 Оставить отзыв")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

async def handle_settings_start(message: types.Message, state: FSMContext):
    logger = logging.getLogger(__name__)
    logger.info(f"/start received from user {message.from_user.id}")
    try:
        await state.clear()
        # Проверяем, есть ли реферальный параметр в команде /start
        referrer_id = None
        if message.text and message.text.startswith('/start'):
            parts = message.text.split()
            if len(parts) > 1 and parts[1].startswith('ref'):
                referrer_id = parts[1][3:]  # Убираем 'ref' из начала
                logger.info(f"[REFERRAL] handle_settings_start: пользователь {message.from_user.id} пришел по реферальной ссылке от {referrer_id}")
        
        await create_user(str(message.from_user.id), referrer_id)
        await message.answer("Добро пожаловать в настройки! Введите имя вашего проекта.", reply_markup=main_menu)
        await state.set_state(SettingsStates.waiting_for_project_name)
        logger.info(f"Sent welcome message to user {message.from_user.id}")
    except Exception as e:
        logger.error(f"Error in handle_settings_start: {e}")

async def handle_help_command(message: types.Message, state: FSMContext):
    await state.clear()
    help_text = """
🤖 **Доступные команды:**

/start - Главное меню
/new - Создать новый проект
/projects - Управление существующими проектами
/help - Показать эту справку
/pay - Оплата подписки
/feedback - Оставить отзыв о сервисе
/referral - Получить реферальную ссылку

📋 **Функции управления проектами:**
• Переименование проекта
• Добавление дополнительных данных
• Изменение данных о бизнесе
• Создание форм для сбора заявок
• Удаление проекта (с отключением webhook)

🎁 **Реферальная программа:**
• Приглашайте друзей по реферальной ссылке
• За каждую оплату реферала получайте +10 дней к пользованию

💡 **Для начала работы используйте /new**
💡 **Для управления проектами используйте /projects**
💡 **Для оплаты используйте команду /pay**
💡 **Для отзыва используйте /feedback**
💡 **Для реферальной ссылки используйте /referral**
    """
    pay_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оплатить", callback_data="pay")],
            [InlineKeyboardButton(text="Реферальная ссылка", callback_data="referral")]
        ]
    )
    await message.bot.send_chat_action(message.chat.id, "typing")
    await message.answer(help_text, reply_markup=pay_kb)

async def handle_projects_command(message: types.Message, state: FSMContext, telegram_id: str = None):
    logger = logging.getLogger(__name__)
    logger.info(f"/projects received from user {message.from_user.id}")
    try:
        if telegram_id is None:
            telegram_id = str(message.from_user.id)
        await state.update_data(telegram_id=telegram_id)
        await state.update_data(selected_project_id=None, selected_project=None)
        projects = await get_projects_by_user(telegram_id)
        if not projects:
            await message.answer("У вас пока нет проектов. Создайте первый проект командой /new", reply_markup=main_menu)
            return
        buttons = []
        for project in projects:
            buttons.append([
                types.InlineKeyboardButton(
                    text=project["project_name"],
                    callback_data=f"project_{project['id']}"
                )
            ])
        if buttons:
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
            await message.answer("Выберите проект для управления:", reply_markup=main_menu)
            await message.answer("Список проектов:", reply_markup=keyboard)
        else:
            await message.answer("Нет доступных проектов.", reply_markup=main_menu)
    except Exception as e:
        logger.error(f"Error in handle_projects_command: {e}")
        await message.answer("Произошла ошибка при получении списка проектов", reply_markup=main_menu)

@settings_router.callback_query(lambda c: c.data == "pay_subscription")
async def handle_pay_subscription(callback_query: types.CallbackQuery, state: FSMContext):
    from database import get_payments
    from config import DISCOUNT_PAYMENT_AMOUNT, PAYMENT_AMOUNT, PAYMENT_CARD_NUMBER
    telegram_id = str(callback_query.from_user.id)
    payments = await get_payments()
    user_payments = [p for p in payments if str(p['telegram_id']) == telegram_id]
    if len(user_payments) <= 1:
        await callback_query.message.answer(
            f"Для оплаты переведите {DISCOUNT_PAYMENT_AMOUNT} рублей на карту: {PAYMENT_CARD_NUMBER}\n\nПосле оплаты отправьте чек сюда (фото/скриншот)."
        )
    else:
        await callback_query.message.answer(
            f"Для продления подписки переведите {PAYMENT_AMOUNT} рублей на карту: {PAYMENT_CARD_NUMBER}\n\nПосле оплаты отправьте чек сюда (фото/скриншот)."
        )
    await state.set_state(SettingsStates.waiting_for_payment_check)
    await callback_query.answer()

@settings_router.message(SettingsStates.waiting_for_payment_check)
async def handle_payment_check_fsm(message: types.Message, state: FSMContext):
    # Любой файл или фото в этом состоянии — это чек
    if message.document or message.photo:
        await handle_payment_check(message, state)
        await message.answer("Чек получен! Мы проверим оплату и сообщим, когда доступ будет расширен.")
        await state.set_state(ExtendedSettingsStates.waiting_for_payment_confirmation)
    else:
        await message.answer("Пожалуйста, отправьте файл или фото чека об оплате.")

# --- Обработчики форм ---
@settings_router.callback_query(lambda c: c.data == "create_form")
async def handle_create_form(callback_query: types.CallbackQuery, state: FSMContext):
    """Начинает создание формы"""
    logging.info(f"[FORM] handle_create_form: user={callback_query.from_user.id}")
    
    form_text = """
📋 **Создание формы для сбора заявок**

Форма поможет собирать информацию от клиентов:
• ФИО, телефон, удобное время
• Специализированные данные (марка машины, возраст студента и т.д.)
• Asking бот будет непринужденно собирать эту информацию

Нажмите "Добавить поле" чтобы начать создание формы.
    """
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Добавить поле", callback_data="add_form_field")],
        [types.InlineKeyboardButton(text="Отмена", callback_data="back_to_projects")]
    ])
    
    await callback_query.message.edit_text(form_text, reply_markup=keyboard)

@settings_router.callback_query(lambda c: c.data == "manage_form")
async def handle_manage_form(callback_query: types.CallbackQuery, state: FSMContext):
    """Управление существующей формой"""
    logging.info(f"[FORM] handle_manage_form: user={callback_query.from_user.id}")
    
    data = await state.get_data()
    project_id = data.get("selected_project_id")
    
    if not project_id:
        await callback_query.answer("Ошибка: проект не выбран")
        return
    
    from database import get_project_form, get_form_submissions
    form = await get_project_form(project_id)
    
    if not form:
        await callback_query.answer("Форма не найдена")
        return
    
    # Получаем количество заявок
    submissions = await get_form_submissions(form["id"])
    
    form_text = f"""
📋 **Управление формой: {form['name']}**

Поля формы:
"""
    
    for field in form["fields"]:
        required_mark = "🔴" if field["required"] else "⚪"
        form_text += f"• {required_mark} {field['name']} ({field['field_type']})\n"
    
    form_text += f"\n📊 Заявок: {len(submissions)}"
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Экспорт в Excel", callback_data="export_form")],
        [types.InlineKeyboardButton(text="Создать новую форму", callback_data="create_form")],
        [types.InlineKeyboardButton(text="Назад", callback_data="back_to_projects")]
    ])
    
    await callback_query.message.edit_text(form_text, reply_markup=keyboard)

@settings_router.callback_query(lambda c: c.data == "add_form_field")
async def handle_add_form_field(callback_query: types.CallbackQuery, state: FSMContext):
    """Начинает добавление поля в форму"""
    logging.info(f"[FORM] handle_add_form_field: user={callback_query.from_user.id}")
    
    data = await state.get_data()
    project_id = data.get("selected_project_id")
    
    if not project_id:
        await callback_query.answer("Ошибка: проект не выбран")
        return
    
    # Проверяем, есть ли уже форма
    from database import get_project_form, create_form
    form = await get_project_form(project_id)
    
    if not form:
        # Создаем новую форму
        form_name = f"Форма проекта {project_id}"
        form_id = await create_form(project_id, form_name)
        
        # Логируем создание формы в аналитику
        await log_form_created(str(callback_query.from_user.id), project_id, form_name)
        
        await state.update_data(current_form_id=form_id)
    else:
        await state.update_data(current_form_id=form["id"])
    
    await callback_query.message.edit_text(
        "Введите название поля формы:\n\nНапример: ФИО, Телефон, Марка машины, Возраст студента и т.д.",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Отмена", callback_data="back_to_projects")]
        ])
    )
    await state.set_state(SettingsStates.waiting_for_field_name)

@settings_router.message(SettingsStates.waiting_for_field_name)
async def handle_field_name(message: types.Message, state: FSMContext):
    """Обрабатывает название поля формы"""
    await log_fsm_state(message, state)
    logging.info(f"[FORM] handle_field_name: user={message.from_user.id}, text={message.text}")
    
    if await handle_command_in_state(message, state):
        return
    
    await state.update_data(field_name=message.text)
    
    # Показываем типы полей
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Текст", callback_data="field_type_text")],
        [types.InlineKeyboardButton(text="Число", callback_data="field_type_number")],
        [types.InlineKeyboardButton(text="Телефон", callback_data="field_type_phone")],
        [types.InlineKeyboardButton(text="Дата", callback_data="field_type_date")],
        [types.InlineKeyboardButton(text="Email", callback_data="field_type_email")],
        [types.InlineKeyboardButton(text="Назад", callback_data="add_form_field")]
    ])
    
    await message.answer(
        f"Выберите тип поля для '{message.text}':",
        reply_markup=keyboard
    )

@settings_router.callback_query(lambda c: c.data.startswith("field_type_"))
async def handle_field_type(callback_query: types.CallbackQuery, state: FSMContext):
    """Обрабатывает выбор типа поля"""
    logging.info(f"[FORM] handle_field_type: user={callback_query.from_user.id}, data={callback_query.data}")
    
    field_type = callback_query.data.replace("field_type_", "")
    data = await state.get_data()
    field_name = data.get("field_name")
    form_id = data.get("current_form_id")
    
    if not field_name or not form_id:
        await callback_query.answer("Ошибка: данные не найдены")
        return
    
    # Добавляем поле в форму
    from database import add_form_field
    await add_form_field(form_id, field_name, field_type, required=False)
    
    # Показываем текущую форму
    await show_form_preview(callback_query.message, state, form_id)

async def show_form_preview(message, state: FSMContext, form_id: str):
    """Показывает предварительный просмотр формы"""
    from database import get_project_form
    
    # Получаем форму с полями
    project_id = (await state.get_data()).get("selected_project_id")
    form = await get_project_form(project_id)
    
    if not form:
        await message.edit_text("Ошибка: форма не найдена")
        return
    
    preview_text = f"📋 **Форма: {form['name']}**\n\nПоля формы:\n"
    
    for i, field in enumerate(form["fields"], 1):
        required_mark = "🔴" if field["required"] else "⚪"
        preview_text += f"{i}. {required_mark} {field['name']} ({field['field_type']})\n"
    
    preview_text += "\nВыберите действие:"
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Использовать форму", callback_data="use_form")],
        [types.InlineKeyboardButton(text="Добавить поле", callback_data="add_form_field")],
        [types.InlineKeyboardButton(text="Назад к проекту", callback_data="back_to_projects")]
    ])
    
    await message.edit_text(preview_text, reply_markup=keyboard)

@settings_router.callback_query(lambda c: c.data == "use_form")
async def handle_use_form(callback_query: types.CallbackQuery, state: FSMContext):
    """Подтверждает использование формы"""
    logging.info(f"[FORM] handle_use_form: user={callback_query.from_user.id}")
    
    await callback_query.message.edit_text(
        "✅ Форма создана и готова к использованию!\n\n"
        "Asking бот будет автоматически собирать информацию от клиентов по этой форме.",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Назад к проекту", callback_data="back_to_projects")]
        ])
    )
    await state.clear()

@settings_router.callback_query(lambda c: c.data == "export_form")
async def handle_export_form(callback_query: types.CallbackQuery, state: FSMContext):
    """Экспортирует данные формы в Excel"""
    logging.info(f"[FORM] handle_export_form: user={callback_query.from_user.id}")
    
    data = await state.get_data()
    project_id = data.get("selected_project_id")
    
    if not project_id:
        await callback_query.answer("Ошибка: проект не выбран")
        return
    
    from database import get_project_form, get_form_submissions
    
    form = await get_project_form(project_id)
    if not form:
        await callback_query.answer("Форма не найдена")
        return
    
    submissions = await get_form_submissions(form["id"])
    
    if not submissions:
        await callback_query.answer("Нет данных для экспорта")
        return
    
    # Создаем Excel файл
    try:
        import pandas as pd
        import io
        
        # Подготавливаем данные для Excel
        excel_data = []
        for submission in submissions:
            row = {
                "ID заявки": submission["id"],
                "Telegram ID": submission["telegram_id"],
                "Дата подачи": submission["submitted_at"].strftime("%Y-%m-%d %H:%M:%S")
            }
            # Добавляем поля формы
            for field_name, field_value in submission["data"].items():
                row[field_name] = field_value
            excel_data.append(row)
        
        df = pd.DataFrame(excel_data)
        
        # Создаем Excel файл в памяти
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Заявки', index=False)
        
        output.seek(0)
        
        # Отправляем файл
        await callback_query.message.answer_document(
            types.BufferedInputFile(
                output.read(),
                filename=f"form_submissions_{form['name']}.xlsx"
            ),
            caption=f"📊 Экспорт заявок формы '{form['name']}'\n\nВсего заявок: {len(submissions)}"
        )
        
    except Exception as e:
        logging.error(f"[FORM] handle_export_form: ОШИБКА: {e}")
        await callback_query.answer("Ошибка при создании Excel файла")
