#!/bin/bash
set -e

###############################################################################
# CONFIGURATION: vLLM for Qwen 3.5
###############################################################################

# --- Configuration & Defaults ---
: "${PORT:=8000}"
: "${SERVED_NAME:=${MODEL_ID:-Qwen/Qwen3.5-4B}}"
: "${GPU_MEMORY:=0.9}"
: "${MAX_NUM_BATCHED_TOKENS:=262144}"
: "${MAX_NUM_SEQS:=512}"
: "${MAX_MODEL_LEN:=16384}"

if [ -d "/mnt/models" ]; then
  MODEL_ROOT="/mnt/models"
elif [ -d "/app/model-weights" ]; then
  MODEL_ROOT="/app/model-weights"
else
  MODEL_ROOT="/app/models"
fi

# Append the served model name to the root path to find the actual weights
MODEL_PATH="${MODEL_ROOT}/${SERVED_NAME}"

export PYTHONUNBUFFERED=1

###############################################################################
# Launch vLLM Server
###############################################################################
echo "Starting $SERVED_NAME with vLLM..."

# Multi-token prediction (MTP) is off unless SPECULATIVE_CONFIG is set. The
# Qwen3.5-4B model card recommends:
#   SPECULATIVE_CONFIG='{"method":"qwen3_next_mtp","num_speculative_tokens":2}'
# Speculative decoding usually helps most at low concurrency; measure it at your
# real load before leaving it on.
EXTRA_ARGS=()
if [ -n "${SPECULATIVE_CONFIG:-}" ]; then
  echo "Speculative decoding on: $SPECULATIVE_CONFIG"
  EXTRA_ARGS+=(--speculative-config "$SPECULATIVE_CONFIG")
fi

# --mm-encoder-tp-mode only takes effect when --tensor-parallel-size is above 1.
# This deployment runs one GPU per pod, so the flag is inert today. It is kept so
# that raising tensor parallelism later does not also require remembering it.
exec vllm serve "$MODEL_PATH" \
  --served-model-name "$SERVED_NAME" \
  --port "$PORT" \
  --gpu-memory-utilization "$GPU_MEMORY" \
  --max-model-len "$MAX_MODEL_LEN" \
  --max-num-batched-tokens "$MAX_NUM_BATCHED_TOKENS" \
  --max-num-seqs "$MAX_NUM_SEQS" \
  --limit-mm-per-prompt '{"image":1, "video":0}' \
  --mm-encoder-tp-mode data \
  --trust-remote-code \
  --load-format instanttensor \
  --reasoning-parser qwen3 \
  --default-chat-template-kwargs '{"enable_thinking": false}' \
  --enable-chunked-prefill \
  "${EXTRA_ARGS[@]}"

