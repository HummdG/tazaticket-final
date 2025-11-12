from langchain_core.tools import tool
from app.langgraph.memory_manager import memory_manager

@tool("SearchMemoryTool.get_latest_search_id")
async def search_memory_get_latest_search_id(thread_id: str):
    """
    Returns the latest search_id for the given user/thread.
    """
    # search_id = await get_latest_search_id(thread_id)
    search_id = await memory_manager.get_latest_search_id(thread_id)

    if not search_id:
        return {"status": "error", "message": "No active search found for this thread."}
    return {"status": "success", "search_id": search_id.decode() if isinstance(search_id, bytes) else search_id}
