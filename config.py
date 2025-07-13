import os
import json
import logging
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot_database.db")

TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", 10))  # 10 дней пробного периода
TRIAL_PROJECTS = int(os.getenv("TRIAL_PROJECTS", 3))
PAID_PROJECTS = int(os.getenv("PAID_PROJECTS", 5))
DISCOUNT_PAYMENT_AMOUNT = int(os.getenv("DISCOUNT_PAYMENT_AMOUNT", 2500))
PAYMENT_AMOUNT = int(os.getenv("PAYMENT_AMOUNT", 5000))
PAYMENT_CARD_NUMBER = os.getenv("PAYMENT_CARD_NUMBER", "1234 5678 9012 3456")
MAIN_TELEGRAM_ID = os.getenv("MAIN_TELEGRAM_ID", "123456789")
PORT = os.getenv("PORT")
SERVER_URL = os.getenv("SERVER_URL")
API_URL = "https://api.telegram.org/bot"
BOT_URL = os.getenv("BOT_URL")

SETTINGS_BOT_TOKEN = os.getenv("SETTINGS_BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
BOT_USERNAME = os.getenv("BOT_USERNAME")

# Google Sheets Analytics
GOOGLE_SHEETS_WEBHOOK_URL = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL")

# Логируем состояние критических переменных
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger.info(f"SERVER_URL: {'Настроен' if SERVER_URL else 'НЕ НАСТРОЕН'}")
logger.info(f"DEEPSEEK_API_KEY: {'Настроен' if DEEPSEEK_API_KEY else 'НЕ НАСТРОЕН'}")
logger.info(f"BOT_USERNAME: {'Настроен' if BOT_USERNAME else 'НЕ НАСТРОЕН'}")