#!/bin/bash

# Script to generate local-run.yaml from run.yaml
# Replaces ~/ with the user's home directory

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Get the parent directory (project root where run.yaml is located)
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Input and output files
INPUT_FILE="${PROJECT_ROOT}/run.yaml"
OUTPUT_FILE="${PROJECT_ROOT}/local-run.yaml"

# Check if run.yaml exists
if [ ! -f "$INPUT_FILE" ]; then
    echo "Error: run.yaml not found at $INPUT_FILE" >&2
    exit 1
fi

# Replace ~/ with $HOME/ and write to local-run.yaml
sed "s|~/|$HOME/|g" "$INPUT_FILE" > "$OUTPUT_FILE"

echo "Successfully generated $OUTPUT_FILE"
