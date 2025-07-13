from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from settings_states import SettingsStates
from settings_feedback import add_feedback
from config import PAYMENT_AMOUNT, PAYMENT_CARD_NUMBER, MAIN_TELEGRAM_ID, TRIAL_PROJECTS, PAID_PROJECTS
from database import get_projects_by_user, get_user_by_id, set_user_paid, get_user_projects, check_project_name_exists, create_user
from settings_bot import main_menu
import logging

async def handle_settings_start(message: types.Message, state: FSMContext):
    logger = logging.getLogger(__name__)
    logger.info(f"/start received from user {message.from_user.id}")
    try:
        await state.clear()
        await create_user(str(message.from_user.id))
        await message.answer("Добро пожаловать в настройки! Введите имя вашего проекта.", reply_markup=main_menu)
        await state.set_state(SettingsStates.waiting_for_project_name)
        logger.info(f"Sent welcome message to user {message.from_user.id}")
    except Exception as e:
        logger.error(f"Error in handle_settings_start: {e}")

async def handle_help_command(message: types.Message, state: FSMContext):
    await state.clear()
    help_text = """
🤖 Доступные команды:

/start - Создать новый проект
/projects - Управление существующими проектами
/help - Показать эту справку

💳 Оплатить — перейти к оплате подписки

📋 Функции управления проектами:
• Переименование проекта
• Добавление дополнительных данных
• Изменение данных о бизнесе
• Удаление проекта (с отключением webhook)

💡 Для начала работы используйте /start
💡 Для управления проектами используйте /projects
💡 Для оплаты используйте кнопку 'Оплатить' или команду /pay
    """
    pay_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оплатить", callback_data="pay")]
        ]
    )
    await message.answer(help_text, reply_markup=pay_kb)

async def handle_projects_command(message: types.Message, state: FSMContext, telegram_id: str = None):
    logger = logging.getLogger(__name__)
    logger.info(f"/projects received from user {message.from_user.id}")
    try:
        if telegram_id is None:
            telegram_id = str(message.from_user.id)
        await state.update_data(telegram_id=telegram_id)
        await state.update_data(selected_project_id=None, selected_project=None)
        projects = await get_projects_by_user(telegram_id)
        if not projects:
            await message.answer("У вас пока нет проектов. Создайте первый проект командой /new", reply_markup=main_menu)
            return
        buttons = []
        for project in projects:
            buttons.append([
                types.InlineKeyboardButton(
                    text=project["project_name"],
                    callback_data=f"project_{project['id']}"
                )
            ])
        if buttons:
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
            await message.answer("Выберите проект для управления:", reply_markup=main_menu)
            await message.answer("Список проектов:", reply_markup=keyboard)
        else:
            await message.answer("Нет доступных проектов.", reply_markup=main_menu)
    except Exception as e:
        logger.error(f"Error in handle_projects_command: {e}")
        await message.answer("Произошла ошибка при получении списка проектов", reply_markup=main_menu) 