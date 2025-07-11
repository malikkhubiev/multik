import logging
import time
from utils import set_webhook, delete_webhook
from file_utils import extract_text_from_file_async
import httpx
from pydub import AudioSegment

async def process_business_file_with_deepseek(file_content: str) -> str:
    from config import DEEPSEEK_API_KEY
    try:
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "Ты - эксперт по анализу и сжатию информации. Твоя задача - извлечь из данных ключевую информацию, убрать лишние детали, символы, смайлики и т.д. и представить её в самом компактном виде без потери смысла для использования минимально необходимого количества токенов"},
                {"role": "user", "content": f"Обработай {file_content}"}
            ],
            "temperature": 0.3
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logging.error(f"Ошибка при обработке файла через Deepseek: {e}")
        return file_content

def clean_markdown(text: str) -> str:
    import re
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'__(.*?)__', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'_(.*?)_', r'\1', text)
    text = re.sub(r'~~(.*?)~~', r'\1', text)
    text = re.sub(r'`(.*?)`', r'\1', text)
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', '', text)
    text = re.sub(r'^[\s]*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[\s]*\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = text.strip()
    return text

def clean_business_text(text: str) -> str:
    import re
    text = text.replace('\r', '')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n+', '\n', text)
    text = text.strip()
    return text

async def get_text_from_message(message, bot, max_length=4096) -> str:
    text_content = None
    if message.document:
        try:
            file_info = await bot.get_file(message.document.file_id)
            file_path = file_info.file_path
            file_content = await bot.download_file(file_path)
            filename = message.document.file_name
            text_content = await extract_text_from_file_async(filename, file_content.read())
        except Exception as e:
            raise RuntimeError(f"Ошибка при обработке файла: {e}")
    elif message.text:
        text_content = message.text
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
                text_content = recognizer.recognize_google(audio_data, language='ru-RU')
            logging.info(f"[VOICE] Распознанный текст из голосового сообщения: {text_content}")
        except Exception as e:
            raise RuntimeError(f"Ошибка при распознавании голоса: {e}")
    if not text_content:
        raise RuntimeError("Пожалуйста, отправьте файл, текст или голосовое сообщение с информацией о бизнесе.")
    if len(text_content) > max_length:
        raise ValueError(f"❌ Данные слишком большие!\n\nРазмер: {len(text_content)} символов\nМаксимальный размер: {max_length} символов\n\nПожалуйста, сократите или разделите на части.")
    return clean_business_text(text_content) 