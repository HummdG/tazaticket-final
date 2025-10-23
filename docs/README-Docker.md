# LangGraph Application - Docker Deployment

This document provides instructions for building and running the LangGraph application using Docker.

## Quick Start

### Using Docker Compose (Recommended)

1. **Build and run the application:**

   ```bash
   docker-compose up --build
   ```

2. **Run in detached mode:**

   ```bash
   docker-compose up -d --build
   ```

3. **View logs:**

   ```bash
   docker-compose logs -f
   ```

4. **Stop the application:**
   ```bash
   docker-compose down
   ```

### Using Docker directly

1. **Build the image:**

   ```bash
   docker build -t langgraph-app .
   ```

2. **Run the container:**

   ```bash
   docker run -p 8000:8000 langgraph-app
   ```

3. **Run with environment variables:**
   ```bash
   docker run -p 8000:8000 \
     -e OPENAI_API_KEY=your_key \
     -e AWS_ACCESS_KEY_ID=your_key \
     -e AWS_SECRET_ACCESS_KEY=your_secret \
     langgraph-app
   ```

## Environment Variables

The application requires several environment variables. Create a `.env` file in the project root:

```env
# OpenAI Configuration (Required)
OPENAI_API_KEY=your_openai_api_key

# Travelport Configuration (Required for flight search)
TRAVELPORT_USERNAME=your_travelport_username
TRAVELPORT_PASSWORD=your_travelport_password
TRAVELPORT_CLIENT_ID=your_travelport_client_id
TRAVELPORT_CLIENT_SECRET=your_travelport_client_secret
TRAVELPORT_PCC=your_travelport_pcc
TRAVELPORT_ACCESS_GROUP=your_travelport_access_group
TRAVELPORT_BASE_URL=your_travelport_base_url

# Twilio Configuration (Required for WhatsApp)
TWILIO_ACCOUNT_SID=your_twilio_account_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886

# AWS Configuration (Required)
AWS_ACCESS_KEY_ID=your_aws_access_key_id
AWS_SECRET_ACCESS_KEY=your_aws_secret_access_key
AWS_REGION=eu-north-1
CHAT_HISTORY_TABLE=ChatHistory
S3_VOICE_BUCKET=tazaticket
S3_VOICE_PREFIX=voices/
S3_PRESIGNED_TTL=3600

# Memory Manager Configuration
SESSION_IDLE_SECONDS=21600
CONTEXT_PAIRS=12
BATCH_PAIRS=1
MAX_RAM_PAIRS=13
```

Then uncomment the `env_file` section in `docker-compose.yml`.

## Image Optimization Features

This Docker setup includes several optimizations for a lightweight, secure image:

- **Multi-stage build**: Separates build dependencies from runtime
- **Python slim base**: Uses `python:3.11-slim` for minimal size
- **Non-root user**: Runs application as non-privileged user
- **Layer caching**: Optimized layer order for faster rebuilds
- **Minimal dependencies**: Only installs necessary runtime packages
- **Health checks**: Built-in health monitoring
- **Security**: No unnecessary packages or permissions

## Production Deployment

### Environment-specific builds

For production, you may want to create environment-specific images:

```bash
# Production build
docker build -t langgraph-app:prod --target production .

# Development build with additional tools
docker build -t langgraph-app:dev --target builder .
```

### Resource limits

For production deployment, consider adding resource limits to `docker-compose.yml`:

```yaml
services:
  langgraph-app:
    # ... other config
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 512M
        reservations:
          cpus: "0.5"
          memory: 256M
```

## Troubleshooting

### Check application health

```bash
curl http://localhost:8000/
```

### View container logs

```bash
docker logs <container_id>
```

### Debug inside container

```bash
docker exec -it <container_id> /bin/bash
```

### Check image size

```bash
docker images langgraph-app
```

## Security Notes

- The application runs as a non-root user (`app`)
- No unnecessary system packages are installed
- Build dependencies are removed in the final image
- Health checks ensure the application is responsive
- Environment variables should be properly secured in production
