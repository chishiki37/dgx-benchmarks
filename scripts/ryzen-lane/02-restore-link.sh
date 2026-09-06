#!/usr/bin/env bash
# Post-reboot gate 2: remove the stale colliding profile, persist the real config,
# and bring the link up at MTU 9000.
IFACE=enp196s0np0
PEER=192.168.100.2

echo "===== Removing stale profile (colliding 10.10.10.1/30) ====="
sudo nmcli con delete qsfp-spark 2>/dev/null && echo "  deleted qsfp-spark" || echo "  (not present)"
sudo nmcli con delete qsfp-sparklink 2>/dev/null

echo
echo "===== Creating persistent profile ====="
sudo nmcli con add type ethernet ifname "$IFACE" con-name qsfp-sparklink \
  ipv4.method manual ipv4.addresses 192.168.100.1/24 \
  ipv4.never-default yes ipv6.method disabled \
  connection.autoconnect yes 802-3-ethernet.mtu 9000
sudo nmcli con up qsfp-sparklink
sleep 3

echo
echo "===== State ====="
ip -br addr show "$IFACE"
echo "  mtu: $(cat /sys/class/net/$IFACE/mtu)"

echo
echo "===== Connectivity (standard frames) ====="
ping -c3 -W2 -I "$IFACE" $PEER 2>&1 | tail -2

echo
echo "===== Jumbo frames ====="
echo "  NOTE: this fails until the Spark side is also at MTU 9000:"
echo "        sudo ip link set enp1s0f1np1 mtu 9000"
if ping -c2 -M do -s 8972 -W2 -I "$IFACE" $PEER >/dev/null 2>&1; then
  echo "  OK: 9000-byte path confirmed end to end"
else
  echo "  NOT YET: set MTU 9000 on the Spark, then re-run this check:"
  echo "        ping -c2 -M do -s 8972 -I $IFACE $PEER"
fi

echo
echo "===== Persisted ====="
sudo ls /etc/netplan/ | grep 90-NM
