from fastapi import APIRouter, Request, Form, UploadFile, File
from aiogram import Bot, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router, Dispatcher
import os
from config import API_URL
from database import create_project, get_project_by_id, create_user
from utils import set_webhook
from qdrant_utils import create_collection as qdrant_create_collection, extract_text_from_file, extract_assertions as extract_assertions_func, vectorize
import json

router = APIRouter()

SETTINGS_BOT_TOKEN = os.getenv("SETTINGS_BOT_TOKEN")
SETTINGS_WEBHOOK_PATH = "/webhook/settings"
SETTINGS_WEBHOOK_URL = os.getenv("SETTINGS_WEBHOOK_URL", f"{API_URL}{SETTINGS_WEBHOOK_PATH}")

settings_bot = Bot(token=SETTINGS_BOT_TOKEN)
settings_storage = MemoryStorage()
settings_router = Router()
settings_dp = Dispatcher(storage=settings_storage)
settings_dp.include_router(settings_router)

@settings_router.message(commands=["start"])
async def handle_settings_start(message: types.Message):
    await create_user(str(message.from_user.id))
    await message.answer("Добро пожаловать в настройки! Введите имя вашего проекта.")

@settings_router.message()
async def handle_settings_text(message: types.Message):
    await message.answer(f"Вы написали: {message.text}")

@router.post(SETTINGS_WEBHOOK_PATH)
async def process_settings_webhook(request: Request):
    update_data = await request.json()
    update = types.Update.model_validate(update_data)
    await settings_dp.feed_update(settings_bot, update)
    return {"ok": True}

@router.post("/create_project_meta")
async def create_project_meta(
    telegram_id: str = Form(...),
    project_name: str = Form(...),
    token: str = Form(...),
    focus: str = Form(...)
):
    logs = []
    try:
        project_id = await create_project(telegram_id, project_name, token)
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

@router.post("/create_collection")
async def create_collection_ep(project_id: str = Form(...)):
    logs = []
    try:
        project = await get_project_by_id(project_id)
        if not project:
            return {"status": "error", "message": "Проект не найден", "logs": logs}
        qdrant_create_collection(project['collection_name'])
        logs.append(f"[STEP] Коллекция создана: {project['collection_name']}")
        return {"status": "ok", "collection": project['collection_name'], "logs": logs}
    except Exception as e:
        logs.append(f"[ERROR] Ошибка при создании коллекции: {str(e)}")
        return {"status": "error", "message": str(e), "logs": logs}

@router.post("/upload_file")
async def upload_file_ep(project_id: str = Form(...), file: UploadFile = File(...)):
    logs = []
    try:
        project = await get_project_by_id(project_id)
        if not project:
            return {"status": "error", "message": "Проект не найден", "logs": logs}
        content = await file.read()
        text = extract_text_from_file(file.filename, content)
        logs.append(f"[STEP] Файл прочитан, размер текста: {len(text)} символов")
        return {"status": "ok", "text": text, "logs": logs}
    except Exception as e:
        logs.append(f"[ERROR] Ошибка при чтении файла: {str(e)}")
        return {"status": "error", "message": str(e), "logs": logs}

@router.post("/extract_assertions")
async def extract_assertions_ep(project_id: str = Form(...), text: str = Form(...)):
    logs = []
    try:
        assertions = extract_assertions_func(text)
        logs.append(f"[STEP] Извлечено утверждений: {len(assertions)}")
        return {"status": "ok", "assertions": assertions, "logs": logs}
    except Exception as e:
        logs.append(f"[ERROR] Ошибка при извлечении утверждений: {str(e)}")
        return {"status": "error", "message": str(e), "logs": logs}

@router.post("/vectorize_and_upload")
async def vectorize_and_upload_ep(project_id: str = Form(...), assertions: str = Form(...)):
    logs = []
    try:
        project = await get_project_by_id(project_id)
        if not project:
            return {"status": "error", "message": "Проект не найден", "logs": logs}
        collection_name = project['collection_name']
        assertions_list = json.loads(assertions)
        vectors = []
        for idx, assertion in enumerate(assertions_list):
            try:
                vector, dim = await vectorize(assertion)
                vectors.append({
                    "id": idx,
                    "vector": vector,
                    "payload": {"text": assertion}
                })
            except Exception as vec_error:
                logs.append(f"[ERROR] Ошибка векторизации для утверждения {idx}: {str(vec_error)}")
        if vectors:
            from base import qdrant
            qdrant.upsert(
                collection_name=collection_name,
                points=vectors
            )
            logs.append(f"[STEP] Векторизация и загрузка завершены: {len(vectors)} точек")
        else:
            logs.append(f"[WARN] Нет данных для загрузки в Qdrant")
        return {"status": "ok", "count": len(vectors), "logs": logs}
    except Exception as e:
        logs.append(f"[ERROR] Ошибка при векторизации/загрузке: {str(e)}")
        return {"status": "error", "message": str(e), "logs": logs}

async def set_settings_webhook():
    await settings_bot.set_webhook(SETTINGS_WEBHOOK_URL) 