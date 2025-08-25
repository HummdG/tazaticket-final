def OneWayFlightSearch(origin: str, destination: str, departure_date: str, number_of_passengers: int = 1, carriers: list = None):
    """Build a one-way flight search payload for Travelport API"""
    
    # Use default carriers if none provided
    if carriers is None:
        carriers = ["TK"]  # Default to Turkish Airlines
    
    # Build passenger criteria
    passenger_criteria = []
    for i in range(number_of_passengers):
        passenger_criteria.append({
            "@type": "PassengerCriteria",
            "number": i + 1,
            "age": 25,
            "passengerTypeCode": "ADT"
        })
    
    payload = {
        "@type": "CatalogProductOfferingsQueryRequest",
        "CatalogProductOfferingsRequest": {
            "@type": "CatalogProductOfferingsRequestAir",
            "maxNumberOfUpsellsToReturn": 1,
            "contentSourceList": ["GDS"],
            "PassengerCriteria": passenger_criteria,
            "SearchCriteriaFlight": [
                {
                    "@type": "SearchCriteriaFlight",
                    "departureDate": departure_date,
                    "From": {"value": origin},
                    "To": {"value": destination}
                }
            ],
            "SearchModifiersAir": {
                "@type": "SearchModifiersAir",
                "CarrierPreference": [
                    {
                        "@type": "CarrierPreference",
                        "preferenceType": "Preferred",
                        "carriers": carriers
                    }
                ]
            },
            "CustomResponseModifiersAir": {
                "@type": "CustomResponseModifiersAir",
                "SearchRepresentation": "Journey"
            }
        }
    }
    
    return payload