import httpx
import logging
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from config import GOOGLE_SHEETS_WEBHOOK_URL

logger = logging.getLogger(__name__)

class AnalyticsTracker:
    def __init__(self):
        self.webhook_url = GOOGLE_SHEETS_WEBHOOK_URL
        
    async def log_user_action(self, 
                             user_id: str, 
                             action: str, 
                             project_id: Optional[str] = None,
                             additional_data: Optional[Dict[str, Any]] = None):
        """
        Логирует действия пользователя в Google Sheets
        
        Actions:
        - "asked_question" - задал вопрос
        - "confirmed_submission" - подтвердил отправку формы
        - "created_project" - создал проект
        - "created_form" - создал форму
        - "rated_response" - поставил оценку ответу
        - "filled_form" - заполнил форму
        """
        logging.info(f"[ANALYTICS] log_user_action: начало, user_id={user_id}, action={action}, project_id={project_id}, additional_data={additional_data}")
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            # --- Новый формат additional_data ---
            readable_data = ""
            if additional_data:
                # Если это {'question_text': ...} или {'form_name': ...}
                if (len(additional_data) == 1 and isinstance(list(additional_data.values())[0], str)):
                    readable_data = list(additional_data.values())[0]
                # Если это {'form_data': {...}}
                elif 'form_data' in additional_data and isinstance(additional_data['form_data'], dict):
                    # Просто значения полей формы через запятую
                    readable_data = ', '.join(str(v) for v in additional_data['form_data'].values())
                else:
                    # fallback: сериализуем в строку
                    readable_data = json.dumps(additional_data, ensure_ascii=False)
            data = {
                "timestamp": timestamp,
                "user_id": user_id,
                "action": action,
                "project_id": project_id or "",
                "additional_data": readable_data
            }
            logging.info(f"[ANALYTICS] log_user_action: сформирован пакет данных для отправки: {data}")
            
            logging.info(f"[ANALYTICS] log_user_action: {action} for user {user_id}")
            
            if self.webhook_url:
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                    response = await client.post(self.webhook_url, json=data)
                    response.raise_for_status()
                    logging.info(f"[ANALYTICS] log_user_action: данные успешно отправлены в Google Sheets")
            else:
                logging.warning(f"[ANALYTICS] GOOGLE_SHEETS_WEBHOOK_URL не настроен, данные не отправлены")
                
        except Exception as e:
            logging.error(f"[ANALYTICS] log_user_action: ОШИБКА: {e}")
            import traceback
            logging.error(f"[ANALYTICS] log_user_action: полный traceback: {traceback.format_exc()}")

# Глобальный экземпляр трекера
analytics = AnalyticsTracker()

async def log_question_asked(user_id: str, project_id: Optional[str] = None, question_text: Optional[str] = None):
    """Логирует заданный вопрос"""
    additional_data = {"question_text": question_text} if question_text else None
    await analytics.log_user_action(user_id, "asked_question", project_id, additional_data)

async def log_form_submission_confirmed(user_id: str, project_id: Optional[str] = None, form_data: Optional[Dict] = None):
    """Логирует подтверждение отправки формы"""
    additional_data = {"form_data": form_data} if form_data else None
    await analytics.log_user_action(user_id, "confirmed_submission", project_id, additional_data)

async def log_project_created(user_id: str, project_id: str, project_name: Optional[str] = None):
    """Логирует создание проекта"""
    additional_data = {"project_name": project_name} if project_name else None
    await analytics.log_user_action(user_id, "created_project", project_id, additional_data)

async def log_form_created(user_id: str, project_id: str, form_name: Optional[str] = None):
    """Логирует создание формы"""
    additional_data = {"form_name": form_name} if form_name else None
    await analytics.log_user_action(user_id, "created_form", project_id, additional_data)

async def log_response_rating(user_id: str, project_id: Optional[str] = None, rating: Optional[bool] = None):
    """Логирует оценку ответа"""
    additional_data = {"rating": "positive" if rating else "negative"} if rating is not None else None
    await analytics.log_user_action(user_id, "rated_response", project_id, additional_data)

async def log_form_filled(user_id: str, project_id: Optional[str] = None, form_data: Optional[Dict] = None):
    """Логирует заполнение формы"""
    additional_data = {"form_data": form_data} if form_data else None
    await analytics.log_user_action(user_id, "filled_form", project_id, additional_data)

async def send_daily_insights_to_project_owners():
    """Отправляет ежедневные инсайты всем владельцам проектов"""
    logging.info("[ANALYTICS] Starting daily insights distribution")
    try:
        from database import get_daily_themes, get_project_by_id
        from settings_bot import settings_bot
        
        # Получаем все проекты с темами за последние 24 часа
        from datetime import datetime, timezone, timedelta
        day_ago = datetime.now(timezone.utc) - timedelta(hours=24)
        
        # Группируем темы по проектам
        project_themes = {}
        
        # Получаем все проекты
        from database import get_all_projects
        
        all_projects = await get_all_projects()
        project_themes = {}
        
        # Получаем темы для каждого проекта
        for project in all_projects:
            project_id = project['id']
            themes = await get_daily_themes(project_id)
            if themes:
                project_themes[project_id] = [theme['theme'] for theme in themes]
        
        # Отправляем инсайты каждому владельцу проекта
        for project_id, themes_list in project_themes.items():
            if not themes_list:
                continue
                
            try:
                # Получаем информацию о проекте
                project = await get_project_by_id(project_id)
                if not project:
                    continue
                
                # Анализируем темы
                theme_counts = {}
                for theme in themes_list:
                    theme_counts[theme] = theme_counts.get(theme, 0) + 1
                
                # Сортируем по популярности
                sorted_themes = sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)
                
                # Формируем отчет
                report = f"📊 **Ежедневная статистика проекта {project['project_name']}:**\n\n"
                for theme, count in sorted_themes[:5]:  # Только топ-5
                    theme_display = theme.replace('_', ' ').title()
                    report += f"• {theme_display}: {count} запросов\n"
                
                report += f"\n📈 Всего запросов: {len(themes_list)}"
                report += f"\n🕐 Период: последние 24 часа"
                
                # Отправляем владельцу проекта
                owner_telegram_id = project['telegram_id']
                await settings_bot.send_message(
                    chat_id=owner_telegram_id,
                    text=report,
                    parse_mode="Markdown"
                )
                
                logging.info(f"[ANALYTICS] Sent daily insights to project owner {owner_telegram_id}")
                
            except Exception as e:
                logging.error(f"[ANALYTICS] Error sending insights for project {project_id}: {e}")
                continue
        
        logging.info(f"[ANALYTICS] Daily insights distribution completed for {len(project_themes)} projects")
        
    except Exception as e:
        logging.error(f"[ANALYTICS] Error in daily insights distribution: {e}")
        import traceback
        logging.error(f"[ANALYTICS] Full traceback: {traceback.format_exc()}") 