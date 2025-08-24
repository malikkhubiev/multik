#!/usr/bin/env python3
"""
Скрипт миграции базы данных для изменения архитектуры проекта.
Убирает поле token и добавляет welcome_message и bot_link.
"""

import asyncio
import sqlite3
import uuid
from pathlib import Path
from config import MAIN_BOT_USERNAME

async def migrate_database():
    """Выполняет миграцию базы данных"""
    print("🚀 Начинаю миграцию базы данных...")
    
    # Путь к базе данных
    db_path = Path(__file__).parent / "bot_database.db"
    
    if not db_path.exists():
        print("❌ База данных не найдена!")
        return
    
    # Подключаемся к базе данных
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    try:
        # Проверяем текущую структуру таблицы project
        cursor.execute("PRAGMA table_info(project)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        print(f"📋 Текущие колонки таблицы project: {column_names}")
        
        # Проверяем, нужна ли миграция
        if 'welcome_message' in column_names and 'bot_link' in column_names:
            print("✅ Миграция уже выполнена!")
            return
        
        # Создаем временную таблицу с новой структурой
        print("🔧 Создаю временную таблицу...")
        cursor.execute("""
            CREATE TABLE project_new (
                id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                business_info TEXT NOT NULL,
                welcome_message TEXT,
                bot_link TEXT NOT NULL,
                telegram_id TEXT NOT NULL,
                FOREIGN KEY (telegram_id) REFERENCES user (telegram_id)
            )
        """)
        
        # Копируем данные из старой таблицы
        print("📥 Копирую данные...")
        if 'token' in column_names:
            cursor.execute("""
                SELECT id, project_name, business_info, token, telegram_id 
                FROM project
            """)
        else:
            cursor.execute("""
                SELECT id, project_name, business_info, telegram_id 
                FROM project
            """)
        
        projects = cursor.fetchall()
        print(f"📊 Найдено проектов для миграции: {len(projects)}")
        
        # Вставляем данные в новую таблицу
        for project in projects:
            if len(project) == 5:  # Старая структура с token
                project_id, project_name, business_info, token, telegram_id = project
            else:  # Новая структура без token
                project_id, project_name, business_info, telegram_id = project
            
            # Генерируем новую ссылку на бота
            bot_username = MAIN_BOT_USERNAME or "your_main_bot"
            bot_link = f"https://t.me/{bot_username}?start=proj{project_id}"
            
            cursor.execute("""
                INSERT INTO project_new (id, project_name, business_info, welcome_message, bot_link, telegram_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (project_id, project_name, business_info, None, bot_link, telegram_id))
        
        # Удаляем старую таблицу и переименовываем новую
        print("🔄 Заменяю таблицу...")
        cursor.execute("DROP TABLE project")
        cursor.execute("ALTER TABLE project_new RENAME TO project")
        
        # Создаем индексы
        print("📌 Создаю индексы...")
        cursor.execute("CREATE INDEX idx_project_telegram_id ON project(telegram_id)")
        cursor.execute("CREATE INDEX idx_project_bot_link ON project(bot_link)")
        
        # Создаем таблицу для истории проектов клиентов
        print("🔧 Создаю таблицу ClientProjectHistory...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS client_project_history (
                id TEXT PRIMARY KEY,
                client_telegram_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                first_visit DATETIME NOT NULL,
                last_visit DATETIME NOT NULL,
                visit_count INTEGER DEFAULT 1,
                FOREIGN KEY (project_id) REFERENCES project (id)
            )
        """)
        
        # Создаем индексы для истории
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_client_history_client ON client_project_history(client_telegram_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_client_history_project ON client_project_history(project_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_client_history_last_visit ON client_project_history(last_visit)")
        
        # Сохраняем изменения
        conn.commit()
        print("✅ Миграция успешно завершена!")
        
        # Показываем результат
        cursor.execute("SELECT COUNT(*) FROM project")
        count = cursor.fetchone()[0]
        print(f"📊 В таблице project теперь {count} проектов")
        
        # Показываем примеры ссылок
        cursor.execute("SELECT project_name, bot_link FROM project LIMIT 3")
        examples = cursor.fetchall()
        print("\n🔗 Примеры сгенерированных ссылок:")
        for name, link in examples:
            print(f"  {name}: {link}")
        
    except Exception as e:
        print(f"❌ Ошибка при миграции: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    asyncio.run(migrate_database())
