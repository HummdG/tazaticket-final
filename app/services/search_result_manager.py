"""
Search Result Manager - Handles storage, retrieval, and formatting of Travelport search results
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import redis.asyncio as redis


@dataclass
class FlightOption:
    """Represents a single flight option from search results"""
    id: str
    departure: str
    arrival: str
    departure_time: str
    arrival_time: str
    duration: str
    airline: str
    flight_number: str
    aircraft: str
    price: float
    currency: str
    cabin_class: str
    stops: int
    baggage_info: Dict[str, Any]
    penalties: Dict[str, Any]
    raw_data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SearchResult:
    """Represents a complete search result"""
    search_id: str
    wa_id: str
    thread_id: str
    origin: str
    destination: str
    search_date: str
    trip_type: str
    passengers: int
    flight_options: List[FlightOption]
    search_timestamp: str
    expires_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "search_id": self.search_id,
            "wa_id": self.wa_id,
            "thread_id": self.thread_id,
            "origin": self.origin,
            "destination": self.destination,
            "search_date": self.search_date,
            "trip_type": self.trip_type,
            "passengers": self.passengers,
            "flight_options": [option.to_dict() for option in self.flight_options],
            "search_timestamp": self.search_timestamp,
            "expires_at": self.expires_at
        }


import boto3
from botocore.exceptions import ClientError


class SearchResultManager:
    """Manages search results with Redis storage and retrieval"""

    def __init__(self):
        self.redis_conn = None
        self.result_ttl = 3600 * 24  # 24 hours
        self.max_cache = 10  # Maximum number of searches to keep in Redis per user
        self.dynamo_table = None  # Will be initialized when needed

    def _get_dynamo_table(self):
        """Initialize and return DynamoDB table resource"""
        if self.dynamo_table is None:
            # Initialize DynamoDB resource - using environment variables for credentials
            dynamodb = boto3.resource('dynamodb')
            self.dynamo_table = dynamodb.Table('TravelportSearchResults')  # Replace with your actual table name
        return self.dynamo_table

    async def get_connection(self):
        """Get Redis connection"""
        if self.redis_conn is None:
            from ..langgraph.redis_manager import redis_manager
            self.redis_conn = await redis_manager.get_connection()
        return self.redis_conn

    async def store_search_result(self, wa_id: str, thread_id: str, search_data: Dict[str, Any]) -> str:
        """Store search result and return search_id"""
        search_id = str(uuid.uuid4())

        # Parse Travelport response into structured format
        flight_options = self._parse_flight_options(search_data)

        # Create search result object
        search_result = SearchResult(
            search_id=search_id,
            wa_id=wa_id,
            thread_id=thread_id,
            origin=search_data.get("origin", ""),
            destination=search_data.get("destination", ""),
            search_date=search_data.get("search_date", ""),
            trip_type=search_data.get("trip_type", "one-way"),
            passengers=search_data.get("passengers", 1),
            flight_options=flight_options,
            search_timestamp=datetime.now(timezone.utc).isoformat(),
            expires_at=datetime.now(timezone.utc).timestamp() + self.result_ttl
        )

        # Store in Redis
        redis_conn = await self.get_connection()
        result_key = f"search_result:{search_id}"
        user_search_key = f"user_searches:{wa_id}"
        user_search_list_key = f"user_search_list:{wa_id}"

        # Store search result
        await redis_conn.setex(
            result_key,
            self.result_ttl,
            json.dumps(search_result.to_dict(), indent=2)
        )

        # Add to user's search history
        await redis_conn.lpush(user_search_list_key, result_key)
        
        # If list length > self.max_cache:
        if await redis_conn.llen(user_search_list_key) > self.max_cache:
            old_key = await redis_conn.rpop(user_search_list_key)
            if old_key:
                old_data = await redis_conn.get(old_key)
                if old_data:
                    # push to DynamoDB
                    try:
                        dynamo_table = self._get_dynamo_table()
                        dynamo_table.put_item(Item=json.loads(old_data))
                        await redis_conn.delete(old_key)
                    except ClientError as e:
                        print(f"[SearchResultManager] Failed to store in DynamoDB: {e}")
                        # Restore the key to the list if DynamoDB storage fails
                        await redis_conn.lpush(user_search_list_key, old_key)

        # Store latest search for thread
        thread_search_key = f"thread_latest_search:{thread_id}"
        await redis_conn.setex(thread_search_key, self.result_ttl, search_id)
        
        # Optional: mark completed bulk searches for Dynamo flush
        # Check if this was a bulk search (indicated by multiple dates or bulk-related search type)
        search_data_str = json.dumps(search_data)
        if "bulk-search" in search_data.get("trip_type", "") or len(search_data.get("raw_response", {}).get("ResolvedOfferings", [])) > 5:
            try:
                dynamo_table = self._get_dynamo_table()
                dynamo_table.put_item(Item=search_result.to_dict())
                print(f"[SearchResultManager] Bulk search {search_id} persisted to DynamoDB")
            except Exception as e:
                print(f"[SearchResultManager] DynamoDB persist failed: {e}")

        print(f"[SearchResultManager] Stored search result {search_id} for user {wa_id}")
        return search_id

    def _parse_flight_options(self, search_data: Dict[str, Any]) -> List[FlightOption]:
        """Parse Travelport response into structured flight options"""
        flight_options = []

        try:
            response = search_data.get("raw_response", {})
            
            # Check for pre-resolved offerings first and prefer them
            resolved_offers = response.get("ResolvedOfferings", [])
            if resolved_offers:
                offerings = resolved_offers  # prefer pre-resolved structure
            else:
                catalog_offerings = response.get("CatalogProductOfferingsResponse", {}).get("CatalogProductOfferings", {})
                if not catalog_offerings.get("CatalogProductOffering"):
                    return flight_options
                offerings = catalog_offerings["CatalogProductOffering"]

            for offering in offerings:
                try:
                    # Check if this is a resolved offering (has already been processed by travelport_parser)
                    if "ProductBrandOptions" in offering and len(offering["ProductBrandOptions"]) > 0 and "brand_name" in offering["ProductBrandOptions"][0]:
                        # This is a resolved offering from travelport_parser
                        for pbo_resolved in offering["ProductBrandOptions"]:
                            # Extract flight details from resolved offering
                            # For resolved offerings, we need to get departure/arrival from flight details
                            flight_detail = pbo_resolved.get("flight_details", [{}])[0] if pbo_resolved.get("flight_details") else {}
                            departure = flight_detail.get("FlightDetail", {}).get("Departure", {}).get("airport", "") if flight_detail else ""
                            arrival = flight_detail.get("FlightDetail", {}).get("Arrival", {}).get("airport", "") if flight_detail else ""
                            
                            # Use data from resolved offering
                            total_price = pbo_resolved.get("price", 0)
                            currency = pbo_resolved.get("currency", "EUR")
                            
                            # Extract flight information from resolved flight details
                            flight_refs = pbo_resolved.get("flightRefs", [])
                            if not flight_refs:
                                continue
                            
                            # Use the first flight for basic details
                            flight_detail = pbo_resolved.get("flight_details", [{}])[0] if pbo_resolved.get("flight_details") else {}
                            
                            # Create flight option
                            flight_option = FlightOption(
                                id=str(uuid.uuid4()),
                                departure=departure,
                                arrival=arrival,
                                departure_time=flight_detail.get("Departure", {}).get("time", "") if flight_detail else "",
                                arrival_time=flight_detail.get("Arrival", {}).get("time", "") if flight_detail else "",
                                duration=flight_detail.get("duration", "") if flight_detail else "",
                                airline=flight_detail.get("carrier", "") if flight_detail else "",
                                flight_number=flight_detail.get("number", "") if flight_detail else "",
                                aircraft=flight_detail.get("equipment", "") if flight_detail else "",
                                price=float(total_price) if total_price else 0.0,
                                currency=currency,
                                cabin_class=pbo_resolved.get("cabin_class", "Economy"),
                                stops=self._calculate_stops(flight_refs),
                                baggage_info=self._extract_baggage_info_from_resolved(pbo_resolved),
                                penalties=self._extract_penalties_from_resolved(pbo_resolved),
                                raw_data={
                                    "offering": offering,
                                    "brand_offering": pbo_resolved,
                                    "flight_refs": flight_refs
                                }
                            )

                            flight_options.append(flight_option)
                    else:
                        # This is the original offering structure
                        # Extract flight details
                        departure = offering.get("Departure", "")
                        arrival = offering.get("Arrival", "")

                        # Get product brand options
                        product_options = offering.get("ProductBrandOptions", [])
                        if not product_options:
                            continue

                        for option in product_options:
                            brand_offerings = option.get("ProductBrandOffering", [])
                            if not brand_offerings:
                                continue

                            for brand_offering in brand_offerings:
                                # Extract price information
                                price_detail = brand_offering.get("BestCombinablePrice", {})
                                if not price_detail:
                                    continue

                                total_price = price_detail.get("TotalPrice", 0)
                                currency = price_detail.get("CurrencyCode", {}).get("value", "EUR")

                                # Extract flight information
                                flight_refs = option.get("flightRefs", [])
                                if not flight_refs:
                                    continue

                                # Get flight details from reference list - use the first flight's details for basic info
                                flight_details = self._get_flight_details(response, flight_refs[0])

                                # Get departure and arrival from the offering itself if not already set from the offering level
                                offering_departure = offering.get("Departure", "")
                                offering_arrival = offering.get("Arrival", "")
                                departure = departure or offering_departure
                                arrival = arrival or offering_arrival

                                # Create flight option
                                flight_option = FlightOption(
                                    id=str(uuid.uuid4()),
                                    departure=departure,
                                    arrival=arrival,
                                    departure_time=flight_details.get("departure_time", ""),
                                    arrival_time=flight_details.get("arrival_time", ""),
                                    duration=flight_details.get("duration", ""),
                                    airline=flight_details.get("airline", ""),
                                    flight_number=flight_details.get("flight_number", ""),
                                    aircraft=flight_details.get("aircraft", ""),
                                    price=float(total_price),
                                    currency=currency,
                                    cabin_class=self._extract_cabin_class(brand_offering),
                                    stops=self._calculate_stops(flight_refs),
                                    baggage_info=self._extract_baggage_info(response, brand_offering),
                                    penalties=self._extract_penalties(response, brand_offering),
                                    raw_data={
                                        "offering": offering,
                                        "brand_offering": brand_offering,
                                        "flight_refs": flight_refs
                                    }
                                )

                                flight_options.append(flight_option)

                except Exception as e:
                    print(f"[SearchResultManager] Error parsing offering: {e}")
                    continue

        except Exception as e:
            print(f"[SearchResultManager] Error parsing search data: {e}")

        return flight_options

    def _get_flight_details(self, response: Dict[str, Any], flight_ref: str) -> Dict[str, str]:
        """Extract flight details from reference list"""
        try:
            # Look for ReferenceList at multiple possible locations
            reference_list = (response.get("CatalogProductOfferingsResponse", {}).get("ReferenceList", []) or 
                              response.get("ReferenceList", []))
            flights = None

            for ref_item in reference_list:
                # Check both typed and untyped ReferenceList entries
                if ref_item.get("@type") == "ReferenceListFlight" or "Flight" in ref_item:
                    flights = ref_item.get("Flight", [])
                    break

            if not flights:
                return {}

            for flight in flights:
                if flight.get("id") == flight_ref:
                    flight_detail = flight.get("FlightDetail", {})
                    return {
                        "departure_time": flight_detail.get("Departure", {}).get("time", ""),
                        "arrival_time": flight_detail.get("Arrival", {}).get("time", ""),
                        "duration": flight_detail.get("duration", ""),
                        "airline": flight_detail.get("carrier", ""),
                        "flight_number": flight_detail.get("number", ""),
                        "aircraft": flight_detail.get("equipment", "")
                    }

        except Exception as e:
            print(f"[SearchResultManager] Error getting flight details: {e}")

        return {}

    def _extract_cabin_class(self, brand_offering: Dict[str, Any]) -> str:
        """Extract cabin class from brand offering"""
        try:
            products = brand_offering.get("Product", [])
            if products:
                product = products[0]
                flight_product = product.get("FlightProduct", [])
                if flight_product:
                    return flight_product[0].get("cabin", "Economy")
        except:
            pass
        return "Economy"

    def _calculate_stops(self, flight_refs: List[str]) -> int:
        """Calculate number of stops from flight references"""
        return max(0, len(flight_refs) - 1)

    def _extract_baggage_info(self, response: Dict[str, Any], brand_offering: Dict[str, Any]) -> Dict[str, Any]:
        """Extract baggage information"""
        try:
            terms_ref = brand_offering.get("TermsAndConditions", {}).get("termsAndConditionsRef", "")
            if not terms_ref:
                return {}

            # Find matching terms and conditions
            reference_list = response.get("ReferenceList", [])
            terms_and_conditions = None

            for ref_item in reference_list:
                if ref_item.get("@type") == "ReferenceListTermsAndConditions":
                    terms_and_conditions = ref_item.get("TermsAndConditions", [])
                    break

            if not terms_and_conditions:
                return {}

            for terms in terms_and_conditions:
                if terms.get("id") == terms_ref:
                    baggage_allowance = terms.get("BaggageAllowance", [])
                    if baggage_allowance:
                        allowance = baggage_allowance[0]
                        return {
                            "carry_on_included": True,
                            "checked_bag_included": True,
                            "carry_on_text": "1 piece included",
                            "checked_bag_text": "Weight allowance applies"
                        }

        except Exception as e:
            print(f"[SearchResultManager] Error extracting baggage info: {e}")

        return {}

    def _extract_penalties(self, response: Dict[str, Any], brand_offering: Dict[str, Any]) -> Dict[str, Any]:
        """Extract penalty information"""
        try:
            terms_ref = brand_offering.get("TermsAndConditions", {}).get("termsAndConditionsRef", "")
            if not terms_ref:
                return {}

            # Find matching terms and conditions
            reference_list = response.get("ReferenceList", [])
            terms_and_conditions = None

            for ref_item in reference_list:
                if ref_item.get("@type") == "ReferenceListTermsAndConditions":
                    terms_and_conditions = ref_item.get("TermsAndConditions", [])
                    break

            if not terms_and_conditions:
                return {}

            for terms in terms_and_conditions:
                if terms.get("id") == terms_ref:
                    penalties = terms.get("Penalties", [])
                    if penalties:
                        penalty_info = penalties[0]
                        change_penalty = "Free"
                        cancel_penalty = "Free"

                        # Extract change penalty
                        change_penalties = penalty_info.get("Change", [])
                        if change_penalties:
                            change_detail = change_penalties[0]
                            change_amounts = change_detail.get("Penalty", [])
                            if change_amounts:
                                change_amount = change_amounts[0].get("Amount", {})
                                if change_amount.get("value", 0) > 0:
                                    change_penalty = f"{change_amount.get('value', 0)} {change_amount.get('code', 'EUR')}"

                        # Extract cancel penalty
                        cancel_penalties = penalty_info.get("Cancel", [])
                        if cancel_penalties:
                            cancel_detail = cancel_penalties[0]
                            cancel_amounts = cancel_detail.get("Penalty", [])
                            if cancel_amounts:
                                cancel_amount = cancel_amounts[0].get("Amount", {})
                                if cancel_amount.get("value", 0) > 0:
                                    cancel_penalty = f"{cancel_amount.get('value', 0)} {cancel_amount.get('code', 'EUR')}"

                        return {
                            "change": change_penalty,
                            "cancel": cancel_penalty
                        }

        except Exception as e:
            print(f"[SearchResultManager] Error extracting penalties: {e}")

        return {"change": "Free", "cancel": "Free"}

    def _extract_baggage_info_from_resolved(self, pbo_resolved: Dict[str, Any]) -> Dict[str, Any]:
        """Extract baggage information from resolved product brand offering"""
        # For now, using the default implementation until we have more specific resolved baggage data
        # This can be enhanced later to extract more detailed baggage info from resolved data
        return {
            "carry_on_included": True,
            "checked_bag_included": True,
            "carry_on_text": "1 piece included",
            "checked_bag_text": "Weight allowance applies"
        }

    def _extract_penalties_from_resolved(self, pbo_resolved: Dict[str, Any]) -> Dict[str, Any]:
        """Extract penalty information from resolved product brand offering"""
        # Extract penalty information if available in resolved data
        # This can be enhanced as needed based on what's available in resolved output
        terms = pbo_resolved.get("terms", "")
        if "free" in terms.lower() or "no penalty" in terms.lower():
            return {"change": "Free", "cancel": "Free"}
        else:
            # Default to "Free" unless more specific data is available
            return {"change": "Free", "cancel": "Free"}

    async def get_search_result(self, search_id: str) -> Optional[SearchResult]:
        """Retrieve search result by ID"""
        try:
            redis_conn = await self.get_connection()
            result_key = f"search_result:{search_id}"

            result_data = await redis_conn.get(result_key)
            if not result_data:
                return None

            data = json.loads(result_data)

            # Convert flight options back to objects
            flight_options = [
                FlightOption(**option_data)
                for option_data in data.get("flight_options", [])
            ]

            return SearchResult(
                search_id=data["search_id"],
                wa_id=data["wa_id"],
                thread_id=data["thread_id"],
                origin=data["origin"],
                destination=data["destination"],
                search_date=data["search_date"],
                trip_type=data["trip_type"],
                passengers=data["passengers"],
                flight_options=flight_options,
                search_timestamp=data["search_timestamp"],
                expires_at=data["expires_at"]
            )

        except Exception as e:
            print(f"[SearchResultManager] Error retrieving search result {search_id}: {e}")
            return None

    async def get_user_search_history(self, wa_id: str) -> List[str]:
        """Get user's search history"""
        try:
            redis_conn = await self.get_connection()
            user_search_key = f"user_searches:{wa_id}"

            search_ids = await redis_conn.smembers(user_search_key)
            return list(search_ids)

        except Exception as e:
            print(f"[SearchResultManager] Error getting user search history for {wa_id}: {e}")
            return []

    async def get_latest_search_for_thread(self, thread_id: str) -> Optional[str]:
        """Get latest search ID for a thread"""
        try:
            redis_conn = await self.get_connection()
            thread_search_key = f"thread_latest_search:{thread_id}"

            return await redis_conn.get(thread_search_key)

        except Exception as e:
            print(f"[SearchResultManager] Error getting latest search for thread {thread_id}: {e}")
            return None

    def format_flight_option_for_display(self, option: FlightOption) -> str:
        """Format a flight option for user display"""
        return (
            f"✈️ {option.departure} → {option.arrival}\n"
            f"🕐 {option.departure_time} - {option.arrival_time} ({option.duration})\n"
            f"🏢 {option.airline} {option.flight_number}\n"
            f"💰 {option.price} {option.currency} ({option.cabin_class})\n"
            f"🧳 Baggage: {option.baggage_info.get('carry_on_text', 'Check details')}\n"
            f"📋 Changes: {option.penalties.get('change', 'Free')} | Cancellation: {option.penalties.get('cancel', 'Free')}\n"
        )

    def format_search_results_for_display(self, search_result: SearchResult) -> str:
        """Format complete search results for user display"""
        if not search_result.flight_options:
            return "❌ No flights found for your search criteria."

        # Sort by price and take top 5
        sorted_options = sorted(search_result.flight_options, key=lambda x: x.price)[:5]

        response = f"🎯 Found {len(search_result.flight_options)} flight options for {search_result.origin} → {search_result.destination}\n\n"

        for i, option in enumerate(sorted_options, 1):
            response += f"**Option {i}:**\n"
            response += self.format_flight_option_for_display(option)
            response += "\n"

        response += f"\n💡 Showing top {len(sorted_options)} cheapest options. Use the option number to get more details!"

        return response

    async def get_latest_for_user(self, wa_id: str) -> Optional[SearchResult]:
        """Get the latest search result for a user"""
        try:
            redis_conn = await self.get_connection()
            # Get all search IDs for the user
            user_search_list_key = f"user_search_list:{wa_id}"
            search_keys = await redis_conn.lrange(user_search_list_key, 0, -1)
            
            if not search_keys:
                return None
                
            # Get the most recent search result
            latest_key = search_keys[0].decode() if isinstance(search_keys[0], bytes) else search_keys[0]
            result_data = await redis_conn.get(latest_key)
            
            if not result_data:
                return None

            data = json.loads(result_data)

            # Convert flight options back to objects
            flight_options = [
                FlightOption(**option_data)
                for option_data in data.get("flight_options", [])
            ]

            return SearchResult(
                search_id=data["search_id"],
                wa_id=data["wa_id"],
                thread_id=data["thread_id"],
                origin=data["origin"],
                destination=data["destination"],
                search_date=data["search_date"],
                trip_type=data["trip_type"],
                passengers=data["passengers"],
                flight_options=flight_options,
                search_timestamp=data["search_timestamp"],
                expires_at=data["expires_at"]
            )

        except Exception as e:
            print(f"[SearchResultManager] Error retrieving latest search result for user {wa_id}: {e}")
            return None

    def get_offer_by_id(self, search_result: SearchResult, offer_id: str):
        """
        Get a specific offer by ID from a search result.
        This method looks through the raw data to find the specific offer by ID.
        """
        # Go through the flight options to find one with the matching raw data
        for option in search_result.flight_options:
            raw_data = option.raw_data
            # Check if this matches the offer ID we're looking for
            
            # The offer ID could be in different locations depending on the response structure
            # Look in the offering's ID first
            offering = raw_data.get("offering", {})
            if offering.get("id") == offer_id:
                return offering
            
            # If not found, look in the brand offering
            brand_offering = raw_data.get("brand_offering", {})
            # The offer ID may be an internal ID, so we might need to match differently
            # Look through the resolved offerings in the raw response
            raw_response = raw_data.get("raw_response", {})
            resolved_offerings = raw_response.get("ResolvedOfferings", [])
            
            for resolved_offering in resolved_offerings:
                if resolved_offering.get("id") == offer_id:
                    # Look for the specific ProductBrandOption with our ID
                    for pbo in resolved_offering.get("ProductBrandOptions", []):
                        # Compare based on other unique identifiers if the ID doesn't match directly
                        # Since the ID in the UI may be different from the internal ID, 
                        # we'll return the first matching PBO or a full offering containing it
                        pass  # We'll implement specific matching logic as needed
    
        # For now, return None - in a real implementation, we'd need to map UI option IDs to internal IDs
        return None


# Global instance
search_result_manager = SearchResultManager()