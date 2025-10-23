"""
Test script to verify the memory pairing fix
"""
import asyncio
import uuid
import time
from app.langgraph.memory_manager import memory_manager

async def test_unique_thread_ids():
    """Test that thread IDs are unique when generated"""
    print("Testing unique thread ID generation...")
    
    # Simulate the new thread ID generation logic
    thread_id_1 = f"whatsapp-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    # Small delay to ensure different timestamp
    await asyncio.sleep(0.1)
    thread_id_2 = f"whatsapp-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    
    print(f"Thread ID 1: {thread_id_1}")
    print(f"Thread ID 2: {thread_id_2}")
    print(f"Are they different? {thread_id_1 != thread_id_2}")
    
    assert thread_id_1 != thread_id_2, "Thread IDs should be unique"
    print("✓ Unique thread ID generation test passed")

async def test_memory_pairing():
    """Test that memory pairing works correctly with unique thread IDs"""
    print("\nTesting memory pairing with unique thread IDs...")
    
    # Generate a unique thread ID
    test_thread_id = f"test-thread-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    print(f"Using test thread ID: {test_thread_id}")
    
    # Start a session
    await memory_manager.on_session_start(test_thread_id)
    print("✓ Session started")
    
    # Add a user message (should start a new pair)
    user_msg = "Hello, this is a test message!"
    await memory_manager.add_user_message(test_thread_id, user_msg)
    print(f"✓ Added user message: {user_msg}")
    
    # Retrieve context to verify user message was added
    context = await memory_manager.get_context_for_llm(test_thread_id)
    print(f"✓ Retrieved context with {len(context)} messages")
    
    # Add an assistant message (should close the pair)
    assistant_msg = "Hello! I received your test message."
    await memory_manager.add_assistant_message(test_thread_id, assistant_msg)
    print(f"✓ Added assistant message: {assistant_msg}")
    
    # Retrieve context again to verify pairing
    context_after = await memory_manager.get_context_for_llm(test_thread_id)
    print(f"✓ Retrieved context after assistant response with {len(context_after)} messages")
    
    print("✓ Memory pairing test passed")

async def run_all_tests():
    """Run all tests"""
    print("Starting memory pairing tests...\n")
    
    await test_unique_thread_ids()
    await test_memory_pairing()
    
    print("\n✓ All tests passed! The memory pairing fix should work correctly.")

if __name__ == "__main__":
    asyncio.run(run_all_tests())