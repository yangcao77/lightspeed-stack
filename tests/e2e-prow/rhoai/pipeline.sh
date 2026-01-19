#!/bin/bash
set -euo pipefail
trap 'echo "❌ Pipeline failed at line $LINENO"; exit 1' ERR


#========================================
# 1. GLOBAL CONFIG
#========================================
NAMESPACE="e2e-rhoai-dsc"
MODEL_NAME="meta-llama/Llama-3.2-1B-Instruct"
PIPELINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Get llama-stack image from GitHub Containerfile
echo "Fetching llama-stack image from GitHub..."
LLAMA_STACK_IMAGE=$(curl -sL https://raw.githubusercontent.com/lightspeed-core/lightspeed-stack/main/test.containerfile | grep -m1 '^FROM' | awk '{print $2}')
if [ -z "$LLAMA_STACK_IMAGE" ]; then
  echo "❌ Failed to fetch llama-stack image from GitHub"
  exit 1
fi
echo "  -> Found llama-stack image: $LLAMA_STACK_IMAGE"
export LLAMA_STACK_IMAGE

#========================================
# 2. ENVIRONMENT SETUP
#========================================
echo "===== Setting up environment variables ====="
export HUGGING_FACE_HUB_TOKEN=$(cat /var/run/huggingface/hf-token-ces-lcore-test || true)
export VLLM_API_KEY=$(cat /var/run/vllm/vllm-api-key-lcore-test || true)
export QUAY_ROBOT_NAME=$(cat /var/run/quay-aipcc-name/lcore-quay-name-lcore-test || true)
export QUAY_ROBOT_PASSWORD=$(cat /var/run/quay-aipcc-password/lcore-quay-password-lcore-test || true)


[[ -n "$HUGGING_FACE_HUB_TOKEN" ]] && echo "✅ HUGGING_FACE_HUB_TOKEN is set" || { echo "❌ Missing HUGGING_FACE_HUB_TOKEN"; exit 1; }
[[ -n "$VLLM_API_KEY" ]] && echo "✅ VLLM_API_KEY is set" || { echo "❌ Missing VLLM_API_KEY"; exit 1; }
[[ -n "$QUAY_ROBOT_NAME" ]] && echo "✅ QUAY_ROBOT_NAME is set" || { echo "❌ Missing QUAY_ROBOT_NAME"; exit 1; }
[[ -n "$QUAY_ROBOT_PASSWORD" ]] && echo "✅ QUAY_ROBOT_PASSWORD is set" || { echo "❌ Missing QUAY_ROBOT_PASSWORD"; exit 1; }

# Basic info
ls -A || true
oc version
oc whoami

#========================================
# 3. CREATE NAMESPACE & SECRETS
#========================================
echo "===== Creating namespace & secrets ====="
oc get ns "$NAMESPACE" >/dev/null 2>&1 || oc create namespace "$NAMESPACE"

# Create NFD and NVIDIA namespaces
oc apply -f "$PIPELINE_DIR/manifests/namespaces/nfd.yaml"
oc apply -f "$PIPELINE_DIR/manifests/namespaces/nvidia-operator.yaml"


create_secret() {
    local name=$1; shift
    echo "Creating secret $name..."
    oc create secret generic "$name" "$@" -n "$NAMESPACE" 2>/dev/null || echo "Secret $name exists"
}

create_secret hf-token-secret --from-literal=token="$HUGGING_FACE_HUB_TOKEN"
create_secret vllm-api-key-secret --from-literal=key="$VLLM_API_KEY"

# Create Quay pull secret for llama-stack images
echo "Creating Quay pull secret..."
oc create secret docker-registry quay-lightspeed-pull-secret \
  --docker-server=quay.io \
  --docker-username="$QUAY_ROBOT_NAME" \
  --docker-password="$QUAY_ROBOT_PASSWORD" \
  -n "$NAMESPACE" 2>/dev/null && echo "✅ Quay pull secret created" || echo "⚠️  Secret exists or creation failed"

# Link the secret to default service account for image pulls
oc secrets link default quay-lightspeed-pull-secret --for=pull -n "$NAMESPACE" 2>/dev/null || echo "⚠️  Secret already linked to default SA"


#========================================
# 4. CONFIGMAPS
#========================================
echo "===== Setting up configmaps ====="

curl -sL -o tool_chat_template_llama3.2_json.jinja \
    https://raw.githubusercontent.com/vllm-project/vllm/main/examples/tool_chat_template_llama3.2_json.jinja \
    || { echo "❌ Failed to download jinja template"; exit 1; }

oc create configmap vllm-chat-template -n "$NAMESPACE" \
    --from-file=tool_chat_template_llama3.2_json.jinja --dry-run=client -o yaml | oc apply -f -


#========================================
# 5. DEPLOY vLLM
#========================================
echo "===== Deploying vLLM ====="
./pipeline-vllm.sh
oc get pods -n "$NAMESPACE"


#========================================
# 6. WAIT FOR POD & TEST API
#========================================
source pod.env
oc wait --for=condition=Ready pod/$POD_NAME -n $NAMESPACE --timeout=300s

echo "===== Testing vLLM endpoint ====="
start_time=$(date +%s)
timeout=200

while true; do
  # Create a temporary pod for testing (if it doesn't exist)
  if ! oc get pod vllm-test-curl -n "$NAMESPACE" &>/dev/null; then
    oc run vllm-test-curl --image=curlimages/curl:latest \
      --restart=Never -n "$NAMESPACE" -- sleep 3600
    oc wait --for=condition=Ready pod/vllm-test-curl -n "$NAMESPACE" --timeout=60s
  fi

  # Execute curl inside the pod and capture response
  response=$(oc exec vllm-test-curl -n "$NAMESPACE" -- \
      curl -sk -w '\n%{http_code}' \
      -H 'Content-Type: application/json' \
      -H "Authorization: Bearer $VLLM_API_KEY" \
      -d "{
          \"model\": \"$MODEL_NAME\",
          \"prompt\": \"Who won the world series in 2020?\",
          \"max_new_tokens\": 100
          }" \
      "$KSVC_URL/v1/completions" 2>&1 || echo -e "\n000")

  # Extract HTTP code from last line
  http_code=$(echo "$response" | tail -1 | tr -d '[:space:]')
  # Extract body from all lines except last
  body=$(echo "$response" | sed '$d')

  if [[ "$http_code" == "200" && "$body" == *'"object":"text_completion"'* ]]; then
    echo "✅ API test passed."
    echo "$body" | jq . 2>/dev/null || echo "$body"
    break
  else
    echo "❌ API test failed (HTTP $http_code)"
    echo "$body" | jq . 2>/dev/null || echo "$body"
  fi

  current_time=$(date +%s)
  elapsed=$((current_time - start_time))

  if (( elapsed >= timeout )); then
      echo "⏰ Timeout reached ($timeout seconds). Stopping test."
      oc delete pod vllm-test-curl -n "$NAMESPACE" --ignore-not-found=true
      exit 1
  fi

  sleep 20
done

# Cleanup test pod
oc delete pod vllm-test-curl -n "$NAMESPACE" --ignore-not-found=true


#========================================
# 7. DEPLOY LIGHTSPEED STACK AND LLAMA STACK
#========================================
echo "===== Deploying Services ====="

create_secret api-url-secret --from-literal=key="$KSVC_URL"
oc create configmap llama-stack-config -n "$NAMESPACE" --from-file=configs/run.yaml
oc create configmap lightspeed-stack-config -n "$NAMESPACE" --from-file=configs/lightspeed-stack.yaml
oc create configmap test-script-cm -n "$NAMESPACE" --from-file=run-tests.sh

./pipeline-services.sh

echo "--> Final wait for both lightspeed-stack-service and llama-stack-service pods..."
if ! oc wait pod/lightspeed-stack-service pod/llama-stack-service \
    -n "$NAMESPACE" --for=condition=Ready --timeout=600s; then
  echo ""
  echo "❌ One or both service pods failed to become ready within timeout"
  echo ""
  echo "DEBUG: Pod status:"
  oc get pods -n "$NAMESPACE" -o wide || true
  echo ""
  echo "DEBUG: lightspeed-stack-service description:"
  oc describe pod lightspeed-stack-service -n "$NAMESPACE" || true
  echo ""
  echo "DEBUG: llama-stack-service description:"
  oc describe pod llama-stack-service -n "$NAMESPACE" || true
  echo ""
  echo "DEBUG: lightspeed-stack-service logs:"
  oc logs lightspeed-stack-service -n "$NAMESPACE" --tail=100 || true
  echo ""
  echo "DEBUG: llama-stack-service logs:"
  oc logs llama-stack-service -n "$NAMESPACE" --tail=100 || true
  echo ""
  echo "DEBUG: Recent events in namespace:"
  oc get events -n "$NAMESPACE" --sort-by='.lastTimestamp' | tail -20 || true
  exit 1
fi
echo "✅ Both service pods are ready"
sleep 30

oc get pods -n "$NAMESPACE"

echo "logs lightspeed"
oc logs lightspeed-stack-service -n "$NAMESPACE" || true
echo "logs llama"
oc logs llama-stack-service -n "$NAMESPACE" || true

oc describe pod lightspeed-stack-service -n "$NAMESPACE" || true
oc describe pod llama-stack-service -n "$NAMESPACE" || true


#========================================
# 8. EXTRACT LCS IP & STORE
#========================================
oc label pod lightspeed-stack-service pod=lightspeed-stack-service -n $NAMESPACE

oc expose pod lightspeed-stack-service \
  --name=lightspeed-stack-service-svc \
  --port=8080 \
  --type=ClusterIP \
  -n $NAMESPACE

E2E_LSC_HOSTNAME="lightspeed-stack-service-svc.$NAMESPACE.svc.cluster.local"
echo "LCS IP: $E2E_LSC_HOSTNAME"

create_secret lcs-ip-secret --from-literal=key="$E2E_LSC_HOSTNAME"


#========================================
# 9. LOGGING & TEST EXECUTION
#========================================
echo "===== Running test pod ====="
./pipeline-test-pod.sh 

sleep 20
oc get pods -n "$NAMESPACE"

# Wait until tests are complete
oc wait --for=condition=Ready=True pod/test-pod -n $NAMESPACE --timeout=900s || oc wait --for=condition=Ready=False pod/test-pod -n $NAMESPACE --timeout=60s

start_time=$(date +%s)
timeout=2400
while true; do
  sleep 120
  
  PHASE=$(oc get pod test-pod -n $NAMESPACE -o jsonpath='{.status.phase}')
  echo "Current phase test-pod: $PHASE"
  if [[ "$PHASE" == "Succeeded" || "$PHASE" == "Failed" ]]; then
      break
  fi

  current_time=$(date +%s)
  elapsed=$((current_time - start_time))

  if (( elapsed >= timeout )); then
      echo "⏰ Timeout reached ($timeout seconds). Stopping test."
      exit 1
  fi

  oc get pods -n "$NAMESPACE"
done
oc logs test-pod -n $NAMESPACE || oc describe pod test-pod -n $NAMESPACE || true


TEST_EXIT_CODE=$(oc get pod test-pod -n $NAMESPACE -o jsonpath='{.status.containerStatuses[0].state.terminated.exitCode}')

echo "===== E2E COMPLETE ====="

if [ "${TEST_EXIT_CODE:-2}" -ne 0 ]; then
    echo "❌ E2E tests failed with exit code $TEST_EXIT_CODE (pod/test-pod failed)"
else
    echo "✅ E2E tests succeeded"
fi

exit $TEST_EXIT_CODE