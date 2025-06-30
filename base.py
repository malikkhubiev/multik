from fastapi import FastAPI
from settings_bot import router as settings_router
from asking_bot import router as asking_router
import logging

app = FastAPI()
app.include_router(settings_router)
app.include_router(asking_router)

# Удалён пример функции с невалидным синтаксисом