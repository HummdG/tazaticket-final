"""
Travelport Parser Utility
Resolves Product, Brand, Flight, and TermsAndConditions references
from CatalogProductOfferingsResponse.ReferenceList into a unified, human-readable structure.
"""

import datetime
from typing import Dict, Any, List, Optional


def _calc_duration(start: str, end: str) -> str:
    """
    Calculate duration between two ISO format datetime strings and return in human-readable format.
    Example: "2023-05-15T08:30:00" to "2023-05-15T10:45:00" -> "2h 15m"
    """
    try:
        if not start or not end:
            return "Unknown"
        
        start_dt = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.datetime.fromisoformat(end.replace("Z", "+00:00"))
        duration = end_dt - start_dt
        
        total_seconds = int(duration.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        
        if hours > 0 and minutes > 0:
            return f"{hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h"
        else:
            return f"{minutes}m"
    except Exception as e:
        print(f"[TravelportParser] Error calculating duration: {e}")
        return "Unknown"


def resolve_references(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a simplified, enriched response with all references resolved.
    Useful for generating conversational outputs or storing in Redis.
    """
    try:
        # Handle the actual structure from the real Travelport response
        ref_lists = response.get("CatalogProductOfferingsResponse", {}).get("ReferenceList", [])
        index = {"Product": {}, "Brand": {}, "TermsAndConditions": {}, "Flight": {}}

        # Build lookup tables - handle the actual structure in the real response
        for ref in ref_lists:
            # Check for different reference list types
            if ref.get("@type") == "ReferenceListProduct":
                for p in ref.get("Product", []):
                    index["Product"][p["id"]] = p
            elif ref.get("@type") == "ReferenceListBrand":
                for b in ref.get("Brand", []):
                    index["Brand"][b["id"]] = b
            elif ref.get("@type") == "ReferenceListTermsAndConditions":
                for t in ref.get("TermsAndConditions", []):
                    index["TermsAndConditions"][t["id"]] = t
            elif ref.get("@type") == "ReferenceListFlight":
                for f in ref.get("Flight", []):
                    index["Flight"][f["id"]] = f

        # Expand offerings
        offerings = response.get("CatalogProductOfferingsResponse", {}) \
                            .get("CatalogProductOfferings", {}) \
                            .get("CatalogProductOffering", [])
        enriched_offerings = []

        for offer in offerings:
            offer_data = {
                "id": offer.get("id"),
                "sequence": offer.get("sequence"),
                "ProductBrandOptions": [],
            }

            for option in offer.get("ProductBrandOptions", []):
                for pbo in option.get("ProductBrandOffering", []):
                    # Get references with the correct structure
                    product_id = None
                    brand_id = None
                    terms_id = None
                    
                    # Product reference
                    product_ref_obj = pbo.get("Product", [])
                    if product_ref_obj and len(product_ref_obj) > 0:
                        product_id = product_ref_obj[0].get("productRef")
                    
                    # Brand reference
                    brand_ref_obj = pbo.get("Brand", {})
                    if brand_ref_obj:
                        brand_id = brand_ref_obj.get("BrandRef")
                    
                    # TermsAndConditions reference
                    terms_ref_obj = pbo.get("TermsAndConditions", {})
                    if terms_ref_obj:
                        terms_id = terms_ref_obj.get("termsAndConditionsRef")

                    product = index["Product"].get(product_id, {})
                    brand = index["Brand"].get(brand_id, {})
                    terms = index["TermsAndConditions"].get(terms_id, {})

                    # Extract additional product information from nested structure
                    cabin_class = None
                    fare_basis_code = None
                    product_description = None
                    
                    # Look for cabin class and fare basis in PassengerFlight -> FlightProduct
                    passenger_flights = product.get("PassengerFlight", [])
                    if passenger_flights and len(passenger_flights) > 0:
                        flight_products = passenger_flights[0].get("FlightProduct", [])
                        if flight_products and len(flight_products) > 0:
                            fp = flight_products[0]
                            cabin_class = fp.get("cabin")
                            fare_basis_code = fp.get("fareBasisCode")
                            
                    # Use product description or ID as fallback
                    product_description = product.get("id")

                    # Get price information
                    price_info = pbo.get("BestCombinablePrice", {})
                    total_price = price_info.get("TotalPrice") if price_info else None
                    currency_info = price_info.get("CurrencyCode", {}) if price_info else {}
                    currency_value = currency_info.get("value") if currency_info else None

                    pbo_resolved = {
                        "brand_name": brand.get("name") if brand else None,
                        "product_name": product_description,
                        "fare_basis": fare_basis_code,
                        "cabin_class": cabin_class,
                        "terms": terms.get("id") if terms else None,  # Using ID as fallback
                        "price": total_price,
                        "currency": currency_value,
                        "flightRefs": option.get("flightRefs", []),
                        "flight_details": [index["Flight"].get(fid, {}) for fid in option.get("flightRefs", [])],
                    }

                    offer_data["ProductBrandOptions"].append(pbo_resolved)
            
            # Add itinerary summaries to each ProductBrandOption
            for pbo in offer_data.get("ProductBrandOptions", []):
                # collect all flight refs
                flight_refs = pbo.get("flightRefs", [])
                segs = [index["Flight"].get(fid, {}) for fid in flight_refs]
                
                # Process segments to extract proper departure/arrival info
                processed_segs = []
                for seg in segs:
                    # Extract departure and arrival info from nested structure
                    departure_detail = seg.get("Departure", {})
                    arrival_detail = seg.get("Arrival", {})
                    
                    # Create a new segment with proper field mappings
                    processed_seg = {
                        # Flight details
                        "id": seg.get("id"),
                        "carrier": seg.get("carrier"),
                        "number": seg.get("number"),
                        "equipment": seg.get("equipment"),
                        "distance": seg.get("distance"),
                        "duration": seg.get("duration"),  # ISO 8601 duration format
                        "AvailabilitySourceCode": seg.get("AvailabilitySourceCode"),
                        "contentSource": seg.get("ContentSource"),
                        
                        # Departure details
                        "departureAirport": departure_detail.get("location"),
                        "departureTime": departure_detail.get("time"),
                        "departureDate": departure_detail.get("date"),
                        "departureTerminal": departure_detail.get("terminal"),
                        
                        # Arrival details
                        "arrivalAirport": arrival_detail.get("location"),
                        "arrivalTime": arrival_detail.get("time"),
                        "arrivalDate": arrival_detail.get("date"),
                        "arrivalTerminal": arrival_detail.get("terminal"),
                        
                        # For duration calculations (convert ISO format to datetime if needed)
                        "departureDateTime": f"{departure_detail.get('date')}T{departure_detail.get('time')}" if departure_detail.get('date') and departure_detail.get('time') else None,
                        "arrivalDateTime": f"{arrival_detail.get('date')}T{arrival_detail.get('time')}" if arrival_detail.get('date') and arrival_detail.get('time') else None,
                        
                        # Segment sequence (if available in the flight object itself)
                        "segmentSequence": seg.get("segmentSequence", 0)
                    }
                    processed_segs.append(processed_seg)
                
                # sort segments by segmentSequence if present
                segs_sorted = sorted(processed_segs, key=lambda s: s.get("segmentSequence", 0))
                
                # build layover info
                layovers = []
                for i in range(len(segs_sorted)-1):
                    arr_time = segs_sorted[i].get("arrivalDateTime")
                    dep_time = segs_sorted[i+1].get("departureDateTime")
                    if arr_time and dep_time:
                        layovers.append({
                            "fromAirport": segs_sorted[i].get("arrivalAirport"),
                            "toAirport": segs_sorted[i+1].get("departureAirport"),
                            "duration": _calc_duration(arr_time, dep_time)
                        })
                
                # compute total duration
                if segs_sorted:
                    first_seg = segs_sorted[0]
                    last_seg = segs_sorted[-1]
                    first_dep_time = first_seg.get("departureDateTime")
                    last_arr_time = last_seg.get("arrivalDateTime")
                    total_duration = _calc_duration(first_dep_time, last_arr_time) if first_dep_time and last_arr_time else None
                else:
                    total_duration = None
                
                # attach itinerary summary
                pbo["itinerary_summary"] = {
                    "segments": segs_sorted,
                    "layovers": layovers,
                    "total_duration": total_duration,
                    "num_stops": len(layovers)
                }
            
            enriched_offerings.append(offer_data)

        response["ResolvedOfferings"] = enriched_offerings
        return response

    except Exception as e:
        print(f"[TravelportParser] Error resolving references: {e}")
        return response