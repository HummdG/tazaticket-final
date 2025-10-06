# Use Python 3.11 slim as base image for smaller size
FROM python:3.11-slim AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies needed for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create and use a non-root user
RUN useradd --create-home --shell /bin/bash app

# Set work directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.11-slim AS production

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    AWS_REGION=eu-north-1 \
    CHAT_HISTORY_TABLE=ChatHistory \
    S3_VOICE_BUCKET=tazaticket \
    S3_VOICE_PREFIX=voices/ \
    S3_PRESIGNED_TTL=3600 \
    SESSION_IDLE_SECONDS=21600 \
    CONTEXT_PAIRS=12 \
    BATCH_PAIRS=1 \
    MAX_RAM_PAIRS=13

# Install runtime dependencies including Redis
RUN apt-get update && apt-get install -y --no-install-recommends \
    redis-server \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash app

# Copy Python packages from builder stage
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Set work directory
WORKDIR /app

# Copy application code
COPY --chown=app:app . .

# Copy the startup script
COPY --chown=app:app start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Switch to non-root user
USER app

# Expose ports
EXPOSE 8000 6379

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/')" || exit 1

# Run the startup script
CMD ["/app/start.sh"] 