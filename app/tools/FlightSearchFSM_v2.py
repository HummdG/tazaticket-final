"""
FlightSearchStateMachine tool for managing flight search state and performing searches
Rewritten to be deterministic and to integrate with the agreed flatten/store/return flow.
"""

from langchain_core.tools import tool
from datetime import datetime

import json
from typing import Optional, Any
# import asyncio

# Existing project imports (kept as in original)
from ..statemachine.ConversationFlowSM import ConversationFlowSM
from ..payloads.OneWayFlightSearch import OneWayFlightSearch
from ..payloads.RoundTripFlightSearch import RoundTripFlightSearch
from .TravelportSearch import TravelportSearch
from ..services.search_result_manager_v2 import search_result_manager  # updated manager
from .airline_codes import (
    DEFAULT_PREFERRED_CARRIERS,
    get_airline_name,
    parse_carrier_preference
)
from .city_codes import resolve_phrase_to_airports
# from .travelport_utils import (
#     parse_date_range,
#     bulk_search_cheapest_async,
#     calculate_return_date,
#     is_bulk_search_query,
#     extract_return_duration
# )

# Redis manager (kept)
from ..langgraph.redis_manager import redis_manager
from ..langgraph.memory_manager import memory_manager

# New flattener (agreed)
from ..services.flight_flattener import flatten_travelport_response

# Helpers for state machine persistence (reused)
async def get_or_create_state_machine(thread_id: str) -> ConversationFlowSM:
    """Get existing state machine from Redis or create new one for thread"""
    redis_conn = await redis_manager.get_connection()
    state_key = f"state_machine:{thread_id}"
    sm_data = await redis_conn.get(state_key)
    if sm_data:
        sm_dict = json.loads(sm_data)
        sm = ConversationFlowSM.from_dict(sm_dict)
    else:
        sm = ConversationFlowSM()
        await _save_state_machine_to_redis(thread_id, sm)
    return sm

async def _save_state_machine_to_redis(thread_id: str, sm: ConversationFlowSM) -> None:
    """Save state machine to Redis with TTL"""
    redis_conn = await redis_manager.get_connection()
    state_key = f"state_machine:{thread_id}"
    sm_data = json.dumps(sm.to_dict())
    await redis_conn.setex(state_key, 86400, sm_data)

def resolve_city_to_iata(city_input: str) -> str:
    """Resolve natural language city to IATA code"""
    if not city_input:
        return city_input
    preferred_code, all_codes = resolve_phrase_to_airports(city_input)
    if preferred_code:
        return preferred_code
    return city_input.upper()

def fix_date_year(date_str: Optional[str]) -> Optional[str]:
    """Ensure date is in the future or sensible year"""
    if not date_str:
        return date_str
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        today = datetime.now().date()
        if date_obj < today:
            next_year_date = date_obj.replace(year=today.year + 1)
            return next_year_date.strftime('%Y-%m-%d')
        elif date_obj.year < today.year:
            current_year_date = date_obj.replace(year=today.year)
            if current_year_date < today:
                next_year_date = date_obj.replace(year=today.year + 1)
                return next_year_date.strftime('%Y-%m-%d')
            else:
                return current_year_date.strftime('%Y-%m-%d')
        return date_str
    except Exception:
        return date_str

def format_duration(minutes: int) -> str:
    if not minutes:
        return "Unknown"
    hours = minutes // 60
    mins = minutes % 60
    if hours and mins:
        return f"{hours}h {mins}m"
    elif hours:
        return f"{hours}h"
    else:
        return f"{mins}m"

def format_stops(stops: int) -> str:
    if stops == 0:
        return "non-stop"
    elif stops == 1:
        return "1 stop"
    else:
        return f"{stops} stops"

def format_baggage_summary(baggage: dict) -> str:
    parts = []
    carry_on = "✓" if baggage.get("carry_on_included") else "✗"
    carry_text = baggage.get("carry_on_text", "")
    if carry_text:
        parts.append(f"carry-on {carry_on} ({carry_text})")
    else:
        parts.append(f"carry-on {carry_on}")
    checked = "✓" if baggage.get("checked_bag_included") else "✗"
    parts.append(f"checked {checked}")
    if baggage.get("validating_airline"):
        airline_code = baggage['validating_airline']
        airline_name = get_airline_name(airline_code)
        parts.append(f"Validating airline: {airline_name}")
    if baggage.get("penalties_change"):
        parts.append(f"Change: {baggage['penalties_change']}")
    if baggage.get("penalties_cancel"):
        parts.append(f"Cancel: {baggage['penalties_cancel']}")
    return " | ".join(parts)

def format_layovers(itinerary: dict) -> str:
    lays = (itinerary or {}).get("layovers") or []
    if not lays:
        return ""
    parts = [f"{l.get('airport_code') or l.get('city')} ({l.get('duration')})" for l in lays]
    return "   Layover: " + ", ".join(parts) + "\n"


@tool("FlightSearchStateMachine")
async def FlightSearchStateMachine(
    origin: Optional[str] = None,
    destination: Optional[str] = None,
    departure_date: Optional[str] = None,
    return_date: Optional[str] = None,
    number_of_passengers: int = 1,
    type_of_trip: Optional[str] = None,
    user_input_text: Optional[str] = "",
    thread_id: str = "default",
    mode_of_conversation: Optional[str] = None,
    detected_language: str = "en",
) -> Any:
    """
    Deterministic FlightSearchStateMachine integrated with TravelportSearch and search_result_manager_v2.
    Behavior:
      - Update ConversationFlowSM variables
      - When state == complete -> perform search deterministically:
          1. Build OneWay/RoundTrip payload using existing payload classes
          2. Call TravelportSearch.ainvoke({"payload": payload, "trip_type": ...})
          3. Normalize raw response
          4. Flatten via flatten_travelport_response (text + structured_offers)
          5. Store via search_result_manager.store_search_result(payload_with_meta)
          6. Reset FSM and return human-friendly summary + search_id
    """
    # --------------- update state machine with provided values --------------
    sm = await get_or_create_state_machine(thread_id)

    # Set conversation mode if provided
    if mode_of_conversation:
        sm.set_variable('mode_of_conversation', mode_of_conversation)
    if detected_language:
        sm.set_variable('detected_language', detected_language)

    # Parse carrier preferences from free text if present
    preferred_carriers = parse_carrier_preference(user_input_text) if user_input_text else DEFAULT_PREFERRED_CARRIERS

    # Resolve and set origin/destination/dates/passengers/type
    if origin:
        sm.set_variable('origin', resolve_city_to_iata(origin))
    if destination:
        sm.set_variable('destination', resolve_city_to_iata(destination))
    if departure_date:
        sm.set_variable('departure_date', fix_date_year(departure_date))
    if return_date:
        sm.set_variable('return_date', fix_date_year(return_date))
    if number_of_passengers:
        sm.set_variable('number_of_passengers', number_of_passengers)
    if type_of_trip:
        normalized = type_of_trip.lower().strip()
        if normalized in ['oneway', 'one-way', 'one way']:
            normalized = 'one-way'
        elif normalized in ['roundtrip', 'round-trip', 'round trip', 'return']:
            normalized = 'round-trip'
        sm.set_variable('type_of_trip', normalized)

    # Persist updated SM
    await _save_state_machine_to_redis(thread_id, sm)

    # If state is not complete -> prompt missing
    if sm.get_state() != "complete":
        missing = sm.get_missing_variables()
        if missing:
            return (
                f"🧭 Flight search setup in progress.\n"
                f"Missing details: {', '.join(missing)}.\n"
                f"Please provide these to continue."
            )
        # If all required fields present but state not marked complete, mark it and continue
        required = ["origin", "destination", "departure_date", "number_of_passengers", "type_of_trip"]
        if all(getattr(sm, field, None) for field in required):
            sm.set_state("complete")
            await _save_state_machine_to_redis(thread_id, sm)
            return "✅ All flight search parameters have been set successfully. Proceeding to search flights..."


    # --------------- state is complete: perform deterministic search --------------
    # # Bulk detection first (preserve existing BulkFlightSearch behavior)
    # if is_bulk_search_query(user_input_text or ""):
    #     # Delegate to BulkFlightSearch tool (keeps original logic)
    #     try:
    #         from .FlightSearchStateMachine import BulkFlightSearch  # circular but original had it
    #         bulk_args = dict(
    #             origin=sm.origin,
    #             destination=sm.destination,
    #             user_input_text=user_input_text,
    #             number_of_passengers=sm.number_of_passengers,
    #             thread_id=thread_id,
    #             mode_of_conversation=sm.mode_of_conversation,
    #             detected_language=sm.detected_language,
    #             departure_date=sm.departure_date,
    #         )
    #         result = await BulkFlightSearch.ainvoke(**bulk_args)
    #         # Attempt to store bulk result if it returned a raw payload we can persist (best-effort)
    #         try:
    #             if isinstance(result, dict):
    #                 store_payload = {
    #                     "wa_id": None,
    #                     "thread_id": thread_id,
    #                     "origin": sm.origin,
    #                     "destination": sm.destination,
    #                     "departure_date": sm.departure_date,
    #                     "trip_type": "bulk-search",
    #                     "passengers": sm.number_of_passengers,
    #                     "raw_response": {"bulk_result": result},
    #                     "flattened_summary_text": str(result),
    #                     "flattened_structured_offers": []
    #                 }
    #                 await search_result_manager.store_search_result(store_payload)
    #         except Exception:
    #             pass
    #         await _save_state_machine_to_redis(thread_id, ConversationFlowSM())  # reset FSM
    #         return result
    #     except Exception as e:
    #         return f"⚠️ Bulk search delegation failed: {e}"

    # Build payload based on trip type using your existing payload classes
    try:
        if sm.type_of_trip == "round-trip" and sm.return_date:
            payload = RoundTripFlightSearch(
                origin=sm.origin,
                destination=sm.destination,
                departure_date=sm.departure_date,
                return_date=sm.return_date,
                number_of_passengers=sm.number_of_passengers,
                carriers=parse_carrier_preference(user_input_text or "")
            )
            trip_label = "round-trip"
        else:
            payload = OneWayFlightSearch(
                origin=sm.origin,
                destination=sm.destination,
                departure_date=sm.departure_date,
                number_of_passengers=sm.number_of_passengers,
                carriers=parse_carrier_preference(user_input_text or "")
            )
            trip_label = "one-way"
    except Exception as e:
        return f"⚠️ Failed to construct search payload: {e}"

    # Clear previous quick-cache keys for thread to ensure fresh search
    try:
        redis_conn = await redis_manager.get_connection()
        await redis_conn.delete(f"thread_latest_search:{thread_id}")
        await redis_conn.delete(f"user_search_list:{thread_id}")
    except Exception:
        pass

    # Call TravelportSearch with standardized ainvoke signature
    try:
        # many of your existing calls used TravelportSearch.ainvoke({"payload": payload, "trip_type": trip_label})
        result = await TravelportSearch.ainvoke({"payload": payload, "trip_type": trip_label})
    except Exception as e:
        return f"⚠️ TravelportSearch call failed: {e}"

    # Normalize result -> expect dict with 'ok' and 'raw' OR direct Catalog response
    raw_response = None
    # if isinstance(result, dict) and result.get("ok") and result.get("raw"):
    #     raw_response = result.get("raw")
    if isinstance(result, dict): # and "CatalogProductOfferingsResponse" in result:
        raw_response = result
    # else:
    #     raw_response = result

    # If no valid raw_response -> return error
    if not raw_response:
        return f"⚠️ Search returned no usable response: {result}"

    # Flatten the raw response into text + structured offers
    try:
        text_summary, structured_offers = flatten_travelport_response(raw_response)
    except Exception as e:
        return f"⚠️ Flattening failed: {e}"

    # Prepare payload for storage
    store_payload = {
        "wa_id": None,  # FSM may not have wa_id; agent can replace if needed
        "thread_id": thread_id,
        "origin": sm.origin,
        "destination": sm.destination,
        "departure_date": sm.departure_date,
        "return_date": sm.return_date,
        "trip_type": trip_label,
        "passengers": sm.number_of_passengers,
        "raw_response": raw_response,
        "flattened_summary_text": text_summary,
        "flattened_structured_offers": structured_offers,
        "detected_language": detected_language
    }

    # Store and get search_id (await deterministically)
    try:
        search_id = await search_result_manager.store_search_result(store_payload)
    except Exception as e:
        return f"⚠️ Storing search results failed: {e}"
    # Store latest search_id for this thread (so agent can retrieve later)

    await memory_manager.set_latest_search_id(thread_id, search_id)
    # Reset FSM state
    await _save_state_machine_to_redis(thread_id, ConversationFlowSM())

    # Return human-friendly summary and search_id (agent will display summary to user)
    return {
        "status": "success",
        "message": "✅ All flight details collected and search completed.",
        "summary": text_summary,
        "search_id": search_id,
        "thread_id": thread_id
    }



# BulkFlightSearch remains in original codebase; we don't modify it here.
# The above function delegates to BulkFlightSearch if needed and attempts to store its result.
