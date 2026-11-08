#!/usr/bin/env bash
# Verify Piccie's root is read-only from the start of every boot.
#
# No live booth ever regenerates an initramfs or asks raspi-config to mutate its
# boot files. Root is mounted ro by the factory cmdline + fstab. Persistent
# application state and NetworkManager profiles live on /data.
#
# Recovery: create piccie-no-readonly on the FAT boot partition. This service
# will deliberately remount root rw early in boot.
set -euo pipefail

BOOT_DIR="${PICCIE_BOOT_DIR:-/boot/firmware}"
RUN_DIR="${PICCIE_RUN_DIR:-/run}"
ROOT_MOUNT="${PICCIE_ROOT_MOUNT:-/}"
FINDMNT="${PICCIE_FINDMNT:-findmnt}"
MOUNT="${PICCIE_MOUNT:-mount}"

if [[ -e "${BOOT_DIR}/piccie-no-readonly" ]]; then
  echo "piccie-root: recovery marker present; remounting root writable."
  "${MOUNT}" -o remount,rw "${ROOT_MOUNT}"
  case ",$("${FINDMNT}" -no OPTIONS "${ROOT_MOUNT}" 2>/dev/null)," in
    *,rw,*) touch "${RUN_DIR}/piccie.root-writable" ;;
    *) echo "piccie-root: ERROR: root did not become writable." >&2; exit 1 ;;
  esac
  exit 0
fi

# The kernel command line and fstab both request ro. Enforce it here as well so
# an accidental missing kernel token fails closed without relying on the
# distribution's generic systemd-remount-fs service.
case ",$("${FINDMNT}" -no OPTIONS "${ROOT_MOUNT}" 2>/dev/null)," in
  *,ro,*) ;;
  *)
    echo "piccie-root: root was writable; enforcing read-only mode."
    "${MOUNT}" -o remount,ro "${ROOT_MOUNT}"
    ;;
esac

case ",$("${FINDMNT}" -no OPTIONS "${ROOT_MOUNT}" 2>/dev/null)," in
  *,ro,*)
    echo "piccie-root: read-only root verified."
    touch "${RUN_DIR}/piccie.root-readonly"
    ;;
  *)
    echo "piccie-root: ERROR: root did not become read-only." >&2
    exit 1
    ;;
esac
