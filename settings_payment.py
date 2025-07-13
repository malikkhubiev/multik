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
    logging.info(f"[PAYMENT] forward_check_with_notice: начало обработки для пользователя {telegram_id}")
    
    try:
        await message.forward(MAIN_TELEGRAM_ID)
        logging.info(f"[PAYMENT] forward_check_with_notice: сообщение переслано админу {MAIN_TELEGRAM_ID}")
        
        if notice_text is None:
            notice_text = f"Оплатил {telegram_id}"
        await message.bot.send_message(MAIN_TELEGRAM_ID, notice_text)
        logging.info(f"[PAYMENT] forward_check_with_notice: отправлено уведомление админу: {notice_text}")
        
        # Отправляем стоимость текущей и предпоследней оплаты
        logging.info(f"[PAYMENT] forward_check_with_notice: получаем список платежей...")
        payments = await get_payments()
        logging.info(f"[PAYMENT] forward_check_with_notice: получено {len(payments)} платежей из БД")
        
        user_payments = [p for p in payments if str(p['telegram_id']) == telegram_id]
        logging.info(f"[PAYMENT] forward_check_with_notice: найдено {len(user_payments)} платежей для пользователя {telegram_id}")
        
        user_payments_sorted = sorted(user_payments, key=lambda p: p['paid_at'])
        logging.info(f"[PAYMENT] forward_check_with_notice: отсортировано {len(user_payments_sorted)} платежей")
        
        if user_payments_sorted:
            last_amount = user_payments_sorted[-1]['amount']
            logging.info(f"[PAYMENT] forward_check_with_notice: последний платеж = {last_amount}")
            await message.bot.send_message(MAIN_TELEGRAM_ID, f"Текущая сумма оплаты: {last_amount}")
            logging.info(f"[PAYMENT] forward_check_with_notice: отправлена текущая сумма {last_amount} админу")
            
            if len(user_payments_sorted) > 1:
                prev_amount = user_payments_sorted[-2]['amount']
                logging.info(f"[PAYMENT] forward_check_with_notice: предыдущий платеж = {prev_amount}")
                await message.bot.send_message(MAIN_TELEGRAM_ID, f"Предыдущая сумма оплаты: {prev_amount}")
                logging.info(f"[PAYMENT] forward_check_with_notice: отправлена предыдущая сумма {prev_amount} админу")
            else:
                logging.info(f"[PAYMENT] forward_check_with_notice: это первый платеж пользователя")
        else:
            logging.warning(f"[PAYMENT] forward_check_with_notice: НЕ НАЙДЕНО платежей для пользователя {telegram_id}")
            
    except Exception as e:
        logging.error(f"[PAYMENT] forward_check_with_notice: ОШИБКА при обработке: {e}")
        import traceback
        logging.error(f"[PAYMENT] forward_check_with_notice: полный traceback: {traceback.format_exc()}")
        raise

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