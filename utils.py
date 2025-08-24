from fastapi import HTTPException
from dotenv import load_dotenv
from functools import wraps
from fastapi.responses import JSONResponse
import httpx
import logging
import traceback
import asyncio
import tempfile
import os
import speech_recognition as sr
from database import get_user
from pydub import AudioSegment
from pydub.silence import split_on_silence

load_dotenv()

# Настроим логирование
logging.basicConfig(level=logging.DEBUG)
logging.getLogger('aiosqlite').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

async def process_long_voice_message(bot, message):
    """Обрабатывает длинные голосовые сообщения, разбивая их на части"""
    try:
        # Получаем информацию о файле
        file_info = await bot.get_file(message.voice.file_id)
        file_path = file_info.file_path
        
        # Скачиваем файл
        file_content = await bot.download_file(file_path)
        
        # Создаем временные файлы
        with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as temp_ogg:
            temp_ogg.write(file_content.read())
            temp_ogg_path = temp_ogg.name
        
        # Конвертируем в WAV
        wav_path = temp_ogg_path.replace('.ogg', '.wav')
        audio = AudioSegment.from_file(temp_ogg_path)
        audio.export(wav_path, format='wav')
        
        # Инициализируем распознаватель
        recognizer = sr.Recognizer()
        
        # Обрабатываем длинное аудио по частям
        text_content = await process_long_audio(wav_path, recognizer)
        
        # Удаляем временные файлы
        os.unlink(temp_ogg_path)
        os.unlink(wav_path)
        
        return text_content
        
        except Exception as e:
        # Очистка временных файлов в случае ошибки
        if 'temp_ogg_path' in locals() and os.path.exists(temp_ogg_path):
            os.unlink(temp_ogg_path)
        if 'wav_path' in locals() and os.path.exists(wav_path):
            os.unlink(wav_path)
        raise e

async def process_long_audio(wav_path, recognizer, chunk_length_ms=30000):
    """Обрабатывает длинное аудио по частям"""
    full_text = []
    
    # Загружаем аудио
    audio = AudioSegment.from_wav(wav_path)
    
    # Разбиваем на чанки по времени
    chunks = [audio[i:i + chunk_length_ms] for i in range(0, len(audio), chunk_length_ms)]
    
    for i, chunk in enumerate(chunks):
        try:
            # Сохраняем чанк во временный файл
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_chunk:
                chunk.export(temp_chunk.name, format='wav')
                chunk_path = temp_chunk.name
            
            # Распознаем чанк
            with sr.AudioFile(chunk_path) as source:
                audio_data = recognizer.record(source)
                text = recognizer.recognize_google(audio_data, language='ru-RU')
                full_text.append(text)
            
            # Удаляем временный файл чанка
            os.unlink(chunk_path)
            
            # Добавляем небольшую задержку между запросами
            await asyncio.sleep(0.1)
            
        except Exception as e:
            logging.error(f"Ошибка при обработке чанка {i}: {e}")
            continue
    
    return " ".join(full_text)

def process_by_silence(wav_path, recognizer):
    """Разбивает аудио на части по тишине"""
    audio = AudioSegment.from_wav(wav_path)
    
    # Настройки для обнаружения тишины
    chunks = split_on_silence(
        audio,
        min_silence_len=500,
        silence_thresh=-40,
        keep_silence=200
    )
    
    full_text = []
    
    for i, chunk in enumerate(chunks):
        try:
            with tempfile.NamedTemporaryFile(suffix='.wav') as temp_chunk:
                chunk.export(temp_chunk.name, format='wav')
                
                with sr.AudioFile(temp_chunk.name) as source:
                    audio_data = recognizer.record(source)
                    text = recognizer.recognize_google(audio_data, language='ru-RU')
                    full_text.append(text)
                    
    except Exception as e:
            logging.error(f"Ошибка в чанке {i}: {e}")
            continue
    
    return " ".join(full_text)

# Универсальная функция для получения текста из текстового или голосового сообщения
async def recognize_message_text(message, bot, language='ru-RU'):
    if message.text:
        return message.text
    elif message.voice:
        try:
            # Проверяем длительность голосового сообщения
            duration = message.voice.duration
            
            # Если сообщение длиннее 30 секунд, используем обработку длинных сообщений
            if duration > 30:
                logging.info(f"[VOICE] Длинное голосовое сообщение ({duration}с), используем обработку по частям")
                return await process_long_voice_message(bot, message)
            else:
                # Для коротких сообщений используем стандартную обработку
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
            logging.error(f"Failed to recognize voice message: {e}")
            raise RuntimeError(f"Ошибка при распознавании голоса: {e}")
    else:
        raise RuntimeError("Пожалуйста, отправьте текстовое или голосовое сообщение.")