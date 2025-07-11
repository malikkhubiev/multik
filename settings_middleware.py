import logging
from database import get_user_by_id
from config import TRIAL_DAYS, PAYMENT_AMOUNT, DISCOUNT_PAYMENT_AMOUNT
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import datetime

async def clear_asking_bot_cache(token: str):
    try:
        from asking_bot import clear_dispatcher_cache
        clear_dispatcher_cache(token)
        logging.info(f"Cleared asking_bot cache for token: {token}")
    except Exception as e:
        logging.error(f"Error clearing asking_bot cache: {e}")

async def trial_middleware(message, state, handler):
    user = await get_user_by_id(str(message.from_user.id))
    if user:
        from database import get_payments
        from datetime import datetime, timezone, timedelta
        if not user['paid']:
            start_date = user['start_date']
            logging.info(f"start_date {start_date}")
            if isinstance(start_date, str):
                from dateutil.parser import parse
                start_date = parse(start_date)
                logging.info(f"start_date parsed {start_date}")
            now = datetime.datetime.utcnow()
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
                    f"Пробный период завершён!\n\nДля продолжения работы оплатите {DISCOUNT_PAYMENT_AMOUNT} рублей за первый месяц или удалите проекты.\n\nВыберите действие:",
                    reply_markup=kb
                )
                return
        else:
            # Проверка истечения платного месяца
            payments = await get_payments()
            user_payments = [p for p in payments if str(p['telegram_id']) == str(user['telegram_id'])]
            if user_payments:
                last_paid = max(p['paid_at'] for p in user_payments)
                if isinstance(last_paid, str):
                    from dateutil.parser import parse
                    last_paid = parse(last_paid)
                now = datetime.datetime.now(timezone.utc)
                # 30 дней = 1 месяц
                if (now - last_paid).days >= 30:
                    kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="Оплатить подписку", callback_data="pay_subscription")],
                        ]
                    )
                    await message.answer(
                        f"Срок вашей подписки истёк! Для продолжения работы оплатите следующий месяц по стоимости {PAYMENT_AMOUNT} рублей.",
                        reply_markup=kb
                    )
                    return
    await handler(message, state) 