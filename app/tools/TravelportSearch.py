import json
from langchain_core.tools import tool
from dotenv import load_dotenv
import os
import httpx
import asyncio
from typing import Any, Dict, List, Optional, Tuple

# Import utility functions
try:
    from .travelport_utils import (
        extract_cheapest_one_way_summary,
        extract_cheapest_round_trip_summary
    )
except ImportError:
    from travelport_utils import (
        extract_cheapest_one_way_summary,
        extract_cheapest_round_trip_summary
    )

# Import the new travelport parser
try:
    from .travelport_parser import resolve_references
except ImportError:
    from travelport_parser import resolve_references

# Done: create a shared httpx.AsyncClient for pooling
_limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)  # tune as needed
_default_timeout = httpx.Timeout(10.0, read=30.0)  # adjust
_shared_client: Optional[httpx.AsyncClient] = None

def _get_shared_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(limits=_limits, timeout=_default_timeout)
    return _shared_client

def run_async(coro):
    """Run async code safely from sync context, avoiding nested loop crashes."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No event loop running → safe to use asyncio.run
        return asyncio.run(coro)
    else:
        # Already inside async loop → schedule and wait
        return loop.run_until_complete(coro)

async def fetch_password_token(CLIENT_ID, CLIENT_SECRET, USERNAME, PASSWORD, OAUTH_URL):
    """Async helper to fetch OAuth password token"""
    data = {
        "grant_type":    "password",
        "username":      USERNAME,
        "password":      PASSWORD,
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope":         "openid"
    }
    client = _get_shared_client()
    resp = await client.post(
        OAUTH_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=data
    )
    resp.raise_for_status()
    body = resp.json()
    return body["access_token"]

async def fetch_catalog(CATALOG_URL, headers, payload):
    """Async helper to call catalog endpoint"""
    client = _get_shared_client()
    response = await client.post(CATALOG_URL, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

@tool("TravelportSearch")
async def TravelportSearch(payload: dict, trip_type: str = "one-way"):

    """This tool calls the travelport rest api to get the cheapest flight possible for the user's given parameters"""
    print(f"[TravelportDebug] 🛰️ TravelportSearch called with trip_type={trip_type}")
    print(f"[TravelportDebug] Payload keys: {list(payload.keys())[:10]}")
    load_dotenv()  # Reads .env in current directory

    CLIENT_ID       = os.getenv("TRAVELPORT_CLIENT_ID")
    CLIENT_SECRET   = os.getenv("TRAVELPORT_CLIENT_SECRET")
    USERNAME        = os.getenv("TRAVELPORT_USERNAME")
    PASSWORD        = os.getenv("TRAVELPORT_PASSWORD")
    ACCESS_GROUP    = os.getenv("TRAVELPORT_ACCESS_GROUP")

    OAUTH_URL       = "https://oauth.pp.travelport.com/oauth/oauth20/token"
    CATALOG_URL     = "https://api.pp.travelport.com/11/air/catalog/search/catalogproductofferings"

    # Step 1: Get token
    try:
        token = await fetch_password_token(CLIENT_ID, CLIENT_SECRET, USERNAME, PASSWORD, OAUTH_URL)
    except httpx.HTTPError as e:
        return {
            "ok": False,
            "error": f"Failed to obtain OAuth token: {str(e)}",
            "summary": None
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"Failed to obtain OAuth token (unexpected): {str(e)}",
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

    # Step 2: Call catalog
    try:
        resp_json = await fetch_catalog(CATALOG_URL, headers, payload)
        
        # Apply the reference resolver to enrich the response
        resp_enriched = resolve_references(resp_json)
        
        try:
            print("[TravelportDebug] ✅ Travelport responded:", json.dumps(resp_enriched)[:800])
        except Exception as e:
            print("[TravelportDebug] ⚠️ Failed to print Travelport raw response:", e)


        # Extract summary
        if trip_type == "one-way":
            summary = extract_cheapest_one_way_summary(resp_enriched)
        else:
            summary = extract_cheapest_round_trip_summary(resp_enriched)

        # Legacy price extraction
        try:
            cheapest_flight_price = resp_enriched["CatalogProductOfferingsResponse"]["CatalogProductOfferings"]["CatalogProductOffering"][0]["ProductBrandOptions"][0]["ProductBrandOffering"][0]["BestCombinablePrice"]["TotalPrice"]
        except (KeyError, IndexError):
            cheapest_flight_price = None
        
        print(f"[TravelportDebug] 🛰️ TravelportSearch called with trip_type={trip_type}")
        print(f"[TravelportDebug] Payload keys: {list(payload.keys())[:10]}")
        return {
            "ok": True,
            "price": cheapest_flight_price,
            "raw": resp_enriched,
            "summary": summary
        }

    except httpx.HTTPStatusError as e:
        return {
            "ok": False,
            "error": f"API request failed: {str(e)} - response: {e.response.text if hasattr(e, 'response') else 'n/a'}",
            "summary": None
        }
    except httpx.HTTPError as e:
        return {
            "ok": False,
            "error": f"HTTP error: {str(e)}",
            "summary": None
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"Unexpected error: {str(e)}",
            "summary": None
        }
