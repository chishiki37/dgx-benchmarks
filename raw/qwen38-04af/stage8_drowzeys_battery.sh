#!/bin/bash
# Stage 6: SGLang+DSPARK rerun — quality FIRST, speed last (arena can kill the server).
set -u
LABEL="drowzeys_mtp3"
OUT=/tmp/qbench
LOG="$OUT/stage8_$LABEL.log"
PY=/tmp/benchvenv/bin/python
export BENCH_URL="http://127.0.0.1:8078/v1/chat/completions"
export BENCH_MODEL="qwen38-nvfp4"

echo "stage8 start $(date -Is)" > "$LOG"

# gate: wait for oneshot full completion incl 26K warmup (up to 60 min)
for i in $(seq 1 720); do
  grep -q "DONE" /tmp/drowzeys_oneshot.log 2>/dev/null && break
  if grep -q "FAILED" /tmp/drowzeys_oneshot.log 2>/dev/null; then echo "oneshot FAILED - battery aborting $(date -Is)" >> "$LOG"; touch "$OUT/STAGE8_FAILED_$LABEL"; exit 1; fi
  sleep 5
done
grep -q "DONE" /tmp/drowzeys_oneshot.log 2>/dev/null || { echo "oneshot gate TIMEOUT no DONE - battery aborting $(date -Is)" >> "$LOG"; touch "$OUT/STAGE8_FAILED_$LABEL"; exit 1; }
echo "oneshot gate passed after $((i*5))s" >> "$LOG"
# wait for server
for i in $(seq 1 240); do
  if curl -fsS -m 5 http://127.0.0.1:8078/v1/models >/dev/null 2>&1; then echo "server up after $((i*5))s" >> "$LOG"; break; fi
  sleep 5
done
curl -fsS -m 5 http://127.0.0.1:8078/v1/models >/dev/null 2>&1 || { echo "server never came up - battery aborting $(date -Is)" >> "$LOG"; touch "$OUT/STAGE8_FAILED_$LABEL"; exit 1; }

# warmup: flush first-forward kernels, verify generation works
echo "=== WARMUP ===" >> "$LOG"
curl -s -m 300 http://127.0.0.1:8078/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model":"qwen38-nvfp4","messages":[{"role":"user","content":"Write one short sentence about the sea."}],"max_tokens":256,"temperature":0}' | head -c 300 >> "$LOG" 2>&1
echo >> "$LOG"
curl -s -m 300 http://127.0.0.1:8078/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model":"qwen38-nvfp4","messages":[{"role":"user","content":"Write one short sentence about mountains."}],"max_tokens":256,"temperature":0}' >/dev/null 2>&1
echo "warmup done" >> "$LOG"

echo "=== GSM8K ===" >> "$LOG"
$PY /tmp/qbench/gsm8k_direct_benchmark.py --url http://127.0.0.1:8078/v1/chat/completions --limit 50 --output $OUT/gsm8k_$LABEL.json >> "$LOG" 2>&1
echo "GSM8K_RC=$?" >> "$LOG"

echo "=== HUMANEVAL ===" >> "$LOG"
$PY /tmp/qbench/humaneval_chat_benchmark.py --base-url http://127.0.0.1:8078/v1 --model qwen38-nvfp4 --limit 50 --output $OUT/humaneval_$LABEL.json >> "$LOG" 2>&1
echo "HUMANEVAL_RC=$?" >> "$LOG"

echo "=== IFEVAL ===" >> "$LOG"
/tmp/benchvenv/bin/lm_eval --model local-chat-completions \
  --model_args model=qwen38-nvfp4,base_url=http://127.0.0.1:8078/v1/chat/completions,tokenizer=unsloth/Qwen3.8-27B-NVFP4,num_concurrent=8,max_retries=3,tokenized_requests=False \
  --apply_chat_template --tasks ifeval --gen_kwargs temperature=0,max_tokens=4096 --limit 100 \
  --output_path $OUT/ifeval_$LABEL.json >> "$LOG" 2>&1
echo "IFEVAL_RC=$?" >> "$LOG"

echo "=== GPQA ===" >> "$LOG"
/tmp/benchvenv/bin/lm_eval --model local-completions \
  --model_args model=qwen38-nvfp4,base_url=http://127.0.0.1:8078/v1/completions,tokenizer=unsloth/Qwen3.8-27B-NVFP4,num_concurrent=8,max_retries=3,tokenized_requests=False \
  --tasks gpqa_diamond_zeroshot --limit 100 \
  --output_path $OUT/gpqa_$LABEL.json >> "$LOG" 2>&1
echo "GPQA_RC=$?" >> "$LOG"

echo "=== HLE ===" >> "$LOG"
$PY /tmp/qbench/hle_eval2.py --base-url http://127.0.0.1:8078/v1 --model qwen38-nvfp4 --limit 100 --concurrency 4 --output $OUT/hle_$LABEL.json >> "$LOG" 2>&1
echo "HLE_RC=$?" >> "$LOG"

echo "=== SPEED: decode_bench ===" >> "$LOG"
python3 /tmp/decode_bench.py >> "$LOG" 2>&1
echo "DECODE_RC=$?" >> "$LOG"

echo "=== SPEED: arena (2k-51k, vLLM-parity depths) ===" >> "$LOG"
python3 /tmp/arena_ladder.py 2048,4096,8192,16384,32768,51200 >> "$LOG" 2>&1
echo "ARENA_RC=$?" >> "$LOG"

touch $OUT/STAGE8_DONE_$LABEL
echo "stage8 end $(date -Is)" >> "$LOG"
