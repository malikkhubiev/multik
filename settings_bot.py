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
    await message.answer("Теперь загрузите файл с информацией о вашем бизнесе (txt, docx, pdf).")
    await state.set_state(SettingsStates.waiting_for_business_file)

@settings_router.message(SettingsStates.waiting_for_business_file)
async def handle_business_file(message: types.Message, state: FSMContext):
    # Проверяем команды через универсальную функцию
    if message.text and await handle_command_in_state(message, state):
        return
    
    logger.info(f"Business file received from user {message.from_user.id}")
    
    if not message.document:
        await message.answer("Пожалуйста, загрузите файл с информацией о бизнесе.")
        return
    
    try:
        # Скачиваем файл асинхронно
        file_info = await settings_bot.get_file(message.document.file_id)
        file_path = file_info.file_path
        file_content = await settings_bot.download_file(file_path)
        
        # Извлекаем текст из файла асинхронно
        filename = message.document.file_name
        text_content = await extract_text_from_file_async(filename, file_content.read())
        
        # Проверяем размер документа (не более 4000 символов)
        if len(text_content) > 4000:
            await message.answer(
                "❌ Документ слишком большой!\n\n"
                f"Размер документа: {len(text_content)} символов\n"
                "Максимальный размер: 4000 символов\n\n"
                "Пожалуйста, сократите документ или разделите его на части."
            )
            await state.clear()
            return
        
        # Обрабатываем через Deepseek асинхронно
        await message.answer("Обрабатываю информацию о бизнесе...")
        processed_business_info = await process_business_file_with_deepseek(text_content)
        
        # Очищаем от markdown символов
        processed_business_info = clean_markdown(processed_business_info)
        
        # Получаем данные из состояния
        data = await state.get_data()
        project_name = data.get("project_name")
        token = data.get("token")
        telegram_id = str(message.from_user.id)
        
        # Создаем проект и устанавливаем вебхук параллельно
        try:
            project_id = await create_project(telegram_id, project_name, processed_business_info, token)
        except ValueError as e:
            await message.answer(f"❌ Ошибка: {str(e)}\n\nПожалуйста, выберите другое название для проекта.")
            await state.clear()
            return
        
        logger.info(f"Перед установкой вебхука: token={token}, project_id={project_id}")
        
        # Устанавливаем вебхук асинхронно
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
    """Возврат к списку проектов"""
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
    """Запрашивает файл с дополнительными данными"""
    await callback_query.message.edit_text(
        "Отправьте файл с дополнительными данными о бизнесе (txt, docx, pdf).\n"
        "Эти данные будут добавлены к существующей информации."
    )
    await state.set_state(SettingsStates.waiting_for_additional_data_file)

@settings_router.message(SettingsStates.waiting_for_additional_data_file)
async def handle_additional_data_file(message: types.Message, state: FSMContext):
    # Проверяем команды через универсальную функцию
    if message.text and await handle_command_in_state(message, state):
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
        text_content = await extract_text_from_file_async(filename, file_content.read())
        
        # Проверяем размер документа (не более 4000 символов)
        if len(text_content) > 4000:
            await message.answer(
                "❌ Документ слишком большой!\n\n"
                f"Размер документа: {len(text_content)} символов\n"
                "Максимальный размер: 4000 символов\n\n"
                "Пожалуйста, сократите документ или разделите его на части."
            )
            await state.clear()
            return
        
        # Обрабатываем через Deepseek
        await message.answer("Обрабатываю дополнительные данные...")
        processed_additional_info = await process_business_file_with_deepseek(text_content)
        
        # Очищаем от markdown символов
        processed_additional_info = clean_markdown(processed_additional_info)
        
        # Добавляем к существующей информации
        success = await append_project_business_info(project_id, processed_additional_info)
        
        if success:
            # Очищаем кэш asking_bot
            project = await get_project_by_id(project_id)
            if project:
                await clear_asking_bot_cache(project["token"])
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
    # Проверяем команды через универсальную функцию
    if message.text and await handle_command_in_state(message, state):
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
        text_content = await extract_text_from_file_async(filename, file_content.read())
        
        # Проверяем размер документа (не более 4000 символов)
        if len(text_content) > 4000:
            await message.answer(
                "❌ Документ слишком большой!\n\n"
                f"Размер документа: {len(text_content)} символов\n"
                "Максимальный размер: 4000 символов\n\n"
                "Пожалуйста, сократите документ или разделите его на части."
            )
            await state.clear()
            return
        
        # Обрабатываем через Deepseek
        await message.answer("Обрабатываю новые данные...")
        processed_new_info = await process_business_file_with_deepseek(text_content)
        
        # Очищаем от markdown символов
        processed_new_info = clean_markdown(processed_new_info)
        
        # Заменяем информацию
        success = await update_project_business_info(project_id, processed_new_info)
        
        if success:
            # Очищаем кэш asking_bot
            project = await get_project_by_id(project_id)
            if project:
                await clear_asking_bot_cache(project["token"])
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