from fastapi import APIRouter, Request, Form
from aiogram import Bot, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router, Dispatcher
from aiogram.filters import Command
import random
import os
from config import SETTINGS_BOT_TOKEN, SERVER_URL, DEEPSEEK_API_KEY, TRIAL_DAYS, TRIAL_PROJECTS, PAID_PROJECTS, PAYMENT_AMOUNT, MAIN_TELEGRAM_ID, DISCOUNT_PAYMENT_AMOUNT, PAYMENT_CARD_NUMBER1, PAYMENT_CARD_NUMBER2, PAYMENT_CARD_NUMBER3
from database import create_project, get_project_by_id, create_user, get_projects_by_user, update_project_name, update_project_business_info, append_project_business_info, delete_project, check_project_name_exists, get_user_by_id, get_users_with_expired_trial, delete_all_projects_for_user, set_user_paid, get_user_projects, log_message_stat, add_feedback, get_users_with_expired_paid_month, set_trial_expired_notified, log_payment, has_feedback, update_project_welcome_message
from analytics import log_project_created, log_form_created

from aiogram.fsm.context import FSMContext
from settings_states import SettingsStates
from settings_business import process_business_file_with_deepseek, clean_markdown, clean_business_text, get_text_from_message
from settings_utils import handle_command_in_state, log_fsm_state, auto_register_handlers
from settings_feedback import handle_feedback_command, handle_feedback_text, handle_feedback_rating_callback, handle_feedback_change_rating
from settings_payment import handle_pay_command, handle_pay_callback, handle_payment_check, handle_payment_check_document, handle_payment_check_document_any, handle_payment_check_photo_any
from settings_middleware import trial_middleware
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import traceback
import time
import datetime
import asyncio
import pandas as pd
import io
import httpx
from aiogram.filters import StateFilter
from settings_forms import settings_forms_router
from settings_states import ExtendedSettingsStates
import settings_forms
from database import get_payments

router = APIRouter()

SETTINGS_WEBHOOK_PATH = "/webhook/settings"
SETTINGS_WEBHOOK_URL = f"{SERVER_URL}{SETTINGS_WEBHOOK_PATH}"

settings_bot = Bot(token=SETTINGS_BOT_TOKEN)
settings_storage = MemoryStorage()
settings_router = Router()

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info("[BOOT] Вкладываю settings_forms_router в settings_router...")
settings_router.include_router(settings_forms_router)

# --- Автоматическая регистрация хэндлеров ---
auto_register_handlers(settings_forms_router, settings_forms)

settings_dp = Dispatcher(storage=settings_storage)
settings_dp.include_router(settings_router)

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
            
            # Отправляем уведомление пользователю
            try:
                pay_kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="💸 Оплатить", callback_data="pay")],
                        [InlineKeyboardButton(text="💀 Удалить проекты", callback_data="delete_trial_projects")]
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
            # Определяем правильную сумму для следующего платежа
            from config import PAYMENT_AMOUNT
            from database import get_payments
            
            payments = await get_payments()
            user_payments = [p for p in payments if str(p['telegram_id']) == telegram_id and p['status'] == 'confirmed']
            
            # Для продления подписки всегда используем полную сумму
            payment_amount = PAYMENT_AMOUNT
            
            pay_kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💸 Оплатить", callback_data="pay")]
                ]
            )
            
            message_text = f"Первый оплаченный месяц завершён!\n\nДля продолжения работы оплатите {payment_amount} рублей."
            
            await settings_bot.send_message(
                telegram_id,
                message_text,
                reply_markup=pay_kb
            )
            logging.info(f"[PAID_MONTH] Пользователь {telegram_id} — первый оплаченный месяц истёк, уведомление отправлено с суммой {payment_amount}")
        except Exception as e:
            logging.error(f"[PAID_MONTH] Ошибка при отправке уведомления: {e}")

scheduler.add_job(check_expired_trials, 'interval', minutes=1)
scheduler.add_job(check_expired_paid_month, 'interval', hours=1)
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
        
        # Учитываем бонусные дни
        bonus_days = user.get('bonus_days', 0)
        effective_trial_days = TRIAL_DAYS + bonus_days
        logger.info(f"[TRIAL_MW] TRIAL_DAYS: {TRIAL_DAYS}, bonus_days: {bonus_days}, effective_trial_days: {effective_trial_days}, paid: {user['paid']}")
        
        if diff_days >= effective_trial_days:
            logger.info(f"[TRIAL_MW] TRIAL EXPIRED: diff_days >= effective_trial_days")
            # Показываем меню оплаты/удаления
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="💸 Оплатить", callback_data="pay_trial")],
                    [InlineKeyboardButton(text="💀 Удалить проекты", callback_data="delete_trial_projects")]
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
                logging.info(f"[REFERRAL][START] Пользователь {telegram_id} стартует по реферальной ссылке от {referrer_id}")
        try:
            user = await get_user_by_id(telegram_id)
            logging.info(f"[REFERRAL][START] get_user_by_id({telegram_id}) вернул: {user}")
        except Exception as user_error:
            logging.error(f"[START] _start_inner: ❌ ОШИБКА при получении пользователя: {user_error}")
            raise user_error
        if not user:
            try:
                await create_user(str(message.from_user.id), referrer_id)
                logging.info(f"[REFERRAL][START] create_user({telegram_id}, referrer_id={referrer_id}) вызван")
                user = await get_user_by_id(telegram_id)
                logging.info(f"[REFERRAL][START] после create_user get_user_by_id({telegram_id}) вернул: {user}")
                if referrer_id:
                    logging.info(f"[REFERRAL][START] пользователь {telegram_id} создан с реферером {referrer_id}")
            except Exception as create_error:
                logging.error(f"[START] _start_inner: ❌ ОШИБКА при создании пользователя: {create_error}")
                raise create_error
        elif referrer_id and not user.get('referrer_id'):
            # Если пользователь уже существует, но пришел по реферальной ссылке и у него нет реферера
            try:
                from database import update_user_referrer
                await update_user_referrer(telegram_id, referrer_id)
                logging.info(f"[REFERRAL][START] пользователю {telegram_id} добавлен реферер {referrer_id} через update_user_referrer")
                user = await get_user_by_id(telegram_id)
                logging.info(f"[REFERRAL][START] после update_user_referrer get_user_by_id({telegram_id}) вернул: {user}")
            except Exception as referrer_error:
                logging.error(f"[START] _start_inner: ❌ ОШИБКА при добавлении реферера: {referrer_error}")
                raise referrer_error
        
        # Получаем количество оставшихся дней
        days_text = await get_days_left_text(telegram_id)
        
        # Показываем приветствие и главное меню
        welcome_text = f"""{days_text}Добро пожаловать в AI-бот для бизнеса!

Здесь вы можете:
• 🏔️ Управлять проектами и создавать новые
• 💸 Оплачивать подписку и продлевать доступ
• 🏄‍♂️ Участвовать в реферальной программе

Доступные функции для ВАС:
• Создание Ai-ботов для бизнеса, отвечающих 24 часа в сутки 
• Настройка ответов на основе бизнес-данных
• Автоматический сбор заявок от клиентов через Ai-формы с последующей выгрузкой в Excel-таблицу

Выберите действие из меню ниже:"""
        
        try:
            await message.bot.send_chat_action(message.chat.id, "typing")
            logging.info(f"[START] _start_inner: ✅ отправлен typing action для пользователя {telegram_id}")
        except Exception as typing_error:
            logging.error(f"[START] _start_inner: ❌ ОШИБКА при отправке typing action: {typing_error}")
        
        try:
            # Динамически строим меню
            start_menu_keyboard = await build_start_menu_keyboard(str(message.from_user.id))
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
                [InlineKeyboardButton(text="💸 Оплатить", callback_data="pay_trial")],
                [InlineKeyboardButton(text="🏔️ Проекты", callback_data="projects_menu")]
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
        reply_markup=await build_main_menu(str(message.from_user.id))
    )
    await state.set_state(SettingsStates.waiting_for_project_name)

@settings_router.message(Command("projects"))
async def projects_with_trial_middleware(message: types.Message, state: FSMContext):
    await trial_middleware(message, state, handle_projects_command)

# Обработчики кнопок главного меню
@settings_router.message(lambda message: message.text == "🏔️ Проекты")
async def handle_projects_button(message: types.Message, state: FSMContext):
    telegram_id = str(message.from_user.id)
    logging.info(f"[BUTTON] handle_projects_button: пользователь {telegram_id} нажал кнопку 'Проекты'")
    try:
        await handle_projects_command(message, state, telegram_id=telegram_id)
        logging.info(f"[BUTTON] handle_projects_button: ✅ обработка завершена для пользователя {telegram_id}")
    except Exception as e:
        logging.error(f"[BUTTON] handle_projects_button: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
        raise

@settings_router.message(lambda message: message.text == "💎 Создать проект")
async def handle_new_project_button(message: types.Message, state: FSMContext):
    """Обработчик кнопки 'Создать проект'"""
    telegram_id = str(message.from_user.id)
    logging.info(f"[BUTTON] handle_new_project_button: пользователь {telegram_id} нажал кнопку 'Создать проект'")
    try:
        await handle_new_project(message, state)
        logging.info(f"[BUTTON] handle_new_project_button: ✅ обработка завершена для пользователя {telegram_id}")
    except Exception as e:
        logging.error(f"[BUTTON] handle_new_project_button: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
        raise

@settings_router.message(lambda message: message.text == "💸 Оплатить")
async def handle_payment_button(message: types.Message, state: FSMContext):
    """Обработчик кнопки 'Оплата'"""
    telegram_id = str(message.from_user.id)
    logging.info(f"[BUTTON] handle_payment_button: пользователь {telegram_id} нажал кнопку 'Оплатить'")
    try:
        await handle_pay_command(message, state)
        logging.info(f"[BUTTON] handle_payment_button: ✅ обработка завершена для пользователя {telegram_id}")
    except Exception as e:
        logging.error(f"[BUTTON] handle_payment_button: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
        raise

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

@settings_router.message(lambda message: message.text == "🏄‍♂️ Реферальная программа")
async def handle_referral_button(message: types.Message, state: FSMContext):
    """Обработчик кнопки 'Реферальная программа'"""
    telegram_id = str(message.from_user.id)
    logging.info(f"[BUTTON] handle_referral_button: пользователь {telegram_id} нажал кнопку 'Реферальная программа'")
    try:
        await handle_referral_command(message, state)
        logging.info(f"[BUTTON] handle_referral_button: ✅ обработка завершена для пользователя {telegram_id}")
    except Exception as e:
        logging.error(f"[BUTTON] handle_referral_button: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
        raise

@settings_router.message(lambda message: message.text == "💍 Оставить отзыв")
async def handle_feedback_button(message: types.Message, state: FSMContext):
    """Обработчик кнопки 'Оставить отзыв'"""
    telegram_id = str(message.from_user.id)
    logging.info(f"[BUTTON] handle_feedback_button: пользователь {telegram_id} нажал кнопку 'Оставить отзыв'")
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
    telegram_id = str(callback_query.from_user.id)
    logging.info(f"[INLINE] handle_start_projects: пользователь {telegram_id} нажал inline-кнопку '🏔️ Проекты'")
    await callback_query.answer()
    async def process():
        try:
            await handle_projects_command(callback_query.message, state, telegram_id=telegram_id)
            logging.info(f"[INLINE] handle_start_projects: ✅ обработка завершена для пользователя {telegram_id}")
        except Exception as e:
            logging.error(f"[INLINE] handle_start_projects: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
            await callback_query.answer("Произошла ошибка при получении проектов")
    asyncio.create_task(process())

@settings_router.callback_query(lambda c: c.data == "start_new_project")
async def handle_start_new_project(callback_query: types.CallbackQuery, state: FSMContext):
    telegram_id = str(callback_query.from_user.id)
    logging.info(f"[INLINE] handle_start_new_project: пользователь {telegram_id} нажал inline-кнопку 'Создать проект'")
    await callback_query.answer()
    async def process():
        try:
            await handle_new_project(callback_query.message, state)
            logging.info(f"[INLINE] handle_start_new_project: ✅ обработка завершена для пользователя {telegram_id}")
        except Exception as e:
            logging.error(f"[INLINE] handle_start_new_project: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
            await callback_query.answer("Произошла ошибка при создании проекта")
    asyncio.create_task(process())

@settings_router.callback_query(lambda c: c.data == "start_payment")
async def handle_start_payment(callback_query: types.CallbackQuery, state: FSMContext):
    telegram_id = str(callback_query.from_user.id)
    logging.info(f"[INLINE] handle_start_payment: пользователь {telegram_id} нажал inline-кнопку 'Оплатить'")
    await callback_query.answer()
    async def process():
        try:
            await handle_pay_command(callback_query.message, state)
            logging.info(f"[INLINE] handle_start_payment: ✅ обработка завершена для пользователя {telegram_id}")
        except Exception as e:
            logging.error(f"[INLINE] handle_start_payment: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
            await callback_query.answer("Произошла ошибка при обработке оплаты")
    asyncio.create_task(process())

@settings_router.callback_query(lambda c: c.data == "start_help")
async def handle_start_help(callback_query: types.CallbackQuery, state: FSMContext):
    telegram_id = str(callback_query.from_user.id)
    logging.info(f"[INLINE] handle_start_help: пользователь {telegram_id} нажал inline-кнопку '❓ Помощь'")
    await callback_query.answer()
    async def process():
        try:
            await handle_help_command(callback_query.message, state)
            logging.info(f"[INLINE] handle_start_help: ✅ обработка завершена для пользователя {telegram_id}")
        except Exception as e:
            logging.error(f"[INLINE] handle_start_help: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
            await callback_query.answer("Произошла ошибка при получении справки")
    asyncio.create_task(process())

@settings_router.callback_query(lambda c: c.data == "start_referral")
async def handle_start_referral(callback_query: types.CallbackQuery, state: FSMContext):
    telegram_id = str(callback_query.from_user.id)
    logging.info(f"[INLINE] handle_start_referral: пользователь {telegram_id} нажал inline-кнопку 'Реферальная программа'")
    await callback_query.answer()
    async def process():
        try:
            await handle_referral_command(callback_query.message, state, telegram_id=telegram_id)
            logging.info(f"[INLINE] handle_start_referral: ✅ обработка завершена для пользователя {telegram_id}")
        except Exception as e:
            logging.error(f"[INLINE] handle_start_referral: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
            await callback_query.answer("Произошла ошибка при получении реферальной ссылки")
    asyncio.create_task(process())

@settings_router.callback_query(lambda c: c.data == "start_feedback")
async def handle_start_feedback(callback_query: types.CallbackQuery, state: FSMContext):
    telegram_id = str(callback_query.from_user.id)
    logging.info(f"[INLINE] handle_start_feedback: пользователь {telegram_id} нажал inline-кнопку 'Оставить отзыв'")
    await callback_query.answer()
    async def process():
        try:
            from settings_feedback import handle_feedback_command
            await handle_feedback_command(callback_query.message, state)
            logging.info(f"[INLINE] handle_start_feedback: ✅ обработка завершена для пользователя {telegram_id}")
        except Exception as e:
            logging.error(f"[INLINE] handle_start_feedback: ❌ ОШИБКА для пользователя {telegram_id}: {e}")
            await callback_query.answer("Произошла ошибка при отправке отзыва")
    asyncio.create_task(process())

async def handle_pay_command(message: types.Message, state: FSMContext):
    """Обработчик команды оплаты"""
    from database import get_payments
    from config import DISCOUNT_PAYMENT_AMOUNT, PAYMENT_AMOUNT
    
    telegram_id = str(message.from_user.id)
    logging.info(f"[PAYMENT-DEBUG] handle_pay_command: telegram_id from message = {telegram_id}")
    payments = await get_payments()
    logging.info(f"[PAYMENT-DEBUG] handle_pay_command: all payments count = {len(payments)}")
    all_user_payments = [p for p in payments if str(p['telegram_id']) == telegram_id]
    logging.info(f"[PAYMENT-DEBUG] handle_pay_command: user payments for {telegram_id}: {all_user_payments}")
    confirmed_payments = [p for p in all_user_payments if p['status'] == 'confirmed']
    logging.info(f"[PAYMENT-DEBUG] handle_pay_command: confirmed payments for {telegram_id}: {confirmed_payments}")
    card = random.choice([PAYMENT_CARD_NUMBER1, PAYMENT_CARD_NUMBER2, PAYMENT_CARD_NUMBER3])
    logging.info(f"[PAYMENT] Пользователь {telegram_id}: всего платежей={len(all_user_payments)}, подтверждённых={len(confirmed_payments)}")
    if len(confirmed_payments) == 0:
        payment_text = f"💳 **Оплата подписки**\n\nДля оплаты переведите {DISCOUNT_PAYMENT_AMOUNT} рублей на карту:\n`{card}`\n\nПосле оплаты отправьте чек сюда (фото/скриншот)."
        logging.info(f"[PAYMENT] Пользователь {telegram_id}: предлагается сумма {DISCOUNT_PAYMENT_AMOUNT}")
    else:
        payment_text = f"💳 **Продление подписки**\n\nДля продления переведите {PAYMENT_AMOUNT} рублей на карту:\n`{card}`\n\nПосле оплаты отправьте чек сюда (фото/скриншот)."
        logging.info(f"[PAYMENT] Пользователь {telegram_id}: предлагается сумма {PAYMENT_AMOUNT}")
    await message.answer(payment_text, reply_markup=await build_main_menu(str(message.from_user.id)))
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
        # Не сбрасываем состояние! Ожидаем новое имя
        return
    await state.update_data(project_name=message.text)
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
        # Показываем "печатает..." перед обработкой
        await message.bot.send_chat_action(message.chat.id, "typing")
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
    telegram_id = str(message.from_user.id)
    try:
        logger.info("[LOAD] Запись проекта в БД...")
        t3 = time.monotonic()
        project_id = await create_project(telegram_id, project_name, processed_business_info)
        logger.info(f"[LOAD] Запись в БД завершена за {time.monotonic() - t3:.2f} сек")
        # Логируем создание проекта в аналитику
        await log_project_created(telegram_id, project_id, project_name)
    except ValueError as e:
        await message.answer(f"❌ Ошибка: {str(e)}\n\nПожалуйста, выберите другое название для проекта.")
        await state.clear()
        return
    
    # Получаем созданный проект для отображения ссылки
    from database import get_project_by_id
    project = await get_project_by_id(project_id)
    
    logger.info(f"[LOAD] ВСЕГО времени на загрузку: {time.monotonic() - t0:.2f} сек")
    
    if project:
        await message.answer(
            f"🎉 Проект успешно создан!\n\n"
            f"📋 Название: {project_name}\n"
            f"🔗 Ссылка на бота: {project['bot_link']}\n\n"
            f"📝 Отправьте эту ссылку вашим клиентам, чтобы они могли общаться с ботом от имени вашего бизнеса.\n\n"
        )
    else:
        await message.answer("❌ Проект создан, но произошла ошибка при получении ссылки.")
    
    await state.clear()

@settings_router.message(Command("projects"))
async def handle_projects_command(message: types.Message, state: FSMContext, telegram_id: str = None):
    logger = logging.getLogger(__name__)
    logger.info(f"/projects received from user {message.from_user.id}")
    # Always use the correct telegram_id
    if telegram_id is None:
        telegram_id = str(message.from_user.id)
    logger.info(f"handle_projects_command: telegram_id={telegram_id}")
    # Reset state for project selection
    await state.update_data(telegram_id=telegram_id)
    await state.update_data(selected_project_id=None, selected_project=None)
    # Log current state for diagnostics
    data = await state.get_data()
    logger.info(f"handle_projects_command: FSM state data before fetching projects: {data}")
    try:
        projects = await get_projects_by_user(telegram_id)
        logger.info(f"handle_projects_command: found {len(projects)} projects for user {telegram_id}")
        if not projects:
            await message.answer("У вас пока нет проектов. Создайте первый проект командой /new", reply_markup=await build_main_menu(telegram_id))
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
            await message.answer("Выберите проект для управления:", reply_markup=await build_main_menu(telegram_id))
            await message.answer("Список проектов:", reply_markup=keyboard)
        else:
            await message.answer("Нет доступных проектов.", reply_markup=await build_main_menu(telegram_id))
    except Exception as e:
        logger.error(f"Error in handle_projects_command: {e}")
        await message.answer("Произошла ошибка при получении списка проектов", reply_markup=await build_main_menu(telegram_id))

@settings_router.callback_query(lambda c: c.data.startswith('project_'))
async def handle_project_selection(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    async def process():
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
            # --- Исправление: инициализация buttons ---
            buttons = []
            # Добавляем кнопку формы в зависимости от наличия формы
            if form:
                buttons.append([types.InlineKeyboardButton(text="Работа с формой", callback_data="manage_form")])
                # Добавляем кнопку экспорта заявок
                buttons.append([types.InlineKeyboardButton(text="Экспорт заявок", callback_data="export_form_submissions")])
            else:
                buttons.append([types.InlineKeyboardButton(text="Создать форму", callback_data="create_form")])
            # Меню управления проектом
            buttons += [
                [types.InlineKeyboardButton(text="Показать данные", callback_data="show_data")],
                [
                    types.InlineKeyboardButton(text="Добавить данные", callback_data="add_data"),
                    types.InlineKeyboardButton(text="Переименовать проект", callback_data="rename_project"),
                ],
                [
                    types.InlineKeyboardButton(text="Изменить данные", callback_data="change_data"),
                    types.InlineKeyboardButton(text="Удалить проект", callback_data="delete_project")
                ],
            ]
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
            await callback_query.message.edit_text(
                f"Проект: {project.get('project_name', 'Неизвестный')}\n\nВыберите действие:",
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Error in handle_project_selection: {e}")
            await callback_query.answer("Произошла ошибка")
    asyncio.create_task(process())

@settings_router.callback_query(lambda c: c.data == "back_to_projects")
async def handle_back_to_projects(callback_query: types.CallbackQuery, state: FSMContext):
    """Возвращает к списку проектов для настройки"""
    try:
        await state.clear()
        await settings_command(callback_query.message, state)
    except Exception as e:
        logging.error(f"[SETTINGS] Error in handle_back_to_projects: {e}")
        await callback_query.answer("❌ Произошла ошибка")

@settings_router.callback_query(lambda c: c.data == "rename_project")
async def handle_rename_project(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    async def process():
        logging.info(f"[BOT] handle_rename_project: user={callback_query.from_user.id}")
        await callback_query.message.edit_text("Введите новое название проекта:")
        await state.set_state(SettingsStates.waiting_for_new_project_name)
    asyncio.create_task(process())

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
    await callback_query.answer()
    async def process():
        logging.info(f"[BOT] handle_add_data: user={callback_query.from_user.id}")
        await callback_query.message.edit_text(
            "Отправьте дополнительные данные о бизнесе одним из способов:\n"
            "1️⃣ Загрузите файл (txt, docx, pdf)\n"
            "2️⃣ Просто отправьте текст сообщением\n"
            "3️⃣ Или отправьте голосовое сообщение (мы преобразуем его в текст)"
        )
        await state.set_state(SettingsStates.waiting_for_additional_data_file)
    asyncio.create_task(process())

@settings_router.callback_query(lambda c: c.data == "create_form")
async def handle_create_form(callback_query: types.CallbackQuery, state: FSMContext):
    """Обрабатывает создание формы"""
    await callback_query.answer()
    async def process():
        logging.info(f"[BOT] handle_create_form: user={callback_query.from_user.id}")
        try:
            data = await state.get_data()
            project_id = data.get("selected_project_id")
            
            if not project_id:
                await callback_query.message.edit_text("❌ Ошибка: проект не выбран")
                return
            
            # Переходим к созданию формы
            await callback_query.message.edit_text(
                "📝 **Создание формы**\n\n"
                "Введите название для новой формы:",
                parse_mode="Markdown"
            )
            await state.set_state(SettingsStates.waiting_for_form_name)
            
        except Exception as e:
            logging.error(f"[BOT] Error in handle_create_form: {e}")
            await callback_query.message.edit_text("❌ Произошла ошибка при создании формы")
    asyncio.create_task(process())

@settings_router.message(SettingsStates.waiting_for_form_name)
async def handle_form_name(message: types.Message, state: FSMContext):
    """Обрабатывает название формы"""
    await log_fsm_state(message, state)
    logging.info(f"[BOT] waiting_for_form_name: user={message.from_user.id}, text={message.text}")
    
    if await handle_command_in_state(message, state):
        return
    
    try:
        data = await state.get_data()
        project_id = data.get("selected_project_id")
        
        if not project_id:
            await message.answer("❌ Ошибка: проект не выбран")
            await state.clear()
            return
        
        # Создаем форму
        from database import create_form
        form_id = await create_form(project_id, message.text)
        
        if form_id:
            await message.answer(
                f"✅ Форма '{message.text}' успешно создана!\n\n"
                "Теперь добавьте поля в форму, используя команду:\n"
                f"/add_field {form_id} название_поля тип_поля [обязательное]"
            )
        else:
            await message.answer("❌ Ошибка при создании формы")
        
        await state.clear()
        
    except Exception as e:
        logging.error(f"[BOT] Error in handle_form_name: {e}")
        await message.answer("❌ Произошла ошибка при создании формы")
        await state.clear()

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
        f"Вы уверены, что хотите удалить проект '{project.get('project_name', 'Неизвестный')}'?\n"
        "Это действие нельзя отменить. Бот будет остановлен и webhook отключен.",
        reply_markup=keyboard
    )

@settings_router.callback_query(lambda c: c.data == "cancel_delete")
async def handle_cancel_delete(callback_query: types.CallbackQuery, state: FSMContext):
    logging.info(f"[BOT] handle_cancel_delete: user={callback_query.from_user.id}")
    """Отменяет удаление проекта и возвращает к списку проектов"""
    telegram_id = str(callback_query.from_user.id)
    await handle_projects_command(callback_query.message, state, telegram_id=telegram_id)
    await callback_query.answer()

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
        
        # Удаляем проект из базы данных
        delete_result = await delete_project(project_id)
        
        if delete_result:
            await callback_query.message.edit_text(
                f"Проект '{project.get('project_name', 'Неизвестный')}' успешно удален!\n"
                "Бот больше не будет отвечать от имени этого проекта."
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
    business_info: str = Form(...)
):
    logs = []
    try:
        project_id = await create_project(telegram_id, project_name, business_info)
        logs.append(f"[STEP] Проект создан: {project_id}")
        
        # Получаем созданный проект для возврата ссылки
        from database import get_project_by_id
        project = await get_project_by_id(project_id)
        
        if project:
            logs.append(f"[STEP] Проект получен, bot_link: {project['bot_link']}")
            return {
                "status": "ok", 
                "project_id": project_id, 
                "bot_link": project['bot_link'],
                "logs": logs
            }
        else:
            logs.append(f"[ERROR] Не удалось получить созданный проект")
            return {"status": "error", "message": "Проект создан, но не получен", "logs": logs}
            
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
    from database import get_payments
    from config import DISCOUNT_PAYMENT_AMOUNT, PAYMENT_AMOUNT
    telegram_id = str(callback_query.from_user.id)
    payments = await get_payments()
    all_user_payments = [p for p in payments if str(p['telegram_id']) == telegram_id]
    confirmed_payments = [p for p in all_user_payments if p['status'] == 'confirmed']
    card = random.choice([PAYMENT_CARD_NUMBER1, PAYMENT_CARD_NUMBER2, PAYMENT_CARD_NUMBER3])
    logging.info(f"[PAYMENT] Пользователь {telegram_id}: всего платежей={len(all_user_payments)}, подтверждённых={len(confirmed_payments)} (pay_trial)")
    if len(confirmed_payments) == 0:
        await callback_query.message.answer(
            f"Для оплаты переведите {DISCOUNT_PAYMENT_AMOUNT} рублей на карту: {card}\n\nПосле оплаты отправьте чек сюда (фото/скриншот)."
        )
        logging.info(f"[PAYMENT] Пользователь {telegram_id}: предлагается сумма {DISCOUNT_PAYMENT_AMOUNT} (pay_trial)")
    else:
        await callback_query.message.answer(
            f"Для продления подписки переведите {PAYMENT_AMOUNT} рублей на карту: {card}\n\nПосле оплаты отправьте чек сюда (фото/скриншот)."
        )
        logging.info(f"[PAYMENT] Пользователь {telegram_id}: предлагается сумма {PAYMENT_AMOUNT} (pay_trial)")
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

@settings_router.message(Command("referral"))
async def referral_command(message: types.Message, state: FSMContext):
    await handle_referral_command(message, state)

@settings_router.callback_query(lambda c: c.data == "referral")
async def referral_callback(callback_query: types.CallbackQuery, state: FSMContext):
    await handle_referral_command(callback_query.message, state)
    await callback_query.answer()

async def handle_referral_command(message, state, telegram_id=None):
    if telegram_id is None:
        telegram_id = str(message.from_user.id)
    logging.info(f"[REFERRAL] handle_referral_command: пользователь {telegram_id} запросил реферальную ссылку")
    from database import get_referral_link, get_user_by_id
    user = await get_user_by_id(telegram_id)
    logging.info(f"[REFERRAL] handle_referral_command: get_user_by_id({telegram_id}) вернул: {user}")
    if not user:
        logging.warning(f"[REFERRAL] handle_referral_command: пользователь {telegram_id} не найден в базе. Требуется /start")
        await message.answer("Сначала создайте аккаунт командой /start")
        return
    logging.info(f"[REFERRAL] handle_referral_command: referrer_id={user.get('referrer_id')}")
    referral_link = await get_referral_link(telegram_id)
    referral_text = f"""
🏄‍♂️ Ваша реферальная ссылка:\n\n{referral_link}\n\n❤ Как это работает:\n• Отправьте эту ссылку друзьям\n• Когда они зарегистрируются и оплатят подписку\n• Вы получите +10 дней к пользованию за каждого реферала\n\n👏 Просто скопируйте ссылку и поделитесь с друзьями!\n    """
    await message.answer(referral_text)

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
            
            await message.answer(f"Пользователь {paid_telegram_id} отмечен как оплативший. Проекты снова активны.")
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

async def handle_settings_start(message: types.Message, state: FSMContext):
    logger = logging.getLogger(__name__)
    logger.info(f"/start received from user {message.from_user.id}")
    try:
        await state.clear()
        referrer_id = None
        if message.text and message.text.startswith('/start'):
            parts = message.text.split()
            if len(parts) > 1 and parts[1].startswith('ref'):
                referrer_id = parts[1][3:]
                logger.info(f"[REFERRAL] handle_settings_start: пользователь {message.from_user.id} пришел по реферальной ссылке от {referrer_id}")
        await create_user(str(message.from_user.id), referrer_id)
        # --- Новое: строка с днями ---
        days_text = await get_days_left_text(str(message.from_user.id))
        main_menu = await build_main_menu(str(message.from_user.id))
        await message.answer(days_text + "Добро пожаловать в настройки! Введите имя вашего проекта.", reply_markup=main_menu)
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

🏄‍♂️ **Реферальная программа:**
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
            [InlineKeyboardButton(text="💸 Оплатить", callback_data="pay")],
            [InlineKeyboardButton(text="🏄‍♂️ Реферальная ссылка", callback_data="referral")]
        ]
    )
    await message.bot.send_chat_action(message.chat.id, "typing")
    await message.answer(help_text, reply_markup=pay_kb)

async def handle_projects_command(message: types.Message, state: FSMContext, telegram_id: str = None):
    logger = logging.getLogger(__name__)
    logger.info(f"/projects received from user {message.from_user.id}")
    # Always use the correct telegram_id
    if telegram_id is None:
        telegram_id = str(message.from_user.id)
    logger.info(f"handle_projects_command: telegram_id={telegram_id}")
    # Reset state for project selection
    await state.update_data(telegram_id=telegram_id)
    await state.update_data(selected_project_id=None, selected_project=None)
    # Log current state for diagnostics
    data = await state.get_data()
    logger.info(f"handle_projects_command: FSM state data before fetching projects: {data}")
    try:
        projects = await get_projects_by_user(telegram_id)
        logger.info(f"handle_projects_command: found {len(projects)} projects for user {telegram_id}")
        if not projects:
            await message.answer("У вас пока нет проектов. Создайте первый проект командой /new", reply_markup=await build_main_menu(telegram_id))
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
            await message.answer("Выберите проект для управления:", reply_markup=await build_main_menu(telegram_id))
            await message.answer("Список проектов:", reply_markup=keyboard)
        else:
            await message.answer("Нет доступных проектов.", reply_markup=await build_main_menu(telegram_id))
    except Exception as e:
        logger.error(f"Error in handle_projects_command: {e}")
        await message.answer("Произошла ошибка при получении списка проектов", reply_markup=await build_main_menu(telegram_id))

@settings_router.callback_query(lambda c: c.data == "pay_subscription")
async def handle_pay_subscription(callback_query: types.CallbackQuery, state: FSMContext):
    from config import DISCOUNT_PAYMENT_AMOUNT, PAYMENT_AMOUNT
    telegram_id = str(callback_query.from_user.id)
    payments = await get_payments()
    all_user_payments = [p for p in payments if str(p['telegram_id']) == telegram_id]
    confirmed_payments = [p for p in all_user_payments if p['status'] == 'confirmed']
    card = random.choice([PAYMENT_CARD_NUMBER1, PAYMENT_CARD_NUMBER2, PAYMENT_CARD_NUMBER3])
    logging.info(f"[PAYMENT] Пользователь {telegram_id}: всего платежей={len(all_user_payments)}, подтверждённых={len(confirmed_payments)} (pay_subscription)")
    if len(confirmed_payments) == 0:
        await callback_query.message.answer(
            f"Для оплаты переведите {DISCOUNT_PAYMENT_AMOUNT} рублей на карту: {card}\n\nПосле оплаты отправьте чек сюда (фото/скриншот)."
        )
        logging.info(f"[PAYMENT] Пользователь {telegram_id}: предлагается сумма {DISCOUNT_PAYMENT_AMOUNT} (pay_subscription)")
    else:
        await callback_query.message.answer(
            f"Для продления подписки переведите {PAYMENT_AMOUNT} рублей на карту: {card}\n\nПосле оплаты отправьте чек сюда (фото/скриншот)."
        )
        logging.info(f"[PAYMENT] Пользователь {telegram_id}: предлагается сумма {PAYMENT_AMOUNT} (pay_subscription)")
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

async def get_days_left_text(telegram_id: str) -> str:
    logging.info(f"[DAYS_LEFT] get_days_left_text: called for telegram_id={telegram_id}")
    user = await get_user_by_id(telegram_id)
    logging.info(f"[DAYS_LEFT] get_days_left_text: user from DB: {user}")
    if not user:
        logging.info(f"[DAYS_LEFT] get_days_left_text: user not found, returning empty string")
        return ""
    if user.get("paid"):
        payments = await get_payments()
        confirmed = [p for p in payments if str(p['telegram_id']) == telegram_id and p['status'] == 'confirmed']
        logging.info(f"[DAYS_LEFT] get_days_left_text: confirmed payments: {confirmed}")
        if confirmed:
            last_paid = max(confirmed, key=lambda p: p['paid_at'])
            from datetime import datetime, timezone
            paid_at = last_paid['paid_at']
            logging.info(f"[DAYS_LEFT] get_days_left_text: paid_at raw: {paid_at} (type: {type(paid_at)})")
            if isinstance(paid_at, str):
                from dateutil.parser import parse
                paid_at = parse(paid_at)
                logging.info(f"[DAYS_LEFT] get_days_left_text: paid_at parsed: {paid_at} (type: {type(paid_at)})")
            now = datetime.now(timezone.utc)
            days_left = 30 - (now - paid_at).days
            logging.info(f"[DAYS_LEFT] get_days_left_text: now={now}, days_left={days_left}")
            if days_left < 0:
                days_left = 0
            result = f"До конца оплаченного периода: {days_left} дней.\n"
            logging.info(f"[DAYS_LEFT] get_days_left_text: result='{result}'")
            return result
        else:
            logging.info(f"[DAYS_LEFT] get_days_left_text: подписка активна, но нет подтверждённых платежей")
            return "Подписка активна.\n"
    else:
        start_date = user.get("start_date")
        logging.info(f"[DAYS_LEFT] get_days_left_text: start_date raw: {start_date} (type: {type(start_date)})")
        if isinstance(start_date, str):
            from dateutil.parser import parse
            start_date = parse(start_date)
            logging.info(f"[DAYS_LEFT] get_days_left_text: start_date parsed: {start_date} (type: {type(start_date)})")
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        bonus_days = user.get('bonus_days', 0) or 0
        effective_trial_days = TRIAL_DAYS + bonus_days
        # Привести start_date к tz-aware (UTC), если нужно
        try:
            if start_date.tzinfo is None:
                start_date = start_date.replace(tzinfo=timezone.utc)
            days_left = effective_trial_days - (now - start_date).days
        except TypeError as e:
            logging.error(f"[DAYS_LEFT][ERROR] TypeError при вычислении дней: now={now} (tzinfo={now.tzinfo}), start_date={start_date} (tzinfo={getattr(start_date, 'tzinfo', None)}), effective_trial_days={effective_trial_days}, ошибка: {e}")
            raise
        logging.info(f"[DAYS_LEFT] get_days_left_text: now={now}, effective_trial_days={effective_trial_days}, days_left={days_left}")
        if days_left < 0:
            days_left = 0
        result = f"До конца пробного периода: {days_left} дней.\n"
        logging.info(f"[DAYS_LEFT] get_days_left_text: result='{result}'")
        return result

async def build_start_menu_keyboard(telegram_id: str):
    """Динамически строит клавиатуру главного меню с учетом наличия отзыва"""
    buttons = [
        [InlineKeyboardButton(text="💎 Создать проект", callback_data="start_new_project"),
         InlineKeyboardButton(text="🏔️ Проекты", callback_data="start_projects")],
    ]
    if not await has_feedback(telegram_id):
        buttons.append([
            InlineKeyboardButton(text="💍 Оставить отзыв", callback_data="start_feedback")
        ])
    buttons.append([
        InlineKeyboardButton(text="🏄‍♂️ Реферальная программа", callback_data="start_referral")
    ])
    buttons.append([
        InlineKeyboardButton(text="💸 Оплатить", callback_data="start_payment")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def build_main_menu(telegram_id: str):
    """Динамически строит ReplyKeyboardMarkup для главного меню"""
    keyboard = [
        [KeyboardButton(text="💎 Создать проект"), KeyboardButton(text="🏔️ Проекты")],
    ]
    if not await has_feedback(telegram_id):
        keyboard.append([KeyboardButton(text="💍 Оставить отзыв")])
    keyboard.append([KeyboardButton(text="🏄‍♂️ Реферальная программа")])
    keyboard.append([KeyboardButton(text="💸 Оплатить")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, one_time_keyboard=False)

@settings_router.message()
async def handle_any_message(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    logging.info(f"[DEBUG] handle_any_message: user={message.from_user.id}, state={current_state}, text={message.text}")
    await trial_middleware(message, state, _handle_any_message_inner)

@settings_router.callback_query(lambda c: c.data == "export_form_submissions")
async def handle_export_form_submissions(callback_query: types.CallbackQuery, state: FSMContext):
    import pandas as pd
    import io
    from database import get_project_form, get_form_submissions
    await callback_query.answer()
    data = await state.get_data()
    project_id = data.get("selected_project_id")
    if not project_id:
        await callback_query.message.answer("Ошибка: проект не выбран")
        return
    form = await get_project_form(project_id)
    if not form:
        await callback_query.message.answer("У проекта нет формы для экспорта заявок.")
        return
    submissions = await get_form_submissions(form["id"])
    if not submissions:
        await callback_query.message.answer("Нет заявок для экспорта.")
        return
    # Собираем данные для DataFrame
    rows = []
    for sub in submissions:
        row = {"telegram_id": sub["telegram_id"], "submitted_at": sub["submitted_at"]}
        row.update(sub["data"])
        rows.append(row)
    df = pd.DataFrame(rows)
    # Сохраняем в Excel в память
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Submissions")
    output.seek(0)
    await callback_query.message.answer_document(
        types.InputFile(output, filename="form_submissions.xlsx"),
        caption="Экспорт заявок из формы"
    )

@settings_router.callback_query(lambda c: c.data == "back_to_projects")
async def handle_back_to_projects(callback_query: types.CallbackQuery, state: FSMContext):
    """Возвращает к списку проектов для настройки"""
    try:
        await state.clear()
        await settings_command(callback_query.message, state)
    except Exception as e:
        logging.error(f"[SETTINGS] Error in handle_back_to_projects: {e}")
        await callback_query.answer("❌ Произошла ошибка")

@settings_router.callback_query()
async def handle_any_callback_query(callback_query: types.CallbackQuery, state: FSMContext):
    logging.warning(f"[CALLBACK][CATCH-ALL] Пользователь {callback_query.from_user.id} нажал callback: {callback_query.data}")
    await callback_query.answer("Неизвестная кнопка или действие. Пожалуйста, попробуйте ещё раз.", show_alert=True)

@settings_router.message(Command("settings"))
async def settings_command(message: types.Message, state: FSMContext):
    """Показывает настройки проекта"""
    try:
        # Получаем проекты пользователя
        projects = await get_projects_by_user(str(message.from_user.id))
        
        if not projects:
            await message.answer("❌ У вас пока нет проектов. Создайте проект командой /create")
            return
        
        # Создаем клавиатуру с проектами для настройки
        keyboard = []
        for project in projects:
            keyboard.append([InlineKeyboardButton(
                text=f"⚙️ {project.get('project_name', 'Неизвестный')}",
                callback_data=f"settings_project_{project['id']}"
            )])
        
        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
        await message.answer(
            "⚙️ **Настройки проектов**\n\nВыберите проект для настройки:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logging.error(f"[SETTINGS] Error in settings_command: {e}")
        await message.answer("❌ Произошла ошибка при загрузке настроек. Попробуйте позже.")

@settings_router.callback_query(lambda c: c.data.startswith("settings_project_"))
async def handle_project_settings(callback_query: types.CallbackQuery, state: FSMContext):
    """Обрабатывает выбор проекта для настройки"""
    try:
        project_id = callback_query.data.split("_")[2]
        project = await get_project_by_id(project_id)
        
        if not project:
            await callback_query.answer("❌ Проект не найден")
            return
        
        # Сохраняем ID проекта в состоянии
        await state.update_data(project_id=project_id)
        
        # Показываем текущие настройки проекта
        current_welcome = project.get("welcome_message") or "Не настроено"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить приветствие", callback_data="edit_welcome")],
            [InlineKeyboardButton(text="🔙 Назад к проектам", callback_data="back_to_projects")]
        ])
        
        await callback_query.message.edit_text(
            f"⚙️ **Настройки проекта: {project.get('project_name', 'Неизвестный')}**\n\n"
                          f"🔗 Ссылка: {project.get('bot_link', 'Неизвестно')}\n"
            f"📝 Приветственное сообщение:\n{current_welcome}\n\n"
            f"Выберите, что хотите настроить:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logging.error(f"[SETTINGS] Error in handle_project_settings: {e}")
        await callback_query.answer("❌ Произошла ошибка")

@settings_router.callback_query(lambda c: c.data == "edit_welcome")
async def handle_edit_welcome(callback_query: types.CallbackQuery, state: FSMContext):
    """Обрабатывает редактирование приветственного сообщения"""
    try:
        await state.set_state(SettingsStates.waiting_for_welcome_message)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="cancel_edit")]
        ])
        
        await callback_query.message.edit_text(
            "✏️ **Редактирование приветственного сообщения**\n\n"
            "Отправьте новое приветственное сообщение для вашего бота.\n"
            "Это сообщение будет показываться клиентам при первом запуске.\n\n"
            "💡 Поддерживается Markdown разметка (жирный текст, курсив и т.д.)",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logging.error(f"[SETTINGS] Error in handle_edit_welcome: {e}")
        await callback_query.answer("❌ Произошла ошибка")

@settings_router.message(StateFilter(SettingsStates.waiting_for_welcome_message))
async def handle_welcome_message_input(message: types.Message, state: FSMContext):
    """Обрабатывает ввод нового приветственного сообщения"""
    try:
        # Получаем ID проекта из состояния
        data = await state.get_data()
        project_id = data.get("project_id")
        
        if not project_id:
            await message.answer("❌ Ошибка: проект не найден. Попробуйте снова.")
            await state.clear()
            return
        
        # Обновляем приветственное сообщение в базе
        await update_project_welcome_message(project_id, message.text)
        
        # Получаем обновленный проект
        project = await get_project_by_id(project_id)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Готово", callback_data="welcome_updated")],
            [InlineKeyboardButton(text="🔙 Назад к настройкам", callback_data=f"settings_project_{project_id}")]
        ])
        
        await message.answer(
            "✅ **Приветственное сообщение обновлено!**\n\n"
            f"📝 Новое сообщение:\n{message.text}\n\n"
            f"Теперь клиенты будут видеть это сообщение при запуске бота.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        await state.clear()
        
    except Exception as e:
        logging.error(f"[SETTINGS] Error in handle_welcome_message_input: {e}")
        await message.answer("❌ Произошла ошибка при обновлении сообщения. Попробуйте позже.")
        await state.clear()

@settings_router.callback_query(lambda c: c.data == "cancel_edit")
async def handle_cancel_edit(callback_query: types.CallbackQuery, state: FSMContext):
    """Отменяет редактирование и возвращает к настройкам проекта"""
    try:
        data = await state.get_data()
        project_id = data.get("project_id")
        
        if project_id:
            # Возвращаемся к настройкам проекта
            await handle_project_settings(callback_query, state)
        else:
            await callback_query.answer("Редактирование отменено")
            await state.clear()
            
    except Exception as e:
        logging.error(f"[SETTINGS] Error in handle_cancel_edit: {e}")
        await callback_query.answer("❌ Произошла ошибка")

@settings_router.callback_query(lambda c: c.data == "welcome_updated")
async def handle_welcome_updated(callback_query: types.CallbackQuery, state: FSMContext):
    """Обрабатывает подтверждение обновления приветственного сообщения"""
    try:
        await callback_query.answer("✅ Приветственное сообщение успешно обновлено!")
        
        # Возвращаемся к главному меню
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
        ])
        
        await callback_query.message.edit_text(
            "🎉 **Настройка завершена!**\n\n"
            "Ваше приветственное сообщение успешно обновлено.\n"
            "Клиенты теперь будут видеть новое сообщение при запуске бота.",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logging.error(f"[SETTINGS] Error in handle_welcome_updated: {e}")
        await callback_query.answer("❌ Произошла ошибка")

__all__ = ["router", "settings_router"]