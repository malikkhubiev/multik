import asyncio
import httpx
from database import database, Project
from sqlalchemy.sql import select

async def check_webhooks():
    await database.connect()
    projects = await database.fetch_all(select(Project))
    tokens = set([p['token'] for p in projects])
    print(f"Найдено токенов: {len(tokens)}")
    for token in tokens:
        url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url)
                data = resp.json()
                print(f"\nToken: {token}\nWebhookInfo: {data}")
        except Exception as e:
            print(f"Ошибка для токена {token}: {e}")
    await database.disconnect()

if __name__ == "__main__":
    asyncio.run(check_webhooks()) 