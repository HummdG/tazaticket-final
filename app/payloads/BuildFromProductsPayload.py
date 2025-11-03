def build_from_products_payload(selected_offer: dict, passengers: int = 1, passenger_type: str = "ADT"):
    """
    Create the AddOffer payload dynamically from a user's selected offer object.
    """
    req = {
        "@type": "OfferQueryBuildFromProducts",
        "BuildFromProductsRequest": {
            "@type": "BuildFromProductsRequestAir",
            "PassengerCriteria": [
                {
                    "@type": "PassengerCriteria",
                    "number": passengers,
                    "passengerTypeCode": passenger_type
                }
            ],
            "ProductCriteriaAir": []
        }
    }
    
    # Get segments from itinerary_summary
    itinerary_summary = selected_offer.get("itinerary_summary", {})
    segments = itinerary_summary.get("segments", [])
    
    # For this implementation, we'll group all segments into one ProductCriteriaAir as a single leg
    # In a more sophisticated implementation, we might need to group by actual legs
    if segments:
        pc = {"SpecificFlightCriteria": []}
        for seg in segments:
            # Use different field names that might exist in the actual response
            flight_number = seg.get("number") or seg.get("flightNumber")
            carrier = seg.get("carrier", "")
            departure_date = seg.get("departureDate", "")
            departure_time = seg.get("departureTime", "")
            arrival_date = seg.get("arrivalDate", "")
            arrival_time = seg.get("arrivalTime", "")
            departure_airport = seg.get("from") or seg.get("departureAirport", "")
            arrival_airport = seg.get("to") or seg.get("arrivalAirport", "")
            class_of_service = seg.get("classOfService", "")
            cabin = seg.get("cabin", "")
            segment_sequence = seg.get("segmentSequence", 1)
            availability_source_code = seg.get("availabilitySourceCode", "")
            content_source = seg.get("contentSource", "")
            
            pc["SpecificFlightCriteria"].append({
                "flightNumber": flight_number,
                "carrier": carrier,
                "departureDate": departure_date,
                "departureTime": departure_time,
                "arrivalDate": arrival_date,
                "arrivalTime": arrival_time,
                "from": departure_airport,
                "to": arrival_airport,
                "classOfService": class_of_service,
                "cabin": cabin,
                "segmentSequence": segment_sequence,
                "brandTier": selected_offer.get("brandTier", 1),
                "AvailabilitySourceCode": availability_source_code,
                "ContentSource": content_source
            })
        req["BuildFromProductsRequest"]["ProductCriteriaAir"].append(pc)
    
    return req