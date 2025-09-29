"""
Redis connection manager for the application
"""
import redis.asyncio as redis
import os
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class RedisManager:
    """
    Manages Redis connections for the application
    """
    def __init__(self):
        self._redis = None
        self._redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._max_connections = int(os.getenv("REDIS_MAX_CONNECTIONS", "20"))
    
    async def get_connection(self) -> redis.Redis:
        """
        Get or create Redis connection
        """
        if self._redis is None:
            try:
                # Create Redis connection pool
                connection_pool = redis.ConnectionPool.from_url(
                    self._redis_url,
                    max_connections=self._max_connections,
                    decode_responses=True
                )
                self._redis = redis.Redis(connection_pool=connection_pool)
                
                # Test connection
                await self._redis.ping()
                logger.info(f"Connected to Redis at {self._redis_url}")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise
        return self._redis

    async def close_connection(self):
        """
        Close Redis connection
        """
        if self._redis:
            await self._redis.close()
            self._redis = None

# Create global instance
redis_manager = RedisManager()