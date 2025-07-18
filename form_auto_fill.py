import logging
import re
from typing import Dict, List, Optional, Tuple
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)

class FormAutoFiller:
    def __init__(self):
        # Паттерны для извлечения данных из текста
        self.patterns = {
            "name": [
                r"меня зовут\s+([а-яёa-z\s]+)",
                r"имя\s+([а-яёa-z\s]+)",
                r"зовут\s+([а-яёa-z\s]+)",
                r"([а-яёa-z\s]+)\s+это мое имя"
            ],
            "phone": [
                r"(\+?[0-9\s\-\(\)]{10,})",
                r"телефон\s+(\+?[0-9\s\-\(\)]{10,})",
                r"номер\s+(\+?[0-9\s\-\(\)]{10,})"
            ],
            "email": [
                r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
                r"email\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
                r"почта\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"
            ],
            "date": [
                r"(\d{1,2}\.\d{1,2}\.\d{4})",
                r"(\d{1,2}/\d{1,2}/\d{4})",
                r"дата\s+(\d{1,2}\.\d{1,2}\.\d{4})"
            ]
        }
    
    def extract_data_from_text(self, text: str) -> Dict[str, str]:
        logger.info(f"[AUTO_FILL] extract_data_from_text: начало, text='{text}'")
        extracted_data = {}
        
        for field_type, patterns in self.patterns.items():
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                logger.info(f"[AUTO_FILL] extract_data_from_text: field_type={field_type}, pattern={pattern}, match={bool(match)}")
                if match:
                    value = match.group(1).strip()
                    logger.info(f"[AUTO_FILL] extract_data_from_text: найдено значение '{value}' для типа '{field_type}'")
                    if value and value not in extracted_data.values():
                        extracted_data[field_type] = value
                        break
        logger.info(f"[AUTO_FILL] extract_data_from_text: итоговый результат {extracted_data}")
        return extracted_data
    
    def map_field_to_form_field(self, field_name: str, field_type: str) -> Optional[str]:
        """Сопоставляет извлеченные данные с полями формы"""
        field_name_lower = field_name.lower()
        
        # Маппинг для имен
        if any(word in field_name_lower for word in ["имя", "name", "фам", "фамилия"]):
            return "name"
        
        # Маппинг для телефонов
        if any(word in field_name_lower for word in ["тел", "phone", "номер", "моб"]):
            return "phone"
        
        # Маппинг для email
        if any(word in field_name_lower for word in ["email", "почта", "mail"]):
            return "email"
        
        # Маппинг для дат
        if any(word in field_name_lower for word in ["дата", "date", "день"]):
            return "date"
        
        return None
    
    def auto_fill_form_data(self, conversation_text: str, form_fields: List[Dict]) -> Dict[str, str]:
        """Автоматически заполняет данные формы на основе текста разговора"""
        extracted_data = self.extract_data_from_text(conversation_text)
        auto_filled_data = {}
        
        for field in form_fields:
            field_name = field["name"]
            field_type = field["field_type"]
            
            # Пытаемся сопоставить поле с извлеченными данными
            mapped_key = self.map_field_to_form_field(field_name, field_type)
            
            if mapped_key and mapped_key in extracted_data:
                auto_filled_data[field_name] = extracted_data[mapped_key]
                logger.info(f"[FORM_AUTO_FILL] Автозаполнено поле '{field_name}': {extracted_data[mapped_key]}")
        
        return auto_filled_data

def create_form_preview_keyboard(form_data: Dict[str, str], form_id: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру с предварительным просмотром формы и кнопкой отправки"""
    keyboard = []
    
    # Кнопка для отправки формы
    keyboard.append([InlineKeyboardButton(
        text="✅ Отправить заявку",
        callback_data=f"submit_form_{form_id}"
    )])
    
    # Кнопка для редактирования
    keyboard.append([InlineKeyboardButton(
        text="✏️ Заполнить вручную",
        callback_data=f"edit_form_{form_id}"
    )])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def create_form_preview_message(form_data: Dict[str, str], form_fields: List[Dict]) -> str:
    """Создает сообщение с предварительным просмотром заполненной формы"""
    message = "📋 **Предварительный просмотр заявки:**\n\n"
    
    for field in form_fields:
        field_name = field["name"]
        field_value = form_data.get(field_name, "❌ Не заполнено")
        
        if field_value != "❌ Не заполнено":
            message += f"✅ **{field_name}:** {field_value}\n"
        else:
            message += f"❌ **{field_name}:** Не заполнено\n"
    
    message += "\n💡 Если данные корректны, нажмите 'Отправить заявку'"
    
    return message

# Глобальный экземпляр автозаполнителя
form_auto_filler = FormAutoFiller() 