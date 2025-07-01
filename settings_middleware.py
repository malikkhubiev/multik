import logging
from database import get_user_by_id
from config import TRIAL_DAYS, PAYMENT_AMOUNT
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

async def clear_asking_bot_cache(token: str):
    try:
        from asking_bot import clear_dispatcher_cache
        clear_dispatcher_cache(token)
        logging.info(f"Cleared asking_bot cache for token: {token}")
    except Exception as e:
        logging.error(f"Error clearing asking_bot cache: {e}")

async def trial_middleware(message, state, handler):
    user = await get_user_by_id(str(message.from_user.id))
    if user and not user['paid']:
        from datetime import datetime, timezone, timedelta
        start_date = user['start_date']
        logging.info(f"start_date {start_date}")
        if isinstance(start_date, str):
            from dateutil.parser import parse
            start_date = parse(start_date)
            logging.info(f"start_date parsed {start_date}")
        now = datetime.now(datetime.timezone.utc)
        logging.info(f"now {now}")
        logging.info(f"(now - start_date).days {(now - start_date).days}")
        logging.info(f"TRIAL_DAYS {TRIAL_DAYS}")
        if (now - start_date).days >= TRIAL_DAYS:
            logging.info(f"(now - start_date).days >= TRIAL_DAYS")
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Оплатить", callback_data="pay_trial")],
                    [InlineKeyboardButton(text="Удалить проекты", callback_data="delete_trial_projects")]
                ]
            )
            await message.answer(
                f"Пробный период завершён!\n\nДля продолжения работы оплатите {PAYMENT_AMOUNT} рублей за первый месяц или удалите проекты.\n\nВыберите действие:",
                reply_markup=kb
            )
            return
    await handler(message, state) 