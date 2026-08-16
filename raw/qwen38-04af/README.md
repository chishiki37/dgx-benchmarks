# Raw artifacts — Qwen3.8 runtime showdown (edgexpert-04af, Aug 15–16 2026)

Companion to [Report 07](../../07-qwen38-runtime-showdown-single-spark.md).

## Layout

**Top level — final results + campaign logs**
- `*_drowzeys_mtp3*.json` (timestamped where applicable): round-2 finals (post reasoning-parser fix)
- `*_vllm_k3*.json`: stock-vLLM k=3 baseline results
- `ifeval_sglang_dspark_*.json`: the only valid sglang quality JSON (server died before GPQA/HLE banked)
- `stage2…stage8_*.log`: per-stage battery logs (sglang numbers live in the stage5/6 logs — its GSM8K/HumanEval JSONs were overwritten, see forensics)
- `drowzeys_oneshot.log`: final successful oneshot run (Profile A)
- `gsm8k.log` / `humaneval.log` / `runner.log` / `stage2_vllm_k3.log` / `stageN_nohup.out`: early k3-era chain logs

**`harness/` — benchmark scripts as-run at campaign end**
- `gsm8k_direct_benchmark.py` (model id fixed to `qwen38-nvfp4`), `humaneval_chat_benchmark.py`, `hle_eval2.py` (+ legacy `hle_eval.py`), `hf_access.py`
- `decode_bench.py`, `arena_ladder.py`: endpoint parameterized via `BENCH_URL` / `BENCH_MODEL` env vars (originally hardcoded to the sglang port 8888 — that bug is in the Report 07 forensics)

**`round1-forensics/` — the artifact round, kept as evidence**
- `stage8_sglang_dspark.log`: the battery that ran blind against a dead port (all-zero results). Note the filename itself is forensic: a copy-paste `LABEL="sglang_dspark"` in the drowzeys battery made it write under the sglang name and overwrite stage6's good JSONs
- `gsm8k/humaneval/hle_sglang_dspark.json`: the overwritten zero/garbage files
- `*_drowzeys_mtp3_round1*` + `gpqa...T07-22*.json`: round-1 drowzeys results (thinking-leak era). Round-1 GPQA 0.40 was the one real number (completions endpoint, no chat template)

**As-run launch/battery scripts** (top level): `start_sglang_dspark.sh`, `stage8_drowzeys_battery.sh` (patched: hard-fail gate + server-health check), `oneshot_drowzeys_patched.sh` (`--hf-overrides` rope fix + `--reasoning-parser qwen3`).

## Server state at campaign end

drowzeys container removed (`docker rm -f qwen38`), node idle. The `lmsysorg/sglang:qwen38-27b` image remains on the node for any future sglang re-run.
