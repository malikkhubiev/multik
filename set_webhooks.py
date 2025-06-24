import asyncio
import httpx
from database import database, Project
from config import SERVER_URL
from sqlalchemy.sql import select

async def set_webhooks():
    await database.connect()
    projects = await database.fetch_all(select([Project]))
    async with httpx.AsyncClient() as client:
        for project in projects:
            token = project["token"]
            project_id = project["id"]
            webhook_url = f"{SERVER_URL}/webhook/{project_id}"
            url = f"https://api.telegram.org/bot{token}/setWebhook"
            try:
                resp = await client.post(url, params={"url": webhook_url})
                data = resp.json()
                if data.get("ok"):
                    print(f"[OK] Webhook set for project {project_id}: {webhook_url}")
                else:
                    print(f"[FAIL] Project {project_id}: {data}")
            except Exception as e:
                print(f"[ERROR] Project {project_id}: {e}")
    await database.disconnect()

if __name__ == "__main__":
    asyncio.run(set_webhooks()) 