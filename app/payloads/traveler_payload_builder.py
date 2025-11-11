# app/payloads/traveler_payload_builder.py
def build_traveler_payload(travelers: list):
    payload = []
    for idx, t in enumerate(travelers, 1):
        payload.append({
            "@type": "Traveler",
            "id": f"trav_{idx}",
            "gender": t["gender"],
            "birthDate": t["birth_date"],
            "passengerTypeCode": t.get("passenger_type_code", "ADT"),
            "PersonName": {"@type": "PersonNameDetail", "Given": t["first_name"], "Surname": t["last_name"]},
            "Telephone": [{"@type": "Telephone", "countryAccessCode": t.get("country_access_code", "1"), "phoneNumber": t["phone_number"]}],
            "Email": [{"value": t["email"]}],
            "TravelDocument": [{
                "@type": "TravelDocumentDetail",
                "docNumber": t["passport_number"],
                "docType": "Passport",
                "expireDate": t["passport_expiry"],
                "issueCountry": t["passport_issue_country"],
            }]
        })
    return payload