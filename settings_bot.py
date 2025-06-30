from fastapi import APIRouter, Request, Form, UploadFile, File
from aiogram import Bot, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router, Dispatcher
from aiogram.filters import Command
import os
from config import API_URL, SERVER_URL, DEEPSEEK_API_KEY, TRIAL_DAYS, TRIAL_PROJECTS, PAID_PROJECTS, PAYMENT_AMOUNT, PAYMENT_CARD_NUMBER, MAIN_TELEGRAM_ID
from database import create_project, get_project_by_id, create_user, get_projects_by_user, update_project_name, update_project_business_info, append_project_business_info, delete_project, get_project_by_token, check_project_name_exists, get_user_by_id, get_users_with_expired_trial, delete_all_projects_for_user, set_user_paid, get_user_projects, log_message_stat, add_feedback, update_project_token
from utils import set_webhook, delete_webhook
from file_utils import extract_text_from_file, extract_text_from_file_async
import json
import logging
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
import traceback
import httpx
import asyncio
from pydub import AudioSegment
import time
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler

router = APIRouter()

SETTINGS_BOT_TOKEN = os.getenv("SETTINGS_BOT_TOKEN")
SETTINGS_WEBHOOK_PATH = "/webhook/settings"
SETTINGS_WEBHOOK_URL = f"{SERVER_URL}{SETTINGS_WEBHOOK_PATH}"

settings_bot = Bot(token=SETTINGS_BOT_TOKEN)
settings_storage = MemoryStorage()
settings_router = Router()
settings_dp = Dispatcher(storage=settings_storage)
settings_dp.include_router(settings_router)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SettingsStates(StatesGroup):
    waiting_for_project_name = State()
    waiting_for_token = State()
    waiting_for_business_file = State()
    # Новые состояния для управления проектами
    waiting_for_new_project_name = State()
    waiting_for_additional_data_file = State()
    waiting_for_new_data_file = State()
    waiting_for_delete_confirmation = State()
    waiting_for_feedback_text = State()
    waiting_for_new_token = State()  # <--- новое состояние для смены токена

# Встроенное меню команд
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="/start"), KeyboardButton(text="/projects"), KeyboardButton(text="/help")]
    ],
    resize_keyboard=True
)

# --- APScheduler ---
scheduler = AsyncIOScheduler()

async def check_expired_trials():
    users = await get_users_with_expired_trial()
    for user in users:
        telegram_id = user['telegram_id']
        # Удаляем вебхуки на все проекты пользователя (если есть)
        projects = await get_user_projects(telegram_id)
        for project in projects:
            try:
                await delete_webhook(project['token'])
            except Exception as e:
                logger.error(f"[TRIAL] Ошибка при удалении вебхука: {e}")
        # Можно добавить флаг в user FSM или просто полагаться на paid/start_date
        # Отправить пользователю уведомление (если нужно)
        # (В реальном боте — отправка через Telegram API)
        logger.info(f"[TRIAL] Пользователь {telegram_id} — trial истёк, вебхуки удалены")

scheduler.add_job(check_expired_trials, 'interval', hours=1)
scheduler.start()

async def process_business_file_with_deepseek(file_content: str) -> str:
    """Обрабатывает файл с данными о бизнесе через Deepseek для создания компактной информации"""
    try:
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "Ты - эксперт по анализу и сжатию информации. Твоя задача - извлечь из данных ключевую информацию, убрать лишние детали, символы, смайлики и т.д. и представить её в самом компактном виде без потери смысла для использования минимально необходимого количества токенов"},
                {"role": "user", "content": f"Обработай {file_content}"}
            ],
            "temperature": 0.3
        }
        
        # Используем asyncio.create_task для неблокирующего выполнения
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Ошибка при обработке файла через Deepseek: {e}")
        # Возвращаем исходный текст, если обработка не удалась
        return file_content

def clean_markdown(text: str) -> str:
    """Очищает текст от markdown символов"""
    import re
    
    # Удаляем заголовки (###, ##, #)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    
    # Удаляем жирный текст (**текст** или __текст__)
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'__(.*?)__', r'\1', text)
    
    # Удаляем курсив (*текст* или _текст_)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'_(.*?)_', r'\1', text)
    
    # Удаляем зачёркнутый текст (~~текст~~)
    text = re.sub(r'~~(.*?)~~', r'\1', text)
    
    # Удаляем код в бэктиках (`код`)
    text = re.sub(r'`(.*?)`', r'\1', text)
    
    # Удаляем блоки кода (```код```)
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    
    # Удаляем ссылки [текст](url)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    
    # Удаляем изображения ![alt](url)
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', '', text)
    
    # Удаляем списки (-, *, +)
    text = re.sub(r'^[\s]*[-*+]\s+', '', text, flags=re.MULTILINE)
    
    # Удаляем нумерованные списки (1., 2., etc.)
    text = re.sub(r'^[\s]*\d+\.\s+', '', text, flags=re.MULTILINE)
    
    # Удаляем лишние пробелы и переносы строк
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = text.strip()
    
    return text

def clean_business_text(text: str) -> str:
    """Удаляет лишние пробелы, табы, множественные переносы строк и приводит текст к компактному виду для экономии токенов."""
    import re
    text = text.replace('\r', '')
    text = re.sub(r'[ \t]+', ' ', text)  # заменяем несколько пробелов/табов на один пробел
    text = re.sub(r'\n+', '\n', text)   # заменяем несколько переносов на один
    text = text.strip()
    return text

async def clear_asking_bot_cache(token: str):
    """Очищает кэш asking_bot для указанного токена"""
    try:
        # Импортируем функцию очистки из asking_bot
        from asking_bot import clear_dispatcher_cache
        clear_dispatcher_cache(token)
        logger.info(f"Cleared asking_bot cache for token: {token}")
    except Exception as e:
        logger.error(f"Error clearing asking_bot cache: {e}")

# --- Middleware для перехвата команд, если trial истёк ---
async def trial_middleware(message: types.Message, state: FSMContext, handler):
    user = await get_user_by_id(str(message.from_user.id))
    if user and not user['paid']:
        from datetime import datetime, timezone, timedelta
        start_date = user['start_date']
        if isinstance(start_date, str):
            from dateutil.parser import parse
            start_date = parse(start_date)
        now = datetime.utcnow()
        if (now - start_date).days >= TRIAL_DAYS:
            # Показываем меню оплаты/удаления
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Оплатить", callback_data="pay_trial")],
                    [InlineKeyboardButton(text="Удалить проекты", callback_data="delete_trial_projects")]
                ]
            )
            await message.answer(
                f"Пробный период завершён!\n\nДля продолжения работы оплатите {PAYMENT_AMOUNT} рублей за первый месяц или удалите проекты.\n\nВыберите действие:",
                reply_markup=kb
            )
            return  # Не передаём управление дальше
    await handler(message, state)

# --- Обработка команд с middleware ---
@settings_router.message(Command("start"))
async def start_with_trial_middleware(message: types.Message, state: FSMContext):
    telegram_id = str(message.from_user.id)
    from database import get_projects_by_user, get_user_by_id
    user = await get_user_by_id(telegram_id)
    projects = await get_projects_by_user(telegram_id)
    is_paid = user and user.get("paid")
    trial_limit = TRIAL_PROJECTS
    paid_limit = PAID_PROJECTS
    if not is_paid and len(projects) >= trial_limit:
        # Trial limit reached
        buttons = [
            [types.KeyboardButton(text="Оплатить")],
            [types.KeyboardButton(text="Проекты")]
        ]
        keyboard = types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
        await message.answer(
            f"Ваш пробный период ограничен {trial_limit} проектами.\n"
            f"Чтобы создать до {paid_limit} проектов, оплатите подписку.\n"
            f"Или вы можете изменить существующий проект под другой бизнес.",
            reply_markup=keyboard
        )
        return
    # Если лимит не превышен — стандартное приветствие
    await message.answer(
        "Добро пожаловать!\n\nВы можете создать новый проект или управлять существующими.",
        reply_markup=main_menu
    )
    await state.clear()

@settings_router.message(Command("help"))
async def help_with_trial_middleware(message: types.Message, state: FSMContext):
    await trial_middleware(message, state, handle_help_command)

@settings_router.message(Command("projects"))
async def projects_with_trial_middleware(message: types.Message, state: FSMContext):
    await trial_middleware(message, state, handle_projects_command)

@settings_router.message(SettingsStates.waiting_for_project_name)
async def handle_project_name(message: types.Message, state: FSMContext):
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

async def get_text_from_message(message, bot, max_length=4096) -> str:
    """Извлекает текст из файла, текста или голосового сообщения. Очищает и ограничивает длину."""
    text_content = None
    # 1. Файл
    if message.document:
        try:
            file_info = await bot.get_file(message.document.file_id)
            file_path = file_info.file_path
            file_content = await bot.download_file(file_path)
            filename = message.document.file_name
            from file_utils import extract_text_from_file_async
            text_content = await extract_text_from_file_async(filename, file_content.read())
        except Exception as e:
            raise RuntimeError(f"Ошибка при обработке файла: {e}")
    # 2. Текст
    elif message.text:
        text_content = message.text
    # 3. Голосовое сообщение
    elif message.voice:
        try:
            file_info = await bot.get_file(message.voice.file_id)
            file_path = file_info.file_path
            file_content = await bot.download_file(file_path)
            import speech_recognition as sr
            import tempfile
            recognizer = sr.Recognizer()
            with tempfile.NamedTemporaryFile(suffix='.ogg') as temp_ogg, tempfile.NamedTemporaryFile(suffix='.wav') as temp_wav:
                temp_ogg.write(file_content.read())
                temp_ogg.flush()
                # Конвертируем ogg/opus в wav через pydub
                audio = AudioSegment.from_file(temp_ogg.name)
                audio.export(temp_wav.name, format='wav')
                temp_wav.flush()
                with sr.AudioFile(temp_wav.name) as source:
                    audio_data = recognizer.record(source)
                text_content = recognizer.recognize_google(audio_data, language='ru-RU')
        except Exception as e:
            raise RuntimeError(f"Ошибка при распознавании голоса: {e}")
    if not text_content:
        raise RuntimeError("Пожалуйста, отправьте файл, текст или голосовое сообщение с информацией о бизнесе.")
    if len(text_content) > max_length:
        raise ValueError(f"❌ Данные слишком большие!\n\nРазмер: {len(text_content)} символов\nМаксимальный размер: {max_length} символов\n\nПожалуйста, сократите или разделите на части.")
    return clean_business_text(text_content)

@settings_router.message(SettingsStates.waiting_for_business_file)
async def handle_business_file(message: types.Message, state: FSMContext):
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
        await message.answer("Обрабатываю информацию о бизнесе...")
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
            await message.answer("У вас пока нет проектов. Создайте первый проект командой /start", reply_markup=main_menu)
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
    """Обрабатывает выбор проекта"""
    project_id = callback_query.data.replace('project_', '')
    logger.info(f"Project selected: {project_id}")
    try:
        project = await get_project_by_id(project_id)
        if not project:
            await callback_query.answer("Проект не найден")
            return
        # Сохраняем выбранный проект в состоянии
        await state.update_data(selected_project_id=project_id, selected_project=project)
        # Создаем меню управления проектом
        buttons = [
            [types.InlineKeyboardButton(text="Показать данные", callback_data="show_data")],
            [types.InlineKeyboardButton(text="Переименовать", callback_data="rename_project")],
            [types.InlineKeyboardButton(text="Изменить токен", callback_data="change_token")],
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
    """Запрашивает новое название проекта"""
    await callback_query.message.edit_text("Введите новое название проекта:")
    await state.set_state(SettingsStates.waiting_for_new_project_name)

@settings_router.message(SettingsStates.waiting_for_new_project_name)
async def handle_new_project_name(message: types.Message, state: FSMContext):
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
    await callback_query.message.edit_text(
        "Отправьте дополнительные данные о бизнесе одним из способов:\n"
        "1️⃣ Загрузите файл (txt, docx, pdf)\n"
        "2️⃣ Просто отправьте текст сообщением\n"
        "3️⃣ Или отправьте голосовое сообщение (мы преобразуем его в текст)"
    )
    await state.set_state(SettingsStates.waiting_for_additional_data_file)

@settings_router.message(SettingsStates.waiting_for_additional_data_file)
async def handle_additional_data_file(message: types.Message, state: FSMContext):
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

@settings_router.message()
async def handle_any_message(message: types.Message, state: FSMContext):
    """Обрабатывает любые сообщения, которые не являются командами"""
    # Проверяем, есть ли активное состояние
    current_state = await state.get_state()
    
    if current_state:
        # Если есть активное состояние, но это не ожидаемое сообщение, сбрасываем
        await state.clear()
        await message.answer(
            "❌ Операция была прервана.\n\n"
            "Доступные команды:\n"
            "/start - Создать новый проект\n"
            "/projects - Управление проектами\n"
            "/help - Справка",
            reply_markup=main_menu
        )
    # Если нет активного состояния, ничего не отвечаем (или можно логировать для отладки)
    # (Раньше здесь была справка, теперь убрано)

    # --- Обработка подтверждения оплаты админом ---
    if message.text and message.text.lower().startswith("оплатил ") and str(message.from_user.id) == str(MAIN_TELEGRAM_ID):
        parts = message.text.strip().split()
        if len(parts) == 2 and parts[1].isdigit():
            paid_telegram_id = parts[1]
            await set_user_paid(paid_telegram_id, True)
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
            await message.answer(f"Пользователь {paid_telegram_id} отмечен как оплативший. Вебхуки восстановлены для {restored} проектов.")
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

async def handle_command_in_state(message: types.Message, state: FSMContext) -> bool:
    """Универсальная функция для обработки команд в любом состоянии"""
    if message.text and message.text.startswith('/'):
        command = message.text.split()[0].lower()
        await state.clear()
        if command == '/start':
            await handle_settings_start(message, state)
        elif command == '/projects':
            await handle_projects_command(message, state)
        elif command == '/help':
            await handle_help_command(message, state)
        else:
            await message.answer("Неизвестная команда. Используйте /help для справки.")
        return True
    return False

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
        f"Для оплаты переведите {PAYMENT_AMOUNT} рублей на карту: {PAYMENT_CARD_NUMBER}\n\nПосле оплаты отправьте чек сюда (фото/скриншот)."
    )
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

@settings_router.message(lambda m: m.photo and m.caption and "чек" in m.caption.lower())
async def handle_payment_check(message: types.Message, state: FSMContext):
    telegram_id = str(message.from_user.id)
    # Пересылаем чек админу
    await message.forward(MAIN_TELEGRAM_ID)
    await message.answer("Чек отправлен на проверку. Ожидайте подтверждения оплаты.")

async def handle_settings_start(message: types.Message, state: FSMContext):
    logger.info(f"/start received from user {message.from_user.id}")
    try:
        # Сбрасываем состояние перед началом
        await state.clear()
        await create_user(str(message.from_user.id))
        await message.answer("Добро пожаловать в настройки! Введите имя вашего проекта.", reply_markup=main_menu)
        await state.set_state(SettingsStates.waiting_for_project_name)
        logger.info(f"Sent welcome message to user {message.from_user.id}")
    except Exception as e:
        logger.error(f"Error in handle_settings_start: {e}")

async def handle_help_command(message: types.Message, state: FSMContext):
    """Показывает справку по командам"""
    await state.clear()
    help_text = """
🤖 Доступные команды:

/start - Создать новый проект
/projects - Управление существующими проектами
/help - Показать эту справку

📋 Функции управления проектами:
• Переименование проекта
• Добавление дополнительных данных
• Изменение данных о бизнесе
• Удаление проекта (с отключением webhook)

💡 Для начала работы используйте /start
💡 Для управления проектами используйте /projects
    """
    await message.answer(help_text, reply_markup=main_menu)

async def handle_projects_command(message: types.Message, state: FSMContext, telegram_id: str = None):
    logger.info(f"/projects received from user {message.from_user.id}")
    try:
        if telegram_id is None:
            telegram_id = str(message.from_user.id)
        await state.update_data(telegram_id=telegram_id)
        await state.update_data(selected_project_id=None, selected_project=None)
        projects = await get_projects_by_user(telegram_id)
        if not projects:
            await message.answer("У вас пока нет проектов. Создайте первый проект командой /start", reply_markup=main_menu)
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

@settings_router.message(Command("feedback"))
async def handle_feedback_command(message: types.Message, state: FSMContext):
    await message.answer(
        "Пожалуйста, напишите ваш отзыв о сервисе. После отправки вы сможете отметить, положительный он или нет."
    )
    await state.set_state(SettingsStates.waiting_for_feedback_text)

@settings_router.message(SettingsStates.waiting_for_feedback_text)
async def handle_feedback_text(message: types.Message, state: FSMContext):
    await state.update_data(feedback_text=message.text)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👍 Положительный", callback_data="feedback_positive")],
            [InlineKeyboardButton(text="👎 Отрицательный", callback_data="feedback_negative")]
        ]
    )
    await message.answer("Спасибо! Отметьте, как вы оцениваете сервис:", reply_markup=kb)

@settings_router.callback_query(lambda c: c.data in ["feedback_positive", "feedback_negative"])
async def handle_feedback_rating(callback_query: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    feedback_text = data.get("feedback_text")
    is_positive = callback_query.data == "feedback_positive"
    username = callback_query.from_user.username
    telegram_id = str(callback_query.from_user.id)
    await add_feedback(telegram_id, username, feedback_text, is_positive)
    await callback_query.message.answer("Спасибо за ваш отзыв! Он очень важен для нас.")
    await state.clear()
    await callback_query.answer()

@settings_router.callback_query(lambda c: c.data == "change_token")
async def handle_change_token(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.message.edit_text("Введите новый API токен для этого проекта:")
    await state.set_state(SettingsStates.waiting_for_new_token)

@settings_router.message(SettingsStates.waiting_for_new_token)
async def handle_new_token(message: types.Message, state: FSMContext):
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