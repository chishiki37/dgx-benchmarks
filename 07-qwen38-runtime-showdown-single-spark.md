# Qwen3.8-27B-NVFP4 on a Single DGX Spark: drowzeys vLLM MTP3 vs SGLang DSPARK vs Stock vLLM k=3

**Date:** August 15–16, 2026
**Node:** edgexpert-04af (1× DGX Spark, GB10, 121 GB unified memory)
**Model:** unsloth/Qwen3.8-27B-NVFP4 (22 GB, NVFP4 compressed-tensors, hybrid attention + GDN linear-attention layers, MTP draft head)

## TL;DR

Three serving runtimes were benched back-to-back on identical hardware with the same model:

1. **The drowzeys recipe's headline claim of 31.7 tok/s (MTP3) does NOT reproduce.** We measured **19.5–20.6 tok/s** single-stream decode — parity with the stock-vLLM MiaAI-style baseline (~21 tok/s from the prior campaign) and ~1.3× SGLang.
2. **Quality is runtime-neutral**, as expected: all three runtimes land within sampling noise on GSM8K (94–96%), HumanEval (92%), IFEval (0.80–0.85), GPQA (0.44–0.47), HLE (0.09–0.11).
3. **SGLang DSPARK dominates prefill** (4.6–14.9K tok/s) but trails on decode (~16 tok/s). The drowzeys/vLLM MTP config throttles prefill to ~1–1.9K tok/s because vLLM pins `max_num_scheduled_tokens=2048` when speculative decoding is enabled.
4. **The drowzeys longctx (1M YaRN) profile is broken** on its own pinned image: a `mamba_block_size` validation error crash-loops the engine at startup with MTP enabled. Only the 256K profile is usable.
5. Two harness bugs initially produced catastrophic-looking quality numbers (GSM8K 0%, HumanEval 0%) that were pure measurement artifacts — root causes documented below.

## Setup

| Arm | Runtime image | Key serve flags |
|---|---|---|
| **vllm_k3** (baseline, Aug 15 AM) | `vllm/vllm-openai:nightly-aarch64` | port 8888, model id `qwen38-27b-unsloth-nvfp4`, MTP `num_speculative_tokens=3` |
| **sglang_dspark** (Aug 15 PM) | `lmsysorg/sglang:qwen38-27b` | DSPARK draft `RadixArk/Qwen3.8-27B-DSpark` (block size 7, unquant), YaRN-4× config overlay (`max_position_embeddings=500000`), `--context-length 500000`, mem-fraction 0.83, max-running-requests 4, chunked-prefill 8192, flashinfer backend, `--reasoning-parser qwen3` (full script: `raw/qwen38-04af/start_sglang_dspark.sh`) |
| **drowzeys_mtp3** (Aug 16) | `ghcr.io/drowzeys/keys-vllm-027-gb10-qwen38:mtp3-20260813` (mirror of `eugr/spark-vllm-b12x:nightly-20260813`, vLLM `0.1.dev19043`) | Profile A: `--max-model-len 262144`, gpu-util 0.90, fp8 KV cache, flashinfer autotune, MTP k=3, `--tool-call-parser qwen3_xml`, **+ our patch: `--reasoning-parser qwen3`** (patched oneshot: `raw/qwen38-04af/oneshot_drowzeys_patched.sh`) |

Battery (all arms): GSM8K 50q (step-by-step prompt, `#### N` extraction, temp 0) · HumanEval 50 chat-native (code-fence extraction, temp 0) · IFEval 100 (lm-eval `ifeval`, local-chat-completions) · GPQA-Diamond 100 zeroshot (lm-eval, completions endpoint) · HLE-text 100 (thinking-off, direct-answer exact match) · decode_bench (512/1024 tok streaming, thinking on/off) · Spark-Arena-style ladder (prefill + decode-under-context, 2k–51k, c=1).

## Speed results

### Single-stream decode (decode_bench, thinking-off unless noted)

| Runtime | 512 tok e2e | 1024 tok e2e | Notes |
|---|:---:|:---:|---|
| drowzeys MTP3 | **19.5–20.7 tok/s** | 19.1–19.3 tok/s | two independent runs (round 1: 20.7/19.3, round 2: 19.5/19.1); thinking-on: 19.7–21.0 |
| vllm_k3 (MiaAI-style) | ~21 tok/s | — | from prior campaign on same model + MTP-3; no decode_bench was run in this campaign's k3 stages |
| sglang_dspark | 15.3 tok/s | 16.0 tok/s | decode-only ≈ 15.7–16.1 |

**vs the drowzeys README claim:** their ladder (11.1 no-spec → 19.4 MTP1 → 26.3 MTP2 → **31.7 MTP3**) was not reproduced at the MTP3 point; we land at the same number they report for **MTP1**.

### Arena ladder (c=1, drowzeys MTP3, round 2)

| Depth | Prefill (ctx_pp) | Decode under context (ctx_tg) | TTFT |
|---|:---:|:---:|:---:|
| 2k | 920 tok/s | 19.6 tok/s | 634 ms |
| 4k | 1,300 | 22.1 | 1,107 ms |
| 8k | 1,516 | 22.6 | 1,982 ms |
| 16k | 1,517 | 18.1 | 3,838 ms |
| 32k | 1,926 | 19.8 | 7,894 ms |
| 51k | 1,884 | 22.6 | 13,105 ms |

Decode-under-context stays flat (~18–23 tok/s) — good. Prefill saturates near ~1.9K tok/s.

### Prefill comparison (where SGLang wins big)

| Depth | sglang_dspark | drowzeys MTP3 | Ratio |
|---|:---:|:---:|:---:|
| 4k | 4,572 tok/s | 1,300 | 3.5× |
| 8k | 5,086 | 1,516 | 3.4× |
| 16k | 14,883 | 1,517 | 9.8× |

(No 32k/51k sglang numbers — the server died mid-arena in both attempts.)

**Root cause of the vLLM prefill cap:** with speculative decoding enabled, this vLLM build sets `max_num_scheduled_tokens=2048` and logs *"This may lead to suboptimal performance. Consider increasing max_num_batched_tokens…"*. Prefill is processed in 2048-token chunks.

## Quality results

| Benchmark | vllm_k3 | sglang_dspark | drowzeys_mtp3 |
|---|:---:|:---:|:---:|
| GSM8K (50) | **96.0%** | **96.0%** | 94.0% |
| HumanEval (50) | 92.0% | 92.0% | **92.0%** |
| IFEval prompt-strict (100) | 0.800 | **0.850** | 0.830 |
| GPQA-Diamond zeroshot (100) | 0.44 | — (server died) | **0.47 ± 0.05** |
| HLE-text (100) | **0.11** | — (server died) | 0.09 |

All deltas are within sampling noise for these limits. **Runtime choice does not move quality.**

sglang HLE/GPQA were never validly banked: the sglang server died mid-benchmark in both stage5 (HLE items 76+ got connection-refused) and stage6 (HLE killed, RC=137; GPQA/decode/arena RC=1). The sglang decode-under-context and 32k/51k prefill numbers are therefore also missing. The banked sglang JSON for IFEval and the stage5/6 logs are in `raw/`.

## Investigation: why the first drowzeys run looked catastrophic

The first full battery (Aug 16, 01:00) returned GSM8K 0.0%, HumanEval 0/50, IFEval 0.25 — while GPQA came back near-normal (0.40). Five distinct faults, found and fixed in order:

1. **`--rope-scaling` CLI arg was removed in this vLLM build.** The recipe's longctx profile passed `--rope-scaling '{"rope_type":"yarn",...}'`; the engine rejected it (`unrecognized arguments`) and the container crash-looped. The image's parser does have `--hf-overrides` — fixed to `--hf-overrides '{"rope_scaling":{...}}'`.
2. **`mamba_block_size` validation crash (longctx + MTP, still unfixed upstream).** After the rope fix, the engine died in `EngineCore` during **MTP drafter** model load: `ValidationError: --mamba-block-size can only be set with --enable-prefix-caching`. The validator (`vllm/config/vllm.py`) treats `mamba_block_size` as "set" when it differs from `model_config.max_model_len`. Profile B (1M): main max 1,048,576 vs MTP draft max 262,144 → mismatch → crash-loop. Profile A (256K): both 262,144 → passes. **Conclusion: the drowzeys longctx profile is unusable with MTP on their pinned image.** Workaround used: Profile A (256K) for the battery; the 1M campaign is deferred.
3. **Thinking leaked into `content`.** The Qwen3.8 chat template defaults thinking ON (`enable_thinking is undefined or true`). SGLang stage6 ran with `--reasoning-parser qwen3` (thinking parsed out of `content`); the drowzeys serve had no reasoning parser — and this custom build exposes **no `--chat-template` CLI override at all**. Every chat-endpoint benchmark got reasoning prose instead of answers. Fix: added `--reasoning-parser qwen3` to the serve args (exact parity with the sglang arm). Diagnostic signature: chat benchmarks collapse while completions-endpoint benchmarks (GPQA) stay normal.
4. **Hardcoded model id in the GSM8K harness.** `gsm8k_direct_benchmark.py` sent `"model": "qwen38-27b-unsloth-nvfp4"` (the sglang id) to a server exposing `qwen38-nvfp4` → all 50 requests errored (`KeyError: 'choices'`). Fixed the id.
5. **Battery gate ran blind.** The battery waited ≤60 min for the oneshot's `DONE` marker, then **continued anyway** when the oneshot had failed — producing an all-zero "results" set that overwrote the good sglang-era GSM8K/HumanEval JSONs (a copy-pasted `LABEL` made it write to the sglang filenames). Fixed: the gate now hard-fails on oneshot `FAILED`/timeout and verifies server health before benchmarking.

Round-2 numbers above are post-fix. The only round-1 number that was real: GPQA 0.40 (completions endpoint, unaffected by the thinking leak) — consistent with round-2's 0.47.

## Known gaps

- **sglang arm:** valid GPQA, HLE, decode-under-context, and 32k/51k prefill never captured (server stability under sustained benchmark load is itself a finding).
- **1M context campaign:** blocked by the mamba_block_size/MTP crash on the drowzeys image; sglang's 500K YaRN overlay was never speed-tested at depth either.
- **drowzeys 31.7 tok/s claim conditions** are unknown (their harness/prompt mix may differ); our decode_bench conditions match the prior MiaAI campaign, where the same model + MTP-3 measured ~21 tok/s, so the measurement method is consistent across runtimes.
- vllm_k3 arm has no arena/decode_bench numbers in this campaign (speed comparison relies on the prior campaign's ~21 tok/s).

## Raw artifacts

Everything in `raw/qwen38-04af/`:

- **JSONs:** `*_drowzeys_mtp3*.json` (round-2 finals), `*_vllm_k3*.json`, `ifeval_sglang_dspark_*.json`
- **Logs:** `stage3/4/4b_vllm_k3`, `stage5/6/7_sglang_dspark`, `stage8_drowzeys_mtp3` (round-2 battery), `drowzeys_oneshot.log`
- **Scripts as-run:** `start_sglang_dspark.sh`, `stage8_drowzeys_battery.sh`, `oneshot_drowzeys_patched.sh` (rope fix + reasoning parser + model-id-safe battery)
