# settings_design.py
from aiogram import types, Router
from aiogram.fsm.context import FSMContext
import logging
from settings_states import SettingsStates

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

async def open_design(q, s):
    logging.info(f"[DESIGN][CLICK] Пользователь {q.from_user.id} нажал кнопку 'Оформление'")
    current_state = await s.get_state()
    logging.info(f"[DESIGN][DEBUG] FSM state при входе: {current_state}")
    data = await s.get_data()
    logging.info(f"[DESIGN][DEBUG] FSM data при входе: {data}")
    project = data.get("selected_project")
    logging.info(f"[DESIGN][DEBUG] selected_project: {project}")
    await q.answer()
    try:
        await show_design_menu(q.message, s)
    except Exception as e:
        logging.error(f"[DESIGN][ERROR] Ошибка в show_design_menu: {e}")
        await q.message.answer(f"Ошибка при открытии меню оформления: {e}")

async def design_change_name(q, s):
    logging.info(f"[DESIGN][CLICK] Пользователь {q.from_user.id} нажал кнопку 'Изменить имя'")
    await q.answer()
    await q.message.edit_text("Введите новое имя бота:")
    await s.set_state(SettingsStates.waiting_for_design_name)

async def waiting_for_design_name(m, s):
    current_state = await s.get_state()
    logging.info(f"[FSM] process_design_name CALLED for user={m.from_user.id}, text={m.text}, state={current_state}")
    if m.text and m.text.startswith('/'):
        await s.clear()
        await m.answer("Вышли из режима оформления.")
        return
    await s.update_data(design_name=m.text)
    logging.info(f"[FSM] process_design_name: design_name set for user={m.from_user.id}, name={m.text}")
    await show_design_menu(m, s)
    await s.set_state(None)
    logging.info(f"[FSM] process_design_name END: Состояние сброшено после показа меню оформления для user={m.from_user.id}")

async def design_change_avatar(q, s):
    logging.info(f"[DESIGN][CLICK] Пользователь {q.from_user.id} нажал кнопку 'Изменить аватарку'")
    await q.answer()
    await q.message.edit_text("Отправьте новую аватарку (фото):")
    await s.set_state(SettingsStates.waiting_for_design_avatar)

async def waiting_for_design_avatar(m, s):
    if m.text and m.text.startswith('/'):
        await s.clear()
        await m.answer("Вышли из режима оформления.")
        return
    if not m.photo:
        logging.info(f"[DESIGN] Пользователь {m.from_user.id} не отправил фото для аватарки")
        await m.answer("Пожалуйста, отправьте фото для аватарки.")
        return
    file_id = m.photo[-1].file_id
    logging.info(f"[DESIGN] Пользователь {m.from_user.id} отправил аватарку, file_id={file_id}")
    await s.update_data(design_avatar=file_id)
    await m.answer("Аватарка сохранена!")
    await show_design_menu(m, s)
    await s.set_state(None)

async def design_change_welcome_text(q, s):
    logging.info(f"[DESIGN][CLICK] Пользователь {q.from_user.id} нажал кнопку 'Изменить парадное описание'")
    await q.answer()
    await q.message.edit_text("Введите новое парадное описание:")
    await s.set_state(SettingsStates.waiting_for_design_welcome_text)

async def waiting_for_design_welcome_text(m, s):
    if m.text and m.text.startswith('/'):
        await s.clear()
        await m.answer("Вышли из режима оформления.")
        return
    logging.info(f"[DESIGN] Пользователь {m.from_user.id} вводит парадное описание: {m.text}")
    await s.update_data(design_welcome_text=m.text)
    await m.answer(f"Парадное описание сохранено!")
    await show_design_menu(m, s)
    await s.set_state(None)

async def design_change_welcome_image(q, s):
    logging.info(f"[DESIGN][CLICK] Пользователь {q.from_user.id} нажал кнопку 'Изменить парадную картинку'")
    await q.answer()
    await q.message.edit_text("Отправьте новую парадную картинку (фото):")
    await s.set_state(SettingsStates.waiting_for_design_welcome_image)

async def waiting_for_design_welcome_image(m, s):
    if m.text and m.text.startswith('/'):
        await s.clear()
        await m.answer("Вышли из режима оформления.")
        return
    if not m.photo:
        logging.info(f"[DESIGN] Пользователь {m.from_user.id} не отправил фото для парадной картинки")
        await m.answer("Пожалуйста, отправьте фото для парадной картинки.")
        return
    file_id = m.photo[-1].file_id
    logging.info(f"[DESIGN] Пользователь {m.from_user.id} отправил парадную картинку, file_id={file_id}")
    await s.update_data(design_welcome_image=file_id)
    await m.answer("Парадная картинка сохранена!")
    await show_design_menu(m, s)
    await s.set_state(None)

async def design_change_description(q, s):
    logging.info(f"[DESIGN][CLICK] Пользователь {q.from_user.id} нажал кнопку 'Изменить описание'")
    await q.answer()
    await q.message.edit_text("Введите новое описание проекта:")
    await s.set_state(SettingsStates.waiting_for_design_description)

async def waiting_for_design_description(m, s):
    if m.text and m.text.startswith('/'):
        await s.clear()
        await m.answer("Вышли из режима оформления.")
        return
    logging.info(f"[DESIGN] Пользователь {m.from_user.id} вводит описание: {m.text}")
    await s.update_data(design_description=m.text)
    await m.answer(f"Описание проекта сохранено!")
    await show_design_menu(m, s)
    await s.set_state(None)

async def apply_design(q, s):
    import httpx
    logging.info(f"[DESIGN][CLICK] Пользователь {q.from_user.id} нажал кнопку 'Применить оформление'")
    await q.answer()
    data = await s.get_data()
    project = data.get("selected_project")
    if not project:
        logging.error(f"[DESIGN] Не выбран проект для применения оформления пользователем {q.from_user.id}")
        await q.message.edit_text("Ошибка: проект не выбран")
        await s.clear()
        return
    token = project.get("token")
    if not token:
        logging.error(f"[DESIGN] Не найден токен бота проекта для пользователя {q.from_user.id}")
        await q.message.edit_text("Ошибка: не найден токен бота проекта")
        await s.clear()
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
                file = await q.bot.get_file(design_avatar)
                file_path = file.file_path
                file_url = f"https://api.telegram.org/file/bot{q.bot.token}/{file_path}"
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
                file = await q.bot.get_file(design_welcome_image)
                file_path = file.file_path
                file_url = f"https://api.telegram.org/file/bot{q.bot.token}/{file_path}"
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
    await q.message.edit_text(text)
    await s.update_data(design_name=None, design_avatar=None, design_welcome_text=None, design_welcome_image=None, design_description=None) 