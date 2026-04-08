FROM python:3.12-slim
WORKDIR /app

# Install trustme for dynamic certificate generation
RUN pip install --no-cache-dir trustme

# Copy server script
COPY server.py .

# Create /certs directory for generated certificates
RUN mkdir -p /certs

EXPOSE 8443 8444
CMD ["python", "server.py"]
