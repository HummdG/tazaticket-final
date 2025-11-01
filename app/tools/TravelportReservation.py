"""
Travelport Reservation Tools - Tools for managing flight reservations with Travelport API
"""

import os
import json
import requests
from datetime import datetime
from langchain_core.tools import tool
from typing import Optional, Dict, Any
from dotenv import load_dotenv
import httpx
import asyncio

# Global client for HTTP requests, same as in TravelportSearch
_limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
_default_timeout = httpx.Timeout(10.0, read=30.0)
_shared_client = None

def _get_shared_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(limits=_limits, timeout=_default_timeout)
    return _shared_client


@tool("TravelportAuthentication")
async def TravelportAuthentication(
    username: Optional[str] = None,
    password: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    scope: str = "openid",
    thread_id: str = "default",
    user_input_text: str = "",
    mode_of_conversation: Optional[str] = None,
    detected_language: str = "en",
):
    """
    Authenticate with Travelport API using OAuth2 to obtain access token.
    
    This tool handles the OAuth2 authentication process with Travelport API.
    It can use environment variables if credentials are not provided explicitly.
    
    Parameters:
    - username: Travelport username (optional, defaults to env var)
    - password: Travelport password (optional, defaults to env var)
    - client_id: OAuth client ID (optional, defaults to env var)
    - client_secret: OAuth client secret (optional, defaults to env var)
    - scope: OAuth scope (optional, defaults to 'openid')
    """
    
    # Use environment variables if not provided
    auth_username = username or os.getenv("TRAVELPORT_USERNAME")
    auth_password = password or os.getenv("TRAVELPORT_PASSWORD")
    auth_client_id = client_id or os.getenv("TRAVELPORT_CLIENT_ID")
    auth_client_secret = client_secret or os.getenv("TRAVELPORT_CLIENT_SECRET")
    
    # Validate required parameters
    if not all([auth_username, auth_password, auth_client_id, auth_client_secret]):
        missing_params = []
        if not auth_username:
            missing_params.append("username")
        if not auth_password:
            missing_params.append("password")
        if not auth_client_id:
            missing_params.append("client_id")
        if not auth_client_secret:
            missing_params.append("client_secret")
        
        return f"❌ Missing required authentication parameters: {', '.join(missing_params)}. Please set environment variables or provide explicit values."
    
    # Build the OAuth token request
    url = "https://oauth.pp.travelport.com/oauth/oauth20/token"
    
    payload = f'grant_type=password&username={auth_username}&password={auth_password}&client_id={auth_client_id}&client_secret={auth_client_secret}&scope={scope}'
    
    headers = {
        'Cache-Control': 'no-cache',
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    
    try:
        response = requests.post(url, headers=headers, data=payload)
        response.raise_for_status()
        
        # Parse the response
        token_data = response.json()
        access_token = token_data.get("access_token")
        
        if not access_token:
            return f"❌ Failed to retrieve access token. Response: {token_data}"
        
        # Store the token in the thread context or return it
        # For now, we just return the token for use in other tools
        return {
            "status": "success",
            "access_token": access_token,
            "token_type": token_data.get("token_type", "Bearer"),
            "expires_in": token_data.get("expires_in"),
            "message": "✅ Successfully authenticated with Travelport API"
        }
        
    except requests.exceptions.HTTPError as e:
        error_msg = f"❌ HTTP error during authentication: {e.response.status_code} - {e.response.text}"
        return error_msg
    except Exception as e:
        error_msg = f"❌ Error during authentication: {str(e)}"
        return error_msg


async def get_auth_token():
    """
    Internal helper function to get authentication token for use in other tools.
    This follows the same authentication approach as TravelportSearch for consistency.
    """
    load_dotenv()  # Ensure we load environment variables
    
    CLIENT_ID = os.getenv("TRAVELPORT_CLIENT_ID")
    CLIENT_SECRET = os.getenv("TRAVELPORT_CLIENT_SECRET")
    USERNAME = os.getenv("TRAVELPORT_USERNAME")
    PASSWORD = os.getenv("TRAVELPORT_PASSWORD")
    OAUTH_URL = "https://oauth.pp.travelport.com/oauth/oauth20/token"
    
    # Validate required parameters
    if not all([CLIENT_ID, CLIENT_SECRET, USERNAME, PASSWORD]):
        missing_params = []
        if not CLIENT_ID:
            missing_params.append("TRAVELPORT_CLIENT_ID")
        if not CLIENT_SECRET:
            missing_params.append("TRAVELPORT_CLIENT_SECRET")
        if not USERNAME:
            missing_params.append("TRAVELPORT_USERNAME")
        if not PASSWORD:
            missing_params.append("TRAVELPORT_PASSWORD")
        
        raise ValueError(f"Missing required environment variables: {', '.join(missing_params)}")
    
    # Make async HTTP request using httpx like TravelportSearch does
    data = {
        "grant_type": "password",
        "username": USERNAME,
        "password": PASSWORD,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "openid"
    }
    
    # Use the same httpx client as TravelportSearch for consistency
    client = _get_shared_client()
    
    try:
        resp = await client.post(
            OAUTH_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=data
        )
        resp.raise_for_status()
        body = resp.json()
        return body["access_token"]
    except httpx.HTTPError as e:
        raise Exception(f"Failed to obtain OAuth token: {str(e)}")
    except Exception as e:
        raise Exception(f"Unexpected error during authentication: {str(e)}")


@tool("TravelportFlightSearch")
async def TravelportFlightSearch(
    origin: str,
    destination: str,
    departure_date: str,
    num_passengers: int = 1,
    passenger_type: str = "ADT",  # ADT for Adult, CHD for Child, INF for Infant
    preferred_carriers: Optional[list] = None,
    content_source: str = "GDS",
    max_upsells: int = 4,
    thread_id: str = "default",
    user_input_text: str = "",
    mode_of_conversation: Optional[str] = None,
    detected_language: str = "en",
):
    """
    Search for available flights using Travelport API.
    
    Parameters:
    - origin: Origin airport code (e.g. 'LHR')
    - destination: Destination airport code (e.g. 'DXB')
    - departure_date: Departure date in YYYY-MM-DD format (e.g. '2025-12-20')
    - num_passengers: Number of passengers (default 1)
    - passenger_type: Passenger type code (default 'ADT' for Adult)
    - preferred_carriers: List of preferred carrier codes (optional)
    - content_source: Content source (default 'GDS')
    - max_upsells: Maximum number of upsells to return (default 4)
    """
    
    try:
        # Get authentication token using the same method as TravelportSearch
        access_token = await get_auth_token()
    except Exception as e:
        return f"❌ Failed to authenticate: {str(e)}"
    
    # Prepare the search payload
    search_dict = {
        "@type": "CatalogProductOfferingsQueryRequest",
        "CatalogProductOfferingsRequest": {
            "@type": "CatalogProductOfferingsRequestAir",
            "maxNumberOfUpsellsToReturn": max_upsells,
            "contentSourceList": [content_source],
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
                    "departureDate": departure_date,
                    "From": {
                        "value": origin
                    },
                    "To": {
                        "value": destination
                    }
                }
            ],
            "SearchModifiersAir": {
                "@type": "SearchModifiersAir",
                "CarrierPreference": [
                    {
                        "@type": "CarrierPreference",
                        "preferenceType": "Preferred",
                        "carriers": preferred_carriers or []
                    }
                ]
            }
        }
    }
    
    # Prepare headers
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'XAUTH_TRAVELPORT_ACCESSGROUP': os.getenv("TRAVELPORT_ACCESS_GROUP"),
        'Accept-Version': '11',
        'Content-Version': '11',
        'taxBreakDown': 'true',
        "Authorization": f"Bearer {access_token}",
    }
    
    url = "https://api.pp.travelport.com/11/air/catalog/search/catalogproductofferings"
    
    try:
        # Use httpx client like TravelportSearch does
        client = _get_shared_client()
        response = await client.post(url, headers=headers, json=search_dict)
        response.raise_for_status()
        
        search_response = response.json()
        
        # Process and format the results
        offers = search_response.get("CatalogProductOfferingsResponse", {}).get("CatalogProductOfferings", {}).get("CatalogProductOffering", [])
        
        if not offers:
            return "❌ No flight offers found for the specified criteria."
        
        result = f"✅ Found {len(offers)} flight options from {origin} to {destination} on {departure_date}:\n\n"
        
        for i, offer in enumerate(offers[:5], 1):  # Show top 5 offers
            # Extract price info
            price_info = offer.get("ProductBrandOptions", [{}])[0].get("ProductBrandOffering", [{}])[0].get("BestCombinablePrice", {})
            total_price = price_info.get("TotalPrice", "N/A")
            currency = price_info.get("CurrencyCode", {}).get("value", "N/A")
            
            # Extract departure/arrival info
            departure = offer.get("Departure", "N/A")
            arrival = offer.get("Arrival", "N/A")
            
            result += f"{i}. Flight Option {offer.get('id', 'N/A')}\n"
            result += f"   Price: {total_price} {currency}\n"
            result += f"   Route: {departure} → {arrival}\n\n"
        
        result += "💡 Use the TravelportAddOfferToReservation tool to select one of these options for your reservation."
        
        return result
        
    except httpx.HTTPStatusError as e:
        error_msg = f"❌ HTTP error during flight search: {e.response.status_code} - {e.response.text}"
        return error_msg
    except Exception as e:
        error_msg = f"❌ Error during flight search: {str(e)}"
        return error_msg


@tool("TravelportInitiateReservationWorkbench")
async def TravelportInitiateReservationWorkbench(
    thread_id: str = "default",
    user_input_text: str = "",
    mode_of_conversation: Optional[str] = None,
    detected_language: str = "en",
):
    """
    Initiate a reservation workbench to create a new reservation.
    
    This creates a new reservation session with Travelport and returns a unique reservation ID
    that is used for all subsequent reservation operations.
    """
    
    try:
        # Get authentication token using the same method as TravelportSearch
        access_token = await get_auth_token()
    except Exception as e:
        return f"❌ Failed to authenticate: {str(e)}"
    
    # Prepare the request
    url = "https://api.pp.travelport.com/11/air/book/session/reservationworkbench"
    
    payload = json.dumps({
        "@type": "ReservationID",
        "ReservationID": {}
    })
    
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'XAUTH_TRAVELPORT_ACCESSGROUP': os.getenv("TRAVELPORT_ACCESS_GROUP"),
        'Content-Version': '11',
        'Authorization': f'Bearer {access_token}'
    }
    
    try:
        # Use httpx client like TravelportSearch does
        client = _get_shared_client()
        response = await client.post(url, headers=headers, json=json.loads(payload))
        response.raise_for_status()
        
        reservation_response = response.json()
        reservation_id = reservation_response.get("ReservationResponse", {}).get("Reservation", {}).get("Identifier", {}).get("value")
        
        if not reservation_id:
            return f"❌ Failed to create reservation workbench. Response: {reservation_response}"
        
        return {
            "status": "success",
            "reservation_id": reservation_id,
            "message": f"✅ Successfully initiated reservation workbench with ID: {reservation_id}"
        }
        
    except httpx.HTTPStatusError as e:
        error_msg = f"❌ HTTP error during reservation workbench initiation: {e.response.status_code} - {e.response.text}"
        return error_msg
    except Exception as e:
        error_msg = f"❌ Error during reservation workbench initiation: {str(e)}"
        return error_msg


@tool("TravelportAddOfferToReservation")
async def TravelportAddOfferToReservation(
    reservation_id: str,
    offer_id: str,
    flight_number: str,
    carrier: str,
    departure_date: str,
    departure_time: str,
    arrival_date: str,
    arrival_time: str,
    departure_airport: str,
    arrival_airport: str,
    class_of_service: str,
    cabin: str,
    segment_sequence: int,
    brand_tier: int,
    availability_source_code: str,
    content_source: str,
    num_passengers: int = 1,
    passenger_type: str = "ADT",  # ADT for Adult, CHD for Child, INF for Infant
    thread_id: str = "default",
    user_input_text: str = "",
    mode_of_conversation: Optional[str] = None,
    detected_language: str = "en",
):
    """
    Add a selected flight offer to the reservation workbench.
    
    Parameters:
    - reservation_id: The reservation workbench ID
    - offer_id: The specific offer ID selected
    - flight_number: Flight number (e.g. '30')
    - carrier: Carrier code (e.g. 'EK')
    - departure_date: Departure date in YYYY-MM-DD format
    - departure_time: Departure time in HH:MM:SS format
    - arrival_date: Arrival date in YYYY-MM-DD format
    - arrival_time: Arrival time in HH:MM:SS format
    - departure_airport: Departure airport code (e.g. 'LHR')
    - arrival_airport: Arrival airport code (e.g. 'DXB')
    - class_of_service: Class of service code (e.g. 'Y' for economy, 'B' for business)
    - cabin: Cabin type (e.g. 'Economy')
    - segment_sequence: Segment sequence number (e.g. 1)
    - brand_tier: Brand tier number (e.g. 3)
    - availability_source_code: Availability source code (e.g. 'Q')
    - content_source: Content source (e.g. 'GDS')
    - num_passengers: Number of passengers (default 1)
    - passenger_type: Passenger type code (default 'ADT' for Adult)
    """
    
    try:
        # Get authentication token using the same method as TravelportSearch
        access_token = await get_auth_token()
    except Exception as e:
        return f"❌ Failed to authenticate: {str(e)}"
    
    # Prepare the payload to add the offer to reservation
    payload_dict = {
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
                            "brandTier": brand_tier,
                            "AvailabilitySourceCode": availability_source_code,
                            "ContentSource": content_source
                        }
                    ],
                    "sequence": 1
                }
            ]
        }
    }
    
    url = f"https://api.pp.travelport.com/11/air/book/airoffer/reservationworkbench/{reservation_id}/offers/buildfromproducts"
    
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'trackingId': reservation_id,
        'XAUTH_TRAVELPORT_ACCESSGROUP': os.getenv("TRAVELPORT_ACCESS_GROUP"),
        'Content-Version': '11',
        'Authorization': f'Bearer {access_token}'
    }
    
    try:
        # Use httpx client like TravelportSearch does
        client = _get_shared_client()
        response = await client.post(url, headers=headers, json=payload_dict)
        response.raise_for_status()
        
        offer_response = response.json()
        offer_ids = offer_response.get("OfferListResponse", {}).get("OfferID", [])
        
        if not offer_ids:
            return f"❌ Failed to add offer to reservation. Response: {offer_response}"
        
        return {
            "status": "success",
            "message": f"✅ Successfully added offer to reservation {reservation_id}",
            "offer_ids": [offer_id.get("Identifier", {}).get("value") for offer_id in offer_ids]
        }
        
    except httpx.HTTPStatusError as e:
        error_msg = f"❌ HTTP error during adding offer to reservation: {e.response.status_code} - {e.response.text}"
        return error_msg
    except Exception as e:
        error_msg = f"❌ Error during adding offer to reservation: {str(e)}"
        return error_msg


@tool("TravelportAddTravelerToReservation")
async def TravelportAddTravelerToReservation(
    reservation_id: str,
    first_name: str,
    last_name: str,
    gender: str,
    birth_date: str,  # Format: YYYY-MM-DD
    phone_number: str,
    email: str,
    passport_number: str,
    passport_expiry: str,  # Format: YYYY-MM-DD
    passport_issuing_country: str,
    passenger_type_code: str = "ADT",
    city_code: str = "ORD",
    phone_role: str = "Home",
    thread_id: str = "default",
    user_input_text: str = "",
    mode_of_conversation: Optional[str] = None,
    detected_language: str = "en",
):
    """
    Add traveler information to the reservation.
    
    Parameters:
    - reservation_id: The reservation workbench ID
    - first_name: Traveler's first name
    - last_name: Traveler's last name
    - gender: Traveler's gender (Male/Female/Other)
    - birth_date: Birth date in YYYY-MM-DD format
    - phone_number: Phone number
    - email: Email address
    - passport_number: Passport number
    - passport_expiry: Passport expiry date in YYYY-MM-DD format
    - passport_issuing_country: Passport issuing country code (e.g. 'US')
    - passenger_type_code: Passenger type (default 'ADT' for Adult)
    - city_code: City code for phone (default 'ORD')
    - phone_role: Role of phone number (default 'Home')
    """
    
    try:
        # Get authentication token using the same method as TravelportSearch
        access_token = await get_auth_token()
    except Exception as e:
        return f"❌ Failed to authenticate: {str(e)}"
    
    # Prepare the traveler payload
    payload = {
        "@type": "Traveler",
        "gender": gender,
        "birthDate": birth_date,
        "id": "trav_1",
        "passengerTypeCode": passenger_type_code,
        "PersonName": {
            "@type": "PersonNameDetail",
            "Given": first_name,
            "Surname": last_name
        },
        "Telephone": [
            {
                "@type": "Telephone",
                "countryAccessCode": "1",  # Assuming US country code, could be parameterized
                "phoneNumber": phone_number,
                "id": "4",
                "cityCode": city_code,
                "role": phone_role
            }
        ],
        "Email": [
            {
                "value": email
            }
        ],
        "TravelDocument": [
            {
                "@type": "TravelDocumentDetail",
                "docNumber": passport_number,
                "docType": "Passport",
                "expireDate": passport_expiry,
                "issueCountry": passport_issuing_country,
                "birthDate": birth_date,
                "Gender": gender,
                "PersonName": {
                    "@type": "PersonName",
                    "Given": first_name,
                    "Surname": last_name
                }
            }
        ]
    }
    
    url = f"https://api.pp.travelport.com/11/air/book/traveler/reservationworkbench/{reservation_id}/travelers"
    
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'XAUTH_TRAVELPORT_ACCESSGROUP': os.getenv("TRAVELPORT_ACCESS_GROUP"),
        'Content-Version': '11',
        'Authorization': f'Bearer {access_token}'
    }
    
    try:
        # Use httpx client like TravelportSearch does
        client = _get_shared_client()
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        
        traveler_response = response.json()
        traveler_id = traveler_response.get("TravelerResponse", {}).get("Traveler", {}).get("Identifier", {}).get("value")
        
        if not traveler_id:
            return f"❌ Failed to add traveler to reservation. Response: {traveler_response}"
        
        return {
            "status": "success",
            "traveler_id": traveler_id,
            "message": f"✅ Successfully added traveler {first_name} {last_name} to reservation {reservation_id}"
        }
        
    except httpx.HTTPStatusError as e:
        error_msg = f"❌ HTTP error during adding traveler to reservation: {e.response.status_code} - {e.response.text}"
        return error_msg
    except Exception as e:
        error_msg = f"❌ Error during adding traveler to reservation: {str(e)}"
        return error_msg


@tool("TravelportCommitReservation")
async def TravelportCommitReservation(
    reservation_id: str,
    thread_id: str = "default",
    user_input_text: str = "",
    mode_of_conversation: Optional[str] = None,
    detected_language: str = "en",
):
    """
    Commit the reservation to finalize the booking.
    
    This finalizes the reservation and returns the complete reservation details
    with booking reference.
    
    Parameters:
    - reservation_id: The reservation workbench ID to commit
    """
    
    try:
        # Get authentication token using the same method as TravelportSearch
        access_token = await get_auth_token()
    except Exception as e:
        return f"❌ Failed to authenticate: {str(e)}"
    
    url = f"https://api.pp.travelport.com/11/air/book/reservation/reservations/{reservation_id}"
    
    payload = {
        "@type": "ReservationQueryCommitReservation"
    }
    
    headers = {
        'Accept': 'application/json',
        'XAUTH_TRAVELPORT_ACCESSGROUP': os.getenv("TRAVELPORT_ACCESS_GROUP"),
        'Content-Version': '11',
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {access_token}'
    }
    
    try:
        # Use httpx client like TravelportSearch does
        client = _get_shared_client()
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        
        commit_response = response.json()
        
        # Extract reservation details
        reservation_details = commit_response.get("ReservationResponse", {}).get("Reservation", {})
        offers = reservation_details.get("Offer", [])
        
        if not offers:
            return f"❌ No offers found in committed reservation. Response: {commit_response}"
        
        # Format the result
        result = f"✅ Reservation committed successfully!\n"
        result += f"🎫 Reservation ID: {reservation_id}\n\n"
        
        for offer in offers:
            offer_id = offer.get("Identifier", {}).get("value", "N/A")
            product = offer.get("Product", [{}])[0]
            flight_segment = product.get("FlightSegment", [{}])[0]
            flight = flight_segment.get("Flight", {})
            
            # Extract flight details
            departure_details = flight.get("Departure", {})
            arrival_details = flight.get("Arrival", {})
            
            result += f"📍 Offer ID: {offer_id}\n"
            result += f"✈️ Flight: {flight.get('carrier', 'N/A')}{flight.get('number', 'N/A')}\n"
            result += f"🛫 {departure_details.get('location', 'N/A')} at {departure_details.get('time', 'N/A')} on {departure_details.get('date', 'N/A')}\n"
            result += f"🛬 {arrival_details.get('location', 'N/A')} at {arrival_details.get('time', 'N/A')} on {arrival_details.get('date', 'N/A')}\n"
            
            # Extract price details
            price_details = offer.get("Price", {})
            total_price = price_details.get("TotalPrice", "N/A")
            currency = price_details.get("CurrencyCode", {}).get("value", "N/A")
            
            result += f"💰 Total Price: {total_price} {currency}\n\n"
        
        result += "🎉 Your reservation is now confirmed! The booking reference has been generated."
        
        return result
        
    except httpx.HTTPStatusError as e:
        error_msg = f"❌ HTTP error during reservation commit: {e.response.status_code} - {e.response.text}"
        return error_msg
    except Exception as e:
        error_msg = f"❌ Error during reservation commit: {str(e)}"
        return error_msg
    

@tool("TravelportFullReservation")
async def TravelportFullReservation(
    token: Optional[str] = None,
    reserve_payload: Optional[dict] = None,
    traveler_payload: Optional[dict] = None,
    thread_id: str = "default",
):
    """
    Perform full Travelport booking flow in one step:
    1️⃣ Initiate reservation workbench
    2️⃣ Add selected offer (build from products)
    3️⃣ Add traveler information
    4️⃣ Commit reservation and return PNR locator

    Args:
        token (str): OAuth access token (if not provided, auto-fetched)
        reserve_payload (dict): Offer payload (from search results)
        traveler_payload (dict): Traveler info payload
        thread_id (str): conversation thread identifier

    Returns:
        dict: { status, reservation_id, locator, message, full_response }
    """
    load_dotenv()

    # --- Step 0: Auth ---
    try:
        if not token:
            token = await get_auth_token()
    except Exception as e:
        return {"status": "error", "message": f"❌ Auth failed: {e}"}

    access_group = os.getenv("TRAVELPORT_ACCESS_GROUP")
    client = _get_shared_client()

    # --- Step 1: Create Workbench ---
    try:
        url_wb = "https://api.pp.travelport.com/11/air/book/session/reservationworkbench"
        wb_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "XAUTH_TRAVELPORT_ACCESSGROUP": access_group,
            "Content-Version": "11",
            "Authorization": f"Bearer {token}",
        }
        wb_payload = {"@type": "ReservationID", "ReservationID": {}}
        resp_wb = await client.post(url_wb, headers=wb_headers, json=wb_payload)
        resp_wb.raise_for_status()
        reservation_id = (
            resp_wb.json()
            .get("ReservationResponse", {})
            .get("Reservation", {})
            .get("Identifier", {})
            .get("value")
        )
        if not reservation_id:
            return {"status": "error", "message": "❌ Failed to get reservation_id"}
    except Exception as e:
        return {"status": "error", "message": f"❌ Reservation init failed: {e}"}

    # --- Step 2: Add Offer ---
    try:
        url_offer = f"https://api.pp.travelport.com/11/air/book/airoffer/reservationworkbench/{reservation_id}/offers/buildfromproducts"
        offer_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "trackingId": reservation_id,
            "XAUTH_TRAVELPORT_ACCESSGROUP": access_group,
            "Content-Version": "11",
            "Authorization": f"Bearer {token}",
        }
        resp_offer = await client.post(url_offer, headers=offer_headers, json=reserve_payload)
        resp_offer.raise_for_status()
    except Exception as e:
        return {
            "status": "error",
            "reservation_id": reservation_id,
            "message": f"❌ Failed to add offer: {e}",
        }

    # --- Step 3: Add Traveler ---
    try:
        url_trav = f"https://api.pp.travelport.com/11/air/book/traveler/reservationworkbench/{reservation_id}/travelers"
        trav_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "XAUTH_TRAVELPORT_ACCESSGROUP": access_group,
            "Content-Version": "11",
            "Authorization": f"Bearer {token}",
        }
        resp_trav = await client.post(url_trav, headers=trav_headers, json=traveler_payload)
        resp_trav.raise_for_status()
    except Exception as e:
        return {
            "status": "error",
            "reservation_id": reservation_id,
            "message": f"❌ Failed to add traveler: {e}",
        }

    # --- Step 4: Commit Reservation ---
    try:
        url_commit = f"https://api.pp.travelport.com/11/air/book/reservation/reservations/{reservation_id}"
        commit_headers = {
            "Accept": "application/json",
            "XAUTH_TRAVELPORT_ACCESSGROUP": access_group,
            "Content-Version": "11",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        commit_payload = {"@type": "ReservationQueryCommitReservation"}
        resp_commit = await client.post(url_commit, headers=commit_headers, json=commit_payload)
        resp_commit.raise_for_status()
        data_commit = resp_commit.json()
        locator = (
            data_commit.get("ReservationResponse", {})
            .get("Receipt", {})
            .get("Confirmation", {})
            .get("Locator", {})
            .get("value", "")
        )
        # Save locally for debug
        with open("final_reservation_response.json", "w") as f:
            json.dump(data_commit, f, indent=2)
        return {
            "status": "success",
            "reservation_id": reservation_id,
            "locator": locator,
            "message": f"✅ Reservation committed successfully. Locator (PNR): {locator}",
            "full_response": data_commit,
        }
    except Exception as e:
        return {
            "status": "error",
            "reservation_id": reservation_id,
            "message": f"❌ Failed to commit reservation: {e}",
        }
