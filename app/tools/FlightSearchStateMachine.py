"""
FlightSearchStateMachine tool for managing flight search state and performing searches
"""

from langchain_core.tools import tool
from datetime import datetime, timedelta
import re
from typing import Optional
import asyncio

# Import required modules
from ..statemachine.ConversationFlowSM import ConversationFlowSM
from ..payloads.OneWayFlightSearch import OneWayFlightSearch
from ..payloads.RoundTripFlightSearch import RoundTripFlightSearch
from .TravelportSearch import TravelportSearch
from .airline_codes import (
    DEFAULT_PREFERRED_CARRIERS, 
    get_airline_name, 
    parse_carrier_preference
)
from .city_codes import resolve_phrase_to_airports
from .travelport_utils import (
    parse_date_range,
    bulk_search_cheapest_async,
    calculate_return_date,
    is_bulk_search_query,
    extract_return_duration
)

# State machine storage per thread
state_machines = {}

def get_or_create_state_machine(thread_id: str) -> ConversationFlowSM:
    """Get existing state machine or create new one for thread"""
    if thread_id not in state_machines:
        state_machines[thread_id] = ConversationFlowSM()
    return state_machines[thread_id]

def resolve_city_to_iata(city_input: str) -> str:
    """
    Convert natural language city names to IATA codes using city_codes.py
    Returns the preferred IATA code or the original input if no match found
    """
    if not city_input:
        return city_input
    
    # Try to resolve the phrase to airport codes
    preferred_code, all_codes = resolve_phrase_to_airports(city_input)
    
    if preferred_code:
        print(f"[CityMapper] Resolved '{city_input}' to IATA code '{preferred_code}'")
        return preferred_code
    else:
        # If no match found, keep the original (might already be an IATA code)
        print(f"[CityMapper] No mapping found for '{city_input}', keeping as-is")
        return city_input.upper()

def format_duration(minutes: int) -> str:
    """Format duration in minutes to Xh Ym"""
    if not minutes:
        return "Unknown"
    hours = minutes // 60
    mins = minutes % 60
    if hours and mins:
        return f"{hours}h {mins}m"
    elif hours:
        return f"{hours}h"
    else:
        return f"{mins}m"

def format_stops(stops: int) -> str:
    """Format stops count"""
    if stops == 0:
        return "non-stop"
    elif stops == 1:
        return "1 stop"
    else:
        return f"{stops} stops"

def format_baggage_summary(baggage: dict) -> str:
    """Format baggage information"""
    parts = []
    
    # Carry-on
    carry_on = "✓" if baggage.get("carry_on_included") else "✗"
    carry_text = baggage.get("carry_on_text", "")
    if carry_text:
        parts.append(f"carry-on {carry_on} ({carry_text})")
    else:
        parts.append(f"carry-on {carry_on}")
    
    # Checked bag
    checked = "✓" if baggage.get("checked_bag_included") else "✗"
    parts.append(f"checked {checked}")
    
    # Validating airline
    if baggage.get("validating_airline"):
        airline_code = baggage['validating_airline']
        airline_name = get_airline_name(airline_code)
        parts.append(f"Validating airline: {airline_name}")
    
    # Penalties
    if baggage.get("penalties_change"):
        parts.append(f"Change: {baggage['penalties_change']}")
    if baggage.get("penalties_cancel"):
        parts.append(f"Cancel: {baggage['penalties_cancel']}")
    
    return " | ".join(parts)

def format_layovers(itinerary: dict) -> str:
        lays = (itinerary or {}).get("layovers") or []
        if not lays:
            return ""
        parts = [f"{l.get('airport_code') or l.get('city')} ({l.get('duration')})" for l in lays]
        return "   Layover: " + ", ".join(parts) + "\n"


@tool("FlightSearchStateMachine")
def FlightSearchStateMachine(
    origin: Optional[str] = None,
    destination: Optional[str] = None,
    departure_date: Optional[str] = None,
    return_date: Optional[str] = None,          
    number_of_passengers: int = 1,
    type_of_trip: Optional[str] = None,
    user_input_text: Optional[str] = "",
    thread_id: str = "default",
):
    """
    Manages flight search state and performs search when all required fields are complete.
    Call this tool when user mentions flight/travel plans to update search parameters.
    
    IMPORTANT - Date Guidelines:
    - Always use YYYY-MM-DD format
    - For current year dates like "November 6th" or "6th of November", use current year
    - For past dates in current year, automatically move to next year
    - Never use years before current year (avoid 2023, 2022, etc.)
    - Examples: "November 6th" → "2025-11-06", "next Friday" → calculate future date
    
    For carrier preferences:
    - Pass the full user input text to detect airline preferences
    - If user mentions specific airline (e.g., "Emirates", "Qatar", "EK"), use that carrier
    - Otherwise, use comprehensive default carrier list for broader search results
    """
    
    def fix_date_year(date_str):
        """Ensure date is in the future - if in past, move to next year"""
        if not date_str:
            return date_str
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
            today = datetime.now().date()
            
            # If the date is in the past, move it to next year
            if date_obj < today:
                next_year_date = date_obj.replace(year=today.year + 1)
                return next_year_date.strftime('%Y-%m-%d')
            elif date_obj.year < today.year:
                # If year is definitely wrong (like 2023), use current year
                current_year_date = date_obj.replace(year=today.year)
                if current_year_date < today:
                    next_year_date = date_obj.replace(year=today.year + 1)
                    return next_year_date.strftime('%Y-%m-%d')
                else:
                    return current_year_date.strftime('%Y-%m-%d')
            return date_str
        except:
            return date_str
    
    # Get state machine for this thread
    sm = get_or_create_state_machine(thread_id)
    
    # Parse carrier preference from user input
    preferred_carriers = parse_carrier_preference(user_input_text) if user_input_text else DEFAULT_PREFERRED_CARRIERS
    
    # Update provided fields with city-to-IATA mapping
    if origin:
        iata_origin = resolve_city_to_iata(origin)
        sm.set_variable('origin', iata_origin)
    if destination:
        iata_destination = resolve_city_to_iata(destination)
        sm.set_variable('destination', iata_destination)
    if departure_date:
        corrected_departure = fix_date_year(departure_date)
        sm.set_variable('departure_date', corrected_departure)
    if return_date:
        corrected_return = fix_date_year(return_date)
        sm.set_variable('return_date', corrected_return)
    if number_of_passengers:
        sm.set_variable('number_of_passengers', number_of_passengers)
    if type_of_trip:
        # Normalize trip type variations
        normalized_trip_type = type_of_trip.lower().strip()
        if normalized_trip_type in ['oneway', 'one-way', 'one way']:
            normalized_trip_type = 'one-way'
        elif normalized_trip_type in ['roundtrip', 'round-trip', 'round trip', 'return']:
            normalized_trip_type = 'round-trip'
        sm.set_variable('type_of_trip', normalized_trip_type)
    
    # Set defaults if not set
    if not sm.detected_language:
        sm.set_variable('detected_language', 'en')
    if not sm.mode_of_conversation:
        sm.set_variable('mode_of_conversation', 'text')
    
    # Check if complete and perform search
    if sm.get_state() == "complete":
        try:
            if sm.type_of_trip == "one-way":
                payload = OneWayFlightSearch(
                    origin=sm.origin,
                    destination=sm.destination,
                    departure_date=sm.departure_date,
                    number_of_passengers=sm.number_of_passengers,
                    carriers=preferred_carriers
                )
                result = TravelportSearch.invoke({"payload": payload, "trip_type": "one-way"})
            else:
                payload = RoundTripFlightSearch(
                    origin=sm.origin,
                    destination=sm.destination,
                    departure_date=sm.departure_date,
                    return_date=sm.return_date,
                    number_of_passengers=sm.number_of_passengers,
                    carriers=preferred_carriers
                )
                result = TravelportSearch.invoke({"payload": payload, "trip_type": "round-trip"})
            
            if result.get("ok"):
                summary = result.get("summary")
                if summary:
                    # Format detailed flight information
                    if summary.get("price_total"):  # Round-trip
                        price = summary["price_total"]
                        outbound = summary.get("outbound", {})
                        inbound = summary.get("inbound", {})
                        
                        response = f"✈️ Round-trip flight found: {price['total']} {price['currency']}\n\n"
                        return {
                            "text": response,           # unchanged human text for the LLM
                            "summary": summary,         # structured data your formatter needs
                            "trip_type": sm.type_of_trip
                        }
                        if outbound:
                            duration = format_duration(outbound.get("duration_minutes_total"))
                            stops = format_stops(outbound.get("stops_total", 0))
                            response += f"🛫 Outbound: {duration}, {stops}\n"
                            if outbound.get("baggage"):
                                response += f"   Baggage: {format_baggage_summary(outbound['baggage'])}\n"
                            lf = format_layovers(outbound.get("itinerary"))
                            if lf:
                                response += lf
                        
                        if inbound:
                            duration = format_duration(inbound.get("duration_minutes_total"))
                            stops = format_stops(inbound.get("stops_total", 0))
                            response += f"🛬 Return: {duration}, {stops}\n"
                            if inbound.get("baggage"):
                                response += f"   Baggage: {format_baggage_summary(inbound['baggage'])}\n"
                            lf = format_layovers(inbound.get("itinerary"))
                            if lf:
                                response += lf
                        # Reset state machine after successful search
                        state_machines[thread_id] = ConversationFlowSM()
                        return response
                    else:  # One-way
                        price = summary.get("price", {})
                        price_text = f"{price.get('total')} {price.get('currency')}" if price.get('total') else "Price not available"
                        
                        duration = format_duration(summary.get("duration_minutes_total"))
                        stops = format_stops(summary.get("stops_total", 0))
                        
                        response = f"✈️ One-way flight found: {price_text}\n"
                        response += f"🛫 Flight: {duration}, {stops}\n"
                        it = (summary.get("itinerary") or {})
                        
                        if it.get("airlines"):
                            response += f"Airline: {it['airlines']}\n"
                        if it.get("flight_numbers"):
                            response += f"Flight no.: {it['flight_numbers']}\n"
                        lf = format_layovers(it)
                        if lf:
                            response += lf
                        
                        if summary.get("baggage"):
                            response += f"Baggage: {format_baggage_summary(summary['baggage'])}\n"
                        
                        # Reset state machine after successful search
                        state_machines[thread_id] = ConversationFlowSM()
                        return response
                
                # Fallback if no summary
                # Reset state machine after successful search
                state_machines[thread_id] = ConversationFlowSM()
                return f"Flight search completed! Found flights for {sm.origin} to {sm.destination} on {sm.departure_date}."
            else:
                return f"Sorry, I couldn't find flights. Error: {result.get('error', 'Unknown error')}"
                
        except Exception as e:
            return f"Sorry, there was an error searching for flights: {str(e)}"
    else:
        missing = sm.get_missing_variables()
        return f"Flight search in progress. Still need: {', '.join(missing)}. Please provide these details to continue."


@tool("BulkFlightSearch")
def BulkFlightSearch(
    origin: Optional[str] = None,
    destination: Optional[str] = None,
    user_input_text: str = "",
    number_of_passengers: int = 1,
    thread_id: str = "default",
):
    """
    Detects and handles bulk flight search requests for date ranges.
    Call this tool when user asks for cheapest tickets over a period of time.
    
    Examples:
    - "find me the cheapest ticket in November"
    - "cheapest flight next week"
    - "best price between 2025-01-01 and 2025-01-31"
    
    This tool will:
    1. Detect if it's a bulk search request
    2. Ask for return ticket confirmation if needed
    3. Perform async searches across all dates
    4. Return the cheapest option found
    """
    
    # Check if this is actually a bulk search request
    if not is_bulk_search_query(user_input_text):
        return "This doesn't appear to be a bulk search request. Please use the regular FlightSearchStateMachine tool for single date searches."
    
    # Resolve cities to IATA codes
    if origin:
        origin = resolve_city_to_iata(origin)
    if destination:
        destination = resolve_city_to_iata(destination)
    
    # Early check for duplicate searches after city resolution
    search_key = f"{thread_id}:{origin}:{destination}"
    from .travelport_utils import _active_searches
    if any(key.startswith(search_key) for key in _active_searches):
        return "I'm already processing a bulk search for this route. Please wait for the current search to complete."
    
    # Check if we have minimum required information
    if not origin or not destination:
        return "I need both origin and destination cities to perform a bulk search. Please provide the missing information."
    
    # Parse carrier preference from user input
    preferred_carriers = parse_carrier_preference(user_input_text) if user_input_text else DEFAULT_PREFERRED_CARRIERS
    
    # Parse date range from user input
    dates, is_bulk = parse_date_range(user_input_text)
    
    if not is_bulk or not dates:
        return "I couldn't detect a valid date range for bulk search. Please specify a time period like 'in November', 'next week', or 'between 2025-01-01 and 2025-01-31'."
    

    
    # Check if user wants return tickets
    return_duration = extract_return_duration(user_input_text)
    wants_return = any(keyword in user_input_text.lower() for keyword in ['return', 'round trip', 'roundtrip', 'round-trip'])
    
    # Determine trip type
    trip_type = "one-way"
    if wants_return and return_duration:
        trip_type = "one-way"  # We'll handle return separately for bulk search
    elif wants_return:
        return f"""🔍 I found a bulk search request for {origin} to {destination} across {len(dates)} dates.

For return tickets, please specify how many days later you want to return (e.g., "10 days later", "1 week later").

Without return duration specified, I'll search for one-way tickets only."""
    
    # Queue the bulk search for background processing and return immediate acknowledgment
    try:
        from .travelport_utils import queue_bulk_search_task, execute_bulk_search_background
        
        # For date ranges larger than 5, use background processing to avoid timeout
        print(f"[BulkFlightSearch] Thread ID received: {thread_id}")
        if len(dates) > 5:
            # Queue the search task for background execution
            print(f"[BulkFlightSearch] Queueing background task with thread_id: {thread_id}")
            queue_bulk_search_task(
                execute_bulk_search_background,
                origin=origin,
                destination=destination, 
                dates=dates,
                number_of_passengers=number_of_passengers,
                carriers=preferred_carriers,
                trip_type=trip_type,
                thread_id=thread_id,
                user_phone=None,  # Not needed, we'll use thread_id directly
                original_user_input=user_input_text
            )
            
            # Return immediate acknowledgment
            response = f"🔍 BULK SEARCH STARTED!\n\n"
            response += f"✈️ Searching {origin} → {destination}\n"
            response += f"📅 Checking {len(dates)} dates for best prices\n"
            response += f"⏳ This will take a few minutes...\n\n"
            response += f"I'll send you the results as soon as I find the cheapest option! 🎯"
            
            if return_duration:
                response += f"\n\n🔄 I'll also calculate return flights {return_duration} days later."
            
            return response
        
        else:
            # For smaller searches (≤5 dates), execute immediately 
            from .travelport_utils import bulk_search_cheapest_sync
            
            bulk_result = bulk_search_cheapest_sync(
                origin=origin,
                destination=destination,
                dates=dates,
                number_of_passengers=number_of_passengers,
                carriers=preferred_carriers,
                trip_type=trip_type
            )
            
            if not bulk_result.get("ok"):
                return f"Bulk search failed: {bulk_result.get('error', 'Unknown error')}"
            
            cheapest = bulk_result.get("cheapest_result")
            if not cheapest:
                return f"No flights found across {bulk_result.get('total_searches', 0)} dates searched."
            
            # Format the result (same as before for small searches)
            summary = cheapest.get("summary")
            search_date = cheapest.get("search_date")
            
            price = summary.get("price", {})
            price_text = f"{price.get('total')} {price.get('currency')}" if price.get('total') else "Price not available"
            
            duration = format_duration(summary.get("duration_minutes_total"))
            stops = format_stops(summary.get("stops_total", 0))
            
            response = f"🎯 CHEAPEST OPTION FOUND!\n\n"
            response += f"✈️ {origin} → {destination} on {search_date}\n"
            response += f"💰 Price: {price_text}\n"
            response += f"⏱️ Duration: {duration}, {stops}\n"
            
            it = summary.get("itinerary", {})
            if it.get("airlines"):
                response += f"🏢 Airline: {it['airlines']}\n"
            if it.get("flight_numbers"):
                response += f"🔢 Flight: {it['flight_numbers']}\n"
            
            # Add layover info
            lf = format_layovers(it)
            if lf:
                response += lf
            
            if summary.get("baggage"):
                response += f"🧳 Baggage: {format_baggage_summary(summary['baggage'])}\n"
            
            response += f"\n📊 Search Summary: {bulk_result.get('search_summary')}"
            
            # Handle return trip if requested
            if return_duration:
                from .travelport_utils import calculate_return_date
                return_date = calculate_return_date(search_date, return_duration)
                response += f"\n\n🔄 For return trip {return_duration} days later ({return_date}), would you like me to search for return flights?"
            
            return response
        
    except Exception as e:
        return f"Error setting up bulk search: {str(e)}"





 