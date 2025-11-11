# app/tools/FlightSearchFSM_v2.py
from langchain_core.tools import tool
from app.services.search_result_manager_v2 import search_result_manager
from app.services.flight_flattener import flatten_travelport_response
from app.tools.TravelportSearch import TravelportSearch

@tool("FlightSearchFSM_v2")
async def FlightSearchFSM_v2(
    origin: str = None,
    destination: str = None,
    departure_date: str = None,
    return_date: str = None,
    passengers: int = 1,
    trip_type: str = "one-way",
    wa_id: str = "",
    thread_id: str = "",
):
    """
    Deterministic FSM for flight search → flatten → store → return summary.
    """
    if not all([origin, destination, departure_date]):
        return "Please provide all flight details (origin, destination, date)."

    # Step 1. Call Travelport Search
    response = await TravelportSearch.ainvoke({
        "origin": origin,
        "destination": destination,
        "departure_date": departure_date,
        "return_date": return_date,
        "number_of_passengers": passengers,
        "trip_type": trip_type
    })

    if not response.get("ok"):
        return f"Search failed: {response.get('error')}"

    raw_response = response.get("raw", {})

    # Step 2. Flatten response
    flattened_string, flattened_struct = flatten_travelport_response(raw_response)

    # Step 3. Store in Redis
    payload = {
        "wa_id": wa_id,
        "thread_id": thread_id,
        "origin": origin,
        "destination": destination,
        "departure_date": departure_date,
        "return_date": return_date,
        "trip_type": trip_type,
        "passengers": passengers,
        "raw_response": raw_response,
        "flattened_summary": flattened_string,
        "flattened_struct": flattened_struct,  # Include structured data
    }
    search_id = await search_result_manager.store_search_result(payload)

    # Step 4. Return formatted response to agent
    return {
        "status": "success",
        "search_id": search_id,
        "summary": flattened_string
    }