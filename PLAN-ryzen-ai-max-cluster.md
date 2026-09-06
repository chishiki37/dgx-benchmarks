# PLAN — Distributed inference on Ryzen AI MAX+ 395 (Strix Halo)

Status: **Phase 1 (single-link PoC) complete; lane fault resolved.** Written 2026-09-06,
updated 2026-09-06 after the post-reboot gates — see [report 11](11-oculink-lane-resolved.md).
The CX-5's fatal PCIe drop was **ASPM** and is fixed; the lane now runs **28.0 Gb/s at
1.34 µs RDMA latency**, and **TP is confirmed viable**.

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

Initial result: **22.3 Gb/s** (4 streams), MTU 1500, ending with the NIC dropping off the
PCIe bus under 8-stream load — [report 10](10-aimax-spark-100g-oculink-link.md).

**After the fix** ([report 11](11-oculink-lane-resolved.md)): the drop was **ASPM**, cured by
`pcie_aspm=off pci=realloc`. With MTU 9000 the lane now runs **28.0 Gb/s** (89% of the
31.5 Gb/s Gen3 x4 ceiling) and, far more importantly, **1.34 µs RDMA write latency**.

**Verdict: concept proven, and the metric that matters is excellent.** 28.0 Gb/s is 2.8× the
10GbE baseline but still not 50 Gb/s, and cannot become 50 Gb/s with this NIC — see the math
below. That no longer governs the decision: at 1.34 µs the *latency* budget for tensor
parallelism is comfortable, and latency is the binding constraint (gap #1). The lane is
stable under the full 1→8 stream ramp that previously killed it.

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

- **Bandwidth:** does Gen4 x4 materialize, and does it clear 50 Gb/s? This is now the
  **only** reason to do the swap.
- ~~Root cause: the card-swap arm of the ConnectX-5 failure isolation.~~ **No longer needed.**
  The root cause is known: ASPM. The CX-5 survives the full ramp with the kernel params in
  place, and both thermal and slot power were disproved directly (flat 70–71 °C under load;
  the kernel reports the slot advertising 75 W). **The fan test is unnecessary** and the
  comparison is no longer confounded.

Keep `pcie_aspm=off pci=realloc` on the cmdline for the E810 too. Untested with `ice`, but
they are what made this dock path stable, and there is no reason to think the root port
behaves differently with a different card.

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

## 1. iperf3 TCP bandwidth is the wrong metric — RESOLVED: 1.34 µs measured

The PoC measured TCP throughput. Distributed inference does not run on TCP throughput;
it runs on **collective operations**, and for tensor parallelism the binding constraint
is **latency, not bandwidth**.

Rough shape of the problem for TP: each transformer layer requires ~2 all-reduces per
token. A 60–80 layer model is therefore 120–160 synchronization round-trips **per token**.

| Transport | Round-trip | 160 RTs/token | Implied ceiling |
|---|---|---|---|
| TCP/IP (measured PoC) | ~590 µs | ~94 ms | **~10 tok/s** |
| **RoCEv2 RDMA (measured 2026-09-06)** | **1.34 µs** | **0.21 ms** | **~4,700 tok/s** |

**A 50 Gb/s TCP link would still be unusable for tensor parallelism.** The Spark fleet
does not run TCP — it runs NCCL over RoCEv2, which is why it works.

**This gap is now closed.** RoCEv2 was measured end to end at **1.34 µs typical**
(min 1.31, 99% 1.70) — better than the 2–5 µs this section assumed, and ~4× better than
kyuz0's 5.23 µs on E810 Gen4. Network overhead is ~0.21 ms/token, so the interconnect is
**not** the bottleneck for TP on this lane. Bandwidth came in at 28.03 Gb/s.

```bash
# perftest (RoCE) - the numbers that actually matter
ib_write_bw  -d <rdma_dev> -x <gid> -F   # bandwidth
ib_write_lat -d <rdma_dev> -x <gid> -F   # latency  <- the critical one
```

RoCEv2 GID is **index 3 on both ends** (`mlx5_0` here, `rocep1s0f1` on the peer). Full
method and numbers in [report 11](11-oculink-lane-resolved.md).

## 2. Parallelism strategy — RESOLVED: tensor parallel

Settled 2026-09-06 from prior PoCs: **pipeline parallel is materially slower than tensor
parallel for these workloads, and TP wins even at 50 Gb/s.** PP is therefore not a fallback
and the low-bandwidth escape hatch is closed.

Consequences, which now bind the rest of the plan:

- **RDMA is mandatory.** TP is ~120-160 all-reduce round-trips per token; the PoC's 590 us
  TCP RTT implies a ~10 tok/s ceiling. Thunderbolt/USB4 is disqualified outright — it is a
  netdev driver with no verbs path, and caps at 40 Gb/s signaling regardless.
- **The 50 Gb/s target is real** and the Gen4 NIC is on the critical path.
- **Prefill, not decode, is the bandwidth risk.** TP all-reduce volume during decode is
  small (~1 Gb/s at realistic token rates), but prefill scales with sequence length. At the
  1M-context shapes this fleet targets, 50 Gb/s is ~4x less fabric than the Spark
  reference's 200G, and TTFT will carry that. Worth computing for the specific model
  before assuming the target is sufficient.

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

Tempered by report 11: the failure turned out to be **ASPM, a link power-management
setting**, not signal integrity or slot power — both of which were disproved. A kernel
parameter fixed it. The chain is more trustworthy than it looked, so this is now a
preference rather than a correction.

If a second node is being purchased anyway, buying one with a real slot rather than
replicating the OCuLink stack is worth costing out. It would also make the two nodes
non-identical, which is itself a useful A/B on whether the dock is the problem.

## 8. Heterogeneous clustering with the Sparks is not viable

Worth stating explicitly to avoid a dead end: Ryzen (x86 + ROCm + RCCL) and Spark
(aarch64 + CUDA + NCCL) cannot be joined into one inference cluster. NCCL and RCCL do not
interoperate. The Ryzen build must be a **separate cluster**, not an extension of the
existing eight nodes.

## 9. Operational items carried over from the PoC

- ~~MTU 9000 was never enabled~~ — **DONE.** Both ends at 9000, jumbo path verified end to
  end, persisted in the `qsfp-sparklink` NetworkManager profile.
- **AER is disabled on this platform** (`_OSC`), so PCIe errors are invisible. Any future
  bus-level fault will be as hard to diagnose as this one was — which is why this one was
  solved by hypothesis elimination rather than error counters.
- **The kernel params are load-bearing.** `iommu=pt pci=realloc pcie_aspm=off` are persisted
  in `/etc/default/grub`. Losing them very likely brings the fatal drop back.
- **Thermals are unmanaged but measured, and are not a problem.** The CX-5 idles warm at
  ~70 °C in the open dock, but stays **flat at 70–71 °C through 20 s of 8-stream load**
  against a 105 °C critical — a 100G part pushing 28 Gb/s is barely working. Read temperature
  from the kernel's mlx5 hwmon sensor (`/sys/class/hwmon/hwmon*/temp1_input` where `name` is
  `mlx5`); **`mget_temp_ext` does not exist** in Ubuntu's `mstflint` package, only in NVIDIA's
  proprietary MFT. Re-check if a hotter card (the E810) goes in.

---

# Open questions

1. **AG01 or AG01?** This document says AG01 per the latest description;
   [report 10](10-aimax-spark-100g-oculink-link.md) says AG01. One is wrong and should be
   corrected.
2. **CRS812 lossless-RoCE capability.** Confirmed: the CRS812 is the QSFP switch
   connecting all 8 Sparks — it *is* the RoCE fabric, not management. Phase 4 therefore
   depends on how it handles lossless RoCEv2 for added Ryzen nodes: whether PFC/ECN is
   configured today, and whether the Sparks currently rely on it or on Resilient RoCE /
   DCQCN instead. Check the existing switch config before assuming a Ryzen node can just
   be plugged in. Also confirm a free QSFP28 port and that it will negotiate 100G to a
   host NIC rather than only Spark-to-Spark rates.
3. **Capacity or speed?** Determines TP vs PP, and therefore whether 50 Gb/s is the right
   target at all (gap #2).
4. **What is the per-node cost** of Ryzen + dock + adapter + cable + NIC versus one more
   Spark, given the Spark software stack already works?

# Immediate next actions

| # | Action | Cost | Unblocks |
|---|---|---|---|
| 1 | ~~Power-cycle `aimax`, run the gate scripts~~ | — | **DONE** — link restored, all 4 gates passed |
| 2 | ~~CX-5 fan test under 8-stream load~~ | — | **UNNECESSARY** — thermal disproved (flat 70–71 °C under load) |
| 3 | ~~`ib_write_lat` / `ib_write_bw` over RoCE~~ | — | **DONE** — 1.34 µs / 28.03 Gb/s; gap #1 closed, TP viable |
| 4 | ~~Enable MTU 9000 both ends, re-measure~~ | — | **DONE** — both ends at 9000, jumbo path verified |
| 5 | 2-node llama.cpp RPC over existing 10GbE | ~1 day | gap #3 — validates software before hardware spend |
| 6 | USB4 `thunderbolt_net` link test | 1 cable | gap #6 — possibly bypasses OCuLink entirely |
| 7 | E810 install → read `current_link_speed` **first** | on arrival | bandwidth only; its A/B role is moot now |

**Items 5 and 6 are the live ones.** Both are runnable before the E810 arrives and are more
informative than any further iperf3 tuning. Item 5 is the highest value on the board: Phase 3
means buying a second node plus dock, adapter, cable and NIC, and item 5 is what validates the
software stack before that spend. Gate 3 proved the *fabric*; it said nothing about whether
distributed inference actually works across two nodes.
