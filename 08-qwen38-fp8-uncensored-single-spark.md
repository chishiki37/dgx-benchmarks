# Qwen3.8-27B Uncensored FP8 on a Single DGX Spark: FP8 vs NVFP4, Same Node, Same Harness

**Date:** 2026-08-16 · **Node:** edgexpert-04af (DGX Spark, GB10, 128 GB unified, sm_121a)
**Model:** `orcarouter/Qwen3.8-27B-Uncensored-FP8` (gated HF repo; abliterated/uncensored fine-tune of `Qwen/Qwen3.8-27B`, block-wise FP8 e4m3 W8A8 dynamic, 30.9 GB, 1 MTP layer)
**Runtime:** `ghcr.io/drowzeys/keys-vllm-027-gb10-qwen38:mtp3-20260813` (eugr GB10 vLLM 0.27, `Qwen3_5MTP` arch auto-resolved, `quantization=fp8` auto-detected)
**Companion artifacts:** [`raw/qwen38fp8-04af/`](raw/qwen38fp8-04af/) · **Baseline:** Report 07 (NVFP4 arms, identical battery)

---

## TL;DR

1. **FP8 decode: 12.4 tok/s single-stream** (MTP1, bf16 KV, util 0.90) vs **NVFP4 19.5–20.7 tok/s** (MTP3) from Report 07 — NVFP4 is **~1.6× faster** on this node. The gap is smaller than the 2× weight-bytes ratio because this FP8 checkpoint kept only **1 of the 3 MTP layers** (+57% from MTP1 here vs the larger MTP3 lift on NVFP4).
2. **Quality is quant-neutral and abliteration-neutral:** GSM8K **96%** (identical to NVFP4), HumanEval **90%** (vs 92%, 2 problems at n=50), IFEval **0.82** (within the NVFP4 arms' 0.80–0.85 range), GPQA-Diamond **0.44** (vs 0.47±0.05, within stderr), HLE **0.11** (identical). The uncensored fine-tune shows **no capability tax** on the academic battery.
3. **Sweep findings:** MTP1 is worth **+57%** (7.95 → 12.50 tok/s); KV-cache fp8 vs bf16 and gpu-util 0.90 vs 0.92 are within noise. Winner: `k=1, kv=auto, util=0.90`.
4. **Prefill** plateaus at ~1.5–1.6K tok/s (same vLLM spec-decode `max_num_scheduled_tokens=2048` throttle documented in Report 07; NVFP4 plateaued ~1.9K).
5. **Infra findings:** IPv6 is broken on 04af (HuggingFace/CloudFront v6 hangs — Python HTTP stalls, curl survives via happy-eyeballs); lm_eval 0.4.12's aiohttp session closes permanently after a request timeout under concurrency — the FP8 model's slower generations trigger it at c=8, safe at c=4.

---

## Campaign shape

Autoresearch sweep **first** (4 configs), then the usual battery on the winner — quality first, speed last (arena can kill servers).

### Autoresearch sweep (single-stream decode, decode_bench mean of 3 runs)

| Config | MTP k | KV dtype | gpu-util | Boot | Decode (tok/s) |
|---|:-:|:-:|:-:|:-:|:-:|
| **mtp1_kvauto_u90** 🏆 | 1 | auto (bf16) | 0.90 | 565 s | **12.50** |
| mtp1_kvfp8_u90 | 1 | fp8 | 0.90 | 503 s | 12.45 |
| mtp1_kvfp8_u92 | 1 | fp8 | 0.92 | 525 s | 12.20 |
| mtp0_kvfp8_u90 | 0 | fp8 | 0.90 | 430 s | 7.95 |

Per-run stability is tight (12.2–12.9 across thinking-on/off, 512/1024 tokens). KV dtype and util deltas are noise; MTP1 is the only lever that matters on this checkpoint.

### Speed — decode_bench (winner config)

| Run | Tokens | Total | TTFT | e2e | Decode |
|---|:-:|:-:|:-:|:-:|:-:|
| thinking-off 512 | 512 | 41.6 s | 0.38 s | 12.32 | **12.41 tok/s** |
| thinking-on 512 | 512 | 41.8 s | 0.31 s | 12.25 | 12.32 tok/s |
| thinking-off 1024 | 717 | 58.3 s | 0.31 s | 12.30 | 12.35 tok/s |

### Speed — arena ladder (c=1)

| Depth | Prefill (ctx_pp) | Decode under ctx | TTFT |
|---|:-:|:-:|:-:|
| 2k (1.1K actual) | 544 tok/s | 12.55 tok/s | 789 ms |
| 4k (2.1K) | 880 tok/s | 12.07 tok/s | 1.23 s |
| 8k (4.1K) | 1,192 tok/s | 12.00 tok/s | 2.29 s |
| 16k (8.2K) | 1,441 tok/s | 11.85 tok/s | 4.53 s |
| 32k (16.4K) | 1,563 tok/s | 11.25 tok/s | 9.26 s |
| 51k (25.6K) | 1,557 tok/s | 10.91 tok/s | 15.2 s |

Decode-under-context degrades gently (−13% at 51k); prefill saturates ~1.56K tok/s — the same `max_num_scheduled_tokens=2048` spec-decode throttle as Report 07's vLLM arms (warning present in serve logs).

### Quality battery (usual order, usual limits)

| Benchmark | **FP8-Uncensored (this run)** | NVFP4 drowzeys MTP3 (Report 07) | NVFP4 vllm_k3 | NVFP4 sglang |
|---|:-:|:-:|:-:|:-:|
| GSM8K (50, step-by-step, `#### N`) | **96.0%** | 96.0% | 96.0% | 94.0% |
| HumanEval (50, chat-native) | **90.0%** | 92.0% | 92.0% | 92.0% |
| IFEval (100, prompt-strict) | **0.82 ± 0.04** | 0.850 | 0.800 | 0.830 |
| GPQA-Diamond zeroshot (100, completions) | **0.44** | 0.47 ± 0.05 | — (server died) | — (server died) |
| HLE-text (100, thinking-off, exact match) | **0.11** | 0.11 | — | 0.09 |

¹ IFEval needed three attempts: attempt 1 died at ~85/100 (concurrency 8 + default 300 s client timeout → lm_eval's aiohttp session closed permanently after one request exhausted retries); attempt 2 at concurrency 4 hit the same timeout wall at 89/100 (at 12 tok/s, thinking-heavy 4K-token generations exceed 300 s even single-stream). Attempt 3 added `timeout=1800` to lm_eval's model_args and completed cleanly in 50 min. The NVFP4 arms never hit this — their 2.5× faster decode kept every generation under the default timeout. No effect on the measurement itself (temp 0, same prompts).

---

## FP8 vs NVFP4 — the comparison everyone asked for

| | **NVFP4 (unsloth)** | **FP8-Uncensored (orcarouter)** |
|---|:-:|:-:|
| Size on disk | 22 GB | 30.9 GB |
| Spec decode | MTP3 (3 draft layers) | MTP1 (1 draft layer) |
| Decode single-stream | 19.5–20.7 tok/s | 12.4 tok/s |
| Prefill plateau | ~1.9K tok/s | ~1.6K tok/s |
| GSM8K / HumanEval | 96% / 92% | 96% / 90% |
| GPQA / HLE | 0.47 / 0.11 | 0.44 / 0.11 |

- **Speed:** NVFP4 wins ~1.6×. Two compounding causes: half the weight bytes per token (bandwidth-bound decode), and 3 MTP draft layers vs 1. The no-spec comparison (FP8 7.95 tok/s vs drowzeys' claimed 11.1 no-spec NVFP4) is only 1.4× — but their 11.1 was never independently reproduced on our harness (Report 07 found their MTP3 claim similarly optimistic), so treat 1.4× as soft.
- **Quality:** statistically indistinguishable across all five banked benchmarks. **Abliteration cost: zero** on this battery.
- **What this FP8 repo is actually for:** the uncensored behavior — which this battery does not measure (no refusal panel). If you need the uncensored behavior specifically, you pay 1.6× latency and 40% more disk; if you just want Qwen3.8-27B speed/quality on Spark, NVFP4 remains the better serving choice.

## Pitfalls & forensics

1. **IPv6 blackhole on 04af.** `huggingface.co` resolves to CloudFront IPv6 first; v6 connections hang indefinitely (curl `-6` test: 10 s timeout, `-4`: 0.05 s). Python's urllib/httpx/xet all stall on it — killed the first download attempt (5 min, zero bytes) and earlier HF probes. Fix: curl-based parallel downloader with resume + size verification (30.9 GB in 14.2 min, 36 MB/s). Node-level fix (disable v6 or prefer v4 in gai.conf) deferred — needs sudo.
2. **Gated repo.** `orcarouter/Qwen3.8-27B-Uncensored-FP8` is auto-gated; the node's existing HF token already had access (verified with an API probe before downloading).
3. **lm_eval session-close bug.** 0.4.12 `local-chat-completions` + concurrency: one timed-out request exhausts `max_retries`, then every pending request dies with `Session is closed`. Slow models (FP8 at 12 tok/s with 4K-token thinking budgets at c=8) hit it; NVFP4's 2.5× faster generations didn't. Mitigation: c=4 + max_retries=5.
4. **lm_eval output filenames** get timestamp suffixes appended (`gpqa_..._2026-08-16T22-13-22.json`) — battery scripts must glob, not assume exact names.
5. **FP8 kernel path on sm_121a** works out of the box in the keys-vllm GB10 image: `quantization=fp8` auto-detected from `quantization_config`, `Qwen3_5MTP` arch resolved, MTP draft shares embeddings/lm_head with target. No flags needed beyond the standard drowzeys set.
6. **MTP count differs per checkpoint.** This FP8 conversion ships `mtp_num_hidden_layers=1` (base Qwen3.8-27B has 3). Always check the config before choosing `num_speculative_tokens`.

## Reproduce

```bash
# download (gated; needs an approved HF token; curl used because IPv6 hangs)
python3 download_curl.py   # raw/qwen38fp8-04af/download_curl.py

# sweep + battery chain
python3 /tmp/launcher_fp8.py   # gates on download -> sweep -> battery
# or manually:
python3 serve_fp8.py --k 1 --kv auto --util 0.90 --port 8090
BENCH_URL=http://127.0.0.1:8090/v1/chat/completions BENCH_MODEL=qwen38-fp8 python3 /tmp/decode_bench.py
```

Serve args (winner): `vllm serve /models/Qwen3.8-27B-Uncensored-FP8 --served-model-name qwen38-fp8 --port 8090 --kv-cache-dtype auto --enable-flashinfer-autotune --enable-auto-tool-choice --tool-call-parser qwen3_xml --reasoning-parser qwen3 --max-model-len 262144 --gpu-memory-utilization 0.90 --speculative-config '{"method":"mtp","num_speculative_tokens":1}'` on `ghcr.io/drowzeys/keys-vllm-027-gb10-qwen38:mtp3-20260813` with `FLASHINFER_CUDA_ARCH_LIST=12.1a`.

## Server state at campaign end

Winner container `qwen38fp8` left serving on :8090 (restart policy: none) pending Vikas's call — `docker rm -f qwen38fp8` returns the node to idle.
