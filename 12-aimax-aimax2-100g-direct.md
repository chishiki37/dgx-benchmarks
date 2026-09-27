# 12 — aimax ↔ aimax-2 100G: two Strix Halo nodes over CX-5, 28.0 Gb/s (2026-09-27)

Scope: first characterization of **node 2** on the Ryzen AI MAX+ 395 track — a second TOPC
(`aimax-2`) linked to `aimax` by ConnectX-5 100GbE NICs in external OCuLink docks. Unlike
reports 10–11 this is not aimax ↔ Spark. The 192.168.100.0/24 P2P that used to terminate on
`edgexpert-9105` now terminates on `aimax-2`.

One result: the two-Strix-Halo path trains the same way the Spark lane did — **100 Gb/s
Ethernet on a PCIe 3.0 ×4 host path** — and delivers **28.0 Gb/s** TCP. That is the Gen3 ×4
ceiling already measured in report 11, not a new miss on the wire. Reverse-direction iperf
and RDMA on this pair have not been recorded.

## Topology as built

```
aimax     M.2 → TKM8 → OCuLink → dock (AG01 or DEG1) → CX-5 MCX515A-CCAT
                                                      enp196s0np0  0000:c4:00.0
                                                      192.168.100.1/24  MTU 9000
                                                           │  QSFP, 100 Gb/s
                                                           ▼
aimax-2   M.2 → TKM8 → OCuLink → dock (AG01 or DEG1) → CX-5 MCX515A-CCAT
                                                      enp196s0np0  0000:c4:00.0
                                                      192.168.100.2/24  MTU 9000
```

Both hosts are TOPC systems with AMD Ryzen AI MAX+ 395. The docks are one AOOSTAR AG01 and
one MINISFORUM DEG1; **which dock is on which host was not recorded.** Each dock holds a
Mellanox MCX515A-CCAT. The QSFP cable is direct — no switch.

Interface names matching (`enp196s0np0` on both) is coincidence of the same PCIe topology
(`0000:c4:00.0`), not a copy-paste error.

## Setup and validation

After seating the TKM8 adapters and booting both systems:

```
lspci -Dnn | grep -Ei 'mellanox|connectx|15b3'
ip -br link show dev enp196s0np0
sudo lspci -vv -s 0000:c4:00.0 | grep 'LnkSta:'
```

Both NICs were detected with `mlx5_core`, reported a 100 Gb/s Ethernet link, and negotiated
**PCIe 3.0 ×4**.

On `aimax-2`, a persistent NetworkManager profile was created to match aimax’s direct-link
network and MTU:

```
sudo nmcli connection add type ethernet \
  ifname enp196s0np0 \
  con-name aimax-direct-100g \
  ethernet.mtu 9000 \
  ipv4.method manual \
  ipv4.addresses 192.168.100.2/24 \
  ipv4.never-default yes \
  ipv6.method disabled

sudo nmcli connection up aimax-direct-100g
ping -I enp196s0np0 -c 4 192.168.100.1
```

Ping: 4 of 4 replies, 0% loss.

## Bandwidth

iperf3 server on aimax-2:

```
iperf3 -s -B 192.168.100.2 -p 5203
```

Client on aimax, four parallel streams, 20 seconds:

```
iperf3 -c 192.168.100.2 -B 192.168.100.1 -p 5203 -P 4 -t 20
```

| Test | Direction | Throughput | Transferred |
|---|---|---|---|
| 4 streams, 20 s | aimax → aimax-2 | **28.0 Gb/s** | 65.1 GB |
| reverse | aimax-2 → aimax | **not recorded** | — |

**28.0 Gb/s is the usable number.** It matches report 11’s 4-stream TCP on the Spark lane
(27.9 Gb/s) and is 89% of the 31.5 Gb/s raw Gen3 ×4 budget the kernel reports for this card
class. Jumbo frames were already on (MTU 9000). The 100 GbE wire rate is cosmetic on this
platform — same arithmetic as reports 10–11: M.2 M-key and OCuLink are ×4, MCX515A-CCAT is
PCIe 3.0, so the chain trains 8 GT/s ×4.

A Gen4 NIC (E810-CQDA1 / CQDA2) in the same chain remains the only path to the ~50 Gb/s
target, and only if OCuLink stays Gen4-clean. That swap is still a bandwidth play, not a
bring-up play.

## Addressing

| Address | Reports 10–11 | This report |
|---|---|---|
| 192.168.100.1 | aimax CX-5 | aimax CX-5 |
| 192.168.100.2 | Spark CX-7 `enp1s0f1np1` | **aimax-2** CX-5 `enp196s0np0` |

Do not mix the two peers. Spark’s 9105 port is no longer this subnet’s `.2`.

## Open

- Reverse-direction iperf (aimax-2 → aimax) not recorded.
- RDMA write bandwidth / latency not measured on this pair. Report 11’s 1.34 µs is the
  aimax ↔ Spark CX-7 number; do not cite it as aimax ↔ aimax-2 evidence.
- Dock ↔ host assignment (AG01 vs DEG1) unrecorded.
- First measurement on any NIC swap is still `lspci` LnkSta, not iperf. Dock powered before
  boot; the M.2 root port has no hotplug.
