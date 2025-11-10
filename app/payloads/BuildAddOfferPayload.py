def build_add_offer_payload(segments: list, passengers: int = 1, passenger_type: str = "ADT"):
    """
    Build Travelport 'Add Offer' payload dynamically for one-way or round-trip flights.
    
    Args:
        segments (list): List of flight segments (each segment is a dict with keys below)
            {
                "flightNumber": "401",
                "carrier": "QF",
                "departureDate": "2025-06-29",
                "departureTime": "06:00:00",
                "arrivalDate": "2025-06-29",
                "arrivalTime": "07:35:00",
                "from": "SYD",
                "to": "MEL",
                "classOfService": "E",
                "cabin": "Economy",
                "segmentSequence": 1,
                "brandTier": "1",
                "AvailabilitySourceCode": "Q",
                "ContentSource": "GDS"
            }
        passengers (int): Number of passengers.
        passenger_type (str): Passenger type code ("ADT", "CHD", "INF").
    """

    return {
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
            "ProductCriteriaAir": [
                {
                    "SpecificFlightCriteria": [
                        {
                            "flightNumber": seg["flightNumber"],
                            "carrier": seg["carrier"],
                            "departureDate": seg["departureDate"],
                            "departureTime": seg["departureTime"],
                            "arrivalDate": seg["arrivalDate"],
                            "arrivalTime": seg["arrivalTime"],
                            "from": seg["from"],
                            "to": seg["to"],
                            "classOfService": seg["classOfService"],
                            "cabin": seg["cabin"],
                            "segmentSequence": seg.get("segmentSequence", i + 1),
                            "brandTier": seg.get("brandTier", "1"),
                            "AvailabilitySourceCode": seg.get("AvailabilitySourceCode", "Q"),
                            "ContentSource": seg.get("ContentSource", "GDS")
                        }
                        for i, seg in enumerate(segments)
                    ]
                }
            ]
        }
    }
