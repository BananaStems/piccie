#!/usr/bin/env bash
# Boot 1 only: AFTER provisioning, enable the read-only root overlay (+ read-only
# boot), then reboot. On boot 2+ the root fs is an immutable tmpfs overlay that
# cannot corrupt on power-yank. All persistent writes go to the separate /data
# partition.
#
# SAFETY:
#  - Runs only once provisioning succeeded (/data/.provisioned) and only once
#    (/data/.lockdown-done).
#  - Kill switch: create /boot/firmware/piccie-no-readonly on the FAT
#    partition (visible from a Mac) to keep root WRITABLE and skip lockdown.
#  - If overlay enable fails, set -e aborts before reboot -> boot 1 stays
#    writable and functional (not bricked); retried next boot.
#  - RECOVERY if a bad overlay ever stops boot: on the Mac, edit cmdline.txt on
#    the bootfs partition and delete the "boot=overlay" token.
set -euo pipefail

if [ -e /boot/firmware/piccie-no-readonly ]; then
  echo "lockdown: kill switch present; leaving root writable."
  touch /data/.lockdown-done 2>/dev/null || true
  exit 0
fi

[ -e /data/.provisioned ]   || { echo "lockdown: not provisioned yet; deferring."; exit 0; }
[ -e /data/.lockdown-done ] && exit 0

# NEVER lock down against a degraded /data. If the real partition failed to mount
# and data-fallback swapped in a tmpfs, /data/.provisioned lives in RAM: enabling
# the read-only root overlay now would leave the booth permanently amnesiac (root
# frozen, /data volatile) with no way to re-provision. Bail until /data is real.
if [ -e /data/.DEGRADED ] || ! mountpoint -q /data; then
  echo "lockdown: /data degraded or not mounted; refusing to lock down."
  exit 0
fi
case "$(findmnt -no FSTYPE /data 2>/dev/null)" in
  ext4|ext3|btrfs|xfs) : ;;
  *) echo "lockdown: /data is not a real disk filesystem; refusing to lock down."; exit 0 ;;
esac

# Stop the engine so its periodic /data writes cannot be torn by the reboot.
systemctl stop piccie-engine.service 2>/dev/null || true
sync

# bootro first (edits fstab/cmdline while still writable), overlay last (freezes
# fstab). Let raspi-config manage the initramfs (auto_initramfs=1 is already set;
# hand-rolling update-initramfs would collide).
raspi-config nonint do_bootro 0 || true     # 0 = enable boot read-only (if supported)
raspi-config nonint do_overlayfs 0          # 0 = enable root overlay (critical)

touch /data/.lockdown-done
sync
systemctl disable piccie-lockdown.service || true
systemctl reboot
