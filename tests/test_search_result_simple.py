#!/usr/bin/env python3
"""
Simple test script for search result features without external dependencies.
Tests the core functionality in isolation.
"""

import asyncio
import sys
import os
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.search_result_manager import SearchResult, FlightOption, search_result_manager


class MockRedisManager:
    """Mock Redis manager for testing"""

    def __init__(self):
        self.data = {}
        self.sets = {}

    async def get_connection(self):
        return self

    async def setex(self, key, ttl, value):
        self.data[key] = value

    async def get(self, key):
        return self.data.get(key)

    async def sadd(self, key, value):
        if key not in self.sets:
            self.sets[key] = set()
        self.sets[key].add(value)

    async def smembers(self, key):
        return self.sets.get(key, set())

    async def expire(self, key, ttl):
        pass


async def test_search_result_manager_core():
    """Test core search result manager functionality"""
    print("🧪 Testing Search Result Manager Core Functionality...")

    # Mock Redis manager
    original_redis_manager = search_result_manager.redis_manager
    search_result_manager.redis_manager = MockRedisManager()

    try:
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

        # Test 1: Store search result
        print("   Testing search result storage...")
        search_id = await search_result_manager.store_search_result(wa_id, thread_id, search_data)
        print(f"   ✅ Search stored with ID: {search_id}")

        # Test 2: Retrieve search result
        print("   Testing search result retrieval...")
        retrieved_result = await search_result_manager.get_search_result(search_id)
        if retrieved_result:
            print(f"   ✅ Retrieved {len(retrieved_result.flight_options)} flight options")
            print(f"   ✅ Route: {retrieved_result.origin} → {retrieved_result.destination}")
            print(f"   ✅ Cheapest: {retrieved_result.flight_options[0].price} {retrieved_result.flight_options[0].currency}")
        else:
            print("   ❌ Failed to retrieve search result")
            return False

        # Test 3: User search history
        print("   Testing user search history...")
        search_history = await search_result_manager.get_user_search_history(wa_id)
        if search_id in search_history:
            print(f"   ✅ User search history: {len(search_history)} searches")
        else:
            print("   ❌ User search history not updated")
            return False

        # Test 4: Thread latest search
        print("   Testing thread latest search...")
        latest_search_id = await search_result_manager.get_latest_search_for_thread(thread_id)
        if latest_search_id == search_id:
            print("   ✅ Thread latest search updated correctly")
        else:
            print("   ❌ Thread latest search not updated")
            return False

        # Test 5: Formatting
        print("   Testing result formatting...")
        formatted_display = search_result_manager.format_search_results_for_display(retrieved_result)
        print("   ✅ Formatted display generated")

        option_display = search_result_manager.format_flight_option_for_display(retrieved_result.flight_options[0])
        print("   ✅ Individual option display generated")

        return True

    except Exception as e:
        print(f"❌ Error in core functionality test: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # Restore original Redis manager
        search_result_manager.redis_manager = original_redis_manager


async def test_flight_option_creation():
    """Test FlightOption creation and methods"""
    print("\n🧪 Testing FlightOption Creation...")

    try:
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
            raw_data={"test": "data"}
        )

        # Test to_dict method
        option_dict = flight_option.to_dict()
        if isinstance(option_dict, dict) and option_dict["id"] == "test_flight_1":
            print("✅ FlightOption.to_dict() works correctly")
        else:
            print("❌ FlightOption.to_dict() failed")
            return False

        # Test formatting
        display = search_result_manager.format_flight_option_for_display(flight_option)
        if "LHR" in display and "DXB" in display and "760.12" in display:
            print("✅ FlightOption formatting works correctly")
        else:
            print("❌ FlightOption formatting failed")
            return False

        return True

    except Exception as e:
        print(f"❌ Error in FlightOption test: {e}")
        return False


async def test_search_result_creation():
    """Test SearchResult creation and methods"""
    print("\n🧪 Testing SearchResult Creation...")

    try:
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
            baggage_info={"carry_on_text": "1 piece included"},
            penalties={"change": "85 EUR"},
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

        # Test to_dict method
        result_dict = search_result.to_dict()
        if isinstance(result_dict, dict) and result_dict["search_id"] == "test_search_123":
            print("✅ SearchResult.to_dict() works correctly")
        else:
            print("❌ SearchResult.to_dict() failed")
            return False

        # Test formatting
        display = search_result_manager.format_search_results_for_display(search_result)
        if "LHR" in display and "DXB" in display and "flight options" in display:
            print("✅ SearchResult formatting works correctly")
        else:
            print("❌ SearchResult formatting failed")
            return False

        return True

    except Exception as e:
        print(f"❌ Error in SearchResult test: {e}")
        return False


async def test_error_scenarios():
    """Test error handling scenarios"""
    print("\n🧪 Testing Error Scenarios...")

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

        # Test with empty search data
        empty_result = await search_result_manager.store_search_result("test_user", "test_thread", {})
        if empty_result:
            print("✅ Empty search data handled correctly")
        else:
            print("❌ Empty search data not handled properly")
            return False

        return True

    except Exception as e:
        print(f"❌ Error in error scenarios test: {e}")
        return False


async def run_simple_tests():
    """Run all simple tests"""
    print("🚀 Starting Simple Search Result Feature Tests\n")
    print("=" * 60)

    tests = [
        ("FlightOption Creation", test_flight_option_creation),
        ("SearchResult Creation", test_search_result_creation),
        ("Core Functionality", test_search_result_manager_core),
        ("Error Scenarios", test_error_scenarios)
    ]

    results = []
    passed = 0

    for test_name, test_func in tests:
        print(f"\n{'='*20} {test_name} {'='*20}")
        try:
            result = await test_func()
            results.append((test_name, result))
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"\n{status}")
            if result:
                passed += 1
        except Exception as e:
            results.append((test_name, False))
            print(f"\n❌ FAILED with exception: {e}")

    # Summary
    print(f"\n{'='*60}")
    print("📊 TEST SUMMARY")
    print(f"{'='*60}")

    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name:<25} {status}")

    print(f"\n🎯 Overall: {passed}/{len(results)} tests passed")

    if passed == len(results):
        print("🎉 All tests passed! Core functionality is working correctly.")
        return True
    else:
        print("⚠️ Some tests failed. Please check the implementation.")
        return False


if __name__ == "__main__":
    success = asyncio.run(run_simple_tests())

    if success:
        print("\n🎉 All tests completed successfully!")
        print("\n📋 Next Steps:")
        print("1. Run the full test suite with Redis: python tests/test_search_result_features.py")
        print("2. Test with actual LangGraph integration")
        print("3. Test with real Travelport API responses")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed. Please review the implementation.")
        sys.exit(1)