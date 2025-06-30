import asyncio
import httpx
from database import database, Project
from sqlalchemy.sql import select
import logging

async def check_webhooks():
    logging.info("[CHECK_WEBHOOKS] check_webhooks started")
    await database.connect()
    projects = await database.fetch_all(select(Project))
    tokens = set([p['token'] for p in projects])
    logging.info(f"[CHECK_WEBHOOKS] Found {len(tokens)} tokens")
    for token in tokens:
        url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url)
                data = resp.json()
                logging.info(f"[CHECK_WEBHOOKS] Token: {token}, WebhookInfo: {data}")
        except Exception as e:
            logging.error(f"[CHECK_WEBHOOKS] Ошибка для токена {token}: {e}")
    await database.disconnect()
    logging.info("[CHECK_WEBHOOKS] check_webhooks finished")

if __name__ == "__main__":
    asyncio.run(check_webhooks()) 