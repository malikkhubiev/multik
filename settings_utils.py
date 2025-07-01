import logging

async def log_fsm_state(message, state):
    current_state = await state.get_state()
    logging.info(f"[FSM] user={message.from_user.id} current_state={current_state}")

async def handle_command_in_state(message, state) -> bool:
    from settings_states import SettingsStates
    from settings_bot import handle_settings_start, handle_projects_command, handle_help_command
    if message.text and message.text.startswith('/'):
        command = message.text.split()[0].lower()
        await state.clear()
        if command == '/start':
            await handle_settings_start(message, state)
        elif command == '/projects':
            await handle_projects_command(message, state)
        elif command == '/help':
            await handle_help_command(message, state)
        else:
            await message.answer("Неизвестная команда. Используйте /help для справки.")
        return True
    return False 