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


@tool("search_result_get_option")
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


