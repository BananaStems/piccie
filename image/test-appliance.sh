#!/usr/bin/env bash
# Build the Piccie image in Docker, then boot it in QEMU for smoke testing.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKIP_BUILD=0
INCREMENTAL=0

for arg in "$@"; do
  case "${arg}" in
    --skip-build) SKIP_BUILD=1 ;;
    --incremental) INCREMENTAL=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: ./image/test-appliance.sh [--skip-build] [--incremental]

  --skip-build    Only run QEMU boot check on an existing image
  --incremental   Fast rebuild before boot (requires prior full build)

Runs a fast boot-only QEMU check (systemd up), not a full SSH/API test.
Requires: Docker Desktop (running) and qemu-system-aarch64.
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: ${arg}" >&2
      exit 1
      ;;
  esac
done

if ! command -v qemu-system-aarch64 >/dev/null 2>&1; then
  echo "qemu-system-aarch64 is required." >&2
  exit 1
fi

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    echo "Docker is not running. Start Docker Desktop, then retry." >&2
    exit 1
  fi
  BUILD_ARGS=(--docker)
  if [[ "${INCREMENTAL}" -eq 1 ]]; then
    BUILD_ARGS+=(--incremental)
  fi
  "${REPO_ROOT}/image/build-image.sh" "${BUILD_ARGS[@]}"
fi

SMOKE_ARGS=()
if [[ "${SKIP_BUILD}" -eq 1 ]]; then
  SMOKE_ARGS+=(--skip-boot)
fi
exec "${REPO_ROOT}/image/smoke-qemu.sh" "${SMOKE_ARGS[@]}"
