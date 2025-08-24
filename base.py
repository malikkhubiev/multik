from fastapi import FastAPI
from settings_bot import router as settings_api_router, settings_router
from main_bot import router as main_bot_router
import logging

app = FastAPI()
# FastAPI endpoints (webhook, REST)
app.include_router(settings_api_router)
app.include_router(main_bot_router)

# aiogram Dispatcher setup (пример, если нужно)
# from aiogram import Dispatcher
# dispatcher = Dispatcher(...)
# dispatcher.include_router(settings_router)

# Удалён пример функции с невалидным синтаксисом