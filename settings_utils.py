import logging
from functools import wraps
from aiogram.filters import StateFilter
import inspect

async def log_fsm_state(message, state):
    current_state = await state.get_state()
    logging.info(f"[FSM] user={message.from_user.id} current_state={current_state}")

async def handle_command_in_state(message, state) -> bool:
    from settings_states import SettingsStates
    from settings_bot import handle_settings_start, handle_projects_command, handle_help_command, handle_feedback_command
    if message.text and message.text.startswith('/'):
        command = message.text.split()[0].lower()
        await state.clear()
        if command == '/start':
            await handle_settings_start(message, state)
        elif command == '/projects':
            await handle_projects_command(message, state)
        elif command == '/help':
            await handle_help_command(message, state)
        elif command == '/feedback':
            await handle_feedback_command(message, state)
        else:
            await message.answer("Неизвестная команда. Используйте /help для справки.")
        return True
    return False

# --- Супер-декоратор для автоматической регистрации хэндлеров ---
def auto_handler(router, handler_type, *args, **kwargs):
    def decorator(func):
        reg = getattr(router, handler_type)
        reg(*args, **kwargs)(func)
        return func
    return decorator

# --- Автоматическая регистрация всех функций-хэндлеров из модуля ---
def auto_register_handlers(router, module):
    """
    Автоматически регистрирует все функции-хэндлеры из модуля в роутер.
    - Если имя начинается с waiting_for_ — FSM message handler (state=SettingsStates:...)
    - Если имя начинается с field_type_ или del_field_ — callback_query startswith
    - Иначе — callback_query по точному совпадению имени с callback_data
    
    Пример вызова:
        import settings_forms
        auto_register_handlers(settings_forms_router, settings_forms)
    """
    for name, func in inspect.getmembers(module, inspect.isfunction):
        if name.startswith("waiting_for_"):
            state_name = f"SettingsStates:{name}"
            router.message(StateFilter(state_name))(func)
        elif name.startswith("field_type_"):
            router.callback_query(lambda c, n=name: c.data.startswith("field_type_"))(func)
        elif name.startswith("del_field_"):
            router.callback_query(lambda c, n=name: c.data.startswith("del_field_"))(func)
        else:
            router.callback_query(lambda c, n=name: c.data == n)(func) 