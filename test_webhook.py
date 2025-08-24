#!/usr/bin/env python3
"""
Скрипт для тестирования webhook основного бота
"""

import asyncio
import httpx
import json
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

async def test_webhook():
    """Тестирует webhook основного бота"""
    
    # URL вашего сервера на render.com
    base_url = "https://your-app-name.onrender.com"  # Замените на ваш URL
    
    # Тест 1: Проверка доступности GET endpoint
    print("🔍 Тест 1: Проверка GET /webhook/main")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{base_url}/webhook/main")
            print(f"✅ GET /webhook/main: {response.status_code}")
            print(f"📄 Ответ: {response.text}")
    except Exception as e:
        print(f"❌ Ошибка GET /webhook/main: {e}")
    
    # Тест 2: Проверка тестового endpoint
    print("\n🔍 Тест 2: Проверка GET /test/main_bot")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{base_url}/test/main_bot")
            print(f"✅ GET /test/main_bot: {response.status_code}")
            print(f"📄 Ответ: {response.text}")
    except Exception as e:
        print(f"❌ Ошибка GET /test/main_bot: {e}")
    
    # Тест 3: Проверка POST webhook (имитация сообщения от Telegram)
    print("\n🔍 Тест 3: Проверка POST /webhook/main")
    try:
        # Имитируем сообщение от Telegram
        test_update = {
            "update_id": 123456789,
            "message": {
                "message_id": 1,
                "from": {
                    "id": 123456789,
                    "is_bot": False,
                    "first_name": "Test",
                    "username": "testuser"
                },
                "chat": {
                    "id": 123456789,
                    "first_name": "Test",
                    "username": "testuser",
                    "type": "private"
                },
                "date": 1234567890,
                "text": "/start test123"
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{base_url}/webhook/main",
                json=test_update,
                headers={"Content-Type": "application/json"}
            )
            print(f"✅ POST /webhook/main: {response.status_code}")
            print(f"📄 Ответ: {response.text}")
    except Exception as e:
        print(f"❌ Ошибка POST /webhook/main: {e}")

if __name__ == "__main__":
    print("🚀 Запуск тестирования webhook основного бота...")
    print("⚠️  Не забудьте заменить base_url на ваш реальный URL!")
    asyncio.run(test_webhook())
