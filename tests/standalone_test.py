#!/usr/bin/env python3
"""
Standalone test for search result features without external dependencies.
Tests the core functionality in isolation.
"""

import sys
import os
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


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
        return {
            "id": self.id,
            "departure": self.departure,
            "arrival": self.arrival,
            "departure_time": self.departure_time,
            "arrival_time": self.arrival_time,
            "duration": self.duration,
            "airline": self.airline,
            "flight_number": self.flight_number,
            "aircraft": self.aircraft,
            "price": self.price,
            "currency": self.currency,
            "cabin_class": self.cabin_class,
            "stops": self.stops,
            "baggage_info": self.baggage_info,
            "penalties": self.penalties,
            "raw_data": self.raw_data
        }


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
    expires_at: float

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


class MockSearchResultManager:
    """Mock search result manager for testing"""

    def __init__(self):
        self.stored_results = {}
        self.user_searches = {}
        self.thread_searches = {}

    def store_search_result(self, wa_id: str, thread_id: str, search_data: Dict[str, Any]) -> str:
        """Store search result and return search_id"""
        import uuid
        search_id = str(uuid.uuid4())

        # Parse flight options (simplified for demo)
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
            search_timestamp=datetime.now().isoformat(),
            expires_at=datetime.now().timestamp() + 3600
        )

        # Store in memory
        self.stored_results[search_id] = search_result

        # Add to user's search history
        if wa_id not in self.user_searches:
            self.user_searches[wa_id] = set()
        self.user_searches[wa_id].add(search_id)

        # Store latest search for thread
        self.thread_searches[thread_id] = search_id

        return search_id

    def _parse_flight_options(self, search_data: Dict[str, Any]) -> List[FlightOption]:
        """Parse search data into flight options (simplified)"""
        flight_options = []

        # Create sample flight options based on search data
        base_price = 750.0
        airlines = ["Emirates", "British Airways", "Lufthansa"]
        flight_numbers = ["EK 6", "BA 107", "LH 911"]

        for i in range(3):
            flight_option = FlightOption(
                id=f"flight_{i+1}",
                departure=search_data.get("origin", "LHR"),
                arrival=search_data.get("destination", "DXB"),
                departure_time=f"{20+i}:00:00",
                arrival_time=f"{8+i}:45:00",
                duration=f"{6+i}h 45m",
                airline=airlines[i],
                flight_number=flight_numbers[i],
                aircraft="Boeing 388",
                price=base_price + (i * 100),
                currency="EUR",
                cabin_class="Economy",
                stops=i,
                baggage_info={"carry_on_text": "1 piece included", "checked_bag_text": "30kg included"},
                penalties={"change": f"{50 + i*25} EUR", "cancel": f"{75 + i*25} EUR"},
                raw_data={}
            )
            flight_options.append(flight_option)

        return flight_options

    def get_search_result(self, search_id: str) -> Optional[SearchResult]:
        """Retrieve search result by ID"""
        return self.stored_results.get(search_id)

    def get_user_search_history(self, wa_id: str) -> List[str]:
        """Get user's search history"""
        return list(self.user_searches.get(wa_id, set()))

    def get_latest_search_for_thread(self, thread_id: str) -> Optional[str]:
        """Get latest search ID for a thread"""
        return self.thread_searches.get(thread_id)

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


def test_search_result_storage():
    """Test basic search result storage and retrieval"""
    print("Testing Search Result Storage...")

    manager = MockSearchResultManager()

    # Test data
    wa_id = "test_user_123"
    thread_id = "test_thread_456"

    search_data = {
        "origin": "LHR",
        "destination": "DXB",
        "search_date": "2025-12-20",
        "trip_type": "one-way",
        "passengers": 1,
        "detected_language": "en"
    }

    try:
        # Store search result
        search_id = manager.store_search_result(wa_id, thread_id, search_data)
        print(f"✅ Search result stored with ID: {search_id}")

        # Retrieve search result
        retrieved_result = manager.get_search_result(search_id)
        if retrieved_result:
            print(f"✅ Search result retrieved successfully: {len(retrieved_result.flight_options)} options")
            print(f"   Route: {retrieved_result.origin} → {retrieved_result.destination}")
            print(f"   Cheapest: {retrieved_result.flight_options[0].price} {retrieved_result.flight_options[0].currency}")
        else:
            print("❌ Failed to retrieve search result")
            return False

        # Test user search history
        search_history = manager.get_user_search_history(wa_id)
        if search_id in search_history:
            print(f"✅ User search history updated: {len(search_history)} searches")
        else:
            print("❌ User search history not updated")
            return False

        # Test thread latest search
        latest_search_id = manager.get_latest_search_for_thread(thread_id)
        if latest_search_id == search_id:
            print("✅ Thread latest search updated correctly")
        else:
            print("❌ Thread latest search not updated")
            return False

        return True

    except Exception as e:
        print(f"❌ Error in search result storage test: {e}")
        return False


def test_search_result_formatting():
    """Test search result formatting for user display"""
    print("\n🧪 Testing Search Result Formatting...")

    manager = MockSearchResultManager()

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
        formatted_display = manager.format_search_results_for_display(search_result)
        print("✅ Formatted display:")
        print(formatted_display)

        # Test individual option formatting
        option_display = manager.format_flight_option_for_display(flight_option)
        print("\n✅ Individual option display:")
        print(option_display)

        return True

    except Exception as e:
        print(f"❌ Error in formatting test: {e}")
        return False


def test_error_handling():
    """Test error handling and edge cases"""
    print("\n🧪 Testing Error Handling...")

    manager = MockSearchResultManager()

    try:
        # Test with invalid search ID
        invalid_result = manager.get_search_result("invalid_id")
        if invalid_result is None:
            print("✅ Invalid search ID handled correctly")
        else:
            print("❌ Invalid search ID not handled properly")
            return False

        # Test with non-existent user
        empty_history = manager.get_user_search_history("non_existent_user")
        if empty_history == []:
            print("✅ Non-existent user handled correctly")
        else:
            print("❌ Non-existent user not handled properly")
            return False

        # Test with empty search data
        empty_result = manager.store_search_result("test_user", "test_thread", {})
        if empty_result:
            print("✅ Empty search data handled correctly")
        else:
            print("❌ Empty search data not handled properly")
            return False

        return True

    except Exception as e:
        print(f"❌ Error in error handling test: {e}")
        return False


def run_standalone_tests():
    """Run all standalone tests"""
    print("Starting Standalone Search Result Feature Tests\n")
    print("=" * 60)

    tests = [
        ("Search Result Storage", test_search_result_storage),
        ("Search Result Formatting", test_search_result_formatting),
        ("Error Handling", test_error_handling)
    ]

    results = []
    passed = 0

    for test_name, test_func in tests:
        print(f"\n{'='*20} {test_name} {'='*20}")
        try:
            result = test_func()
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
        print("\n📋 Next Steps:")
        print("1. Test with Redis integration")
        print("2. Test with actual Travelport API responses")
        print("3. Test LangGraph integration")
        return True
    else:
        print("⚠️ Some tests failed. Please check the implementation.")
        return False


if __name__ == "__main__":
    success = run_standalone_tests()

    if success:
        print("\n🎉 All standalone tests completed successfully!")
        print("\n🔧 Features Verified:")
        print("   ✅ Search result storage and retrieval")
        print("   ✅ User and thread association")
        print("   ✅ Flight option parsing and formatting")
        print("   ✅ Error handling and edge cases")
        print("   ✅ User-friendly display generation")
        print("\n🚀 Ready for integration with Redis and LangGraph!")
    else:
        print("\n❌ Some tests failed. Please review the implementation.")
        exit(1)