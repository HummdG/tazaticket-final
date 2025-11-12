# app/services/search_result_manager_v2.py
import json
import uuid
from ..langgraph.redis_manager import redis_manager  # use shared connection manager


class SearchResultManagerV2:
    def __init__(self):
        self.ttl = 86400  # 24 hours

    async def store_search_result(self, data: dict):
        """Store flattened search data and return a generated search_id"""
        redis_conn = await redis_manager.get_connection()
        search_id = str(uuid.uuid4())
        redis_key = f"search_result:{search_id}"
        await redis_conn.setex(redis_key, self.ttl, json.dumps(data))
        return search_id

    async def get_option(self, search_id: str, offer_number: int, option_number: int = None):
        """Retrieve an offer or specific option by its number."""
        redis_conn = await redis_manager.get_connection()
        redis_key = f"search_result:{search_id}"
        raw = await redis_conn.get(redis_key)
        if not raw:
            return {"status": "error", "message": "Search not found"}

        data = json.loads(raw)
        offers = data.get("flattened_struct", []) or data.get("flattened_structured_offers", [])
        if not offers:
            return {"status": "error", "message": "No offers found in stored search"}

        if offer_number < 1 or offer_number > len(offers):
            return {"status": "error", "message": "Invalid offer number"}

        offer = offers[offer_number - 1]

        # Entire offer requested
        if option_number is None:
            return {"status": "success", "flight_option": offer}

        # Specific option requested
        options = offer.get("options", [])
        if option_number < 1 or option_number > len(options):
            return {
                "status": "error",
                "message": f"Invalid option number for Offer {offer_number}. Available: {len(options)}"
            }

        selected_option = options[option_number - 1]
        return {
            "status": "success",
            "offer_number": offer_number,
            "option_number": option_number,
            "offer_id": offer.get("offer_id"),
            "option_id": selected_option.get("option_id"),
            "option": selected_option
        }


# Shared instance (consistent with your project pattern)
search_result_manager = SearchResultManagerV2()



# # app/services/search_result_manager_v2.py
# import json, uuid, redis.asyncio as redis


# class SearchResultManagerV2:
#     def __init__(self):
#         self.redis = redis.from_url("redis://localhost:6379")
#         self.ttl = 86400  # 24 hours

#     async def store_search_result(self, data: dict):
#         search_id = str(uuid.uuid4())
#         redis_key = f"search_result:{search_id}"
#         await self.redis.setex(redis_key, self.ttl, json.dumps(data))
#         return search_id


#     async def get_option(self, search_id: str, offer_number: int, option_number: int = None):
#         redis_key = f"search_result:{search_id}"
#         raw = await self.redis.get(redis_key)
#         if not raw:
#             return {"status": "error", "message": "Search not found"}

#         data = json.loads(raw)
#         offers = data.get("flattened_struct", []) or data.get("flattened_structured_offers", [])

#         if offer_number < 1 or offer_number > len(offers):
#             return {"status": "error", "message": "Invalid offer number"}

#         offer = offers[offer_number - 1]

#         # If user wants entire offer (no specific option)
#         if option_number is None:
#             return {"status": "success", "flight_option": offer}

#         options = offer.get("options", [])
#         if option_number < 1 or option_number > len(options):
#             return {
#                 "status": "error",
#                 "message": f"Invalid option number for Offer {offer_number}. Available: {len(options)}"
#             }

#         selected_option = options[option_number - 1]
#         return {
#             "status": "success",
#             "offer_number": offer_number,
#             "option_number": option_number,
#             "offer_id": offer.get("offer_id"),
#             "option_id": selected_option.get("option_id"),
#             "option": selected_option
#         }


#     # async def get_option(self, search_id: str, offer_number: int):
#     #     redis_key = f"search_result:{search_id}"
#     #     raw = await self.redis.get(redis_key)
#     #     if not raw:
#     #         return {"status": "error", "message": "Search not found"}

#     #     data = json.loads(raw)
#     #     offers = data.get("flattened_struct", [])
#     #     if offer_number < 1 or offer_number > len(offers):
#     #         return {"status": "error", "message": "Invalid offer number"}

#     #     return {"status": "success", "flight_option": offers[offer_number - 1]}

# search_result_manager = SearchResultManagerV2()