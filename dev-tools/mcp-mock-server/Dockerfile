FROM python:3.12-slim

WORKDIR /app

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Copy the mock server script
COPY dev-tools/mcp-mock-server/server.py .

# Expose HTTP port (we'll only use HTTP in Docker for simplicity)
EXPOSE 3000

# Run the mock server (HTTP only on port 3000)
CMD ["python", "server.py", "3000"]
