# Muse-Glimmer and Friends — Benchmark Reports

Benchmark and optimization reports for Muse-Glimmer-30B, Qwen3.6, Nemotron-3.5-Lightning, DeepSeek V4 Flash abliterated variants and other models on NVIDIA DGX Spark (GB10).

## Reports

1. **[Glimmer Optimization Study](01-glimmer-optimization.md)** — Full optimization journey: BF16 → Q4 kquant → DFlash speculative decoding (10× speedup), plus NVFP4 via SGLang. Includes 8-config autoresearch sweeps for both frameworks.

2. **[Glimmer vs Qwen Comparison](02-glimmer-vs-qwen.md)** — Head-to-head comparison with Qwen3.6-27B: decode speed, GSM8K, HumanEval pass@1, architecture impact, and use-case recommendations.

3. **[Nemotron Three-Way Comparison](03-nemotron-three-way-comparison.md)** — Nemotron-3.5-Lightning-30B-A3B (MoE, NVFP4, vLLM) vs Glimmer and Qwen. Nemotron dominates: 95.6 tok/s (2× faster), 100% GSM8K, 92% HumanEval. Includes MoE architecture analysis and DFlash vs MTP comparison.

4. **[SuperDeepSeek vs Ablit](04-superdeepseek-vs-ablit-comparison.md)** — Two abliterated DeepSeek V4 Flash checkpoints, head-to-head on identical 2-node hardware. SuperDeepSeek-MQ wins on speed (+37% single-stream) and matches ablit at 96% HumanEval. Includes the endpoint-mismatch investigation that initially looked like a quality regression.

5. **[DSpark-Optimized k=3 Comparison](05-dspark-optimized-k3-comparison.md)** — Third abliterated checkpoint (`drowzeys/keys-...-Abliterated-32-32`) with DSpark k=3 speculative decoding. Fastest recipe yet: 56.4 tok/s single-stream (2.1× ablit), 100% GSM8K, 94% HumanEval. Includes per-position spec-decode acceptance analysis and HumanEval failure diff across all three checkpoints.

6. **[Post-Hotfix Revalidation](06-post-hotfix-revalidation.md)** — Same k=3 deployment after adopting Mia's hotfix set (#21/#22/#26v2/#27). Quality fully preserved: GSM8K 50/50, HumanEval 47/50 with bit-identical temp-0 failure set. Short-prompt speed unchanged (creative cells ±3%), GSM8K latency −29% (4.1→2.9 s/q). Intended gains confirmed: warm long-prefix TTFT 7.5–15× faster. Includes the harness-mismatch caveat (prompt wording + string-vs-float scoring explain apparent regressions).

7. **[Qwen3.8 Runtime Showdown (single Spark)](07-qwen38-runtime-showdown-single-spark.md)** — Qwen3.8-27B-NVFP4, three runtimes head-to-head on one GB10: drowzeys vLLM MTP3 vs SGLang DSPARK vs stock vLLM k=3. The drowzeys 31.7 tok/s claim does **not** reproduce (19.5–20.6 measured, parity with MiaAI ~21, 1.3× sglang's 16); quality is runtime-neutral (94–96% GSM8K, 92% HumanEval everywhere); SGLang wins prefill 3.5–10×. Includes the full forensics: removed `--rope-scaling` CLI, the `mamba_block_size` crash that breaks 1M+MTP on the drowzeys image, thinking-leak into `content` without a reasoning parser, and a blind battery gate that overwrote good results with zeros.

## Key Results

| Config | Framework | Decode (tok/s) | GSM8K | HumanEval |
|--------|-----------|:--------------:|:-----:|:---------:|
| **Nemotron NVFP4** | **vLLM** | **95.6** | **100%** | **92%** |
| **DSpark-Optimized k=3** | **vLLM DSpark** | **56.4** | **100%** | **94%** |
| **SuperDeepSeek-MQ** | **vLLM DSpark** | **36.8** | **92%*** | **96%** |
| Ablit (DSpark runtime) | vLLM DSpark | 26.9 | 96%* | 96% |
| Qwen3.8 drowzeys MTP3 (256K) | vLLM GB10 0.27 | 19.5–20.6 | 94% | 92% |
| Qwen3.8 MiaAI-style k=3 | vLLM nightly | ~21† | 96% | 92% |
| Qwen3.8 SGLang DSPARK | SGLang | 15.3–16.0 | 96% | 92% |
| Qwen Q4+DFlash | llama.cpp | 47.3 | 92% | 92% |
| Glimmer Q4+DFlash | llama.cpp | 38.3 | 96% | 82% |
| Glimmer NVFP4 | SGLang | 11.3 | 86% | 82% |

\* After smart-extraction re-score (thinking mode puts reasoning in a separate field, breaking simple `#### N` regex).
† Prior campaign, same model + MTP-3, same decode harness family (Report 07).

## Hardware
- NVIDIA DGX Spark (GB10, 128 GB unified memory)
- 2-node TP=2 deployments: MSI EdgeXpert 9105 + bdea, 200G RoCEv2, MTU 9000
- llama.cpp: CUDA 13.0, sm_121
- SGLang: FlashInfer SM120 backend, muse-glimmer branch (PR #34262)
- vLLM: 0.21.1rc1 (ablit, Nemotron) / 0.25.2.dev0 (SuperDeepSeek-MQ, DSpark k=3)
- Image: ghcr.io/anemll/dspark-vllm-gx10:0.1.1, flashinfer_b12x MoE, DSpark speculative decoding

## Date
August 10–16, 2026
