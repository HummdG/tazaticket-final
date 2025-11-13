from app.langgraph.memory_manager import memory_manager
import asyncio

async def test_latest_search():
    print(await memory_manager.get_latest_search_id("923035031692"))

asyncio.run(test_latest_search())
