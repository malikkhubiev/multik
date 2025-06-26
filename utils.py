import os
import pandas as pd
from fastapi import HTTPException
from dotenv import load_dotenv
from functools import wraps
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException
import httpx
import logging
from config import API_URL, SERVER_URL
import traceback

load_dotenv()

# Настроим логирование
logging.basicConfig(level=logging.DEBUG)
logging.getLogger('aiosqlite').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

def exception_handler(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            logging.info("inside wrapper of exception handler")
            return await func(*args, **kwargs)
        except HTTPException as e:
            logging.error(f"HTTP error: {e.detail}")
            return JSONResponse({"status": "error", "message": e.detail}, status_code=e.status_code)
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            return JSONResponse({"status": "error", "message": "Internal server error"}, status_code=500)
    return wrapper

# Функция для проверки обязательных параметров
def check_parameters(**kwargs):
    missing_params = [param for param, value in kwargs.items() if value is None]
    if missing_params:
        logging.info(f"Не указаны следующие необходимые параметры: {', '.join(missing_params)}")
        return {"result": False, "message": "Введите команду /start и используйте кнопки для навигации"}
    return {"result": True}

async def get_user_by_telegram_id(telegram_id: str, to_throw: bool = True):
    logging.info(f"in get_user_by_telegram_id telegram_id = {telegram_id}")
    user = await get_user(telegram_id)
    if not(user):
        if to_throw:
            raise HTTPException(status_code=404, message="Пользователь не найден")
        else:
            return None
    return user

async def send_request(url: str, data: dict, method: str = "POST") -> dict:
    """Универсальная функция для отправки HTTP-запросов с обработкой ошибок."""
    try:
        async with httpx.AsyncClient() as client:
            if method.upper() == "POST":
                response = await client.post(url, json=data)
            elif method.upper() == "GET":
                response = await client.get(url, params=data)
            else:
                raise ValueError(f"Unsupported method: {method}")

            response.raise_for_status()  # Проверка на ошибки HTTP

            logging.info(f"Запрос на {url} успешно отправлен.")
            return response.json()  # Возвращаем данные ответа в формате JSON

    except httpx.RequestError as e:
        logging.error(f"Ошибка при отправке запроса: {e}")
        raise HTTPException(status_code=500, message="Request failed")

    except httpx.HTTPStatusError as e:
        logging.error(f"Ошибка HTTP при отправке запроса: {e}")
        raise HTTPException(status_code=500, message=f"HTTP error: {e.response.status_code}")

    except Exception as e:
        logging.error(f"Неизвестная ошибка: {e}")
        raise HTTPException(status_code=500, message="An unknown error occurred")

async def set_webhook(token: str, project_id: str) -> dict:
    logging.info(f"SERVER_URL={SERVER_URL}, project_id={project_id}")
    webhook_url = f"{SERVER_URL}/webhook/{project_id}"
    logging.info(f"webhook_url={webhook_url}")
    url = f"{API_URL}{token}/setWebhook"
    get_info_url = f"{API_URL}{token}/getWebhookInfo"
    async with httpx.AsyncClient() as client:
        try:
            logging.info(f"POST {url} params={{'url': {webhook_url}}}")
            resp = await client.post(url, params={"url": webhook_url})
            logging.info(f"setWebhook response status: {resp.status_code}, text: {resp.text}")
            data = resp.json()
            # Сразу после установки проверяем getWebhookInfo
            info_resp = await client.get(get_info_url)
            logging.info(f"getWebhookInfo response status: {info_resp.status_code}, text: {info_resp.text}")
            info_data = info_resp.json()
            logging.info(f"[WEBHOOK] setWebhook result: {data}")
            logging.info(f"[WEBHOOK] getWebhookInfo: {info_data}")
            data["webhook_info"] = info_data
            return data
        except Exception as e:
            logging.error(f"[WEBHOOK] Error: {e}\n{traceback.format_exc()}")
            return {"ok": False, "error": str(e), "trace": traceback.format_exc()}