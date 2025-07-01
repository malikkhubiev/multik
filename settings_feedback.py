from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import add_feedback
from settings_states import SettingsStates

async def handle_feedback_command(message, state):
    await message.answer(
        "Пожалуйста, напишите ваш отзыв о сервисе. После отправки вы сможете отметить, положительный он или нет."
    )
    await state.set_state(SettingsStates.waiting_for_feedback_text)

async def handle_feedback_text(message, state):
    await state.update_data(feedback_text=message.text)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👍 Положительный", callback_data="feedback_positive")],
            [InlineKeyboardButton(text="👎 Отрицательный", callback_data="feedback_negative")]
        ]
    )
    await message.answer("Спасибо! Отметьте, как вы оцениваете сервис:", reply_markup=kb)

async def handle_feedback_rating(callback_query, state):
    data = await state.get_data()
    feedback_text = data.get("feedback_text")
    is_positive = callback_query.data == "feedback_positive"
    username = callback_query.from_user.username
    telegram_id = str(callback_query.from_user.id)
    await add_feedback(telegram_id, username, feedback_text, is_positive)
    await callback_query.message.answer("Спасибо за ваш отзыв! Он очень важен для нас.")
    await state.clear()
    await callback_query.answer() 