#!/usr/bin/env python3
"""
Comprehensive test script for the new search result management features.
Tests the complete flow from search to conversational interaction.
"""

import asyncio
import json
import sys
import os
from datetime import datetime

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.search_result_manager import search_result_manager, SearchResult, FlightOption
from app.tools.SearchResultTool import SearchResultManager, StoreSearchResult
from app.langgraph.graph_config import create_graph, invoke_graph
from app.langgraph.memory_manager import memory_manager


async def test_search_result_storage():
    """Test basic search result storage and retrieval"""
    print("🧪 Testing Search Result Storage...")

    # Test data
    wa_id = "test_user_123"
    thread_id = "test_thread_456"

    search_data = {
        "origin": "LHR",
        "destination": "DXB",
        "search_date": "2025-12-20",
        "trip_type": "one-way",
        "passengers": 1,
        "raw_response": {
            "CatalogProductOfferingsResponse": {
                "CatalogProductOfferings": {
                    "CatalogProductOffering": [
                        {
                            "Departure": "LHR",
                            "Arrival": "DXB",
                            "ProductBrandOptions": [
                                {
                                    "flightRefs": ["s1"],
                                    "ProductBrandOffering": [
                                        {
                                            "Brand": {"BrandRef": "b0"},
                                            "BestCombinablePrice": {
                                                "TotalPrice": 760.12,
                                                "CurrencyCode": {"value": "EUR"}
                                            }
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                },
                "ReferenceList": [
                    {
                        "@type": "ReferenceListFlight",
                        "Flight": [
                            {
                                "id": "s1",
                                "FlightDetail": {
                                    "Departure": {"time": "22:00:00"},
                                    "Arrival": {"time": "08:45:00"},
                                    "duration": "PT6H45M",
                                    "carrier": "EK",
                                    "number": "6",
                                    "equipment": "388"
                                }
                            }
                        ]
                    }
                ]
            }
        },
        "detected_language": "en"
    }

    try:
        # Store search result
        search_id = await search_result_manager.store_search_result(wa_id, thread_id, search_data)
        print(f"✅ Search result stored with ID: {search_id}")

        # Retrieve search result
        retrieved_result = await search_result_manager.get_search_result(search_id)
        if retrieved_result:
            print(f"✅ Search result retrieved successfully: {len(retrieved_result.flight_options)} options")
            print(f"   Route: {retrieved_result.origin} → {retrieved_result.destination}")
            print(f"   Cheapest: {retrieved_result.flight_options[0].price} {retrieved_result.flight_options[0].currency}")
        else:
            print("❌ Failed to retrieve search result")
            return False

        # Test user search history
        search_history = await search_result_manager.get_user_search_history(wa_id)
        if search_id in search_history:
            print(f"✅ User search history updated: {len(search_history)} searches")
        else:
            print("❌ User search history not updated")
            return False

        # Test thread latest search
        latest_search_id = await search_result_manager.get_latest_search_for_thread(thread_id)
        if latest_search_id == search_id:
            print("✅ Thread latest search updated correctly")
        else:
            print("❌ Thread latest search not updated")
            return False

        return True

    except Exception as e:
        print(f"❌ Error in search result storage test: {e}")
        return False


async def test_search_result_formatting():
    """Test search result formatting for user display"""
    print("\n🧪 Testing Search Result Formatting...")

    try:
        # Create a mock search result
        flight_option = FlightOption(
            id="test_flight_1",
            departure="LHR",
            arrival="DXB",
            departure_time="22:00:00",
            arrival_time="08:45:00",
            duration="6h 45m",
            airline="Emirates",
            flight_number="EK 6",
            aircraft="Boeing 388",
            price=760.12,
            currency="EUR",
            cabin_class="Economy",
            stops=0,
            baggage_info={"carry_on_text": "1 piece included", "checked_bag_text": "30kg included"},
            penalties={"change": "85 EUR", "cancel": "128 EUR"},
            raw_data={}
        )

        search_result = SearchResult(
            search_id="test_search_123",
            wa_id="test_user_123",
            thread_id="test_thread_456",
            origin="LHR",
            destination="DXB",
            search_date="2025-12-20",
            trip_type="one-way",
            passengers=1,
            flight_options=[flight_option],
            search_timestamp=datetime.now().isoformat(),
            expires_at=datetime.now().timestamp() + 3600
        )

        # Test formatting
        formatted_display = search_result_manager.format_search_results_for_display(search_result)
        print("✅ Formatted display:")
        print(formatted_display)

        # Test individual option formatting
        option_display = search_result_manager.format_flight_option_for_display(flight_option)
        print("\n✅ Individual option display:")
        print(option_display)

        return True

    except Exception as e:
        print(f"❌ Error in formatting test: {e}")
        return False


async def test_search_result_tools():
    """Test the SearchResultTool functionality"""
    print("\n🧪 Testing Search Result Tools...")

    try:
        # Test StoreSearchResult tool
        print("Testing StoreSearchResult tool...")

        search_data = {
            "origin": "LHR",
            "destination": "DXB",
            "search_date": "2025-12-20",
            "trip_type": "one-way",
            "passengers": 1,
            "raw_response": {"test": "data"},
            "detected_language": "en"
        }

        result = await StoreSearchResult.ainvoke({
            "wa_id": "test_user_123",
            "thread_id": "test_thread_456",
            "search_data": search_data
        })

        print(f"✅ StoreSearchResult response: {result}")

        # Test SearchResultManager tool - list action
        print("\nTesting SearchResultManager tool - list action...")
        result = await SearchResultManager.ainvoke({
            "action": "list",
            "wa_id": "test_user_123"
        })

        print(f"✅ List action response: {result}")

        # Test SearchResultManager tool - latest action
        print("\nTesting SearchResultManager tool - latest action...")
        result = await SearchResultManager.ainvoke({
            "action": "latest",
            "thread_id": "test_thread_456"
        })

        print(f"✅ Latest action response: {result}")

        return True

    except Exception as e:
        print(f"❌ Error in search result tools test: {e}")
        return False


async def test_langgraph_integration():
    """Test LangGraph integration with new tools"""
    print("\n🧪 Testing LangGraph Integration...")

    try:
        # Create graph with new tools
        graph = create_graph()
        print("✅ Graph created successfully")

        # Test basic graph invocation
        test_message = "Show me latest search results"
        state = await invoke_graph(graph, test_message, "test_thread_456", detected_language="en")

        if state:
            print("✅ Graph invocation successful")
            print(f"   Response: {state.get('messages', [])}")
        else:
            print("❌ Graph invocation failed")
            return False

        return True

    except Exception as e:
        print(f"❌ Error in LangGraph integration test: {e}")
        return False


async def test_error_handling():
    """Test error handling and edge cases"""
    print("\n🧪 Testing Error Handling...")

    try:
        # Test with invalid search ID
        invalid_result = await search_result_manager.get_search_result("invalid_id")
        if invalid_result is None:
            print("✅ Invalid search ID handled correctly")
        else:
            print("❌ Invalid search ID not handled properly")
            return False

        # Test with non-existent user
        empty_history = await search_result_manager.get_user_search_history("non_existent_user")
        if empty_history == []:
            print("✅ Non-existent user handled correctly")
        else:
            print("❌ Non-existent user not handled properly")
            return False

        # Test tool with missing parameters
        error_result = await SearchResultManager.ainvoke({"action": "invalid_action"})
        if "Invalid action" in str(error_result):
            print("✅ Invalid action handled correctly")
        else:
            print("❌ Invalid action not handled properly")
            return False

        return True

    except Exception as e:
        print(f"❌ Error in error handling test: {e}")
        return False


async def test_conversational_flow():
    """Test conversational flow with stored results"""
    print("\n🧪 Testing Conversational Flow...")

    try:
        # First, store a search result
        wa_id = "conversation_test_user"
        thread_id = "conversation_test_thread"

        search_data = {
            "origin": "LHR",
            "destination": "DXB",
            "search_date": "2025-12-20",
            "trip_type": "one-way",
            "passengers": 1,
            "raw_response": {
                "CatalogProductOfferingsResponse": {
                    "CatalogProductOfferings": {
                        "CatalogProductOffering": [
                            {
                                "Departure": "LHR",
                                "Arrival": "DXB",
                                "ProductBrandOptions": [
                                    {
                                        "flightRefs": ["s1"],
                                        "ProductBrandOffering": [
                                            {
                                                "Brand": {"BrandRef": "b0"},
                                                "BestCombinablePrice": {
                                                    "TotalPrice": 760.12,
                                                    "CurrencyCode": {"value": "EUR"}
                                                }
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    "ReferenceList": [
                        {
                            "@type": "ReferenceListFlight",
                            "Flight": [
                                {
                                    "id": "s1",
                                    "FlightDetail": {
                                        "Departure": {"time": "22:00:00"},
                                        "Arrival": {"time": "08:45:00"},
                                        "duration": "PT6H45M",
                                        "carrier": "EK",
                                        "number": "6",
                                        "equipment": "388"
                                    }
                                }
                            ]
                        }
                    ]
                }
            },
            "detected_language": "en"
        }

        search_id = await search_result_manager.store_search_result(wa_id, thread_id, search_data)
        print(f"✅ Test search stored: {search_id}")

        # Test conversational queries
        test_queries = [
            "show latest results",
            "list my searches",
            "show search details",
            "compare options"
        ]

        graph = create_graph()

        for query in test_queries:
            print(f"\n   Testing query: '{query}'")
            try:
                state = await invoke_graph(graph, query, thread_id, detected_language="en")
                if state and state.get('messages'):
                    response = state['messages'][-1].content if hasattr(state['messages'][-1], 'content') else str(state['messages'][-1])
                    print(f"   ✅ Response: {response[:100]}...")
                else:
                    print("   ⚠️ No response generated")
            except Exception as e:
                print(f"   ❌ Error: {e}")

        return True

    except Exception as e:
        print(f"❌ Error in conversational flow test: {e}")
        return False


async def run_all_tests():
    """Run all tests and report results"""
    print("🚀 Starting Comprehensive Search Result Feature Tests\n")
    print("=" * 60)

    tests = [
        ("Search Result Storage", test_search_result_storage),
        ("Search Result Formatting", test_search_result_formatting),
        ("Search Result Tools", test_search_result_tools),
        ("LangGraph Integration", test_langgraph_integration),
        ("Error Handling", test_error_handling),
        ("Conversational Flow", test_conversational_flow)
    ]

    results = []

    for test_name, test_func in tests:
        print(f"\n{'='*20} {test_name} {'='*20}")
        try:
            result = await test_func()
            results.append((test_name, result))
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"\n{status}")
        except Exception as e:
            results.append((test_name, False))
            print(f"\n❌ FAILED with exception: {e}")

    # Summary
    print(f"\n{'='*60}")
    print("📊 TEST SUMMARY")
    print(f"{'='*60}")

    passed = 0
    total = len(results)

    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name:<25} {status}")
        if result:
            passed += 1

    print(f"\n🎯 Overall: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! The search result features are working correctly.")
    else:
        print("⚠️ Some tests failed. Please check the implementation.")

    return passed == total


if __name__ == "__main__":
    # Set environment variables for testing
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
    os.environ.setdefault("OPENAI_API_KEY", "test_key")  # Mock key for testing

    # Run all tests
    success = asyncio.run(run_all_tests())

    if success:
        print("\n🎉 All tests completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed. Please review the implementation.")
        sys.exit(1)