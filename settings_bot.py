from fastapi import APIRouter, Request, Form, UploadFile, File
from aiogram import Bot, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router, Dispatcher
from aiogram.filters import Command
import os
from config import API_URL, SERVER_URL, DEEPSEEK_API_KEY
from database import create_project, get_project_by_id, create_user, get_projects_by_user, update_project_name, update_project_business_info, append_project_business_info, delete_project
from utils import set_webhook, delete_webhook
from file_utils import extract_text_from_file
import json
import logging
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
import traceback
import httpx

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
                {"role": "system", "content": "Ты - эксперт по анализу бизнес-информации. Твоя задача - извлечь из предоставленных данных ключевую информацию о бизнесе и представить её в компактном виде для использования в чат-боте. Убери лишние детали, оставь только самое важное для ответов клиентам."},
                {"role": "user", "content": f"Обработай эту информацию о бизнесе и сделай её компактной для чат-бота: {file_content}"}
            ],
            "temperature": 0.3
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Ошибка при обработке файла через Deepseek: {e}")
        # Возвращаем исходный текст, если обработка не удалась
        return file_content

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
    # Проверяем, не является ли сообщение командой
    if message.text and message.text.startswith('/'):
        # Если это команда, сбрасываем состояние и не обрабатываем здесь
        await state.clear()
        return
    
    logger.info(f"Project name received from user {message.from_user.id}: {message.text}")
    await state.update_data(project_name=message.text)
    await message.answer("Теперь введите API токен для Telegram-бота.")
    await state.set_state(SettingsStates.waiting_for_token)

@settings_router.message(SettingsStates.waiting_for_token)
async def handle_token(message: types.Message, state: FSMContext):
    # Проверяем, не является ли сообщение командой
    if message.text and message.text.startswith('/'):
        # Если это команда, сбрасываем состояние и не обрабатываем здесь
        await state.clear()
        return
    
    logger.info(f"Token received from user {message.from_user.id}: {message.text}")
    await state.update_data(token=message.text)
    await message.answer("Теперь загрузите файл с информацией о вашем бизнесе (txt, docx, pdf).")
    await state.set_state(SettingsStates.waiting_for_business_file)

@settings_router.message(SettingsStates.waiting_for_business_file)
async def handle_business_file(message: types.Message, state: FSMContext):
    # Проверяем, не является ли сообщение командой
    if message.text and message.text.startswith('/'):
        # Если это команда, сбрасываем состояние и не обрабатываем здесь
        return
    
    logger.info(f"Business file received from user {message.from_user.id}")
    
    if not message.document:
        await message.answer("Пожалуйста, загрузите файл с информацией о бизнесе.")
        return
    
    try:
        # Скачиваем файл
        file_info = await settings_bot.get_file(message.document.file_id)
        file_path = file_info.file_path
        file_content = await settings_bot.download_file(file_path)
        
        # Извлекаем текст из файла
        filename = message.document.file_name
        text_content = extract_text_from_file(filename, file_content.read())
        
        # Обрабатываем через Deepseek
        await message.answer("Обрабатываю информацию о бизнесе...")
        processed_business_info = await process_business_file_with_deepseek(text_content)
        
        # Получаем данные из состояния
        data = await state.get_data()
        project_name = data.get("project_name")
        token = data.get("token")
        telegram_id = str(message.from_user.id)
        
        # Создаем проект с обработанной информацией о бизнесе
        project_id = await create_project(telegram_id, project_name, processed_business_info, token)
        logger.info(f"Перед установкой вебхука: token={token}, project_id={project_id}")
        
        # Устанавливаем вебхук
        webhook_result = await set_webhook(token, project_id)
        if webhook_result.get("ok"):
            await message.answer(f"Спасибо! Проект создан.\n\nПроект: {project_name}\nТокен: {token}\nВебхук успешно установлен!\n\nБот готов к работе!")
        else:
            await message.answer(f"Проект создан, но не удалось установить вебхук: {webhook_result}")
            
    except Exception as e:
        logger.error(f"Error in handle_business_file: {e}")
        await message.answer(f"Ошибка при обработке файла: {e}")
    
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
        
        # Создаем клавиатуру с проектами
        keyboard = types.InlineKeyboardMarkup()
        for project in projects:
            keyboard.add(
                types.InlineKeyboardButton(
                    text=project["project_name"],
                    callback_data=f"project_{project['id']}"
                )
            )
        
        await message.answer("Выберите проект для управления:", reply_markup=keyboard)
        
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
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("Переименовать", callback_data="rename_project"))
        keyboard.add(types.InlineKeyboardButton("Добавить данные", callback_data="add_data"))
        keyboard.add(types.InlineKeyboardButton("Изменить данные", callback_data="change_data"))
        keyboard.add(types.InlineKeyboardButton("Удалить проект", callback_data="delete_project"))
        keyboard.add(types.InlineKeyboardButton("Назад к списку", callback_data="back_to_projects"))
        
        await callback_query.message.edit_text(
            f"Проект: {project['project_name']}\n\nВыберите действие:",
            reply_markup=keyboard
        )
        
    except Exception as e:
        logger.error(f"Error in handle_project_selection: {e}")
        await callback_query.answer("Произошла ошибка")

@settings_router.callback_query(lambda c: c.data == "back_to_projects")
async def handle_back_to_projects(callback_query: types.CallbackQuery, state: FSMContext):
    """Возврат к списку проектов"""
    await handle_projects_command(callback_query.message, state)

@settings_router.callback_query(lambda c: c.data == "rename_project")
async def handle_rename_project(callback_query: types.CallbackQuery, state: FSMContext):
    """Запрашивает новое название проекта"""
    await callback_query.message.edit_text("Введите новое название проекта:")
    await state.set_state(SettingsStates.waiting_for_new_project_name)

@settings_router.message(SettingsStates.waiting_for_new_project_name)
async def handle_new_project_name(message: types.Message, state: FSMContext):
    # Проверяем, не является ли сообщение командой
    if message.text and message.text.startswith('/'):
        # Если это команда, сбрасываем состояние и не обрабатываем здесь
        await state.clear()
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
    """Запрашивает файл с дополнительными данными"""
    await callback_query.message.edit_text(
        "Отправьте файл с дополнительными данными о бизнесе (txt, docx, pdf).\n"
        "Эти данные будут добавлены к существующей информации."
    )
    await state.set_state(SettingsStates.waiting_for_additional_data_file)

@settings_router.message(SettingsStates.waiting_for_additional_data_file)
async def handle_additional_data_file(message: types.Message, state: FSMContext):
    # Проверяем, не является ли сообщение командой
    if message.text and message.text.startswith('/'):
        # Если это команда, сбрасываем состояние и не обрабатываем здесь
        return
    
    """Обрабатывает файл с дополнительными данными"""
    if not message.document:
        await message.answer("Пожалуйста, загрузите файл с дополнительными данными.")
        return
    
    try:
        data = await state.get_data()
        project_id = data.get("selected_project_id")
        
        if not project_id:
            await message.answer("Ошибка: проект не выбран")
            await state.clear()
            return
        
        # Скачиваем файл
        file_info = await settings_bot.get_file(message.document.file_id)
        file_path = file_info.file_path
        file_content = await settings_bot.download_file(file_path)
        
        # Извлекаем текст из файла
        filename = message.document.file_name
        text_content = extract_text_from_file(filename, file_content.read())
        
        # Обрабатываем через Deepseek
        await message.answer("Обрабатываю дополнительные данные...")
        processed_additional_info = await process_business_file_with_deepseek(text_content)
        
        # Добавляем к существующей информации
        success = await append_project_business_info(project_id, processed_additional_info)
        
        if success:
            await message.answer("Дополнительные данные успешно добавлены к проекту!")
        else:
            await message.answer("Ошибка при добавлении дополнительных данных")
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Error in handle_additional_data_file: {e}")
        await message.answer(f"Ошибка при обработке файла: {e}")
        await state.clear()

@settings_router.callback_query(lambda c: c.data == "change_data")
async def handle_change_data(callback_query: types.CallbackQuery, state: FSMContext):
    """Запрашивает файл с новыми данными"""
    await callback_query.message.edit_text(
        "Отправьте файл с новыми данными о бизнесе (txt, docx, pdf).\n"
        "Старые данные будут полностью заменены новыми."
    )
    await state.set_state(SettingsStates.waiting_for_new_data_file)

@settings_router.message(SettingsStates.waiting_for_new_data_file)
async def handle_new_data_file(message: types.Message, state: FSMContext):
    # Проверяем, не является ли сообщение командой
    if message.text and message.text.startswith('/'):
        # Если это команда, сбрасываем состояние и не обрабатываем здесь
        return
    
    """Обрабатывает файл с новыми данными"""
    if not message.document:
        await message.answer("Пожалуйста, загрузите файл с новыми данными.")
        return
    
    try:
        data = await state.get_data()
        project_id = data.get("selected_project_id")
        
        if not project_id:
            await message.answer("Ошибка: проект не выбран")
            await state.clear()
            return
        
        # Скачиваем файл
        file_info = await settings_bot.get_file(message.document.file_id)
        file_path = file_info.file_path
        file_content = await settings_bot.download_file(file_path)
        
        # Извлекаем текст из файла
        filename = message.document.file_name
        text_content = extract_text_from_file(filename, file_content.read())
        
        # Обрабатываем через Deepseek
        await message.answer("Обрабатываю новые данные...")
        processed_new_info = await process_business_file_with_deepseek(text_content)
        
        # Заменяем информацию
        success = await update_project_business_info(project_id, processed_new_info)
        
        if success:
            await message.answer("Данные проекта успешно обновлены!")
        else:
            await message.answer("Ошибка при обновлении данных проекта")
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Error in handle_new_data_file: {e}")
        await message.answer(f"Ошибка при обработке файла: {e}")
        await state.clear()

@settings_router.callback_query(lambda c: c.data == "delete_project")
async def handle_delete_project_request(callback_query: types.CallbackQuery, state: FSMContext):
    """Запрашивает подтверждение удаления проекта"""
    data = await state.get_data()
    project = data.get("selected_project")
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("Да, удалить", callback_data="confirm_delete"))
    keyboard.add(types.InlineKeyboardButton("Отмена", callback_data="cancel_delete"))
    
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
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("Переименовать", callback_data="rename_project"))
    keyboard.add(types.InlineKeyboardButton("Добавить данные", callback_data="add_data"))
    keyboard.add(types.InlineKeyboardButton("Изменить данные", callback_data="change_data"))
    keyboard.add(types.InlineKeyboardButton("Удалить проект", callback_data="delete_project"))
    keyboard.add(types.InlineKeyboardButton("Назад к списку", callback_data="back_to_projects"))
    
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