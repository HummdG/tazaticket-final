from langchain.tools import tool
from ..payloads.BuildFromProductsPayload import build_from_products_payload
from ..services.search_result_manager import search_result_manager
from .TravelportReservation import (
    TravelportInitiateReservationWorkbench,
    TravelportAddOfferToReservation,
    TravelportAddTravelerToReservation,
    TravelportCommitReservation
)


@tool("UnifiedTravelportBooking")
async def unified_travelport_booking(wa_id: str, selected_option_id: str, traveler_details: dict):
    """
    Handle full workflow: initiate reservation → add offer → add traveler(s) → commit reservation (PNR).
    """
    # 1. fetch search result using wa_id
    search = await search_result_manager.get_latest_for_user(wa_id)
    if not search:
        return {"status": "error", "message": f"No search results found for user {wa_id}"}
    
    # Find the selected option among the flight options
    selected_flight_option = None
    for option in search.flight_options:
        if option.id == selected_option_id:
            selected_flight_option = option
            break
    
    if not selected_flight_option:
        return {"status": "error", "message": f"Flight option {selected_option_id} not found"}
    
    # Get the raw data to access the resolved offering with itinerary summary
    raw_data = selected_flight_option.raw_data
    brand_offering = raw_data.get("brand_offering", {})
    
    # Check if the resolved offering has itinerary summary
    if "itinerary_summary" not in brand_offering:
        # If not in the brand offering, check if it's in the offering
        offering = raw_data.get("offering", {})
        for pbo in offering.get("ProductBrandOptions", []):
            if pbo.get("id") == selected_option_id or selected_option_id in str(pbo):  # rough match
                if "itinerary_summary" in pbo:
                    brand_offering = pbo
                    break
    
    # If we still don't have an itinerary summary, try to get it from the raw response directly
    if "itinerary_summary" not in brand_offering:
        # Attempt to find the offering in the raw_response
        raw_response = raw_data.get("raw_response", {})
        resolved_offerings = raw_response.get("ResolvedOfferings", [])
        
        for offering in resolved_offerings:
            for pbo in offering.get("ProductBrandOptions", []):
                # Look for the specific PBO that matches our selected option
                if pbo.get("flightRefs"):  # A heuristic to match
                    brand_offering = pbo
                    break
            if brand_offering:
                break
    
    if "itinerary_summary" not in brand_offering:
        return {"status": "error", "message": "Itinerary summary not found in selected option"}
    
    # 2. build payload using the brand_offering which contains itinerary_summary
    payload = build_from_products_payload(brand_offering,
                                          passengers=len(traveler_details),
                                          passenger_type="ADT")  # adjust mapping
    
    # 3. Initiate reservation
    init_resp = await TravelportInitiateReservationWorkbench()
    if isinstance(init_resp, dict) and "reservation_id" in init_resp:
        reservation_id = init_resp["reservation_id"]
    else:
        return {"status": "error", "message": f"Failed to initiate reservation: {init_resp}"}
    
    # 4. Add offer - Use the payload generated from itinerary_summary
    # Extract first segment details for the function call
    itinerary_summary = brand_offering.get("itinerary_summary", {})
    segments = itinerary_summary.get("segments", [])
    
    if not segments:
        return {"status": "error", "message": "No flight segments found in itinerary summary"}
    
    # Use the first segment for details (for now - in a real scenario you'd handle multiple segments)
    first_segment = segments[0]
    
    add_offer_resp = await TravelportAddOfferToReservation(
        reservation_id=reservation_id,
        offer_id=selected_option_id,  # Use the original selected option ID
        flight_number=first_segment.get("number", first_segment.get("flightNumber", "")),  # Try both keys
        carrier=first_segment.get("carrier", ""),
        departure_date=first_segment.get("departureDate", ""),
        departure_time=first_segment.get("departureTime", ""),
        arrival_date=first_segment.get("arrivalDate", ""),
        arrival_time=first_segment.get("arrivalTime", ""),
        departure_airport=first_segment.get("departureAirport", first_segment.get("from", "")),
        arrival_airport=first_segment.get("arrivalAirport", first_segment.get("to", "")),
        class_of_service=first_segment.get("classOfService", ""),
        cabin=first_segment.get("cabin", ""),
        segment_sequence=first_segment.get("segmentSequence", 1),
        brand_tier=brand_offering.get("brandTier", 1),  # This might not exist in all cases
        availability_source_code=first_segment.get("availabilitySourceCode", ""),
        content_source=first_segment.get("contentSource", ""),
        num_passengers=len(traveler_details),
        passenger_type="ADT"
    )
    
    if isinstance(add_offer_resp, dict) and "status" in add_offer_resp and add_offer_resp["status"] != "success":
        return {"status": "error", "message": f"Failed to add offer: {add_offer_resp}"}
    
    # 5. Add travelers
    # Assuming traveler_details is a list of travelers, we'll process the first one for now
    first_traveler = traveler_details[0] if isinstance(traveler_details, list) and traveler_details else traveler_details
    if isinstance(first_traveler, dict):
        add_trav_resp = await TravelportAddTravelerToReservation(
            reservation_id=reservation_id,
            first_name=first_traveler.get("first_name", ""),
            last_name=first_traveler.get("last_name", ""),
            gender=first_traveler.get("gender", ""),
            birth_date=first_traveler.get("birth_date", ""),
            phone_number=first_traveler.get("phone_number", ""),
            email=first_traveler.get("email", ""),
            passport_number=first_traveler.get("passport_number", ""),
            passport_expiry=first_traveler.get("passport_expiry", ""),
            passport_issuing_country=first_traveler.get("passport_issuing_country", ""),
            passenger_type_code=first_traveler.get("passenger_type_code", "ADT"),
            city_code=first_traveler.get("city_code", "ORD"),
            phone_role=first_traveler.get("phone_role", "Home")
        )
    else:
        return {"status": "error", "message": "Invalid traveler details format"}
    
    if isinstance(add_trav_resp, dict) and "status" in add_trav_resp and add_trav_resp["status"] != "success":
        return {"status": "error", "message": f"Failed to add traveler: {add_trav_resp}"}
    
    # 6. Commit reservation
    commit_resp = await TravelportCommitReservation(reservation_id=reservation_id)
    
    # Extract the PNR from the response
    if isinstance(commit_resp, str) and "PNR" in commit_resp:
        # Extract PNR from text response
        import re
        pnr_match = re.search(r'Locator \(PNR\): (\w+)', commit_resp)
        pnr = pnr_match.group(1) if pnr_match else None
        status = "success" if pnr else "error"
        return {
            "reservationId": reservation_id,
            "PNR": pnr,
            "status": status,
            "message": commit_resp
        }
    elif isinstance(commit_resp, dict):
        # Return the response as is
        return commit_resp
    else:
        return {
            "reservationId": reservation_id,
            "PNR": None,
            "status": "error",
            "message": f"Unexpected commit response format: {commit_resp}"
        }