#!/usr/bin/env bash
# Deterministic tests for the early read-only-root verifier and recovery marker.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="${REPO_ROOT}/image/piccie-lockdown.sh"
PASS_COUNT=0

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

setup_fixture() {
  FIXTURE="$(mktemp -d)"
  BOOT="${FIXTURE}/boot"
  RUN="${FIXTURE}/run"
  STATE="${FIXTURE}/mount-state"
  FINDMNT="${FIXTURE}/findmnt"
  MOUNT="${FIXTURE}/mount"
  mkdir -p "${BOOT}" "${RUN}"
  printf '%s\n' ro >"${STATE}"
}

cleanup_fixture() {
  rm -rf "${FIXTURE}"
}

write_fake_commands() {
  {
    printf '%s\n' '#!/usr/bin/env bash'
    printf 'cat %q\n' "${STATE}"
  } >"${FINDMNT}"
  {
    printf '%s\n' '#!/usr/bin/env bash'
    printf 'case "$*" in *remount,rw*) mode=rw ;; *remount,ro*) mode=ro ;; *) exit 2 ;; esac\n'
    printf 'printf "%%s\\\\n" "$mode" >%q\n' "${STATE}"
  } >"${MOUNT}"
  chmod +x "${FINDMNT}" "${MOUNT}"
}

run_verifier() {
  PICCIE_BOOT_DIR="${BOOT}" \
    PICCIE_RUN_DIR="${RUN}" \
    PICCIE_ROOT_MOUNT="${FIXTURE}/root" \
    PICCIE_FINDMNT="${FINDMNT}" \
    PICCIE_MOUNT="${MOUNT}" \
    "${SCRIPT}"
}

test_readonly_root_is_accepted() {
  setup_fixture
  write_fake_commands
  run_verifier >/dev/null
  [[ -e "${RUN}/piccie.root-readonly" ]] || fail "readonly marker missing"
  [[ ! -e "${RUN}/piccie.root-writable" ]] || fail "unexpected writable marker"
  cleanup_fixture
}

test_writable_root_without_marker_is_forced_readonly() {
  setup_fixture
  write_fake_commands
  printf '%s\n' rw >"${STATE}"
  run_verifier >/dev/null
  [[ "$(cat "${STATE}")" == ro ]] || fail "root was not forced read-only"
  [[ -e "${RUN}/piccie.root-readonly" ]] || fail "readonly marker missing"
  cleanup_fixture
}

test_recovery_marker_remounts_and_verifies_writable() {
  setup_fixture
  write_fake_commands
  touch "${BOOT}/piccie-no-readonly"
  run_verifier >/dev/null
  [[ "$(cat "${STATE}")" == rw ]] || fail "recovery did not remount root"
  [[ -e "${RUN}/piccie.root-writable" ]] || fail "writable marker missing"
  cleanup_fixture
}

test_failed_recovery_remount_fails_closed() {
  setup_fixture
  write_fake_commands
  touch "${BOOT}/piccie-no-readonly"
  {
    printf '%s\n' '#!/usr/bin/env bash'
    printf '%s\n' 'exit 1'
  } >"${MOUNT}"
  chmod +x "${MOUNT}"
  if run_verifier >/dev/null 2>&1; then
    fail "failed remount was accepted"
  fi
  [[ ! -e "${RUN}/piccie.root-writable" ]] || fail "unexpected writable marker"
  cleanup_fixture
}

test_failed_readonly_enforcement_fails_closed() {
  setup_fixture
  write_fake_commands
  printf '%s\n' rw >"${STATE}"
  {
    printf '%s\n' '#!/usr/bin/env bash'
    printf '%s\n' 'exit 1'
  } >"${MOUNT}"
  chmod +x "${MOUNT}"
  if run_verifier >/dev/null 2>&1; then
    fail "failed readonly remount was accepted"
  fi
  [[ ! -e "${RUN}/piccie.root-readonly" ]] || fail "unexpected readonly marker"
  cleanup_fixture
}

for test_name in \
  test_readonly_root_is_accepted \
  test_writable_root_without_marker_is_forced_readonly \
  test_recovery_marker_remounts_and_verifies_writable \
  test_failed_recovery_remount_fails_closed \
  test_failed_readonly_enforcement_fails_closed; do
  "${test_name}"
  PASS_COUNT=$((PASS_COUNT + 1))
  echo "ok ${PASS_COUNT} - ${test_name#test_}"
done

echo "PASS: ${PASS_COUNT} read-only-root tests"
