# app/tools/SearchResultTool.py
"""
SearchResultTool
----------------
Expose deterministic search result lookups to LangGraph as a tool.

Usage (from LLM / LangGraph tool call):
    - name: "SearchResultTool.get_option"
    - args: {"search_id": "<uuid>", "offer_number": 3, "option_number": 2}

Returns:
    {
      "status": "success",
      "offer_number": 3,
      "option_number": 2 or None,
      "offer_id": "o3",
      "option_id": "uuid-of-option" or None,
      "option": { ... }  # full option dict when option_number provided
      "offer": { ... }   # full offer dict when option_number omitted
    }
"""

from langchain_core.tools import tool
from typing import Optional, Dict, Any
import json

# import your search_result_manager instance
from app.services.search_result_manager_v2 import search_result_manager


@tool("SearchResultTool.get_option")
async def search_result_get_option(
    search_id: str,
    offer_number: int,
    option_number: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Tool wrapper to fetch an offer or a specific option inside an offer.
    - If option_number is None -> returns the entire offer object.
    - If option_number is provided -> returns the single option inside the offer.
    """
    # Basic validation (fail fast)
    if not search_id:
        return {"status": "error", "message": "search_id is required"}
    if not isinstance(offer_number, int) or offer_number < 1:
        return {"status": "error", "message": "offer_number must be a positive integer"}

    # Call service
    try:
        res = await search_result_manager.get_option(search_id, offer_number, option_number)
    except TypeError:
        # In case your search_result_manager.get_option signature is older and expects only two args,
        # call backward-compatible path by calling the two-arg version and drilling down here.
        raw_search = await search_result_manager.get_search(search_id)
        if not raw_search:
            return {"status": "error", "message": "search_id not found"}
        offers = raw_search.get("flattened_structured_offers", raw_search.get("flattened_struct", []))
        if offer_number < 1 or offer_number > len(offers):
            return {"status": "error", "message": "Invalid offer_number"}
        offer = offers[offer_number - 1]
        if option_number is None:
            return {"status": "success", "offer": offer}
        options = offer.get("options", []) or offer.get("pbo_list", [])  # try both keys
        if option_number < 1 or option_number > len(options):
            return {"status": "error", "message": "Invalid option_number for this offer"}
        return {
            "status": "success",
            "offer_number": offer_number,
            "option_number": option_number,
            "offer_id": offer.get("offer_id"),
            "option_id": options[option_number - 1].get("option_id"),
            "option": options[option_number - 1]
        }

    # Return what the manager returned
    return res




# """
# Search Result Tool - Enhanced tool for managing and retrieving search results in conversations
# """

# from langchain_core.tools import tool
# from typing import Optional, Dict, Any, List
# import json
# from ..services.search_result_manager import search_result_manager, SearchResult, FlightOption


# @tool("SearchResultManager")
# async def SearchResultManager(
#     action: str = "list",
#     search_id: Optional[str] = None,
#     thread_id: Optional[str] = None,
#     wa_id: Optional[str] = None,
#     option_number: Optional[int] = None,
#     user_input_text: str = "",
#     thread_id_param: str = "default",
#     mode_of_conversation: Optional[str] = None,
#     detected_language: str = "en",
# ):
#     """
#     Enhanced search result management tool that provides seamless conversational flow with stored search results.

#     Actions:
#     - list: List user's search history
#     - latest: Get latest search results for thread
#     - details: Get detailed information about a specific search
#     - option: Get details of a specific flight option
#     - compare: Compare multiple flight options

#     This tool integrates with the SearchResultManager to provide persistent,
#     user-specific search result storage and retrieval.
#     """

#     try:
#         if action == "list" and wa_id:
#             # Get user's search history
#             search_ids = await search_result_manager.get_user_search_history(wa_id)
#             if not search_ids:
#                 return "📭 No search history found for this user."

#             response = "🔍 Your Search History:\n\n"
#             for i, sid in enumerate(search_ids[:5], 1):  # Show last 5 searches
#                 search_result = await search_result_manager.get_search_result(sid)
#                 if search_result:
#                     response += (
#                         f"{i}. {search_result.origin} → {search_result.destination} "
#                         f"({search_result.search_date}) - {len(search_result.flight_options)} options\n"
#                     )

#             response += "\n💡 Use 'get latest' to see the most recent search results!"
#             return response

#         elif action == "latest" and thread_id:
#             # Get latest search for thread
#             latest_search_id = await search_result_manager.get_latest_search_for_thread(thread_id)
#             if not latest_search_id:
#                 return "❌ No recent search found for this conversation. Please perform a new search first."

#             search_result = await search_result_manager.get_search_result(latest_search_id)
#             if not search_result:
#                 return "❌ Search results not found. Please try searching again."

#             return search_result_manager.format_search_results_for_display(search_result)

#         elif action == "details" and search_id:
#             # Get detailed information about a specific search
#             search_result = await search_result_manager.get_search_result(search_id)
#             if not search_result:
#                 return f"❌ Search result {search_id} not found."

#             response = "🔍 Search Details:\n\n"
#             response += f"📅 Date: {search_result.search_date}\n"
#             response += f"🛣️ Route: {search_result.origin} → {search_result.destination}\n"
#             response += f"👥 Passengers: {search_result.passengers}\n"
#             response += f"✈️ Trip Type: {search_result.trip_type}\n"
#             response += f"📊 Total Options: {len(search_result.flight_options)}\n\n"

#             # Show top 3 options
#             top_options = sorted(search_result.flight_options, key=lambda x: x.price)[:3]
#             response += "💰 Top 3 Cheapest Options:\n"

#             for i, option in enumerate(top_options, 1):
#                 response += f"\n{i}. {option.price} {option.currency} - {option.airline} {option.flight_number}"
#                 response += f"\n   {option.departure_time} - {option.arrival_time} ({option.duration})"

#             return response

#         elif action == "option" and search_id and option_number is not None:
#             # Get details of a specific flight option
#             search_result = await search_result_manager.get_search_result(search_id)
#             if not search_result:
#                 return f"❌ Search result {search_id} not found."

#             if option_number < 1 or option_number > len(search_result.flight_options):
#                 return f"❌ Please choose an option number between 1 and {len(search_result.flight_options)}."

#             option = search_result.flight_options[option_number - 1]

#             response = "🎫 Flight Option Details:\n\n"
#             response += f"🛣️ Route: {option.departure} → {option.arrival}\n"
#             response += f"🕐 Departure: {option.departure_time}\n"
#             response += f"🕐 Arrival: {option.arrival_time}\n"
#             response += f"⏱️ Duration: {option.duration}\n"
#             response += f"🏢 Airline: {option.airline}\n"
#             response += f"✈️ Flight: {option.flight_number}\n"
#             response += f"🛩️ Aircraft: {option.aircraft}\n"
#             response += f"💰 Price: {option.price} {option.currency}\n"
#             response += f"💺 Class: {option.cabin_class}\n"
#             response += f"🛑 Stops: {option.stops}\n\n"

#             response += "🧳 Baggage Information:\n"
#             response += f"• Carry-on: {option.baggage_info.get('carry_on_text', 'Check with airline')}\n"
#             response += f"• Checked bag: {option.baggage_info.get('checked_bag_text', 'Check with airline')}\n\n"

#             response += "📋 Change & Cancellation:\n"
#             response += f"• Changes: {option.penalties.get('change', 'Free')}\n"
#             response += f"• Cancellation: {option.penalties.get('cancel', 'Free')}\n\n"

#             response += "💡 To book this flight, please provide your payment details and passenger information."

#             return response

#         elif action == "compare" and search_id:
#             # Compare multiple flight options
#             search_result = await search_result_manager.get_search_result(search_id)
#             if not search_result:
#                 return f"❌ Search result {search_id} not found."

#             if len(search_result.flight_options) < 2:
#                 return "❌ Need at least 2 flight options to compare."

#             # Get top 3 options for comparison
#             top_options = sorted(search_result.flight_options, key=lambda x: x.price)[:3]

#             response = "⚖️ Flight Comparison:\n\n"

#             for i, option in enumerate(top_options, 1):
#                 response += f"**Option {i}:**\n"
#                 response += search_result_manager.format_flight_option_for_display(option)
#                 response += "\n" + "="*50 + "\n"

#             return response

#         else:
#             return (
#                 "❌ Invalid action or missing parameters.\n\n"
#                 "Available actions:\n"
#                 "• 'list' - Show search history (requires wa_id)\n"
#                 "• 'latest' - Show latest search results (requires thread_id)\n"
#                 "• 'details' - Show search details (requires search_id)\n"
#                 "• 'option' - Show specific flight option (requires search_id and option_number)\n"
#                 "• 'compare' - Compare flight options (requires search_id)"
#             )

#     except Exception as e:
#         print(f"[SearchResultManager] Error in SearchResultManager tool: {e}")
#         return f"❌ Error retrieving search results: {str(e)}"


# @tool("StoreSearchResult")
# async def StoreSearchResult(
#     wa_id: str,
#     thread_id: str,
#     search_data: Optional[Dict[str, Any]],
#     user_input_text: str = "",
#     thread_id_param: str = "default",
#     mode_of_conversation: Optional[str] = None,
#     detected_language: str = "en",
# ):
#     """
#     Store Travelport search results for later retrieval in conversations.

#     This tool should be called after receiving Travelport API results to ensure
#     they're stored locally and can be referenced throughout the conversation.
#     """

#     try:
#         # Store the search result
#         search_id = await search_result_manager.store_search_result(wa_id, thread_id, search_data)

#         # Get the stored result for confirmation
#         search_result = await search_result_manager.get_search_result(search_id)

#         if not search_result:
#             return "❌ Failed to store search results."

#         # Format response for user
#         response = "✅ Search Results Stored Successfully!\n\n"
#         response += f"🔍 Found {len(search_result.flight_options)} flight options\n"
#         response += f"💰 Cheapest: {search_result.flight_options[0].price} {search_result.flight_options[0].currency}\n"
#         response += f"📅 Search ID: {search_id}\n\n"

#         response += "💡 You can now:\n"
#         response += "• Ask me to 'show latest results' anytime\n"
#         response += "• Request 'option 1', 'option 2', etc. for details\n"
#         response += "• Ask to 'compare options' for side-by-side view\n"
#         response += "• View your 'search history'"

#         return response

#     except Exception as e:
#         print(f"[StoreSearchResult] Error storing search result: {e}")
#         return f"❌ Error storing search results: {str(e)}"