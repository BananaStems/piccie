#!/usr/bin/env bash
# Fast QEMU smoke test: confirm p3 grows across one reboot and systemd comes up.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TIMEOUT="${PICCIE_QEMU_TIMEOUT:-1200}"
KEEP_RUNNING=0
SKIP_BOOT=0
LOG=""
REBOOT_RESTARTED=0
HTTP_PORT="${PICCIE_QEMU_HTTP_PORT:-18080}"
LAUNCH_PID=""

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

Boots a fresh copy of the Piccie image with 256 MiB of extra virtual-card space.
Passes after p3/ext4 growth, the controlled reboot, systemd startup, and a
successful response from the real engine health endpoint.

  --keep-running  Leave QEMU running after a successful boot check
  --skip-boot       Check an already-running QEMU VM (reads its serial log only if found)

Env:
  PICCIE_QEMU_TIMEOUT      Seconds to wait for boot (default: 1200)
  PICCIE_QEMU_EXTRA_SIZE   Extra virtual-card bytes (default: 256 MiB)
  PICCIE_QEMU_HTTP_PORT    Host health-check port (default: 18080)
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
  grep -qE "piccie-grow-data: (filesystem expansion verified|partition and ext4 filesystem already use the full device)" "${LOG}" 2>/dev/null \
    && grep -q "Reached target local-fs.target" "${LOG}" 2>/dev/null \
    && grep -q "Reached target multi-user.target" "${LOG}" 2>/dev/null \
    && curl -fsS --max-time 3 "http://127.0.0.1:${HTTP_PORT}/healthz" >/dev/null
}

boot_failed() {
  grep -qE "Kernel panic|VFS: Cannot open root device|Unable to mount root|piccie-grow-data: ERROR:|Failed to mount |Dependency failed for local-fs.target|You are in emergency mode|Cannot open access to console" "${LOG}" 2>/dev/null
}

reboot_loop() {
  local boots
  boots="$(grep -c "Booting Linux on physical CPU" "${LOG}" 2>/dev/null || true)"
  boots="${boots:-0}"
  [[ "${boots}" -ge 4 ]] && ! boot_ok
}

restart_after_qemu_reboot() {
  [[ "${REBOOT_RESTARTED}" -eq 0 ]] \
    && grep -qE "Reboot failed -- System halted|reboot: Restarting system" "${LOG}" 2>/dev/null
}

if [[ "${SKIP_BOOT}" -eq 0 ]]; then
  pkill -f "qemu-system-aarch64.*piccie-qemu" 2>/dev/null || true
  sleep 2
  LOG="$(mktemp)"
  echo "Starting QEMU (data-growth boot check, timeout ${TIMEOUT}s)..."
  PICCIE_QEMU_FRESH="${PICCIE_QEMU_FRESH:-1}" \
    PICCIE_QEMU_REUSE_IMAGE="${PICCIE_QEMU_REUSE_IMAGE:-0}" \
    PICCIE_QEMU_EXTRA_SIZE="${PICCIE_QEMU_EXTRA_SIZE:-268435456}" \
    PICCIE_QEMU_HTTP_PORT="${HTTP_PORT}" \
    PICCIE_QEMU_HEADLESS=1 PICCIE_QEMU_BACKGROUND=1 \
    "${REPO_ROOT}/image/run-qemu.sh" >"${LOG}" 2>&1 &
  LAUNCH_PID=$!
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
    if restart_after_qemu_reboot; then
      echo "QEMU halted at the controlled reboot; starting boot two..."
      pkill -f "qemu-system-aarch64.*piccie-qemu" 2>/dev/null || true
      PICCIE_QEMU_FRESH=0 PICCIE_QEMU_REUSE_IMAGE=1 \
        PICCIE_QEMU_EXTRA_SIZE="${PICCIE_QEMU_EXTRA_SIZE:-268435456}" \
        PICCIE_QEMU_HTTP_PORT="${HTTP_PORT}" \
        PICCIE_QEMU_HEADLESS=1 PICCIE_QEMU_BACKGROUND=1 \
        "${REPO_ROOT}/image/run-qemu.sh" >>"${LOG}" 2>&1 &
      LAUNCH_PID=$!
      REBOOT_RESTARTED=1
    fi
    if [[ -n "${LAUNCH_PID}" ]] \
        && ! kill -0 "${LAUNCH_PID}" 2>/dev/null \
        && ! pgrep -f "qemu-system-aarch64.*piccie-qemu" >/dev/null; then
      echo "QEMU failed to start or exited unexpectedly. Last log lines:" >&2
      tail -20 "${LOG}" >&2
      exit 1
    fi
    if boot_ok; then
      echo ""
      echo "Boot check passed — data grew and the Piccie engine answered."
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
