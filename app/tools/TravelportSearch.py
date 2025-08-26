from langchain_core.tools import tool
from dotenv import load_dotenv
import os
import requests
from typing import Any, Dict, List, Optional, Tuple

# Import utility functions from the new utils module
try:
    # Try relative import for package usage
    from .travelport_utils import (
        extract_cheapest_one_way_summary,
        extract_cheapest_round_trip_summary
    )
except ImportError:
    # Fall back to absolute import for direct execution
    from travelport_utils import (
        extract_cheapest_one_way_summary,
        extract_cheapest_round_trip_summary
    )

@tool("TravelportSearch")
def TravelportSearch(payload: dict, trip_type: str = "one-way"):
    """This tool calls the travelport rest api to get the cheapest flight possible for the user's given parameters"""
    load_dotenv()  # Reads .env in current directory

    CLIENT_ID       = os.getenv("TRAVELPORT_CLIENT_ID")
    CLIENT_SECRET   = os.getenv("TRAVELPORT_CLIENT_SECRET")
    USERNAME        = os.getenv("TRAVELPORT_USERNAME")
    PASSWORD        = os.getenv("TRAVELPORT_PASSWORD")
    ACCESS_GROUP    = os.getenv("TRAVELPORT_ACCESS_GROUP")

    OAUTH_URL       = "https://oauth.pp.travelport.com/oauth/oauth20/token"
    CATALOG_URL     = "https://api.pp.travelport.com/11/air/catalog/search/catalogproductofferings"

    def fetch_password_token():
        data = {
            "grant_type":    "password",
            "username":      USERNAME,
            "password":      PASSWORD,
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "scope":         "openid"
        }
        resp = requests.post(
            OAUTH_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=data
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    try:
        token = fetch_password_token()
    except Exception as e:
        return {
            "ok": False,
            "error": f"Failed to obtain OAuth token: {str(e)}",
            "summary": None
        }

    headers = {
        "Accept":                       "application/json",
        "Content-Type":                 "application/json",
        "Accept-Encoding":              "gzip, deflate",
        "Cache-Control":                "no-cache",
        "Authorization":                f"Bearer {token}",
        "XAUTH_TRAVELPORT_ACCESSGROUP": ACCESS_GROUP,
        "Accept-Version":               "11",
        "Content-Version":              "11",
    }

    try:
        response = requests.post(CATALOG_URL, headers=headers, json=payload)
        response.raise_for_status()
        resp_json = response.json()
        
        # Extract summary based on trip type
        if trip_type == "one-way":
            summary = extract_cheapest_one_way_summary(resp_json)
        else:
            summary = extract_cheapest_round_trip_summary(resp_json)
        
        # Legacy price extraction for backwards compatibility
        try:
            cheapest_flight_price = resp_json["CatalogProductOfferingsResponse"]["CatalogProductOfferings"]["CatalogProductOffering"][0]["ProductBrandOptions"][0]["ProductBrandOffering"][0]["BestCombinablePrice"]["TotalPrice"]
        except (KeyError, IndexError):
            cheapest_flight_price = None

        return {
            "ok": True,
            "price": cheapest_flight_price,
            "raw": resp_json,
            "summary": summary
        }
        
    except requests.HTTPError as e:
        return {
            "ok": False,
            "error": f"API request failed: {str(e)} - {response.text if 'response' in locals() else 'No response'}",
            "summary": None
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"Unexpected error: {str(e)}",
            "summary": None
        }
