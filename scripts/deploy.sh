#!/usr/bin/env bash
# Atomically push a code/UI release over SSH. No root-overlay unlock or reflash.
# Usage: ./scripts/deploy.sh <booth-ip|pi@booth-ip>
set -euo pipefail
cd "$(dirname "$0")/.."

TARGET="${1:-}"
if [[ -z "${TARGET}" || "${TARGET}" == "-h" || "${TARGET}" == "--help" ]]; then
  echo "Usage: ./scripts/deploy.sh <booth-ip|pi@booth-ip>"
  echo "Example: ./scripts/deploy.sh 192.168.1.145"
  exit "$([[ -n "${TARGET}" ]] && echo 0 || echo 2)"
fi
if [[ "${TARGET}" == *@* ]]; then
  HOST="${TARGET}"
else
  HOST="pi@${TARGET}"
fi
SSH_ARGS=(
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o StrictHostKeyChecking=accept-new
)

if ! ssh "${SSH_ARGS[@]}" "${HOST}" \
  'test -x /usr/local/sbin/piccie-update && test -d /data/app/current' \
  >/dev/null 2>&1; then
  cat >&2 <<EOF
Could not open key-based SSH access to ${HOST}.

A fresh Piccie image disables password login and installs your SSH key only
when onboarding finishes. If no key was previously installed, this booth
cannot receive an SSH update yet; finish setup locally once or reflash an image
that includes the phone-pairing fix.
EOF
  exit 2
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REV="$(git rev-parse --short HEAD 2>/dev/null || echo local)"
if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
  REV="${REV}-dirty"
fi
RELEASE_ID="${STAMP}-${REV}"
STAGE="$(mktemp -d)"
ARCHIVE_DIR="$(mktemp -d)"
ARCHIVE="${ARCHIVE_DIR}/${RELEASE_ID}.tar.gz"
cleanup() { rm -rf -- "${STAGE}" "${ARCHIVE_DIR}"; }
trap cleanup EXIT

mkdir -p "${STAGE}"
rsync -a engine web templates scripts requirements.txt constraints.txt README.md VERSION "${STAGE}/"
printf '%s\n' "${RELEASE_ID}" > "${STAGE}/BUILD"
# macOS stores extended attributes as AppleDouble `._*` files when creating a
# portable archive. They are not application files and Python correctly rejects
# them as source, so disable metadata copying and exclude the known wrappers.
COPYFILE_DISABLE=1 tar --no-xattrs \
  --exclude='._*' --exclude='.DS_Store' --exclude='__MACOSX' \
  -C "${STAGE}" -czf "${ARCHIVE}" .

ssh "${SSH_ARGS[@]}" "${HOST}" 'mkdir -p /data/app/incoming'
REMOTE="/data/app/incoming/${RELEASE_ID}.tar.gz"
scp "${SSH_ARGS[@]}" "${ARCHIVE}" "${HOST}:${REMOTE}"
ssh "${SSH_ARGS[@]}" "${HOST}" "/usr/local/sbin/piccie-update '${REMOTE}'"
# v1.0.3's installed updater restarts the engine but not the already-open
# browser. Force one clean kiosk relaunch so the newly deployed UI appears
# immediately; openbox starts it again after the engine health check above.
ssh "${SSH_ARGS[@]}" "${HOST}" \
  'pkill -x chromium 2>/dev/null || pkill -x chromium-browser 2>/dev/null || true'

echo "Deployed ${RELEASE_ID}."
