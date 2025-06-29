from fastapi import APIRouter, Request
from aiogram import Bot, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router, Dispatcher
from database import get_project_by_id
from aiogram.filters import Command
import logging
import httpx
from config import DEEPSEEK_API_KEY

router = APIRouter()

bot_dispatchers = {}

async def get_or_create_dispatcher(token: str, business_info: str):
    if token in bot_dispatchers:
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
        
        if not business_info:
            await message.answer("Информация о бизнесе не найдена. Обратитесь к администратору.")
            logging.warning(f"[ASKING_BOT] handle_question: business_info not found for project")
            return
        
        try:
            url = "https://api.deepseek.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": f"Ты - менеджер по продажам. Отвечай на вопросы клиентов на основе информации о бизнесе. Информация о бизнесе: {business_info}"},
                    {"role": "user", "content": f"Ответь на вопрос клиента: {text}"}
                ],
                "temperature": 0.3
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, headers=headers, json=payload, timeout=60)
                resp.raise_for_status()
                data = resp.json()
            content = data["choices"][0]["message"]["content"]
            logging.info(f"[ASKING_BOT] handle_question: deepseek response='{content}'")
            await message.answer(content)
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