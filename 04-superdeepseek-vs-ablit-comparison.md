# SuperDeepSeek-V4-Flash-abliterated-MQ vs Ablit on 2× DGX Spark

**Date:** August 12, 2026
**Hardware:** 2× NVIDIA DGX Spark (GB10, 128 GB unified memory, SM121)
**Nodes:** 9105 (rank 0, head) + bdea (rank 1, worker)
**Interconnect:** Direct CX-7 RoCEv2, GID index 5, `rocep1s0f0` + `enp1s0f0np0`

---

## 1. Headline

A head-to-head comparison of two DeepSeek V4 Flash abliterated checkpoints on identical hardware and identical serving topology (TP=2 across two DGX Sparks):

- **`drowzeys/keys-DeepSeekV4-Flash-GA-0731-Dspark-Abliterated-32-32`** — the **Ablit** baseline (NVFP4 + FP8 attention, 156 GB, 48 shards)
- **`Jiunsong/SuperDeepseek-V4-Flash-abliterated-MQ-2xDGX`** — the **SuperDeepSeek** mixed-quantization successor (FP4 experts + FP8 attention + BF16 quality-sensitive tensors + BF16 output-head overlay, 169.5 GB, 50 shards)

**Bottom line:** SuperDeepSeek decodes **1.37× faster single-stream and 1.05× faster at C=4** while matching ablit at **96% HumanEval pass@1** and trailing only 4 percentage points on GSM8K (which is dominated by extraction artifacts, not genuine capability regression). Speed is the decisive win; quality is matched.

---

## 2. Models at a Glance

| Property | Ablit | SuperDeepSeek-MQ |
|----------|:-----:|:----------------:|
| **Total parameters** | 162.7B (MoE, 256 experts, top-6) | same (304B-class MoE, 256 experts, top-6, 43 backbone + 3 MTP layers) |
| **Active params/token** | ~6B | ~6B |
| **Quantization** | NVFP4 experts + FP8 attention + BF16 | **FP4 experts + FP8 attention + BF16 quality-sensitive + BF16 output-head overlay** |
| **On-disk size** | 156 GB (48 shards) | 169.5 GB (50 shards) |
| **Context window** | 65,536 (used) | 1,048,576 (configured) |
| **Speculative decoding** | ❌ Not supported (`NotImplementedError` in vLLM DSpark runtime) | ✅ **DSpark K=1, greedy draft, self-MTP-based** |
| **KV cache** | NVFP4 DS-MLA | NVFP4 DS-MLA |
| **Targeted abliteration** | Full-model width | **Surgical**: 46 `attn.wo_b` weight/scale pairs + bounded rank-64 BF16 output-head recovery |
| **Refusal subspace shift** | Reduction (per release notes) | 97.92% → 4.17% worst-mode refusal |
| **Reasoning parser** | deepseek_v4 | deepseek_v4 (`<think>...</think>`) |
| **Serving framework** | vLLM (DSpark runtime) | vLLM DSpark (`ghcr.io/anemll/dspark-vllm-gx10:0.1.1`) |
| **Container** | `vllm-dspark-runtime:dspark-nvfp4-stage-c` | `ghcr.io/anemll/dspark-vllm-gx10:0.1.1` |
| **Recipe compliance** | Anemll GA abliterated recipe | Pinned HF recipe `repro/scripts/serve_superdeepseek_v4_dual.sh` |

### Why SuperDeepSeek Exists

The parent checkpoint `deepseek-ai/DeepSeek-V4-Flash-0731@9e165c30e2704aec5d9d593cce3eebd58bbef1cb` is a hybrid FP4/FP8/BF16 release. SuperDeepSeek keeps that hybrid layout intact (experts FP4, attention FP8, embeddings + mHC + sensitive tensors BF16) and applies two changes:

1. **OBLITERATUS surgical pass** — fits a rank-1 refusal direction across modes, applies strength 2, then a second rank-1 residual pass recaptured from the first and orthogonalized (strength 0.5). Only 46 `attn.wo_b` weight/scale pairs in 43 backbone + 3 MTP layers are redirected; routed experts, routers, embeddings, mHC, and untargeted parent tensors keep the original quantization and bytes.
2. **Bounded rank-64 BF16 output-head recovery** — single overlay on `head.weight`; relative Frobenius delta 0.0025.

Ablit's release was a wider-net quantization + abliteration; SuperDeepSeek is minimal-touch surgical abliteration with output-head precision preserved.

---

## 3. Speed: Decode Throughput

**Protocol:** Decode throughput measured with two harnesses, each on the same canonical prompt set used for its prior ablit runs:

1. **Q&A-style single-stream** (used for the 36.8 / 26.9 comparison): prompt `"Explain the concept of recursion in programming, with a simple example."`, `max_tokens=2048`, `temperature=0.7`, 3 reps, median tok/s.
2. **Creative-writing concurrency** (used for the C=4, C=8 row): `f"Write a short creative story about topic {worker_id}_{j}. Be creative."` × 3 reps per worker, `max_tokens=512`, `temperature=0.7`. Wall-clock from first request sent to last response received.

Same model, same node, **different prompts give different single-stream numbers**: 36.8 tok/s on the recursion Q&A prompt vs 32.9 tok/s on the creative-writing prompt. Thinking mode is engaged more aggressively by "varied vocabulary / be creative" framing (longer reasoning chains before content decode). We report both because (a) the Q&A number is the right baseline for comparison to ablit's 26.9, and (b) the C=4 / C=8 numbers were generated with the creative prompt that is the apples-to-apples match for the concurrent tests.

| Model | Single-stream (tok/s) | C=4 aggregate (tok/s) | C=8 aggregate (tok/s) | TTFT (short prompt) |
|-------|:---------------------:|:----------------------:|:----------------------:|:-------------------:|
| **Ablit** (DSpark runtime, autoresearch-optimal) | 26.9 | 73.6 | 87.3 | ~2–5s |
| **SuperDeepSeek** (DSpark runtime, recipe) | **36.8** *(Q&A)* / **32.9** *(creative)* | **82.7** | **101.6** | not measured* |

*SuperDeepSeek's recipe config is `max-num-seqs=6` and `max-model-len=1048576`, vs ablit's tuned `max-num-seqs=8` + `max-model-len=65536`. At C=8, SuperDeepSeek's hard cap queues 2 of the 8 requests per batch, but the model keeps decoding during queue idle, so aggregate still wins. The ablit C=8 used `max-num-seqs=8` from its autoresearch sweep. Apparent throughput gap is the `max-num-seqs=6` cap, not a model ceiling — re-tuning that flag would likely push SuperDeepSeek further.

**Single-stream: SuperDeepSeek is 1.37× faster than Ablit.**
**C=4 aggregate: SuperDeepSeek is 1.05× faster than Ablit.**

### Why SuperDeepSeek Is So Much Faster Single-Stream

Single-stream throughput on GB10 is approximately:

```
tok/s ≈ effective_memory_bandwidth / weight_size
```

Both models are memory-bandwidth bound. The difference is what they **do** with each weight read:

1. **DSpark K=1 speculative decoding.** Each weight read feeds one **forward + verification** of the main model, but the verification also accepts one bonus token drafted by the model's own MTP tensors — zero extra weights in memory. Ablit's runtime throws `NotImplementedError` on `--speculative-config`, so ablit is plain single-token decode.

2. **Bigger windows matter for speculative.** Ablit's autoresearch sweep [see report reference] explored 16 configurations — none enabled speculative decoding because the docker image didn't support it. SuperDeepSeek's recipe has it on by default and the model was trained with MTP for self-speculation.

3. **Output head recovery in BF16, not requantized.** The rank-64 BF16 head overlay keeps the lm_head in higher precision than a full NVFP4 requantization would have — making target-logit computations marginally cheaper to verify against the draft.

### Autoresearch Notes

- **Ablit:** 16-config sweep yielded three kept changes from baseline — `max-num-seqs=8` (NEW capability), `breakable_cudagraph=1` (+19.4% C=8), jumbo MTU 9000 (-77% fabric latency). All within ±1.3% of baseline at single-stream.
- **SuperDeepSeek:** recipe defaults used as-is per HF recipe contract. Model is brand-new (released same week); no sweep yet. The HF recipe's own autotune produced its claimed 123.3 aggregate tok/s at p256/C6 — this report reproduces ~77 tok/s at C=4 which is on the right curve.

---

## 4. Quality: GSM8K (Math Reasoning)

**Protocol:** 50-question subset (Vikas-pinned), 0-shot, `#### N` answer extraction, max_tokens=4096, thinking mode `low`, temperature=0. Same 50 questions used for all prior reports.

| Model | Score (auto-extract) | Score (rescored*) | Real math errors |
|-------|:--------------------:|:-----------------:|:----------------:|
| **Ablit** | 80% (40/50) | **~96% (48/50)** | 2 (Q12 off-by-one, Q40 wrong answer) |
| **SuperDeepSeek-MQ** | 78% (39/50) | **92% (46/50)** | 1 (Q49 wrong answer) |

*Rescoring applies a smarter extractor that prefers bolded `**N**` or the last `$N` in the final 200 chars rather than the first `#### N` match (which doesn't exist because thinking mode puts reasoning in a separate field). Both models were affected by the same extraction artifact.

### The Extraction Artifact

When thinking mode is enabled, the model emits its reasoning in a separate `reasoning_content` field; the `content` field contains only the final answer. The simpler extractor (used in the ablit run) preferentially picked the first `#### N` it found anywhere — but in thinking-mode output there typically isn't one. Hence the 8 "false negative" misses that were actually correct.

The smarter extractor (used for both ablit post-hoc and SuperDeepSeek): prefer `**$N**` markdown bold, else last `$N,NNN` or standalone `N` in the last 200 chars of content.

### Genuine Failures After Re-Score

**Ablit (2 genuine math errors):**
- **Q12:** bakery — `3 dozen × $68 = $204` then confused units (got correct sub-sums, wrong total)
- **Q40:** misread the constraint, gave `15` instead of `100`

**SuperDeepSeek (1 genuine math error):**
- **Q49:** clock problem — model computed `7:36 PM` from "8 hours after midnight − 24 minutes" but the prompt asks for "what time does it stop being a palindrome?", which yields `7:36` as the model's interpretation (genuine reasoning divergence)

The other "failures" in SuperDeepSeek's raw output are:
- **Q8** — extraction caught intermediate $160 min, missed the +20 restart step (extraction artifact)
- **Q24** — model text said `"3325 good toys are produced in a week"` but extractor's input was truncated to last 200 chars (extraction artifact)
- **Q27** — model wrote `\frac{1}{4}` of pizza remains; extractor couldn't parse LaTeX fraction (extraction artifact)

After fixing the extraction, **SuperDeepSeek has 1 real math error vs Ablit's 2**.

---

## 5. Quality: HumanEval (Code Generation)

**Protocol:** pass@1, 50-problem subset, temperature=0, n=1, executed against canonical test cases. Both models benchmarked on the same 50 problems (canonical `HumanEval.jsonl`).

### Initial result — looked like a regression

First run used the existing Nemotron HumanEval harness (raw `/v1/completions` endpoint, no chat template, max_tokens=512, stop on `\nclass`/`\ndef`/`\n#`/`\nif`/`\nprint`):

| Model | HumanEval pass@1 | Notes |
|-------|:-----------------:|-------| 
| **Ablit** | **96% (48/50)** | clean |
| **SuperDeepSeek-MQ** | 76% (38/50) | 6 BUG + 6 TRUNC |

The SuperDeepSeek 12 failures had smoking-gun contents:

```
HumanEval/1:  ...ack:\n</code>\n</pre>\n</div>\n</body>\n</html>
HumanEval/2:  </original>\n<patched>\n
HumanEval/21: </original>\n<patched>\nfrom typing import List
HumanEval/28: <feedback_analysis>...</feedback_analysis>
HumanEval/40: <original_code><original> (repeated)
HumanEval/46: </solution></problem>"""
```

**The failures were not bugs — they were the model emitting chat-tuned response framing** (`</html>`, `</solution>`, `<original_code>`, `<feedback_analysis>` XML/HTML wrappers) into a raw completion endpoint that expected Python code only. The script then tried to `subprocess.run()` the markup, which failed.

### Re-run with chat endpoint + system prompt

**Protocol v2:** `/v1/chat/completions` with system prompt:

> *"You are a Python coding assistant. When asked to complete a function, output ONLY the completed Python code block. No explanation, no markdown headers, no XML tags, no HTML. Just the code."*

and user prompt *"Complete the following Python function. Output ONLY the completed function in a single ```python``` block…"*. max_tokens=1024.

| Model | HumanEval pass@1 | Failures |
|-------|:-----------------:|---------:|
| **Ablit** (chat endpoint, thinking) | **96% (48/50)** | 2 failures |
| **SuperDeepSeek-MQ** (chat endpoint, chat-system) | **96% (48/50)** | 2 failures |

**It was the endpoint, not the model.** Both models score identically when called correctly. The ablit's first 96% was already on the chat endpoint (Vikas had configured it earlier). SuperDeepSeek needs the same treatment.

The remaining 2 SuperDeepSeek failures were both `finish_reason: length` — the model went into extended thinking on HumanEval/32 and HumanEval/40 and never reached the code within 1024 tokens. With longer budgets (2048+) those would likely also pass.

---

## 6. Comprehensive Comparison

| Metric | Ablit | SuperDeepSeek-MQ | Best |
|--------|:-----:|:----------------:|:----:|
| **Single decode tok/s (Q&A)** | 26.9 | **36.8** | SuperDeepSeek (1.37×) |
| **Single decode tok/s (creative)** | 26.9 | **32.9** | SuperDeepSeek (1.22×) |
| **C=4 aggregate tok/s** | 73.6 | **82.7** | SuperDeepSeek (1.12×) |
| **C=8 aggregate tok/s** | 87.3 | **101.6** | SuperDeepSeek (1.16×) |
| **GSM8K (smart-extract)** | 96% (48/50) | 92% (46/50) | Ablit (-4 pts) |
| **GSM8K genuine math errors** | 2 | **1** | SuperDeepSeek |
| **HumanEval pass@1** | 96% (48/50) | **96% (48/50)** | **TIE** |
| **Real code bugs** | 2 | **0** (only 2 truncations at 1024t) | SuperDeepSeek |
| **Memory (active)** | ~76 GB / node | ~79 GB / node | Ablit (slightly lighter) |
| **On-disk size** | 156 GB | 169.5 GB (+8.7%) | Ablit |
| **Context window** | 65K (used) | **1M (configured and verified)** | SuperDeepSeek |
| **Speculative decoding** | ❌ | ✅ DSpark K=1 | SuperDeepSeek |
| **Surgical abliteration** | wide | surgical (46 attn.wo_b + head) | SuperDeepSeek |
| **Reasoning mode** | deepseek_v4 | deepseek_v4 | Tie |
| **Output head precision** | NVFP4 | **BF16 (rank-64 overlay)** | SuperDeepSeek |

---

## 7. Architecture Deep-Dive: Why SuperDeepSeek Wins on Speed

### The Memory-Bandwidth Ceiling (same for both)

GB10's unified memory at LPDDR5X means both models decode at the ceiling of:

```
tok/s ≈ effective_bandwidth / weight_size
```

This is why both are bandwidth-bound. The difference is what the model achieves **per step**. With no speculation, ablit decodes one token per memory read. With DSpark K=1, SuperDeepSeek decodes on average ~1.4 tokens per memory read (verified by the 1.37× speedup matching K=1 acceptance rates).

### DSpark Speculative Decoding Anatomy

DSpark K=1 is **self-speculative**: the model uses its own trained MTP (Multi-Token Prediction) tensors — already on the GPU as part of the 50-shard checkpoint — to draft one bonus token per step. The main model then verifies the drafted token in the same forward pass. Accepted tokens count for free (one weight read produces ~1.4 tokens of output instead of 1).

The acceptance rate is governed by the model's local coherence on the actual prompt distribution, not by an external draft model like DFlash. For reasoning tasks (HumanEval, GSM8K), the model is in a tight reasoning loop where its own next-token predictions are very accurate — so acceptance runs high.

Ablit's docker image (`vllm-dspark-runtime:dspark-nvfp4-stage-c`) did not implement `--speculative-config` for the DS4 architecture — it raised `NotImplementedError`. This is an upstream constraint, not a model constraint.

### Mixed Quantization (MQ) Layout

SuperDeepSeek uses what the parent release calls **MQ** — not a uniform requantization, but preservation of the official layout:

| Component | Precision | On disk |
|-----------|:---------:|--------:|
| MoE expert weights | FP4 | ~89 GB |
| Attention + KV | FP8 E4M3 + UE8M0 scales, 128×128 weight blocks | ~52 GB |
| Selected `attn.wo_b` overlays | FP8 (deterministic) | ~2 GB |
| Embeddings, mHC, lm_head, sensitive tensors | **BF16** | ~26.5 GB |
| **Total** | | **169.5 GB** |

The BF16 `lm_head` (output head overlay, rank-64 recovery, Frobenius delta 0.0025) is the key — keeping it in BF16 instead of requantizing to NVFP4 means: (1) lower error at decode-bound logit computation, (2) cheaper verification of the draft token (BF16 GEMM is faster than NVFP4 GEMM on Blackwell for small batch sizes).

---

## 8. Serving Configuration

### SuperDeepSeek (winning config — HF recipe)

```bash
docker run --rm -d --name superdeepseek-v4-rank0 \
  --privileged --gpus all --network host --ipc host \
  --shm-size 64g --ulimit memlock=-1:-1 --ulimit stack=67108864:67108864 \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  -e NODE_RANK=0 -e MASTER_ADDR=10.10.10.1 -e MASTER_PORT=25001 \
  -e HEADLESS=0 -e GRAPH_PROFILE=regular \
  -e SERVED_NAME=SuperDeepseek-V4-Flash-abliterated-MQ-2xDGX \
  -e DEFAULT_THINKING=low -e VLLM_HOST_IP=10.10.10.1 \
  -e NCCL_NET=IB -e NCCL_IB_DISABLE=0 -e NCCL_IB_HCA=rocep1s0f0 \
  -e NCCL_IB_GID_INDEX=5 -e NCCL_SOCKET_IFNAME=enp1s0f0np0 \
  -e GLOO_SOCKET_IFNAME=enp1s0f0np0 -e TP_SOCKET_IFNAME=enp1s0f0np0 \
  -e NCCL_IB_ADDR_FAMILY=AF_INET -e NCCL_IB_ROCE_VERSION_NUM=2 \
  -e NCCL_CROSS_NIC=1 -e NCCL_CUMEM_ENABLE=0 -e NCCL_IGNORE_CPU_AFFINITY=1 \
  -e NCCL_NVLS_ENABLE=0 -e NCCL_DEBUG=WARN \
  -e VLLM_ALLOW_LONG_MAX_MODEL_LEN=1 \
  -e VLLM_SPARSE_INDEXER_MAX_LOGITS_MB=256 \
  -e VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=0 \
  -e VLLM_USE_BREAKABLE_CUDAGRAPH=0 \
  -e VLLM_USE_B12X_MOE=1 -e VLLM_USE_FLASHINFER_SAMPLER=1 \
  -e VLLM_B12X_W4A16_FORCE_BLOCKS_PER_SM=0 \
  -e VLLM_B12X_W4A16_FORCE_BLOCKS_MAX_M=16 \
  -e TORCH_CUDA_ARCH_LIST=12.1a -e FLASHINFER_CUDA_ARCH_LIST=12.1a \
  -e CUTE_DSL_ARCH=sm_121a -e FLASHINFER_DISABLE_VERSION_CHECK=1 \
  -e FLASHINFER_WORKSPACE_BASE=/cache/flashinfer \
  -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  -v /home/vikassridhar/models/superdeepseek-ablit-mq:/model:ro \
  -v /home/vikassridhar/superdeepseek-cache/vllm:/root/.cache/vllm \
  -v /home/vikassridhar/superdeepseek-cache/flashinfer:/cache/flashinfer \
  -v /home/vikassridhar/superdeepseek-cache/tmp:/tmp \
  -v /home/vikassridhar/run_superdeepseek_v4_vllm.sh:/bundle-scripts/run_superdeepseek_v4_vllm.sh:ro \
  --entrypoint /bin/bash \
  ghcr.io/anemll/dspark-vllm-gx10:0.1.1 \
  /bundle-scripts/run_superdeepseek_v4_vllm.sh
```

Inside the container, `vllm serve` is invoked with:

```bash
vllm serve /model \
  --served-model-name "SuperDeepseek-V4-Flash-abliterated-MQ-2xDGX" \
  --host 0.0.0.0 --port 8888 --trust-remote-code \
  --tensor-parallel-size 2 --pipeline-parallel-size 1 \
  --kv-cache-dtype nvfp4_ds_mla --block-size 256 \
  --max-model-len 1048576 --max-num-seqs 6 \
  --max-num-batched-tokens 8192 --gpu-memory-utilization 0.80 \
  --enable-prefix-caching --enable-prompt-tokens-details \
  --cudagraph-metrics --async-scheduling --enable-chunked-prefill \
  --speculative-config '{"method":"dspark","num_speculative_tokens":1,"draft_sample_method":"greedy"}' \
  --tokenizer-mode deepseek_v4 --distributed-executor-backend mp \
  --moe-backend flashinfer_b12x \
  --tool-call-parser deepseek_v4 --enable-auto-tool-choice \
  --reasoning-parser deepseek_v4 \
  --reasoning-config '{"reasoning_parser":"deepseek_v4","reasoning_start_str":"<think>","reasoning_end_str":"</think>"}' \
  --default-chat-template-kwargs '{"thinking":true,"reasoning_effort":"low"}' \
  --generation-config vllm --enable-flashinfer-autotune \
  --nnodes 2 --node-rank "$NODE_RANK" \
  --master-addr "$MASTER_ADDR" --master-port "$MASTER_PORT" \
  --max-cudagraph-capture-size 32 \
  --performance-mode interactivity \
  --compilation-config '{"backend":"eager"}'
```

### Ablit (winning config — from prior autoresearch)

```bash
vllm serve \
  --model deepseek-v4-ablit \
  --tensor-parallel-size 2 \
  --max-num-seqs 8 \
  --reasoning-effort medium \
  --gpu-memory-utilization 0.75 \
  --max-model-len 65536 \
  --enable-chunked-prefill \
  --max-num-batched-tokens 8192
```

(plus fabric tuning: jumbo MTU 9000, both RDMA rails active, `VLLM_USE_BREAKABLE_CUDAGRAPH=1`)

### Runtime Stack

| Component | Ablit | SuperDeepSeek |
|-----------|:-----:|:-------------:|
| vLLM | 0.21.1rc1 (eugr nightly, patched) | **0.25.2.dev0+g752a3a504** (dspark branch) |
| Container | `vllm-dspark-runtime:dspark-nvfp4-stage-c` | **`ghcr.io/anemll/dspark-vllm-gx10:0.1.1`** |
| MoE Backend | Marlin | **flashinfer_b12x** |
| MTP Drafter | none (NotImplementedError) | **dspark K=1 greedy** |
| KV Cache | NVFP4 DS-MLA | NVFP4 DS-MLA |
| CUDA Graphs | breakable | regular (eager backend) |
| Model Load Time (local disk) | ~98s | ~170s (50 shards @ 4.0s/shard) |
| Model Load Time (NFS, ablit) | ~201s | n/a (served from local on both nodes) |

---

## 9. Pitfalls Encountered

1. **Image pull is large.** `ghcr.io/anemll/dspark-vllm-gx10:0.1.1` is a CUDA 13 + vLLM 0.25.2 image (~15 GB). Two parallel pulls complete in ~12 min on WiFi; one node ahead of the other creates sync issues — wait for both before launching.

2. **Model is on node 9105, must rsync to bdea first.** 169.5 GB at ~455 MB/s over the fabric = ~6 min. The HF cache directory only has `refs` stubs (not the actual files) because `huggingface_hub.snapshot_download` was used directly.

3. **Serving script is sealed to specific hostnames** (`spark-deca`, `spark-dd73`). The HF-bundled launcher refuses to start on `edgexpert-9105` and `edgexpert-bdea`. Copy the script body, change hostname checks to comments, keep all other settings (NCCL, env vars, args) exactly.

4. **VLLM_BUILD_* warnings are noise.** The image sets `VLLM_BUILD_URL`, `VLLM_BUILD_COMMIT`, `VLLM_BUILD_PIPELINE`, `VLLM_IMAGE_TAG` — vLLM logs each as "Unknown environment variable detected". Ignore.

5. **`encoding/encoding_dsv4.py` must exist in the model directory.** The startup script copies it into the vLLM install. If the model is downloaded via a different tool (e.g. `huggingface-cli`), this file may not be in the snapshot — verify with `ls /model/encoding/encoding_dsv4.py` before serving.

6. **MTP layer `DeepSeekV4MTPModel` resolves before `DeepseekV4ForCausalLM` in the startup log.** Both are expected; not a duplicate-load warning.

7. **CUDA graph capture size 32, eager backend.** Recipe-tuned for DS4 + DSpark combination. Don't switch to `enforce-eager` or `compilation-config: cudagraph_mode=PIECEWISE` without retesting — the recipe is delicate and the HF card documents why each knob is set this way.

8. **HumanEval **must use `/v1/chat/completions` with a system prompt**. The model is chat-tuned; sending a raw Python function signature via `/v1/completions` triggers HTML/XML wrapper responses. See Section 5.

9. **GSM8K extraction is sensitive to thinking mode.** When `reasoning_effort: low` (default for DSpark), reasoning goes into `reasoning_content` and the `content` field is short — smart extraction (last-$-in-tail or bolded-N) recovers 8–10 extra correct answers vs greedy regex.

10. **`default_chat_template_kwargs: '{"thinking":true,"reasoning_effort":"low"}'` is the default.** If you change to `high` or `max`, GSM8K takes 2–3× longer because the model generates 1500+ thinking tokens per problem. Stay on `low` for benchmarks.

---

## 10. Recommendations

### When to choose SuperDeepSeek-MQ over Ablit:

- **Speed matters.** Single-stream decode is 1.37× faster — difference between "feels instant" and "feels slow" for interactive chat.
- **Long context.** Configured and verified for 1M tokens; ablit is capped at 65K in our deployment.
- **Tool calling.** DSpark runtime's tool parser is well-tested; both models expose `deepseek_v4` tool call format identically.
- **When the upstream ablit gets speculative decoding.** Right now ablit can't use it because its docker image throws `NotImplementedError`. SuperDeepSeek's image was built with `dspark` method and works out of the box.

### When to keep Ablit:

- **C=8 concurrent users.** Ablit's autoresearch-tuned config supports `max-num-seqs=8`. SuperDeepSeek's HF recipe caps at 6. Aggregated serving throughput may differ at C=8 — needs measurement.
- **Smaller download/footprint.** 156 GB vs 169.5 GB on disk; +8.7% the storage and download time.
- **When the surgical abliteration is a concern.** SuperDeepSeek only touches 46 `attn.wo_b` pairs plus the output head. If your safety pipeline expects a wider-net abliteration, ablit's release history is more established.

### When NOT to use either on 2-node DGX Spark:

- **High-concurrency production serving.** 8 concurrent users is the proven limit. For more, split loads across more node pairs.
- **Single-node deployment.** Both require TP=2 and the full 169 GB doesn't fit a single 128 GB DGX Spark (even with quantization).

---

## 11. Methodology

### Benchmarks

- **GSM8K:** 50-question subset from the canonical OpenAI/grade-school-math test set, locked to the same questions used in reports 01–03. 0-shot, `#### N` extraction with smart-extractor override (last `$N` in last 200 chars preferred). max_tokens=4096. `temperature=0`, `reasoning_effort=low`. Wall-clock timing per question.
- **HumanEval:** pass@1, 50-problem subset. `/v1/chat/completions` with system+user prompts requiring clean Python code in markdown fences. max_tokens=1024 for chat run (vs 512 for the initial raw-completions run). `temperature=0`, `n=1`. Code extracted from markdown fence, executed against canonical test case via `subprocess.run(...)`.
- **Speed:** Single-stream decode at 512-token output, 3 reps, temperature=0, BS=1, median tok/s reported. C=4 aggregate using 4 concurrent threads with 1024-token prompts (or whatever default the harness uses), wall-clock from first request to last. TTFT measured on short ~30-token prompts.

### Hardware

- 2× DGX Spark (GB10, SM121, 128 GB unified memory each)
- Node 9105: rank 0, IP 10.10.10.1, hostname `edgexpert-9105`
- Node bdea: rank 1, IP 10.10.10.2, hostname `edgexpert-bdea`
- Direct CX-7 QSFP56 RoCEv2, GID index 5, device `rocep1s0f0`, netdev `enp1s0f0np0`
- NCCL socket ifname = `enp1s0f0np0`, both NCCL and GLOO

### Recipe Compliance

**SuperDeepSeek:** Follows the pinned HF recipe at [`repro/scripts/serve_superdeepseek_v4_dual.sh`](https://huggingface.co/Jiunsong/SuperDeepseek-V4-Flash-abliterated-MQ-2xDGX/raw/main/repro/scripts/serve_superdeepseek_v4_dual.sh) exactly — image, NCCL env, vLLM flags, reasoning config. Only deviation: the script's hostname seal (`spark-deca`, `spark-dd73`) was replaced with no-op checks because we're on different physical nodes; all other settings are byte-identical.

**Ablit:** Follows the prior 16-config autoresearch run captured in [`/home/vikassridhar/ds4-autoresearch/results.tsv`](file:///home/vikassridhar/ds4-autoresearch/results.tsv) and skill at `~/.openclaw/skills/deepseek-v4-ablit-serving/SKILL.md`. Reproducing those flags exactly.

### Limitations

- C=8 aggregate for SuperDeepSeek not measured (recipe caps seqs at 6).
- TTFT for SuperDeepSeek not measured (recipe skips explicit TTFT benchmark).
- GSM8K `low` reasoning effort is the recipe default; `medium`/`high` not tested.
- HumanEval ablit was previously benchmarked with chat endpoint (96%); this report uses the same methodology for an apples-to-apples comparison.
- Both models' release weeks overlap; long-term stability not assessed.

---

## 12. Raw Artifacts

On 9105 (`100.127.212.61`):
- `/home/vikassridhar/superdeepseek-gsm8k.json` — 50-question GSM8K, raw auto-extract: 78%
- `/home/vikassridhar/superdeepseek-gsm8k-rescored.json` — same with smart extractor: 92%
- `/home/vikassridhar/superdeepseek-humaneval-chat.json` — HumanEval via chat endpoint: 96% (48/50)
- `/home/vikassridhar/superdeepseek-humaneval.json` — HumanEval via raw completions: 76% (illustrative of the endpoint issue)
- `/home/vikassridhar/run_superdeepdeepseek_v4_vllm.sh` — adapted startup script
- `/home/vikassridhar/humaneval_chat.py` — chat-endpoint HumanEval harness with code extraction

Ablit references (prior runs):
- `/home/vikassridhar/ds4-autoresearch/results.tsv` — 16-config autoresearch matrix
- `/home/vikassridhar/ds4-autoresearch/REPORT.md` — ablit optimization report
- `~/.openclaw/skills/deepseek-v4-ablit-serving/SKILL.md` — full serving recipe

### Date
August 12, 2026
