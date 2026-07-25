#!/usr/bin/env bash
# Grow Piccie's final p3 /data partition without racing systemd's mount jobs.
#
# Boot 1 updates only the on-disk partition table, then immediately requests a
# reboot so the kernel never has to reread a table containing the mounted root.
# Boot 2 sees the larger p3, grows ext4 while it is still unmounted, verifies the
# result, and lets systemd continue with data.mount and the normal data seed.
set -euo pipefail

DATA_MOUNT="${PICCIE_GROW_DATA_MOUNT:-/data}"
SYS_BLOCK="${PICCIE_GROW_DATA_SYS_BLOCK:-/sys/class/block}"
DEGRADED_MARKER="${PICCIE_GROW_DATA_DEGRADED_MARKER:-/run/piccie.degraded}"
FAILURE_MARKER="${PICCIE_GROW_DATA_FAILURE_MARKER:-/run/piccie-data-grow.failed}"
EXPECTED_PARTITION=3

log() {
  echo "piccie-grow-data: $*"
}

die() {
  log "ERROR: $*" >&2
  exit 1
}

canonicalize_device() {
  readlink -f -- "$1"
}

is_block_device() {
  [[ -b "$1" ]]
}

read_uint() {
  local value
  value="$(<"$1")"
  [[ "${value}" =~ ^[0-9]+$ ]] || die "invalid numeric value in $1: ${value}"
  printf '%s\n' "${value}"
}

resolve_data_device() {
  local source=""
  source="$(findmnt --fstab --evaluate --noheadings --output SOURCE --target "${DATA_MOUNT}" 2>/dev/null || true)"
  [[ -n "${source}" && "${source}" != *$'\n'* ]] \
    || die "could not resolve exactly one ${DATA_MOUNT} source from /etc/fstab"
  [[ "${source}" == /dev/* ]] \
    || die "${DATA_MOUNT} source did not resolve to a block device: ${source}"

  DATA_DEV="$(canonicalize_device "${source}")"
  is_block_device "${DATA_DEV}" || die "${DATA_MOUNT} source is not a block device: ${DATA_DEV}"

  DATA_KNAME="$(lsblk --noheadings --nodeps --output KNAME "${DATA_DEV}" | xargs)"
  [[ -n "${DATA_KNAME}" ]] || die "lsblk could not identify ${DATA_DEV}"
  [[ "$(lsblk --noheadings --nodeps --output TYPE "${DATA_DEV}" | xargs)" == "part" ]] \
    || die "${DATA_DEV} is not a partition"

  PARENT_KNAME="$(lsblk --noheadings --nodeps --output PKNAME "${DATA_DEV}" | xargs)"
  [[ -n "${PARENT_KNAME}" && "${PARENT_KNAME}" != */* ]] \
    || die "lsblk could not identify the parent disk for ${DATA_DEV}"
  PARENT_DEV="$(canonicalize_device "/dev/${PARENT_KNAME}")"
  is_block_device "${PARENT_DEV}" || die "parent is not a block device: ${PARENT_DEV}"
}

read_table_geometry() {
  sfdisk --json "${PARENT_DEV}" | python3 -c '
import json
import os
import sys

target = os.path.realpath(sys.argv[1])
table = json.load(sys.stdin)["partitiontable"]
parts = table.get("partitions", [])
matches = [p for p in parts if os.path.realpath(p.get("node", "")) == target]
if len(matches) != 1:
    raise SystemExit(f"expected one table entry for {target}, found {len(matches)}")
part = matches[0]
ends = [int(p["start"]) + int(p["size"]) for p in parts]
print(
    table.get("label", ""),
    int(table.get("sectorsize", 0)),
    len(parts),
    int(part["start"]),
    int(part["size"]),
    max(ends, default=0),
)
' "${DATA_DEV}"
}

validate_target() {
  local data_sys="${SYS_BLOCK}/${DATA_KNAME}"
  local part_number table_geometry table_label table_part_count table_max_end
  local sys_start_512 sys_size_512

  [[ -r "${data_sys}/partition" && -r "${data_sys}/start" && -r "${data_sys}/size" ]] \
    || die "missing kernel partition geometry for ${DATA_DEV}"
  part_number="$(read_uint "${data_sys}/partition")"
  [[ "${part_number}" -eq "${EXPECTED_PARTITION}" ]] \
    || die "${DATA_DEV} is p${part_number}, expected the dedicated p${EXPECTED_PARTITION} data partition"

  [[ "$(blkid -o value -s PTTYPE "${PARENT_DEV}" 2>/dev/null)" == "dos" ]] \
    || die "${PARENT_DEV} does not have Piccie's expected DOS partition table"
  [[ "$(blkid -o value -s TYPE "${DATA_DEV}" 2>/dev/null)" == "ext4" ]] \
    || die "${DATA_DEV} is not ext4"
  [[ "$(blkid -o value -s LABEL "${DATA_DEV}" 2>/dev/null)" == "data" ]] \
    || die "${DATA_DEV} does not have the expected data filesystem label"

  table_geometry="$(read_table_geometry)" \
    || die "could not read the partition table for ${PARENT_DEV}"
  read -r table_label SECTOR_BYTES table_part_count TABLE_START TABLE_SIZE table_max_end \
    <<<"${table_geometry}"
  [[ "${table_label}" == "dos" && "${SECTOR_BYTES}" =~ ^[0-9]+$ && "${SECTOR_BYTES}" -gt 0 ]] \
    || die "unexpected partition-table geometry for ${PARENT_DEV}: ${table_geometry}"
  [[ "${table_part_count}" -eq 3 ]] \
    || die "${PARENT_DEV} has ${table_part_count} partitions; expected exactly boot, root, and data"
  [[ $((TABLE_START + TABLE_SIZE)) -eq "${table_max_end}" ]] \
    || die "${DATA_DEV} is not the final partition on ${PARENT_DEV}"

  sys_start_512="$(read_uint "${data_sys}/start")"
  sys_size_512="$(read_uint "${data_sys}/size")"
  [[ $((TABLE_START * SECTOR_BYTES)) -eq $((sys_start_512 * 512)) \
      && $((TABLE_SIZE * SECTOR_BYTES)) -eq $((sys_size_512 * 512)) ]] \
    || die "kernel and on-disk geometry disagree for ${DATA_DEV}; reboot before retrying"

  DISK_BYTES="$(blockdev --getsize64 "${PARENT_DEV}")"
  [[ "${DISK_BYTES}" =~ ^[0-9]+$ && "${DISK_BYTES}" -gt 0 ]] \
    || die "could not determine the size of ${PARENT_DEV}"
  [[ $((DISK_BYTES % SECTOR_BYTES)) -eq 0 ]] \
    || die "${PARENT_DEV} size is not aligned to its logical sector size"

  TARGET_SIZE=$((DISK_BYTES / SECTOR_BYTES - TABLE_START))
  [[ "${TARGET_SIZE}" -ge "${TABLE_SIZE}" ]] \
    || die "${DATA_DEV} extends beyond the reported end of ${PARENT_DEV}"
}

check_data_mount_state() {
  local mounted_source mounted_type

  SKIP_GROW=0
  if [[ -e "${DEGRADED_MARKER}" || -e "${DATA_MOUNT}/.DEGRADED" ]]; then
    log "${DATA_MOUNT} is in degraded/tmpfs mode; refusing to resize"
    SKIP_GROW=1
    return
  fi
  if ! mountpoint -q "${DATA_MOUNT}"; then
    return
  fi

  mounted_type="$(findmnt --noheadings --output FSTYPE --target "${DATA_MOUNT}" | xargs)"
  mounted_source="$(findmnt --noheadings --output SOURCE --target "${DATA_MOUNT}" | xargs)"
  if [[ "${mounted_type}" == "tmpfs" || "${mounted_source}" == "tmpfs" ]]; then
    log "${DATA_MOUNT} is a tmpfs fallback; refusing to resize"
    SKIP_GROW=1
    return
  fi

  die "${DATA_MOUNT} is already mounted; offline growth must run before data.mount"
}

grow_partition_and_reboot() {
  local geometry label sector_bytes part_count new_start new_size max_end

  log "extending ${DATA_DEV} from ${TABLE_SIZE} to ${TARGET_SIZE} sectors"
  printf 'start=%s, size=+\n' "${TABLE_START}" \
    | sfdisk --no-reread --lock=yes --no-tell-kernel \
        --wipe never --wipe-partitions never \
        -N "${EXPECTED_PARTITION}" "${PARENT_DEV}"
  sync

  geometry="$(read_table_geometry)" \
    || die "could not verify the updated partition table"
  read -r label sector_bytes part_count new_start new_size max_end <<<"${geometry}"
  [[ "${label}" == "dos" && "${sector_bytes}" -eq "${SECTOR_BYTES}" \
      && "${part_count}" -eq 3 && "${new_start}" -eq "${TABLE_START}" \
      && "${new_size}" -eq "${TARGET_SIZE}" \
      && $((new_start + new_size)) -eq "${max_end}" ]] \
    || die "partition-table verification failed after updating ${DATA_DEV}: ${geometry}"

  log "partition table updated; rebooting once before filesystem growth"
  systemctl --no-block reboot
}

read_filesystem_geometry() {
  tune2fs -l "${DATA_DEV}" 2>/dev/null | awk -F: '
    /^Block count:/ { gsub(/[[:space:]]/, "", $2); blocks=$2 }
    /^Block size:/  { gsub(/[[:space:]]/, "", $2); size=$2 }
    END {
      if (blocks !~ /^[0-9]+$/ || size !~ /^[0-9]+$/) exit 1
      print blocks, size
    }
  '
}

check_ext4() {
  local rc
  set +e
  e2fsck -pf "${DATA_DEV}"
  rc=$?
  set -e
  case "${rc}" in
    0|1) return 0 ;;
    *) die "e2fsck failed for ${DATA_DEV} with status ${rc}" ;;
  esac
}

grow_filesystem_if_needed() {
  local geometry fs_blocks fs_block_size fs_bytes partition_bytes

  geometry="$(read_filesystem_geometry)" \
    || die "could not read ext4 geometry from ${DATA_DEV}"
  read -r fs_blocks fs_block_size <<<"${geometry}"
  partition_bytes=$((TABLE_SIZE * SECTOR_BYTES))
  fs_bytes=$((fs_blocks * fs_block_size))

  if [[ $((fs_bytes + fs_block_size)) -gt "${partition_bytes}" ]]; then
    log "${DATA_DEV} partition and ext4 filesystem already use the full device"
    return 0
  fi

  log "growing ext4 on ${DATA_DEV} from ${fs_bytes} to ${partition_bytes} bytes"
  check_ext4
  resize2fs "${DATA_DEV}"
  check_ext4

  geometry="$(read_filesystem_geometry)" \
    || die "could not verify ext4 geometry after resize"
  read -r fs_blocks fs_block_size <<<"${geometry}"
  fs_bytes=$((fs_blocks * fs_block_size))
  [[ $((fs_bytes + fs_block_size)) -gt "${partition_bytes}" ]] \
    || die "ext4 verification failed: filesystem=${fs_bytes} bytes partition=${partition_bytes} bytes"
  log "filesystem expansion verified"
}

main() {
  # A degraded mount is deliberately left untouched so data-fallback retains
  # control. In the normal boot path /data is not mounted yet.
  check_data_mount_state
  if [[ "${SKIP_GROW}" -eq 1 ]]; then
    return 0
  fi

  resolve_data_device
  validate_target

  if [[ "${TABLE_SIZE}" -lt "${TARGET_SIZE}" ]]; then
    grow_partition_and_reboot
    return 0
  fi

  grow_filesystem_if_needed
}

record_result() {
  local rc=$?
  if [[ "${rc}" -eq 0 ]]; then
    rm -f "${FAILURE_MARKER}"
  else
    : >"${FAILURE_MARKER}"
  fi
}

run_main() {
  trap record_result EXIT
  main "$@"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  run_main "$@"
fi
