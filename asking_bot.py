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

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from analytics import log_question_asked, log_form_submission_confirmed, log_response_rating
from form_auto_fill import form_auto_filler, create_form_preview_keyboard, create_form_preview_message

router = APIRouter()

bot_dispatchers = {}

# Состояния для сбора данных формы
class FormStates(StatesGroup):
    collecting_form_data = State()

role_base = """
Ты - самый npl-прокаченный менеджер по продажам.
Правила общения:
- Не используй markdown при ответе
- Если есть ссылка, помогающая продать, вставь её в ответ
- После каждого ответа предложи купить
- Если вопрос не по теме, переводи в шутку, связанную с бизнесом и продолжай продавливать продажу
- Если не знаешь что-то о чём спросили, честно скажи и дай вспомогательную инфу из базы
- Используй красивые смайлики
- Не продавай, а искренне помогай купить
"""

role_form = """
\nДОПОЛНИТЕЛЬНЫЕ ПРАВИЛА ДЛЯ РАБОТЫ С ФОРМАМИ:
- Если клиент упоминает информацию, которая может быть полезна для формы (имя, телефон, email, дата), запоминай это
- Если клиент говорит \"хочу записаться\", \"оставить заявку\", \"зарегистрироваться\" - предложи заполнить форму
- При заполнении формы будь дружелюбным и помогай клиенту
- Если клиент не хочет заполнять форму сейчас, не настаивай, но предложи позже
- Используй контекст разговора для автозаполнения формы
- Если нужно отформатировать ответы для заполнения формы, делай это аккуратно и понятно
- При сборе данных формы задавай вопросы по одному полю за раз, не перегружай клиента
- Если клиент дает информацию для нескольких полей сразу, используй её для автозаполнения
- НЕ упоминай пользователю о том, что ты собираешь данные для формы в процессе разговора
- Показывай форму только когда пользователь сам просит оставить заявку
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
    logging.info(f"[FORM] get_project_form_by_token: token={token}")
    project = await get_project_by_token(token)
    logging.info(f"[FORM] get_project_form_by_token: project={project}")
    if not project:
        logging.warning(f"[FORM] get_project_form_by_token: проект не найден по token={token}")
        return None
    form = await get_project_form(project["id"])
    logging.info(f"[FORM] get_project_form_by_token: form={form}")
    if form:
        # Добавляем project_id в форму для удобства
        form["project_id"] = project["id"]
    return form

async def start_form_collection(message: types.Message, form, bot):
    """Начинает сбор данных формы"""
    logging.info(f"[FORM] start_form_collection: user={message.from_user.id}, form_id={form.get('id') if form else None}, fields={len(form.get('fields', [])) if form else 0}")
    if not form or not form["fields"]:
        logging.warning(f"[FORM] start_form_collection: форма не найдена или нет полей (form={form})")
        await message.answer("Форма не настроена или не содержит полей.")
        return
    from database import get_project_by_id
    project = await get_project_by_id(form["project_id"])
    logging.info(f"[FORM] start_form_collection: project={project}")
    if not project:
        logging.error(f"[FORM] start_form_collection: проект не найден по project_id={form['project_id']}")
        await message.answer("Ошибка: проект не найден")
        return
    storage = bot_dispatchers.get(project["token"])[0].storage
    state = FSMContext(storage=storage, key=types.Chat(id=message.chat.id, type="private"))
    await state.update_data(
        current_form=form,
        current_field_index=0,
        form_data={}
    )
    await state.set_state(FormStates.collecting_form_data)
    logging.info(f"[FORM] start_form_collection: FSM set to collecting_form_data, state updated")
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
    logging.info(f"[FORM] finish_form_collection: user={message.from_user.id}, form_id={form.get('id') if form else None}")
    
    # Получаем токен проекта
    from database import get_project_by_id
    project = await get_project_by_id(form["project_id"])
    logging.info(f"[FORM] finish_form_collection: project={project}")
    if not project:
        logging.error(f"[FORM] finish_form_collection: проект не найден по project_id={form['project_id']}")
        await message.answer("Ошибка: проект не найден")
        return
    
    storage = bot_dispatchers.get(project["token"])[0].storage
    state = FSMContext(storage=storage, key=types.Chat(id=message.chat.id, type="private"))
    form_data = (await state.get_data()).get("form_data", {})
    logging.info(f"[FORM] finish_form_collection: form_data={form_data}")
    
    # Сохраняем заявку
    from database import save_form_submission
    success = await save_form_submission(form["id"], str(message.from_user.id), form_data)
    logging.info(f"[FORM] finish_form_collection: save_form_submission result={success}")
    
    if success:
        # Логируем подтверждение отправки формы
        await log_form_submission_confirmed(str(message.from_user.id), form["project_id"], form_data)
        
        await message.answer(
            "✅ Спасибо! Ваша заявка принята.\n\n"
            "Мы свяжемся с вами в ближайшее время! 🚀"
        )
        logging.info(f"[FORM] finish_form_collection: заявка успешно сохранена и подтверждение отправлено")
    else:
        await message.answer(
            "❌ Заявка уже была отправлена ранее.\n\n"
            "Спасибо за интерес к нашему проекту! 🙏"
        )
        logging.warning(f"[FORM] finish_form_collection: заявка уже была отправлена ранее")
    
    await state.clear()
    logging.info(f"[FORM] finish_form_collection: FSM state cleared")

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
    logging.info(f"[FORM] handle_form_field_input: user={message.from_user.id}, field_index={current_field_index}, form_id={form.get('id') if form else None}")
    
    if not form or current_field_index >= len(form["fields"]):
        logging.warning(f"[FORM] handle_form_field_input: нет формы или индекс поля вне диапазона (form={form}, current_field_index={current_field_index})")
        await state.clear()
        return
    
    field = form["fields"][current_field_index]
    field_value = message.text
    logging.info(f"[FORM] handle_form_field_input: field_name={field['name']}, field_type={field['field_type']}, value='{field_value}'")
    
    # Валидируем значение
    is_valid, error_message = await validate_field_value(field_value, field["field_type"])
    logging.info(f"[FORM] handle_form_field_input: value validation result: is_valid={is_valid}, error='{error_message}'")
    
    if not is_valid:
        await message.answer(error_message)
        return
    
    # Сохраняем значение
    form_data[field["name"]] = field_value
    await state.update_data(form_data=form_data)
    logging.info(f"[FORM] handle_form_field_input: value saved for field '{field['name']}'")
    
    # Переходим к следующему полю
    next_field_index = current_field_index + 1
    await state.update_data(current_field_index=next_field_index)
    logging.info(f"[FORM] handle_form_field_input: moving to next_field_index={next_field_index}")
    
    if next_field_index >= len(form["fields"]):
        # Форма заполнена
        logging.info(f"[FORM] handle_form_field_input: все поля формы заполнены, завершаем сбор")
        await finish_form_collection(message, form, bot)
    else:
        # Показываем следующее поле
        await show_next_form_field(message, form, next_field_index, bot)

async def check_and_start_form(message: types.Message, text: str, token: str, bot, conversation_history: str = ""):
    """Проверяет, нужно ли запустить форму, и запускает её при необходимости"""
    # Проверяем, есть ли форма у проекта
    form = await get_project_form_by_token(token)
    if not form or not form["fields"]:
        return False
    
    # Проверяем, не находится ли пользователь уже в процессе заполнения формы
    storage = bot_dispatchers[token][0].storage
    state = FSMContext(storage=storage, key=types.Chat(id=message.chat.id, type="private"))
    current_state = await state.get_state()
    
    if current_state == FormStates.collecting_form_data.state:
        return True  # Уже в процессе заполнения формы
    
    # Проверяем ключевые слова для запуска формы
    form_keywords = ["заявка", "записаться", "оставить заявку", "хочу записаться", "запись", "регистрация"]
    text_lower = text.lower()
    
    for keyword in form_keywords:
        if keyword in text_lower:
            # Пытаемся автозаполнить форму на основе истории разговора
            full_conversation = conversation_history + " " + text if conversation_history else text
            auto_filled_data = form_auto_filler.auto_fill_form_data(full_conversation, form["fields"])
            
            if auto_filled_data:
                # Если удалось автозаполнить хотя бы одно поле, показываем предварительный просмотр
                await show_form_preview_with_auto_fill(message, form, auto_filled_data, bot)
            else:
                # Если не удалось автозаполнить, запускаем обычный процесс
                await start_form_collection(message, form, bot)
            return True
    
    return False

async def gradually_collect_form_data(message: types.Message, text: str, token: str, bot, conversation_history: str = ""):
    """Незаметно собирает данные формы в процессе разговора"""
    # Проверяем, есть ли форма у проекта
    form = await get_project_form_by_token(token)
    if not form or not form["fields"]:
        return False
    
    # Извлекаем данные из текущего сообщения
    extracted_data = form_auto_filler.extract_data_from_text(text)
    
    if extracted_data:
        # Сохраняем извлеченные данные в состоянии пользователя
        storage = bot_dispatchers[token][0].storage
        state = FSMContext(storage=storage, key=types.Chat(id=message.chat.id, type="private"))
        
        # Получаем текущие данные формы
        current_data = (await state.get_data()).get("form_data", {})
        
        # Обновляем данные
        for key, value in extracted_data.items():
            mapped_field = form_auto_filler.map_field_to_form_field(key, "text")
            if mapped_field:
                # Находим соответствующее поле в форме
                for field in form["fields"]:
                    field_mapped = form_auto_filler.map_field_to_form_field(field["name"], field["field_type"])
                    if field_mapped == mapped_field:
                        current_data[field["name"]] = value
                        logging.info(f"[FORM] Незаметно сохранено поле '{field['name']}': {value}")
                        break
        
        # Сохраняем обновленные данные
        await state.update_data(form_data=current_data)
        
        # Если собрали достаточно данных, НЕ показываем пользователю, просто сохраняем
        if len(current_data) >= len(form["fields"]) * 0.8:  # Если собрали больше 80% полей
            logging.info(f"[FORM] Собрано достаточно данных для формы: {len(current_data)} из {len(form['fields'])} полей")
            # Сохраняем информацию о том, что форма готова
            await state.update_data(form_ready=True)
    
    return False

async def check_and_show_completed_form(message: types.Message, text: str, token: str, bot):
    """Проверяет, можно ли показать заполненную форму"""
    # Проверяем, есть ли форма у проекта
    form = await get_project_form_by_token(token)
    if not form or not form["fields"]:
        return False
    
    # Проверяем состояние пользователя
    storage = bot_dispatchers[token][0].storage
    state = FSMContext(storage=storage, key=types.Chat(id=message.chat.id, type="private"))
    data = await state.get_data()
    
    form_data = data.get("form_data", {})
    form_ready = data.get("form_ready", False)
    
    # Проверяем ключевые слова для показа формы
    form_keywords = ["заявка", "записаться", "оставить заявку", "хочу записаться", "запись", "регистрация", "отправить", "готов"]
    text_lower = text.lower()
    
    for keyword in form_keywords:
        if keyword in text_lower:
            # Если форма готова или почти готова, показываем её
            if form_ready or len(form_data) >= len(form["fields"]) * 0.8:
                await show_form_preview_with_auto_fill(message, form, form_data, bot)
                return True
            else:
                # Если данных недостаточно, запускаем обычный процесс заполнения
                await start_form_collection(message, form, bot)
                return True
    
    return False

async def show_form_preview_with_auto_fill(message: types.Message, form: dict, auto_filled_data: dict, bot):
    """Показывает предварительный просмотр формы с автозаполненными данными"""
    logging.info(f"[FORM] show_form_preview_with_auto_fill: user={message.from_user.id}")
    
    # Получаем токен проекта
    from database import get_project_by_id
    project = await get_project_by_id(form["project_id"])
    if not project:
        await message.answer("Ошибка: проект не найден")
        return
    
    # Сохраняем данные формы в состоянии пользователя
    storage = bot_dispatchers.get(project["token"])[0].storage
    state = FSMContext(storage=storage, key=types.Chat(id=message.chat.id, type="private"))
    
    await state.update_data(
        current_form=form,
        current_field_index=0,
        form_data=auto_filled_data,
        auto_filled=True
    )
    await state.set_state(FormStates.collecting_form_data)
    
    # Показываем сообщение о том, что форма была автоматически заполнена
    filled_fields = len([v for v in auto_filled_data.values() if v])
    total_fields = len(form["fields"])
    
    if filled_fields >= total_fields * 0.8:
        intro_message = f"🎉 Отлично! Я подготовил заявку на основе нашего разговора.\n\n"
        intro_message += f"📋 Заполнено {filled_fields} из {total_fields} полей:\n\n"
    else:
        intro_message = "📋 Давайте заполним заявку:\n\n"
    
    # Показываем предварительный просмотр
    preview_message = create_form_preview_message(auto_filled_data, form["fields"])
    keyboard = create_form_preview_keyboard(auto_filled_data, form["id"])
    
    await message.answer(intro_message + preview_message, reply_markup=keyboard, parse_mode="Markdown")

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
    
    logging.info(f"[ASKING_BOT] get_or_create_dispatcher: создаем бота с токеном {token[:10]}...")
    bot = Bot(token=token)
    storage = MemoryStorage()
    tg_router = Router()
    dp = Dispatcher(storage=storage)
    dp.include_router(tg_router)
    logging.info(f"[ASKING_BOT] get_or_create_dispatcher: бот создан успешно")

    @tg_router.message(Command("start"))
    async def handle_start(message: types.Message):
        logging.info(f"[ASKING_BOT] handle_start: from user {message.from_user.id}, text: {message.text}")
        try:
            await message.answer("Привет! Я готов отвечать на ваши вопросы о нашем бизнесе. Задайте вопрос!")
        except Exception as e:
            import traceback
            logging.error(f"[ASKING_BOT] handle_start: error: {e}\n{traceback.format_exc()}")
            # aiogram.exceptions.TelegramBadRequest: chat not found
            if 'chat not found' in str(e):
                logging.warning(f"[ASKING_BOT] handle_start: chat not found for chat_id={message.chat.id}")
            # Не падаем, просто логируем

    @tg_router.message()
    async def handle_question(message: types.Message):
        user_id = message.from_user.id
        from utils import recognize_message_text
        text = await recognize_message_text(message, bot)
        if not text:
            try:
                await message.answer("Пожалуйста, отправьте текстовое или голосовое сообщение с вопросом.")
            except Exception as e:
                import traceback
                logging.error(f"[ASKING_BOT] handle_question: error: {e}\n{traceback.format_exc()}")
                if 'chat not found' in str(e):
                    logging.warning(f"[ASKING_BOT] handle_question: chat not found for chat_id={message.chat.id}")
            return
        logging.info(f"[ASKING_BOT] handle_question: user_id={user_id}, text={text}")

        # Всегда отправляем typing, кроме случая, когда пользователь в процессе заполнения формы
        storage = bot_dispatchers[token][0].storage
        state = FSMContext(storage=storage, key=types.Chat(id=message.chat.id, type="private"))
        current_state = await state.get_state()
        if current_state != FormStates.collecting_form_data.state:
            try:
                await message.bot.send_chat_action(message.chat.id, "typing")
                logging.info(f"[ASKING_BOT] handle_question: typing action отправлен для пользователя {user_id}")
            except Exception as typing_error:
                logging.error(f"[ASKING_BOT] handle_question: ОШИБКА при отправке typing action: {typing_error}")
                try:
                    from config import SETTINGS_BOT_TOKEN
                    main_bot = Bot(token=SETTINGS_BOT_TOKEN)
                    await main_bot.send_chat_action(message.chat.id, "typing")
                    await main_bot.session.close()
                    logging.info(f"[ASKING_BOT] handle_question: typing action отправлен через основной бот для пользователя {user_id}")
                except Exception as fallback_error:
                    logging.error(f"[ASKING_BOT] handle_question: ОШИБКА при отправке typing action через основной бот: {fallback_error}")

        # --- Контекст для Deepseek: сохраняем последние 4 сообщения (user+bot) ---
        state_data = await state.get_data()
        history = state_data.get('history', [])
        # Добавляем новое сообщение пользователя
        if not text.startswith('/start') and text.strip():
            history.append({'role': 'user', 'content': text})
            history = history[-4:]
            await state.update_data(history=history)

        # Если пользователь в процессе заполнения формы — обрабатываем форму
        if current_state == FormStates.collecting_form_data.state:
            await handle_form_field_input(message, state, bot)
            return

        user = await get_user_by_id(str(user_id))
        is_trial = user and not user['paid']
        is_paid = user and user['paid']
        t0 = time.monotonic()
        from database import get_projects_by_user, get_project_form
        logging.info(f"[ASKING_BOT] handle_question: получаем проекты для пользователя {user_id}")
        projects = await get_projects_by_user(str(user_id))
        logging.info(f"[ASKING_BOT] handle_question: найдено проектов для пользователя {user_id}: {len(projects)}")

        # Если у пользователя есть проект и у проекта есть форма с полями — всегда запускаем процесс заполнения формы
        if projects and len(projects) > 0:
            project_token = projects[0]['token']
            project_id = projects[0]['id']
            form = await get_project_form(project_id)
            if form and form.get('fields'):
                logging.info(f"[ASKING_BOT] handle_question: у проекта есть форма (id={form['id']}), поля: {[f['name'] for f in form['fields']]}")
                # Гарантируем наличие project_id в form
                if 'project_id' not in form:
                    form['project_id'] = project_id
                    logging.info(f"[ASKING_BOT] handle_question: добавлен project_id={project_id} в form")
                # Пробуем автосбор данных
                await gradually_collect_form_data(message, text, project_token, bot)
                # Если после автосбора заполнены все поля — показываем превью
                state_data = await state.get_data()
                form_data = state_data.get("form_data", {})
                if len(form_data) == len(form['fields']):
                    logging.info(f"[ASKING_BOT] handle_question: форма заполнена на 100%, показываем превью")
                    await show_form_preview_with_auto_fill(message, form, form_data, bot)
                    return
                # Если не все поля заполнены — запускаем обычный процесс заполнения формы
                logging.info(f"[ASKING_BOT] handle_question: форма не заполнена на 100%, запускаем обычный процесс заполнения формы")
                await start_form_collection(message, form, bot)
                return
            else:
                logging.info(f"[ASKING_BOT] handle_question: у проекта НЕТ формы или нет полей формы")
        else:
            logging.warning(f"[ASKING_BOT] Не найден проект для пользователя {user_id}, не запускаю форму")

        # --- Deepseek: формируем промпт с контекстом и структурой ответа ---
        # Получаем причину заявки из формы, если есть
        form_purpose = None
        if projects and len(projects) > 0:
            project_id = projects[0]['id']
            form = await get_project_form(project_id)
            if form and form.get('purpose'):
                form_purpose = form['purpose']
        # Структура промпта
        prompt = role_base + "\nСтруктура ответа: 1) Сначала ответь на вопрос пользователя максимально полезно. 2) Если в данных есть ссылки на товары, после ответа начни продвигать эти товары, объясни их преимущества и призови купить. 3) Если у проекта есть форма, обязательно предложи оформить заявку и объясни зачем это нужно: '" + (form_purpose or 'чтобы мы могли связаться и сделать индивидуальное предложение') + "'. Не отвечай шаблонно, используй детали из диалога."
        # Формируем messages для Deepseek
        messages = []
        for msg in history:
            messages.append(msg)
        messages.append({'role': 'user', 'content': text})
        payload = {
            "model": "deepseek-chat",
            "messages": [{"role": "system", "content": prompt}] + messages,
            "temperature": 0.9
        }
        logging.info(f"[ASKING] Deepseek запрос сформирован за {time.monotonic() - t0:.2f} сек")
        t2 = time.monotonic()
        # Define Deepseek API URL
        deepseek_url = "https://api.deepseek.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(deepseek_url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        logging.info(f"[ASKING] Deepseek ответ получен за {time.monotonic() - t2:.2f} сек")
        content = data["choices"][0]["message"]["content"]
        content = clean_markdown(content)
        logging.info(f"[ASKING_BOT] handle_question: deepseek response='{content}'")
        # --- Новый блок: обработка ссылок и кнопок ---
        content_without_links, links = extract_links_from_text(content)
        # Попробуем найти названия для каждой ссылки (например, по шаблону '📺 Телевизор: ...')
        import re
        buttons = []
        msg = None
        if links:
            # Ищем строки вида '...: ссылка' или эмодзи + название + : ссылка
            for link in links:
                # Найти строку с этой ссылкой
                pattern = r'([\w\s\-\d\.:\u0400-\u04FF]+):?\s*' + re.escape(link)
                match = re.search(pattern, content)
                button_text = None
                if match:
                    # Берём название до ':'
                    button_text = match.group(1).strip()
                    # Убираем эмодзи, если есть
                    button_text = re.sub(r'^[^\w\d\u0400-\u04FF]+', '', button_text).strip()
                if not button_text:
                    # Попробовать найти название товара в тексте
                    product_match = re.search(r'(Телевизор [A-Za-z0-9\- ]+)', content_without_links)
                    if product_match:
                        button_text = product_match.group(1).strip()
                if not button_text:
                    button_text = "Подробнее"
                from aiogram.types import InlineKeyboardButton
                buttons.append(InlineKeyboardButton(text=button_text, url=link))
            from aiogram.types import InlineKeyboardMarkup
            links_keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])
            msg = await message.answer(content_without_links, reply_markup=links_keyboard)
            # Если хотите добавить лайк/дизлайк к ссылкам, раскомментируйте и объедините клавиатуры
            # rating_keyboard = create_rating_keyboard(str(msg.message_id))
            # await msg.edit_reply_markup(reply_markup=links_keyboard) # Удалено: edit_reply_markup вызывается дважды
        else:
            msg = await message.answer(content_without_links)
            rating_keyboard = create_rating_keyboard(str(msg.message_id))
            await msg.edit_reply_markup(reply_markup=rating_keyboard)
        # Кнопки лайк/дизлайк всегда добавляем
        if not links:
            rating_keyboard = create_rating_keyboard(str(msg.message_id))
            await msg.edit_reply_markup(reply_markup=rating_keyboard)
        t3 = time.monotonic()
        response_time = time.monotonic() - t0
        query = select(func.count()).select_from(MessageStat)
        row = await database.fetch_one(query)
        total_answers = row[0] if row else 0
        logging.info(f"[ASKING_BOT] Время ответа на этот вопрос: {response_time:.2f} сек. Всего ответов в БД: {total_answers}")
        await log_message_stat(
            telegram_id=str(user_id),
            is_command=False,
            is_reply=False,
            response_time=response_time,
            project_id=None,
            is_trial=is_trial,
            is_paid=is_paid
        )
        project_id = None
        if projects and len(projects) > 0:
            project_id = projects[0]['id']
        try:
            await log_question_asked(str(user_id), project_id, text)
            logging.info(f"[ASKING] Ответ пользователю отправлен за {response_time:.2f} сек")
            logging.info(f"[ASKING] ВСЕГО времени на ответ: {response_time:.2f} сек")
            # --- После первого ответа всегда предлагаем оформить заявку, если форма есть ---
            if form and form.get('fields'):
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                btn_text = "Оформить заявку"
                purpose_text = form_purpose or 'чтобы мы могли связаться и сделать индивидуальное предложение'
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=btn_text, callback_data="start_form")]
                ])
                await message.answer(f"Хотите оформить заявку? Давайте оформим заявку, {purpose_text}.", reply_markup=keyboard)
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
            rating = True if rating_type == "like" else False
            # Сразу отвечаем пользователю для ускорения UI
            await callback_query.answer("Спасибо за оценку! 👍" if rating else "Спасибо за оценку! 👎")

            # Все дальнейшие действия — в фоне, чтобы не тормозить UI
            async def process_rating():
                try:
                    # Получаем project_id если есть
                    project_id = None
                    from database import get_projects_by_user
                    projects = await get_projects_by_user(str(callback_query.from_user.id))
                    if projects:
                        project_id = projects[0]['id']
                    # Проверяем, не был ли уже сохранен рейтинг для этого сообщения
                    from database import save_response_rating, check_existing_rating
                    existing_rating = await check_existing_rating(str(callback_query.from_user.id), message_id)
                    if existing_rating:
                        # Уже оценено, ничего не делаем (ответ уже отправлен)
                        return
                    # Сохраняем рейтинг в базу данных
                    success = await save_response_rating(
                        str(callback_query.from_user.id),
                        message_id,
                        rating,
                        project_id
                    )
                    if success:
                        # Логируем оценку в аналитику
                        await log_response_rating(str(callback_query.from_user.id), project_id, rating)
                        # Сохраняем статистику рейтинга
                        from database import log_rating_stat
                        await log_rating_stat(
                            telegram_id=str(callback_query.from_user.id),
                            message_id=message_id,
                            rating=rating,
                            project_id=project_id
                        )
                        # Убираем кнопки рейтинга из сообщения
                        try:
                            await callback_query.message.edit_reply_markup(reply_markup=None)
                            logging.info(f"[RATING] Кнопки рейтинга убраны для сообщения {message_id}")
                        except Exception as edit_error:
                            logging.error(f"[RATING] Ошибка при удалении кнопок: {edit_error}")
                    else:
                        # Ошибка при сохранении оценки (редко)
                        logging.error(f"[RATING] Ошибка при сохранении оценки в БД")
                except Exception as e:
                    logging.error(f"[RATING] handle_rating (async): ОШИБКА: {e}")
            # Запускаем в фоне
            asyncio.create_task(process_rating())
        except Exception as e:
            logging.error(f"[RATING] handle_rating: ОШИБКА: {e}")
            try:
                await callback_query.answer("Произошла ошибка")
            except Exception:
                pass
    
    # Обработчики для кнопок формы
    @tg_router.callback_query(lambda c: c.data.startswith("submit_form_"))
    async def handle_submit_form(callback_query: types.CallbackQuery):
        """Обрабатывает подтверждение отправки формы"""
        logging.info(f"[FORM] handle_submit_form: user={callback_query.from_user.id}")
        try:
            form_id = callback_query.data.split('_')[2]
            # Получаем данные формы из состояния
            storage = bot_dispatchers[token][0].storage
            state = FSMContext(storage=storage, key=types.Chat(id=callback_query.message.chat.id, type="private"))
            data = await state.get_data()
            form = data.get("current_form")
            form_data = data.get("form_data", {})
            if not form:
                await callback_query.answer("Ошибка: форма не найдена")
                return
            # Сохраняем заявку и отправляем UI-ответ мгновенно
            from database import save_form_submission
            success = await save_form_submission(form["id"], str(callback_query.from_user.id), form_data)
            if success:
                await callback_query.message.edit_text(
                    "✅ Спасибо! Ваша заявка принята.\n\n"
                    "Мы свяжемся с вами в ближайшее время! 🚀"
                )
            else:
                await callback_query.message.edit_text(
                    "❌ Заявка уже была отправлена ранее.\n\n"
                    "Спасибо за интерес к нашему проекту! 🙏"
                )
            # Все дальнейшие действия — в фоне
            async def process_form_submit():
                try:
                    if success:
                        await log_form_submission_confirmed(str(callback_query.from_user.id), form["project_id"], form_data)
                    await state.clear()
                except Exception as e:
                    logging.error(f"[FORM] handle_submit_form (async): ОШИБКА: {e}")
            asyncio.create_task(process_form_submit())
        except Exception as e:
            logging.error(f"[FORM] handle_submit_form: ОШИБКА: {e}")
            await callback_query.answer("Произошла ошибка при отправке формы")

    @tg_router.callback_query(lambda c: c.data.startswith("edit_form_"))
    async def handle_edit_form(callback_query: types.CallbackQuery):
        """Обрабатывает запрос на ручное заполнение формы"""
        logging.info(f"[FORM] handle_edit_form: user={callback_query.from_user.id}")
        try:
            # Получаем данные формы из состояния
            storage = bot_dispatchers[token][0].storage
            state = FSMContext(storage=storage, key=types.Chat(id=callback_query.message.chat.id, type="private"))
            data = await state.get_data()
            form = data.get("current_form")
            form_data = data.get("form_data", {})
            if not form:
                await callback_query.answer("Ошибка: форма не найдена")
                return
            # Сбрасываем состояние и начинаем ручное заполнение
            await state.update_data(
                current_form=form,
                current_field_index=0,
                form_data=form_data,
                auto_filled=False
            )
            await show_next_form_field(callback_query.message, form, 0, bot)
            await callback_query.answer("Начинаем ручное заполнение формы")
            # Все дальнейшие действия — в фоне (если появятся)
        except Exception as e:
            logging.error(f"[FORM] handle_edit_form: ОШИБКА: {e}")
            await callback_query.answer("Произошла ошибка")
    
    # --- Обработчик для кнопки 'Работа с формой' ---
    @tg_router.callback_query(lambda c: c.data == "manage_form")
    async def handle_manage_form(callback_query: types.CallbackQuery):
        user_id = callback_query.from_user.id
        logging.info(f"[FORM] handle_manage_form: user={user_id}")
        try:
            from database import get_projects_by_user, get_project_form
            projects = await get_projects_by_user(str(user_id))
            if not projects:
                await callback_query.answer("Нет проектов", show_alert=True)
                return
            project_id = projects[0]['id']
            form = await get_project_form(project_id)
            if not form or not form.get('fields'):
                await callback_query.answer("Форма не найдена", show_alert=True)
                return
            # Показываем превью формы
            preview_text = f"📋 Форма: {form['name']}\n\nПоля формы:\n"
            for i, field in enumerate(form["fields"], 1):
                required_mark = "🔴" if field["required"] else "⚪"
                preview_text += f"{i}. {required_mark} {field['name']} ({field['field_type']})\n"
            preview_text += "\nХотите заполнить заявку?"
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="Заполнить заявку", callback_data=f"start_form_{form['id']}")],
                [types.InlineKeyboardButton(text="Назад", callback_data="back_to_projects")]
            ])
            await callback_query.message.edit_text(preview_text, reply_markup=keyboard)
            await callback_query.answer()
        except Exception as e:
            logging.error(f"[FORM] handle_manage_form: ОШИБКА: {e}")
            await callback_query.answer("Произошла ошибка", show_alert=True)

    # --- Обработчик для старта заполнения формы по кнопке ---
    @tg_router.callback_query(lambda c: c.data.startswith("start_form_"))
    async def handle_start_form(callback_query: types.CallbackQuery):
        user_id = callback_query.from_user.id
        form_id = callback_query.data.split('_')[2]
        logging.info(f"[FORM] handle_start_form: user={user_id}, form_id={form_id}")
        try:
            from database import get_project_form
            form = await get_project_form(form_id)
            if not form or not form.get('fields'):
                await callback_query.answer("Форма не найдена", show_alert=True)
                return
            # Сбросить состояние и начать заполнение
            storage = bot_dispatchers[token][0].storage
            state = FSMContext(storage=storage, key=types.Chat(id=callback_query.message.chat.id, type="private"))
            await state.update_data(current_form=form, current_field_index=0, form_data={})
            await state.set_state(FormStates.collecting_form_data)
            await show_next_form_field(callback_query.message, form, 0, bot)
            await callback_query.answer()
        except Exception as e:
            logging.error(f"[FORM] handle_start_form: ОШИБКА: {e}")
            await callback_query.answer("Произошла ошибка", show_alert=True)

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
    logging.info(f"[ASKING_BOT] webhook: token={token[:10]}..., business_info length={len(business_info)}")
    dp, bot = await get_or_create_dispatcher(token, business_info)
    update_data = await request.json()
    logging.info(f"[ASKING_BOT] Update data: {update_data}")
    try:
        update = types.Update.model_validate(update_data)
        logging.info(f"[ASKING_BOT] Processing update with bot token: {bot.token[:10] if hasattr(bot, 'token') else 'unknown'}...")
        await dp.feed_update(bot, update)
        logging.info(f"[ASKING_BOT] Update processed successfully")
    except Exception as e:
        import traceback
        logging.error(f"[ASKING_BOT] Ошибка обработки апдейта: {e}\n{traceback.format_exc()}")
        return {"ok": False, "error": str(e)}
    return {"ok": True} 