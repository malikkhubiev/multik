from aiogram import Bot, Dispatcher
from aiogram.contrib.fsm_storage.memory import MemoryStorage

bot_dispatchers = {}

async def get_or_create_dispatcher(token: str):
    if token in bot_dispatchers:
        return bot_dispatchers[token]
    bot = Bot(token=token)
    storage = MemoryStorage()
    dp = Dispatcher(bot, storage=storage)
    bot_dispatchers[token] = dp
    return dp 