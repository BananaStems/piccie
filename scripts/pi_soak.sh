#!/usr/bin/env bash
# Run on a Pi against its live appliance. Requires an existing event.
set -Eeuo pipefail

ROUNDS="${1:-24}"
DURATION_MINUTES="${DURATION_MINUTES:-0}"
SESSIONS_PER_ROUND="${SESSIONS_PER_ROUND:-5}"
PAUSE_SECONDS="${PAUSE_SECONDS:-0}"
INTER_ROUND_SECONDS="${INTER_ROUND_SECONDS:-15}"
MAX_ENGINE_MEMORY_MB="${MAX_ENGINE_MEMORY_MB:-${MAX_RSS_MB:-700}}"
MAX_KIOSK_MEMORY_MB="${MAX_KIOSK_MEMORY_MB:-900}"
MAX_ENGINE_GROWTH_MB="${MAX_ENGINE_GROWTH_MB:-256}"
MAX_KIOSK_GROWTH_MB="${MAX_KIOSK_GROWTH_MB:-384}"
MAX_TEMP_C="${MAX_TEMP_C:-80}"
MIN_DISK_FREE_MB="${MIN_DISK_FREE_MB:-500}"
MAX_UPLOAD_BACKLOG="${MAX_UPLOAD_BACKLOG:-0}"
SKIP_UPLOAD_CHECK="${SKIP_UPLOAD_CHECK:-0}"
BASE_URL="${BASE_URL:-http://localhost:8080}"
MIN_PREVIEW_FPS="${MIN_PREVIEW_FPS:-5}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
START_EPOCH="$(date +%s)"
LOG_FILE="${LOG_FILE:-/tmp/piccie-soak-$(date +%Y%m%d-%H%M%S).log}"
SOAK_UPLOAD_ARGS=()
if [[ "${SKIP_UPLOAD_CHECK}" == "1" ]]; then
  SOAK_UPLOAD_ARGS+=(--skip-upload-check)
fi

exec > >(tee -a "${LOG_FILE}") 2>&1

service_memory_mb() {
  local service="$1" cgroup memory_file pid total_kb=0 rss_kb
  cgroup="$(systemctl show --value --property ControlGroup "${service}")"
  memory_file="/sys/fs/cgroup${cgroup}/memory.current"
  if [[ -r "${memory_file}" ]]; then
    echo $(( ($(cat "${memory_file}") + 1048575) / 1048576 ))
    return
  fi
  while read -r pid; do
    [[ -r "/proc/${pid}/status" ]] || continue
    rss_kb="$(awk '/VmRSS:/ { print $2 }' "/proc/${pid}/status")"
    total_kb=$((total_kb + ${rss_kb:-0}))
  done < <(systemctl show --value --property MainPID "${service}")
  echo $(( (total_kb + 1023) / 1024 ))
}

service_restarts() {
  systemctl show --value --property NRestarts "$1"
}

kiosk_pid() {
  pgrep -o -u pi -f 'chromium.*--app=http://localhost:8080' || true
}

kiosk_memory_mb() {
  local total_kb=0 pid rss_kb
  while read -r pid; do
    [[ -r "/proc/${pid}/status" ]] || continue
    rss_kb="$(awk '/VmRSS:/ { print $2 }' "/proc/${pid}/status")"
    total_kb=$((total_kb + ${rss_kb:-0}))
  done < <(pgrep -u pi -f chromium || true)
  echo $(( (total_kb + 1023) / 1024 ))
}

on_error() {
  local exit_code="$1" line="$2"
  echo "soak_failed exit=${exit_code} line=${line}"
  journalctl -u piccie-engine -u lightdm --since "@${START_EPOCH}" --no-pager -n 200 || true
  echo "log=${LOG_FILE}"
  exit "${exit_code}"
}
trap 'on_error $? $LINENO' ERR

systemctl is-active --quiet piccie-engine
KIOSK_PID_START="$(kiosk_pid)"
[[ -n "${KIOSK_PID_START}" ]]

WIFI_DEVICE="$(nmcli -t -f DEVICE,TYPE,STATE device | awk -F: '$2=="wifi" && $3=="connected" {print $1; exit}')"
[[ -n "${WIFI_DEVICE}" ]] || { echo "No active Wi-Fi device" >&2; false; }
WIFI_CONNECTION="$(nmcli -g GENERAL.CONNECTION device show "${WIFI_DEVICE}")"
WIFI_UUID="$(nmcli -g connection.uuid connection show "${WIFI_CONNECTION}")"
WIFI_KEYFILE="$(grep -l -m1 "^uuid=${WIFI_UUID}$" /data/system-connections/*.nmconnection 2>/dev/null | head -1 || true)"
[[ "${WIFI_KEYFILE}" == /data/system-connections/* ]] || {
  echo "Wi-Fi profile is not persisted on /data: ${WIFI_KEYFILE:-missing}" >&2
  false
}

python3 - "${BASE_URL}" "${MIN_PREVIEW_FPS}" <<'PY'
import sys, time, urllib.request
base, minimum = sys.argv[1].rstrip("/"), float(sys.argv[2])
started = time.monotonic()
for _ in range(10):
    with urllib.request.urlopen(f"{base}/api/camera/frame", timeout=10) as response:
        frame = response.read()
    if not (frame.startswith(b"\xff\xd8") and frame.endswith(b"\xff\xd9")):
        raise SystemExit("camera preview returned an invalid JPEG")
fps = 10 / (time.monotonic() - started)
if fps < minimum:
    raise SystemExit(f"camera preview too slow: {fps:.1f} fps < {minimum:.1f} fps")
print(f"preview_fps={fps:.1f}")
PY

ENGINE_RESTARTS_START="$(service_restarts piccie-engine)"
ENGINE_MEMORY_START="$(service_memory_mb piccie-engine)"
KIOSK_MEMORY_START="$(kiosk_memory_mb)"
DEADLINE=0
if (( DURATION_MINUTES > 0 )); then
  DEADLINE=$((START_EPOCH + DURATION_MINUTES * 60))
fi

echo "soak_start rounds=${ROUNDS} duration_minutes=${DURATION_MINUTES} sessions_per_round=${SESSIONS_PER_ROUND}"
echo "baseline engine_memory_mb=${ENGINE_MEMORY_START} kiosk_memory_mb=${KIOSK_MEMORY_START} log=${LOG_FILE}"

round=1
while (( DEADLINE > 0 || round <= ROUNDS )); do
  if (( DEADLINE > 0 && $(date +%s) >= DEADLINE )); then
    break
  fi

  systemctl is-active --quiet piccie-engine
  [[ "$(kiosk_pid)" == "${KIOSK_PID_START}" ]]
  KIOSK_HEARTBEAT_AGE="$(curl -fsS "${BASE_URL}/api/kiosk/status" | python3 -c 'import json,sys; print(json.load(sys.stdin)["heartbeat_age_seconds"])')"
  [[ "${KIOSK_HEARTBEAT_AGE}" != "None" ]] \
    && awk "BEGIN { exit !(${KIOSK_HEARTBEAT_AGE} < 15) }" \
    || { echo "Kiosk page heartbeat is missing or stale" >&2; false; }
  python3 "${REPO_DIR}/scripts/soak_test.py" \
    --base "${BASE_URL}" \
    --sessions "${SESSIONS_PER_ROUND}" \
    --pause-seconds "${PAUSE_SECONDS}" \
    --min-disk-free-mb "${MIN_DISK_FREE_MB}" \
    --max-upload-backlog "${MAX_UPLOAD_BACKLOG}" \
    "${SOAK_UPLOAD_ARGS[@]}"

  ENGINE_MEMORY_MB="$(service_memory_mb piccie-engine)"
  KIOSK_MEMORY_MB="$(kiosk_memory_mb)"
  ENGINE_RESTARTS="$(service_restarts piccie-engine)"
  TEMP_C="$(vcgencmd measure_temp | sed -E "s/.*=([0-9.]+).*/\1/")"
  THROTTLED="$(vcgencmd get_throttled | cut -d= -f2)"
  ELAPSED_MINUTES=$(( ($(date +%s) - START_EPOCH) / 60 ))

  echo "round=${round} elapsed_minutes=${ELAPSED_MINUTES} engine_memory_mb=${ENGINE_MEMORY_MB} kiosk_memory_mb=${KIOSK_MEMORY_MB} temp_c=${TEMP_C} throttled=${THROTTLED}"

  (( ENGINE_MEMORY_MB <= MAX_ENGINE_MEMORY_MB )) || { echo "Engine memory limit exceeded" >&2; false; }
  (( KIOSK_MEMORY_MB <= MAX_KIOSK_MEMORY_MB )) || { echo "Kiosk memory limit exceeded" >&2; false; }
  (( ENGINE_MEMORY_MB - ENGINE_MEMORY_START <= MAX_ENGINE_GROWTH_MB )) || { echo "Engine memory growth limit exceeded" >&2; false; }
  (( KIOSK_MEMORY_MB - KIOSK_MEMORY_START <= MAX_KIOSK_GROWTH_MB )) || { echo "Kiosk memory growth limit exceeded" >&2; false; }
  [[ "${ENGINE_RESTARTS}" == "${ENGINE_RESTARTS_START}" ]] || { echo "Engine restarted during soak" >&2; false; }
  awk "BEGIN { exit !(${TEMP_C} <= ${MAX_TEMP_C}) }" || { echo "Temperature limit exceeded" >&2; false; }
  [[ "${THROTTLED}" == "0x0" ]] || { echo "Pi throttled" >&2; false; }

  round=$((round + 1))
  if (( INTER_ROUND_SECONDS > 0 )); then
    sleep "${INTER_ROUND_SECONDS}"
  fi
done

trap - ERR
echo "soak_pass elapsed_minutes=$(( ($(date +%s) - START_EPOCH) / 60 )) rounds=$((round - 1)) log=${LOG_FILE}"
