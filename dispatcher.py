from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router
import logging

bot_dispatchers = {}

async def get_or_create_dispatcher(token: str):
    logging.info(f"[DISPATCHER] get_or_create_dispatcher called with token: {token}")
    if token in bot_dispatchers:
        logging.info(f"[DISPATCHER] Dispatcher for token {token} already exists")
        return bot_dispatchers[token]
    bot = Bot(token=token)
    storage = MemoryStorage()
    router = Router()
    dp = Dispatcher(storage=storage)
    dp.include_router(router)
    bot_dispatchers[token] = (dp, bot, router)
    logging.info(f"[DISPATCHER] Dispatcher for token {token} created successfully")
    return dp, bot, router 