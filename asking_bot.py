from fastapi import APIRouter, Request
from aiogram import Bot, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router, Dispatcher
from database import get_project_by_id, get_project_by_token, log_message_stat, get_user_by_id
from aiogram.filters import Command
import logging
import httpx
import asyncio
from config import DEEPSEEK_API_KEY
import time
from settings_bot import clean_markdown
from database import MessageStat
from sqlalchemy import func
from database import database
from sqlalchemy import select
from utils import send_typing_action

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
    else:
        logging.info(f"[ASKING_BOT] No dispatcher cache to clear for token: {token}")

async def get_or_create_dispatcher(token: str, business_info: str):
    logging.info(f"[ASKING_BOT] get_or_create_dispatcher: token={token}")
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
        from utils import recognize_message_text
        text = await recognize_message_text(message, bot)
        if not text:
            await message.answer("Пожалуйста, отправьте текстовое или голосовое сообщение с вопросом.")
            return
        logging.info(f"[ASKING_BOT] handle_question: user_id={user_id}, text={text}")
        user = await get_user_by_id(str(user_id))
        is_trial = user and not user['paid']
        is_paid = user and user['paid']
        t0 = time.monotonic()
        # Получаем токен из Project по user_id
        from database import get_projects_by_user
        logging.info(f"[ASKING_BOT] handle_question: получаем проекты для пользователя {user_id}")
        projects = await get_projects_by_user(str(user_id))
        logging.info(f"[ASKING_BOT] handle_question: найдено проектов для пользователя {user_id}: {len(projects)}")
        
        if projects and len(projects) > 0:
            project_token = projects[0]['token']
            logging.info(f"[ASKING_BOT] handle_question: найден токен проекта {project_token[:10]}... для пользователя {user_id}")
            logging.info(f"[ASKING_BOT] handle_question: отправляем typing action для пользователя {user_id}")
            await send_typing_action(user_id, project_token)
            logging.info(f"[ASKING_BOT] handle_question: typing action отправлен для пользователя {user_id}")
        else:
            logging.warning(f"[ASKING_BOT] Не найден проект для пользователя {user_id}, не отправляю typing action")
            await message.answer("...печатает")
            logging.info(f"[ASKING_BOT] handle_question: отправлено сообщение '...печатает' пользователю {user_id}")
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
            content = clean_markdown(content)
            logging.info(f"[ASKING_BOT] handle_question: deepseek response='{content}'")
            t3 = time.monotonic()
            await message.answer(content)
            response_time = time.monotonic() - t0
            # Логируем время ответа и общее количество ответов
            query = select(func.count()).select_from(MessageStat)
            row = await database.fetch_one(query)
            total_answers = row[0] if row else 0
            logging.info(f"[ASKING_BOT] Время ответа на этот вопрос: {response_time:.2f} сек. Всего ответов в БД: {total_answers}")
            await log_message_stat(
                telegram_id=str(user_id),
                is_command=False,
                is_reply=False,
                response_time=response_time,
                project_id=None,  # Можно добавить project_id, если есть
                is_trial=is_trial,
                is_paid=is_paid
            )
            logging.info(f"[ASKING] Ответ пользователю отправлен за {response_time:.2f} сек")
            logging.info(f"[ASKING] ВСЕГО времени на ответ: {response_time:.2f} сек")
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