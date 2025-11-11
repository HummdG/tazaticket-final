# app/services/search_result_manager_v2.py
import json, uuid, redis.asyncio as redis

class SearchResultManagerV2:
    def __init__(self):
        self.redis = redis.from_url("redis://localhost:6379")
        self.ttl = 86400  # 24 hours

    async def store_search_result(self, data: dict):
        search_id = str(uuid.uuid4())
        redis_key = f"search_result:{search_id}"
        await self.redis.setex(redis_key, self.ttl, json.dumps(data))
        return search_id

    async def get_option(self, search_id: str, offer_number: int):
        redis_key = f"search_result:{search_id}"
        raw = await self.redis.get(redis_key)
        if not raw:
            return {"status": "error", "message": "Search not found"}

        data = json.loads(raw)
        offers = data.get("flattened_struct", [])
        if offer_number < 1 or offer_number > len(offers):
            return {"status": "error", "message": "Invalid offer number"}

        return {"status": "success", "flight_option": offers[offer_number - 1]}

search_result_manager = SearchResultManagerV2()