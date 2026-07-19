#!/usr/bin/env bash
# Fast QEMU smoke test: confirm the image boots to systemd (no SSH/API wait).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TIMEOUT="${PICCIE_QEMU_TIMEOUT:-600}"
KEEP_RUNNING=0
SKIP_BOOT=0
LOG=""

cleanup() {
  if [[ -n "${LOG}" && -f "${LOG}" ]]; then
    rm -f "${LOG}"
  fi
  if [[ "${KEEP_RUNNING}" -eq 0 ]]; then
    pkill -f "qemu-system-aarch64.*piccie-qemu" 2>/dev/null || true
  fi
}

for arg in "$@"; do
  case "${arg}" in
    --keep-running) KEEP_RUNNING=1 ;;
    --skip-boot) SKIP_BOOT=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: ./image/smoke-qemu.sh [--keep-running] [--skip-boot]

Boots the Piccie image in QEMU and passes when systemd starts.
Does not wait for SSH or the booth API (too slow/unreliable on Mac TCG).

  --keep-running  Leave QEMU running after a successful boot check
  --skip-boot       Check an already-running QEMU VM (reads its serial log only if found)

Env:
  PICCIE_QEMU_TIMEOUT   Seconds to wait for boot (default: 600)
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: ${arg}" >&2
      exit 1
      ;;
  esac
done

trap cleanup EXIT

boot_ok() {
  grep -q "Hostname set to <piccie>" "${LOG}" 2>/dev/null \
    || grep -q "Reached target multi-user.target" "${LOG}" 2>/dev/null
}

boot_failed() {
  grep -qE "Kernel panic|VFS: Cannot open root device|Unable to mount root" "${LOG}" 2>/dev/null
}

reboot_loop() {
  local boots
  boots="$(grep -c "Booting Linux on physical CPU" "${LOG}" 2>/dev/null || true)"
  boots="${boots:-0}"
  [[ "${boots}" -ge 4 ]] && ! boot_ok
}

if [[ "${SKIP_BOOT}" -eq 0 ]]; then
  pkill -f "qemu-system-aarch64.*piccie-qemu" 2>/dev/null || true
  sleep 2
  LOG="$(mktemp)"
  echo "Starting QEMU (boot-only check, timeout ${TIMEOUT}s)..."
  PICCIE_QEMU_HEADLESS=1 PICCIE_QEMU_BACKGROUND=1 \
    "${REPO_ROOT}/image/run-qemu.sh" >"${LOG}" 2>&1 &
else
  LOG="$(mktemp)"
  echo "Checking already-running QEMU (timeout ${TIMEOUT}s)..."
  if ! pgrep -f "qemu-system-aarch64.*piccie-qemu" >/dev/null; then
    echo "No QEMU VM running. Start one with: ./image/run-qemu.sh" >&2
    exit 1
  fi
  echo "(Serial log only available when smoke-qemu starts QEMU; checking ports as fallback.)" >&2
fi

deadline=$((SECONDS + TIMEOUT))
while (( SECONDS < deadline )); do
  if [[ -f "${LOG}" ]]; then
    if boot_failed; then
      echo "Boot failed. Last kernel lines:" >&2
      grep -E "panic|VFS:|mount" "${LOG}" | tail -5 >&2 || true
      exit 1
    fi
    if reboot_loop; then
      echo "Boot loop detected (watchdog or first-boot reboot)." >&2
      exit 1
    fi
    if boot_ok; then
      echo ""
      echo "Boot check passed — systemd started on Piccie."
      if [[ "${KEEP_RUNNING}" -eq 1 ]]; then
        trap - EXIT
        echo "QEMU left running. Stop with: pkill -f 'qemu-system-aarch64.*piccie-qemu'"
        echo "Interactive boot log: tail -f ${LOG}"
      fi
      exit 0
    fi
  fi
  sleep 5
done

echo "Timed out after ${TIMEOUT}s waiting for systemd boot." >&2
if [[ -f "${LOG}" ]]; then
  echo "Last log lines:" >&2
  tail -20 "${LOG}" >&2
fi
exit 1
