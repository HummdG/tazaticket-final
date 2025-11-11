# app/tools/UnifiedTravelportBooking_v2.py
from app.payloads.add_offer_payload_builder import build_add_offer_payload_from_pbo
from app.payloads.traveler_payload_builder import build_traveler_payload
from app.services.search_result_manager_v2 import search_result_manager

async def UnifiedTravelportBooking_v2(wa_id, search_id, offer_number, travelers):
    option = await search_result_manager.get_option(search_id, offer_number)
    if option["status"] != "success":
        return {"status": "error", "message": "Invalid selection"}

    pbo = option["flight_option"]["pbo_data"]
    ref_list = option["flight_option"].get("reference_list", {})

    offer_payload = build_add_offer_payload_from_pbo(pbo, ref_list, len(travelers))
    traveler_payload = build_traveler_payload(travelers)

    # Travelport API sequence here (mock)
    return {
        "status": "success",
        "pnr": "ABC123",
        "summary": {
            "airline": "Emirates",
            "route": "LHE → DXB",
            "fare": 480
        }
    }