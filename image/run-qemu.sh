#!/usr/bin/env bash
# Boot a Piccie SD image in QEMU (Pi 4B — matches our pi-gen arm64 image).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMG="${PICCIE_IMG:-}"
if [[ -z "${IMG}" ]]; then
  if [[ -f "${REPO_ROOT}/.pi-gen/deploy/piccie.img" ]]; then
    IMG="${REPO_ROOT}/.pi-gen/deploy/piccie.img"
  else
    IMG="$(ls -t "${REPO_ROOT}"/.pi-gen/deploy/*-piccie.img 2>/dev/null | head -1 || true)"
  fi
fi
BOOT_DIR="${REPO_ROOT}/.pi-gen/qemu-boot"
MACHINE="${PICCIE_QEMU_MACHINE:-raspi4b}"
MEMORY="${PICCIE_QEMU_MEM:-2G}"
SSH_PORT="${PICCIE_QEMU_SSH_PORT:-2222}"
HTTP_PORT="${PICCIE_QEMU_HTTP_PORT:-8080}"
HEADLESS="${PICCIE_QEMU_HEADLESS:-0}"
BACKGROUND="${PICCIE_QEMU_BACKGROUND:-0}"

if [[ ! -f "${IMG}" ]]; then
  echo "Image not found: ${IMG}" >&2
  echo "Build first: ./image/build-image.sh --docker" >&2
  exit 1
fi

if ! command -v qemu-system-aarch64 >/dev/null 2>&1; then
  echo "qemu-system-aarch64 is required." >&2
  exit 1
fi

"${REPO_ROOT}/image/extract-boot.sh" "${IMG}" "${BOOT_DIR}"

if [[ -f "${BOOT_DIR}/bcm2711-rpi-4-b.dtb" ]]; then
  DTB="${BOOT_DIR}/bcm2711-rpi-4-b-qemu.dtb"
  if [[ ! -f "${DTB}" || "${BOOT_DIR}/bcm2711-rpi-4-b.dtb" -nt "${DTB}" ]]; then
    if command -v dtc >/dev/null 2>&1; then
      DTS="${BOOT_DIR}/bcm2711-rpi-4-b-qemu.dts"
      dtc -I dtb -O dts -o "${DTS}" "${BOOT_DIR}/bcm2711-rpi-4-b.dtb" 2>/dev/null
      python3 - "${DTS}" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text()
needle = "watchdog@7e100000 {"
if needle in text and "status = \"disabled\"" not in text.split(needle, 1)[1].split("}", 1)[0]:
    text = text.replace(needle, needle + "\n\t\tstatus = \"disabled\";", 1)
    path.write_text(text)
PY
      dtc -I dts -O dtb -o "${DTB}" "${DTS}" 2>/dev/null
    else
      cp "${BOOT_DIR}/bcm2711-rpi-4-b.dtb" "${DTB}"
      echo "Warning: dtc not found — using unpatched DTB (watchdog may reboot the VM)." >&2
    fi
  fi
  CPU="cortex-a72"
  MACHINE="raspi4b"
  MEMORY="${PICCIE_QEMU_MEM:-2G}"
  # On raspi4b the SD slot is mmcblk1 (not mmcblk0 like Pi 3 / real hardware).
  ROOT_DEV="/dev/mmcblk1p2"
  # Do not pass boot/initramfs8 — it is modules-only and breaks handoff to systemd.
  # systemd.firstboot=off avoids repeated reboots from first-boot wizard on resized images.
  APPEND="earlycon=pl011,mmio32,0xfe201000 console=ttyAMA0,115200 root=${ROOT_DEV} rw rootwait rootfstype=ext4 piccie.qemu=1 dwc_otg.fiq_fsm_enable=0 systemd.firstboot=off systemd.condition_first_boot=0 nowatchdog systemd.watchdog=0 systemd.unit=multi-user.target systemd.mask=lightdm.service systemd.mask=systemd-growfs-root.service systemd.mask=rpi-resize-swap-file.service"
else
  DTB="${BOOT_DIR}/bcm2710-rpi-3-b-plus.dtb"
  CPU="cortex-a53"
  MACHINE="raspi3b"
  MEMORY="1G"
  ROOT_DEV="/dev/mmcblk0p2"
  APPEND="console=ttyAMA0,115200 root=${ROOT_DEV} rw rootwait rootfstype=ext4 piccie.qemu=1"
  echo "Warning: Pi 4 DTB not found — falling back to Pi 3B (may hang on splash)." >&2
fi

QEMU_IMG="${REPO_ROOT}/.pi-gen/deploy/piccie-qemu.img"
if [[ ! -f "${QEMU_IMG}" || "${IMG}" -nt "${QEMU_IMG}" ]]; then
  cp "${IMG}" "${QEMU_IMG}"
fi
qemu-img resize "${QEMU_IMG}" 8G >/dev/null

DISPLAY_ARGS=(-display cocoa)
if [[ "${HEADLESS}" == "1" ]]; then
  DISPLAY_ARGS=(-nographic)
fi

echo ""
echo "Starting QEMU (${MACHINE}, root=${ROOT_DEV})..."
echo "  SSH:      key-only on port ${SSH_PORT} (if a key was installed in the image)"
echo "  Booth UI: http://localhost:${HTTP_PORT}  (first boot is slow — 5–15 min on Mac)"
echo "  Stop:     Ctrl+A then X  (or close the window)"
echo ""

QEMU_ARGS=(
  -machine "${MACHINE}"
  -cpu "${CPU}"
  -smp 4
  -m "${MEMORY}"
  -kernel "${BOOT_DIR}/kernel8.img"
  -dtb "${DTB}"
  -drive "file=${QEMU_IMG},format=raw,if=sd"
  -append "${APPEND}"
  -usb
  -netdev "user,id=net0,hostfwd=tcp:127.0.0.1:${SSH_PORT}-:22,hostfwd=tcp:127.0.0.1:${HTTP_PORT}-:8080"
  -device usb-net,netdev=net0
  "${DISPLAY_ARGS[@]}"
  -serial mon:stdio
)

if [[ "${BACKGROUND}" == "1" ]]; then
  qemu-system-aarch64 "${QEMU_ARGS[@]}" &
  echo "QEMU started in background (PID $!)."
else
  exec qemu-system-aarch64 "${QEMU_ARGS[@]}"
fi
