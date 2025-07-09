from config import PAYMENT_AMOUNT, PAYMENT_CARD_NUMBER, MAIN_TELEGRAM_ID, PAID_PROJECTS
from database import set_user_paid, get_user_projects, get_payments
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

async def forward_check_with_notice(message, notice_text=None):
    telegram_id = str(message.from_user.id)
    await message.forward(MAIN_TELEGRAM_ID)
    if notice_text is None:
        notice_text = f"Оплатил {telegram_id}"
    await message.bot.send_message(MAIN_TELEGRAM_ID, notice_text)
    # Отправляем стоимость текущей и предпоследней оплаты
    payments = await get_payments()
    user_payments = [p for p in payments if str(p['telegram_id']) == telegram_id]
    user_payments_sorted = sorted(user_payments, key=lambda p: p['paid_at'])
    if user_payments_sorted:
        last_amount = user_payments_sorted[-1]['amount']
        await message.bot.send_message(MAIN_TELEGRAM_ID, f"Текущая сумма оплаты: {last_amount}")
        if len(user_payments_sorted) > 1:
            prev_amount = user_payments_sorted[-2]['amount']
            await message.bot.send_message(MAIN_TELEGRAM_ID, f"Предыдущая сумма оплаты: {prev_amount}")

async def handle_payment_check(message, state):
    try:
        await forward_check_with_notice(message)
        await message.answer("Чек отправлен на проверку. Ожидайте подтверждения оплаты.")
    except Exception as e:
        logging.error(f"[PAYMENT] Ошибка при пересылке чека админу: {e}")
        await message.answer("Ошибка при отправке чека админу. Попробуйте позже или свяжитесь с поддержкой.")

async def handle_payment_check_document(message, state):
    try:
        await forward_check_with_notice(message)
        await message.answer("Чек отправлен на проверку. Ожидайте подтверждения оплаты.")
    except Exception as e:
        logging.error(f"[PAYMENT] Ошибка при пересылке чека-документа админу: {e}")
        await message.answer("Ошибка при отправке чека админу. Попробуйте позже или свяжитесь с поддержкой.")

async def handle_payment_check_document_any(message, state):
    try:
        await forward_check_with_notice(message)
        await message.answer("Документ отправлен на проверку. Ожидайте подтверждения оплаты.")
    except Exception as e:
        logging.error(f"[PAYMENT] Ошибка при пересылке документа админу: {e}")
        await message.answer("Ошибка при отправке документа админу. Попробуйте позже или свяжитесь с поддержкой.")

async def handle_payment_check_photo_any(message, state):
    try:
        await forward_check_with_notice(message)
        await message.answer("Фото отправлено на проверку. Ожидайте подтверждения оплаты.")
    except Exception as e:
        logging.error(f"[PAYMENT] Ошибка при пересылке фото админу: {e}")
        await message.answer("Ошибка при отправке фото админу. Попробуйте позже или свяжитесь с поддержкой.") 