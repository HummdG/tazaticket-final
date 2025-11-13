# app/services/search_result_manager_v2.py
import json
import uuid
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from ..langgraph.redis_manager import redis_manager  # use shared connection manager

@dataclass
class FlightOption:
    """Represents a single flight option from search results"""
    id: str
    departure: str
    arrival: str
    departure_time: str
    arrival_time: str
    duration: str
    airline: str
    flight_number: str
    aircraft: str
    price: float
    currency: str
    cabin_class: str
    stops: int
    baggage_info: Dict[str, Any]
    penalties: Dict[str, Any]
    raw_data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SearchResult:
    """Represents a complete search result"""
    search_id: str
    wa_id: str
    thread_id: str
    origin: str
    destination: str
    search_date: str
    trip_type: str
    passengers: int
    flight_options: List[FlightOption]
    search_timestamp: str
    expires_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "search_id": self.search_id,
            "wa_id": self.wa_id,
            "thread_id": self.thread_id,
            "origin": self.origin,
            "destination": self.destination,
            "search_date": self.search_date,
            "trip_type": self.trip_type,
            "passengers": self.passengers,
            "flight_options": [option.to_dict() for option in self.flight_options],
            "search_timestamp": self.search_timestamp,
            "expires_at": self.expires_at
        }



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

    async def get_search_result(self, search_id: str) -> Optional[SearchResult]:
        """Retrieve search result by ID"""
        try:
            redis_conn = await self.get_connection()
            result_key = f"search_result:{search_id}"

            result_data = await redis_conn.get(result_key)
            if not result_data:
                return None

            data = json.loads(result_data)

            # Convert flight options back to objects
            flight_options = [
                FlightOption(**option_data)
                for option_data in data.get("flight_options", [])
            ]

            return SearchResult(
                search_id=data["search_id"],
                wa_id=data["wa_id"],
                thread_id=data["thread_id"],
                origin=data["origin"],
                destination=data["destination"],
                search_date=data["search_date"],
                trip_type=data["trip_type"],
                passengers=data["passengers"],
                flight_options=flight_options,
                search_timestamp=data["search_timestamp"],
                expires_at=data["expires_at"]
            )

        except Exception as e:
            print(f"[SearchResultManager] Error retrieving search result {search_id}: {e}")
            return None



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