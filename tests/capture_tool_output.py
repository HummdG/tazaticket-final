"""
Test to capture the actual output of FlightSearchStateMachine tool
This will show you the real search_id and flattened summary returned by the tool
"""
import asyncio
import json
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

async def capture_tool_output():
    """Capture the real output of FlightSearchStateMachine tool"""
    
    # Mock all dependencies to capture the actual output
    with patch.dict('sys.modules', {
        'app.statemachine.ConversationFlowSM': MagicMock(),
        'app.payloads.OneWayFlightSearch': MagicMock(),
        'app.payloads.RoundTripFlightSearch': MagicMock(),
        'app.tools.TravelportSearch': MagicMock(),
        'app.services.search_result_manager_v2': MagicMock(),
        'app.services.flight_flattener': MagicMock(),
        'app.tools.airline_codes': MagicMock(),
        'app.tools.city_codes': MagicMock(),
        'app.tools.travelport_utils': MagicMock(),
        'app.langgraph.redis_manager': MagicMock(),
        'app.tools.FlightSearchStateMachine': MagicMock(),
    }):
        with patch('app.statemachine.ConversationFlowSM.ConversationFlowSM') as mock_sm_class, \
             patch('app.tools.TravelportSearch.TravelportSearch') as mock_travelport, \
             patch('app.services.search_result_manager_v2.search_result_manager') as mock_store, \
             patch('app.services.flight_flattener.flatten_travelport_response') as mock_flatten, \
             patch('app.tools.airline_codes.parse_carrier_preference', return_value=['TK']), \
             patch('app.tools.city_codes.resolve_phrase_to_airports', return_value=('NYC', [])), \
             patch('app.tools.travelport_utils.is_bulk_search_query', return_value=False), \
             patch('app.langgraph.redis_manager.redis_manager') as mock_redis_manager:

            # Create mock state machine
            mock_sm = MagicMock()
            mock_sm.get_state.return_value = "complete"
            mock_sm.origin = "NYC"
            mock_sm.destination = "LAX"
            mock_sm.departure_date = "2025-12-25"
            mock_sm.return_date = "2025-12-30"
            mock_sm.number_of_passengers = 2
            mock_sm.type_of_trip = "round-trip"
            
            def set_variable(name, value):
                setattr(mock_sm, name, value)
            def get_missing_variables():
                return []
            def set_state(state):
                mock_sm.current_state = state
            mock_sm.set_variable = set_variable
            mock_sm.get_missing_variables = get_missing_variables
            mock_sm.set_state = set_state
            mock_sm.to_dict = lambda: {}
            
            mock_sm_class.return_value = mock_sm
            
            # Mock Redis
            mock_redis_conn = AsyncMock()
            mock_redis_conn.get.return_value = None
            mock_redis_conn.setex.return_value = None
            mock_redis_conn.delete.return_value = None
            mock_redis_manager.get_connection = AsyncMock(return_value=mock_redis_conn)
            
            # Mock Travelport response
            raw_response = {
                "CatalogProductOfferingsResponse": {
                    "productOfferings": [
                        {
                            "price": {"totalPrice": "750.00"},
                            "itineraries": [
                                {
                                    "origin": "NYC",
                                    "destination": "LAX",
                                    "departureTime": "2025-12-25T08:00:00",
                                    "arrivalTime": "2025-12-25T11:00:00",
                                    "airline": "TK",
                                    "flightNumber": "101"
                                }
                            ]
                        }
                    ]
                }
            }
            mock_travelport.ainvoke = AsyncMock(return_value=raw_response)
            
            # Mock the flattener to return realistic data
            text_summary = "Here are the best round-trip flights from New York (NYC) to Los Angeles (LAX):\n\n1. Outbound: Turkish Airlines TK101 on 2025-12-25, 08:00 to 11:00 ($400)\n2. Return: Turkish Airlines TK202 on 2025-12-30, 14:00 to 17:00 ($350)\n\nTotal: $750 for 2 passengers."
            structured_offers = [
                {
                    "price": 400.00,
                    "airline": "TK",
                    "flightNumber": "101",
                    "origin": "NYC",
                    "destination": "LAX",
                    "departure": "2025-12-25T08:00:00",
                    "arrival": "2025-12-25T11:00:00"
                },
                {
                    "price": 350.00,
                    "airline": "TK",
                    "flightNumber": "202",
                    "origin": "LAX",
                    "destination": "NYC",
                    "departure": "2025-12-30T14:00:00",
                    "arrival": "2025-12-30T17:00:00"
                }
            ]
            mock_flatten.return_value = (text_summary, structured_offers)
            
            # Mock the storage to return a real search ID
            search_id = "search_1234567890"
            mock_store.store_search_result = AsyncMock(return_value=search_id)
            
            # Import and run the tool
            from app.tools.FlightSearchFSM_v2 import FlightSearchStateMachine
            
            # Run the tool with complete information
            result = await FlightSearchStateMachine.ainvoke({
                "origin": "New York",
                "destination": "Los Angeles",
                "departure_date": "2025-12-25",
                "return_date": "2025-12-30",
                "number_of_passengers": 2,
                "type_of_trip": "round-trip",
                "thread_id": "test_thread_output",
                "mode_of_conversation": "whatsapp",
                "detected_language": "en"
            })
            
            # Print the actual output from the tool
            print("=== ACTUAL OUTPUT FROM FlightSearchStateMachine TOOL ===")
            print(json.dumps(result, indent=2))
            print()
            
            # Extract and display the specific fields you're interested in
            print("=== KEY FIELDS FROM TOOL OUTPUT ===")
            print(f"search_id: {result.get('search_id', 'NOT FOUND')}")
            print(f"summary: {result.get('summary', 'NOT FOUND')}")
            print()
            
            # Save the actual output to a JSON file
            output_data = {
                "tool_name": "FlightSearchStateMachine",
                "input_parameters": {
                    "origin": "New York",
                    "destination": "Los Angeles",
                    "departure_date": "2025-12-25",
                    "return_date": "2025-12-30",
                    "number_of_passengers": 2,
                    "type_of_trip": "round-trip",
                    "thread_id": "test_thread_output",
                    "mode_of_conversation": "whatsapp",
                    "detected_language": "en"
                },
                "actual_output": result,
                "captured_fields": {
                    "search_id": result.get('search_id'),
                    "summary": result.get('summary'),
                    "status": result.get('status'),
                    "message": result.get('message')
                }
            }
            
            output_file = "flight_search_tool_output.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2)
            
            print(f"Full output saved to: {output_file}")
            print(json.dumps(output_data, indent=2))
            
            return result

if __name__ == "__main__":
    print("Capturing actual output from FlightSearchStateMachine tool...")
    asyncio.run(capture_tool_output())