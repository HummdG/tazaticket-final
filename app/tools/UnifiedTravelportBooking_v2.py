import os
import json
import aiohttp
from langchain_core.tools import tool
from ..services.search_result_manager_v2 import search_result_manager
from ..payloads.BuildFromProductsPayload import build_from_products_payload
from ..payloads.BuildTravelerPayload import build_traveler_payload
from app.tools.TravelportSearch import get_access_token


@tool("UnifiedTravelportBooking_v2")
async def UnifiedTravelportBooking_v2(
    wa_id: str,
    search_id: str,
    offer_number: int,
    option_number: int,
    traveler_details: list
):
    """
    Executes the full booking flow:
      1. Fetch selected offer/option from Redis.
      2. Build AddOffer and Traveler payloads.
      3. Initiate Workbench session.
      4. Add Offer → Add Traveler(s) → Commit Reservation.
      5. Return final booking confirmation (PNR, summary, etc.)
    """

    # --- 1. Fetch Selected Offer/Option ---
    selected = await search_result_manager.get_option(
        search_id=search_id,
        offer_number=offer_number,
        option_number=option_number
    )

    if selected.get("status") != "success":
        return {"status": "error", "message": "Invalid offer or option selection."}

    # selected_option = selected.get("option", {})
    # flights = selected_option.get("flights", [])
    # brand = selected_option.get("brand", {})
    # product = selected_option.get("product", {})

    # # --- 2. Build Payloads ---
    # add_offer_payload = build_from_products_payload(
    #     selected_offer={
    #         "itinerary_summary": {"segments": flights},
    #         "brandTier": brand.get("tier", 1)
    #     },
    #     passengers=len(traveler_details),
    #     passenger_type="ADT"
    # )

    selected_option = selected.get("option", {})
    offer_ref = selected_option.get("offer_ref")
    product_refs = selected_option.get("product_ref_list", [])

    if not offer_ref or not product_refs:
        return {
            "status": "error",
            "message": "Selected option is missing offer_ref or product_refs."
        }

    add_offer_payload = build_from_products_payload(
        offer_ref=offer_ref,
        product_refs=product_refs,
        passengers=len(traveler_details),
        passenger_type="ADT"
    )





    traveler_payload = build_traveler_payload(travelers=traveler_details)



    # --- 3. Setup Travelport API Config ---
    
    BASE_URL = "https://api.pp.travelport.com/11/air/book"
    token = await get_access_token()
    
    HEADERS = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "XAUTH_TRAVELPORT_ACCESSGROUP": os.getenv("TRAVELPORT_ACCESS_GROUP"),
        # "Authorization": f"Bearer {os.getenv('TRAVELPORT_TOKEN')}",
        "Authorization": f"Bearer {token}",
        "Content-Version": "11"
    }

    async with aiohttp.ClientSession() as session:
        # --- 4. Initiate Workbench Session ---
        init_url = f"{BASE_URL}/session/reservationworkbench"
        init_payload = {"@type": "ReservationID", "ReservationID": {}}

        async with session.post(init_url, headers=HEADERS, json=init_payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                return {
                    "status": "error",
                    "message": f"Travelport returned {resp.status}",
                    "response": text
                }

            init_data = await resp.json()
            reservation_id = (
                init_data.get("ReservationResponse", {})
                .get("Reservation", {})
                .get("Identifier", {})
                .get("value")
            )

        if not reservation_id:
            return {"status": "error", "message": "Failed to initiate reservation."}

        # --- 5. Add Offer ---
        add_offer_url = f"{BASE_URL}/airoffer/reservationworkbench/{reservation_id}/offers/buildfromproducts"
        HEADERS["trackingId"] = reservation_id

        async with session.post(add_offer_url, headers=HEADERS, json=add_offer_payload) as resp:
            add_offer_response = await resp.json()

        if "error" in add_offer_response or "Error" in json.dumps(add_offer_response):
            return {"status": "error", "message": "Failed to add offer.", "response": add_offer_response}

        # --- 6. Add Travelers ---
        add_traveler_url = f"{BASE_URL}/traveler/reservationworkbench/{reservation_id}/travelers"

        for t in traveler_payload:
            async with session.post(add_traveler_url, headers=HEADERS, json=t) as resp:
                traveler_response = await resp.json()
                if "error" in traveler_response or "Error" in json.dumps(traveler_response):
                    return {"status": "error", "message": "Traveler addition failed.", "response": traveler_response}

        # --- 7. Commit Reservation ---
        commit_url = f"{BASE_URL.replace('book', 'reservation')}/reservations/{reservation_id}"
        commit_payload = {"@type": "ReservationQueryCommitReservation"}

        async with session.post(commit_url, headers=HEADERS, json=commit_payload) as resp:
            commit_data = await resp.json()

        pnr = (
            commit_data.get("ReservationResponse", {})
            .get("Receipt", {})
            .get("Confirmation", {})
            .get("Locator", {})
            .get("value")
        )

        if not pnr:
            return {"status": "error", "message": "Commit failed, PNR not found.", "response": commit_data}

    # --- 8. Return Final Confirmation ---
    return {
        "status": "success",
        "pnr": pnr,
        "reservation_id": reservation_id,
        "waid" : wa_id,
        "summary": {
            "airline": flights[0].get("carrier"),
            "route": f"{flights[0].get('Departure', {}).get('location')} → {flights[-1].get('Arrival', {}).get('location')}",
            "fare": selected_option.get("price"),
            "currency": selected_option.get("currency")
        }
    }
