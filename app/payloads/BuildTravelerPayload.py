def build_traveler_payload(travelers: list):
    """
    Build payload for adding one or more travelers to a reservation.

    Args:
        travelers (list): List of traveler dicts, e.g.
        [
            {
                "id": "trav_1",
                "first_name": "John",
                "last_name": "Doe",
                "gender": "Male",
                "birth_date": "1986-11-11",
                "passenger_type_code": "ADT",
                "email": "john@example.com",
                "phone_number": "212456121",
                "country_access_code": "1",
                "city_code": "ORD",
                "phone_role": "Home",
                "passport_number": "A123123",
                "passport_expiry": "2035-05-29",
                "passport_issue_country": "US",
                "birth_country": "US"
            },
            ...
        ]
    """
    traveler_entries = []
    for t in travelers:
        traveler_entries.append({
            "@type": "Traveler",
            "gender": t["gender"],
            "birthDate": t["birth_date"],
            "id": t.get("id", f"trav_{travelers.index(t)+1}"),
            "passengerTypeCode": t.get("passenger_type_code", "ADT"),
            "PersonName": {
                "@type": "PersonNameDetail",
                "Given": t["first_name"],
                "Surname": t["last_name"]
            },
            "Telephone": [
                {
                    "@type": "Telephone",
                    "countryAccessCode": t.get("country_access_code", "1"),
                    "phoneNumber": t["phone_number"],
                    "cityCode": t.get("city_code", "ORD"),
                    "role": t.get("phone_role", "Home")
                }
            ],
            "Email": [
                {
                    "value": t["email"]
                }
            ],
            "TravelDocument": [
                {
                    "@type": "TravelDocumentDetail",
                    "docNumber": t["passport_number"],
                    "docType": "Passport",
                    "expireDate": t["passport_expiry"],
                    "issueCountry": t["passport_issue_country"],
                    "birthDate": t["birth_date"],
                    "Gender": t["gender"],
                    "PersonName": {
                        "@type": "PersonName",
                        "Given": t["first_name"],
                        "Surname": t["last_name"]
                    }
                }
            ]
        })
    return traveler_entries
