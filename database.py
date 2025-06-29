import uuid
from sqlalchemy import insert, create_engine, func, and_, Column, Integer, String, ForeignKey, DateTime, Boolean, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime, timezone, timedelta
import databases
from sqlalchemy.sql import select
from typing import Optional
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Получаем путь к директории, где находится database.py
BASE_DIR = Path(__file__).parent
# Формируем путь к файлу БД в той же папке
DATABASE_URL = f"sqlite:///{BASE_DIR}/bot_database.db"
database = databases.Database(DATABASE_URL)

Base = declarative_base()

# Новая таблица user
class User(Base):
    __tablename__ = 'user'
    telegram_id = Column(String, primary_key=True)
    projects = relationship("Project", back_populates="user")

# Новая таблица project
class Project(Base):
    __tablename__ = 'project'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_name = Column(String, nullable=False)
    business_info = Column(String, nullable=False)
    token = Column(String, nullable=False)
    telegram_id = Column(String, ForeignKey('user.telegram_id'))
    user = relationship("User", back_populates="projects")
    
    # Добавляем уникальный индекс для project_name внутри пользователя
    __table_args__ = (
        # Уникальный индекс для комбинации telegram_id и project_name
        {'sqlite_autoincrement': True}
    )

engine = create_engine(DATABASE_URL.replace("sqlite+aiosqlite", "sqlite"))
Base.metadata.create_all(bind=engine)

# CRUD для user
async def create_user(telegram_id: str):
    query = select(User).where(User.telegram_id == telegram_id)
    row = await database.fetch_one(query)
    if not row:
        query = insert(User).values(telegram_id=telegram_id)
        await database.execute(query)

async def get_user(telegram_id: str) -> Optional[dict]:
    query = select(User).where(User.telegram_id == telegram_id)
    row = await database.fetch_one(query)
    if row:
        return {"telegram_id": row["telegram_id"]}
    return None

# CRUD для project
async def create_project(telegram_id: str, project_name: str, business_info: str, token: str) -> str:
    # Проверяем, существует ли проект с таким именем у пользователя
    if await check_project_name_exists(telegram_id, project_name):
        raise ValueError(f"Проект с именем '{project_name}' уже существует у этого пользователя")
    
    project_id = str(uuid.uuid4())
    query = insert(Project).values(id=project_id, project_name=project_name, business_info=business_info, token=token, telegram_id=telegram_id)
    await database.execute(query)
    return project_id

async def get_project_by_id(project_id: str) -> Optional[dict]:
    query = select(Project).where(Project.id == project_id)
    row = await database.fetch_one(query)
    if row:
        return {"id": row["id"], "project_name": row["project_name"], "business_info": row["business_info"], "token": row["token"], "telegram_id": row["telegram_id"]}
    return None

async def get_projects_by_user(telegram_id: str) -> list:
    query = select(Project).where(Project.telegram_id == telegram_id)
    rows = await database.fetch_all(query)
    return [{"id": r["id"], "project_name": r["project_name"], "business_info": r["business_info"], "token": r["token"], "telegram_id": r["telegram_id"]} for r in rows]

async def get_user_business_info(telegram_id: str) -> Optional[str]:
    """Возвращает business_info первого проекта пользователя (или None, если нет проектов)"""
    query = select(Project).where(Project.telegram_id == telegram_id)
    row = await database.fetch_one(query)
    if row:
        return row["business_info"]
    return None

async def get_project_by_token(token: str) -> Optional[dict]:
    """Возвращает проект по токену"""
    query = select(Project).where(Project.token == token)
    row = await database.fetch_one(query)
    if row:
        return {"id": row["id"], "project_name": row["project_name"], "business_info": row["business_info"], "token": row["token"], "telegram_id": row["telegram_id"]}
    return None

async def check_project_name_exists(telegram_id: str, project_name: str) -> bool:
    """Проверяет, существует ли проект с таким именем у пользователя"""
    query = select(Project).where(and_(Project.telegram_id == telegram_id, Project.project_name == project_name))
    row = await database.fetch_one(query)
    return row is not None

async def update_project_name(project_id: str, new_name: str) -> bool:
    """Обновляет название проекта"""
    try:
        from sqlalchemy import update
        # Получаем текущий проект для проверки telegram_id
        current_project = await get_project_by_id(project_id)
        if not current_project:
            return False
        
        # Проверяем, существует ли проект с таким именем у этого пользователя (исключая текущий проект)
        query = select(Project).where(
            and_(
                Project.telegram_id == current_project["telegram_id"],
                Project.project_name == new_name,
                Project.id != project_id
            )
        )
        existing_project = await database.fetch_one(query)
        if existing_project:
            raise ValueError(f"Проект с именем '{new_name}' уже существует у этого пользователя")
        
        # Обновляем название
        update_query = update(Project).where(Project.id == project_id).values(project_name=new_name)
        await database.execute(update_query)
        return True
    except Exception as e:
        logger.error(f"Error updating project name: {e}")
        return False

async def update_project_business_info(project_id: str, new_business_info: str) -> bool:
    """Обновляет информацию о бизнесе проекта"""
    try:
        from sqlalchemy import update
        query = update(Project).where(Project.id == project_id).values(business_info=new_business_info)
        await database.execute(query)
        return True
    except Exception as e:
        logger.error(f"Error updating project business info: {e}")
        return False

async def append_project_business_info(project_id: str, additional_info: str) -> bool:
    """Добавляет дополнительную информацию к существующей информации о бизнесе"""
    try:
        from sqlalchemy import update
        # Получаем текущую информацию
        current_project = await get_project_by_id(project_id)
        if not current_project:
            return False
        
        # Объединяем с новой информацией
        updated_info = current_project["business_info"] + "\n\n" + additional_info
        query = update(Project).where(Project.id == project_id).values(business_info=updated_info)
        await database.execute(query)
        return True
    except Exception as e:
        logger.error(f"Error appending project business info: {e}")
        return False

async def delete_project(project_id: str) -> bool:
    """Удаляет проект"""
    try:
        from sqlalchemy import delete
        query = delete(Project).where(Project.id == project_id)
        await database.execute(query)
        return True
    except Exception as e:
        logger.error(f"Error deleting project: {e}")
        return False