import asyncio
from sqlalchemy import text
from app.db.session import async_session_maker


async def update():
    async with async_session_maker() as db:
        await db.execute(text("UPDATE chat_rooms SET is_public = TRUE"))
        await db.commit()
        print("Updated existing chats to public")


if __name__ == "__main__":
    asyncio.run(update())
