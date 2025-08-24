#!/usr/bin/env python3
"""
Тестовый файл для проверки всех импортов после обновления на короткие ссылки
"""

def test_imports():
    """Тестирует все основные импорты"""
    try:
        print("🔍 Тестирую импорты...")
        
        # Тест базовых модулей
        print("✅ Импортирую config...")
        from config import MAIN_BOT_TOKEN, SETTINGS_BOT_TOKEN, SERVER_URL, generate_short_link
        
        print("✅ Импортирую database...")
        from database import database, get_project_by_id, create_project, get_project_by_short_link
        
        print("✅ Импортирую main_bot...")
        from main_bot import router as main_bot_router
        
        print("✅ Импортирую settings_bot...")
        from settings_bot import router as settings_router
        
        print("✅ Импортирую form_auto_fill...")
        from form_auto_fill import create_form_preview_keyboard
        
        print("✅ Импортирую base...")
        from base import app
        
        print("✅ Импортирую server...")
        from server import startup_event
        
        print("✅ Импортирую utils...")
        from utils import recognize_message_text, process_long_voice_message
        
        print("✅ Импортирую settings_forms...")
        from settings_forms import settings_forms_router
        
        print("✅ Импортирую settings_business...")
        from settings_business import process_business_file_with_deepseek
        
        print("✅ Импортирую settings_payment...")
        from settings_payment import handle_pay_command
        
        print("✅ Импортирую settings_middleware...")
        from settings_middleware import trial_middleware
        
        # Тест генерации коротких ссылок
        print("✅ Тестирую генерацию коротких ссылок...")
        short_link = generate_short_link()
        print(f"   Сгенерированная ссылка: {short_link}")
        assert len(short_link) == 5
        assert short_link.isalpha()
        assert short_link.islower()
        
        print("🎉 Все импорты успешны!")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка импорта: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_imports()

