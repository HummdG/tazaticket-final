#!/usr/bin/env python3
"""
Test script to verify the asyncio event loop fix for Redis connections
"""
import asyncio
import sys
import threading
from app.langgraph.redis_manager import redis_manager
from app.langgraph.graph_config import create_graph, invoke_graph


async def test_main_loop():
    """Test Redis connection in main thread/loop"""
    print("Testing Redis connection in main loop...")
    try:
        redis_conn = await redis_manager.get_connection()
        await redis_conn.ping()
        print("✓ Main loop Redis connection works")
        
        # Test graph creation and invocation
        print("Testing graph creation...")
        graph = create_graph()
        print("✓ Graph created successfully in main loop")
        
        print("Testing graph invocation...")
        state = await invoke_graph(graph, "Hello, this is a test message", "test-thread-main", is_voice=False)
        print("✓ Graph invocation successful in main loop")
        
    except Exception as e:
        print(f"✗ Error in main loop: {e}")
        import traceback
        traceback.print_exc()


async def test_background_loop():
    """Test Redis connection in background thread with its own event loop"""
    print("Testing Redis connection in background thread...")
    try:
        # Create a new event loop for the background thread
        def run_background():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def background_task():
                redis_conn = await redis_manager.get_connection()
                await redis_conn.ping()
                print("✓ Background thread Redis connection works")
                
                # Test graph creation and invocation
                print("Testing graph creation in background thread...")
                graph = create_graph()
                print("✓ Graph created successfully in background thread")
                
                print("Testing graph invocation in background thread...")
                state = await invoke_graph(graph, "Hello, this is a test message in background", "test-thread-bg", is_voice=False)
                print("✓ Graph invocation successful in background thread")
                
            loop.run_until_complete(background_task())
            loop.close()
            
        # Run the background event loop in a separate thread
        bg_thread = threading.Thread(target=run_background)
        bg_thread.start()
        bg_thread.join()
        
    except Exception as e:
        print(f"✗ Error in background thread: {e}")
        import traceback
        traceback.print_exc()


async def main():
    print("Starting test of asyncio event loop fixes...")
    print()
    
    await test_main_loop()
    print()
    await test_background_loop()
    
    print()
    print("Test complete!")


if __name__ == "__main__":
    asyncio.run(main())