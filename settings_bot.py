from fastapi import APIRouter, Request, Form, UploadFile, File
from aiogram import Bot, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router, Dispatcher
from aiogram.filters import Command
import os
from config import API_URL, SERVER_URL, DEEPSEEK_API_KEY
from database import create_project, get_project_by_id, create_user
from utils import set_webhook
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
        await create_user(str(message.from_user.id))
        await message.answer("Добро пожаловать в настройки! Введите имя вашего проекта.")
        await state.set_state(SettingsStates.waiting_for_project_name)
        logger.info(f"Sent welcome message to user {message.from_user.id}")
    except Exception as e:
        logger.error(f"Error in handle_settings_start: {e}")

@settings_router.message(SettingsStates.waiting_for_project_name)
async def handle_project_name(message: types.Message, state: FSMContext):
    logger.info(f"Project name received from user {message.from_user.id}: {message.text}")
    await state.update_data(project_name=message.text)
    await message.answer("Теперь введите API токен для Telegram-бота.")
    await state.set_state(SettingsStates.waiting_for_token)

@settings_router.message(SettingsStates.waiting_for_token)
async def handle_token(message: types.Message, state: FSMContext):
    logger.info(f"Token received from user {message.from_user.id}: {message.text}")
    await state.update_data(token=message.text)
    await message.answer("Теперь загрузите файл с информацией о вашем бизнесе (txt, docx, pdf).")
    await state.set_state(SettingsStates.waiting_for_business_file)

@settings_router.message(SettingsStates.waiting_for_business_file)
async def handle_business_file(message: types.Message, state: FSMContext):
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