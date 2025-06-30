from base import app
from fastapi.responses import JSONResponse
from fastapi import Request, APIRouter
from config import PORT, SERVER_URL, API_URL
from database import database, get_feedbacks, get_payments, get_user_by_id, get_users_with_expired_trial, get_projects_by_user, get_user_projects, log_message_stat, add_feedback, MessageStat, User, Payment
from sqlalchemy.sql import func
from datetime import datetime, timedelta
import uvicorn
from base import *
from utils import *
from settings_bot import (
    set_settings_webhook,
    router as settings_router,
    SETTINGS_BOT_TOKEN,
    SETTINGS_WEBHOOK_URL
)
import asyncio
import logging

@app.on_event("startup")
async def startup_event():
    try:
        logging.info(f"[ENV] SERVER_URL={SERVER_URL}, API_URL={API_URL}")
        logging.info(f"[ENV] SETTINGS_BOT_TOKEN={SETTINGS_BOT_TOKEN}, SETTINGS_WEBHOOK_URL={SETTINGS_WEBHOOK_URL}")
        await set_settings_webhook()
        print("[STARTUP] Settings bot webhook set!")
    except Exception as e:
        print(f"[STARTUP] Failed to set settings bot webhook: {e}")

@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    logging.info("[MIDDLEWARE] Перед database.connect()")
    await database.connect()
    logging.info("[MIDDLEWARE] После database.connect()")
    request.state.db = database
    logging.info("[MIDDLEWARE] Перед call_next")
    response = await call_next(request)
    logging.info("[MIDDLEWARE] После call_next")
    logging.info("[MIDDLEWARE] Перед database.disconnect()")
    await database.disconnect()
    logging.info("[MIDDLEWARE] После database.disconnect()")
    return response

@app.api_route("/", methods=["GET", "HEAD"])
async def super():
    logging.info("[HANDLER] Получен запрос на / (корень)")
    return JSONResponse(content={"message": f"Сервер работает!"}, status_code=200)

@app.get("/stats")
async def get_stats():
    # Общее количество пользователей
    total_users = await database.fetch_val(func.count(User.telegram_id).select())
    # Новые пользователи за сегодня
    today = datetime.utcnow().date()
    new_users_today = await database.fetch_val(
        func.count(User.telegram_id).select().where(func.date(User.start_date) == today)
    )
    # DAU (уникальные пользователи за сегодня)
    dau = await database.fetch_val(
        func.count(func.distinct(MessageStat.telegram_id)).select().where(func.date(MessageStat.datetime) == today)
    )
    # Всего сообщений
    total_messages = await database.fetch_val(func.count(MessageStat.id).select())
    # Среднее сообщений на пользователя
    avg_msg_per_user = (total_messages / total_users) if total_users else 0
    # Пиковые часы активности
    rows = await database.fetch_all(
        func.strftime('%H', MessageStat.datetime).label('hour'),
        func.count(MessageStat.id).label('cnt')
    )
    hour_counts = {}
    for r in rows:
        hour = r[0]
        cnt = r[1]
        hour_counts[hour] = cnt
    peak_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    # Среднее время ответа
    avg_response_time = await database.fetch_val(func.avg(MessageStat.response_time).select().where(MessageStat.response_time != None))
    # Конверсия из триала в оплату
    paid_users = await database.fetch_val(func.count(User.telegram_id).select().where(User.paid == True))
    expired_trial_users = await database.fetch_val(func.count(User.telegram_id).select().where(User.paid == False, User.start_date < datetime.utcnow() - timedelta(days=14)))
    conversion = (paid_users / (paid_users + expired_trial_users) * 100) if (paid_users + expired_trial_users) else 0
    # Среднее количество ботов на пользователя
    all_projects = await database.fetch_all(func.count().select().select_from(User).join(MessageStat, User.telegram_id == MessageStat.telegram_id))
    avg_bots_per_user = (len(all_projects) / total_users) if total_users else 0
    # Количество платящих
    paid_count = paid_users
    # Общая выручка
    payments = await get_payments()
    total_revenue = sum(p['amount'] for p in payments)
    # ARPU
    arpu = (total_revenue / paid_count) if paid_count else 0
    # LTV (ARPU * средний срок жизни клиента)
    # Для MVP: средний срок жизни = 1 месяц
    ltv = arpu * 1
    # Activity Rate
    activity_rate = (dau / total_users * 100) if total_users else 0
    # Удержание (Retention)
    # Для MVP: считаем как (платящих сейчас / плативших когда-либо)
    retention = (paid_count / paid_count * 100) if paid_count else 100
    return {
        "total_users": total_users,
        "new_users_today": new_users_today,
        "dau": dau,
        "total_messages": total_messages,
        "avg_msg_per_user": avg_msg_per_user,
        "peak_hours": peak_hours,
        "avg_response_time": avg_response_time,
        "conversion_trial_to_paid": conversion,
        "avg_bots_per_user": avg_bots_per_user,
        "total_revenue": total_revenue,
        "arpu": arpu,
        "ltv": ltv,
        "activity_rate": activity_rate,
        "retention": retention
    }

@app.get("/feedbacks")
async def get_feedbacks_api():
    feedbacks = await get_feedbacks()
    return feedbacks

app.include_router(settings_router)

if __name__ == "__main__":
    port = int(PORT)
    print("port")
    print(port)
    logging.info(f"[STARTUP] Запуск uvicorn на порту {port}")
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=port,
        workers=1,
        loop="asyncio",
        access_log=True
    )
