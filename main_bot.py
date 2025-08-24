from fastapi import APIRouter, Request
from aiogram import Bot, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router, Dispatcher
from database import get_project_by_start_param, log_message_stat, get_user_by_id, get_project_form, save_form_submission
from aiogram.filters import Command
import logging
import httpx
import asyncio
from config import DEEPSEEK_API_KEY, MAIN_BOT_TOKEN
import time
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from form_auto_fill import form_auto_filler, create_form_preview_keyboard, create_form_preview_message

router = APIRouter()

# Состояния для сбора данных формы
class FormStates(StatesGroup):
    collecting_form_data = State()

# Основной бот
main_bot = Bot(token=MAIN_BOT_TOKEN)
storage = MemoryStorage()
main_dispatcher = Dispatcher(storage=storage)

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
"""

async def check_project_accessibility(project_id: str) -> bool:
    """Проверяет, доступен ли проект (не истек ли пробный/оплаченный период)"""
    from database import get_project_by_id, get_user_by_id
    
    project = await get_project_by_id(project_id)
    if not project:
        return False
    
    user = await get_user_by_id(project["telegram_id"])
    if not user:
        return False
    
    # Проверяем, оплачен ли пользователь или не истек пробный период
    from datetime import datetime, timezone, timedelta
    from config import TRIAL_DAYS
    
    if user["paid"]:
        # Для оплаченных пользователей проверяем, не истек ли месяц
        from database import get_payments
        payments = await get_payments()
        user_payments = [p for p in payments if p["telegram_id"] == project["telegram_id"] and p["status"] == "confirmed"]
        
        if user_payments:
            last_payment = max(user_payments, key=lambda x: x["paid_at"])
            if datetime.now(timezone.utc) - last_payment["paid_at"] > timedelta(days=30):
                return False
    else:
        # Для неоплаченных пользователей проверяем пробный период
        trial_end = user["start_date"] + timedelta(days=TRIAL_DAYS)
        if datetime.now(timezone.utc) > trial_end:
            return False
    
    return True

@main_dispatcher.message(Command("start"))
async def start_command(message: types.Message):
    """Обработчик команды /start с projectId"""
    logging.info(f"[MAIN_BOT] /start command from user {message.from_user.id}")
    
    # Получаем параметр start
    start_param = message.get_args()
    if not start_param:
        await message.answer("❌ Ошибка: не указан ID проекта")
        return
    
    # Получаем проект по параметру
    project = await get_project_by_start_param(start_param)
    if not project:
        await message.answer("❌ Проект не найден или недоступен")
        return
    
    # Проверяем доступность проекта
    if not await check_project_accessibility(project["id"]):
        await message.answer("❌ Проект временно недоступен. Свяжитесь с владельцем для продления подписки.")
        return
    
    # Сохраняем информацию о проекте в контексте пользователя
    await storage.set_data(
        bot=main_bot,
        key=types.Chat(id=message.chat.id, type="private"),
        data={"current_project": project}
    )
    
    # Отправляем приветственное сообщение
    welcome_msg = project.get("welcome_message") or f"👋 Добро пожаловать в {project['project_name']}!\n\nЯ готов помочь вам с любыми вопросами о нашем бизнесе."
    
    # Проверяем, есть ли форма у проекта
    form = await get_project_form(project["id"])
    if form:
        welcome_msg += "\n\n📝 Также вы можете оформить заявку через нашу форму."
        keyboard = create_form_preview_keyboard()
        await message.answer(welcome_msg, reply_markup=keyboard)
    else:
        await message.answer(welcome_msg)
    
    # Логируем статистику
    user = await get_user_by_id(project["telegram_id"])
    await log_message_stat(
        telegram_id=message.from_user.id,
        is_command=True,
        is_reply=False,
        response_time=0,
        project_id=project["id"],
        is_trial=not user["paid"] if user else True,
        is_paid=user["paid"] if user else False
    )

@main_dispatcher.message()
async def handle_message(message: types.Message):
    """Обработчик всех сообщений"""
    logging.info(f"[MAIN_BOT] Message from user {message.from_user.id}: {message.text}")
    
    # Получаем текущий проект из контекста
    chat_data = await storage.get_data(
        bot=main_bot,
        key=types.Chat(id=message.chat.id, type="private")
    )
    
    current_project = chat_data.get("current_project")
    if not current_project:
        await message.answer("❌ Сначала запустите бота командой /start с ID проекта")
        return
    
    # Проверяем доступность проекта
    if not await check_project_accessibility(current_project["id"]):
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
@main_dispatcher.callback_query()
async def handle_callback(callback: types.CallbackQuery):
    """Обработчик callback запросов"""
    logging.info(f"[MAIN_BOT] Callback from user {callback.from_user.id}: {callback.data}")
    
    if callback.data == "show_form":
        # Показываем форму
        chat_data = await storage.get_data(
            bot=main_bot,
            key=types.Chat(id=callback.message.chat.id, type="private")
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
    
    await callback.answer()

# Функция для запуска webhook
async def set_main_bot_webhook():
    """Устанавливает webhook для основного бота"""
    from config import SERVER_URL
    if SERVER_URL:
        webhook_url = f"{SERVER_URL}/webhook/main"
        await main_bot.set_webhook(url=webhook_url)
        logging.info(f"[MAIN_BOT] Webhook set to {webhook_url}")
    else:
        logging.warning("[MAIN_BOT] SERVER_URL not set, webhook not configured")

# Webhook endpoint для основного бота
@router.post("/webhook/main")
async def main_bot_webhook(request: Request):
    """Webhook endpoint для основного бота"""
    try:
        update_data = await request.json()
        logging.info(f"[MAIN_BOT] Webhook received: {update_data}")
        
        # Создаем объект Update для aiogram
        from aiogram.types import Update
        update = Update(**update_data)
        
        # Обрабатываем обновление
        await main_dispatcher.feed_update(main_bot, update)
        
        return {"status": "ok"}
    except Exception as e:
        logging.error(f"[MAIN_BOT] Webhook error: {e}")
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
