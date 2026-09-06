#!/usr/bin/env bash
# Gate 3, peer side. Run this ON THE SPARK (gx10-141d).
# Auto-detects the QSFP interface and RDMA device -- interface naming on the
# Spark is not guaranteed stable across reboots, so nothing is hardcoded.
set -u
MYIP=192.168.100.2
PREFIX=24

echo "===== 1. Locating the QSFP interface ====="
IFACE=$(ip -o -4 addr show | awk -v ip="$MYIP" '$4 ~ "^"ip"/" {print $2; exit}')
if [ -n "${IFACE:-}" ]; then
  echo "  found by address: $IFACE already holds $MYIP"
else
  echo "  $MYIP not configured yet; looking for an mlx5 netdev..."
  for d in /sys/class/infiniband/*/device/net/*; do
    [ -e "$d" ] || continue
    IFACE=$(basename "$d"); echo "  candidate: $IFACE (rdma: $(basename $(dirname $(dirname $(dirname $d)))))"
  done
  [ -z "${IFACE:-}" ] && { echo "  FAIL: no RDMA-capable netdev found"; exit 1; }
  echo "  using $IFACE -- assigning $MYIP/$PREFIX"
  sudo ip addr add $MYIP/$PREFIX dev "$IFACE" 2>/dev/null || echo "  (address already present)"
  sudo ip link set "$IFACE" up
fi

echo
echo "===== 2. MTU 9000 ====="
sudo ip link set "$IFACE" mtu 9000 && echo "  set" || echo "  FAILED to set mtu"
echo "  mtu is now: $(cat /sys/class/net/$IFACE/mtu)"
echo "  link: $(cat /sys/class/net/$IFACE/operstate)  speed: $(cat /sys/class/net/$IFACE/speed 2>/dev/null) Mb/s"

echo
echo "===== 3. perftest ====="
if command -v ib_write_lat >/dev/null; then echo "  already installed"
else sudo apt install -y perftest ibverbs-utils mstflint; fi

echo
echo "===== 4. RDMA device for $IFACE ====="
DEV=""
for c in /sys/class/infiniband/*; do
  [ -e "$c/device/net/$IFACE" ] && DEV=$(basename "$c")
done
[ -z "$DEV" ] && { echo "  FAIL: no RDMA device maps to $IFACE"; exit 1; }
echo "  $DEV"

echo
echo "===== 5. RoCEv2 GID discovery (want ...ffff:c0a8:6402 = $MYIP) ====="
GID=""
for i in $(seq 0 15); do
  t=$(cat /sys/class/infiniband/$DEV/ports/1/gid_attrs/types/$i 2>/dev/null)
  g=$(cat /sys/class/infiniband/$DEV/ports/1/gids/$i 2>/dev/null)
  [ -z "$t" ] && continue
  echo "  [$i] $t  $g"
  if [ "$t" = "RoCE v2" ] && echo "$g" | grep -q 'ffff:c0a8:6402'; then GID=$i; fi
done
[ -z "$GID" ] && { echo; echo "  FAIL: no RoCEv2 IPv4 GID for $MYIP. Is the link up with the address assigned?"; exit 1; }

echo
echo "=================================================================="
echo " Spark ready.   device=$DEV   gid=$GID   iface=$IFACE"
echo
echo " Start the LATENCY server now (leave it running):"
echo "     ib_write_lat -d $DEV -x $GID -F"
echo
echo " Then after the latency run finishes, the BANDWIDTH server:"
echo "     ib_write_bw  -d $DEV -x $GID -F"
echo "=================================================================="
