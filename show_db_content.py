import asyncio
from database import database, User, Project
from sqlalchemy.sql import select

async def show_db():
    await database.connect()
    print('Users:')
    users = await database.fetch_all(select([User]))
    for user in users:
        print(dict(user))
    print('\nProjects:')
    projects = await database.fetch_all(select([Project]))
    for project in projects:
        print(dict(project))
    await database.disconnect()

if __name__ == "__main__":
    asyncio.run(show_db()) 