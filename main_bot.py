from fastapi import APIRouter, Request
from aiogram import Bot, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router, Dispatcher
from database import (
    get_project_by_start_param, log_message_stat, get_user_by_id, get_project_form, 
    record_project_visit, get_client_projects, get_client_current_project, get_project_by_id, get_payments, get_project_by_short_link
)
from aiogram.filters import Command
import logging
import httpx
from config import DEEPSEEK_API_KEY, MAIN_BOT_TOKEN, TRIAL_DAYS
import time
from datetime import datetime, timezone, timedelta
from form_auto_fill import create_form_preview_keyboard, create_form_preview_message, create_form_fill_keyboard, create_form_submission_summary
from typing import Optional
import re

router = APIRouter()

# Состояния для сбора данных формы
class FormStates:
    collecting_form_data = None # This class is no longer used, but keeping it as per instructions

# Основной бот
main_bot = Bot(token=MAIN_BOT_TOKEN)
storage = MemoryStorage()
main_dispatcher = Dispatcher(storage=storage)

# Создаем router для обработчиков
main_router = Router()
main_dispatcher.include_router(main_router)

# Базовый промпт для роли
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
- Сначала ответь на вопрос пользователя максимально полезно
- Если в данных есть ссылки на товары, после ответа начни продвигать эти товары, объясни их преимущества и недостатки и призови купить
- Если у проекта есть форма, обязательно предложи оформить заявку и объясни зачем это нужно

В КОНЦЕ ОТВЕТА ОБЯЗАТЕЛЬНО добавь блок:
[АНАЛИТИКА:краткая_тема_запроса]

Примеры тем:
- цена_и_стоимость
- доставка_и_сроки  
- гарантия_и_возврат
- технические_характеристики
- сравнение_с_конкурентами
- акции_и_скидки
- отзывы_клиентов
- оформление_заказа
- общие_вопросы
- жалобы_и_проблемы
"""

def create_projects_keyboard(client_projects: list) -> types.InlineKeyboardMarkup:
    """Создает клавиатуру для переключения между проектами"""
    keyboard = []
    
    for project in client_projects:
        # Показываем название проекта и количество посещений
        text = f"🏢 {project['project_name']} ({project['visit_count']} раз)"
        callback_data = f"switch_to_project_{project['id']}"
        keyboard.append([types.InlineKeyboardButton(text=text, callback_data=callback_data)])
    
    # Добавляем кнопку для показа текущего проекта
    if client_projects:
        keyboard.append([types.InlineKeyboardButton(text="📋 Показать текущий проект", callback_data="show_current_project")])
    
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)

def extract_theme_from_response(response_text: str) -> Optional[str]:
    """Извлекает тему из ответа AI"""
    match = re.search(r'\[АНАЛИТИКА:(.+?)\]', response_text)
    return match.group(1) if match else None

async def save_query_statistics(project_id: str, user_id: int, original_query: str, theme: str, timestamp: datetime):
    """Сохраняет статистику запроса для аналитики"""
    try:
        from database import save_query_theme
        await save_query_theme(
            project_id=project_id,
            user_id=str(user_id),
            original_query=original_query,
            theme=theme,
            timestamp=timestamp
        )
        logging.info(f"[STATS] Сохранена статистика: project={project_id}, user={user_id}, theme={theme}")
    except Exception as e:
        logging.error(f"[STATS] Ошибка сохранения статистики: {e}")

async def send_daily_insights_to_owner(project_id: str):
    """Отправляет ежедневные инсайты владельцу проекта"""
    try:
        from database import get_project_by_id, get_daily_themes
        from settings_bot import settings_bot
        
        # Получаем информацию о проекте
        project = await get_project_by_id(project_id)
        if not project:
            return
        
        # Получаем темы за последние 24 часа
        themes = await get_daily_themes(project_id)
        
        if not themes:
            return
        
        # Анализируем локально
        theme_counts = {}
        for theme in themes:
            theme_counts[theme['theme']] = theme_counts.get(theme['theme'], 0) + 1
        
        # Сортируем по популярности
        sorted_themes = sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)
        
        # Формируем отчет
        report = f"📊 **Ежедневная статистика проекта {project['project_name']}:**\n\n"
        for theme, count in sorted_themes[:5]:  # Только топ-5
            theme_display = theme.replace('_', ' ').title()
            report += f"• {theme_display}: {count} запросов\n"
        
        report += f"\n📈 Всего запросов: {len(themes)}"
        report += f"\n🕐 Период: последние 24 часа"
        
        # Отправляем владельцу проекта
        owner_telegram_id = project['telegram_id']
        await settings_bot.send_message(
            chat_id=owner_telegram_id,
            text=report,
            parse_mode="Markdown"
        )
        
        logging.info(f"[INSIGHTS] Отправлены инсайты владельцу проекта {project_id}")
        
    except Exception as e:
        logging.error(f"[INSIGHTS] Ошибка отправки инсайтов: {e}")

async def check_project_accessibility(project: dict) -> bool:
    """Проверяет доступность проекта (trial/paid период)"""
    try:
        user = await get_user_by_id(project["telegram_id"])
        if not user:
            return False
        
        current_time = datetime.now(timezone.utc)
        
        if user["paid"]:
            # Для оплаченных пользователей
            payments = await get_payments()
            user_payments = [p for p in payments if str(p['telegram_id']) == project["telegram_id"] and p['status'] == 'confirmed']
            
            if not user_payments:
                return False
                
            last_payment = max(user_payments, key=lambda x: x['paid_at'])
            
            # Преобразуем дату платежа
            paid_at = last_payment['paid_at']
            if isinstance(paid_at, str):
                paid_at = paid_at.replace('Z', '+00:00') if 'Z' in paid_at else paid_at
                last_payment_date = datetime.fromisoformat(paid_at)
            else:
                last_payment_date = paid_at
            
            # Делаем оба datetime aware
            if last_payment_date.tzinfo is None:
                last_payment_date = last_payment_date.replace(tzinfo=timezone.utc)
            
            return (current_time - last_payment_date).days <= 30
            
        else:
            # Для trial пользователей
            if not user.get('start_date'):
                return False
                
            start_date = user["start_date"]
            if isinstance(start_date, str):
                start_date = start_date.replace('Z', '+00:00') if 'Z' in start_date else start_date
                start_date = datetime.fromisoformat(start_date)
            
            if start_date.tzinfo is None:
                start_date = start_date.replace(tzinfo=timezone.utc)
            
            trial_end = start_date + timedelta(days=TRIAL_DAYS)
            return current_time < trial_end
            
    except Exception as e:
        logging.error(f"[MAIN_BOT] Error checking project accessibility: {e}")
        return False

@main_router.message(Command("start"))
async def start_command(message: types.Message):
    """Обрабатывает команду /start с параметром проекта"""
    logging.info(f"[MAIN_BOT] /start command from user {message.from_user.id}")
    logging.info(f"[MAIN_BOT] Full message text: {message.text}")
    
    # Получаем параметр start
    start_param = message.text.split()[1] if len(message.text.split()) > 1 else None
    logging.info(f"[MAIN_BOT] Start param: {start_param}")
    
    if not start_param:
        # Если нет параметра, показываем список проектов клиента
        client_telegram_id = str(message.from_user.id)
        client_projects = await get_client_projects(client_telegram_id)
        
        if client_projects:
            # У клиента есть проекты, показываем их
            message_text = "👋 Добро пожаловать! Выберите проект для работы:\n\n"
            for i, project in enumerate(client_projects, 1):
                message_text += f"🏢 **{i}. {project['project_name']}**\n"
                message_text += f"   📅 Посещений: {project['visit_count']}\n"
                message_text += f"   🕐 Последний раз: {project['last_visit'].strftime('%d.%m.%Y %H:%M')}\n\n"
            
            message_text += "💡 Используйте кнопки ниже для выбора проекта:"
            
            # Создаем клавиатуру с проектами
            keyboard = create_projects_keyboard(client_projects)
            await message.answer(message_text, reply_markup=keyboard, parse_mode="Markdown")
        else:
            # У клиента нет проектов
            await message.answer("👋 Добро пожаловать! Перейдите по ссылке на любой проект, чтобы начать работу.")
        return
    
    try:
        # Получаем проект по короткой ссылке
        logging.info(f"[MAIN_BOT] Looking for project with short link: {start_param}")
        project = await get_project_by_short_link(start_param)
        
        if not project:
            logging.warning(f"[MAIN_BOT] Project not found for short link: {start_param}")
            await message.answer("❌ Проект не найден. Проверьте ссылку.")
            return
        
        logging.info(f"[MAIN_BOT] Project found: {project['project_name']} (ID: {project['id']})")
        
        # Проверяем доступность проекта
        accessibility = await check_project_accessibility(project)
        logging.info(f"[MAIN_BOT] Project accessibility: {accessibility}")
        
        if not accessibility:
            await message.answer("❌ Проект временно недоступен. Обратитесь к владельцу проекта.")
            return
        
        # Записываем посещение проекта
        await record_project_visit(str(message.from_user.id), project["id"])
        logging.info(f"[MAIN_BOT] Project visit recorded for user {message.from_user.id}")
        
        # Сохраняем информацию о проекте в контексте пользователя
        await storage.set_data(
            key=f"user:{message.from_user.id}",
            data={"current_project": project}
        )
        logging.info(f"[MAIN_BOT] Project data saved to storage for user {message.from_user.id}")
        
        # Отправляем приветственное сообщение
        welcome_message = project.get("welcome_message") or f"👋 Добро пожаловать в проект **{project['project_name']}**!\n\nЯ готов ответить на ваши вопросы о бизнесе."
        
        await message.answer(welcome_message, parse_mode="Markdown")
        logging.info(f"[MAIN_BOT] Welcome message sent to user {message.from_user.id}")
        
    except Exception as e:
        logging.error(f"[MAIN_BOT] Error in start_command: {e}")
        await message.answer("❌ Произошла ошибка при запуске проекта. Попробуйте позже.")

@main_router.message(Command("projects"))
async def projects_command(message: types.Message):
    """Показывает список проектов, которые посещал клиент"""
    logging.info(f"[MAIN_BOT] /projects command from user {message.from_user.id}")
    
    client_telegram_id = str(message.from_user.id)
    client_projects = await get_client_projects(client_telegram_id)
    
    if not client_projects:
        await message.answer("📋 У вас пока нет посещенных проектов. Перейдите по ссылке на любой проект, чтобы начать работу!")
        return
    
    # Получаем текущий активный проект
    current_project = await get_client_current_project(client_telegram_id)
    
    message_text = "🏢 **Ваши проекты:**\n\n"
    
    for i, project in enumerate(client_projects, 1):
        # Отмечаем текущий проект
        current_marker = "📍 " if current_project and current_project["id"] == project["id"] else "🏢 "
        message_text += f"{current_marker}**{i}. {project['project_name']}**\n"
        message_text += f"   📅 Посещений: {project['visit_count']}\n"
        message_text += f"   🕐 Последний раз: {project['last_visit'].strftime('%d.%m.%Y %H:%M')}\n\n"
    
    message_text += "💡 Используйте кнопки ниже для переключения между проектами:"
    
    # Создаем клавиатуру с проектами
    keyboard = create_projects_keyboard(client_projects)
    await message.answer(message_text, reply_markup=keyboard)

@main_router.message()
async def handle_message(message: types.Message):
    """Обработчик всех сообщений"""
    logging.info(f"[MAIN_BOT] Message from user {message.from_user.id}: {message.text}")
    
    # Получаем текущий проект из контекста
    chat_data = await storage.get_data(
        key=f"user:{message.from_user.id}"
    )
    
    current_project = chat_data.get("current_project")
    if not current_project:
        # Если нет текущего проекта в контексте, пробуем получить из истории
        client_telegram_id = str(message.from_user.id)
        current_project = await get_client_current_project(client_telegram_id)
        
        if current_project:
            # Сохраняем в контекст
            await storage.set_data(
                key=f"user:{message.from_user.id}",
                data={"current_project": current_project}
            )
        else:
            await message.answer("❌ Сначала запустите бота командой /start с ID проекта или используйте /projects для просмотра ваших проектов")
            return
    
    # Проверяем доступность проекта
    if not await check_project_accessibility(current_project):
        await message.answer("❌ Проект временно недоступен. Свяжитесь с владельцем для продления подписки.")
        return
    
    start_time = time.time()
    
    try:
        # Формируем промпт для AI
        business_info = current_project["business_info"]
        prompt = f"{role_base}\n\nИнформация о бизнесе:\n{business_info}\n\nВопрос клиента: {message.text}"
        
        # Получаем ответ от AI
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                    "max_tokens": 1000
                },
                timeout=30.0
            )
            
            if response.status_code == 200:
                ai_response = response.json()["choices"][0]["message"]["content"]
                
                # Извлекаем тему из ответа AI
                theme = extract_theme_from_response(ai_response)
                if theme:
                    await save_query_statistics(current_project["id"], message.from_user.id, message.text, theme, datetime.now(timezone.utc))
                    logging.info(f"[MAIN_BOT] Theme extracted: {theme}")
                    # Убираем аналитический блок из ответа пользователю
                    ai_response = ai_response.split('[АНАЛИТИКА:')[0].strip()
                
                # Проверяем, есть ли форма у проекта
                form = await get_project_form(current_project["id"])
                if form:
                    # Добавляем предложение оформить заявку
                    ai_response += "\n\n📝 Хотите оформить заявку? У нас есть удобная форма для сбора информации."
                
                await message.answer(ai_response)
                
                # Логируем статистику
                user = await get_user_by_id(current_project["telegram_id"])
                response_time = time.time() - start_time
                await log_message_stat(
                    telegram_id=message.from_user.id,
                    is_command=False,
                    is_reply=True,
                    response_time=response_time,
                    project_id=current_project["id"],
                    is_trial=not user["paid"] if user else True,
                    is_paid=user["paid"] if user else False
                )
                
            else:
                await message.answer("❌ Извините, произошла ошибка при обработке вашего вопроса. Попробуйте позже.")
                logging.error(f"[MAIN_BOT] AI API error: {response.status_code} - {response.text}")
                
    except Exception as e:
        await message.answer("❌ Произошла ошибка при обработке сообщения. Попробуйте позже.")
        logging.error(f"[MAIN_BOT] Error processing message: {e}")

# Обработчики для форм
@main_router.callback_query()
async def handle_callback(callback: types.CallbackQuery):
    """Обработчик callback запросов"""
    logging.info(f"[MAIN_BOT] Callback from user {callback.from_user.id}: {callback.data}")
    
    if callback.data == "show_form":
        # Показываем форму
        chat_data = await storage.get_data(
            key=f"user:{callback.from_user.id}"
        )
        
        current_project = chat_data.get("current_project")
        if not current_project:
            await callback.answer("❌ Проект не найден")
            return
        
        form = await get_project_form(current_project["id"])
        if form:
            form_message = create_form_preview_message(form)
            await callback.message.edit_text(form_message, reply_markup=None)
        else:
            await callback.answer("❌ Форма не найдена")
    
    elif callback.data.startswith("switch_to_project_"):
        # Переключение на другой проект
        project_id = callback.data.replace("switch_to_project_", "")
        client_telegram_id = str(callback.from_user.id)
        
        # Получаем информацию о проекте
        project = await get_project_by_id(project_id)
        
        if not project:
            await callback.answer("❌ Проект не найден")
            return
        
        # Проверяем доступность проекта
        if not await check_project_accessibility(project):
            await callback.answer("❌ Проект временно недоступен")
            return
        
        # Записываем новое посещение
        await record_project_visit(client_telegram_id, project["id"])
        
        # Обновляем контекст пользователя
        await storage.set_data(
            key=f"user:{callback.from_user.id}",
            data={"current_project": project}
        )
        
        # Отправляем сообщение о переключении
        switch_msg = f"🔄 Переключились на проект **{project['project_name']}**\n\n"
        switch_msg += project.get("welcome_message") or f"👋 Добро пожаловать в {project['project_name']}!\n\nЯ готов помочь вам с любыми вопросами о нашем бизнесе."
        
        # Проверяем, есть ли форма у проекта
        form = await get_project_form(project["id"])
        if form:
            switch_msg += "\n\n📝 Также вы можете оформить заявку через нашу форму."
            keyboard = create_form_preview_keyboard()
            await callback.message.edit_text(switch_msg, reply_markup=keyboard)
        else:
            await callback.message.edit_text(switch_msg, reply_markup=None)
        
        await callback.answer(f"✅ Переключились на {project['project_name']}")
    
    elif callback.data == "show_current_project":
        # Показываем информацию о текущем проекте
        chat_data = await storage.get_data(
            bot=main_bot,
            key=f"user:{callback.from_user.id}"
        )
        
        current_project = chat_data.get("current_project")
        if not current_project:
            await callback.answer("❌ Текущий проект не найден")
            return
        
        project_info = f"📍 **Текущий проект: {current_project['project_name']}**\n\n"
        project_info += current_project.get("welcome_message") or f"👋 Добро пожаловать в {current_project['project_name']}!\n\nЯ готов помочь вам с любыми вопросами о нашем бизнесе."
        
        # Проверяем, есть ли форма у проекта
        form = await get_project_form(current_project["id"])
        if form:
            project_info += "\n\n📝 Также вы можете оформить заявку через нашу форму."
            keyboard = create_form_preview_keyboard()
            await callback.message.edit_text(project_info, reply_markup=keyboard)
        else:
            await callback.message.edit_text(project_info, reply_markup=None)
        
        await callback.answer("✅ Показан текущий проект")
    
    await callback.answer()

# Функция для запуска webhook
async def set_main_bot_webhook():
    """Устанавливает webhook для основного бота"""
    try:
        from config import SERVER_URL
        if SERVER_URL:
            webhook_url = f"{SERVER_URL}/webhook/main"
            logging.info(f"[MAIN_BOT] Attempting to set webhook to {webhook_url}")
            
            # Сначала удаляем старый webhook
            await main_bot.delete_webhook()
            logging.info("[MAIN_BOT] Old webhook removed")
            
            # Устанавливаем новый webhook
            result = await main_bot.set_webhook(url=webhook_url)
            logging.info(f"[MAIN_BOT] Webhook set result: {result}")
            
            # Проверяем статус webhook
            webhook_info = await main_bot.get_webhook_info()
            logging.info(f"[MAIN_BOT] Webhook info: {webhook_info}")
            
        else:
            logging.warning("[MAIN_BOT] SERVER_URL not set, webhook not configured")
    except Exception as e:
        logging.error(f"[MAIN_BOT] Error setting webhook: {e}")
        raise

# Тестовый endpoint для проверки работы основного бота
@router.get("/test/main_bot")
async def test_main_bot():
    """Тестовый endpoint для проверки работы основного бота"""
    try:
        bot_info = await main_bot.get_me()
        webhook_info = await main_bot.get_webhook_info()
        return {
            "status": "ok",
            "bot_info": {
                "id": bot_info.id,
                "username": bot_info.username,
                "first_name": bot_info.first_name
            },
            "webhook_info": webhook_info
        }
    except Exception as e:
        logging.error(f"[MAIN_BOT] Test endpoint error: {e}")
        return {"status": "error", "message": str(e)}

# Простой endpoint для проверки доступности
@router.get("/webhook/main")
async def webhook_status():
    """Проверяет статус webhook endpoint"""
    return {"status": "webhook endpoint is available", "method": "GET"}

# Webhook endpoint для основного бота
@router.post("/webhook/main")
async def main_bot_webhook(request: Request):
    """Webhook endpoint для основного бота"""
    try:
        update_data = await request.json()
        logging.info(f"[MAIN_BOT] Webhook received from {request.client.host if request.client else 'unknown'}")
        logging.info(f"[MAIN_BOT] Update data: {update_data}")
        
        # Создаем объект Update для aiogram
        from aiogram.types import Update
        update = Update(**update_data)
        
        # Обрабатываем обновление
        logging.info(f"[MAIN_BOT] Processing update with dispatcher")
        await main_dispatcher.feed_update(main_bot, update)
        logging.info(f"[MAIN_BOT] Update processed successfully")
        
        return {"status": "ok"}
    except Exception as e:
        logging.error(f"[MAIN_BOT] Webhook error: {e}")
        logging.error(f"[MAIN_BOT] Request body: {await request.body() if hasattr(request, 'body') else 'N/A'}")
        return {"status": "error", "message": str(e)}

# Функция для удаления webhook
async def remove_main_bot_webhook():
    """Удаляет webhook для основного бота"""
    await main_bot.delete_webhook()
    logging.info("[MAIN_BOT] Webhook removed")

# Инициализация при импорте
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.info("[MAIN_BOT] Main bot module loaded")
