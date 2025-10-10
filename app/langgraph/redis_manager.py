"""
Redis connection manager for the application
"""
import redis.asyncio as redis
import os
import asyncio
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class RedisManager:
    """
    Manages Redis connections for the application
    """
    def __init__(self):
        self._redis_connections = {}  # Store connections per event loop
        self._redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._max_connections = int(os.getenv("REDIS_MAX_CONNECTIONS", "20"))
    
    async def get_connection(self) -> redis.Redis:
        """
        Get or create Redis connection for the current event loop
        """
        # Get the current event loop
        loop = asyncio.get_running_loop()
        loop_id = id(loop)
        
        # Check if we already have a connection for this loop
        if loop_id not in self._redis_connections:
            try:
                # Create Redis connection pool
                connection_pool = redis.ConnectionPool.from_url(
                    self._redis_url,
                    max_connections=self._max_connections,
                    decode_responses=True
                )
                self._redis_connections[loop_id] = redis.Redis(connection_pool=connection_pool)
                
                # Test connection
                await self._redis_connections[loop_id].ping()
                logger.info(f"Connected to Redis at {self._redis_url} for loop {loop_id}")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise
        
        return self._redis_connections[loop_id]

    async def close_connection(self):
        """
        Close Redis connections
        """
        # Close all connections for all loops
        for conn in self._redis_connections.values():
            if conn:
                await conn.close()
        self._redis_connections.clear()

# Create global instance
redis_manager = RedisManager()