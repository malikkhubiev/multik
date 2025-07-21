# settings_design.py
from aiogram import types, Router
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
import logging
from settings_states import SettingsStates

# Экспортируемый роутер для подключения в settings_bot.py
settings_design_router = Router()

# --- Меню оформления ---
async def show_design_menu(callback_or_message, state: FSMContext):
    data = await state.get_data()
    project = data.get("selected_project")
    if not project:
        await (callback_or_message.answer if hasattr(callback_or_message, 'answer') else callback_or_message.reply)("Ошибка: проект не выбран", show_alert=True if hasattr(callback_or_message, 'answer') else None)
        await state.clear()
        return
    design_name = data.get("design_name")
    design_avatar = data.get("design_avatar")
    design_welcome_text = data.get("design_welcome_text")
    design_welcome_image = data.get("design_welcome_image")
    design_description = data.get("design_description")
    text = f"Оформление проекта: {project['project_name']}\n\n" \
        f"Имя: {design_name or 'не задано'}\n" \
        f"Аватарка: {'задано' if design_avatar else 'не задано'}\n" \
        f"Парадное описание: {design_welcome_text or 'не задано'}\n" \
        f"Парадная картинка: {'задано' if design_welcome_image else 'не задано'}\n" \
        f"Описание: {design_description or 'не задано'}\n\nВыберите, что хотите изменить:"
    buttons = [
        [types.InlineKeyboardButton(text="Изменить имя", callback_data="design_change_name")],
        [types.InlineKeyboardButton(text="Изменить аватарку", callback_data="design_change_avatar")],
        [types.InlineKeyboardButton(text="Изменить парадное описание", callback_data="design_change_welcome_text")],
        [types.InlineKeyboardButton(text="Изменить парадную картинку", callback_data="design_change_welcome_image")],
        [types.InlineKeyboardButton(text="Изменить описание", callback_data="design_change_description")],
        [types.InlineKeyboardButton(text="Применить оформление", callback_data="apply_design")],
        [types.InlineKeyboardButton(text="Назад", callback_data="back_to_projects")],
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    if hasattr(callback_or_message, 'edit_text'):
        await callback_or_message.edit_text(text, reply_markup=keyboard)
    else:
        await callback_or_message.answer(text, reply_markup=keyboard)

# --- Хендлеры оформления ---
@settings_design_router.callback_query(lambda c: c.data == "open_design")
async def handle_project_design(callback_query: types.CallbackQuery, state: FSMContext):
    logging.info(f"[DESIGN][CLICK] Пользователь {callback_query.from_user.id} нажал кнопку 'Оформление'")
    current_state = await state.get_state()
    logging.info(f"[DESIGN][DEBUG] FSM state при входе: {current_state}")
    data = await state.get_data()
    logging.info(f"[DESIGN][DEBUG] FSM data при входе: {data}")
    project = data.get("selected_project")
    logging.info(f"[DESIGN][DEBUG] selected_project: {project}")
    await callback_query.answer()
    try:
        await show_design_menu(callback_query.message, state)
    except Exception as e:
        logging.error(f"[DESIGN][ERROR] Ошибка в show_design_menu: {e}")
        await callback_query.message.answer(f"Ошибка при открытии меню оформления: {e}")

@settings_design_router.callback_query(lambda c: c.data == "design_change_name")
async def handle_design_change_name(callback_query: types.CallbackQuery, state: FSMContext):
    logging.info(f"[DESIGN][CLICK] Пользователь {callback_query.from_user.id} нажал кнопку 'Изменить имя'")
    await callback_query.answer()
    await callback_query.message.edit_text("Введите новое имя бота:")
    await state.set_state(SettingsStates.waiting_for_design_name)

@settings_design_router.message(StateFilter('SettingsStates:waiting_for_design_name'))
async def process_design_name(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    logging.info(f"[FSM] process_design_name CALLED for user={message.from_user.id}, text={message.text}, state={current_state}")
    if message.text and message.text.startswith('/'):
        await state.clear()
        await message.answer("Вышли из режима оформления.")
        return
    await state.update_data(design_name=message.text)
    logging.info(f"[FSM] process_design_name: design_name set for user={message.from_user.id}, name={message.text}")
    await show_design_menu(message, state)
    await state.set_state(None)
    logging.info(f"[FSM] process_design_name END: Состояние сброшено после показа меню оформления для user={message.from_user.id}")

@settings_design_router.callback_query(lambda c: c.data == "design_change_avatar")
async def handle_design_change_avatar(callback_query: types.CallbackQuery, state: FSMContext):
    logging.info(f"[DESIGN][CLICK] Пользователь {callback_query.from_user.id} нажал кнопку 'Изменить аватарку'")
    await callback_query.answer()
    await callback_query.message.edit_text("Отправьте новую аватарку (фото):")
    await state.set_state(SettingsStates.waiting_for_design_avatar)

@settings_design_router.message(StateFilter('SettingsStates:waiting_for_design_avatar'))
async def process_design_avatar(message: types.Message, state: FSMContext):
    if message.text and message.text.startswith('/'):
        await state.clear()
        await message.answer("Вышли из режима оформления.")
        return
    if not message.photo:
        logging.info(f"[DESIGN] Пользователь {message.from_user.id} не отправил фото для аватарки")
        await message.answer("Пожалуйста, отправьте фото для аватарки.")
        return
    file_id = message.photo[-1].file_id
    logging.info(f"[DESIGN] Пользователь {message.from_user.id} отправил аватарку, file_id={file_id}")
    await state.update_data(design_avatar=file_id)
    await message.answer("Аватарка сохранена!")
    await show_design_menu(message, state)
    await state.set_state(None)

@settings_design_router.callback_query(lambda c: c.data == "design_change_welcome_text")
async def handle_design_change_welcome_text(callback_query: types.CallbackQuery, state: FSMContext):
    logging.info(f"[DESIGN][CLICK] Пользователь {callback_query.from_user.id} нажал кнопку 'Изменить парадное описание'")
    await callback_query.answer()
    await callback_query.message.edit_text("Введите новое парадное описание:")
    await state.set_state(SettingsStates.waiting_for_design_welcome_text)

@settings_design_router.message(StateFilter('SettingsStates:waiting_for_design_welcome_text'))
async def process_design_welcome_text(message: types.Message, state: FSMContext):
    if message.text and message.text.startswith('/'):
        await state.clear()
        await message.answer("Вышли из режима оформления.")
        return
    logging.info(f"[DESIGN] Пользователь {message.from_user.id} вводит парадное описание: {message.text}")
    await state.update_data(design_welcome_text=message.text)
    await message.answer(f"Парадное описание сохранено!")
    await show_design_menu(message, state)
    await state.set_state(None)

@settings_design_router.callback_query(lambda c: c.data == "design_change_welcome_image")
async def handle_design_change_welcome_image(callback_query: types.CallbackQuery, state: FSMContext):
    logging.info(f"[DESIGN][CLICK] Пользователь {callback_query.from_user.id} нажал кнопку 'Изменить парадную картинку'")
    await callback_query.answer()
    await callback_query.message.edit_text("Отправьте новую парадную картинку (фото):")
    await state.set_state(SettingsStates.waiting_for_design_welcome_image)

@settings_design_router.message(StateFilter('SettingsStates:waiting_for_design_welcome_image'))
async def process_design_welcome_image(message: types.Message, state: FSMContext):
    if message.text and message.text.startswith('/'):
        await state.clear()
        await message.answer("Вышли из режима оформления.")
        return
    if not message.photo:
        logging.info(f"[DESIGN] Пользователь {message.from_user.id} не отправил фото для парадной картинки")
        await message.answer("Пожалуйста, отправьте фото для парадной картинки.")
        return
    file_id = message.photo[-1].file_id
    logging.info(f"[DESIGN] Пользователь {message.from_user.id} отправил парадную картинку, file_id={file_id}")
    await state.update_data(design_welcome_image=file_id)
    await message.answer("Парадная картинка сохранена!")
    await show_design_menu(message, state)
    await state.set_state(None)

@settings_design_router.callback_query(lambda c: c.data == "design_change_description")
async def handle_design_change_description(callback_query: types.CallbackQuery, state: FSMContext):
    logging.info(f"[DESIGN][CLICK] Пользователь {callback_query.from_user.id} нажал кнопку 'Изменить описание'")
    await callback_query.answer()
    await callback_query.message.edit_text("Введите новое описание проекта:")
    await state.set_state(SettingsStates.waiting_for_design_description)

@settings_design_router.message(StateFilter('SettingsStates:waiting_for_design_description'))
async def process_design_description(message: types.Message, state: FSMContext):
    if message.text and message.text.startswith('/'):
        await state.clear()
        await message.answer("Вышли из режима оформления.")
        return
    logging.info(f"[DESIGN] Пользователь {message.from_user.id} вводит описание: {message.text}")
    await state.update_data(design_description=message.text)
    await message.answer(f"Описание проекта сохранено!")
    await show_design_menu(message, state)
    await state.set_state(None)

@settings_design_router.callback_query(lambda c: c.data == "apply_design")
async def handle_apply_design(callback_query: types.CallbackQuery, state: FSMContext):
    import httpx
    logging.info(f"[DESIGN][CLICK] Пользователь {callback_query.from_user.id} нажал кнопку 'Применить оформление'")
    await callback_query.answer()
    data = await state.get_data()
    project = data.get("selected_project")
    if not project:
        logging.error(f"[DESIGN] Не выбран проект для применения оформления пользователем {callback_query.from_user.id}")
        await callback_query.message.edit_text("Ошибка: проект не выбран")
        await state.clear()
        return
    token = project.get("token")
    if not token:
        logging.error(f"[DESIGN] Не найден токен бота проекта для пользователя {callback_query.from_user.id}")
        await callback_query.message.edit_text("Ошибка: не найден токен бота проекта")
        await state.clear()
        return
    api_url = f"https://api.telegram.org/bot{token}"
    design_name = data.get("design_name")
    design_avatar = data.get("design_avatar")
    design_welcome_text = data.get("design_welcome_text")
    design_welcome_image = data.get("design_welcome_image")
    design_description = data.get("design_description")
    results = []
    async with httpx.AsyncClient() as client:
        if design_name:
            logging.info(f"[DESIGN][API] Отправка setMyName: {design_name}")
            resp = await client.post(f"{api_url}/setMyName", json={"name": design_name})
            if resp.status_code == 200 and resp.json().get("ok"):
                results.append("Имя: ✅")
            else:
                results.append("Имя: ❌")
        if design_description:
            logging.info(f"[DESIGN][API] Отправка setMyDescription: {design_description}")
            resp = await client.post(f"{api_url}/setMyDescription", json={"description": design_description})
            if resp.status_code == 200 and resp.json().get("ok"):
                results.append("Описание: ✅")
            else:
                results.append("Описание: ❌")
        if design_welcome_text:
            logging.info(f"[DESIGN][API] Отправка setMyShortDescription: {design_welcome_text}")
            resp = await client.post(f"{api_url}/setMyShortDescription", json={"short_description": design_welcome_text})
            if resp.status_code == 200 and resp.json().get("ok"):
                results.append("Парадное сообщение: ✅")
            else:
                results.append("Парадное сообщение: ❌")
        if design_avatar:
            try:
                file = await callback_query.bot.get_file(design_avatar)
                file_path = file.file_path
                file_url = f"https://api.telegram.org/file/bot{callback_query.bot.token}/{file_path}"
                file_bytes = (await httpx.AsyncClient().get(file_url)).content
                files = {"photo": ("avatar.jpg", file_bytes)}
                resp = await client.post(f"{api_url}/setMyPhoto", files=files)
                if resp.status_code == 200 and resp.json().get("ok"):
                    results.append("Аватарка: ✅")
                else:
                    results.append("Аватарка: ❌")
            except Exception as e:
                logging.error(f"[DESIGN][API] Ошибка при установке аватарки: {e}")
                results.append(f"Аватарка: ❌ ({e})")
        if design_welcome_image:
            try:
                file = await callback_query.bot.get_file(design_welcome_image)
                file_path = file.file_path
                file_url = f"https://api.telegram.org/file/bot{callback_query.bot.token}/{file_path}"
                file_bytes = (await httpx.AsyncClient().get(file_url)).content
                files = {"photo": ("welcome.jpg", file_bytes)}
                resp = await client.post(f"{api_url}/setMyPhoto", files=files)
                if resp.status_code == 200 and resp.json().get("ok"):
                    results.append("Парадная картинка: ✅")
                else:
                    results.append("Парадная картинка: ❌")
            except Exception as e:
                logging.error(f"[DESIGN][API] Ошибка при установке парадной картинки: {e}")
                results.append(f"Парадная картинка: ❌ ({e})")
    text = "Результат применения оформления:\n" + "\n".join(results)
    await callback_query.message.edit_text(text)
    await state.update_data(design_name=None, design_avatar=None, design_welcome_text=None, design_welcome_image=None, design_description=None) 