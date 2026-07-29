#!/usr/bin/env bash
# Deterministic tests for Piccie's boot performance profile and reboot handoff.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP_ROOT="$(mktemp -d)"
trap 'result=$?; if [[ ${result} -ne 0 && -f "${OUTPUT:-}" ]]; then cat "${OUTPUT}" >&2; fi; rm -rf "${TMP_ROOT}"; exit "${result}"' EXIT
HELPER="${REPO_ROOT}/image/piccie-performance"
PASS_COUNT=0

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_contains() {
  grep -Fq -- "$2" "$1" || fail "expected '$2' in $1"
}

assert_not_contains() {
  if grep -Fq -- "$2" "$1"; then
    fail "did not expect '$2' in $1"
  fi
}

setup_fixture() {
  FIXTURE="${TMP_ROOT}/fixture-$RANDOM-$RANDOM"
  mkdir -p "${FIXTURE}/bin"
  CONFIG="${FIXTURE}/config.txt"
  MODEL="${FIXTURE}/model"
  ACTIONS="${FIXTURE}/actions"
  TIMER_FAILURE="${FIXTURE}/timer-failure"
  OUTPUT="${FIXTURE}/output"
  printf '# Raspberry Pi boot configuration\ndtoverlay=vc4-kms-v3d\n' >"${CONFIG}"
  printf 'Raspberry Pi 4 Model B Rev 1.5\0' >"${MODEL}"
  : >"${ACTIONS}"

  cat >"${FIXTURE}/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
printf 'systemctl %s\n' "$*" >>"${PICCIE_TEST_ACTIONS}"
if [[ "$*" == "is-active --quiet piccie-performance-reboot.timer" \
  && -e "${PICCIE_TEST_TIMER_FAILURE}" ]]; then
  exit 1
fi
EOF
  chmod +x "${FIXTURE}/bin/systemctl"
}

run_helper() {
  PICCIE_BOOT_CONFIG="${CONFIG}" \
  PICCIE_MODEL_FILE="${MODEL}" \
  PICCIE_SYSTEMCTL="${FIXTURE}/bin/systemctl" \
  PICCIE_TEST_ACTIONS="${ACTIONS}" \
  PICCIE_TEST_TIMER_FAILURE="${TIMER_FAILURE}" \
    bash "${HELPER}" "$@" >"${OUTPUT}" 2>&1
}

test_performance_profile_schedules_verified_named_reboot() {
  setup_fixture
  run_helper pi4 performance

  assert_contains "${CONFIG}" "# Raspberry Pi boot configuration"
  assert_contains "${CONFIG}" "# BEGIN PICCIE PERFORMANCE"
  assert_contains "${CONFIG}" "[pi4]"
  assert_contains "${CONFIG}" "arm_boost=1"
  assert_contains "${ACTIONS}" "systemctl start piccie-performance-reboot.timer"
  assert_contains "${ACTIONS}" "systemctl is-active --quiet piccie-performance-reboot.timer"
  [[ -f "${CONFIG}.piccie-original" ]] || fail "expected original config backup"
}

test_profile_is_idempotent_and_standard_removes_it() {
  setup_fixture
  run_helper pi4 performance
  run_helper pi4 performance
  [[ "$(grep -Fc '# BEGIN PICCIE PERFORMANCE' "${CONFIG}")" -eq 1 ]] \
    || fail "managed performance block was duplicated"

  run_helper pi4 standard
  assert_not_contains "${CONFIG}" "# BEGIN PICCIE PERFORMANCE"
  assert_contains "${CONFIG}" "dtoverlay=vc4-kms-v3d"
}

test_wrong_hardware_fails_without_changes_or_reboot() {
  setup_fixture
  cp "${CONFIG}" "${FIXTURE}/before"
  printf 'Raspberry Pi 5 Model B Rev 1.0\0' >"${MODEL}"
  if run_helper pi4 performance; then
    fail "mismatched hardware unexpectedly succeeded"
  fi
  cmp -s "${FIXTURE}/before" "${CONFIG}" || fail "config changed for mismatched hardware"
  [[ ! -s "${ACTIONS}" ]] || fail "reboot was scheduled for mismatched hardware"
  assert_contains "${OUTPUT}" "does not match detected hardware"
}

test_missing_reboot_timer_fails_safely() {
  setup_fixture
  : >"${TIMER_FAILURE}"
  if run_helper pi4 performance; then
    fail "missing reboot timer unexpectedly succeeded"
  fi
  assert_contains "${OUTPUT}" "reboot timer did not become active"
  assert_contains "${ACTIONS}" "systemctl is-active --quiet piccie-performance-reboot.timer"
}

test_static_reboot_units_are_installed() {
  local setup="${REPO_ROOT}/image/setup-appliance.sh"
  local timer="${REPO_ROOT}/image/piccie-performance-reboot.timer"
  local service="${REPO_ROOT}/image/piccie-performance-reboot.service"

  assert_contains "${setup}" "piccie-performance-reboot.service"
  assert_contains "${setup}" "piccie-performance-reboot.timer"
  assert_contains "${timer}" "OnActiveSec=5s"
  assert_contains "${timer}" "Unit=piccie-performance-reboot.service"
  assert_contains "${service}" "ExecStart=/usr/bin/systemctl --no-block reboot"
}

run_test() {
  local name="$1"
  "$name"
  PASS_COUNT=$((PASS_COUNT + 1))
  echo "ok ${PASS_COUNT} - ${name#test_}"
}

run_test test_performance_profile_schedules_verified_named_reboot
run_test test_profile_is_idempotent_and_standard_removes_it
run_test test_wrong_hardware_fails_without_changes_or_reboot
run_test test_missing_reboot_timer_fails_safely
run_test test_static_reboot_units_are_installed

echo "PASS: ${PASS_COUNT} performance tests"
