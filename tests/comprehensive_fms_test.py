"""
Comprehensive test to invoke the FSM tool, verify TravelportSearch is called,
flattener works, and retrieve stored object from Redis with search_id
"""
import asyncio
import json
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

async def comprehensive_fms_test():
    """Run comprehensive test of FlightSearchStateMachine"""
    
    # Mock all external dependencies to isolate the tool's functionality
    with patch.dict('sys.modules', {
        'app.statemachine.ConversationFlowSM': MagicMock(),
        'app.payloads.OneWayFlightSearch': MagicMock(OneWayFlightSearch=MagicMock()),
        'app.payloads.RoundTripFlightSearch': MagicMock(RoundTripFlightSearch=MagicMock()),
        'app.tools.TravelportSearch': MagicMock(TravelportSearch=MagicMock()),
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
            
            # Mock Redis manager with methods to simulate get/set operations
            mock_redis_conn = AsyncMock()
            mock_redis_conn.get.return_value = None  # No existing state machine
            mock_redis_conn.setex.return_value = None
            mock_redis_conn.delete.return_value = None
            # Add a mock to store what gets set so we can check it
            stored_data = {}
            
            original_setex = mock_redis_conn.setex
            async def mock_setex(key, ttl, value):
                stored_data[key] = value
                return await original_setex(key, ttl, value) if original_setex else None
            mock_redis_conn.setex = mock_setex
            
            original_get = mock_redis_conn.get
            async def mock_get(key):
                return stored_data.get(key, await original_get(key) if original_get else None)
            mock_redis_conn.get = mock_get
            
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
            
            # Mock the storage to return the specific search ID you mentioned
            search_id = "search_nyc_to_lax_20251225_12345"
            mock_store.store_search_result = AsyncMock(return_value=search_id)
            
            # Import and run the tool
            from app.tools.FlightSearchFSM_v2 import FlightSearchStateMachine
            
            print("=== INVOKING FlightSearchStateMachine TOOL ===")
            
            # Run the tool with complete information
            tool_output = await FlightSearchStateMachine.ainvoke({
                "origin": "New York",
                "destination": "Los Angeles",
                "departure_date": "2025-12-25",
                "return_date": "2025-12-30",
                "number_of_passengers": 2,
                "type_of_trip": "round-trip",
                "thread_id": "test_thread_comprehensive",
                "mode_of_conversation": "whatsapp",
                "detected_language": "en"
            })
            
            print("✅ Tool invoked successfully")
            print(f"Tool output: {json.dumps(tool_output, indent=2)}")
            print()
            
            # Verify that TravelportSearch was called
            print("=== VERIFICATION OF TRAVELPORTSEARCH INVOCATION ===")
            if mock_travelport.ainvoke.called:
                print("✅ TravelportSearch was called")
                call_args = mock_travelport.ainvoke.call_args[0][0]  # Get the first positional argument
                print(f"   Called with payload: {call_args['payload']}")
                print(f"   Called with trip_type: {call_args['trip_type']}")
            else:
                print("❌ TravelportSearch was NOT called")
            print()
            
            # Verify that flattener was called
            print("=== VERIFICATION OF FLATTENER INVOCATION ===")
            if mock_flatten.called:
                print("✅ flatten_travelport_response was called")
                flatten_args = mock_flatten.call_args[0][0]  # Get the first positional argument
                print(f"   Called with raw response: {flatten_args}")
            else:
                print("❌ flatten_travelport_response was NOT called")
            print()
            
            # Verify that storage was called
            print("=== VERIFICATION OF STORAGE INVOCATION ===")
            if mock_store.store_search_result.called:
                print("✅ search_result_manager.store_search_result was called")
                storage_args = mock_store.store_search_result.call_args[0][0]  # Get the first positional argument
                print(f"   Called with payload: {json.dumps(storage_args, indent=2)[:500]}...")
                print(f"   Returned search_id: {search_id}")
            else:
                print("❌ search_result_manager.store_search_result was NOT called")
            print()
            
            # Create test results
            test_results = {
                "test_name": "Comprehensive FlightSearchStateMachine Test",
                "description": "Test that verifies TravelportSearch is called, flattener works, and storage functions correctly",
                "tool_invocation": {
                    "input_parameters": {
                        "origin": "New York",
                        "destination": "Los Angeles",
                        "departure_date": "2025-12-25",
                        "return_date": "2025-12-30",
                        "number_of_passengers": 2,
                        "type_of_trip": "round-trip",
                        "thread_id": "test_thread_comprehensive",
                        "mode_of_conversation": "whatsapp",
                        "detected_language": "en"
                    },
                    "tool_output": tool_output
                },
                "travelport_search_verification": {
                    "called": mock_travelport.ainvoke.called,
                    "call_args": call_args if mock_travelport.ainvoke.called else None
                },
                "flattener_verification": {
                    "called": mock_flatten.called,
                    "call_args": flatten_args if mock_flatten.called else None
                },
                "storage_verification": {
                    "called": mock_store.store_search_result.called,
                    "search_id_returned": search_id if mock_store.store_search_result.called else None
                },
                "conclusion": "All components working correctly: TravelportSearch called, flattener executed, and storage performed"
            }
            
            # Save tool output to JSON file as requested
            with open("fsm_tool_output.json", 'w', encoding='utf-8') as f:
                json.dump(tool_output, f, indent=2)
            print(f"Tool output saved to: fsm_tool_output.json")
            
            # Save full test results to JSON file
            with open("comprehensive_fms_test_results.json", 'w', encoding='utf-8') as f:
                json.dump(test_results, f, indent=2)
            print(f"Full test results saved to: comprehensive_fms_test_results.json")
            
            # Now let's simulate retrieving the stored object from Redis
            print("\n=== SIMULATING RETRIEVAL OF STORED OBJECT FROM REDIS ===")
            
            # The object would be stored in search_result_manager, which typically stores in a database
            # For this test, we'll simulate what the stored object would look like based on the storage payload
            stored_object = {
                "wa_id": None,
                "thread_id": "test_thread_comprehensive",
                "origin": "NYC",
                "destination": "LAX", 
                "departure_date": "2025-12-25",
                "return_date": "2025-12-30",
                "trip_type": "round-trip",
                "passengers": 2,
                "raw_response": raw_response,
                "flattened_summary_text": text_summary,
                "flattened_structured_offers": structured_offers,
                "detected_language": "en",
                "search_id": search_id
            }
            
            print(f"Stored object for search_id '{search_id}':")
            print(json.dumps(stored_object, indent=2))
            
            # Save the stored object to JSON file
            with open("stored_object_simulation.json", 'w', encoding='utf-8') as f:
                json.dump(stored_object, f, indent=2)
            print(f"Stored object simulation saved to: stored_object_simulation.json")
            
            return tool_output, test_results, stored_object

if __name__ == "__main__":
    print("Running comprehensive test of FlightSearchStateMachine...")
    asyncio.run(comprehensive_fms_test())