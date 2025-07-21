# settings_forms.py
from aiogram import types
from aiogram.fsm.context import FSMContext
import logging
from settings_states import SettingsStates

async def create_form(q, s):
    logging.info(f"[FORM] handle_create_form: user={q.from_user.id} (начало создания формы)")
    await s.update_data(form_draft={"fields": []})
    form_text = """
📋 **Создание формы для сбора заявок**

Форма поможет собирать информацию от клиентов:
• ФИО, телефон, удобное время
• Специализированные данные (марка машины, возраст студента и т.д.)
• Asking бот будет непринужденно собирать эту информацию

Нажмите 'Добавить поле', чтобы начать создание формы.
    """
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Добавить поле", callback_data="add_form_field")],
        [types.InlineKeyboardButton(text="Отмена", callback_data="back_to_projects")]
    ])
    logging.info(f"[FORM] handle_create_form: user={q.from_user.id} (черновик формы создан)")
    await q.message.edit_text(form_text, reply_markup=keyboard)

async def add_form_field(q, s):
    await q.message.edit_text(
        "Введите название поля формы:\n\nНапример: ФИО, Телефон, Марка машины, Возраст студента и т.д.",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="Отмена", callback_data="back_to_projects")]
        ])
    )
    await s.set_state(SettingsStates.waiting_for_field_name)

async def waiting_for_field_name(m, s):
    current_state = await s.get_state()
    logging.info(f"[FORM] handle_field_name: user={m.from_user.id}, state={current_state}, text={m.text}")
    await s.update_data(field_name=m.text)
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Текст", callback_data="field_type_text")],
        [types.InlineKeyboardButton(text="Число", callback_data="field_type_number")],
        [types.InlineKeyboardButton(text="Телефон", callback_data="field_type_phone")],
        [types.InlineKeyboardButton(text="Дата", callback_data="field_type_date")],
        [types.InlineKeyboardButton(text="Email", callback_data="field_type_email")],
        [types.InlineKeyboardButton(text="Назад", callback_data="add_form_field")]
    ])
    await m.answer(
        f"Выберите тип поля для '{m.text}':",
        reply_markup=keyboard
    )
    await s.set_state(SettingsStates.waiting_for_field_type)

async def field_type(q, s):
    field_type = q.data.replace("field_type_", "")
    data = await s.get_data()
    field_name = data.get("field_name")
    form_draft = data.get("form_draft", {"fields": []})
    logging.info(f"[FORM] handle_field_type: user={q.from_user.id}, field_name={field_name}, field_type={field_type}")
    if any(f['name'].strip().lower() == field_name.strip().lower() for f in form_draft["fields"]):
        await q.message.answer(f"Поле с названием '{field_name}' уже есть в форме. Введите уникальное название поля.")
        await s.set_state(SettingsStates.waiting_for_field_name)
        return
    form_draft["fields"].append({"name": field_name, "type": field_type, "required": False})
    await s.update_data(form_draft=form_draft)
    fields_text = "\n".join([
        f"{i+1}. {f['name']} ({f['type']})"
        for i, f in enumerate(form_draft["fields"])
    ]) or "Нет полей"
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Добавить еще поле", callback_data="add_form_field")],
        [types.InlineKeyboardButton(text="Завершить и использовать форму", callback_data="use_form")],
        [types.InlineKeyboardButton(text="Назад к проекту", callback_data="back_to_projects")]
    ] + [
        [types.InlineKeyboardButton(text=f"Удалить поле {f['name']}", callback_data=f"del_field_{i}")] for i, f in enumerate(form_draft["fields"])
    ])
    logging.info(f"[FORM] handle_field_type: user={q.from_user.id}, form_draft={form_draft}")
    await q.message.edit_text(
        f"Поля формы:\n{fields_text}\n\nХотите добавить еще поле или использовать форму?",
        reply_markup=keyboard
    )
    await s.set_state(SettingsStates.form_draft_edit)

async def del_field(q, s):
    idx = int(q.data.replace("del_field_", ""))
    data = await s.get_data()
    form_draft = data.get("form_draft", {"fields": []})
    if 0 <= idx < len(form_draft["fields"]):
        form_draft["fields"].pop(idx)
        await s.update_data(form_draft=form_draft)
    fields_text = "\n".join([
        f"{i+1}. {f['name']} ({f['type']})"
        for i, f in enumerate(form_draft["fields"])
    ]) or "Нет полей"
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Добавить еще поле", callback_data="add_form_field")],
        [types.InlineKeyboardButton(text="Завершить и использовать форму", callback_data="use_form")],
        [types.InlineKeyboardButton(text="Назад к проекту", callback_data="back_to_projects")]
    ] + [
        [types.InlineKeyboardButton(text=f"Удалить поле {f['name']}", callback_data=f"del_field_{i}")] for i, f in enumerate(form_draft["fields"])
    ])
    await q.message.edit_text(
        f"Поля формы:\n{fields_text}\n\nХотите добавить еще поле или использовать форму?",
        reply_markup=keyboard
    )
    await s.set_state(SettingsStates.form_draft_edit)

async def use_form(q, s):
    data = await s.get_data()
    form_draft = data.get("form_draft")
    project_id = data.get("selected_project_id")
    logging.info(f"[FORM] handle_use_form: user={q.from_user.id}, project_id={project_id}, form_draft={form_draft}")
    if not form_draft or not form_draft["fields"]:
        logging.warning(f"[FORM] handle_use_form: попытка сохранить пустую форму (form_draft={form_draft})")
        await q.answer("Сначала добавьте хотя бы одно поле")
        return
    await s.update_data(form_draft=form_draft, form_stage="waiting_for_purpose")
    await q.message.edit_text(
        "Зачем нужна заявка?\n\nНапример: Для того, чтобы мой сотрудник связался по телефону и договорился об индивидуальной консультации.\n\nЧем подробнее будет цель, тем лучше!",
    )
    await s.set_state(SettingsStates.waiting_for_form_purpose)

async def waiting_for_form_purpose(m, s):
    data = await s.get_data()
    form_draft = data.get("form_draft")
    project_id = data.get("selected_project_id")
    purpose = m.text.strip()
    logging.info(f"[FORM] handle_form_purpose: user={m.from_user.id}, project_id={project_id}, purpose={purpose}")
    from database import create_form, add_form_field, set_form_purpose
    form_name = f"Форма проекта {project_id}"
    form_id = await create_form(project_id, form_name)
    for field in form_draft["fields"]:
        await add_form_field(form_id, field["name"], field["type"], field.get("required", False))
    await set_form_purpose(form_id, purpose)
    await m.answer(
        "✅ Форма создана и готова к использованию!\n\nAsking бот будет автоматически собирать информацию от клиентов по этой форме.",
    )
    logging.info(f"[FORM] handle_form_purpose: форма {form_id} успешно сохранена с целью '{purpose}' и готова к использованию")
    await s.clear()

async def export_form_submissions(q, s):
    import pandas as pd
    import io
    from database import get_project_form, get_form_submissions
    await q.answer()
    data = await s.get_data()
    project_id = data.get("selected_project_id")
    if not project_id:
        await q.message.answer("Ошибка: проект не выбран")
        return
    form = await get_project_form(project_id)
    if not form:
        await q.message.answer("У проекта нет формы для экспорта заявок.")
        return
    submissions = await get_form_submissions(form["id"])
    if not submissions:
        await q.message.answer("Нет заявок для экспорта.")
        return
    rows = []
    for sub in submissions:
        row = {"telegram_id": sub["telegram_id"], "submitted_at": sub["submitted_at"]}
        row.update(sub["data"])
        rows.append(row)
    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Submissions")
    output.seek(0)
    await q.message.answer_document(
        types.InputFile(output, filename="form_submissions.xlsx"),
        caption="Экспорт заявок из формы"
    ) 