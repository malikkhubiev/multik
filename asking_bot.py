from fastapi import APIRouter, Request
from aiogram import Bot, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router, Dispatcher
from database import get_project_by_id, get_user_collection
from qdrant_utils import vectorize, qdrant
from aiogram.filters import Command

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
        await message.answer("Привет! Я готов отвечать на ваши вопросы. Загрузите знания, чтобы начать.")

    @tg_router.message()
    async def handle_question(message: types.Message):
        user_id = message.from_user.id
        text = message.text
        collection_name = await get_user_collection(user_id)
        if not collection_name:
            await message.answer("Коллекция не найдена. Сначала создайте коллекцию.")
            return
        question_vector, dim = await vectorize(text)
        hits = qdrant.search(collection_name=collection_name, query_vector=question_vector, limit=5)
        context = "\n".join([hit.payload["text"] for hit in hits if hasattr(hit, 'payload') and 'text' in hit.payload])
        if not context.strip():
            await message.answer("В базе нет подходящих данных для ответа на ваш вопрос. Пожалуйста, загрузите знания.")
            return
        response = deepseek.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "Ты - менеджер по продажам, который преобразует данные в дружелюбный продающий ответ клиенту в телеграм-чате."},
                {"role": "user", "content": f"На основе этих данных сформируй краткий ответ: {context} Ответ должен быть: - Отвечай ТОЛЬКО на поставленный вопрос, без лишней информации - На русском языке - Без символов разметки markdown - Упорядочен по степени совпадения (score) и напиши только данные, связанные с вопросом {text} - Без лишних слов вроде 'ответ клиенту' и т.д.: сразу ответ"}
            ],
            temperature=0.3
        )
        await message.answer(response.choices[0].message.content)
    bot_dispatchers[token] = (dp, bot)
    return dp, bot

@router.post("/webhook/{project_id}")
async def telegram_webhook(project_id: str, request: Request):
    project = await get_project_by_id(project_id)
    if not project:
        return {"status": "error", "message": "Проект не найден"}
    token = project["token"]
    dp, bot = await get_or_create_dispatcher(token)
    update_data = await request.json()
    update = types.Update.model_validate(update_data)
    await dp.feed_update(bot, update)
    return {"ok": True} 