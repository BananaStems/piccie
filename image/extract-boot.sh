#!/usr/bin/env bash
# Extract kernel + DTB from a pi-gen SD image boot partition.
set -euo pipefail

IMG="${1:-}"
OUT_DIR="${2:-}"

if [[ -z "${IMG}" || -z "${OUT_DIR}" ]]; then
  echo "Usage: $0 <image.img> <output-dir>" >&2
  exit 1
fi

if [[ ! -f "${IMG}" ]]; then
  echo "Image not found: ${IMG}" >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"
IMG="$(cd "$(dirname "${IMG}")" && pwd)/$(basename "${IMG}")"
OUT_DIR="$(cd "${OUT_DIR}" && pwd)"

cleanup() {
  if [[ -n "${DISK_DEV:-}" ]]; then
    hdiutil detach "${DISK_DEV}" 2>/dev/null || true
  elif [[ -n "${MOUNT_DIR:-}" && -d "${MOUNT_DIR}" && "${AUTO_MOUNTED:-}" != "1" ]]; then
    umount "${MOUNT_DIR}" 2>/dev/null || true
    rmdir "${MOUNT_DIR}" 2>/dev/null || true
  fi
  if [[ -n "${LOOP_DEV:-}" ]]; then
    losetup -d "${LOOP_DEV}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [[ "$(uname -s)" == "Darwin" ]]; then
  # Auto-mount works without root; -nomount + mount often fails in sandboxes.
  ATTACH_OUT="$(hdiutil attach -imagekey diskimage-class=CRawDiskImage "${IMG}")"
  MOUNT_DIR="$(echo "${ATTACH_OUT}" | awk '/Windows_FAT|FAT32|bootfs/ {print $NF; exit}')"
  DISK_DEV="$(echo "${ATTACH_OUT}" | awk 'NR==1 {print $1}')"
  if [[ -z "${MOUNT_DIR}" || ! -d "${MOUNT_DIR}" ]]; then
    echo "Failed to mount boot partition from ${IMG}" >&2
    exit 1
  fi
  AUTO_MOUNTED=1
else
  LOOP_DEV="$(losetup --find --show -P "${IMG}")"
  PART="${LOOP_DEV}p1"
  if [[ ! -e "${PART}" ]]; then
    PART="${LOOP_DEV}1"
  fi
  MOUNT_DIR="$(mktemp -d)"
  mount "${PART}" "${MOUNT_DIR}"
fi

shopt -s nullglob
for file in "${MOUNT_DIR}"/bcm*.dtb "${MOUNT_DIR}"/kernel*.img \
  "${MOUNT_DIR}"/initramfs8 "${MOUNT_DIR}"/initramfs_2712; do
  [[ -f "${file}" ]] && cp "${file}" "${OUT_DIR}/"
done
shopt -u nullglob

if [[ ! -f "${OUT_DIR}/kernel8.img" ]]; then
  echo "kernel8.img not found in boot partition" >&2
  exit 1
fi

# Prefer Pi 4 DTB when emulating raspi4b; fall back to Pi 3.
if [[ ! -f "${OUT_DIR}/bcm2711-rpi-4-b.dtb" ]]; then
  for candidate in bcm2711-rpi-4-b.dtb bcm2710-rpi-3-b-plus.dtb bcm2710-rpi-3-b.dtb; do
    if [[ -f "${MOUNT_DIR}/${candidate}" ]]; then
      cp "${MOUNT_DIR}/${candidate}" "${OUT_DIR}/"
    fi
  done
fi
if [[ ! -f "${OUT_DIR}/bcm2711-rpi-4-b.dtb" && ! -f "${OUT_DIR}/bcm2710-rpi-3-b-plus.dtb" ]]; then
  echo "No supported device tree blob found in boot partition" >&2
  exit 1
fi

echo "Extracted boot files to ${OUT_DIR}"
