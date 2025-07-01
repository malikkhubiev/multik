from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import add_feedback
from settings_states import SettingsStates

async def handle_feedback_command(message, state):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Супер", callback_data="feedback_rate:positive"),
             InlineKeyboardButton(text="Так себе", callback_data="feedback_rate:negative")]
        ]
    )
    await message.answer(
        "Как вам впечатление от сервиса?",
        reply_markup=kb
    )
    await state.set_state(SettingsStates.waiting_for_feedback_rating)

async def handle_feedback_rating_callback(callback_query, state):
    # Сохраняем выбранную оценку
    rate = callback_query.data.split(":")[1]
    await state.update_data(feedback_rating=rate)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Изменить выбор", callback_data="feedback_change_rating")]
        ]
    )
    text = "Пожалуйста, опишите своё впечатление. Нам важно ваше мнение!\n\nВыбранная оценка: "
    text += "Супер" if rate == "positive" else "Так себе"
    await callback_query.message.answer(text, reply_markup=kb)
    await state.set_state(SettingsStates.waiting_for_feedback_text)
    await callback_query.answer()

async def handle_feedback_change_rating(callback_query, state):
    # Возврат к выбору оценки
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Супер", callback_data="feedback_rate:positive"),
             InlineKeyboardButton(text="Так себе", callback_data="feedback_rate:negative")]
        ]
    )
    await callback_query.message.answer(
        "Как вам впечатление от сервиса?",
        reply_markup=kb
    )
    await state.set_state(SettingsStates.waiting_for_feedback_rating)
    await callback_query.answer()

async def handle_feedback_text(message, state):
    data = await state.get_data()
    feedback_rating = data.get("feedback_rating")
    feedback_text = message.text
    username = message.from_user.username
    telegram_id = str(message.from_user.id)
    is_positive = True if feedback_rating == "positive" else False if feedback_rating == "negative" else None
    await add_feedback(telegram_id, username, feedback_text, is_positive)
    await message.answer("Спасибо за ваш отзыв! Он очень важен для нас.")
    await state.clear() 