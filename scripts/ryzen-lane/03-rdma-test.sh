#!/usr/bin/env bash
# Post-reboot gate 3: the measurement that decides whether TP is viable.
# Reference (kyuz0, E810 Gen4 x4): 5.23 us latency, 50.64 Gb/s.
# We are on a Gen3 CX-5, so expect ~22 Gb/s. LATENCY is what matters here.
PEER=192.168.100.2
DEV=mlx5_0

command -v ib_write_lat >/dev/null || { echo "install first: sudo apt install -y perftest ibverbs-utils"; exit 1; }

echo "===== RoCEv2 GID discovery on $DEV ====="
GID=""
for i in $(seq 0 15); do
  t=$(cat /sys/class/infiniband/$DEV/ports/1/gid_attrs/types/$i 2>/dev/null)
  g=$(cat /sys/class/infiniband/$DEV/ports/1/gids/$i 2>/dev/null)
  n=$(cat /sys/class/infiniband/$DEV/ports/1/gid_attrs/ndevs/$i 2>/dev/null)
  [ -z "$t" ] && continue
  echo "  [$i] $t  ndev=$n  $g"
  # RoCE v2 + IPv4-mapped (::ffff:) = the one we want
  if [ "$t" = "RoCE v2" ] && echo "$g" | grep -q 'ffff:c0a8:6401'; then GID=$i; fi
done

[ -z "$GID" ] && { echo; echo "No RoCEv2 IPv4 GID found for 192.168.100.1 - check the link is up."; exit 1; }
echo
echo ">>> Using GID index $GID"

echo
echo "=================================================================="
echo " On the SPARK, start the servers first (one at a time):"
echo "   ib_write_lat -d rocep1s0f1 -x <its_gid> -F"
echo "   ib_write_bw  -d rocep1s0f1 -x <its_gid> -F"
echo " Find its GID the same way, matching ...ffff:c0a8:6402"
echo "=================================================================="
echo
read -p "Press enter once ib_write_lat is running on the Spark... "

echo
echo "===== LATENCY (the number that decides TP viability) ====="
ib_write_lat -d $DEV -x $GID -F $PEER 2>&1 | tail -12

echo
read -p "Now start ib_write_bw on the Spark, then press enter... "
echo "===== BANDWIDTH ====="
ib_write_bw -d $DEV -x $GID -F $PEER 2>&1 | tail -12

echo
echo "=================================================================="
echo " INTERPRETATION (typical latency, us):"
echo "   2-10    healthy RoCE  -> TP viable, build node 2"
echo "   10-20   degraded      -> investigate before committing"
echo "   >50     broken        -> likely falling back to TCP"
echo " Compare: kyuz0 measured 5.23 us. Your PoC TCP was 590 us."
echo "=================================================================="
