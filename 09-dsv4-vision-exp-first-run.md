# 09 — DeepSeek V4 Flash Vision-Exp: first run on the updated Mia recipe (2026-09-01)

Scope: first fleet run of the official
[`deepseek-ai/DeepSeek-V4-Flash-Vision-Exp`](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Vision-Exp)
(published 2026-08-31, revision pinned `86f746b3…`), served with the **updated**
[MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark](https://github.com/MiaAI-Lab/DeepSeek-v4-Flash-DSpark-2x-DGX-Spark)
recipe on lane **.12 (head) + .14** (cage-2 100G RoCE, MTU 9000, dual-HCA exact selector).
Comparison target: our August **0731-ablit k=3** deployment (reports 05/06), same
harness family, same prompt sets.

## Recipe as run (stock profile, unchanged)

- Image `ghcr.io/anemll/dspark-vllm-gx10:0.1.1` (Anemll DSpark vLLM 0.25.2.dev0 fork)
- TP=2, `MAX_MODEL_LEN=1048576` (1M), `MAX_NUM_SEQS=6`, batched 8192, k=6 spec
  (`MTP_NUM_TOKENS=6`; Vision-Exp `n_predict=3` forces k ≥ 5 and divisible by 3)
- `GPU_MEMORY_UTILIZATION_TEXT=0.835`, `nvfp4_ds_mla` KV, `LONG_PREFILL_TOKEN_THRESHOLD=1024`
  (issue #27), retention 4096 (#26), hotfixes #21/#22/#26/#27/#43 + spin-wait (#79) on
- `DEFAULT_THINKING=max` at the server; **bench/quality requests force `thinking=false`
  via request-level `chat_template_kwargs`** for comparability with the August numbers
  (request-level overrides win per the recipe README)
- Weights: 157 GiB, 48 shards, downloaded once on .14 via the recipe's prepare script,
  rsynced .14→.12 at 383 MB/s

**Booted clean first try** — GID auto-resolve handled our fabric, worker-first launch,
boot-shape warmup swept 47/47 JIT shapes, health green. KV pool: **13.86 GiB /
2,058,523 tokens**, 1.96× concurrency for full-1M requests (Mia's cluster: 17.04 GiB /
2.33M / 2.22× — ViT weight footprint + our util; the delta is cosmetic for this battery).

## Speed (e2e prose, temp 0.2, 256 tokens; warm run cited — fresh run within noise)

| metric | Vision-Exp stock | 0731-ablit k=3 (Aug) | Δ |
|---|---|---|---|
| Single-stream (median of 5) | **38.0 tok/s** | 56.4 | **−33%** |
| C4 aggregate | 76.6 | 107.8 | −29% |
| C6 aggregate | 102.4 | (not measured) | — |
| C8 aggregate (seqs-6 cap → queueing) | 80.5 | 121.4 | −34% |

0731 references are the link-study RoCE-100G numbers (same `ds4_bench` harness lineage;
single-stream is memory-bandwidth-bound, so the lane is not the variable). Mia's
published claims for this recipe are 62–83 single / ~162 @c6 — our lane lands below
both; workload mix (her bench vs our prose) likely explains part of it, the acceptance
difference below explains the rest.

**Mechanism — speculative acceptance.** Bench-window acceptance from `/metrics`:
**27.8%** (4,333 accepted / 15,558 draft tokens) vs ~48% measured on the August k=3
deployment with the same harness. Two compounding causes:

1. Vision-Exp's draft head is structurally heavier (`n_predict=3` vs 0731's 1), and k is
   forced 3→6 by the divisibility rule — every draft step costs more.
2. Prose at temp 0.2 is near-worst-case for DSpark acceptance (structured/code drafts
   better — same lesson as the GLM-5.3 DFlash2 work). ~72% of drafted tokens are rejected,
   so decode pays draft compute it doesn't keep.

Caveats: `DRAFT_SAMPLE_METHOD` stays stock probabilistic (the 0731 official cards paired
k+greedy; greedy is an untested follow-up here), and Mia's numbers may use a friendlier
workload. But vs 0731 on identical workload the decode tax is real.

## Quality (verbatim August harnesses, thinking off per-request)

| benchmark | Vision-Exp | 0731-ablit k=3 | Δ |
|---|---|---|---|
| GSM8K (50q) | 49/50 = **98%**¹ | 50/50 = 100% | −1 (artifact) |
| HumanEval (50q, temp 0) | **48/50 = 96%** | 47/50 = 94% | **+1 task** |
| GSM8K latency | 3.2 s/q | 2.9 s/q | +10% |

¹ The single GSM8K "failure" is extraction, not reasoning: the model answered `20.00.`
for expected `20` — correct value, trailing period broke the harness's `float()` parse.
Functionally at the 50/50 ceiling.

**HumanEval failure sets:** 0731 = {/10, /32, /38} → Vision-Exp = {/10, /38}.
**HumanEval/32 — the checkpoint logic bug documented since report 05 — is fixed.**
/10 and /38 remain the shared stubborn pair across every DSv4 checkpoint we've run.

## Verdict

Vision-Exp is not a speed upgrade: **−33% single-stream decode** at acceptance-driven
cost, C4/C8 down ~30%. It is a capability upgrade: quality at ceiling (GSM8K 98%
effective / HumanEval 96%, fixing the long-standing /32 bug), plus native `image_url`
vision and budgeted reasoning modes the 0731 checkpoints lack. Keep 0731-ablit k=3 for
latency-sensitive serving; Vision-Exp for vision/reasoning workloads where ~38 tok/s is
acceptable. Follow-ups queued: abliterated Vision-Exp (`drowzeys/keys-…-ablit`, same
recipe `ABLITERATED=1` + 26-shard overlay), and an optional greedy-draft probe.

## Operational notes

1. **Prepare-script image gotcha:** `IMAGE_PYTHON=/usr/bin/python3` is Anemll-only; on
   the stage-c image set `IMAGE_PYTHON=/opt/env/bin/python` or the download container
   fails to exec.
2. **Final teardown before lane reuse:** the GLM sweep left its last cell's engine loaded
   on both nodes (reports/06 note 3 pattern) — cleared before this launch.
3. No earlyoom on either node (recipe prerequisite already satisfied); MTU 9000 already
   set; dual-HCA exact selector `=rocep1s0f0,roceP2p1s0f0` per the recipe's measured note.
4. `.env.dspark` uses bare image tag (no digest) — docker save/load doesn't carry digests.

Raw: [`raw/dsv4fv/`](raw/dsv4fv/) — speed JSONs (fresh + warm), GSM8K/HumanEval results, both harnesses.
