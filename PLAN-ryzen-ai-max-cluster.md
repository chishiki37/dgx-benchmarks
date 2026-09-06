# PLAN — Distributed inference on Ryzen AI MAX+ 395 (Strix Halo)

Status: **Phase 1 (single-link PoC) complete.** Written 2026-09-06.

## Objective

Stand up a distributed-inference cluster on AMD Ryzen AI MAX+ 395 nodes as a parallel
track to the existing 8× DGX Spark fleet. The binding constraint is node-to-node
interconnect: onboard Ethernet is 10GbE, which is not enough to shard a model across
nodes. Target is **≥50 Gb/s usable** to make multi-node worthwhile.

Reference architecture is the Spark fleet — 200G RoCEv2, MTU 9000, NCCL over dual HCAs
(`rocep1s0f0,roceP2p1s0f0`), TP=2 (reports 04–06) and TP4+DCP4 across 4 nodes
(`glm-5.3-exl3-abliterated-4x-dgx-spark`).

## Phase 1 — single-link PoC (DONE)

Chain: M.2 slot → OCuLink adapter → OCuLink cable → AOOSTAR AG01 dock →
Mellanox MCX515A-CCAT → QSFP28 DAC → `edgexpert-9105`.

Result: **22.3 Gb/s** (4 streams), 19.5 Gb/s single, 0.59 ms RTT, MTU 1500.
Full detail in [report 10](10-aimax-spark-100g-oculink-link.md).

**Verdict: concept proven, target not met.** 22.3 Gb/s is 2.2× the 10GbE baseline, which
establishes that the OCuLink path is viable at all. But it is **not** 50 Gb/s, and it
cannot become 50 Gb/s with this NIC — see the math below. The run also ended with the
NIC dropping off the PCIe bus under 8-stream load, unrecovered without a power cycle.

## The bandwidth ceiling is arithmetic, not tuning

Both M.2 (M-key) and OCuLink (SFF-8611) carry **exactly four PCIe lanes**. Confirmed on
this board: `00:02.5` at `max=x4` is the *only* expansion root port; every x16 port
(`00:08.1/.2/.3`) is internal — iGPU, USB4, NPU. **One NIC per node is the hard limit,
and it is four lanes wide.**

| Card generation | Link | Raw | Realistically usable | Meets 50 G target? |
|---|---|---|---|:---:|
| MCX515A-CCAT (PCIe 3.0) | Gen3 x4 | 31.5 Gb/s | 22–27 Gb/s | **No — impossible** |
| E810-CQDA1 (PCIe 4.0) | Gen4 x4 | 63.0 Gb/s | ~50–55 Gb/s | **Only just** |
| E810 if OCuLink falls back | Gen3 x4 | 31.5 Gb/s | 22–27 Gb/s | **No** |

Two consequences that should shape expectations:

1. **The Gen4 NIC is necessary, not an optimization.** The 50 Gb/s target is
   unreachable on a PCIe 3.0 card at x4 — no MTU, offload, or stream-count tuning
   closes a gap that wide.
2. **Even at Gen4 there is no headroom.** ~50–55 Gb/s usable means the target is met
   with nothing to spare. If the OCuLink adapter or cable is not Gen4-clean and the link
   trains down to 8 GT/s, the target becomes unreachable on this platform entirely.

**First measurement when the E810 arrives** — before any throughput test:

```bash
cat /sys/bus/pci/devices/<bdf>/current_link_speed   # need "16.0 GT/s PCIe"
cat /sys/bus/pci/devices/<bdf>/current_link_width   # x4
```

This single read decides whether the plan is viable. Treat it as a go/no-go gate.

## Phase 2 — E810-CQDA1 swap (NIC arriving ~2026-09-08 → 09-21)

Same slot, adapter, cable, and dock; different card. Serves two purposes at once:

- **Bandwidth:** does Gen4 x4 materialize, and does it clear 50 Gb/s?
- **Root cause:** it is the card-swap arm of the ConnectX-5 failure isolation. E810
  stable under load implicates the CX-5; E810 also dropping implicates the dock, cable,
  adapter, or the dock's thermal/power environment.

**Run the CX-5 fan test first.** Without it, a successful E810 result is confounded —
you will not know whether you fixed a card fault or merely installed a cooler-running
part. Five minutes with a desk fan removes that ambiguity permanently.

Notes: driver is `ice`, not `mlx5`. Wants a DDP package present (`dmesg | grep -i ddp`)
or it runs degraded. RoCEv2 comes via `irdma`.

## Phase 3 — second Ryzen node, 2-node cluster

Direct-attach, no switch needed at n=2. Requires a second dock, adapter, cable, and NIC.

This is where the plan meets its real test, and where the metric must change (below).

## Phase 4 — scale beyond 2

At n≥3 every node needs a switch port, since each node has exactly one NIC. The CRS812
becomes load-bearing here — see open questions.

---

# Gaps and risks

## 1. iperf3 TCP bandwidth is the wrong metric — this is the biggest gap

The PoC measured TCP throughput. Distributed inference does not run on TCP throughput;
it runs on **collective operations**, and for tensor parallelism the binding constraint
is **latency, not bandwidth**.

Rough shape of the problem for TP: each transformer layer requires ~2 all-reduces per
token. A 60–80 layer model is therefore 120–160 synchronization round-trips **per token**.

| Transport | Round-trip | 160 RTs/token | Implied ceiling |
|---|---|---|---|
| TCP/IP (measured PoC) | ~590 µs | ~94 ms | **~10 tok/s** |
| RoCEv2 RDMA | ~2–5 µs | ~0.3–0.8 ms | ~1,000+ tok/s |

**A 50 Gb/s TCP link would still be unusable for tensor parallelism.** The Spark fleet
does not run TCP — it runs NCCL over RoCEv2, which is why it works. Any Ryzen cluster
must reproduce that, and the PoC has not yet demonstrated RDMA at all.

**Action:** re-baseline on RDMA metrics before drawing conclusions about the plan.

```bash
# perftest (RoCE) - the numbers that actually matter
ib_write_bw  -d <rdma_dev> -x <gid> -F   # bandwidth
ib_write_lat -d <rdma_dev> -x <gid> -F   # latency  <- the critical one
```

The CX-5 already exposes `/sys/class/infiniband/mlx5_0`, so RoCEv2 was available during
the PoC and simply was not exercised. This is the highest-value next measurement,
independent of which NIC is installed.

## 2. Parallelism strategy is unchosen, and it changes the target

The 50 Gb/s figure appears to be a bandwidth intuition rather than a derived requirement.
What is actually needed depends entirely on how the model is split:

- **Tensor parallel** — all-reduce every layer. Latency-critical, bandwidth-hungry.
  Needs RDMA. This is what the Spark fleet does (TP=2, TP=4) over 200G.
- **Pipeline parallel** — only the activation tensor crosses each node boundary, once
  per token. For hidden 8192 at bf16 that is ~16 KB/token; at 50 tok/s, well under
  1 Gb/s. **Bandwidth is nearly irrelevant, and TCP latency is tolerable** because there
  is one hop per token rather than 160.

**If the goal is capacity (run bigger models) rather than single-stream speed, pipeline
parallelism over the existing 10GbE may already be sufficient** — and the entire OCuLink
programme is unnecessary. If the goal is single-stream decode speed matching the Spark
TP deployments, RDMA is mandatory and 50 Gb/s is the floor.

Deciding this first would either validate the hardware spend or avoid it.

## 3. Software stack is the largest unvalidated risk

The Spark fleet runs CUDA + NCCL + vLLM/SGLang. **None of that ports.** The Ryzen path
needs ROCm + RCCL, and the maturity gap is the real project risk — larger than the
interconnect.

Specific items to verify **before** buying a second node:

- Does **RCCL** work on gfx1151 (Strix Halo iGPU), and does its RDMA transport work over
  RoCE on this hardware? NCCL's `NCCL_NET=IB` path has no guaranteed RCCL equivalent here.
- Is **vLLM or SGLang** usable on a Strix Halo iGPU at all? ROCm support targets
  MI200/MI300 discrete parts; iGPU is a much weaker story. This may not be viable.
- **llama.cpp** is the realistic near-term path — ROCm and Vulkan backends both run on
  Strix Halo, and its **RPC backend** does distributed inference. It is pipeline-oriented
  and TCP-based, which loops back to gap #2: it would not need 50 Gb/s.

Recommendation: validate a two-node llama.cpp RPC run over the *existing 10GbE* first.
It costs nothing, and it establishes whether the software stack works before the
interconnect is scaled.

## 4. Unified memory is an underexploited advantage

Strix Halo shares LPDDR5X between CPU and iGPU (~256 GB/s, comparable to GB10's ~273).
There is no discrete VRAM and therefore **no host-to-device copy** in the inference path.
RDMA writes land directly in memory the iGPU can read.

This removes the GPUDirect problem that normally complicates RDMA + GPU, and is a genuine
architectural point in this platform's favour. Worth designing around rather than
treating the Ryzen node as a GPU box with slow VRAM.

Corollary: because decode is memory-bandwidth-bound and per-node bandwidth is
Spark-comparable, **per-node decode speed should be in the same class as a Spark** — the
value proposition is cost per node, not performance per node.

## 5. One NIC per node breaks parity with the Spark topology

The Spark deployments use **two HCAs per node** (`NCCL_IB_HCA=rocep1s0f0,roceP2p1s0f0`,
dual-rail). A Ryzen node physically cannot do this — one x4 port exists, total.

So a Ryzen cluster starts at roughly **half the per-node fabric width** of the Spark
reference architecture, before accounting for the x4 ceiling. Any performance model
extrapolated from the Spark results should carry that discount.

## 6. USB4 is a second interconnect you already own (unexplored)

This board has **two USB4 host routers** (`c9:00.5`, `c9:00.6`) and `thunderbolt_net` is
present in the kernel. USB4 networking gives roughly 20–25 Gb/s usable per link with no
dock, no adapter, and no PCIe slot consumed.

Three things this could enable:

- A **zero-cost 2-node PoC** that bypasses the entire OCuLink chain and its failure modes.
- A **second rail** alongside the OCuLink NIC, partially restoring the dual-rail parity
  lost in gap #5.
- A **3-node ring** without any switch, using both USB4 ports per node.

Latency will be worse than RoCE and it is not RDMA, so this does not solve gap #1 for
tensor parallelism — but for pipeline parallelism it may be entirely sufficient, and it
is testable this week for the price of a cable.

## 7. The OCuLink chain is three avoidable failure points

The PoC failure was in the PCIe path, and that path contains an adapter, a cable, and a
dock that a normal PCIe slot would not. **Strix Halo boards exist with a native PCIe x4
slot** (e.g. Framework Desktop). Same four lanes, same ceiling — but the adapter, cable,
and dock disappear, and with them most of the signal-integrity and slot-power risk.

If a second node is being purchased anyway, buying one with a real slot rather than
replicating the OCuLink stack is worth costing out. It would also make the two nodes
non-identical, which is itself a useful A/B on whether the dock is the problem.

## 8. Heterogeneous clustering with the Sparks is not viable

Worth stating explicitly to avoid a dead end: Ryzen (x86 + ROCm + RCCL) and Spark
(aarch64 + CUDA + NCCL) cannot be joined into one inference cluster. NCCL and RCCL do not
interoperate. The Ryzen build must be a **separate cluster**, not an extension of the
existing eight nodes.

## 9. Operational items carried over from the PoC

- **MTU 9000 was never enabled** — both ends still at 1500. The Spark fabric already runs
  jumbo; report 04 measured **−77% fabric latency** from that change alone. Free win,
  not yet taken.
- **AER is disabled on this platform** (`_OSC`), so PCIe errors are invisible. Any future
  bus-level fault will be as hard to diagnose as this one was.
- **Thermals are unmanaged.** A datacenter NIC in an open dock has no directed airflow.
  Whatever card is installed, this needs solving before sustained load is trusted.

---

# Open questions

1. **AG01 or AG02?** This document says AG01 per the latest description;
   [report 10](10-aimax-spark-100g-oculink-link.md) says AG02. One is wrong and should be
   corrected.
2. **What is the CRS812's role?** Reports 04 and 09 describe *direct* CX-7 attachment for
   the RoCE lanes, which suggests the switch may carry management/10GbE rather than the
   RDMA fabric. Phase 4 depends on this: if Ryzen nodes must reach RoCE through the
   switch, it needs **PFC/ECN support for lossless RoCEv2**, which is not a given on
   MikroTik hardware. Resilient RoCE / DCQCN may be required instead.
3. **Capacity or speed?** Determines TP vs PP, and therefore whether 50 Gb/s is the right
   target at all (gap #2).
4. **What is the per-node cost** of Ryzen + dock + adapter + cable + NIC versus one more
   Spark, given the Spark software stack already works?

# Immediate next actions

| # | Action | Cost | Unblocks |
|---|---|---|---|
| 1 | Power-cycle `aimax`, run `post-reboot.sh` | minutes | link restored |
| 2 | CX-5 fan test under 8-stream load | minutes | root cause, un-confounds Phase 2 |
| 3 | `ib_write_lat` / `ib_write_bw` over RoCE | ~1 hr | gap #1 — the real metric |
| 4 | Enable MTU 9000 both ends, re-measure | minutes | free throughput + latency |
| 5 | 2-node llama.cpp RPC over existing 10GbE | ~1 day | gap #3 — validates software before hardware spend |
| 6 | USB4 `thunderbolt_net` link test | 1 cable | gap #6 — possibly bypasses OCuLink entirely |
| 7 | E810 install → read `current_link_speed` **first** | on arrival | go/no-go on the whole plan |

Items 3, 5, and 6 are all runnable before the E810 arrives and are more informative than
any further iperf3 tuning.
