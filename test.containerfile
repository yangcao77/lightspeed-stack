# Custom Red Hat llama-stack image with missing dependencies
FROM quay.io/rhoai/odh-llama-stack-core-rhel9:rhoai-3.2 

# Install missing dependencies and create required directories
USER root
RUN pip install faiss-cpu==1.11.0 && \
    mkdir -p /app-root && \
    chown -R 1001:0 /app-root && \
    chmod -R 775 /app-root && \
    mkdir -p /opt/app-root/src/.llama/storage /opt/app-root/src/.llama/providers.d && \
    chown -R 1001:0 /opt/app-root/src/.llama

# Switch back to the original user
USER 1001
