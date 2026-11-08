#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
STATE="${TMP}/last-clock"
MARKER="${TMP}/synchronized"
ACTIONS="${TMP}/actions"

cat >"${TMP}/date" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "-u +%s") echo 1700000000 ;;
  "-u -d "*" +%s") echo 1800000000 ;;
  "-u -s "*) printf '%s\n' "$*" >>"${PICCIE_TEST_ACTIONS}" ;;
  *) exit 2 ;;
esac
EOF
cat >"${TMP}/curl" <<'EOF'
#!/usr/bin/env bash
printf 'HTTP/2 200\r\nDate: Fri, 15 Jan 2027 08:00:00 GMT\r\n\r\n'
EOF
chmod +x "${TMP}/date" "${TMP}/curl"
printf '1750000000\n' >"${STATE}"

PICCIE_ALLOW_NON_ROOT_TEST=1 \
PICCIE_CLOCK_STATE="${STATE}" \
PICCIE_CLOCK_MARKER="${MARKER}" \
PICCIE_DATE="${TMP}/date" \
PICCIE_CURL="${TMP}/curl" \
PICCIE_TEST_ACTIONS="${ACTIONS}" \
  bash "${ROOT}/image/piccie-clock-sync"

[[ "$(cat "${STATE}")" == "1800000000" ]]
[[ -e "${MARKER}" ]]
grep -Fxq -- "-u -s @1750000000" "${ACTIONS}"
grep -Fxq -- "-u -s @1800000000" "${ACTIONS}"
echo "PASS: persistent and trusted HTTPS clock recovery"
