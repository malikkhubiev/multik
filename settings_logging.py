from database import log_message_stat as db_log_message_stat

async def log_message_stat(telegram_id, is_command, is_reply, response_time, project_id, is_trial, is_paid):
    await db_log_message_stat(
        telegram_id=telegram_id,
        is_command=is_command,
        is_reply=is_reply,
        response_time=response_time,
        project_id=project_id,
        is_trial=is_trial,
        is_paid=is_paid
    ) 