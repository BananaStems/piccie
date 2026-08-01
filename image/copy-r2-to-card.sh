#!/usr/bin/env bash
# Validate the private local R2 file and copy it to a freshly flashed boot drive.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="${PICCIE_R2_FILE:-${REPO_ROOT}/piccie-r2.txt}"
TEMPLATE="${REPO_ROOT}/image/files/piccie-r2.txt"

usage() {
  cat <<'EOF'
Usage:
  ./image/copy-r2-to-card.sh [BOOT_VOLUME]
  ./image/copy-r2-to-card.sh --init

Without BOOT_VOLUME, the helper uses the only mounted Raspberry Pi boot volume
under /Volumes. Pass the mount path explicitly if more than one card is present.

The private setup source defaults to ./piccie-r2.txt and is ignored by Git.
EOF
}

if [[ "${1:-}" == "--init" ]]; then
  [[ "$#" -eq 1 ]] || { usage >&2; exit 2; }
  if [[ -e "${SOURCE}" ]]; then
    echo "Private setup file already exists: ${SOURCE}"
    exit 0
  fi
  cp "${TEMPLATE}" "${SOURCE}"
  chmod 600 "${SOURCE}"
  echo "Created private setup file: ${SOURCE}"
  echo "Fill it in, then run ./image/copy-r2-to-card.sh after flashing."
  exit 0
fi

[[ "$#" -le 1 ]] || { usage >&2; exit 2; }
[[ -f "${SOURCE}" ]] || {
  echo "Private setup file not found: ${SOURCE}" >&2
  echo "Create it with: ./image/copy-r2-to-card.sh --init" >&2
  exit 2
}

python3 - "${REPO_ROOT}" "${SOURCE}" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from engine.r2_boot_config import BootConfigError, parse_boot_config, validated_r2

source = Path(sys.argv[2])
try:
    validated_r2(parse_boot_config(source.read_text()))
except (OSError, UnicodeError, BootConfigError) as exc:
    raise SystemExit(f"Piccie setup file is not ready: {exc}")
PY

TARGET="${1:-}"
if [[ -z "${TARGET}" ]]; then
  candidates=()
  for candidate in /Volumes/*; do
    [[ -d "${candidate}" \
        && -f "${candidate}/config.txt" \
        && -f "${candidate}/cmdline.txt" ]] || continue
    candidates+=("${candidate}")
  done
  case "${#candidates[@]}" in
    0)
      echo "No mounted Raspberry Pi boot volume found under /Volumes." >&2
      echo "Reinsert the flashed card or pass its mount path explicitly." >&2
      exit 3
      ;;
    1) TARGET="${candidates[0]}" ;;
    *)
      echo "More than one Raspberry Pi boot volume is mounted:" >&2
      printf '  %s\n' "${candidates[@]}" >&2
      echo "Pass the intended mount path explicitly." >&2
      exit 3
      ;;
  esac
fi

TARGET="${TARGET%/}"
[[ -n "${TARGET}" && "${TARGET}" != "/" && -d "${TARGET}" ]] || {
  echo "Invalid boot volume: ${TARGET:-<empty>}" >&2
  exit 3
}
[[ -f "${TARGET}/config.txt" && -f "${TARGET}/cmdline.txt" ]] || {
  echo "Refusing to copy: ${TARGET} is not a Raspberry Pi boot volume." >&2
  echo "Expected both config.txt and cmdline.txt." >&2
  exit 3
}
[[ -w "${TARGET}" ]] || {
  echo "Boot volume is not writable: ${TARGET}" >&2
  exit 3
}

DESTINATION="${TARGET}/piccie-r2.txt"
TEMP_DESTINATION="${TARGET}/.piccie-r2.txt.tmp.$$"
cleanup() {
  [[ ! -e "${TEMP_DESTINATION}" ]] || rm -f "${TEMP_DESTINATION}"
}
trap cleanup EXIT

cp "${SOURCE}" "${TEMP_DESTINATION}"
mv -f "${TEMP_DESTINATION}" "${DESTINATION}"
sync "${DESTINATION}" 2>/dev/null || sync

echo "Piccie setup settings copied safely to: ${DESTINATION}"
echo "No credential values were printed. Eject the card before removing it."
