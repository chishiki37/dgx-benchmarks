# Post-reboot checklist — aimax OCuLink lane

> **All four gates passed on 2026-09-06.** Results are written up in
> [report 11](../../11-oculink-lane-resolved.md): the fatal PCIe drop was **ASPM**, fixed by
> `pcie_aspm=off pci=realloc`; bandwidth rose 22.3 → **28.0 Gb/s**; RDMA latency is
> **1.34 µs**, so **TP is viable**. Thermal and dock power were both disproved — **the fan
> test below is no longer needed.** This file is retained as the reproduction procedure.

Run in order. Each gate must pass before the next.
Prerequisite: the kernel params are now persisted in `/etc/default/grub`, but the dock must
still be powered on **before** the PC boots — root port `00:02.5` has no hotplug.

## Gate 1 — did the boot take? (2 min)

```bash
bash 01-verify-boot.sh
```

Checks the three kernel params landed, the NIC enumerated as an Ethernet controller
(not `rev ff`), and the PCIe link is 8.0 GT/s x4. **Stop if this fails.**

## Gate 2 — restore the link (3 min)

```bash
bash 02-restore-link.sh
```

Deletes any stale `qsfp-spark` profile holding the colliding `10.10.10.1/30`, persists
`192.168.100.1/24` at MTU 9000, verifies the jumbo path. The peer is already at MTU 9000
and holds `192.168.100.2` persistently, so no action is needed on that side.

## Gate 3 — RDMA latency (10 min) ← the decisive measurement

```bash
sudo apt install -y perftest ibverbs-utils     # both nodes
bash 03b-spark-prep.sh                          # on the peer: discovery + servers
bash 03-rdma-test.sh                            # here
```

Latency is the number that matters, not bandwidth. TP is ~120–160 all-reduce
round-trips per token, so microseconds here scale by ~150×.

| Result | Meaning |
|---|---|
| 2–10 µs | healthy — TP viable, proceed to node 2 |
| 10–20 µs | degraded — investigate |
| >50 µs | broken — probably not using RDMA at all |

**Measured: 1.34 µs typical, 28.03 Gb/s.** RoCEv2 GID is **index 3 on both ends**
(`mlx5_0` here, `rocep1s0f1` on the peer). kyuz0's E810 Gen4 reference was 5.23 µs.

Note `03-rdma-test.sh` is interactive by design and assumes a human on both ends; the peer
servers can instead be driven over SSH, which is what `03b-spark-prep.sh` sets up.

## Gate 4 — the stability hypothesis (10 min)

```bash
bash 04-stress-test.sh
```

Re-runs the exact 1→4→8 stream ramp that killed the card, now with `pcie_aspm=off` and
`pci=realloc`. Auto-starts the peer's `iperf3 -s` over SSH and samples NIC temperature
throughout, so it runs unattended.

- **Survives** → the kernel params fixed it. *(This is what happened.)*
- **Dies again** → ASPM/BAR disproved; read the temperature series to tell thermal from
  slot power.

**Temperature comes from the kernel's mlx5 hwmon sensor**
(`/sys/class/hwmon/hwmon*/temp1_input` where `name` is `mlx5`) — no sudo required.
Do **not** use `mget_temp_ext`: it ships only in NVIDIA's proprietary MFT bundle and is
**absent from Ubuntu's `mstflint` package**, which provides `mstmget_temp` instead. The
original version of Gate 4 called it and silently produced no temperature data.

Result: flat **70–71 °C** from idle through 20 s of 8-stream load, against a 105 °C
critical — which is what disproved the thermal branch.

## Then, in the background (1–3 h, mostly downloads)

Pull the toolbox and run vLLM **TP=1** on this node alone — no NIC needed, no second node.
Gives a decode baseline to compare against the Spark reports and proves the stack works on
gfx1151 before node 2 arrives.

```bash
podman pull docker.io/kyuz0/vllm-therock-gfx1151:latest
```

Requires membership in the `render` and `video` groups (`sudo usermod -aG render,video $USER`,
then a new login) — `/dev/kfd` and `/dev/dri/renderD128` are otherwise unreadable. With
rootless podman use `--group-add keep-groups`, **not** `--group-add video --group-add render`.

Note: upstream ROCm lacks gfx1151 RCCL support — the toolbox bundles a custom
`librccl.so`. Do not try to build from stock ROCm.

## Reference

- Results: [report 11](../../11-oculink-lane-resolved.md)
- Original characterization: [report 10](../../10-aimax-spark-100g-oculink-link.md) *(superseded)*
- Programme: [plan](../../PLAN-ryzen-ai-max-cluster.md)
- Upstream: https://github.com/kyuz0/amd-strix-halo-vllm-toolboxes
