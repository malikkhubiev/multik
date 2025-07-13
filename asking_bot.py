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
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

router = APIRouter()

bot_dispatchers = {}

# Состояния для сбора данных формы
class FormStates(StatesGroup):
    collecting_form_data = State()

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

async def get_project_form_by_token(token: str):
    """Получает форму проекта по токену"""
    from database import get_project_by_token, get_project_form
    project = await get_project_by_token(token)
    if not project:
        return None
    form = await get_project_form(project["id"])
    if form:
        # Добавляем project_id в форму для удобства
        form["project_id"] = project["id"]
    return form

async def start_form_collection(message: types.Message, form, bot):
    """Начинает сбор данных формы"""
    logging.info(f"[FORM] start_form_collection: user={message.from_user.id}")
    
    if not form or not form["fields"]:
        await message.answer("Форма не настроена или не содержит полей.")
        return
    
    # Получаем токен проекта
    from database import get_project_by_id
    project = await get_project_by_id(form["project_id"])
    if not project:
        await message.answer("Ошибка: проект не найден")
        return
    
    # Сохраняем данные формы в состоянии пользователя
    storage = bot_dispatchers.get(project["token"])[0].storage
    state = FSMContext(storage=storage, key=types.Chat(chat_id=message.chat.id, type="private"))
    
    await state.update_data(
        current_form=form,
        current_field_index=0,
        form_data={}
    )
    await state.set_state(FormStates.collecting_form_data)
    
    # Показываем первое поле
    await show_next_form_field(message, form, 0, bot)

async def show_next_form_field(message: types.Message, form, field_index: int, bot):
    """Показывает следующее поле формы"""
    if field_index >= len(form["fields"]):
        # Форма заполнена
        await finish_form_collection(message, form, bot)
        return
    
    field = form["fields"][field_index]
    required_text = " (обязательно)" if field["required"] else ""
    
    field_text = f"📋 {field['name']}{required_text}\n\n"
    
    if field["field_type"] == "text":
        field_text += "Введите текст:"
    elif field["field_type"] == "number":
        field_text += "Введите число:"
    elif field["field_type"] == "phone":
        field_text += "Введите номер телефона:"
    elif field["field_type"] == "date":
        field_text += "Введите дату (например: 01.01.2024):"
    elif field["field_type"] == "email":
        field_text += "Введите email:"
    
    await message.answer(field_text)

async def finish_form_collection(message: types.Message, form, bot):
    """Завершает сбор данных формы"""
    logging.info(f"[FORM] finish_form_collection: user={message.from_user.id}")
    
    # Получаем токен проекта
    from database import get_project_by_id
    project = await get_project_by_id(form["project_id"])
    if not project:
        await message.answer("Ошибка: проект не найден")
        return
    
    storage = bot_dispatchers.get(project["token"])[0].storage
    state = FSMContext(storage=storage, key=types.Chat(chat_id=message.chat.id, type="private"))
    form_data = (await state.get_data()).get("form_data", {})
    
    # Сохраняем заявку
    from database import save_form_submission
    success = await save_form_submission(form["id"], str(message.from_user.id), form_data)
    
    if success:
        await message.answer(
            "✅ Спасибо! Ваша заявка принята.\n\n"
            "Мы свяжемся с вами в ближайшее время! 🚀"
        )
    else:
        await message.answer(
            "❌ Заявка уже была отправлена ранее.\n\n"
            "Спасибо за интерес к нашему проекту! 🙏"
        )
    
    await state.clear()

async def validate_field_value(value: str, field_type: str) -> tuple[bool, str]:
    """Валидирует значение поля формы"""
    import re
    
    if field_type == "text":
        return True, ""
    elif field_type == "number":
        try:
            float(value)
            return True, ""
        except ValueError:
            return False, "Пожалуйста, введите число"
    elif field_type == "phone":
        # Простая валидация телефона
        phone_pattern = r'^[\+]?[0-9\s\-\(\)]{10,}$'
        if re.match(phone_pattern, value):
            return True, ""
        return False, "Пожалуйста, введите корректный номер телефона"
    elif field_type == "date":
        # Простая валидация даты
        date_pattern = r'^\d{1,2}\.\d{1,2}\.\d{4}$'
        if re.match(date_pattern, value):
            return True, ""
        return False, "Пожалуйста, введите дату в формате ДД.ММ.ГГГГ"
    elif field_type == "email":
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if re.match(email_pattern, value):
            return True, ""
        return False, "Пожалуйста, введите корректный email"
    
    return True, ""

def extract_links_from_text(text: str) -> tuple[str, list]:
    """Извлекает ссылки из текста и возвращает текст без ссылок и список ссылок"""
    import re
    
    # Паттерн для поиска ссылок
    url_pattern = r'https?://[^\s]+'
    links = re.findall(url_pattern, text)
    
    # Убираем ссылки из текста
    text_without_links = re.sub(url_pattern, '', text)
    # Убираем лишние пробелы
    text_without_links = re.sub(r'\s+', ' ', text_without_links).strip()
    
    return text_without_links, links

def create_rating_keyboard(message_id: str) -> types.InlineKeyboardMarkup:
    """Создает клавиатуру с кнопками лайк/дизлайк"""
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text="👍", callback_data=f"rate_like_{message_id}"),
                types.InlineKeyboardButton(text="👎", callback_data=f"rate_dislike_{message_id}")
            ]
        ]
    )

def create_links_keyboard(links: list) -> types.InlineKeyboardMarkup:
    """Создает клавиатуру с ссылками"""
    buttons = []
    for i, link in enumerate(links, 1):
        buttons.append([types.InlineKeyboardButton(text=f"🔗 Ссылка {i}", url=link)])
    
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)

async def handle_form_field_input(message: types.Message, state: FSMContext, bot):
    """Обрабатывает ввод данных в поле формы"""
    logging.info(f"[FORM] handle_form_field_input: user={message.from_user.id}")
    
    data = await state.get_data()
    form = data.get("current_form")
    current_field_index = data.get("current_field_index", 0)
    form_data = data.get("form_data", {})
    
    if not form or current_field_index >= len(form["fields"]):
        await state.clear()
        return
    
    field = form["fields"][current_field_index]
    field_value = message.text
    
    # Валидируем значение
    is_valid, error_message = await validate_field_value(field_value, field["field_type"])
    
    if not is_valid:
        await message.answer(error_message)
        return
    
    # Сохраняем значение
    form_data[field["name"]] = field_value
    await state.update_data(form_data=form_data)
    
    # Переходим к следующему полю
    next_field_index = current_field_index + 1
    await state.update_data(current_field_index=next_field_index)
    
    if next_field_index >= len(form["fields"]):
        # Форма заполнена
        await finish_form_collection(message, form, bot)
    else:
        # Показываем следующее поле
        await show_next_form_field(message, form, next_field_index, bot)

async def check_and_start_form(message: types.Message, text: str, token: str, bot):
    """Проверяет, нужно ли запустить форму, и запускает её при необходимости"""
    # Проверяем, есть ли форма у проекта
    form = await get_project_form_by_token(token)
    if not form or not form["fields"]:
        return False
    
    # Проверяем, не находится ли пользователь уже в процессе заполнения формы
    storage = bot_dispatchers[token][0].storage
    state = FSMContext(storage=storage, key=types.Chat(chat_id=message.chat.id, type="private"))
    current_state = await state.get_state()
    
    if current_state == FormStates.collecting_form_data.state:
        return True  # Уже в процессе заполнения формы
    
    # Проверяем ключевые слова для запуска формы
    form_keywords = ["заявка", "записаться", "оставить заявку", "хочу записаться", "запись", "регистрация"]
    text_lower = text.lower()
    
    for keyword in form_keywords:
        if keyword in text_lower:
            await start_form_collection(message, form, bot)
            return True
    
    return False

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
        
        # Проверяем, находится ли пользователь в процессе заполнения формы
        storage = bot_dispatchers[token][0].storage
        state = FSMContext(storage=storage, key=types.Chat(chat_id=message.chat.id, type="private"))
        current_state = await state.get_state()
        
        if current_state == FormStates.collecting_form_data.state:
            # Обрабатываем заполнение формы
            await handle_form_field_input(message, state, bot)
            return
        
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
            
            # Проверяем, нужно ли запустить форму
            if await check_and_start_form(message, text, project_token, bot):
                return
            
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
            
            # Обрабатываем ссылки в ответе
            content_without_links, links = extract_links_from_text(content)
            
            # Отправляем ответ без ссылок
            response_message = await message.answer(content_without_links)
            
            # Создаем клавиатуру с кнопками лайк/дизлайк используя ID отправленного сообщения
            rating_keyboard = create_rating_keyboard(str(response_message.message_id))
            
            # Редактируем сообщение чтобы добавить кнопки
            await response_message.edit_reply_markup(reply_markup=rating_keyboard)
            
            # Если есть ссылки, отправляем их отдельно
            if links:
                links_keyboard = create_links_keyboard(links)
                await message.answer("🔗 Полезные ссылки:", reply_markup=links_keyboard)
            
            t3 = time.monotonic()
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
    
    # Обработчики для кнопок лайк/дизлайк
    @tg_router.callback_query(lambda c: c.data.startswith("rate_"))
    async def handle_rating(callback_query: types.CallbackQuery):
        """Обрабатывает нажатие на кнопки лайк/дизлайк"""
        logging.info(f"[RATING] handle_rating: user={callback_query.from_user.id}, data={callback_query.data}")
        
        try:
            # Парсим данные из callback_data
            parts = callback_query.data.split('_')
            rating_type = parts[1]  # like или dislike
            message_id = parts[2]
            
            # Определяем рейтинг
            rating = True if rating_type == "like" else False
            
            # Получаем project_id если есть
            project_id = None
            from database import get_projects_by_user
            projects = await get_projects_by_user(str(callback_query.from_user.id))
            if projects:
                project_id = projects[0]['id']
            
            # Сохраняем рейтинг
            from database import save_response_rating
            success = await save_response_rating(
                str(callback_query.from_user.id),
                message_id,
                rating,
                project_id
            )
            
            if success:
                await callback_query.answer("Спасибо за оценку! 👍" if rating else "Спасибо за оценку! 👎")
            else:
                await callback_query.answer("Ошибка при сохранении оценки")
                
        except Exception as e:
            logging.error(f"[RATING] handle_rating: ОШИБКА: {e}")
            await callback_query.answer("Произошла ошибка")
    
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