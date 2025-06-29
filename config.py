import os
import json
import logging
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot_database.db")

PORT = os.getenv("PORT")
SERVER_URL = os.getenv("SERVER_URL")
API_URL = "https://api.telegram.org/bot"
BOT_URL = os.getenv("BOT_URL")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Логируем состояние критических переменных
logger = logging.getLogger(__name__)
logger.info(f"SERVER_URL: {'Настроен' if SERVER_URL else 'НЕ НАСТРОЕН'}")
logger.info(f"DEEPSEEK_API_KEY: {'Настроен' if DEEPSEEK_API_KEY else 'НЕ НАСТРОЕН'}")