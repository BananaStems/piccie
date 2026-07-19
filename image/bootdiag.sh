#!/bin/bash
# Boot diagnostics snapshot. Writes to /data/diag (readable over SSH) AND, while
# the FAT boot partition is still writable (boot 1, before read-only lockdown),
# also to /boot/firmware so it can be read from a Mac with no network/console.
# Runs late each boot via piccie-bootdiag.service and overwrites the file.
set +e

mkdir -p /data/diag 2>/dev/null
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
TMP="$(mktemp 2>/dev/null || echo /tmp/pbdiag.$$)"

{
  echo "=== piccie boot diag ${TS} ==="
  echo "### uname"; uname -a
  echo "### default target"; systemctl get-default
  echo "### mounts (overlay/ro check)"
  echo "/      -> $(findmnt -no FSTYPE,OPTIONS / 2>&1)"
  echo "/boot/firmware -> $(findmnt -no FSTYPE,OPTIONS /boot/firmware 2>&1)"
  echo "/data  -> $(findmnt -no FSTYPE,OPTIONS /data 2>&1)"
  echo "### cmdline"; cat /proc/cmdline
  echo "### lockdown markers"; ls -l /data/.provisioned /data/.lockdown-done /data/.datapart-done /data/.DEGRADED 2>&1
  echo "### failed units"; systemctl --failed --no-pager
  echo
  echo "### usb storage (bridge id for UAS quirk)"; lsusb 2>&1
  echo "--- uas/usb-storage modules ---"; lsmod | grep -E 'uas|usb_storage' 2>&1
  echo "--- sd/usb dmesg ---"; dmesg | grep -iE 'uas|usb-storage|\bsd [0-9]' | tail -20 2>&1
  echo
  echo "### lightdm enabled/active"; systemctl is-enabled lightdm 2>&1; systemctl is-active lightdm 2>&1
  echo "### lightdm log"; journalctl -u lightdm -b --no-pager 2>&1 | tail -40
  echo "### sessions"; loginctl --no-pager 2>&1
  echo "### X/openbox/chromium procs"; pgrep -a Xorg 2>&1; pgrep -a openbox 2>&1; pgrep -a chromium 2>&1
  echo "### drm connectors"; for s in /sys/class/drm/card*-HDMI-A-*/status; do [ -e "$s" ] && echo "$s: $(cat "$s" 2>/dev/null)"; done 2>&1
  echo "### drm/edid/mode dmesg"; dmesg | grep -iE 'drm|vc4|edid|mode' | tail -25 2>&1
  echo
  echo "### network devices"; nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device 2>&1
  echo "### connections"; nmcli -t -f NAME,UUID,TYPE,DEVICE connection show 2>&1
  echo "### rfkill"; rfkill list 2>&1
  echo "### ip"; ip -brief addr 2>&1
  echo "### nm keyfile store"; ls -l /data/system-connections/ 2>&1
  echo
  echo "### setup marker"; [ -f /data/.provisioned ] && cat /data/.provisioned 2>&1
  echo "### engine status"; systemctl status piccie-engine --no-pager -l 2>&1 | tail -20
  echo "### engine log"; journalctl -u piccie-engine -b --no-pager 2>&1 | tail -40
  echo "### api"; curl -s -o /dev/null -w "api_http=%{http_code}\n" http://localhost:8080/api/status 2>&1
  echo
  echo "### slow boot"; systemd-analyze blame 2>&1 | head -25
  echo "### boot time"; systemd-analyze 2>&1
} > "${TMP}" 2>&1

# SSH-readable copy on /data (always).
cp -f "${TMP}" /data/diag/piccie-boot-diag.txt 2>/dev/null
# Mac-readable copy on the FAT partition when it's still writable (boot 1).
cp -f "${TMP}" /boot/firmware/piccie-boot-diag.txt 2>/dev/null || true
rm -f "${TMP}" 2>/dev/null
sync
