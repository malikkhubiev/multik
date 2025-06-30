from fastapi import APIRouter, Request, Form, UploadFile, File
from aiogram import Bot, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router, Dispatcher
from aiogram.filters import Command
import os
from config import API_URL, SERVER_URL, DEEPSEEK_API_KEY
from database import create_project, get_project_by_id, create_user, get_projects_by_user, update_project_name, update_project_business_info, append_project_business_info, delete_project, get_project_by_token, check_project_name_exists
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

@settings_router.message(Command("start"))
async def handle_settings_start(message: types.Message, state: FSMContext):
    logger.info(f"/start received from user {message.from_user.id}")
    try:
        # Сбрасываем состояние перед началом
        await state.clear()
        await create_user(str(message.from_user.id))
        await message.answer("Добро пожаловать в настройки! Введите имя вашего проекта.")
        await state.set_state(SettingsStates.waiting_for_project_name)
        logger.info(f"Sent welcome message to user {message.from_user.id}")
    except Exception as e:
        logger.error(f"Error in handle_settings_start: {e}")

@settings_router.message(Command("help"))
async def handle_help_command(message: types.Message, state: FSMContext):
    """Показывает справку по командам"""
    # Сбрасываем состояние
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
    await message.answer(help_text)

@settings_router.message(SettingsStates.waiting_for_project_name)
async def handle_project_name(message: types.Message, state: FSMContext):
    # Проверяем команды через универсальную функцию
    if await handle_command_in_state(message, state):
        return
    
    logger.info(f"Project name received from user {message.from_user.id}: {message.text}")
    await state.update_data(project_name=message.text)
    await message.answer("Теперь введите API токен для Telegram-бота.")
    await state.set_state(SettingsStates.waiting_for_token)

@settings_router.message(SettingsStates.waiting_for_token)
async def handle_token(message: types.Message, state: FSMContext):
    # Проверяем команды через универсальную функцию
    if await handle_command_in_state(message, state):
        return
    
    logger.info(f"Token received from user {message.from_user.id}: {message.text}")
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
    try:
        text_content = await get_text_from_message(message, settings_bot)
    except ValueError as ve:
        await message.answer(str(ve))
        await state.clear()
        return
    except RuntimeError as re:
        await message.answer(str(re))
        await state.clear()
        return
    await message.answer("Обрабатываю информацию о бизнесе...")
    processed_business_info = await process_business_file_with_deepseek(text_content)
    processed_business_info = clean_markdown(processed_business_info)
    data = await state.get_data()
    project_name = data.get("project_name")
    token = data.get("token")
    telegram_id = str(message.from_user.id)
    try:
        project_id = await create_project(telegram_id, project_name, processed_business_info, token)
    except ValueError as e:
        await message.answer(f"❌ Ошибка: {str(e)}\n\nПожалуйста, выберите другое название для проекта.")
        await state.clear()
        return
    logger.info(f"Перед установкой вебхука: token={token}, project_id={project_id}")
    webhook_result = await set_webhook(token, project_id)
    if webhook_result.get("ok"):
        await message.answer(f"Спасибо! Проект создан.\n\nПроект: {project_name}\nТокен: {token}\nВебхук успешно установлен!\n\nБот готов к работе!")
    else:
        await message.answer(f"Проект создан, но не удалось установить вебхук: {webhook_result}")
    await state.clear()

@settings_router.message(Command("projects"))
async def handle_projects_command(message: types.Message, state: FSMContext):
    """Показывает список проектов пользователя"""
    logger.info(f"/projects received from user {message.from_user.id}")
    try:
        # Сбрасываем состояние перед показом проектов
        await state.clear()
        telegram_id = str(message.from_user.id)
        projects = await get_projects_by_user(telegram_id)
        
        if not projects:
            await message.answer("У вас пока нет проектов. Создайте первый проект командой /start")
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
            await message.answer("Выберите проект для управления:", reply_markup=keyboard)
        else:
            await message.answer("Нет доступных проектов.")
        
    except Exception as e:
        logger.error(f"Error in handle_projects_command: {e}")
        await message.answer("Произошла ошибка при получении списка проектов")

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
    """Возврат к списку проектов (не сбрасывает telegram_id пользователя)"""
    # Очищаем только выбор проекта, но не всё состояние
    await state.update_data(selected_project_id=None, selected_project=None)
    await handle_projects_command(callback_query.message, state)

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
    try:
        data = await state.get_data()
        project_id = data.get("selected_project_id")
        if not project_id:
            await message.answer("Ошибка: проект не выбран")
            await state.clear()
            return
        text_content = await get_text_from_message(message, settings_bot)
    except ValueError as ve:
        await message.answer(str(ve))
        await state.clear()
        return
    except RuntimeError as re:
        await message.answer(str(re))
        await state.clear()
        return
    await message.answer("Обрабатываю дополнительные данные...")
    processed_additional_info = await process_business_file_with_deepseek(text_content)
    processed_additional_info = clean_markdown(processed_additional_info)
    success = await append_project_business_info(project_id, processed_additional_info)
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
    try:
        data = await state.get_data()
        project_id = data.get("selected_project_id")
        if not project_id:
            await message.answer("Ошибка: проект не выбран")
            await state.clear()
            return
        text_content = await get_text_from_message(message, settings_bot)
    except ValueError as ve:
        await message.answer(str(ve))
        await state.clear()
        return
    except RuntimeError as re:
        await message.answer(str(re))
        await state.clear()
        return
    await message.answer("Обрабатываю новые данные...")
    processed_new_info = await process_business_file_with_deepseek(text_content)
    processed_new_info = clean_markdown(processed_new_info)
    success = await update_project_business_info(project_id, processed_new_info)
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
            "/help - Справка"
        )
    else:
        # Если нет активного состояния, показываем справку
        await message.answer(
            "🤖 Используйте команды для работы с ботом:\n\n"
            "/start - Создать новый проект\n"
            "/projects - Управление существующими проектами\n"
            "/help - Показать справку"
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