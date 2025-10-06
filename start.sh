#!/bin/bash
set -e

# Start Redis server with custom configuration for 512MB instance
redis-server /app/redis.conf --daemonize yes
echo "Redis server started"

# Wait a moment for Redis to be ready
sleep 2

# Check if Redis is responding
if ! redis-cli ping; then
    echo "Failed to connect to Redis"
    exit 1
fi

echo "Redis is ready, starting the application"

# Start the main application
exec python main.py "$@"