# 11 — OCuLink lane resolved: ASPM was the fault, 1.34 µs RDMA, TP is viable (2026-09-06)

Scope: follow-up to [report 10](10-aimax-spark-100g-oculink-link.md), which characterized the
`aimax` ↔ `edgexpert-9105` OCuLink lane at a 22.3 Gb/s ceiling and ended with the ConnectX-5
falling off the PCIe bus under load. This report closes that out. **Report 10's two headline
conclusions are both superseded.**

Three results: the fatal PCIe drop was caused by **ASPM**, not heat or dock power, and is
fixed by kernel parameters; usable bandwidth rose to **28.0 Gb/s**; and RDMA write latency is
**1.34 µs**, which makes tensor parallelism viable on this lane.

## The fix

```
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash iommu=pt pci=realloc pcie_aspm=off"
```

Persisted in `/etc/default/grub`, so it survives reboots and kernel updates. The dock must
still be powered **before** the host boots — root port `00:02.5` has no hotplug.

## Results

| Measurement | Report 10 | Now | Note |
|---|---|---|---|
| 1 stream | 19.5 Gb/s | 27.3 Gb/s | |
| 4 streams | 22.3 Gb/s | 27.9 Gb/s | |
| 8 streams | **fatal at t≈8 s** | **27.9 Gb/s, survived** | the hypothesis test |
| RDMA write bandwidth | not measured | 28.03 Gb/s | 89% of the 31.5 Gb/s Gen3 x4 ceiling |
| RDMA write latency | not measured | **1.34 µs typical** | min 1.31, 99% 1.70, 99.9% 15.86 |

MTU is now 9000 both ends. Report 10 predicted jumbo frames would plausibly reach ~25–26 Gb/s;
the actual figure is 28.0, so that estimate was slightly conservative. At 89% of the ceiling
the kernel itself reports (`31.504 Gb/s available PCIe bandwidth, limited by 8.0 GT/s PCIe x4
link at 0000:00:02.5`), there is little left to win on this card.

## Two hypotheses disproved in the same run

Report 10 left thermal and AG01 slot power as live suspects, with a fan test queued to
separate them. Both are now ruled out, and **the fan test is unnecessary**:

- **Thermal.** NIC temperature was sampled every 2 s across the full 1→4→8 ramp. It sat at
  **70–71 °C from idle through 20 s of 8-stream load** — 11 samples at 70, 19 at 71, against a
  105 °C critical. Full load added essentially nothing. The card idles warm in the dock, but
  it does not *heat up* under traffic, because a 100G part pushing 28 Gb/s is barely working.
- **Slot power.** The kernel reports `mlx5_pcie_event: PCIe slot advertised sufficient power
  (75W)`.

Post-run the journal is clean — no AER, no mlx5 errors, link still 8.0 GT/s x4, port ACTIVE.

## Why 1.34 µs is the number that matters

Tensor parallelism costs roughly 120–160 all-reduce round trips per token, so link latency
multiplies by ~150:

| Transport | Latency | ×150 round trips | Network-bound ceiling |
|---|---|---|---|
| TCP (the original PoC) | 590 µs | 88.5 ms/token | ~11 tok/s — unusable |
| RoCEv2 here | **1.34 µs** | 0.20 ms/token | ~4,900 tok/s — not the bottleneck |

For reference kyuz0 measured 5.23 µs on E810 Gen4 x4; this lane is ~4× better on latency
despite being the slower card on bandwidth. **Decision: TP is viable. Build node 2.**

## Method notes

- **RoCEv2 GID is index 3 on both ends** (`mlx5_0` here, `rocep1s0f1` there) — the
  `...ffff:c0a8:6401` / `...ffff:c0a8:6402` entries. The earlier index-3-vs-5 ambiguity was
  unfounded; only four GIDs exist per port.
- **Do not use `mget_temp_ext` for NIC temperature.** It ships only in NVIDIA's proprietary
  MFT bundle and is absent from Ubuntu's `mstflint` package, which provides `mstmget_temp`
  instead. The better source needs no sudo at all: the kernel's mlx5 hwmon sensor, at
  `/sys/class/hwmon/hwmon*/temp1_input` where `name` reads `mlx5`.
- The peer is `edgexpert-9105`, a GB10 aarch64 box on kernel 6.17. Its lane interface is
  `enp1s0f1np1`. Note `edgexpert-1d49` presents an **identical SSH host key** — the two were
  imaged from the same snapshot, so `known_hosts` cannot distinguish them.

## Open

- ICMP RTT on the lane is ~0.95 ms, high for a direct link. This is CPU power management, not
  fabric — `acpi_idle` rather than `amd_pstate`, `powersave` governor. It does not affect RDMA,
  which busy-polls, so it is cosmetic for TP. Worth checking why `amd_pstate` is inactive.
- The E810-CQDA1 swap (see the plan) is now a **pure bandwidth play** — its root-cause
  isolation role is moot. It buys Gen4 (~50 Gb/s), not latency; latency is already excellent.

## Reproducing

Gated scripts in `scripts/ryzen-lane/`. Gate 4 reads temperature from hwmon and auto-starts
the peer's `iperf3` over SSH, so it runs unattended. Gate 3 (`03-rdma-test.sh`) is still
interactive by design and assumes a human on both ends.
