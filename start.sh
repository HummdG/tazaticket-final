#!/bin/bash
set -e

# Start Redis server with custom configuration for 512MB instance
redis-server /app/redis.conf --daemonize yes
echo "Redis server started"

# Wait for Redis to be ready with retry logic
echo "Waiting for Redis to be ready..."
max_attempts=30
attempt=1
while [ $attempt -le $max_attempts ]; do
    if redis-cli ping > /dev/null 2>&1; then
        echo "Redis is ready!"
        break
    else
        echo "Attempt $attempt/$max_attempts: Redis not ready yet, waiting..."
        sleep 1
        ((attempt++))
    fi
done

if [ $attempt -gt $max_attempts ]; then
    echo "Failed to connect to Redis after $max_attempts attempts"
    exit 1
fi

echo "Redis is ready, starting the application"

# Start the main application
exec python main.py "$@"