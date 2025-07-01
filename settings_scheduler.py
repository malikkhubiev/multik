import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import get_users_with_expired_trial, get_users_with_expired_paid_month, get_user_projects
from utils import delete_webhook
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import PAYMENT_AMOUNT
from settings_bot import settings_bot

scheduler = AsyncIOScheduler()

async def check_expired_trials():
    users = await get_users_with_expired_trial()
    logging.info(f"[TRIAL] Найдено пользователей с истекшим trial: {len(users)}")
    for user in users:
        telegram_id = user.get('telegram_id')
        logging.info(f"[TRIAL] Проверяю пользователя: {user}")
        try:
            projects = await get_user_projects(telegram_id)
            logging.info(f"[TRIAL] У пользователя {telegram_id} найдено проектов: {len(projects)}")
            for project in projects:
                try:
                    await delete_webhook(project['token'])
                    logging.info(f"[TRIAL] Вебхук удалён для проекта {project['id']} (token={project['token']})")
                except Exception as e:
                    logging.error(f"[TRIAL] Ошибка при удалении вебхука: {e}")
            try:
                pay_kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="Оплатить", callback_data="pay")],
                        [InlineKeyboardButton(text="Удалить проекты", callback_data="delete_trial_projects")]
                    ]
                )
                await settings_bot.send_message(
                    telegram_id,
                    f"Пробный период завершён!\n\nДля продолжения работы оплатите {PAYMENT_AMOUNT} рублей за первый месяц или удалите проекты.",
                    reply_markup=pay_kb
                )
                logging.info(f"[TRIAL] Пользователь {telegram_id} — trial истёк, уведомление отправлено")
            except Exception as e:
                logging.error(f"[TRIAL] Ошибка при отправке уведомления: {e}")
        except Exception as e:
            logging.error(f"[TRIAL] Ошибка при обработке пользователя {telegram_id}: {e}")

async def check_expired_paid_month():
    users = await get_users_with_expired_paid_month()
    logging.info(f"[PAID_MONTH] Найдено пользователей с истекшим первым оплачиваемым месяцем: {len(users)}")
    for user in users:
        telegram_id = user.get('telegram_id')
        logging.info(f"[PAID_MONTH] Проверяю пользователя: {user}")
        try:
            pay_kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Оплатить", callback_data="pay")]
                ]
            )
            await settings_bot.send_message(
                telegram_id,
                "Первый оплаченный месяц завершён!\n\nДля продолжения работы оплатите полную стоимость подписки.",
                reply_markup=pay_kb
            )
            logging.info(f"[PAID_MONTH] Пользователь {telegram_id} — первый оплаченный месяц истёк, уведомление отправлено")
        except Exception as e:
            logging.error(f"[PAID_MONTH] Ошибка при отправке уведомления: {e}")

scheduler.add_job(check_expired_trials, 'interval', minutes=1)
scheduler.add_job(check_expired_paid_month, 'interval', minutes=1)

def start_scheduler():
    scheduler.start() 