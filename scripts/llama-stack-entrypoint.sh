#!/bin/bash
# Entrypoint for llama-stack container.
# Enriches config with lightspeed dynamic values, then starts llama-stack.

set -e

INPUT_CONFIG="${LLAMA_STACK_CONFIG:-/opt/app-root/run.yaml}"
ENRICHED_CONFIG="/opt/app-root/run.yaml"
LIGHTSPEED_CONFIG="${LIGHTSPEED_CONFIG:-/opt/app-root/lightspeed-stack.yaml}"
ENV_FILE="/opt/app-root/.env"

# Enrich config if lightspeed config exists
if [ -f "$LIGHTSPEED_CONFIG" ]; then
    echo "Enriching llama-stack config..."
    python3 /opt/app-root/llama_stack_configuration.py \
        -c "$LIGHTSPEED_CONFIG" \
        -i "$INPUT_CONFIG" \
        -o "$ENRICHED_CONFIG" \
        -e "$ENV_FILE" 2>&1 || true

    # Source .env if generated (contains AZURE_API_KEY)
    if [ -f "$ENV_FILE" ]; then
        # shellcheck source=/dev/null
        set -a && . "$ENV_FILE" && set +a
    fi

    if [ -f "$ENRICHED_CONFIG" ]; then
        echo "Using enriched config: $ENRICHED_CONFIG"
        exec llama stack run "$ENRICHED_CONFIG"
    fi
fi

echo "Using original config: $INPUT_CONFIG"
exec llama stack run "$INPUT_CONFIG"

