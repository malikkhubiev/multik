from fastapi import HTTPException
from dotenv import load_dotenv
from functools import wraps
from fastapi.responses import JSONResponse
import httpx
import logging
from config import SETTINGS_BOT_TOKEN, API_URL, SERVER_URL
import traceback
from database import get_user
from pydub import AudioSegment

load_dotenv()

# Настроим логирование
logging.basicConfig(level=logging.DEBUG)
logging.getLogger('aiosqlite').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

def exception_handler(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            logging.info(f"[UTILS] exception_handler: calling {func.__name__}")
            return await func(*args, **kwargs)
        except HTTPException as e:
            logging.error(f"[UTILS] HTTP error: {e.detail}")
            return JSONResponse({"status": "error", "message": e.detail}, status_code=e.status_code)
        except Exception as e:
            logging.error(f"[UTILS] Unexpected error: {e}")
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
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        else:
            return None
    return user

async def send_request(url: str, data: dict, method: str = "POST") -> dict:
    """Универсальная функция для отправки HTTP-запросов с обработкой ошибок."""
    try:
        logging.info(f"Отправка запроса: {method} {url}")
        logging.debug(f"Данные запроса: {data}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            if method.upper() == "POST":
                response = await client.post(url, json=data)
            elif method.upper() == "GET":
                response = await client.get(url, params=data)
            else:
                raise ValueError(f"Unsupported method: {method}")

            response.raise_for_status()  # Проверка на ошибки HTTP

            logging.info(f"Запрос на {url} успешно отправлен. Статус: {response.status_code}")
            return response.json()  # Возвращаем данные ответа в формате JSON

    except httpx.ConnectError as e:
        logging.error(f"Ошибка подключения к {url}: {e}")
        raise HTTPException(status_code=500, detail=f"Connection failed to {url}: {str(e)}")

    except httpx.TimeoutException as e:
        logging.error(f"Таймаут при запросе к {url}: {e}")
        raise HTTPException(status_code=500, detail=f"Request timeout to {url}")

    except httpx.RequestError as e:
        logging.error(f"Ошибка при отправке запроса к {url}: {e}")
        raise HTTPException(status_code=500, detail=f"Request failed to {url}: {str(e)}")

    except httpx.HTTPStatusError as e:
        logging.error(f"Ошибка HTTP при отправке запроса к {url}: {e.response.status_code} - {e.response.text}")
        raise HTTPException(status_code=500, detail=f"HTTP error {e.response.status_code}: {e.response.text}")

    except Exception as e:
        logging.error(f"Неизвестная ошибка при запросе к {url}: {e}")
        raise HTTPException(status_code=500, detail=f"An unknown error occurred: {str(e)}")

async def set_webhook(token: str, project_id: str) -> dict:
    logging.info(f"SERVER_URL={SERVER_URL}, project_id={project_id}")
    webhook_url = f"{SERVER_URL}/webhook/{project_id}"
    logging.info(f"webhook_url={webhook_url}")
    url = f"{API_URL}{token}/setWebhook"
    get_info_url = f"{API_URL}{token}/getWebhookInfo"
    async with httpx.AsyncClient(timeout=30.0) as client:
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

async def delete_webhook(token: str) -> dict:
    """Отключает webhook для бота"""
    logging.info(f"Deleting webhook for token: {token}")
    url = f"{API_URL}{token}/deleteWebhook"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            logging.info(f"POST {url}")
            resp = await client.post(url)
            logging.info(f"deleteWebhook response status: {resp.status_code}, text: {resp.text}")
            data = resp.json()
            logging.info(f"[WEBHOOK] deleteWebhook result: {data}")
            return data
        except Exception as e:
            logging.error(f"[WEBHOOK] Error deleting webhook: {e}\n{traceback.format_exc()}")
            return {"ok": False, "error": str(e), "trace": traceback.format_exc()}

# --- Функция "печатает" ---
async def send_typing_action(chat_id, token):
    logging.info(f"[TYPING] send_typing_action: начало отправки для chat_id={chat_id}, token={token[:10]}...")
    try:
        url = f"https://api.telegram.org/bot{token}/sendChatAction"
        payload = {
            "chat_id": chat_id,
            "action": "typing"
        }
        logging.info(f"[TYPING] send_typing_action: URL={url}")
        logging.info(f"[TYPING] send_typing_action: payload={payload}")
        
        timeout = httpx.Timeout(5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            logging.info(f"[TYPING] send_typing_action: получен ответ status_code={resp.status_code}")
            logging.info(f"[TYPING] send_typing_action: ответ text={resp.text}")
            
            if resp.status_code != 200:
                logger.error(f"Failed to send typing action: {resp.status_code} - {resp.text}")
            else:
                logging.info(f"[TYPING] send_typing_action: успешно отправлен typing action")
    except Exception as e:
        logger.error(f"Failed to send typing action: {e}")
        import traceback
        logger.error(f"[TYPING] send_typing_action: полный traceback: {traceback.format_exc()}")

# Универсальная функция для получения текста из текстового или голосового сообщения
async def recognize_message_text(message, bot, language='ru-RU'):
    if message.text:
        return message.text
    elif message.voice:
        try:
            file_info = await bot.get_file(message.voice.file_id)
            file_path = file_info.file_path
            file_content = await bot.download_file(file_path)
            import speech_recognition as sr
            import tempfile
            recognizer = sr.Recognizer()
            with tempfile.NamedTemporaryFile(suffix='.ogg') as temp_ogg, tempfile.NamedTemporaryFile(suffix='.wav') as temp_wav:
                temp_ogg.write(file_content.read())
                temp_ogg.flush()
                audio = AudioSegment.from_file(temp_ogg.name)
                audio.export(temp_wav.name, format='wav')
                temp_wav.flush()
                with sr.AudioFile(temp_wav.name) as source:
                    audio_data = recognizer.record(source)
                text_content = recognizer.recognize_google(audio_data, language=language)
            logging.info(f"[VOICE] Распознанный текст из голосового сообщения: {text_content}")
            return text_content
        except Exception as e:
            logging.error(f"Ошибка при распознавании голоса: {e}")
            return None
    else:
        return None