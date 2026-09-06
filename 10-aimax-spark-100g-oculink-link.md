# 10 — aimax ↔ Spark 100G over OCuLink: 22.3 Gb/s ceiling and a fatal PCIe drop (2026-09-06)

> **Superseded (2026-09-06).** Both headline conclusions below are out of date. The fatal
> PCIe drop was ASPM and is fixed by `pcie_aspm=off pci=realloc`; the 22.3 Gb/s ceiling rose
> to 28.0 Gb/s. Thermal and dock power were both disproved, so the fan test queued here is
> unnecessary. See [report 11](11-oculink-lane-resolved.md). Retained for the forensics.


Scope: first characterization of a **new lane** — an x86 workstation (`aimax`, AMD Ryzen AI
MAX+ 395 / Strix Halo) attached to `edgexpert-9105` by a ConnectX-5 100GbE NIC housed in an
external OCuLink dock. Unlike reports 01–09 this is not a model benchmark; it is a link
bring-up and bandwidth characterization, plus the forensics of a hard NIC failure that
ended the run.

Two results: the link's usable ceiling is **~22 Gb/s, not 100**, set by the PCIe path rather
than the wire; and the NIC **fell off the PCIe bus under sustained load** and did not
recover without a power cycle.

## Topology as built

```
aimax  M.2 slot (root port 00:02.5, Gen4 x4 capable)
   └─ M.2 → OCuLink adapter
       └─ OCuLink cable
           └─ AOOSTAR AG01 dock
               └─ ConnectX-5 MCX515A-CCAT   enp196s0np0   192.168.100.1/24
                    │  QSFP28 DAC, negotiated 100 Gb/s
                    ▼
edgexpert-9105 (GB10)  ConnectX-7  enp1s0f1np1  0000:01:00.1  192.168.100.2/24
```

The Spark exposes four mlx5 ports across two ConnectX-7 controllers. Ours was identified by
ARP (`192.168.100.2 lladdr fc:9d:05:13:91:07`), **not** by assumption — a passive tcpdump for
our MAC matched *two* ports, so the capture alone was not conclusive. The other three ports
(`10.10.10.1/24`, `10.10.20.1/24`, `10.100.0.2/24`) are separate fabric and were left untouched.

## Bandwidth

| Test | Throughput | Retransmits |
|---|---|:---:|
| 1 stream | 19.5 Gb/s | 0 |
| 4 streams | **22.3 Gb/s** | 2 |
| 8 streams | **fatal — link dead at t≈8 s** | — |

RTT 0.59 ms, MTU 1500 both ends, link speed 100000 Mb/s.

**22.3 Gb/s is the usable number.** Jumbo frames were never enabled (both ends at 1500), so
this is the un-tuned figure; MTU 9000 would plausibly reach ~25–26 Gb/s but was not measured.

### Why not 100

The kernel states the budget explicitly at enumeration:

```
pci 0000:c4:00.0: 31.504 Gb/s available PCIe bandwidth, limited by 8.0 GT/s PCIe x4 link
                  at 0000:00:02.5 (capable of 126.016 Gb/s with 8.0 GT/s PCIe x16 link)
```

Two independent caps compound:

- **x4, not x16** — inherent to the path. M.2 M-key carries PCIe x4; OCuLink (SFF-8611)
  carries x4. The card is a x16 part, but the chain cannot present more than four lanes.
  There is no wider slot on this board to move to: root port `00:02.5` is the widest
  expansion port, and the x16 ports (`00:08.1/.2/.3`) are internal (iGPU, audio, USB4).
- **Gen3, not Gen4** — the root port is 16 GT/s capable, but MCX515A-CCAT is a PCIe 3.0
  part, so it trains at 8 GT/s.

PCIe 3.0 x4 = 31.5 Gb/s raw. Measured 22.3 Gb/s is **~71% of raw**, normal TLP efficiency at
1500-byte MTU. The 100GbE wire rate was never the constraint and is cosmetic on this platform.

A Gen4 NIC (e.g. ConnectX-6 Dx) in the same chain would train x4 at 16 GT/s ≈ 63 Gb/s raw —
roughly double. Caveat: OCuLink at Gen4 is materially more marginal than at Gen3, so that
upgrade may trade throughput for stability.

## The failure

At 19:21:57, eight seconds into the 8-stream run, the card stopped answering:

```
mlx5_core 0000:c4:00.0: poll_health:803: Fatal error 1 detected
mlx5_core 0000:c4:00.0: print_health_info:432: PCI slot is unavailable
mlx5_core 0000:c4:00.0: mlx5_error_sw_reset:236: start
mlx5_core 0000:c4:00.0: NIC IFC still 7 after 2000ms.
mlx5_core 0000:c4:00.0: mlx5_health_try_recover:343: health recovery flow aborted,
                        PCI reads still not working
```

iperf3 recorded the same moment from the other side:

```
[SUM]   8.00-9.00   sec  0.00 Bytes  0.00 Gbits/sec
[SUM]   9.00-10.00  sec  0.00 Bytes  0.00 Gbits/sec
```

Post-mortem, the endpoint reads all-ones — `rev ff`, class `ffff` — and its BARs are gone:

```
c4:00.0 Unassigned class [ffff]: Mellanox Technologies MT27800 Family [ConnectX-5] (rev ff)
mlx5_core 0000:c4:00.0: Missing registers BAR, aborting
mlx5_core 0000:c4:00.0: probe_one:2005: mlx5_pci_init failed with error code -19
```

PCI remove + rescan and a full `mlx5_core` module reload both failed. The device was still
down at end of session; it requires a cold power cycle (mains removed), not a warm reboot.

### Diagnostic limitation

```
acpi PNP0A08:00: _OSC: platform does not support [SHPCHotplug AER LTR DPC]
```

**AER is unavailable on this platform**, so there are no PCIe correctable/uncorrectable error
counters. The evidence that would normally discriminate a signal-integrity failure from a
power or thermal one does not exist here. The failure window contains only mlx5's own health
poller — no `pcieport` link-down, no bus error. Everything below is therefore inference, not
proof.

### Component elimination

| Component | Verdict | Basis |
|---|---|---|
| DGX Spark | **ruled out** | Not in the PCIe path; a remote Ethernet peer cannot make a local endpoint's config space read all-Fs. Its ports stayed up. |
| QSFP cable | **ruled out** | Same. It also carried 22.3 Gb/s with 2 retransmits total — a clean cable. Failure signature is PCIe-side. |
| M.2 slot | unlikely | Enumerated at full x4 Gen3, stable 42 min; both NVMes (Gen4 x2, other root ports) show zero errors. |
| OCuLink cable + adapter | possible | But the link trained *optimally* (x4 Gen3 — the chain's ceiling) and never retrained or downgraded. Marginal cabling usually trains down. |
| AOOSTAR AG01 dock | likely | Slot power delivery under load transient. |
| ConnectX-5 | **most likely** | Thermal — see below. |

The failure is load-correlated (idle 42 min fine → 1 stream fine → 4 streams fine → 8 streams
dead in 8 s) and clears only on power removal. That is a *latched* fault, pointing at the two
quantities that scale with load: heat and current draw.

A ConnectX-5 100G is a datacenter part expecting ~200–300 LFM of forced airflow and
dissipating ~15–20 W under load. The AG01 is an open eGPU dock built for cards that bring
their own fans; the NIC has no directed airflow. Against this: mlx5 logged **no** temperature
warning before the fault, which weakens the thermal case — though the register path may
already have been dead by then.

## Next steps (untested)

1. **Fan test.** Aim a fan at the heatsink, repeat the identical 8-stream run. Survives with
   airflow and dies without → thermal, conclusive and nearly free.
2. **Instrument temperature.** `mstflint` → `mget_temp_ext -d 0000:c4:00.0` sampled during
   load. Must be installed *before* the next stress run.
3. **Swap the card in the dock.** Another PCIe card dying under load in the same AG01
   implicates dock/cable/adapter; surviving implicates the NIC.
4. **Swap the NIC into a real slot** on another host. Definitive but highest effort.
5. Enable jumbo (MTU 9000) on both ends once stable, and re-measure.

Until root cause is settled, **treat this lane as unreliable for sustained transfers**
regardless of the 22.3 Gb/s figure, and cap `iperf3` at `-P 4`.

## Config note

The working config (`192.168.100.1/24` on `enp196s0np0`) was in-memory only at end of
session; NetworkManager persists profiles to `/etc/netplan/90-NM-<uuid>.yaml` on this host
and no file existed for it. A stale profile carrying a colliding `10.10.10.1/30` — the same
address as the Spark's `enp1s0f0np0` — remains on disk with `autoconnect yes` and must be
deleted before the link is brought up again.

## Raw data

`raw/net-aimax-spark-100g/` — `link-endpoints.txt`, `pcie-topology.txt`,
`iperf3-1stream.txt`, `iperf3-4stream-and-8stream-crash.txt`, `dmesg-mlx5-full.txt`,
`post-mortem-pci.txt`.

## Hardware

- **aimax** — AMD Ryzen AI MAX+ 395 w/ Radeon 8060S (Strix Halo), 32 threads, 124 GiB RAM,
  Linux 7.0.0-31-generic. Mellanox ConnectX-5 MCX515A-CCAT, fw 16.35.4030, `mlx5_core`.
- **edgexpert-9105** — NVIDIA DGX Spark (GB10), ConnectX-7, 4 mlx5 ports.
- Link: QSFP28 DAC, 100 Gb/s negotiated, MTU 1500, `192.168.100.0/24`.

## Date

2026-09-06
