#!/bin/bash

set -euo pipefail

PIPELINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$PIPELINE_DIR/scripts/bootstrap.sh" "$PIPELINE_DIR"
"$PIPELINE_DIR/scripts/gpu-setup.sh" "$PIPELINE_DIR"
source "$PIPELINE_DIR/scripts/fetch-vllm-image.sh"
"$PIPELINE_DIR/scripts/deploy-vllm.sh" "$PIPELINE_DIR"
"$PIPELINE_DIR/scripts/get-vllm-pod-info.sh" 