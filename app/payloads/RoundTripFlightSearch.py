def RoundTripFlightSearch(origin: str, destination: str, departure_date: str, return_date: str, number_of_passengers: int = 1, carriers: list = None):
    """Build a round-trip flight search payload for Travelport API"""
    
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
            "contentSourceList": [
                "GDS"
            ],
            "PassengerCriteria": passenger_criteria,
            "SearchCriteriaFlight": [
                {
                    "@type": "SearchCriteriaFlight",
                    "departureDate": departure_date,
                    "From": {
                        "value": origin
                    },
                    "To": {
                        "value": destination
                    }
                },
                {
                    "@type": "SearchCriteriaFlight",
                    "departureDate": return_date,
                    "From": {
                        "value": destination
                    },
                    "To": {
                        "value": origin
                    }
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
            "PricingModifiersAir":{"@type":"PricingModifiersAir","FareSelection":{"@type":"FareSelection","fareType":"AllFares"}},
            "CustomResponseModifiersAir": {
                "@type": "CustomResponseModifiersAir",
                "SearchRepresentation": "Journey"
            }
        }
    }
    
    return payload