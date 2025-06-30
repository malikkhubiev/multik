from fastapi import APIRouter, Request
from aiogram import Bot, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router, Dispatcher
from database import get_project_by_id, get_project_by_token
from aiogram.filters import Command
import logging
import httpx
import asyncio
from config import DEEPSEEK_API_KEY
import time

router = APIRouter()

bot_dispatchers = {}

role = """
Ты - самый npl-прокаченный менеджер по продажам.
Правила общения:
- Не используй markdown при ответе
- После каждого ответа предложи купить
- Если вопрос не по теме, переводи в шутку, связанную с бизнесом и продолжай продавливать продажу
- Если не знаешь что-то о чём спросили, честно скажи и дай вспомогательную инфу из базы
- Используй красивые смайлики
- Не продавай, а искренне помогай купить
"""

def clear_dispatcher_cache(token: str):
    """Очищает кэш диспетчера для указанного токена"""
    if token in bot_dispatchers:
        del bot_dispatchers[token]
        logging.info(f"[ASKING_BOT] Cleared dispatcher cache for token: {token}")

async def get_or_create_dispatcher(token: str, business_info: str):
    # Проверяем, есть ли уже диспетчер с этим токеном
    if token in bot_dispatchers:
        # Если есть, но business_info изменился, очищаем кэш
        existing_dp, existing_bot = bot_dispatchers[token]
        # Получаем актуальные данные проекта
        project = await get_project_by_token(token)
        if project and project["business_info"] != business_info:
            logging.info(f"[ASKING_BOT] Business info changed, clearing cache for token: {token}")
            clear_dispatcher_cache(token)
        else:
            return bot_dispatchers[token]
    
    bot = Bot(token=token)
    storage = MemoryStorage()
    tg_router = Router()
    dp = Dispatcher(storage=storage)
    dp.include_router(tg_router)

    @tg_router.message(Command("start"))
    async def handle_start(message: types.Message):
        logging.info(f"[ASKING_BOT] handle_start: from user {message.from_user.id}, text: {message.text}")
        await message.answer("Привет! Я готов отвечать на ваши вопросы о нашем бизнесе. Задайте вопрос!")

    @tg_router.message()
    async def handle_question(message: types.Message):
        user_id = message.from_user.id
        text = message.text
        logging.info(f"[ASKING_BOT] handle_question: from user {user_id}, text: {text}")
        t0 = time.monotonic()
        # Отправляем сообщение о начале обработки
        processing_msg = await message.answer("Изучаем базу данных...")
        if not business_info:
            await message.answer("Информация о бизнесе не найдена. Обратитесь к администратору.")
            logging.warning(f"[ASKING_BOT] handle_question: business_info not found for project")
            return
        try:
            logging.info("[ASKING] Формирование запроса к Deepseek...")
            t1 = time.monotonic()
            url = "https://api.deepseek.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": role + f"Отвечай на вопросы клиентов на основе информации о бизнесе: {business_info}"},
                    {"role": "user", "content": f"Ответь на вопрос клиента: {text}"}
                ],
                "temperature": 0.9
            }
            logging.info(f"[ASKING] Deepseek запрос сформирован за {time.monotonic() - t1:.2f} сек")
            t2 = time.monotonic()
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            logging.info(f"[ASKING] Deepseek ответ получен за {time.monotonic() - t2:.2f} сек")
            content = data["choices"][0]["message"]["content"]
            logging.info(f"[ASKING_BOT] handle_question: deepseek response='{content}'")
            t3 = time.monotonic()
            await message.answer(content)
            logging.info(f"[ASKING] Ответ пользователю отправлен за {time.monotonic() - t3:.2f} сек")
            logging.info(f"[ASKING] ВСЕГО времени на ответ: {time.monotonic() - t0:.2f} сек")
        except Exception as e:
            import traceback
            logging.error(f"[ASKING_BOT] handle_question: error: {e}\n{traceback.format_exc()}")
            await message.answer("Произошла ошибка при обработке вашего вопроса. Пожалуйста, попробуйте позже.")
    
    bot_dispatchers[token] = (dp, bot)
    return dp, bot

@router.post("/webhook/{project_id}")
async def telegram_webhook(project_id: str, request: Request):
    logging.info(f"[ASKING_BOT] Received webhook for project_id={project_id}")
    project = await get_project_by_id(project_id)
    if not project:
        logging.error(f"[ASKING_BOT] Project not found: {project_id}")
        return {"status": "error", "message": "Проект не найден"}
    token = project["token"]
    business_info = project["business_info"]
    dp, bot = await get_or_create_dispatcher(token, business_info)
    update_data = await request.json()
    logging.info(f"[ASKING_BOT] Update data: {update_data}")
    try:
        update = types.Update.model_validate(update_data)
        await dp.feed_update(bot, update)
    except Exception as e:
        import traceback
        logging.error(f"[ASKING_BOT] Ошибка обработки апдейта: {e}\n{traceback.format_exc()}")
        return {"ok": False, "error": str(e)}
    return {"ok": True} 