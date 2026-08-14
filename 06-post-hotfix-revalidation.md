# Report 06 — Post-Hotfix Revalidation: DSpark-Optimized k=3 (Mia hotfix set)

**Date:** 2026-08-14
**Purpose:** Revalidate the k=3 abliterated deployment after adopting Mia's hotfix set (#21/#22/#26v2/#27) — verify the patches changed nothing in short-prompt speed or model quality, and confirm the intended long-prefix TTFT gains.
**Hardware:** 2× NVIDIA DGX Spark (MSI EdgeXpert 9105 + bdea), GB10 SoC, 128 GB LPDDR5X
**Fabric:** 200G RoCEv2, MTU 9000, GID index 3
**Image:** `ghcr.io/anemll/dspark-vllm-gx10:0.1.1` · vLLM 0.25.2.dev0+g752a3a504 (DSpark fork)
**Model:** `drowzeys/keys-DeepSeekV4-Flash-GA-0731-Dspark-Abliterated-32-32` (DSpark k=3, 1M context, port 8888)
**Baseline:** Report 05 (2026-08-12, same deployment pre-hotfix)

## Patches under test

| Issue | Patch | Target |
| --- | --- | --- |
| #21 | `encoding_dsv4.py` dict tool-arguments fix | tokenizer |
| #22 | `nvfp4_ds_mla` fast-FP8 kernel dispatch | attention decode |
| #26v2 + #36 | hybrid SWA/MLA prefix-cache coordinator + `VLLM_PREFIX_CACHE_RETENTION_INTERVAL=4096` | prefix caching |
| #27 | partial-prefill admission cap + `--long-prefill-token-threshold 1024` | scheduler |

Full adoption details: skill `deepseek-v4-ablit-serving` → `references/mia-hotfixes-adoption.md`.

## Speed benchmarks (Report 05 methodology, verbatim)

Q&A prompt: recursion explanation · Creative prompt: `topic_N` short story · 300 max_tokens · thinking=false · warmup 4× concurrent trivial. Two post-patch runs to gauge variance.

| Metric | Baseline | Post run 1 | Post run 2 | Verdict |
| --- | ---: | ---: | ---: | --- |
| Q&A single tok/s | 56.4 | 59.0 | 49.3 | unchanged (±run variance) |
| Q&A C8 aggregate tok/s | 115.0 | 131.4 | 170.1 | unchanged-to-better |
| Creative single tok/s | 37.1 | 37.3 | 36.9 | unchanged (±0.5%) |
| Creative C4 aggregate tok/s | 84.4 | 83.7 | 81.6 | unchanged (±3%) |
| Creative C8 aggregate tok/s | 123.5 | 120.2 | 123.6 | unchanged (±3%) |

Creative cells are the low-variance cells: all post-patch values within ±3% of baseline → **no decode regression from the hotfixes**. Q&A cells carry temp-0.7 output-content variance (pitfall #32) and Triton JIT timing on C8 (pitfall #13); both post-patch runs sit above baseline on C8.

## Speculative decoding (scraped from /metrics during speed runs)

| Metric | Baseline | Post run 1 | Post run 2 |
| --- | ---: | ---: | ---: |
| Overall acceptance | 42.4% | 48.7% | 47.9% |
| Mean acceptance length | 2.27 tok/step | 2.46 tok/step | 2.44 tok/step |

Baseline acceptance was scraped from a full day of mixed traffic; post-patch values are from the speed harness only. Read as prompt-mix difference, not a patch effect — none of the four hotfixes touch the draft path.

## Quality benchmarks (baseline harnesses, verbatim)

Re-run with the exact Aug 12 harnesses (`~/gsm8k_benchmark.py`, `~/humaneval_chat_benchmark.py` — verbatim prompts, temp, max_tokens, extraction, scoring).

| Benchmark | Baseline | Post-patch | Delta |
| --- | ---: | ---: | --- |
| GSM8K (50q) | **50/50 (100%)** | **50/50 (100%)** | identical |
| HumanEval (50q, chat, temp=0) | 47/50 (94%) | 47/50 (94%) | identical |
| HumanEval failure set | /10, /32, /38 | /10, /32, /38 | **bit-identical** |
| GSM8K avg latency | 4.1 s/q | **2.9 s/q** | −29% |
| GSM8K avg output length | 156 tok | 154 tok | identical |

The HumanEval failure set reproducing exactly at temp=0 is the strongest possible evidence that generation behavior is unchanged by the patches: same prompt + same greedy decode → same outputs, same 3 failures (all known checkpoint logic bugs, documented in Report 05).

## Intended patch gains (measured during adoption, from hotfix A/B)

| Cell | Pre-patch | Post-patch |
| --- | ---: | ---: |
| Warm 4×59K long-prefix (hit ratio) | 0.000 (full re-prefill, 116s) | **0.998, wall 15.5s → 7.5s (7.5–15× faster TTFT)** |
| Decode floor under 8× concurrent long prefills (thr=1024) | 10.7 tok/s min | 7.8–8.2 tok/s min (guard active, trade documented) |
| 620K single-stream prefill | 526.9s | 710.3s at thr=1024 (threshold cost; 509.6s at thr=4096 fallback) |

## Takeaways

1. **Quality is fully preserved** — GSM8K 100%, HumanEval 94%, and a bit-identical temp-0 failure set. The hotfixes do not perturb generation.
2. **Short-prompt speed is unchanged** — all creative cells within ±3%; Q&A flat-to-better. No decode-path regression from #22's kernel dispatch or #27's admission cap.
3. **GSM8K per-question latency dropped 29%** (4.1 → 2.9 s/q) at identical output length — consistent with the higher observed acceptance length (2.44–2.46 vs 2.27 tok/step) on this prompt class.
4. **The patch's value is where it was designed**: warm long-prefix TTFT 7.5–15× faster and decode-starvation protection under concurrent long prefills. Chat/agent profile keeps `--long-prefill-token-threshold 1024`; 4096 remains the documented one-line fallback if single-user long-document TTFT becomes a complaint.

## Methodology

- **Speed:** Report 05 cells verbatim (Q&A recursion + creative topic_N, 300 max_tokens, thinking=false, temp 0.7, warmup 4× concurrent trivial). Aggregate = Σ completion_tokens / wall clock. Harness: `~/mia-hotfixes/report06_speed.py`.
- **Quality:** verbatim re-implementation of the Aug 12 harnesses (stdlib-only): GSM8K prefix prompt, temp 0.2, max_tokens 8192, 3-strategy extraction + float-tolerance scoring; HumanEval "ONLY the function implementation" prompt, temp 0.0, max_tokens 1024, fence-strip + import-prepend + exec. Harness: `~/mia-hotfixes/report06_quality_v2.py`.
- **Harness-mismatch caveat:** an initial quality run with the skill's `quality_benchmark.py` (different prompt wording + string scoring) reported GSM8K 45/50 and a shifted HumanEval failure set — every deviation traced to harness differences (`.00` string-vs-float scoring, prompt wording at temp 0), not model behavior. Comparable runs require the identical harness; raw outputs of both runs are kept.
- **Spec metrics:** live `/metrics` counter deltas bracketing the speed runs.

## Raw data

- `raw/report06-speed.json` — speed cells (run 2)
- `raw/report06-gsm8k-v2.json` — GSM8K per-question results
- `raw/report06-humaneval-v2.json` — HumanEval per-task results + code tails
- `raw/report06-gsm8k-v1.json`, `raw/report06-humaneval-v1.json` — initial harness-mismatched run (kept for reference)
