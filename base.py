from fastapi import FastAPI
from settings_bot import router as settings_api_router, settings_router
from main_bot import router as main_bot_router
import logging
import asyncio
from datetime import datetime, timezone, timedelta
import time

app = FastAPI()
# FastAPI endpoints (webhook, REST)
app.include_router(settings_api_router)
app.include_router(main_bot_router)

# aiogram Dispatcher setup (пример, если нужно)
# from aiogram import Dispatcher
# dispatcher = Dispatcher(...)
# dispatcher.include_router(settings_router)

# Удалён пример функции с невалидным синтаксисом

# Планировщик для ежедневной отправки инсайтов
async def daily_insights_scheduler():
    """Планировщик для ежедневной отправки инсайтов"""
    logging.info("[SCHEDULER] Daily insights scheduler started")
    
    while True:
        try:
            # Ждем до следующего дня в 9:00 UTC
            now = datetime.now(timezone.utc)
            next_run = now.replace(hour=9, minute=0, second=0, microsecond=0)
            
            if now.hour >= 9:
                next_run += timedelta(days=1)
            
            wait_seconds = (next_run - now).total_seconds()
            logging.info(f"[SCHEDULER] Next daily insights run at {next_run} (waiting {wait_seconds:.0f} seconds)")
            
            await asyncio.sleep(wait_seconds)
            
            # Отправляем инсайты
            logging.info("[SCHEDULER] Sending daily insights")
            from analytics import send_daily_insights_to_project_owners
            await send_daily_insights_to_project_owners()
            
        except Exception as e:
            logging.error(f"[SCHEDULER] Error in daily insights scheduler: {e}")
            # Ждем час перед повторной попыткой
            await asyncio.sleep(3600)

# Запускаем планировщик при старте приложения
@app.on_event("startup")
async def startup_event():
    """Запускается при старте приложения"""
    logging.info("[APP] Starting up...")
    
    # Запускаем планировщик в фоне
    asyncio.create_task(daily_insights_scheduler())
    logging.info("[APP] Daily insights scheduler started")

@app.on_event("shutdown")
async def shutdown_event():
    """Запускается при остановке приложения"""
    logging.info("[APP] Shutting down...")