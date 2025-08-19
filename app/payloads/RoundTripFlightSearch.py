def OneWayFlightSearch(departure_date:str, from_city:str, to_city:str, carrier:str, return_date:str):

    payload = {
        "@type": "CatalogProductOfferingsQueryRequest",
        "CatalogProductOfferingsRequest": {
            "@type": "CatalogProductOfferingsRequestAir",
            "contentSourceList": [
                "GDS"
            ],
            "PassengerCriteria": [
                {
                    "@type": "PassengerCriteria",
                    "number": 1,
                    "age": 25,
                    "passengerTypeCode": "ADT"
                }
            ],
            "SearchCriteriaFlight": [
                {
                    "@type": "SearchCriteriaFlight",
                    "departureDate": departure_date,
                    "From": {
                        "value": from_city
                    },
                    "To": {
                        "value": to_city
                    }
                },
                {
                    "@type": "SearchCriteriaFlight",
                    "departureDate": return_date,
                    "From": {
                        "value": to_city
                    },
                    "To": {
                        "value": from_city
                    }
                }
            ],
            "SearchModifiersAir": {
                "@type": "SearchModifiersAir",
                "CarrierPreference": [
                    {
                        "@type": "CarrierPreference",
                        "preferenceType": "Preferred",
                        "carriers": [
                            "TK"
                        ]
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