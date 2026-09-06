#!/usr/bin/env bash
# Post-reboot gate 4: THE hypothesis test.
# Re-run the exact load that killed the CX-5, now with pcie_aspm=off + pci=realloc.
# Survives -> ASPM/BAR was the cause. Dies -> thermal or dock power.
PEER=192.168.100.2
IFACE=enp196s0np0
BDF=0000:c4:00.0
OUT=/tmp/cx5-stress-$(date +%H%M%S)

command -v iperf3 >/dev/null || { echo "need iperf3"; exit 1; }
echo "Start 'iperf3 -s' on the Spark, then press enter."; read -r

# temperature sampler, if mstflint is available
if command -v mget_temp_ext >/dev/null; then
  ( while true; do echo "$(date +%T) $(sudo mget_temp_ext -d $BDF 2>/dev/null | tr -d '\n')"; sleep 2; done ) > $OUT.temp 2>&1 &
  TPID=$!
  echo "temperature sampling -> $OUT.temp"
else
  echo "WARN: mstflint not installed, no temperature data."
  echo "      sudo apt install -y mstflint   (do this BEFORE the run to get temps)"
  TPID=""
fi

echo
echo "===== Ramping load: 1 -> 4 -> 8 streams ====="
for P in 1 4 8; do
  echo "--- $P stream(s) ---"
  timeout 60 iperf3 -c $PEER -t 20 -P $P -f g 2>&1 | grep -E 'SUM|receiver' | tail -2
  if ! ls -d /sys/class/net/$IFACE >/dev/null 2>&1; then
    echo
    echo "!!! NIC DROPPED at P=$P - the fault reproduced."
    [ -n "$TPID" ] && kill $TPID 2>/dev/null
    echo "Last temperatures:"; tail -5 $OUT.temp 2>/dev/null
    journalctl -k --no-pager -n 40 | grep -i mlx5 | tail -10
    echo
    echo ">>> ASPM/BAR hypothesis DISPROVED. Next suspect: thermal or AG01 slot power."
    echo ">>> Re-run with a fan on the card to separate those two."
    exit 1
  fi
  echo "    NIC still alive"
done

[ -n "$TPID" ] && kill $TPID 2>/dev/null
echo
echo ">>> SURVIVED all three loads."
echo ">>> The kernel params (pcie_aspm=off / pci=realloc) very likely fixed it."
[ -f $OUT.temp ] && { echo; echo "Peak temperature seen:"; sort -k2 -n $OUT.temp | tail -3; }
echo
echo "Final state:"; ip -br addr show $IFACE
