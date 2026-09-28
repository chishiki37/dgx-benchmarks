# 13 — First TP2: DeepSeek V4.1 Flash Q2 on aimax ↔ aimax-2 (2026-09-27/28)

Scope: first **tensor-parallel** serve on the two-node Strix Halo pair from
[report 12](12-aimax-aimax2-100g-direct.md). Engine is DwarfStar (`ds4`) ROCm
`gfx1151`, kyuz0 toolbox `ds4.1f-rocm10.0` (PR
[antirez/ds4#1036](https://github.com/antirez/ds4/pull/1036)), weights
`antirez/deepseek-v4.1-flash-gguf` **Q2** (365,713,686,528 bytes). This is not
a Spark vLLM/SGLang recipe and it is not llama.cpp Vulkan.

Two results: **TCP TP2 and RoCE TP2 both produce coherent greedy output.** A
512-token C1 probe then **took aimax-2 offline** mid-decode; that is a fabric /
peer-host failure, not a PCIe drop on aimax (unlike report 10). No battery, no
median tok/s pin, no quality set. DSpark is unsupported in this TP mode.

## PoC bill of materials

As built for this pair. Dock↔host assignment (AG01 vs DEG1) was not recorded.

- 2× TOPC Ryzen AI MAX+ 395 (128 GB) — [Alibaba](https://www.alibaba.com/x/18rVhO?ck=pdp)
- 2× Mellanox **MCX515A-CCAT** (ConnectX-5, 100 GbE) — [Alibaba](https://www.alibaba.com/x/18rVhh?ck=pdp)
- 1× MINISFORUM **DEG1** eGPU dock — [Lazada](https://s.lazada.co.th/s.ZQ5BUC?c=s)
- 1× AOOSTAR **AG01** eGPU dock — [Lazada](https://s.lazada.co.th/s.ZQ5z0L?c=s)
- 1× Thermaltake **TR2 S 550W** (dock PSU) — [JIB](https://www.jib.co.th/web/product/readProduct/84507/185/POWER-SUPPLY--%E0%B8%AD%E0%B8%B8%E0%B8%9B%E0%B8%81%E0%B8%A3%E0%B8%93%E0%B9%8C%E0%B8%88%E0%B9%88%E0%B8%B2%E0%B8%A2%E0%B9%84%E0%B8%9F--THERMALTAKE-TR2-S-550W---550W-80-PLUS-ATX-BLACK-TRS-0550NNSAWE-H)
- 2 m NADDOD Cisco **QSFP-100G-CU2M** compatible QSFP28 DAC — [naddod.com](https://www.naddod.com/products/32257.html)
- Per host: M.2 → TKM8 → OCuLink into the dock; CX-5 in the dock

**Next phase (not installed):** 2× Intel **E810-CQDA1** (eBay listing
[398243791858](https://www.ebay.com/itm/398243791858)) — Gen4 play for the
~50 Gb/s target in the [cluster plan](PLAN-ryzen-ai-max-cluster.md). CX-5 is
PCIe 3.0; this path is Gen3 ×4 regardless of a 100 GbE cable.

## Topology

```
aimax     M.2 → TKM8 → OCuLink → dock → CX-5  enp196s0np0  mlx5_0
          192.168.100.1/24  MTU 9000  GTT 120 GiB
                │  QSFP28 DAC, 100 GbE, PCIe 3.0 ×4 host path
                ▼
aimax-2   M.2 → TKM8 → OCuLink → dock → CX-5  enp196s0np0  rocep196s0
          192.168.100.2/24  MTU 9000  GTT 120 GiB
```

Link vet (report 12): iperf3 `-P 4 -t 20` aimax→aimax-2 **28.0 Gb/s**. Reverse
not recorded. Treat as the Gen3 ×4 ceiling, not a 100 GbE miss.

## Bring-up (what actually blocked)

1. **GPU on aimax-2.** User was not in `render`/`video`; `/dev/kfd` EACCES.
   Podman missing. Fixed with `usermod -aG render,video` + `apt install podman
   rdma-core …`. New SSH session required.
2. **GTT on aimax-2.** BIOS UMA already 512 MB (`vram_total` 0.500 GiB) but
   `gtt_total` was **61.34 GiB**. ds4 refused: “V4.1 needs 84.67 GiB … safe ROCm
   budget 61.34 GiB.” Same GRUB drop-in as aimax (`amdgpu.gttsize=122880
   ttm.pages_limit=31457280`) + kdump crashkernel disabled. After reboot:
   GTT **120 GiB**, MemTotal **~125 GiB**.
3. **Weights.** `DeepSeek-V4.1-Flash-Q2.gguf` on both hosts (rsync over 100G
   ~1.1 GB/s, 5 min). Engram stays disk-backed; each rank maps **80.56 GiB**
   resident experts.
4. **RoCE memlock.** Default 8 MiB. `ibv_reg_mr` → `RoCE setup … Cannot allocate
   memory`. Need `DefaultLimitMEMLOCK=infinity` and a coordinator launched
   outside the 8 MiB Hermes session (`sudo bash ~/start-ds4-coord-roce.sh`).
5. **GID indexes are reboot-volatile.** Do not hard-pin `3` forever. After the
   aimax-2 power cycle, aimax IPv4 RoCEv2 was **GID 4** (GID 3 all zeros);
   aimax-2 stayed **GID 3**. Log line `RoCE: selected GID is zero` means the
   pinned index went empty — re-read
   `/sys/class/infiniband/*/ports/1/gids/*` on **that boot**.

## What ran

Coordinator (aimax), worker (aimax-2), ctx 16384, `--batched-session 1`,
`--transport tcp` then `--transport rdma`:

```
# coordinator (GID is host- and boot-specific)
ds4-server --rocm -m DeepSeek-V4.1-Flash-Q2.gguf --ctx 16384 \
  --tensor-parallel --role coordinator --listen 192.168.100.1 9911 \
  --transport rdma --rdma-device mlx5_0 --rdma-port 1 --rdma-gid-index 4 \
  --batched-session 1 --host 127.0.0.1 --port 8080

# worker
ds4 --rocm -m DeepSeek-V4.1-Flash-Q2.gguf --ctx 16384 \
  --tensor-parallel --role worker --coordinator 192.168.100.1 9911 \
  --transport rdma --rdma-device rocep196s0 --rdma-port 1 --rdma-gid-index 3
```

Toolbox image: `docker.io/kyuz0/strix-halo-ds4-toolbox:ds4.1f-rocm10.0`.
API only on the coordinator (`127.0.0.1:8080`). Cluster SSD streaming, DSpark,
and `--layers` PP are **not** supported on this TP path.

RoCE bind (successful boot): `RoCE RC … window=4 chunk=2097152 host-staging=16MiB`,
`transport=rdma`, 50/50 expert split.

## Measured (and not measured)

Greedy `thinking=false`, `Say hello.` — TCP and RoCE both returned
`Hello! 👋 How can I help you today?` (7 prompt + 11 completion tokens).
Link stayed UP on the short prompt.

A Spark-style C1 probe (transistor essay, 512 tok, temp 0) on RoCE:

- Server log warmup decode **~17.7 tok/s** (not a median, not a pin).
- First measured run died at **position 508**:
  `ds4-tp: socket I/O failed … Connection timed out` /
  `V4.1 decode failed at position 508`.
- Same second: `mlx5_core … Link down` on aimax. **No AER, no `poll_health`,
  no `rev ff`.** `enp196s0np0` went `NO-CARRIER`. aimax-2 Tailscale went
  offline. This is the **peer vanishing**, not report 10’s ASPM/PCIe death
  on the coordinator NIC (card stayed enumerated).
- Hard power-cycle of aimax-2 restored 100G ping. Coordinator CX-5 did not
  need a power cycle.

No C1/C4/C8 battery. No GSM8K/HumanEval. Do not cite kyuz0’s published
~16–17 tok/s RoCE table as this pair’s number.

ds4 also logs `iogpu.wired_limit_mb is 0` (lazy expert paging). Not swept.

## Open

- Autoresearch sweep (batched-session, prefill-chunk, wired_limit) queued in
  `~/src/aimax-ds41-tp2/` — blocked until long decode is stable on RoCE.
- Why aimax-2 died under ~28 s of RoCE TP decode: no peer dmesg yet.
- E810-CQDA1 swap: first measurement is `lspci` LnkSta (need Gen4 ×4), not iperf.
- Reverse iperf still unrecorded.
