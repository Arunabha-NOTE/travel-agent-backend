import asyncio
import uuid
from app.agents.langgraph_agent import run_langgraph_agent
from app.db.session import async_session_maker


async def test_stream():
    chat_id = uuid.uuid4()
    user_message = "plan a trip to delhi"
    history = []

    async with async_session_maker() as db:
        print(f"--- Testing LangGraph Stream for message: {user_message} ---")
        async for token in run_langgraph_agent(chat_id, user_message, history, db):
            # We don't care about the tokens, we want to look at the logs triggered internally
            pass


if __name__ == "__main__":
    asyncio.run(test_stream())
