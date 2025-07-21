from fastapi import FastAPI
from settings_bot import router as settings_api_router, settings_router
from asking_bot import router as asking_router
import logging

app = FastAPI()
# FastAPI endpoints (webhook, REST)
app.include_router(settings_api_router)
app.include_router(asking_router)

# aiogram Dispatcher setup (пример, если нужно)
# from aiogram import Dispatcher
# dispatcher = Dispatcher(...)
# dispatcher.include_router(settings_router)

# Удалён пример функции с невалидным синтаксисом