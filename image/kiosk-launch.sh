#!/usr/bin/env bash
set -euo pipefail

URL="${PICCIE_KIOSK_URL:-http://localhost:8080}"
case "${URL}" in
  *\?*) APP_URL="${URL}&kiosk" ;;
  *) APP_URL="${URL}?kiosk" ;;
esac
CHROMIUM="$(command -v chromium-browser || command -v chromium || true)"

if [[ -z "${CHROMIUM}" ]]; then
  echo "Chromium not found" >&2
  exit 1
fi

# Wait for the engine before opening the kiosk UI. If it never answers, exit
# non-zero so the openbox autostart relaunch loop retries — otherwise Chromium
# opens straight onto a connection-error page and parks there forever (an --app
# window never navigates away), leaving a dead screen until a power cycle.
ENGINE_UP=false
for _ in $(seq 1 60); do
  if curl -sf "${URL}/api/status" >/dev/null 2>&1; then
    ENGINE_UP=true
    break
  fi
  sleep 1
done
if [[ "${ENGINE_UP}" != "true" ]]; then
  echo "engine did not come up within 60s; exiting so autostart relaunches" >&2
  exit 1
fi

COMMON_FLAGS=(
  --noerrdialogs
  --disable-infobars
  --disable-session-crashed-bubble
  --disable-dev-shm-usage
  --disable-restore-session-state
  --no-first-run
  --js-flags=--max-old-space-size=128
  --ozone-platform=x11
  --start-maximized
  --kiosk
  "--app=${APP_URL}"
)

# Dedicated profile dir; clear stale single-instance locks left by an unclean
# power-off (otherwise Chromium refuses to start and the screen stays black).
PROFILE="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/piccie-chromium"
mkdir -p "${PROFILE}"
rm -f "${PROFILE}/SingletonLock" "${PROFILE}/SingletonSocket" "${PROFILE}/SingletonCookie"
COMMON_FLAGS+=( "--user-data-dir=${PROFILE}" )

if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
  exec "${CHROMIUM}" "${COMMON_FLAGS[@]}" --ozone-platform=wayland
fi

export DISPLAY="${DISPLAY:-:0}"
exec "${CHROMIUM}" "${COMMON_FLAGS[@]}"
