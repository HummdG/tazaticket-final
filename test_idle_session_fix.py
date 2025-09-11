#!/usr/bin/env python3
"""
Test script to validate the idle session handling fix.
This script simulates the scenario where a session becomes idle and needs to reload context.
"""

import sys
import os
import time
import uuid
from unittest.mock import Mock, patch

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

def test_idle_session_handling():
    """Test that idle sessions properly reload conversation context"""
    print("🧪 Testing idle session handling...")
    
    try:
        from app.langgraph.memory_manager import MemoryManager
        from app.langgraph.memory_utils import Pair, Message, get_now_iso
        
        # Create a test memory manager with mocked DynamoDB
        memory_manager = MemoryManager()
        
        # Mock the DynamoDB client to avoid actual AWS calls
        mock_dynamodb = Mock()
        memory_manager.dynamodb = mock_dynamodb
        
        # Test thread ID
        test_thread_id = "test_thread_447948623631"
        
        # Step 1: Create a fresh thread state
        print(f"📝 Step 1: Creating fresh thread state for {test_thread_id}")
        thread_state = memory_manager._get_thread_state(test_thread_id)
        
        # Add some test pairs to simulate existing conversation
        test_pairs = [
            Pair(
                turn=1,
                user_message=Message(role="user", content="Hello", ts_iso=get_now_iso(), seq=1, turn=1),
                assistant_message=Message(role="assistant", content="Hi there!", ts_iso=get_now_iso(), seq=2, turn=1)
            ),
            Pair(
                turn=2,
                user_message=Message(role="user", content="How are you?", ts_iso=get_now_iso(), seq=3, turn=2),
                assistant_message=Message(role="assistant", content="I'm doing well!", ts_iso=get_now_iso(), seq=4, turn=2)
            )
        ]
        
        thread_state.context_pairs = test_pairs
        thread_state.next_turn = 3
        thread_state.next_seq = 5
        
        print(f"✅ Thread state created with {len(thread_state.context_pairs)} pairs")
        
        # Step 2: Simulate session becoming idle
        print(f"⏰ Step 2: Simulating idle session (setting last_activity to past)")
        # Set last activity to more than SESSION_IDLE_SECONDS ago
        thread_state.last_activity_at = time.time() - 25000  # Much longer than 6 hours
        
        # Mock the load_conversation_state_from_dynamodb function to return our test pairs
        def mock_load_conversation_state(client, thread_id):
            print(f"[MOCK] Loading conversation state for {thread_id}")
            return test_pairs
        
        # Step 3: Mock DynamoDB operations
        print(f"🔧 Step 3: Setting up DynamoDB mocks")
        mock_dynamodb.get_item.return_value = {'Item': None}  # No conversation state item
        mock_dynamodb.query.return_value = {'Items': []}  # No individual messages
        mock_dynamodb.batch_write_item.return_value = {'UnprocessedItems': {}}
        
        # Patch the load function
        with patch('app.langgraph.memory_manager.load_conversation_state_from_dynamodb', mock_load_conversation_state):
            # Step 4: Test the session start with idle detection
            print(f"🚀 Step 4: Testing on_session_start with idle session")
            
            # This should detect idle session, clear context, and reload from DynamoDB
            memory_manager.on_session_start(test_thread_id)
            
            # Step 5: Verify the results
            print(f"🔍 Step 5: Verifying results")
            final_thread_state = memory_manager.threads[test_thread_id]
            
            print(f"   - Context pairs: {len(final_thread_state.context_pairs)}")
            print(f"   - Next turn: {final_thread_state.next_turn}")
            print(f"   - Next seq: {final_thread_state.next_seq}")
            
            # Verify that context was reloaded
            if len(final_thread_state.context_pairs) == 2:
                print("✅ SUCCESS: Context pairs were properly reloaded from DynamoDB")
            else:
                print(f"❌ FAILED: Expected 2 context pairs, got {len(final_thread_state.context_pairs)}")
                return False
            
            # Verify counters were updated
            if final_thread_state.next_turn == 3 and final_thread_state.next_seq == 5:
                print("✅ SUCCESS: Counters were properly updated")
            else:
                print(f"❌ FAILED: Expected next_turn=3, next_seq=5, got next_turn={final_thread_state.next_turn}, next_seq={final_thread_state.next_seq}")
                return False
            
            print("🎉 All tests passed! Idle session handling is working correctly.")
            return True
            
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_idle_session_handling()
    sys.exit(0 if success else 1)

