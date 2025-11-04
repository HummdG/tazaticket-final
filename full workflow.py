# %% [markdown]
# # Full Itienry Workflow

# %% [markdown]
# 3 types of itineries:
# 1. One way: `LHE to DXB`
# 2. Return:  `LHE -> DXB` and `DXB -> LHE`
# 3. Mutli-Segment: `LHE -> KHI -> JED -> DXB` and `DXB -> DOH -> LHE`

# %% [markdown]
# ### OAuth

# %%
import requests
import os
import json
import time
import dotenv

# %%
dotenv.load_dotenv()

# %%

url = "https://oauth.pp.travelport.com/oauth/oauth20/token"

# payload = 'grant_type=password&username=TP11590373&password=sY8QNHQR&client_id=pp-cRGXqAeBfsyzuK2L7ZM0T5WXM1TVdQPVZLgrNGYC&client_secret=d65bf3ca79b2f058d33be1516f410e35aef0439760f5d99087da26651d9de8a1&scope=openid'
payload = f'grant_type=password&username={os.getenv("TRAVELPORT_USERNAME")}&password={os.getenv("TRAVELPORT_PASSWORD")}&client_id={os.getenv("TRAVELPORT_CLIENT_ID")}&client_secret={os.getenv("TRAVELPORT_CLIENT_SECRET")}&scope=openid'
headers = {
  'Cache-Control': 'no-cache',
  'Content-Type': 'application/x-www-form-urlencoded',
  'Authorization': 'Bearer eyJhbGciOiJkaXIiLCJlbmMiOiJBMTI4Q0JDLUhTMjU2IiwianRpIjoidGEydHNrbHJqMmpiIn0..HeTi_3RtNXIorYsWI6BENA.QVHggDgQeRGDHLcp0UrUwKjNCdhtv5KAZzr1uC3V5h_0szGbrbL6h58gTsV9t7SQPbK32GXFGAKGHxhUgeWDzLwXHABanrF4grYFz1uGxm0wgyTM6zqq-r-Hc-CLDd6zOxknFy0k1Ho5KLro9vlEfSWzVRaycQBvabBopKo8on9C67pCuA3sNyh-ls1IgTFhOXtj1i7r6LJWG0ADL2vgV_qi_ISd2SX-3A1H6RSSEE_bHEuJ4gIWiqSrpAuGbveiQmVUpXBGoIszad7TaPnxk_PGbDCbg8ucRq_P8CXQl4vgVdaiceJBt0iwBdGp3xzYWbtIhFOYDDlykUIfNBplqNOx9tCJrEcYFu0oKIwjuTKDFMOlsB1NmxUKIlqpqxBQgHYLHdqR0Yroq1QbGOTG5ctwRQy84LDn1hsEQrDouhUQ820QJ2qrHSJ3gFp5KNyVBxVy-wfLrcioaa2j1oqTn0SX2btYXNmhaRhtD0Grz_53tYiZ1_W5w5AHTJZaYZ8iQYQ_YBi6IQFc6Q_G0uPMsPSRzN9q6VfPZTkd35d_EoQDXRcTSzrDu-ycZ_H9cjKuRJVXhUmOE6VBWVQbxC2GDRzlrMxGAphHDHv7KfeZdhNpmFFI3ETZcOH0qPTys4zNNNK6k9S-EyGCd-sFkqrdSwtoNDCTxEKyC57jss8IRtSaJ39IMKIcL4PWDamrtNjZYMQrx0iNCGg2IIoLflNXvxt6EE_dIBDnaoaBQmnLMZm1mUJZc6VpE07AfpnwTUBcOA3tBadItkZxUHOMT1mdGyzn9ROMR_ozzb0KP3F2c-mJaza-DtntE6YZaqkw2pFhriJ7N4kJ0895X_v9oYiCuunpGtN0lPfImaQNBYmjY5eRj4Cst1Q48AcGLfIjZ8lfjAC2pHFRuB6Gs6U3JI3-KDEUx0dDGigzEru9aovcUBEoUKNZRhMueLXWPqoA3CYRqlWlcmiuWtJLXfcyxBJhV7L3rC5wmutllN3k4lB11v0AewhWJriYkD2D2Mj8gMDDhS_b3bRsS7P5UkSDmUjGHJmLQiWDcD973PFC9P8IuwaKjt8tM7IpyOajGIqpDdDubqSGPSSLW8cKY89CG1AmauTWJT999cOZXrCIsSqJO2yzXVnxUMFVeQO25mEy7xztF4qX2qtKZMSl7WBaJxmOM9CsrmWWQA-kGKJl3SHNZOekHuXWmpegK9le5tyCFAirx28ul_D7C80AQLupvaPFBLZgXKhzZ0E2wrEZz-RuScd2WVe0Py-HF9BpFsb-L87T9bg0k_MLMOmugWQN4DPFbqtvDbONFcwNC2O7EWk9KREwFWnZZJ4Y0dGtcx97qYn5KeLuDoHSF-5y920ycaG10mP9pjMYqo7GFi7hMVCDXV4XQX_a4-uL_NkSvcKnVTfh55vLSuKwAWTNgAFtbHKU97FP8x07i_LmsAufFB8wYwOqx212L9p7HeylxCMyh0dGAaR4UnZ1EVdgwdX7JkTYwpZteS4y6_loGzGVzDQQoB8mVi7A8EYgdwevps8HTBtjjFXa_eiM4Z0Ua88oPImax7uNegXlCTq9A8fnBwW5cUCn7oZVgiprRsfHP2tUVPgJ_d7tIwgWfT7JXIlY7y8G6PJAayy5TlUbyeuAoHJI9yZS8Cvt-BB0DQYgeGHnOg9cTUPzb83vVTziIrd5BCaEMcRMUtbojMaX9swM5VSd0BVXofEO7gZpm3NF_yI0vMiGyc37MNt4b0zojpbUoSa-zcaAyviuxVd8cmv7DoNNuR9N3-nLGWNJ_byWgJjRj0G5JXW34fgOR4rvOab0m2evoXAyJUav5THa2hamfExaRed_XgB_UQ4mwi06QLftaXEynKLmHpO4HzNMST6EXjwyIMrSnX56lV8yliqu-DFGrSeTgASHYhG-zyviyJKZvOj4xwCM1R8gG9Eg61vs8oVlYkYwMMT4Twy6uPzV9YF9c3k21_7hYkwrDHOVxGGBGccrVHZkRcpUiKR79m59jfzIf3QyrcRrMeJi4cG8K6se5WhaelJ2uV3yQ24k9MqR27sJHIltOZZ8Cx1pHYwFc-EyeZyZ4BSNa1FxDlHor1DyTRSVKGPjBphtg0LZiF4qPvanLXB8yS1s74-AxGC0YONxJSfXRmvB5KoKKEVoHotH8VqmPnrzDqZERN9pyj4gtL-Us4XJQ2aUGzKjSQewG9kgDtTDcrhe1Xnz9HQgCUvaYpxLc8K8gcR-8CqmAw0bf5VZx-9_imrx0eIPlxtawNX7C2-Cd3WU1xqzjG7pg8mI0WoZBB2mlwVem9NKWHHNUtUgbZLyd_3DU0gVdm7jYSMZ87ftAcEajBQm4FYSKo2SAdnN4hPapI_k4NY_KeHbt1M90DMXUhXbHCTsgD6FkvHUEsVBJ3yn5hb0I8uMeQSqEYJmBu2kui8-Yvy_3p3GiUeZGg7jHbisbFK6XsaEGLYTVrch4v_gEDmy6lHGNlhraU_XnooKHc2DZ7bWi1lSCQE10oFvSSpLFKyTIbzfA71k54qkuu-9ZKgPoSvG1JOIy3m0f6EATt6JTMUpmrA7J0W8tQNbeQop-5iED-fuMvKcpMXbEWoF09sHSOmKWfgkffB615-nC3wzVr9UBtPLTz1WrIfCTne1ZR_wnOXMET6scoho7Gvpz_STcq8DvVeoUYuXjAE5-6qXtXRdz8b3yOr_.aanmDSe-KfyCeCZ6qqt1vA',
  'Cookie': 'akaalb_OAUTH_PP=1760625237~op=TESTING_OAUTH_PP:oauth_pp_adc|~rv=81~m=oauth_pp_adc:0|~os=7557a3a7e0cab2ea6762b88c5dd8697c~id=8d172fcf24523b7aaeb579b373c2b492'
}

response = requests.request("POST", url, headers=headers, data=payload)

print(response.text)
token = json.loads(response.text)["access_token"]
print(token)



# %% [markdown]
# ## One Way:
# 
# - `LHE -> DXB`
# - 1x Adult Passenger

# %%
num_passengers = 1
itinerary = [
    {
        "departure": "LHR", # no details found for LHE to DXB on travelport, changing.
        "arrival": "DXB",
        # "departure": "LHE", # no details found for LHE to DXB on travelport, changing.
        # "arrival": "DXB",
        "departureDate": "2025-12-20"
    }
]
passenger_type = "ADT"  # ADT for Adult, CHD for Child, INF for Infant

# %% [markdown]
# ### Search

# %%
search_headers = {
  'Accept': 'application/json',
  'Content-Type': 'application/json',
  'XAUTH_TRAVELPORT_ACCESSGROUP': os.getenv("TRAVELPORT_ACCESS_GROUP"),
  'Accept-Version': '11',
  'Content-Version': '11',
  'taxBreakDown': 'true',
   "Authorization": f"Bearer {token}",
}

# %%
search_dict = {
  "@type": "CatalogProductOfferingsQueryRequest",
  "CatalogProductOfferingsRequest": {
    "@type": "CatalogProductOfferingsRequestAir",
    "maxNumberOfUpsellsToReturn": 4,
    "contentSourceList": [
      "GDS"
    ],
    "PassengerCriteria": [
      {
        "@type": "PassengerCriteria",
        "number": num_passengers,
        "passengerTypeCode": passenger_type
      }
    ],
    "SearchCriteriaFlight": [
      {
        "@type": "SearchCriteriaFlight",
        "departureDate": itinerary[0]["departureDate"],
        "From": {
          "value": itinerary[0]["departure"]
        },
        "To": {
          "value": itinerary[0]["arrival"]
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
            # "AA"
            "EK"
          ]
        }
      ]
    }
  }
}


# %%

# url = f"{os.getenv('TRAVELPORT_BASE_URL')}/{os.getenv('TRAVELPORT_VERSION')}/air/catalog/search/catalogproductofferings"
# url = f"{os.getenv('TRAVELPORT_BASE_URL')}/{os.getenv('TRAVELPORT_VERSION')}/air/catalog/search/catalogproductofferings" # getting 404 error 
url = "https://api.pp.travelport.com/11/air/catalog/search/catalogproductofferings"

search_payload = json.dumps(search_dict)

response = requests.request("POST", url, headers=search_headers, data=search_payload)

print(response)

print(type(response))

print(response.text)

search_response_json = response.json()
print(type(search_response_json))
print(search_response_json)

#save in a json file
with open("search_response.json", "w") as json_file:
    json.dump(search_response_json, json_file)


# %%
type(response)

# %%
print(type(response))

# %% [markdown]
# ### Price

# %%
import requests
import json

# %%
headers = {
  'Accept': 'application/json',
  'Content-Type': 'application/json',
  'XAUTH_TRAVELPORT_ACCESSGROUP': os.getenv("TRAVELPORT_ACCESS_GROUP"),
  'Accept-Version': '11',
  'Content-Version': '11'
}

# %%

# url = "https://{{baseURL}}/{{version}}/air/price/offers/buildfromproducts"
url = "https://api.pp.travelport.com/11/air/price/offers/buildfromproducts"

payload = json.dumps(
    {
  "@type": "OfferQueryBuildFromProducts",
  "BuildFromProductsRequest": {
    "@type": "BuildFromProductsRequestAir",
    "PassengerCriteria": [
      {
        "@type": "PassengerCriteria",
        "number": 1,
        "passengerTypeCode": "ADT"
      }
    ],
    "ProductCriteriaAir": [
      {
        "SpecificFlightCriteria": [
          {
            "flightNumber": "2755",
            "carrier": "AA",
            "departureDate": "2025-06-28",
            "departureTime": "06:49:00",
            "arrivalDate": "2025-06-28",
            "arrivalTime": "08:23:00",
            "from": itinerary[0]["departure"],
            "to": itinerary[0]["arrival"],
            "classOfService": "Y",
            "cabin": "Economy",
            "segmentSequence": 1,
            "brandTier": "4",
            "AvailabilitySourceCode": "Q",
            "ContentSource": "GDS"
          }
        ],
        "sequence": 1
      }
    ]
  },
  "validateInventoryInd": True
})



response = requests.request("POST", url, headers=headers, data=payload)

print(response.text)


# %% [markdown]
# ### Reservation

# %% [markdown]
# In our choice, we have corresponding Refernces:
# 
# - offer: `o5`
# - brand: `b0`
# - flightRef: `s4`
# - product: `p36`
# - Terms&Cond: `T17`

# %%
# load json into a  dict
with open("search_response.json") as f:
    search_response = json.load(f)

# %%

offers = search_response["CatalogProductOfferingsResponse"]["CatalogProductOfferings"]["CatalogProductOffering"]
my_offer = next((offer for offer in offers if offer.get("id") == "o5"), None)
print(my_offer)

brand = next((b for b in search_response["CatalogProductOfferingsResponse"]["ReferenceList"][2]["Brand"] if b.get("id") == "b0"), None)
print(brand)


flight = next((f for f in search_response["CatalogProductOfferingsResponse"]["ReferenceList"][0]["Flight"] if f.get("id") == "s4"), None)
print(flight)


product = next((p for p in search_response["CatalogProductOfferingsResponse"]["ReferenceList"][1]["Product"] if p.get("id") == "p36"), None)
print(product)

terms_and_conditions = next((t for t in search_response["CatalogProductOfferingsResponse"]["ReferenceList"][3]["TermsAndConditions"] if t.get("id") == "T17"), None)
print(terms_and_conditions)

# %% [markdown]
# Extracting specifications for reservation

# %%

flightNumber = flight["number"]
print("flightNumber:", flightNumber)

carrier = flight["carrier"]
print("carrier:", carrier)

departureDate = flight["Departure"]["date"]
print("departureDate:", departureDate)
departureTime = flight["Departure"]["time"]
arrivalDate = flight["Arrival"]["date"]
arrivalTime = flight["Arrival"]["time"]
departure = flight["Departure"]["location"]
arrival = flight["Arrival"]["location"]
print("departureTime:", departureTime)
print("arrivalDate:", arrivalDate)
print("arrivalTime:", arrivalTime)
print("departure:", departure)
print("arrival:", arrival)


classOfService = product["PassengerFlight"][0]["FlightProduct"][0]["classOfService"]
cabin = product["PassengerFlight"][0]["FlightProduct"][0]["cabin"]
print("classOfService:", classOfService)
print("cabin:", cabin)

segmentSequence = product["PassengerFlight"][0]["FlightProduct"][0]["segmentSequence"][0]
print("segmentSequence:", segmentSequence)
brandTier = brand["tier"]
print("brandTier:", brandTier)
AvailabilitySourceCode = flight["AvailabilitySourceCode"]
print("AvailabilitySourceCode:", AvailabilitySourceCode)
ContentSource = my_offer["ProductBrandOptions"][0]["ProductBrandOffering"][0]["ContentSource"]
print("ContentSource:", ContentSource)

# %%

payload_dict= {
  "@type": "OfferQueryBuildFromProducts",
  "BuildFromProductsRequest": {
    "@type": "BuildFromProductsRequestAir",
    "PassengerCriteria": [
      {
        "@type": "PassengerCriteria",
        "number": num_passengers,
        "passengerTypeCode": passenger_type
      }
    ],
    "ProductCriteriaAir": [
      {
        "SpecificFlightCriteria": [
          {
            # "flightNumber": "2755",
            "flightNumber": flightNumber,
            # "carrier": "AA",
            "carrier": carrier,
            # "departureDate": "2025-06-28",
            "departureDate": departureDate,
            # "departureTime": "06:49:00",
            "departureTime": departureTime,
            # "arrivalDate": "2025-06-28",
            "arrivalDate": arrivalDate,
            # "arrivalTime": "08:23:00",
            "arrivalTime": arrivalTime,
            # "from": "LHE",
            "from": departure,
            "to": arrival,
            # "classOfService": "Y",
            "classOfService": classOfService,
            # "cabin": "Economy",
            "cabin": cabin,
            # "segmentSequence": 1,
            "segmentSequence": segmentSequence,
            # "brandTier": "4",
            "brandTier": brandTier,
            # "AvailabilitySourceCode": "Q",
            "AvailabilitySourceCode": AvailabilitySourceCode,
            # "ContentSource": "GDS"
            "ContentSource": ContentSource
          }
        ],
        "sequence": 1
      }
    ]
  }
}

reserve_payload = json.dumps(payload_dict)


# %%
import requests
import json

# iniitiate workbench session 
headers = {
  'Accept': 'application/json',
  'Content-Type': 'application/json',
  'XAUTH_TRAVELPORT_ACCESSGROUP': os.getenv("TRAVELPORT_ACCESS_GROUP"),
  'Content-Version': '11',
  'Authorization': f'Bearer {token}'
  }

url = "https://api.pp.travelport.com/11/air/book/session/reservationworkbench"

payload = json.dumps({
  "@type": "ReservationID",
  "ReservationID": {}
})

response = requests.request("POST", url, headers=headers, data=payload)

print(response.text)
# get the token "value" from the response
reservation_id = json.loads(response.text)["ReservationResponse"]["Reservation"]["Identifier"]["value"]
print(reservation_id)


# add  offer

url_to_add_offer = f"https://api.pp.travelport.com/11/air/book/airoffer/reservationworkbench/{reservation_id}/offers/buildfromproducts"


headers_to_add_offer = {
  'Accept': 'application/json',
  'Content-Type': 'application/json',
#   'trackingId': 'fdf6b395-9e8f-709b-b5b2-8fad2c4b3e0e',
  'trackingId': f'{reservation_id}',
  'XAUTH_TRAVELPORT_ACCESSGROUP': os.getenv("TRAVELPORT_ACCESS_GROUP"),
  'Content-Version': '11',
  'Authorization': f'Bearer {token}'}

response = requests.request("POST", url_to_add_offer, headers=headers_to_add_offer, data=reserve_payload)

print(response.text)

# add traveler info
url_to_add_traveler = f"https://api.pp.travelport.com/11/air/book/traveler/reservationworkbench/{reservation_id}/travelers"

payload_traveler = json.dumps({
  "@type": "Traveler",
  "gender": "Male",
  "birthDate": "1986-11-11",
  "id": "trav_1",
  "passengerTypeCode": "ADT",
  "PersonName": {
    "@type": "PersonNameDetail",
    "Given": "Hummd",
    "Surname": "Bhai"
  },
  "Telephone": [
    {
      "@type": "Telephone",
      "countryAccessCode": "1",
      "phoneNumber": "212456121",
      "id": "4",
      "cityCode": "ORD",
      "role": "Home"
    }
  ],
  "Email": [
    {
      "value": "qtanwer@gmail.com"
    }
  ],
  "TravelDocument": [
    {
      "@type": "TravelDocumentDetail",
      "docNumber": "A123123",
      "docType": "Passport",
      "expireDate": "2035-10-16",
      "issueCountry": "US",
      "birthDate": "1986-11-11",
      "Gender": "Male",
      "PersonName": {
        "@type": "PersonName",
        "Given": "Hummd",
        "Surname": "Bhai"
      }
    }
  ]
})


headers_traveler = {
  'Accept': 'application/json',
  'Content-Type': 'application/json',
  'XAUTH_TRAVELPORT_ACCESSGROUP': os.getenv("TRAVELPORT_ACCESS_GROUP"),
  'Content-Version': '11',
  'Authorization': f'Bearer {token}'
  }

response = requests.request("POST", url_to_add_traveler, headers=headers_traveler, data=payload_traveler)

print(response.text)


# commit reservation
url_to_commit_reservation = f"https://api.pp.travelport.com/11/air/book/reservation/reservations/{reservation_id}"

payload_commit_reservation = json.dumps({
  "@type": "ReservationQueryCommitReservation"
})



headers_commit_reservation = {
  'Accept': 'application/json',
  'XAUTH_TRAVELPORT_ACCESSGROUP': os.getenv("TRAVELPORT_ACCESS_GROUP"),
  'Content-Version': '11',
  'Content-Type': 'application/json',
  'Authorization': f'Bearer {token}'
}
response = requests.request("POST", url_to_commit_reservation, headers=headers_commit_reservation, data=payload_commit_reservation)

print(response.text)


# save response to a json file
with open("final_reservation_response.json", "w") as json_file:
    json.dump(response.json(), json_file)

# print locator PNR
print(response.json().get("ReservationResponse", {}).get("Receipt", {}).get("Confirmation", {}).get("Locator", {}).get("value", ""))




# %%
response = requests.request("POST", url_to_commit_reservation, headers=headers_commit_reservation, data=payload_commit_reservation)


# %%
# print(response.json().get("ReservationResponse", {}).get("Receipt", {}).get("Confirmation", {}).get("Locator", {}).get("value", ""))
print(response.json().get("ReservationResponse", {}).get("Receipt", {}))

# %% [markdown]
# ### Ticket

# %% [markdown]
# 1. Initiate workbench

# %%
import requests
import json
import os

# %%
pnr_locator = "D72LVG"

# %%


url = f"https://api.pp.travelport.com/11/air/book/session/reservationworkbench/buildfromlocator?Locator={pnr_locator}"

payload = ""
headers = {
  'XAUTH_TRAVELPORT_ACCESSGROUP': os.getenv("TRAVELPORT_ACCESS_GROUP"),
  'Accept': 'application/json'
}

response = requests.request("POST", url, headers=headers, data=payload)

print(response.text)


# %%
workbench_token = ""

# %% [markdown]
# 2. Add Form of Payment

# %%
import requests
import json

url = "https://api.pp.travelport.com/11/air/payment/reservationworkbench//formofpayment"

payload = json.dumps({
  "@type": "FormOfPaymentPaymentCard",
  "id": "formOfPayment_1",
  "FormOfPaymentRef": "formOfPayment_1",
  "PaymentCard": {
    "@type": "PaymentCardDetail",
    "id": "paymentCard_4",
    "expireDate": "1228",
    "CardType": "Credit",
    "CardCode": "VI",
    "CardHolderName": "JANE DOE",
    "approvalCode": "123456",
    "CardNumber": {
      "@type": "CardNumber",
      "PlainText": "4987654321098769"
    },
    "SeriesCode": {
      "PlainText": "123"
    }
  }
})
headers = {
  'Accept': 'application/json',
  'Content-Type': 'application/json',
  'XAUTH_TRAVELPORT_ACCESSGROUP': os.getenv("TRAVELPORT_ACCESS_GROUP"),
  'Content-Version': '11',
  'Authorization': f'Bearer {token}'
}

response = requests.request("POST", url, headers=headers, data=payload)

print(response.text)


# %% [markdown]
# 3. Apply Payment

# %%
import requests
import json

# %%

# url = "https://{{baseURL}}/{{version}}/air/paymentoffer/reservationworkbench/{1546cc57-c5c3-4670-b555-fed35dd69ddf}/payments"
url = f"https://api.pp.travelport.com/11/air/paymentoffer/reservationworkbench/{workbench_token}/payments"


payload = json.dumps({
  "@type": "Payment",
  "id": "payment_1",
  "Identifier": {
    "authority": "Travelport",
    "value": "A0656EFF-FAF4-456F-B061-0161008D6A5E"
  },
  "Amount": {
    "code": "USD",
    "minorUnit": 2,
    "currencySource": "Charged",
    "value": 943.6
  },
  "FormOfPaymentIdentifier": {
    "id": "formOfPayment_1",
    "FormOfPaymentRef": "formOfPayment_1",
    "Identifier": {
      "authority": "Travelport",
      "value": "1546cc57-c5c3-4670-b555-fed35dd69ddf"
    }
  },
  "OfferIdentifier": [
    {
      "id": "offer_1",
      "offerRef": "offer_1",
      "Identifier": {
        "authority": "Travelport",
        "value": "9829d223-66dc-4590-8a8e-66a1669f8b00"
      }
    }
  ]
})
headers = {
  'Content-Type': 'application/json',
  'XAUTH_TRAVELPORT_ACCESSGROUP': os.getenv("TRAVELPORT_ACCESS_GROUP"),
  'Accept': 'application/json',
  'Content-Version': '11'
}

response = requests.request("POST", url, headers=headers, data=payload)

print(response.text)


# %% [markdown]
# 4. Review before genrating

# %%
import requests
import json

# %%

# url = "https://{{baseURL}}/{{version}}/air/book/session/reservationworkbench/1546cc57-c5c3-4670-b555-fed35dd69ddf"

url = f"https://api.pp.travelport.com/11/air/book/session/reservationworkbench/{workbench_token}"


payload = {}
headers = {
  'Accept': 'application/json',
  'Content-Type': 'application/json',
  'XAUTH_TRAVELPORT_ACCESSGROUP': os.getenv("TRAVELPORT_ACCESS_GROUP")
}

response = requests.request("GET", url, headers=headers, data=payload)

print(response.text)


# %% [markdown]
# 5. Ticket Genration

# %%


url = f"https://api.pp.travelport.com/11/air/book/reservation/reservations/{workbench_token}"

payload = json.dumps({
  "@type": "ReservationQueryCommitReservation"
})
headers = {
  'XAUTH_TRAVELPORT_ACCESSGROUP': os.getenv("TRAVELPORT_ACCESS_GROUP"),
  'Accept': 'application/json',
  'Content-Type': 'application/json',
  'Authorization': f'Bearer {token}',
    'Content-Version': '11'
}

response = requests.request("POST", url, headers=headers, data=payload)

print(response.text)


# %% [markdown]
# 6. Review

# %%


url = f"https://api.pp.travelport.com/11/air/book/reservation/reservations/{pnr_locator}"

payload = {}
headers = {
  'Accept': 'application/json',
  'Content-Type': 'application/json',
  'XAUTH_TRAVELPORT_ACCESSGROUP': os.getenv("TRAVELPORT_ACCESS_GROUP"),
  'Authorization': f'Bearer {token}',
  'Content-Version': '11'
}

response = requests.request("GET", url, headers=headers, data=payload)

print(response.text)


# %%


# %% [markdown]
# 


