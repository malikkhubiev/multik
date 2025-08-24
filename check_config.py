#!/usr/bin/env python3
"""
Скрипт для проверки конфигурации основного бота
"""

import os
import asyncio
import logging
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def check_env_variables():
    """Проверяет все необходимые переменные окружения"""
    print("🔍 Проверка переменных окружения...")
    
    required_vars = [
        "MAIN_BOT_TOKEN",
        "SERVER_URL", 
        "DEEPSEEK_API_KEY",
        "DATABASE_URL"
    ]
    
    optional_vars = [
        "PORT",
        "TRIAL_DAYS",
        "MAIN_BOT_USERNAME"
    ]
    
    all_good = True
    
    # Проверяем обязательные переменные
    for var in required_vars:
        value = os.getenv(var)
        if value:
            print(f"✅ {var}: {'Настроен' if value else 'Пустое значение'}")
            if not value:
                all_good = False
        else:
            print(f"❌ {var}: НЕ НАСТРОЕН")
            all_good = False
    
    # Проверяем опциональные переменные
    print("\n📋 Опциональные переменные:")
    for var in optional_vars:
        value = os.getenv(var)
        if value:
            print(f"✅ {var}: {value}")
        else:
            print(f"⚠️  {var}: НЕ НАСТРОЕН")
    
    return all_good

async def test_bot_connection():
    """Тестирует подключение к Telegram Bot API"""
    print("\n🤖 Тестирование подключения к Telegram Bot API...")
    
    token = os.getenv("MAIN_BOT_TOKEN")
    if not token:
        print("❌ MAIN_BOT_TOKEN не настроен")
        return False
    
    try:
        import httpx
        url = f"https://api.telegram.org/bot{token}/getMe"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    bot_info = data["result"]
                    print(f"✅ Бот подключен: {bot_info['first_name']} (@{bot_info['username']})")
                    print(f"📋 ID бота: {bot_info['id']}")
                    return True
                else:
                    print(f"❌ Ошибка API: {data}")
                    return False
            else:
                print(f"❌ HTTP ошибка: {response.status_code}")
                return False
                
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        return False

async def test_webhook_status():
    """Проверяет статус webhook"""
    print("\n🔗 Проверка статуса webhook...")
    
    token = os.getenv("MAIN_BOT_TOKEN")
    if not token:
        print("❌ MAIN_BOT_TOKEN не настроен")
        return False
    
    try:
        import httpx
        url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    webhook_info = data["result"]
                    print(f"📋 URL webhook: {webhook_info.get('url', 'Не установлен')}")
                    print(f"📋 Ошибки: {webhook_info.get('last_error_message', 'Нет')}")
                    print(f"📋 Последняя ошибка: {webhook_info.get('last_error_date', 'Нет')}")
                    
                    if webhook_info.get('url'):
                        return True
                    else:
                        print("⚠️  Webhook не установлен")
                        return False
                else:
                    print(f"❌ Ошибка API: {data}")
                    return False
            else:
                print(f"❌ HTTP ошибка: {response.status_code}")
                return False
                
    except Exception as e:
        print(f"❌ Ошибка проверки webhook: {e}")
        return False

async def main():
    """Основная функция"""
    print("🚀 Проверка конфигурации основного бота...\n")
    
    # Проверяем переменные окружения
    env_ok = check_env_variables()
    
    if not env_ok:
        print("\n❌ Критические переменные окружения не настроены!")
        print("📋 Создайте файл .env со следующими переменными:")
        print("MAIN_BOT_TOKEN=your_bot_token")
        print("SERVER_URL=https://your-app.onrender.com")
        print("DEEPSEEK_API_KEY=your_api_key")
        print("DATABASE_URL=your_database_url")
        return
    
    print("\n✅ Все обязательные переменные настроены!")
    
    # Тестируем подключение к боту
    bot_ok = await test_bot_connection()
    
    # Проверяем статус webhook
    webhook_ok = await test_webhook_status()
    
    # Итоговая оценка
    print("\n📊 Итоговая оценка:")
    if env_ok and bot_ok and webhook_ok:
        print("🎉 Все проверки пройдены! Основной бот должен работать корректно.")
    elif env_ok and bot_ok:
        print("⚠️  Основные настройки корректны, но webhook не установлен.")
        print("💡 Запустите сервер для установки webhook.")
    else:
        print("❌ Есть проблемы с конфигурацией. Проверьте настройки.")

if __name__ == "__main__":
    asyncio.run(main())
