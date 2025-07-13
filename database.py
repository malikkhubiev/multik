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
    trial_expired_notified = Column(Boolean, default=False)
    referrer_id = Column(String, nullable=True)  # ID пользователя, который пригласил
    bonus_days = Column(Integer, default=0)  # Дополнительные дни за рефералов
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
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    paid_at = Column(DateTime, default=datetime.now(timezone.utc))

# ВАЖНО: ниже используется синхронный движок только для создания таблиц!
engine = create_engine(DATABASE_URL.replace("sqlite+aiosqlite", "sqlite"))
Base.metadata.create_all(bind=engine)
# Это безопасно, так как используется только при старте для миграции схемы.

# CRUD для user
async def create_user(telegram_id: str, referrer_id: str = None) -> None:
    logging.info(f"[METRIC] create_user: telegram_id={telegram_id}, referrer_id={referrer_id}")
    query = select(User).where(User.telegram_id == telegram_id)
    user = await database.fetch_one(query)
    if not user:
        logging.info(f"[DB] create_user: creating new user {telegram_id} with referrer {referrer_id}")
        # Создаем базовые значения
        values = {
            "telegram_id": telegram_id,
            "paid": False,
            "start_date": datetime.now(timezone.utc),
            "trial_expired_notified": False
        }
        
        # Добавляем новые поля только если они существуют в схеме
        try:
            # Проверяем, есть ли новые поля в таблице
            test_query = select(User).limit(1)
            test_row = await database.fetch_one(test_query)
            if test_row and hasattr(test_row, "referrer_id"):
                values["referrer_id"] = referrer_id
                values["bonus_days"] = 0
        except (KeyError, AttributeError):
            # Если новых полей нет, создаем пользователя без них
            pass
        
        query = insert(User).values(**values)
        await database.execute(query)
        logging.info(f"[DB] create_user: user {telegram_id} created with referrer {referrer_id}")
    else:
        logging.info(f"[DB] create_user: user {telegram_id} already exists, не обновляем paid/start_date")
    # Диагностика: выводим всех пользователей после создания
    all_users = await database.fetch_all(select(User))
    for u in all_users:
        logging.info(f"[DB] DEBUG: после create_user: telegram_id={u['telegram_id']}, paid={u['paid']}, start_date={u['start_date']}, trial_expired_notified={u['trial_expired_notified']}, referrer_id={u.get('referrer_id')}, bonus_days={u.get('bonus_days')}")

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
    logging.info(f"[METRIC] create_project: telegram_id={telegram_id}, project_name={project_name}, token={token}")
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
    logging.info(f"[DB] get_projects_by_user: ищем проекты для пользователя {telegram_id}")
    query = select(Project).where(Project.telegram_id == telegram_id)
    logging.info(f"[DB] get_projects_by_user: SQL запрос = {query}")
    rows = await database.fetch_all(query)
    logging.info(f"[DB] get_projects_by_user: найдено {len(rows)} проектов для пользователя {telegram_id}")
    
    result = [{"id": r["id"], "project_name": r["project_name"], "business_info": r["business_info"], "token": r["token"], "telegram_id": r["telegram_id"]} for r in rows]
    
    for i, project in enumerate(result):
        logging.info(f"[DB] get_projects_by_user: проект {i+1}: id={project['id']}, name={project['project_name']}, token={project['token'][:10]}...")
    
    return result

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
    values = {'paid': paid}
    if paid:
        values['trial_expired_notified'] = False
    query = update(User).where(User.telegram_id == telegram_id).values(**values)
    await database.execute(query)

async def get_user_by_id(telegram_id: str):
    query = select(User).where(User.telegram_id == telegram_id)
    row = await database.fetch_one(query)
    if row:
        mapping = row._mapping if hasattr(row, '_mapping') else row
        return {
            "telegram_id": row["telegram_id"],
            "paid": row["paid"],
            "start_date": row["start_date"],
            "trial_expired_notified": row["trial_expired_notified"],
            "referrer_id": mapping["referrer_id"] if "referrer_id" in mapping else None,
            "bonus_days": mapping["bonus_days"] if "bonus_days" in mapping else 0
        }
    return None

async def get_users_with_expired_trial():
    from datetime import datetime, timedelta
    from config import TRIAL_DAYS
    from sqlalchemy import and_, update
    trial_period = timedelta(days=TRIAL_DAYS)
    trial_expired_before = datetime.now(timezone.utc) - trial_period
    logger.info(f"[DB] get_users_with_expired_trial: ищем пользователей с start_date < {trial_expired_before}")
    logger.info(f"[DB] get_users_with_expired_trial: TRIAL_DAYS = {TRIAL_DAYS}")
    now = datetime.now(timezone.utc)
    logger.info(f"[DB] get_users_with_expired_trial: текущее время UTC = {now}")
    all_users = await database.fetch_all(select(User))
    logger.info(all_users)
    logger.info(f"[DB] get_users_with_expired_trial: все пользователи:")
    for u in all_users:
        logger.info(f"[DB] USER: telegram_id={u['telegram_id']}, paid={u['paid']}, start_date={u['start_date']}, trial_expired_notified={u['trial_expired_notified']}, referrer_id={u.get('referrer_id')}, bonus_days={u.get('bonus_days', 0)}")
    query = select(User).where(
        and_(
            User.paid == False,
            User.start_date < trial_expired_before,
            User.trial_expired_notified == False
        )
    )
    logger.info(f"[DB] get_users_with_expired_trial: SQL запрос = {query}")
    rows = await database.fetch_all(query)
    logger.info(f"[DB] get_users_with_expired_trial: найдено пользователей = {len(rows)}")
    for i, row in enumerate(rows):
        logger.info(f"[DB] get_users_with_expired_trial: пользователь {i+1}: {row}")
        start_date = row.start_date
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        time_diff = now - start_date
        logger.info(f"[DB] get_users_with_expired_trial: пользователь {i+1} - разница времени: {time_diff}")
    return [dict(r) for r in rows]

async def set_trial_expired_notified(telegram_id: str, notified: bool = True):
    from sqlalchemy import update
    query = update(User).where(User.telegram_id == telegram_id).values(trial_expired_notified=notified)
    await database.execute(query)

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
    logging.info(f"[METRIC] log_message_stat: telegram_id={telegram_id}, is_command={is_command}, is_reply={is_reply}, response_time={response_time}, project_id={project_id}, is_trial={is_trial}, is_paid={is_paid}")
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
    logging.info(f"[METRIC] add_feedback: telegram_id={telegram_id}, username={username}, is_positive={is_positive}, feedback_text={feedback_text}")
    query = insert(Feedback).values(
        id=str(uuid.uuid4()),
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
    logging.info(f"[METRIC] log_payment: начало записи платежа telegram_id={telegram_id}, amount={amount}")
    try:
        query = insert(Payment).values(
            telegram_id=telegram_id,
            amount=amount,
            paid_at=datetime.now(timezone.utc)
        )
        logging.info(f"[METRIC] log_payment: SQL запрос = {query}")
        await database.execute(query)
        logging.info(f"[METRIC] log_payment: платеж успешно записан в БД для пользователя {telegram_id}, сумма {amount}")
    except Exception as e:
        logging.error(f"[METRIC] log_payment: ОШИБКА при записи платежа: {e}")
        import traceback
        logging.error(f"[METRIC] log_payment: полный traceback: {traceback.format_exc()}")
        raise

async def get_payments():
    logging.info(f"[DB] get_payments: получаем все платежи из БД")
    query = select(Payment)
    logging.info(f"[DB] get_payments: SQL запрос = {query}")
    rows = await database.fetch_all(query)
    logging.info(f"[DB] get_payments: найдено {len(rows)} платежей")
    
    result = [dict(r) for r in rows]
    for i, payment in enumerate(result):
        logging.info(f"[DB] get_payments: платеж {i+1}: telegram_id={payment['telegram_id']}, amount={payment['amount']}, paid_at={payment['paid_at']}")
    
    return result

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
    from sqlalchemy import select, and_, func
    from datetime import datetime, timedelta, timezone
    one_month_ago = datetime.now(timezone.utc) - timedelta(seconds=30)
    logger.info(f"[DB] get_users_with_expired_paid_month: ищем пользователей с paid=True и последним paid_at < {one_month_ago}")
    # Подзапрос: для каждого пользователя выбрать последний платёж
    subq = select(
        Payment.telegram_id,
        func.max(Payment.paid_at).label('last_paid_at')
    ).group_by(Payment.telegram_id).subquery()
    # Основной запрос: только если последний платёж старше 30 секунд
    query = select(User, subq.c.last_paid_at).join(subq, User.telegram_id == subq.c.telegram_id).where(
        and_(
            User.paid == True,
            subq.c.last_paid_at < one_month_ago
        )
    )
    logger.info(f"[DB] get_users_with_expired_paid_month: SQL запрос = {query}")
    rows = await database.fetch_all(query)
    logger.info(f"[DB] get_users_with_expired_paid_month: найдено записей = {len(rows)}")
    for i, row in enumerate(rows):
        logger.info(f"[DB] get_users_with_expired_paid_month: пользователь {i+1}: telegram_id={row['telegram_id']}, last_paid_at={row['last_paid_at']}")
    # Возвращаем только пользователей (dict)
    result = []
    for row in rows:
        user_dict = dict(row)
        user_dict['last_paid_at'] = row['last_paid_at']
        result.append(user_dict)
    logger.info(f"[DB] get_users_with_expired_paid_month: итоговый результат (уникальных пользователей) = {len(result)}")
    return result

async def update_user_referrer(telegram_id: str, referrer_id: str) -> bool:
    """Обновляет реферера пользователя"""
    logging.info(f"[REFERRAL] update_user_referrer: telegram_id={telegram_id}, referrer_id={referrer_id}")
    try:
        # Проверяем, есть ли поле referrer_id в таблице
        test_query = select(User).limit(1)
        test_row = await database.fetch_one(test_query)
        if not test_row or not hasattr(test_row, "referrer_id"):
            logging.warning(f"[REFERRAL] update_user_referrer: поле referrer_id не существует в таблице")
            return False
            
        from sqlalchemy import update
        query = update(User).where(User.telegram_id == telegram_id).values(referrer_id=referrer_id)
        await database.execute(query)
        logging.info(f"[REFERRAL] update_user_referrer: успешно обновлен реферер для пользователя {telegram_id}")
        return True
    except Exception as e:
        logging.error(f"[REFERRAL] update_user_referrer: ОШИБКА: {e}")
        import traceback
        logging.error(f"[REFERRAL] update_user_referrer: полный traceback: {traceback.format_exc()}")
        return False

# --- Referral System ---
async def add_bonus_days_to_referrer(referrer_id: str, bonus_days: int = 10):
    """Добавляет бонусные дни рефереру"""
    logging.info(f"[REFERRAL] add_bonus_days_to_referrer: referrer_id={referrer_id}, bonus_days={bonus_days}")
    try:
        from sqlalchemy import update
        query = update(User).where(User.telegram_id == referrer_id).values(
            bonus_days=User.bonus_days + bonus_days
        )
        await database.execute(query)
        logging.info(f"[REFERRAL] add_bonus_days_to_referrer: успешно добавлено {bonus_days} дней рефереру {referrer_id}")
    except Exception as e:
        logging.error(f"[REFERRAL] add_bonus_days_to_referrer: ОШИБКА: {e}")
        import traceback
        logging.error(f"[REFERRAL] add_bonus_days_to_referrer: полный traceback: {traceback.format_exc()}")

async def get_referrer_info(telegram_id: str):
    """Получает информацию о реферере пользователя"""
    logging.info(f"[REFERRAL] get_referrer_info: telegram_id={telegram_id}")
    user = await get_user_by_id(telegram_id)
    if user and user.get('referrer_id'):
        referrer = await get_user_by_id(user['referrer_id'])
        return referrer
    return None

async def get_referral_link(telegram_id: str) -> str:
    """Генерирует реферальную ссылку для пользователя"""
    from config import BOT_USERNAME
    username = BOT_USERNAME or "your_bot_username"
    return f"https://t.me/{username}?start=ref{telegram_id}"

async def process_referral_payment(paid_user_id: str, paid_user_username: str = None):
    """Обрабатывает оплату реферала и начисляет бонус рефереру"""
    logging.info(f"[REFERRAL] process_referral_payment: paid_user_id={paid_user_id}, username={paid_user_username}")
    
    # Получаем информацию о пользователе, который оплатил
    user = await get_user_by_id(paid_user_id)
    if not user or not user.get('referrer_id'):
        logging.info(f"[REFERRAL] process_referral_payment: у пользователя {paid_user_id} нет реферера")
        return None
    
    referrer_id = user['referrer_id']
    logging.info(f"[REFERRAL] process_referral_payment: реферер пользователя {paid_user_id} = {referrer_id}")
    
    # Добавляем бонусные дни рефереру
    await add_bonus_days_to_referrer(referrer_id, 10)
    
    # Получаем обновленную информацию о реферере
    referrer = await get_user_by_id(referrer_id)
    if not referrer:
        logging.error(f"[REFERRAL] process_referral_payment: не удалось получить информацию о реферере {referrer_id}")
        return None
    
    # Формируем сообщение для реферера
    username_display = paid_user_username if paid_user_username else f"пользователь {paid_user_id}"
    message = f"🎉 Ваш реферал {username_display} оплатил подписку!\n\n💎 Вам начислено +10 дней к пользованию.\n\n📊 Теперь у вас {referrer.get('bonus_days', 0)} дополнительных дней."
    
    return {
        'referrer_id': referrer_id,
        'message': message,
        'bonus_days': referrer.get('bonus_days', 0)
    }