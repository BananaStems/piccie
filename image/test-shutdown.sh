#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
ACTIONS="${TMP}/actions"

cat >"${TMP}/systemctl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"${PICCIE_TEST_ACTIONS}"
[[ "${PICCIE_TEST_FAIL:-0}" != "1" || "$*" != "is-active --quiet piccie-poweroff.timer" ]]
EOF
chmod +x "${TMP}/systemctl"

PICCIE_ALLOW_NON_ROOT_TEST=1 \
PICCIE_SYSTEMCTL="${TMP}/systemctl" \
PICCIE_TEST_ACTIONS="${ACTIONS}" \
  bash "${ROOT}/image/piccie-shutdown"
grep -Fxq "start piccie-poweroff.timer" "${ACTIONS}"
grep -Fxq "is-active --quiet piccie-poweroff.timer" "${ACTIONS}"

if PICCIE_ALLOW_NON_ROOT_TEST=1 \
  PICCIE_SYSTEMCTL="${TMP}/systemctl" \
  PICCIE_TEST_ACTIONS="${ACTIONS}" \
  PICCIE_TEST_FAIL=1 \
  bash "${ROOT}/image/piccie-shutdown" 2>/dev/null; then
  echo "FAIL: inactive timer reported success" >&2
  exit 1
fi

grep -Fq "piccie-poweroff.service" "${ROOT}/image/setup-appliance.sh"
grep -Fq "OnActiveSec=3s" "${ROOT}/image/piccie-poweroff.timer"
grep -Fq "/usr/bin/systemctl --no-block poweroff" "${ROOT}/image/piccie-poweroff.service"
echo "PASS: safe shutdown uses a verified static timer"
