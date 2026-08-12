# Muse-Glimmer and Friends — Benchmark Reports

Benchmark and optimization reports for Muse-Glimmer-30B, Qwen3.6, Nemotron-3.5-Lightning, DeepSeek V4 Flash abliterated variants and other models on NVIDIA DGX Spark (GB10).

## Reports

1. **[Glimmer Optimization Study](01-glimmer-optimization.md)** — Full optimization journey: BF16 → Q4 kquant → DFlash speculative decoding (10× speedup), plus NVFP4 via SGLang. Includes 8-config autoresearch sweeps for both frameworks.

2. **[Glimmer vs Qwen Comparison](02-glimmer-vs-qwen.md)** — Head-to-head comparison with Qwen3.6-27B: decode speed, GSM8K, HumanEval pass@1, architecture impact, and use-case recommendations.

3. **[Nemotron Three-Way Comparison](03-nemotron-three-way-comparison.md)** — Nemotron-3.5-Lightning-30B-A3B (MoE, NVFP4, vLLM) vs Glimmer and Qwen. Nemotron dominates: 95.6 tok/s (2× faster), 100% GSM8K, 92% HumanEval. Includes MoE architecture analysis and DFlash vs MTP comparison.

4. **[SuperDeepSeek vs Ablit](04-superdeepseek-vs-ablit-comparison.md)** — Two abliterated DeepSeek V4 Flash checkpoints, head-to-head on identical 2-node hardware. SuperDeepSeek-MQ wins on speed (+37% single-stream) and matches ablit at 96% HumanEval. Includes the endpoint-mismatch investigation that initially looked like a quality regression.

## Key Results

| Config | Framework | Decode (tok/s) | GSM8K | HumanEval |
|--------|-----------|:--------------:|:-----:|:---------:|
| **Nemotron NVFP4** | **vLLM** | **95.6** | **100%** | **92%** |
| **SuperDeepSeek-MQ** | **vLLM DSpark** | **36.8** | **92%*** | **96%** |
| Ablit (DSpark runtime) | vLLM DSpark | 26.9 | 96%* | 96% |
| Qwen Q4+DFlash | llama.cpp | 47.3 | 92% | 92% |
| Glimmer Q4+DFlash | llama.cpp | 38.3 | 96% | 82% |
| Glimmer NVFP4 | SGLang | 11.3 | 86% | 82% |

\* After smart-extraction re-score (thinking mode puts reasoning in a separate field, breaking simple `#### N` regex).

## Hardware
- NVIDIA DGX Spark (GB10, 128 GB unified memory)
- llama.cpp: CUDA 13.0, sm_121
- SGLang: FlashInfer SM120 backend, muse-glimmer branch (PR #34262)
- vLLM: 0.21.1rc1 (ablit, Nemotron) / 0.25.2.dev0 (SuperDeepSeek-MQ)
- SuperDeepSeek-MQ: ghcr.io/anemll/dspark-vllm-gx10:0.1.1, flashinfer_b12x MoE, DSpark K=1 speculative

## Date
August 10–12, 2026
