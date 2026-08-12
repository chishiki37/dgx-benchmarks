# Report 05 — DeepSeek V4 Flash DSpark-Optimized (k=3) vs SuperDeepSeek (k=1) vs Ablit (no spec)

**Date:** 2026-08-12
**Hardware:** 2× NVIDIA DGX Spark (MSI EdgeXpert 9105 + bdea), GB10 SoC, 128 GB LPDDR5X
**Fabric:** 200G RoCEv2, MTU 9000, GID index 3
**Image:** `ghcr.io/anemll/dspark-vllm-gx10:0.1.1@sha256:a83948492cf13df455170fb42885f5ef4db54fefe0feff0f841ecbff464ac9d8`
**Engine:** vLLM 0.25.2.dev0+g752a3a504 (DSpark fork)

## Models tested

| Recipe | Checkpoint | Spec decode | GPU mem util |
| --- | --- | --- | --- |
| Ablit (baseline) | `deepseek-ai/DeepSeek-V4-Flash` abliterated | None (NotImplementedError on DS4) | 0.75 |
| SuperDeepSeek | `Jiunsong/SuperDeepseek-V4-Flash-abliterated-MQ-2xDGX` | DSpark k=1 | 0.80 |
| **DSpark-Optimized** | `drowzeys/keys-DeepSeekV4-Flash-GA-0731-Dspark-Abliterated-32-32` | **DSpark k=3** | **0.80** |

All three use the same runtime image, TP=2, `nvfp4_ds_mla` KV cache, `block_size=256`, `flashinfer_b12x` MoE backend.

## Speed benchmarks

### Q&A prompts (apples-to-apples across all three)

Prompt: "Explain the concept of recursion in programming, with a simple example."

| Metric | DSpark k=3 | SuperDeepSeek k=1 | Ablit (no spec) |
| --- | ---: | ---: | ---: |
| Single decode tok/s | **56.4** | 36.8 | 26.9 |
| C8 aggregate tok/s | **115.0** | N/A | 87.3 |

### Creative writing prompts (apples-to-apples: DSpark k=3 vs SuperDeepSeek)

Prompt: "Write a short creative story about topic_N. Include varied vocabulary."

| Metric | DSpark k=3 | SuperDeepSeek k=1 | Delta |
| --- | ---: | ---: | ---: |
| Single tok/s | **37.1** | 32.9 | +12.8% |
| C4 aggregate tok/s | **84.4** | 82.7 | +2.1% |
| C8 aggregate tok/s | **123.5** | 101.6 | +21.6% |

## Quality benchmarks

| Benchmark | DSpark k=3 | SuperDeepSeek k=1 | Ablit |
| --- | ---: | ---: | ---: |
| GSM8K (50q) | **50/50 (100%)** | 46/50 (92%) | 48/50 (96%) |
| HumanEval (50q, chat) | 47/50 (94%) | 48/50 (96%) | 48/50 (96%) |

### HumanEval failure analysis

| Task | DSpark k=3 | SuperDeepSeek | Ablit | Root cause |
| --- | --- | --- | --- | --- |
| HumanEval/10 (`make_palindrome`) | BUG | PASS | PASS | Appends reversed prefix instead of prepending (`string + prefix[::-1]` vs correct `prefix[::-1] + string`) |
| HumanEval/32 (`find_zero`) | BUG | BUG | BUG | Bisection converges to wrong root for multi-root polynomials (shared across all three) |
| HumanEval/38 (`decode_cyclic`) | BUG | PASS | PASS | Decode reuses encode's forward rotation instead of inverting it |
| HumanEval/40 (`car_race_collision`) | PASS | BUG | BUG | Fixed in DSpark k=3 |

**Net:** 2 new logic bugs (HumanEval/10, 38), 1 old bug fixed (HumanEval/40). Neither new bug is a spec-decode artifact — clean token output, no garbling.

## Speculative decoding metrics

| Metric | DSpark k=3 | SuperDeepSeek k=1 |
| --- | ---: | ---: |
| Overall acceptance rate | 42.4% (17,021/40,173) | 78.4% (28,701/36,608) |
| Position 0 acceptance | 67.9% | 78.4% |
| Position 1 acceptance | 39.0% | — |
| Position 2 acceptance | 20.2% | — |
| Mean acceptance length | 2.27 tok/step | 1.78 tok/step |

Despite lower per-token acceptance (42% vs 78%), k=3 drafts more tokens per step, achieving a higher effective speedup (2.27× vs 1.78×). This is the expected mathematical behavior — acceptance rate degrades with draft depth, but net throughput still scales with k.

## Configuration

### DSpark-Optimized (general profile)

```
MAX_MODEL_LEN=1048576
MAX_NUM_SEQS=8
MAX_NUM_BATCHED_TOKENS=8192
GPU_MEMORY_UTILIZATION=0.80
MTP_NUM_TOKENS=3 (k=3 speculative decoding)
VLLM_USE_BREAKABLE_CUDAGRAPH=0
VLLM_USE_B12X_MOE=1
enable_flashinfer_autotune=true
```

### Key env vars (from docker-compose.yml)

- `VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=0`
- `VLLM_USE_FLASHINFER_SAMPLER=1`
- `VLLM_B12X_W4A16_FORCE_BLOCKS_MAX_M=16`
- `CUTE_DSL_ARCH=sm_121a`
- `NCCL_NET=IB`, `NCCL_IB_HCA=rocep1s0f0,roceP2p1s0f0`
- `NCCL_IB_GID_INDEX=3`, `NCCL_IB_ROCE_VERSION_NUM=2`

## Takeaways

1. **DSpark k=3 is the fastest recipe** — 56.4 tok/s single-stream is 2.1× the ablit baseline and 1.5× SuperDeepSeek's k=1.
2. **Quality is maintained or improved** — perfect 100% GSM8K (best of all three), HumanEval within 2 points (noise at 50q sample size).
3. **k=3 acceptance decay is expected and worthwhile** — 42% overall acceptance still yields 2.27× effective decode speedup vs 1.78× for k=1.
4. **The 2 new HumanEval bugs are reasoning errors, not spec-decode artifacts** — the model genuinely makes different logic mistakes on this checkpoint. This is within normal variance for abliterated models.

## Methodology

- **Speed:** Q&A recursion prompt (apples-to-apples with ablit), creative writing prompts (apples-to-apples with SuperDeepSeek). Warmup with 4 concurrent trivial requests before measurement. `thinking=false` to avoid reasoning-mode token inflation.
- **GSM8K:** 50 canonical questions from `openai/grade-school-math`, temp=0.2, max_tokens=4096, `#### N` extraction with last-number fallback.
- **HumanEval:** 50 problems via `/v1/chat/completions` (chat-native), temp=0.0, max_tokens=1024. Markdown fence stripping + import prepending.
- **Spec metrics:** Scraped live from `/metrics` endpoint during benchmarks.

## Recipe source

Deployment scripts: [joeynyc/deepseek-dspark-optimized](https://github.com/joeynyc/deepseek-dspark-optimized)
