from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router

bot_dispatchers = {}

async def get_or_create_dispatcher(token: str):
    if token in bot_dispatchers:
        return bot_dispatchers[token]
    bot = Bot(token=token)
    storage = MemoryStorage()
    router = Router()
    dp = Dispatcher(storage=storage)
    dp.include_router(router)
    bot_dispatchers[token] = (dp, bot, router)
    return dp, bot, router 