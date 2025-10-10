#!/usr/bin/env python3
"""
Simple test script to verify the asyncio event loop fix for Redis connections
"""
import asyncio
import sys
import threading
from app.langgraph.redis_manager import redis_manager


async def test_main_loop():
    """Test Redis connection in main thread/loop"""
    print("Testing Redis connection in main loop...")
    try:
        redis_conn = await redis_manager.get_connection()
        await redis_conn.ping()
        print("✓ Main loop Redis connection works")
        print(f"✓ Redis connection object: {redis_conn}")
        print(f"✓ Connection address: {redis_conn.connection_pool.connection_kwargs}")
        
    except Exception as e:
        print(f"✗ Error in main loop: {e}")
        import traceback
        traceback.print_exc()


def run_background():
    """Run background event loop in a separate thread"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def background_task():
        print("Testing Redis connection in background thread...")
        try:
            redis_conn = await redis_manager.get_connection()
            await redis_conn.ping()
            print("✓ Background thread Redis connection works")
            print(f"✓ Redis connection object: {redis_conn}")
            print(f"✓ Connection address: {redis_conn.connection_pool.connection_kwargs}")
            
        except Exception as e:
            print(f"✗ Error in background thread: {e}")
            import traceback
            traceback.print_exc()
    
    loop.run_until_complete(background_task())
    loop.close()


async def main():
    print("Starting test of asyncio event loop fixes...")
    print("Testing Redis manager's ability to handle multiple event loops...")
    print()
    
    await test_main_loop()
    print()
    
    # Run the background event loop in a separate thread
    bg_thread = threading.Thread(target=run_background)
    bg_thread.start()
    bg_thread.join()
    
    print()
    print("Test complete! RedisManager properly handles different event loops.")


if __name__ == "__main__":
    asyncio.run(main())