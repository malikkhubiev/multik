from fastapi import APIRouter, Request
from aiogram import Bot, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router, Dispatcher
from database import get_project_by_id, get_user_collection
from qdrant_utils import vectorize, qdrant
from aiogram.filters import Command
import logging
import httpx
from config import DEEPSEEK_API_KEY

router = APIRouter()

bot_dispatchers = {}

async def get_or_create_dispatcher(token: str):
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
        await message.answer("Привет! Я готов отвечать на ваши вопросы. Загрузите знания, чтобы начать.")

    @tg_router.message()
    async def handle_question(message: types.Message):
        user_id = message.from_user.id
        text = message.text
        logging.info(f"[ASKING_BOT] handle_question: from user {user_id}, text: {text}")
        collection_name = await get_user_collection(user_id)
        logging.info(f"[ASKING_BOT] handle_question: collection_name={collection_name}")
        if not collection_name:
            await message.answer("Коллекция не найдена. Сначала создайте коллекцию.")
            logging.warning(f"[ASKING_BOT] handle_question: collection not found for user {user_id}")
            return
        try:
            question_vector, dim = await vectorize(text)
            logging.info(f"[ASKING_BOT] handle_question: vectorized question, dim={dim}")
            hits = qdrant.search(collection_name=collection_name, query_vector=question_vector, limit=5)
            logging.info(f"[ASKING_BOT] handle_question: qdrant hits count={len(hits)}")
            context = "\n".join([hit.payload["text"] for hit in hits if hasattr(hit, 'payload') and 'text' in hit.payload])
            logging.info(f"[ASKING_BOT] handle_question: context='{context}'")
            if not context.strip():
                await message.answer("В базе нет подходящих данных для ответа на ваш вопрос. Пожалуйста, загрузите знания.")
                logging.warning(f"[ASKING_BOT] handle_question: no context found for user {user_id}")
                return
            url = "https://api.deepseek.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "Ты - менеджер по продажам, который преобразует данные в дружелюбный продающий ответ клиенту в телеграм-чате."},
                    {"role": "user", "content": f"На основе этих данных сформируй краткий ответ: {context} Ответ должен быть: - Отвечай ТОЛЬКО на поставленный вопрос, без лишней информации - На русском языке - Без символов разметки markdown - Упорядочен по степени совпадения (score) и напиши только данные, связанные с вопросом {text} - Без лишних слов вроде 'ответ клиенту' и т.д.: сразу ответ"}
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
    dp, bot = await get_or_create_dispatcher(token)
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