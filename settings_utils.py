import logging
from functools import wraps
from aiogram.filters import StateFilter

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

# --- Фабрика-декоратор для оформления и форм ---
def make_handler(router):
    def handler(event_key, *, state=None):
        """
        event_key: str — callback_data (для callback_query) или state (для message)
        state: bool — если True, то message-хэндлер по FSM, иначе callback_query
        """
        def decorator(func):
            if state:
                # FSM message handler
                router.message(StateFilter(event_key))(func)
            else:
                # Callback handler
                router.callback_query(lambda c: c.data == event_key)(func)
            return func
        return decorator
    handler.state = lambda state_name: make_handler(router)(state_name, state=True)
    return handler 