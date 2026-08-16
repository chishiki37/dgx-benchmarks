# Raw artifacts — Qwen3.8-27B-Uncensored-FP8 campaign (edgexpert-04af, Aug 16 2026)

Companion to [Report 08](../../08-qwen38-fp8-uncensored-single-spark.md).

## Layout

**Quality JSONs**
- `gsm8k_fp8_uncensored.json` — 50q, step-by-step, `#### N` extraction (96%)
- `humaneval_fp8_uncensored.json` — 50 chat-native (90%)
- `ifeval_fp8_uncensored_rerun_*.json` — lm_eval ifeval, c=4 + timeout=1800 (0.82 prompt-strict; third attempt — see Report 08 footnote)
- `gpqa_fp8_uncensored_*.json` — lm_eval gpqa_diamond_zeroshot, completions endpoint (0.44)
- `hle_fp8_uncensored.json` — HLE-text 100, thinking-off exact match (0.11)

**Speed**
- `decode_fp8_uncensored.run.log` — decode_bench on the winner config (12.3–12.4 tok/s)
- `arena_fp8_uncensored.run.log` — arena ladder 2k–51k c=1

**Sweep**
- `sweep_summary.json` — full 4-config sweep with per-run decode values + winner
- `sweep.log`, `decode_mtp*.log`, `arena_mtp*.log`, `launch_mtp*.log` — per-config evidence

**Campaign**
- `battery_fp8_uncensored.log` — stage order + RCs + timings
- `server_info.txt` — winner container serve args / CUDA-graph / MTP log lines
- `harness/` — campaign scripts as-run: `serve_fp8.py` (docker launch + health), `sweep_fp8.py` (config sweep + auto-winner), `battery_fp8.py` (gated battery), `gsm8k_fp8.py` (GSM8K harness patched for model id + local dataset), `download_curl.py` (curl-based HF downloader — IPv6 on 04af hangs Python HTTP)

## Server state at campaign end

Winner container `qwen38fp8` left serving on :8090 (no restart policy) — `docker rm -f qwen38fp8` returns the node to idle. Model dir: `~/models-local-qwen38fp8/Qwen3.8-27B-Uncensored-FP8` (30.9 GB).
