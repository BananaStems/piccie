#!/usr/bin/env bash
# Atomically deploy a code/UI release over SSH. No root-overlay unlock or reflash.
# Usage: ./scripts/deploy.sh pi@<booth-ip>
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${1:?usage: deploy.sh pi@<booth-ip>}"
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
rsync -a engine web templates scripts requirements.txt constraints.txt README.md "${STAGE}/"
printf '%s\n' "${RELEASE_ID}" > "${STAGE}/VERSION"
tar -C "${STAGE}" -czf "${ARCHIVE}" .

ssh "${HOST}" 'mkdir -p /data/app/incoming'
REMOTE="/data/app/incoming/${RELEASE_ID}.tar.gz"
scp "${ARCHIVE}" "${HOST}:${REMOTE}"
ssh -t "${HOST}" "sudo /usr/local/sbin/piccie-update '${REMOTE}'"

echo "Deployed ${RELEASE_ID}."
