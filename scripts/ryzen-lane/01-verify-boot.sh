#!/usr/bin/env bash
# Post-reboot gate 1: did the kernel params take, and did the NIC come back?
# Read-only. No sudo needed.
BDF=0000:c4:00.0
FAIL=0

echo "===== 1. Kernel parameters ====="
for p in iommu=pt pci=realloc pcie_aspm=off; do
  if grep -q -- "$p" /proc/cmdline; then echo "  OK      $p"
  else echo "  MISSING $p"; FAIL=1; fi
done
echo "  cmdline: $(cat /proc/cmdline)"

echo
echo "===== 2. ASPM policy ====="
pol=$(cat /sys/module/pcie_aspm/parameters/policy 2>/dev/null)
echo "  $pol"
grep -q 'pcie_aspm=off' /proc/cmdline && echo "  (disabled via cmdline - policy line may still show default)"

echo
echo "===== 3. NIC enumerated? ====="
line=$(lspci -nn | grep -i mellanox)
echo "  $line"
if echo "$line" | grep -q 'rev ff\|ffff'; then
  echo "  FAIL: card still reading all-Fs (wedged)."; FAIL=1
elif echo "$line" | grep -q 'Ethernet controller'; then
  echo "  OK: enumerated as an Ethernet controller"
else
  echo "  FAIL: card not visible at all"; FAIL=1
fi

echo
echo "===== 4. PCIe link ====="
if [ -e /sys/bus/pci/devices/$BDF/current_link_speed ]; then
  sp=$(cat /sys/bus/pci/devices/$BDF/current_link_speed)
  wd=$(cat /sys/bus/pci/devices/$BDF/current_link_width)
  echo "  $sp  x$wd    (CX-5 is Gen3, so 8.0 GT/s x4 is correct and optimal)"
  [ "$wd" = "4" ] || { echo "  WARN: expected x4"; FAIL=1; }
else
  echo "  FAIL: no PCIe link info"; FAIL=1
fi

echo
echo "===== 5. netdev + driver ====="
if [ -d /sys/class/net/enp196s0np0 ]; then
  echo "  OK: enp196s0np0 present"
  echo "  speed: $(cat /sys/class/net/enp196s0np0/speed 2>/dev/null) Mb/s   mtu: $(cat /sys/class/net/enp196s0np0/mtu)"
  echo "  rdma:  $(ls /sys/class/infiniband/ 2>/dev/null | tr '\n' ' ')"
else
  echo "  FAIL: enp196s0np0 absent"; FAIL=1
fi

echo
echo "===== 6. IOMMU mode ====="
journalctl -k --no-pager -b 2>/dev/null | grep -iE 'iommu.*(passthrough|pt mode)' | head -2 || echo "  (no explicit passthrough line)"

echo
if [ $FAIL -eq 0 ]; then echo ">>> GATE 1 PASS - proceed to 02-restore-link.sh"
else echo ">>> GATE 1 FAIL - stop and report the output above"; fi
exit $FAIL
