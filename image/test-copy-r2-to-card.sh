#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "${TMP_ROOT}"' EXIT

VALID="${TMP_ROOT}/valid.txt"
INVALID="${TMP_ROOT}/invalid.txt"
VOLUME="${TMP_ROOT}/boot"
WRONG_VOLUME="${TMP_ROOT}/wrong"
mkdir -p "${VOLUME}" "${WRONG_VOLUME}"
touch "${VOLUME}/config.txt" "${VOLUME}/cmdline.txt"

cat >"${VALID}" <<'EOF'
ACCOUNT_ID=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
ACCESS_KEY_ID=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
SECRET_ACCESS_KEY=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
BUCKET_NAME=piccie-photos
JURISDICTION=default
SSH_AUTHORIZED_KEY=ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAID7xmMhz1/FKQxq0ML54lMRKG/th7+UEMiaq7HLEJHNC test-deploy
EOF

cat >"${INVALID}" <<'EOF'
ACCOUNT_ID=
ACCESS_KEY_ID=
SECRET_ACCESS_KEY=
BUCKET_NAME=piccie-photos
JURISDICTION=default
SSH_AUTHORIZED_KEY=
EOF

PICCIE_R2_FILE="${VALID}" "${REPO_ROOT}/image/copy-r2-to-card.sh" "${VOLUME}" >/dev/null
cmp -s "${VALID}" "${VOLUME}/piccie-r2.txt" \
  || { echo "FAIL: copied R2 file differs from its validated source" >&2; exit 1; }

if PICCIE_R2_FILE="${INVALID}" \
    "${REPO_ROOT}/image/copy-r2-to-card.sh" "${VOLUME}" >/dev/null 2>&1; then
  echo "FAIL: incomplete R2 settings were accepted" >&2
  exit 1
fi

if PICCIE_R2_FILE="${VALID}" \
    "${REPO_ROOT}/image/copy-r2-to-card.sh" "${WRONG_VOLUME}" >/dev/null 2>&1; then
  echo "FAIL: non-boot target was accepted" >&2
  exit 1
fi

echo "PASS: private R2 copy validates credentials and the target boot volume"
