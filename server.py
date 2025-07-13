from base import app
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi import Request, APIRouter
from config import PORT, SERVER_URL, API_URL
from database import database, get_feedbacks, get_payments, get_user_by_id, get_users_with_expired_trial, get_projects_by_user, get_user_projects, log_message_stat, add_feedback, MessageStat, User, Payment, get_response_ratings_stats
from sqlalchemy.sql import func
from datetime import datetime, timedelta, timezone
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
from sqlalchemy import select
import plotly.graph_objs as go
import plotly.io as pio

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
async def get_stats(request: Request):
    logging.info(f"[API] /stats called from {request.client.host if hasattr(request, 'client') else 'unknown'}")
    # Общее количество пользователей
    total_users = await database.fetch_val(func.count(User.telegram_id).select())
    # Новые пользователи за сегодня
    today = datetime.now(timezone.utc).date()
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
    hour_select = select(
        func.strftime('%H', MessageStat.datetime).label('hour'),
        func.count(MessageStat.id).label('cnt')
    ).group_by(func.strftime('%H', MessageStat.datetime))
    rows = await database.fetch_all(hour_select)
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
    expired_trial_users = await database.fetch_val(func.count(User.telegram_id).select().where(User.paid == False, User.start_date < datetime.now(timezone.utc) - timedelta(days=14)))
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
    # LTV (реальный средний срок жизни клиента в месяцах)
    from collections import defaultdict
    user_payments = defaultdict(list)
    for p in payments:
        user_payments[p['telegram_id']].append(p['paid_at'])
    lifetimes = []
    for telegram_id, dates in user_payments.items():
        if len(dates) > 1:
            # Сортируем даты
            dates_sorted = sorted([d if not isinstance(d, str) else datetime.fromisoformat(d) for d in dates])
            lifetime_days = (dates_sorted[-1] - dates_sorted[0]).days
            lifetime_months = lifetime_days / 30
            if lifetime_months < 1:
                lifetime_months = 1  # Минимум 1 месяц, если пользователь платил более одного раза
            lifetimes.append(lifetime_months)
        else:
            lifetimes.append(1)  # Если только один платёж, считаем 1 месяц
    avg_lifetime_months = sum(lifetimes) / len(lifetimes) if lifetimes else 0
    ltv = arpu * avg_lifetime_months
    # Activity Rate
    activity_rate = (dau / total_users * 100) if total_users else 0
    # Удержание (Retention)
    # Для MVP: считаем как (платящих сейчас / плативших когда-либо)
    retention = (paid_count / paid_count * 100) if paid_count else 100
    
    # Статистика рейтингов ответов
    rating_stats = await get_response_ratings_stats()
    
    stats = {
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
        "retention": retention,
        "response_ratings": rating_stats
    }
    logging.info(f"[API] /stats: total_users={total_users}, dau={dau}, total_messages={total_messages}")
    # Форматируем значения для HTML (None -> '—')
    avg_msg_per_user_str = f"{avg_msg_per_user:.2f}" if avg_msg_per_user is not None else "—"
    avg_response_time_str = f"{avg_response_time:.2f} сек" if avg_response_time is not None else "—"
    arpu_str = f"{arpu:.2f} ₽" if arpu is not None else "—"
    ltv_str = f"{ltv:.2f} ₽" if ltv is not None else "—"
    total_revenue_str = f"{total_revenue:.2f} ₽" if total_revenue is not None else "—"
    avg_bots_per_user_str = f"{avg_bots_per_user:.2f}" if avg_bots_per_user is not None else "—"
    activity_rate_str = f"{activity_rate:.1f}%" if activity_rate is not None else "—"
    retention_str = f"{retention:.1f}%" if retention is not None else "—"
    conversion_str = f"{conversion:.1f}%" if conversion is not None else "—"
    
    # Статистика рейтингов
    rating_stats = stats.get("response_ratings", {})
    total_ratings_str = str(rating_stats.get("total_ratings", 0))
    likes_str = str(rating_stats.get("likes", 0))
    dislikes_str = str(rating_stats.get("dislikes", 0))
    like_percentage_str = f"{rating_stats.get('like_percentage', 0):.1f}%" if rating_stats.get('like_percentage') else "—"
    
    if "text/html" in request.headers.get("accept", ""):
        logging.info("[API] /stats: returning HTML page")
        # --- Plotly графики ---
        # 1. DAU по дням (за последние 14 дней)
        from sqlalchemy import desc
        days = [(datetime.now(timezone.utc).date() - timedelta(days=i)) for i in range(13, -1, -1)]
        dau_per_day = []
        for d in days:
            cnt = await database.fetch_val(
                func.count(func.distinct(MessageStat.telegram_id)).select().where(func.date(MessageStat.datetime) == d)
            )
            dau_per_day.append(cnt or 0)
        fig_dau = go.Figure(go.Bar(x=[d.strftime('%d.%m') for d in days], y=dau_per_day, marker_color='#1f77b4'))
        fig_dau.update_layout(
            title='DAU (уникальные пользователи по дням)',
            template='plotly_dark',
            plot_bgcolor='#222',
            paper_bgcolor='#222',
            font_color='#fff',
            margin=dict(l=30, r=30, t=60, b=30)
        )
        dau_html = pio.to_html(fig_dau, full_html=False, include_plotlyjs='cdn')
        # 2. Сообщения по часам (heatmap)
        hour_counts_full = [0]*24
        for h, c in hour_counts.items():
            try:
                hour_int = int(h)
                hour_counts_full[hour_int] = c
            except:
                pass
        fig_hours = go.Figure(go.Bar(x=[f"{h:02d}:00" for h in range(24)], y=hour_counts_full, marker_color='#e45756'))
        fig_hours.update_layout(
            title='Распределение сообщений по часам суток',
            template='plotly_dark',
            plot_bgcolor='#222',
            paper_bgcolor='#222',
            font_color='#fff',
            margin=dict(l=30, r=30, t=60, b=30)
        )
        hours_html = pio.to_html(fig_hours, full_html=False, include_plotlyjs=False)
        # 3. Выручка по месяцам (если есть платежи)
        payments = await get_payments()
        if payments:
            from collections import defaultdict
            revenue_by_month = defaultdict(float)
            for p in payments:
                dt = p['paid_at']
                if isinstance(dt, str):
                    dt = datetime.fromisoformat(dt)
                key = dt.strftime('%Y-%m')
                revenue_by_month[key] += p['amount']
            months = sorted(revenue_by_month.keys())
            values = [revenue_by_month[m] for m in months]
            fig_rev = go.Figure(go.Bar(x=months, y=values, marker_color='#72b7b2'))
            fig_rev.update_layout(
                title='Выручка по месяцам',
                template='plotly_dark',
                plot_bgcolor='#222',
                paper_bgcolor='#222',
                font_color='#fff',
                margin=dict(l=30, r=30, t=60, b=30)
            )
            rev_html = pio.to_html(fig_rev, full_html=False, include_plotlyjs=False)
        else:
            rev_html = ''
        # --- HTML dark theme ---
        html = f"""
        <html lang='ru'>
        <head>
            <meta charset='utf-8'>
            <title>Статистика бота</title>
            <script src='https://cdn.plot.ly/plotly-latest.min.js'></script>
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #181c24; color: #fff; margin: 0; padding: 0; }}
                .container {{ max-width: 900px; margin: 40px auto; background: #232733; border-radius: 16px; box-shadow: 0 4px 24px #0008; padding: 32px; }}
                h1 {{ text-align: center; color: #4fc3f7; margin-bottom: 32px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
                th, td {{ padding: 12px 10px; text-align: left; }}
                th {{ background: #232733; color: #4fc3f7; font-size: 1.1em; }}
                tr:nth-child(even) {{ background: #232733; }}
                tr:hover {{ background: #2a2e3a; }}
                .desc {{ color: #aaa; font-size: 0.95em; }}
                .charts {{ margin: 40px 0 0 0; }}
                .charts > div {{ margin-bottom: 40px; }}
            </style>
        </head>
        <body>
        <div class='container'>
            <h1>📊 Статистика Telegram-бота</h1>
            <table>
                <tr><th>Показатель</th><th>Значение</th></tr>
                <tr><td>👥 Всего пользователей</td><td>{total_users}</td></tr>
                <tr><td>🆕 Новых сегодня</td><td>{new_users_today}</td></tr>
                <tr><td>🗓️ DAU (уникальных за сегодня)</td><td>{dau}</td></tr>
                <tr><td>💬 Всего сообщений</td><td>{total_messages}</td></tr>
                <tr><td>💬 Среднее сообщений на пользователя</td><td>{avg_msg_per_user_str}</td></tr>
                <tr><td>⏰ Пиковые часы активности</td><td>{', '.join([f'{h}:00 ({c} сообщений)' for h, c in peak_hours]) if peak_hours else 'Нет данных'}</td></tr>
                <tr><td>⏱️ Среднее время ответа</td><td>{avg_response_time_str}</td></tr>
                <tr><td>🔄 Конверсия из триала в оплату</td><td>{conversion_str}</td></tr>
                <tr><td>🤖 Среднее число проектов на пользователя</td><td>{avg_bots_per_user_str}</td></tr>
                <tr><td>💸 Общая выручка</td><td>{total_revenue_str}</td></tr>
                <tr><td>💰 ARPU (средний доход на пользователя)</td><td>{arpu_str}</td></tr>
                <tr><td>📈 LTV (пожизненная ценность клиента)</td><td>{ltv_str}</td></tr>
                <tr><td>🔥 Activity Rate</td><td>{activity_rate_str}</td></tr>
                <tr><td>🔁 Retention (удержание)</td><td>{retention_str}</td></tr>
                <tr><td>👍 Всего оценок ответов</td><td>{total_ratings_str}</td></tr>
                <tr><td>👍 Лайки</td><td>{likes_str}</td></tr>
                <tr><td>👎 Дизлайки</td><td>{dislikes_str}</td></tr>
                <tr><td>📊 Процент лайков</td><td>{like_percentage_str}</td></tr>
            </table>
            <div class='desc' style='margin-top:24px;'>
                <b>Пояснения:</b><br>
                <b>DAU</b> — Daily Active Users, уникальные пользователи за сегодня.<br>
                <b>ARPU</b> — средний доход на пользователя.<br>
                <b>LTV</b> — пожизненная ценность клиента.<br>
                <b>Retention</b> — удержание платящих пользователей.<br>
                <b>Activity Rate</b> — доля активных пользователей за сутки.<br>
            </div>
            <div class='charts'>
                <div>{dau_html}</div>
                <div>{hours_html}</div>
                {f'<div>{rev_html}</div>' if rev_html else ''}
            </div>
        </div>
        </body></html>
        """
        return HTMLResponse(content=html)
    else:
        logging.info("[API] /stats: returning JSON")
        return stats

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
