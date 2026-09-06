# Post-reboot checklist — aimax OCuLink lane

Run in order. Each gate must pass before the next.
Prerequisite: `add-kernel-params.sh` ran **before** shutdown, dock powered on
**before** the PC booted (root port `00:02.5` has no hotplug).

## Gate 1 — did the boot take? (2 min)

```bash
bash 01-verify-boot.sh
```

Checks the three kernel params landed, the NIC enumerated as an Ethernet controller
(not `rev ff`), and the PCIe link is 8.0 GT/s x4. **Stop if this fails.**

## Gate 2 — restore the link (3 min)

```bash
bash 02-restore-link.sh
# then on the Spark:
sudo ip link set enp1s0f1np1 mtu 9000
```

Deletes the stale `qsfp-spark` profile still holding the colliding `10.10.10.1/30`,
persists `192.168.100.1/24` at MTU 9000, verifies the jumbo path.

## Gate 3 — RDMA latency (10 min) ← the decisive measurement

```bash
sudo apt install -y perftest ibverbs-utils mstflint     # both nodes
bash 03-rdma-test.sh
```

Latency is the number that matters, not bandwidth. TP is ~120–160 all-reduce
round-trips per token, so microseconds here scale by ~150×.

| Result | Meaning |
|---|---|
| 2–10 µs | healthy — TP viable, proceed to node 2 |
| 10–20 µs | degraded — investigate |
| >50 µs | broken — probably not using RDMA at all |

Reference: kyuz0 measured **5.23 µs / 50.64 Gb/s** on E810 Gen4 x4.
Our CX-5 is Gen3, so expect **~22 Gb/s** — bandwidth is *not* the test here.

## Gate 4 — the stability hypothesis (10 min)

```bash
bash 04-stress-test.sh
```

Re-runs the exact 1→4→8 stream ramp that killed the card, now with
`pcie_aspm=off` and `pci=realloc`. Install `mstflint` first or you get no
temperature data.

- **Survives** → the kernel params fixed it; OCuLink chain is sound.
- **Dies again** → ASPM/BAR disproved. Next: fan on the card to separate
  thermal from AG01 slot power.

## Then, in the background (1–3 h, mostly downloads)

Pull the kyuz0 toolbox and run vLLM **TP=1** on this node alone — no NIC needed,
no second node. Gives a decode baseline to compare against the Spark reports and
proves the stack works on gfx1151 before node 2 arrives.

Note: upstream ROCm lacks gfx1151 RCCL support — the toolbox bundles a custom
`librccl.so`. Do not try to build from stock ROCm.

## Reference

- Lane details: [report 10](../../10-aimax-spark-100g-oculink-link.md)
- Programme: [plan](../../PLAN-ryzen-ai-max-cluster.md)
- Upstream: https://github.com/kyuz0/amd-strix-halo-vllm-toolboxes
