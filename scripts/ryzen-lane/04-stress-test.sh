#!/usr/bin/env bash
# Post-reboot gate 4: THE hypothesis test.
# Re-run the exact load that killed the CX-5, now with pcie_aspm=off + pci=realloc.
# Survives -> ASPM/BAR was the cause. Dies -> thermal or dock power.
#
# Temperature is read from the kernel's mlx5 hwmon sensor (no sudo, always
# present) rather than mget_temp_ext, which ships only in NVIDIA's proprietary
# MFT bundle and is NOT in Ubuntu's mstflint package.
PEER=192.168.100.2
IFACE=enp196s0np0
BDF=0000:c4:00.0
OUT=/tmp/cx5-stress-$(date +%H%M%S)

command -v iperf3 >/dev/null || { echo "need iperf3"; exit 1; }

# ---- locate the mlx5 temperature sensor -------------------------------------
TEMPF=""
for h in /sys/class/hwmon/hwmon*; do
  [ "$(cat $h/name 2>/dev/null)" = "mlx5" ] && [ -r "$h/temp1_input" ] && TEMPF="$h/temp1_input"
done
if [ -n "$TEMPF" ]; then
  CRIT=$(( $(cat ${TEMPF%input}crit 2>/dev/null || echo 105000) / 1000 ))
  echo "temperature source: $TEMPF   (idle $(( $(cat $TEMPF) / 1000 ))C, crit ${CRIT}C)"
elif command -v mstmget_temp >/dev/null; then
  echo "temperature source: mstmget_temp (needs sudo)"
else
  echo "WARN: no temperature source. Thermal branch will be undecidable."
fi

# ---- start the peer iperf3 server -------------------------------------------
if ssh -o BatchMode=yes -o ConnectTimeout=5 vikassridhar@$PEER true 2>/dev/null; then
  echo "starting iperf3 -s on peer over ssh..."
  ssh -o BatchMode=yes vikassridhar@$PEER 'pkill -x iperf3; sleep 1; nohup iperf3 -s -D' 2>/dev/null
  sleep 2
else
  echo "No key-based ssh to peer. Start 'iperf3 -s' on it manually, then press enter."
  read -r
fi

# ---- temperature sampler ----------------------------------------------------
TPID=""
if [ -n "$TEMPF" ]; then
  ( while true; do echo "$(date +%T) $(( $(cat $TEMPF 2>/dev/null || echo 0) / 1000 ))"; sleep 2; done ) > $OUT.temp 2>&1 &
  TPID=$!
  echo "temperature sampling -> $OUT.temp"
fi
cleanup() { [ -n "$TPID" ] && kill $TPID 2>/dev/null; }
trap cleanup EXIT

peak() { [ -f $OUT.temp ] && awk '{if($2>m)m=$2}END{print m"C"}' $OUT.temp; }

echo
echo "===== Ramping load: 1 -> 4 -> 8 streams ====="
for P in 1 4 8; do
  echo "--- $P stream(s) ---  (temp now $([ -n "$TEMPF" ] && echo $(( $(cat $TEMPF)/1000 ))C || echo n/a))"
  timeout 90 iperf3 -c $PEER -t 20 -P $P -f g 2>&1 | grep -E 'SUM|receiver' | tail -2
  if ! ls -d /sys/class/net/$IFACE >/dev/null 2>&1; then
    echo
    echo "!!! NIC DROPPED at P=$P - the fault reproduced."
    cleanup
    echo "Peak temperature: $(peak)"
    echo "Last samples:"; tail -5 $OUT.temp 2>/dev/null
    journalctl -k --no-pager -n 60 | grep -i mlx5 | tail -10
    echo
    echo ">>> ASPM/BAR hypothesis DISPROVED."
    echo ">>> If peak was near ${CRIT:-105}C -> thermal. If it died cool -> AG01 slot power."
    exit 1
  fi
  echo "    NIC still alive  (peak so far $(peak))"
done

cleanup
echo
echo ">>> SURVIVED all three loads."
echo ">>> The kernel params (pcie_aspm=off / pci=realloc) very likely fixed it."
echo "Peak temperature: $(peak)"
[ -f $OUT.temp ] && { echo "Hottest samples:"; sort -k2 -n $OUT.temp | tail -3; }
echo
echo "Final state:"; ip -br addr show $IFACE
echo "  link: $(cat /sys/bus/pci/devices/$BDF/current_link_speed) x$(cat /sys/bus/pci/devices/$BDF/current_link_width)"
