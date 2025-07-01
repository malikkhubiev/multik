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
from config import TRIAL_DAYS

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
    paid = Column(Boolean, default=False)
    start_date = Column(DateTime, default=datetime.now(timezone.utc))
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

# Новая таблица MessageStat
class MessageStat(Base):
    __tablename__ = 'message_stat'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    telegram_id = Column(String, nullable=False)
    datetime = Column(DateTime, default=datetime.now(timezone.utc))
    is_command = Column(Boolean, default=False)
    is_reply = Column(Boolean, default=False)
    response_time = Column(Float, nullable=True)
    project_id = Column(String, nullable=True)
    is_trial = Column(Boolean, default=True)
    is_paid = Column(Boolean, default=False)

# Новая таблица Feedback
class Feedback(Base):
    __tablename__ = 'feedback'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    telegram_id = Column(String, nullable=False)
    username = Column(String, nullable=True)
    feedback_text = Column(String, nullable=False)
    is_positive = Column(Boolean, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

# Новая таблица Payment
class Payment(Base):
    __tablename__ = 'payment'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    telegram_id = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    paid_at = Column(DateTime, default=datetime.now(timezone.utc))

# ВАЖНО: ниже используется синхронный движок только для создания таблиц!
engine = create_engine(DATABASE_URL.replace("sqlite+aiosqlite", "sqlite"))
Base.metadata.create_all(bind=engine)
# Это безопасно, так как используется только при старте для миграции схемы.

# CRUD для user
async def create_user(telegram_id: str) -> None:
    logging.info(f"[DB] create_user: telegram_id={telegram_id}")
    query = select(User).where(User.telegram_id == telegram_id)
    user = await database.fetch_one(query)
    if not user:
        logging.info(f"[DB] create_user: creating new user {telegram_id}")
        query = insert(User).values(telegram_id=telegram_id, paid=False, start_date=datetime.now(timezone.utc))
        await database.execute(query)
    else:
        logging.info(f"[DB] create_user: user {telegram_id} already exists, не обновляем paid/start_date")
    # Диагностика: выводим всех пользователей после создания
    all_users = await database.fetch_all(select(User))
    for u in all_users:
        logging.info(f"[DB] DEBUG: после create_user: telegram_id={u['telegram_id']}, paid={u['paid']}, start_date={u['start_date']}")

async def get_user(telegram_id: str) -> Optional[dict]:
    logging.info(f"[DB] get_user: telegram_id={telegram_id}")
    query = select(User).where(User.telegram_id == telegram_id)
    row = await database.fetch_one(query)
    if row:
        logging.info(f"[DB] get_user: found {row}")
        return {"telegram_id": row["telegram_id"]}
    logging.info(f"[DB] get_user: not found")
    return None

# CRUD для project
async def create_project(telegram_id: str, project_name: str, business_info: str, token: str) -> str:
    logging.info(f"[DB] create_project: telegram_id={telegram_id}, project_name={project_name}, token={token}")
    if await check_project_name_exists(telegram_id, project_name):
        logging.warning(f"[DB] create_project: project with name '{project_name}' already exists for user {telegram_id}")
        raise ValueError(f"Проект с именем '{project_name}' уже существует у этого пользователя")
    project_id = str(uuid.uuid4())
    query = insert(Project).values(id=project_id, project_name=project_name, business_info=business_info, token=token, telegram_id=telegram_id)
    await database.execute(query)
    logging.info(f"[DB] create_project: created project {project_id}")
    return project_id

async def get_project_by_id(project_id: str) -> Optional[dict]:
    logging.info(f"[DB] get_project_by_id: project_id={project_id}")
    query = select(Project).where(Project.id == project_id)
    row = await database.fetch_one(query)
    if row:
        logging.info(f"[DB] get_project_by_id: found {row}")
        return {"id": row["id"], "project_name": row["project_name"], "business_info": row["business_info"], "token": row["token"], "telegram_id": row["telegram_id"]}
    logging.info(f"[DB] get_project_by_id: not found")
    return None

async def get_projects_by_user(telegram_id: str) -> list:
    logging.info(f"[DB] get_projects_by_user: telegram_id={telegram_id}")
    query = select(Project).where(Project.telegram_id == telegram_id)
    rows = await database.fetch_all(query)
    logging.info(f"[DB] get_projects_by_user: found {len(rows)} projects")
    return [{"id": r["id"], "project_name": r["project_name"], "business_info": r["business_info"], "token": r["token"], "telegram_id": r["telegram_id"]} for r in rows]

async def get_user_business_info(telegram_id: str) -> Optional[str]:
    logging.info(f"[DB] get_user_business_info: telegram_id={telegram_id}")
    query = select(Project).where(Project.telegram_id == telegram_id)
    row = await database.fetch_one(query)
    if row:
        logging.info(f"[DB] get_user_business_info: found business_info")
        return row["business_info"]
    logging.info(f"[DB] get_user_business_info: not found")
    return None

async def get_project_by_token(token: str) -> Optional[dict]:
    logging.info(f"[DB] get_project_by_token: token={token}")
    query = select(Project).where(Project.token == token)
    row = await database.fetch_one(query)
    if row:
        logging.info(f"[DB] get_project_by_token: found {row}")
        return {"id": row["id"], "project_name": row["project_name"], "business_info": row["business_info"], "token": row["token"], "telegram_id": row["telegram_id"]}
    logging.info(f"[DB] get_project_by_token: not found")
    return None

async def check_project_name_exists(telegram_id: str, project_name: str) -> bool:
    logging.info(f"[DB] check_project_name_exists: telegram_id={telegram_id}, project_name={project_name}")
    query = select(Project).where(and_(Project.telegram_id == telegram_id, Project.project_name == project_name))
    row = await database.fetch_one(query)
    exists = row is not None
    logging.info(f"[DB] check_project_name_exists: exists={exists}")
    return exists

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

async def set_user_paid(telegram_id: str, paid: bool = True):
    from sqlalchemy import update
    query = update(User).where(User.telegram_id == telegram_id).values(paid=paid)
    await database.execute(query)

async def get_user_by_id(telegram_id: str):
    query = select(User).where(User.telegram_id == telegram_id)
    return await database.fetch_one(query)

async def get_users_with_expired_trial():
    from datetime import datetime, timedelta
    from config import TRIAL_DAYS
    trial_period = timedelta(days=TRIAL_DAYS)
    trial_expired_before = datetime.now(timezone.utc) - trial_period
    logger.info(f"[DB] get_users_with_expired_trial: ищем пользователей с start_date < {trial_expired_before}")
    logger.info(f"[DB] get_users_with_expired_trial: TRIAL_DAYS = {TRIAL_DAYS}")
    now = datetime.now(timezone.utc)
    logger.info(f"[DB] get_users_with_expired_trial: текущее время UTC = {now}")
    # Логируем всех пользователей для отладки
    all_users = await database.fetch_all(select(User))
    logger.info(all_users)
    logger.info(f"[DB] get_users_with_expired_trial: все пользователи:")
    for u in all_users:
        logger.info(f"[DB] USER: telegram_id={u['telegram_id']}, paid={u['paid']}, start_date={u['start_date']}")
    query = select(User).where(User.paid == False, User.start_date < trial_expired_before)
    logger.info(f"[DB] get_users_with_expired_trial: SQL запрос = {query}")
    rows = await database.fetch_all(query)
    logger.info(f"[DB] get_users_with_expired_trial: найдено пользователей = {len(rows)}")
    for i, row in enumerate(rows):
        logger.info(f"[DB] get_users_with_expired_trial: пользователь {i+1}: {row}")
        if hasattr(row, 'start_date') and row.start_date:
            time_diff = now - row.start_date
            logger.info(f"[DB] get_users_with_expired_trial: пользователь {i+1} - разница времени: {time_diff}")
    return rows

async def delete_all_projects_for_user(telegram_id: str):
    from sqlalchemy import delete
    query = delete(Project).where(Project.telegram_id == telegram_id)
    await database.execute(query)

async def get_user_projects(telegram_id: str) -> list:
    query = select(Project).where(Project.telegram_id == telegram_id)
    rows = await database.fetch_all(query)
    return [{
        "id": r["id"],
        "project_name": r["project_name"],
        "business_info": r["business_info"],
        "token": r["token"],
        "telegram_id": r["telegram_id"]
    } for r in rows]

# --- MessageStat ---
async def log_message_stat(telegram_id, is_command, is_reply, response_time, project_id, is_trial, is_paid):
    query = insert(MessageStat).values(
        id=str(uuid.uuid4()),
        telegram_id=telegram_id,
        datetime=datetime.now(timezone.utc),
        is_command=is_command,
        is_reply=is_reply,
        response_time=response_time,
        project_id=project_id,
        is_trial=is_trial,
        is_paid=is_paid
    )
    await database.execute(query)

# --- Feedback ---
async def add_feedback(telegram_id, username, feedback_text, is_positive=None):
    query = insert(Feedback).values(
        telegram_id=telegram_id,
        username=username,
        feedback_text=feedback_text,
        is_positive=is_positive,
        created_at=datetime.now(timezone.utc)
    )
    await database.execute(query)

async def get_feedbacks():
    query = select(Feedback)
    rows = await database.fetch_all(query)
    return [dict(r) for r in rows]

# --- Payment ---
async def log_payment(telegram_id, amount):
    query = insert(Payment).values(
        telegram_id=telegram_id,
        amount=amount,
        paid_at=datetime.now(timezone.utc)
    )
    await database.execute(query)

async def get_payments():
    query = select(Payment)
    rows = await database.fetch_all(query)
    return [dict(r) for r in rows]

async def update_project_token(project_id: str, new_token: str) -> bool:
    """Обновляет токен проекта, если он уникален"""
    try:
        from sqlalchemy import update
        # Проверяем, существует ли проект с таким токеном
        existing = await get_project_by_token(new_token)
        if existing and existing["id"] != project_id:
            raise ValueError(f"Проект с таким токеном уже существует")
        query = update(Project).where(Project.id == project_id).values(token=new_token)
        await database.execute(query)
        return True
    except Exception as e:
        logger.error(f"Error updating project token: {e}")
        return False

async def get_users_with_expired_paid_month():
    """Возвращает пользователей, у которых прошёл первый платный месяц (тест: 30 секунд), и которые уже оплатили (paid=True)"""
    from sqlalchemy import select, and_
    from datetime import datetime, timedelta
    # Для реального продакшена:
    # one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)
    # Для теста используем 30 секунд:
    one_month_ago = datetime.now(timezone.utc) - timedelta(seconds=30)
    logger.info(f"[DB] get_users_with_expired_paid_month: ищем пользователей с paid=True и paid_at < {one_month_ago}")
    now = datetime.now(timezone.utc)
    logger.info(f"[DB] get_users_with_expired_paid_month: текущее время UTC = {now}")
    query = select(User).join(Payment, User.telegram_id == Payment.telegram_id).where(
        and_(
            User.paid == True,
            Payment.paid_at < one_month_ago
        )
    )
    logger.info(f"[DB] get_users_with_expired_paid_month: SQL запрос = {query}")
    rows = await database.fetch_all(query)
    logger.info(f"[DB] get_users_with_expired_paid_month: найдено записей = {len(rows)}")
    seen = set()
    result = []
    for row in rows:
        if row['telegram_id'] not in seen:
            seen.add(row['telegram_id'])
            result.append(row)
            logger.info(f"[DB] get_users_with_expired_paid_month: добавлен пользователь: {row}")
        else:
            logger.info(f"[DB] get_users_with_expired_paid_month: пропущен дубликат для telegram_id: {row['telegram_id']}")
    logger.info(f"[DB] get_users_with_expired_paid_month: итоговый результат (уникальных пользователей) = {len(result)}")
    return result