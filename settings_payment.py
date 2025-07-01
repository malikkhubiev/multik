from config import PAYMENT_AMOUNT, PAYMENT_CARD_NUMBER, MAIN_TELEGRAM_ID, PAID_PROJECTS
from database import set_user_paid, get_user_projects
from utils import set_webhook
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging

async def send_pay_instructions(send_method):
    await send_method(
        f"Для оплаты переведите {PAYMENT_AMOUNT} рублей на карту: {PAYMENT_CARD_NUMBER}\n\nПосле оплаты отправьте чек сюда (фото/скриншот)."
    )

async def handle_pay_command(message, state):
    await send_pay_instructions(message.answer)

async def handle_pay_callback(callback_query, state):
    await send_pay_instructions(callback_query.message.answer)
    await callback_query.answer()

async def handle_payment_check(message, state):
    telegram_id = str(message.from_user.id)
    try:
        await message.forward(MAIN_TELEGRAM_ID)
        await message.answer("Чек отправлен на проверку. Ожидайте подтверждения оплаты.")
    except Exception as e:
        logging.error(f"[PAYMENT] Ошибка при пересылке чека админу: {e}")
        await message.answer("Ошибка при отправке чека админу. Попробуйте позже или свяжитесь с поддержкой.")

async def handle_payment_check_document(message, state):
    telegram_id = str(message.from_user.id)
    try:
        await message.forward(MAIN_TELEGRAM_ID)
        await message.answer("Чек отправлен на проверку. Ожидайте подтверждения оплаты.")
    except Exception as e:
        logging.error(f"[PAYMENT] Ошибка при пересылке чека-документа админу: {e}")
        await message.answer("Ошибка при отправке чека админу. Попробуйте позже или свяжитесь с поддержкой.")

async def handle_payment_check_document_any(message, state):
    telegram_id = str(message.from_user.id)
    try:
        await message.forward(MAIN_TELEGRAM_ID)
        await message.answer("Документ отправлен на проверку. Ожидайте подтверждения оплаты.")
    except Exception as e:
        logging.error(f"[PAYMENT] Ошибка при пересылке документа админу: {e}")
        await message.answer("Ошибка при отправке документа админу. Попробуйте позже или свяжитесь с поддержкой.")

async def handle_payment_check_photo_any(message, state):
    telegram_id = str(message.from_user.id)
    try:
        await message.forward(MAIN_TELEGRAM_ID)
        await message.answer("Фото отправлено на проверку. Ожидайте подтверждения оплаты.")
    except Exception as e:
        logging.error(f"[PAYMENT] Ошибка при пересылке фото админу: {e}")
        await message.answer("Ошибка при отправке фото админу. Попробуйте позже или свяжитесь с поддержкой.") 