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