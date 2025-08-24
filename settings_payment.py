from config import PAYMENT_AMOUNT, PAYMENT_CARD_NUMBER1, PAYMENT_CARD_NUMBER2, PAYMENT_CARD_NUMBER3, MAIN_TELEGRAM_ID, PAID_PROJECTS
from database import set_user_paid, get_user_projects, get_payments, log_payment
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import logging
import random

async def send_pay_instructions(send_method):
    card = random.choice([PAYMENT_CARD_NUMBER1, PAYMENT_CARD_NUMBER2, PAYMENT_CARD_NUMBER3])
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
        # Логируем информацию о сообщении
        logging.info(f"[PAYMENT] forward_check_with_notice: тип сообщения = {message.content_type}")
        logging.info(f"[PAYMENT] forward_check_with_notice: MAIN_TELEGRAM_ID = {MAIN_TELEGRAM_ID}")
        
        # Пересылаем сообщение админу
        try:
            await message.forward(MAIN_TELEGRAM_ID)
            logging.info(f"[PAYMENT] forward_check_with_notice: ✅ сообщение успешно переслано админу {MAIN_TELEGRAM_ID}")
        except Exception as forward_error:
            logging.error(f"[PAYMENT] forward_check_with_notice: ❌ ОШИБКА при пересылке сообщения: {forward_error}")
            raise forward_error
        
        # Отправляем уведомление
        if notice_text is None:
            notice_text = f"Оплатил {telegram_id}"
        
        try:
            await message.bot.send_message(MAIN_TELEGRAM_ID, notice_text)
            logging.info(f"[PAYMENT] forward_check_with_notice: ✅ отправлено уведомление админу: {notice_text}")
        except Exception as notice_error:
            logging.error(f"[PAYMENT] forward_check_with_notice: ❌ ОШИБКА при отправке уведомления: {notice_error}")
            raise notice_error
        
        # Отправляем стоимость текущей и предпоследней оплаты ОТДЕЛЬНЫМИ SMS-сообщениями
        logging.info(f"[PAYMENT] forward_check_with_notice: получаем список платежей...")
        try:
            payments = await get_payments()
            logging.info(f"[PAYMENT] forward_check_with_notice: ✅ получено {len(payments)} платежей из БД")
        except Exception as payments_error:
            logging.error(f"[PAYMENT] forward_check_with_notice: ❌ ОШИБКА при получении платежей: {payments_error}")
            # Не поднимаем исключение, продолжаем обработку
            payments = []
        
        user_payments = [p for p in payments if str(p['telegram_id']) == telegram_id]
        logging.info(f"[PAYMENT] forward_check_with_notice: найдено {len(user_payments)} платежей для пользователя {telegram_id}")
        
        user_payments_sorted = sorted(user_payments, key=lambda p: p['paid_at'])
        logging.info(f"[PAYMENT] forward_check_with_notice: отсортировано {len(user_payments_sorted)} платежей")
        
        if user_payments_sorted:
            # Определяем правильную сумму для следующего платежа
            from config import DISCOUNT_PAYMENT_AMOUNT, PAYMENT_AMOUNT
            
            # Подсчитываем количество подтвержденных платежей
            confirmed_payments = [p for p in user_payments_sorted if p['status'] == 'confirmed']
            payment_count = len(confirmed_payments)
            
            if payment_count == 0:
                # Первый платеж - используем скидочную сумму
                next_payment_amount = DISCOUNT_PAYMENT_AMOUNT
                logging.info(f"[PAYMENT] forward_check_with_notice: первый платеж пользователя, сумма = {next_payment_amount}")
            else:
                # Повторный платеж - используем полную сумму
                next_payment_amount = PAYMENT_AMOUNT
                logging.info(f"[PAYMENT] forward_check_with_notice: повторный платеж пользователя (№{payment_count + 1}), сумма = {next_payment_amount}")
            
            # Создаем новый pending платеж с правильной суммой
            try:
                await log_payment(telegram_id, next_payment_amount, status='pending')
                logging.info(f"[PAYMENT] forward_check_with_notice: ✅ новый pending платеж создан: пользователь {telegram_id}, сумма {next_payment_amount}")
            except Exception as db_error:
                logging.error(f"[PAYMENT] forward_check_with_notice: ❌ ОШИБКА при создании pending платежа: {db_error}")
                raise db_error
            
            # Отправляем правильную сумму отдельным SMS-сообщением
            try:
                await message.bot.send_message(MAIN_TELEGRAM_ID, f"💰 Сумма: {next_payment_amount} руб.")
                logging.info(f"[PAYMENT] forward_check_with_notice: ✅ отправлена правильная сумма {next_payment_amount} админу отдельным SMS")
            except Exception as amount_error:
                logging.error(f"[PAYMENT] forward_check_with_notice: ❌ ОШИБКА при отправке суммы {next_payment_amount}: {amount_error}")
                raise amount_error
            
            # Показываем информацию о предыдущих платежах
            if len(confirmed_payments) > 0:
                last_confirmed = confirmed_payments[-1]
                prev_amount = last_confirmed['amount']
                logging.info(f"[PAYMENT] forward_check_with_notice: последний подтвержденный платеж = {prev_amount}")
                
                # Отправляем информацию о предыдущем платеже
                try:
                    await message.bot.send_message(MAIN_TELEGRAM_ID, f"📊 Последний подтвержденный платеж: {prev_amount} руб.")
                    logging.info(f"[PAYMENT] forward_check_with_notice: ✅ отправлена информация о предыдущем платеже {prev_amount} админу")
                except Exception as prev_amount_error:
                    logging.error(f"[PAYMENT] forward_check_with_notice: ❌ ОШИБКА при отправке информации о предыдущем платеже {prev_amount}: {prev_amount_error}")
                    raise prev_amount_error
            else:
                logging.info(f"[PAYMENT] forward_check_with_notice: это первый платеж пользователя")
        else:
            logging.warning(f"[PAYMENT] forward_check_with_notice: ⚠️ НЕ НАЙДЕНО платежей для пользователя {telegram_id}")
            
            # Создаем pending платеж в базе данных
            try:
                from config import DISCOUNT_PAYMENT_AMOUNT, PAYMENT_AMOUNT
                
                # Получаем все платежи пользователя для определения типа платежа
                all_payments = await get_payments()
                user_all_payments = [p for p in all_payments if str(p['telegram_id']) == telegram_id]
                
                if len(user_all_payments) == 0:
                    # Первый платеж - используем скидочную сумму
                    payment_amount = DISCOUNT_PAYMENT_AMOUNT
                    logging.info(f"[PAYMENT] forward_check_with_notice: первый платеж пользователя, сумма = {payment_amount}")
                else:
                    # Повторный платеж - используем полную сумму
                    payment_amount = PAYMENT_AMOUNT
                    logging.info(f"[PAYMENT] forward_check_with_notice: повторный платеж пользователя, сумма = {payment_amount}")
                
                # Создаем pending платеж в базе данных
                try:
                    await log_payment(telegram_id, payment_amount, status='pending')
                    logging.info(f"[PAYMENT] forward_check_with_notice: ✅ pending платеж создан в БД: пользователь {telegram_id}, сумма {payment_amount}")
                except Exception as db_error:
                    logging.error(f"[PAYMENT] forward_check_with_notice: ❌ ОШИБКА при создании pending платежа в БД: {db_error}")
                    raise db_error
                
                # Отправляем точную сумму отдельным SMS-сообщением
                try:
                    await message.bot.send_message(MAIN_TELEGRAM_ID, f"💰 Сумма: {payment_amount} руб.")
                    logging.info(f"[PAYMENT] forward_check_with_notice: ✅ отправлена точная сумма {payment_amount} админу отдельным SMS")
                except Exception as amount_error:
                    logging.error(f"[PAYMENT] forward_check_with_notice: ❌ ОШИБКА при отправке суммы {payment_amount}: {amount_error}")
                    raise amount_error
                    
            except Exception as config_error:
                logging.error(f"[PAYMENT] forward_check_with_notice: ❌ ОШИБКА при определении суммы платежа: {config_error}")
                # Отправляем сообщение об ошибке
                try:
                    await message.bot.send_message(MAIN_TELEGRAM_ID, f"⚠️ Не удалось определить сумму платежа для пользователя {telegram_id}")
                    logging.info(f"[PAYMENT] forward_check_with_notice: ✅ отправлено уведомление об ошибке определения суммы")
                except Exception as error_msg_error:
                    logging.error(f"[PAYMENT] forward_check_with_notice: ❌ ОШИБКА при отправке уведомления об ошибке: {error_msg_error}")
            
        logging.info(f"[PAYMENT] forward_check_with_notice: ✅ обработка завершена успешно для пользователя {telegram_id}")
            
    except Exception as e:
        logging.error(f"[PAYMENT] forward_check_with_notice: ❌ ОШИБКА при обработке: {e}")
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