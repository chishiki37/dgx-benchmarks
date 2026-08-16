#!/bin/bash
# SGLang + DSPARK arm v2: YaRN baked into config overlay (no --hf-overrides in this build).
set -euo pipefail

IMAGE="lmsysorg/sglang:qwen38-27b"
NAME="sglang-qwen38-dspark"
PORT=8888
HF_HOME="$HOME/.cache/huggingface"
FI_CACHE="$HOME/.cache/flashinfer"
OVERLAY="$HOME/qwen38-nvfp4-yarn1m"
mkdir -p "$FI_CACHE"

HF_TOKEN="$(cat "$HOME/.cache/huggingface/token" 2>/dev/null || true)"

# --- build overlay: symlinks to snapshot, modified config.json ---
SNAP=$(ls -d $HF_HOME/hub/models--RadixArk--Qwen3.8-27B-NVFP4/snapshots/*/ | head -1)
mkdir -p "$OVERLAY"
for f in "$SNAP"*; do
  base=$(basename "$f")
  if [ "$base" != "config.json" ]; then
    ln -fL "$f" "$OVERLAY/$base" 2>/dev/null || cp -fL "$f" "$OVERLAY/$base"
  fi
done
python3 - "$SNAP/config.json" "$OVERLAY/config.json" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
c = json.load(open(src))
tc = c["text_config"]
tc["max_position_embeddings"] = 500000
rp = dict(tc.get("rope_parameters", {}))
rp.update({
    "rope_type": "yarn",
    "factor": 4.0,
    "original_max_position_embeddings": 262144,
    "rope_theta": 10000000,
    "partial_rotary_factor": 0.25,
})
tc["rope_parameters"] = rp
json.dump(c, open(dst, "w"), indent=2)
print("overlay config written:", dst)
print("rope_parameters:", json.dumps(rp))
PY

# --- launch ---
if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  docker rm -f "$NAME" >/dev/null
fi

docker run -d \
  --name "$NAME" \
  --network host \
  --ipc host \
  --privileged \
  --gpus all \
  -e HF_TOKEN="$HF_TOKEN" \
  -e SGLANG_ALLOW_OVERWRITE_LONGER_CONTEXT_LEN=1 \
  -v "$HF_HOME:/root/.cache/huggingface" \
  -v "$OVERLAY:/model" \
  -v "$FI_CACHE:/root/.cache/flashinfer" \
  --entrypoint python3 \
  "$IMAGE" \
  -m sglang.launch_server \
    --model-path /model \
    --served-model-name qwen38-27b-unsloth-nvfp4 \
    --host 0.0.0.0 --port $PORT \
    --tp-size 1 \
    --trust-remote-code \
    --context-length 500000 \
    --speculative-algorithm DSPARK \
    --speculative-draft-model-path RadixArk/Qwen3.8-27B-DSpark \
    --speculative-dspark-block-size 7 \
    --speculative-draft-model-quantization unquant \
    --mamba-scheduler-strategy extra_buffer \
    --mamba-full-memory-ratio 0.5 \
    --attention-backend flashinfer \
    --chunked-prefill-size 8192 \
    --mem-fraction-static 0.83 \
    --max-running-requests 4 \
    --cuda-graph-max-bs 4 \
    --disable-prefill-cuda-graph \
    --watchdog-timeout 1800 \
    --reasoning-parser qwen3 \
    --enable-metrics

echo "waiting for readiness..."
for i in $(seq 1 360); do
  if curl -fsS http://127.0.0.1:$PORT/v1/models >/dev/null 2>&1; then
    echo "SGLANG-READY after $((i*5))s"
    exit 0
  fi
  if ! docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
    echo "container died during startup"
    docker logs --tail 40 "$NAME"
    exit 1
  fi
  sleep 5
done
echo "timed out waiting for readiness"
docker logs --tail 40 "$NAME"
exit 1
