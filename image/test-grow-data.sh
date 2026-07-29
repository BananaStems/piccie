#!/usr/bin/env bash
# Deterministic tests for piccie-grow-data's two-boot state machine. The fake
# block stack models kernel sysfs separately from the on-disk partition table,
# which is the safety property that requires the controlled reboot.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "${TMP_ROOT}"' EXIT

PICCIE_GROW_DATA_MOUNT="${TMP_ROOT}/data"
PICCIE_GROW_DATA_SYS_BLOCK="${TMP_ROOT}/sys"
PICCIE_GROW_DATA_DEGRADED_MARKER="${TMP_ROOT}/run/piccie.degraded"
PICCIE_GROW_DATA_FAILURE_MARKER="${TMP_ROOT}/run/piccie-data-grow.failed"
source "${REPO_ROOT}/image/piccie-grow-data.sh"

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

assert_equals() {
  [[ "$1" == "$2" ]] || fail "expected '$2', got '$1'"
}

setup_fixture() {
  FIXTURE="${TMP_ROOT}/fixture-$RANDOM-$RANDOM"
  mkdir -p \
    "${FIXTURE}/sys/fakediskp3" \
    "${FIXTURE}/data" \
    "${FIXTURE}/run"
  SYS_BLOCK="${FIXTURE}/sys"
  DATA_MOUNT="${FIXTURE}/data"
  DEGRADED_MARKER="${FIXTURE}/run/piccie.degraded"
  FAILURE_MARKER="${FIXTURE}/run/piccie-data-grow.failed"
  TABLE_SIZE_FILE="${FIXTURE}/table-size"
  FS_BLOCKS_FILE="${FIXTURE}/fs-blocks"
  ACTIONS_FILE="${FIXTURE}/actions"
  SFDISK_INPUT_FILE="${FIXTURE}/sfdisk-input"
  OUTPUT_FILE="${FIXTURE}/output"
  MOUNT_STATE_FILE="${FIXTURE}/mount-state"
  EXTRA_PARTITION_FILE="${FIXTURE}/extra-partition"
  WRITE_STUCK_FILE="${FIXTURE}/write-stuck"
  RESIZE_STUCK_FILE="${FIXTURE}/resize-stuck"
  LABEL_FILE="${FIXTURE}/label"

  printf '3\n' >"${SYS_BLOCK}/fakediskp3/partition"
  printf '128\n' >"${SYS_BLOCK}/fakediskp3/start"
  printf '128\n' >"${SYS_BLOCK}/fakediskp3/size"
  printf '128\n' >"${TABLE_SIZE_FILE}"
  printf '16\n' >"${FS_BLOCKS_FILE}"
  printf 'unmounted\n' >"${MOUNT_STATE_FILE}"
  printf 'data\n' >"${LABEL_FILE}"
  : >"${ACTIONS_FILE}"
}

canonicalize_device() {
  printf '%s\n' "$1"
}

is_block_device() {
  return 0
}

mountpoint() {
  [[ "$(<"${MOUNT_STATE_FILE}")" != "unmounted" ]]
}

findmnt() {
  local arg
  for arg in "$@"; do
    if [[ "${arg}" == "--fstab" ]]; then
      printf '/dev/fakediskp3\n'
      return
    fi
  done

  for arg in "$@"; do
    if [[ "${arg}" == "FSTYPE" ]]; then
      [[ "$(<"${MOUNT_STATE_FILE}")" == "tmpfs" ]] && printf 'tmpfs\n' || printf 'ext4\n'
      return
    fi
    if [[ "${arg}" == "SOURCE" ]]; then
      [[ "$(<"${MOUNT_STATE_FILE}")" == "tmpfs" ]] && printf 'tmpfs\n' || printf '/dev/fakediskp3\n'
      return
    fi
  done
  return 1
}

lsblk() {
  local output="" arg
  while [[ "$#" -gt 0 ]]; do
    arg="$1"
    shift
    if [[ "${arg}" == "--output" ]]; then
      output="$1"
      shift
    fi
  done
  case "${output}" in
    KNAME) printf 'fakediskp3\n' ;;
    TYPE) printf 'part\n' ;;
    PKNAME) printf 'fakedisk\n' ;;
    *) return 1 ;;
  esac
}

blkid() {
  local field="" arg
  while [[ "$#" -gt 0 ]]; do
    arg="$1"
    shift
    if [[ "${arg}" == "-s" ]]; then
      field="$1"
      shift
    fi
  done
  case "${field}" in
    PTTYPE) printf 'dos\n' ;;
    TYPE) printf 'ext4\n' ;;
    LABEL) cat "${LABEL_FILE}" ;;
    *) return 1 ;;
  esac
}

blockdev() {
  [[ "$1" == "--getsize64" ]] || return 1
  printf '%s\n' "$((640 * 512))"
}

sfdisk() {
  local arg json=0 mutate=0
  for arg in "$@"; do
    [[ "${arg}" == "--json" ]] && json=1
    [[ "${arg}" == "-N" ]] && mutate=1
  done

  if [[ "${json}" -eq 1 ]]; then
    local extra=""
    if [[ -e "${EXTRA_PARTITION_FILE}" ]]; then
      extra=', {"node": "/dev/fakediskp4", "start": 620, "size": 20, "type": "83"}'
    fi
    printf '{"partitiontable":{"label":"dos","sectorsize":512,"partitions":['
    printf '{"node":"/dev/fakediskp1","start":1,"size":31,"type":"c"},'
    printf '{"node":"/dev/fakediskp2","start":32,"size":96,"type":"83"},'
    printf '{"node":"/dev/fakediskp3","start":128,"size":%s,"type":"83"}%s]}}\n' \
      "$(<"${TABLE_SIZE_FILE}")" "${extra}"
    return
  fi

  if [[ "${mutate}" -eq 1 ]]; then
    cat >"${SFDISK_INPUT_FILE}"
    printf 'sfdisk\n' >>"${ACTIONS_FILE}"
    if [[ ! -e "${WRITE_STUCK_FILE}" ]]; then
      printf '512\n' >"${TABLE_SIZE_FILE}"
    fi
    return
  fi
  return 1
}

sync() {
  :
}

tune2fs() {
  printf 'Block count:              %s\n' "$(<"${FS_BLOCKS_FILE}")"
  printf 'Block size:               4096\n'
}

e2fsck() {
  printf 'e2fsck\n' >>"${ACTIONS_FILE}"
  return 0
}

resize2fs() {
  printf 'resize2fs\n' >>"${ACTIONS_FILE}"
  if [[ ! -e "${RESIZE_STUCK_FILE}" ]]; then
    printf '64\n' >"${FS_BLOCKS_FILE}"
  fi
}

systemctl() {
  printf 'reboot\n' >>"${ACTIONS_FILE}"
}

test_partition_growth_requests_one_reboot() {
  setup_fixture
  main >"${OUTPUT_FILE}" 2>&1
  assert_equals "$(<"${TABLE_SIZE_FILE}")" "512"
  assert_equals "$(<"${FS_BLOCKS_FILE}")" "16"
  assert_equals "$(tr '\n' ' ' <"${ACTIONS_FILE}")" "sfdisk reboot "
  assert_equals "$(<"${SFDISK_INPUT_FILE}")" "start=128, size=+"
  assert_contains "${OUTPUT_FILE}" "partition table updated; rebooting once"
}

test_second_boot_grows_and_verifies_ext4() {
  setup_fixture
  printf '512\n' >"${TABLE_SIZE_FILE}"
  printf '512\n' >"${SYS_BLOCK}/fakediskp3/size"
  main >"${OUTPUT_FILE}" 2>&1
  assert_equals "$(<"${FS_BLOCKS_FILE}")" "64"
  assert_equals "$(tr '\n' ' ' <"${ACTIONS_FILE}")" "e2fsck resize2fs e2fsck "
  assert_contains "${OUTPUT_FILE}" "filesystem expansion verified"
}

test_full_device_is_idempotent() {
  setup_fixture
  printf '512\n' >"${TABLE_SIZE_FILE}"
  printf '512\n' >"${SYS_BLOCK}/fakediskp3/size"
  printf '64\n' >"${FS_BLOCKS_FILE}"
  main >"${OUTPUT_FILE}" 2>&1
  [[ ! -s "${ACTIONS_FILE}" ]] || fail "idempotent run performed a mutating action"
  assert_contains "${OUTPUT_FILE}" "already use the full device"
}

test_one_ext4_block_short_is_grown() {
  setup_fixture
  printf '512\n' >"${TABLE_SIZE_FILE}"
  printf '512\n' >"${SYS_BLOCK}/fakediskp3/size"
  printf '63\n' >"${FS_BLOCKS_FILE}"
  main >"${OUTPUT_FILE}" 2>&1
  assert_equals "$(<"${FS_BLOCKS_FILE}")" "64"
  assert_contains "${ACTIONS_FILE}" "resize2fs"
}

test_wrong_partition_number_fails_without_changes() {
  setup_fixture
  printf '2\n' >"${SYS_BLOCK}/fakediskp3/partition"
  if (main) >"${OUTPUT_FILE}" 2>&1; then
    fail "wrong partition number unexpectedly succeeded"
  fi
  [[ ! -s "${ACTIONS_FILE}" ]] || fail "wrong partition number changed state"
  assert_contains "${OUTPUT_FILE}" "expected the dedicated p3"
}

test_nonfinal_partition_fails_without_changes() {
  setup_fixture
  touch "${EXTRA_PARTITION_FILE}"
  if (main) >"${OUTPUT_FILE}" 2>&1; then
    fail "non-final p3 unexpectedly succeeded"
  fi
  [[ ! -s "${ACTIONS_FILE}" ]] || fail "non-final p3 changed state"
  assert_contains "${OUTPUT_FILE}" "expected exactly boot, root, and data"
}

test_unexpected_filesystem_label_fails_without_changes() {
  setup_fixture
  printf 'other\n' >"${LABEL_FILE}"
  if (main) >"${OUTPUT_FILE}" 2>&1; then
    fail "unexpected label succeeded"
  fi
  [[ ! -s "${ACTIONS_FILE}" ]] || fail "unexpected label changed state"
  assert_contains "${OUTPUT_FILE}" "expected data filesystem label"
}

test_degraded_mode_is_untouched() {
  setup_fixture
  touch "${DEGRADED_MARKER}"
  main >"${OUTPUT_FILE}" 2>&1
  [[ ! -s "${ACTIONS_FILE}" ]] || fail "degraded mode changed state"
  assert_contains "${OUTPUT_FILE}" "degraded/tmpfs mode; refusing to resize"
}

test_tmpfs_mount_is_untouched() {
  setup_fixture
  printf 'tmpfs\n' >"${MOUNT_STATE_FILE}"
  main >"${OUTPUT_FILE}" 2>&1
  [[ ! -s "${ACTIONS_FILE}" ]] || fail "tmpfs mode changed state"
  assert_contains "${OUTPUT_FILE}" "tmpfs fallback; refusing to resize"
}

test_real_mount_fails_without_changes() {
  setup_fixture
  printf 'ext4\n' >"${MOUNT_STATE_FILE}"
  if (main) >"${OUTPUT_FILE}" 2>&1; then
    fail "mounted filesystem unexpectedly succeeded"
  fi
  [[ ! -s "${ACTIONS_FILE}" ]] || fail "mounted filesystem changed state"
  assert_contains "${OUTPUT_FILE}" "already mounted; offline growth must run before data.mount"
}

test_stale_kernel_geometry_fails_without_changes() {
  setup_fixture
  printf '512\n' >"${TABLE_SIZE_FILE}"
  if (main) >"${OUTPUT_FILE}" 2>&1; then
    fail "stale kernel geometry unexpectedly succeeded"
  fi
  [[ ! -s "${ACTIONS_FILE}" ]] || fail "stale kernel geometry changed state"
  assert_contains "${OUTPUT_FILE}" "kernel and on-disk geometry disagree"
}

test_partition_write_must_verify_before_reboot() {
  setup_fixture
  touch "${WRITE_STUCK_FILE}"
  if (main) >"${OUTPUT_FILE}" 2>&1; then
    fail "unverified partition write unexpectedly succeeded"
  fi
  assert_equals "$(tr '\n' ' ' <"${ACTIONS_FILE}")" "sfdisk "
  assert_contains "${OUTPUT_FILE}" "partition-table verification failed"
  assert_not_contains "${ACTIONS_FILE}" "reboot"
}

test_failure_is_recorded_for_fallback_gate() {
  setup_fixture
  printf '2\n' >"${SYS_BLOCK}/fakediskp3/partition"
  if (run_main) >"${OUTPUT_FILE}" 2>&1; then
    fail "failed growth unexpectedly succeeded"
  fi
  [[ -e "${FAILURE_MARKER}" ]] || fail "growth failure marker was not recorded"
}

test_success_clears_stale_failure_marker() {
  setup_fixture
  printf '512\n' >"${TABLE_SIZE_FILE}"
  printf '512\n' >"${SYS_BLOCK}/fakediskp3/size"
  printf '64\n' >"${FS_BLOCKS_FILE}"
  touch "${FAILURE_MARKER}"
  (run_main) >"${OUTPUT_FILE}" 2>&1
  [[ ! -e "${FAILURE_MARKER}" ]] || fail "successful growth check left a stale failure marker"
}

test_filesystem_resize_must_verify() {
  setup_fixture
  printf '512\n' >"${TABLE_SIZE_FILE}"
  printf '512\n' >"${SYS_BLOCK}/fakediskp3/size"
  touch "${RESIZE_STUCK_FILE}"
  if (main) >"${OUTPUT_FILE}" 2>&1; then
    fail "unverified filesystem resize unexpectedly succeeded"
  fi
  assert_contains "${OUTPUT_FILE}" "ext4 verification failed"
  assert_not_contains "${ACTIONS_FILE}" "reboot"
}

test_systemd_ordering_keeps_growth_offline() {
  local grow_unit="${REPO_ROOT}/image/piccie-grow-data.service"
  local fallback_unit="${REPO_ROOT}/image/data-fallback.service"
  local seed_unit="${REPO_ROOT}/image/piccie-firstboot-datapart.service"
  local engine_unit="${REPO_ROOT}/image/piccie-engine.service"
  local qemu_runner="${REPO_ROOT}/image/run-qemu.sh"

  assert_contains "${grow_unit}" "Before=local-fs-pre.target data.mount"
  assert_contains "${grow_unit}" "WantedBy=sysinit.target"
  assert_contains "${fallback_unit}" "After=piccie-grow-data.service local-fs.target data.mount"
  assert_contains "${fallback_unit}" "/run/piccie-data-grow.failed"
  assert_contains "${seed_unit}" "Requires=data-fallback.service"
  assert_contains "${engine_unit}" "Requires=data-fallback.service"
  assert_contains "${engine_unit}" "Wants=systemd-timesyncd.service"
  assert_contains "${qemu_runner}" 'root=${ROOT_DEV} ro rootwait'
  assert_not_contains "${qemu_runner}" 'root=${ROOT_DEV} rw rootwait'
  assert_contains "${qemu_runner}" 'qemu-img create -q -f qcow2 -F raw -b "${IMG}" "${QEMU_IMG}"'
  assert_contains "${qemu_runner}" 'format=qcow2,if=sd'
  assert_contains "${qemu_runner}" 'systemd.log_target=kmsg'
  assert_contains "${qemu_runner}" 'systemd.journald.forward_to_console=1'
  assert_contains "${REPO_ROOT}/image/smoke-qemu.sh" 'reboot: Restarting system'
}

test_root_is_readonly_without_runtime_boot_mutation() {
  local setup="${REPO_ROOT}/image/setup-appliance.sh"
  local service="${REPO_ROOT}/image/piccie-lockdown.service"
  local script="${REPO_ROOT}/image/piccie-lockdown.sh"
  local cmdline="${REPO_ROOT}/image/pigen/cmdline.txt"
  local fstab="${REPO_ROOT}/image/pigen/fstab"
  local final_stage="${REPO_ROOT}/image/pi-gen/stage2-piccie/01-piccie/00-run.sh"

  assert_contains "${setup}" "piccie-lockdown data-fallback"
  assert_contains "${service}" "WantedBy=local-fs.target"
  assert_contains "${service}" "RequiresMountsFor=/boot/firmware"
  assert_contains "${script}" "piccie-no-readonly"
  assert_contains "${script}" "remount,rw"
  assert_contains "${script}" "remount,ro"
  assert_contains "${setup}" "systemctl mask systemd-remount-fs.service"
  assert_contains "${cmdline}" "rootfstype=ext4 ro "
  assert_contains "${fstab}" "ext4    ro,noatime"
  assert_contains "${final_stage}" "piccie-src/image/pigen/cmdline.txt"
  assert_contains "${final_stage}" "piccie-src/image/pigen/fstab"
  assert_not_contains "${script}" "raspi-config nonint"
  assert_not_contains "${script}" "overlayroot="
  assert_not_contains "${script}" "systemctl reboot"
  assert_not_contains "${setup}" "piccie-lockdown.path"
}

test_safe_shutdown_uses_narrow_privileged_helper() {
  local setup="${REPO_ROOT}/image/setup-appliance.sh"
  local helper="${REPO_ROOT}/image/piccie-shutdown"
  local sudoers="${REPO_ROOT}/image/files/piccie-shutdown-sudoers"
  local poweroff_service="${REPO_ROOT}/image/piccie-poweroff.service"
  local poweroff_timer="${REPO_ROOT}/image/piccie-poweroff.timer"

  assert_contains "${setup}" "install -m 755 \"\${INSTALL_DIR}/image/piccie-shutdown\" /usr/local/sbin/piccie-shutdown"
  assert_contains "${setup}" "visudo -cf /etc/sudoers.d/piccie-shutdown"
  assert_contains "${helper}" "sync"
  assert_contains "${helper}" "start \"\${UNIT}.timer\""
  assert_contains "${helper}" "is-active --quiet \"\${UNIT}.timer\""
  assert_contains "${poweroff_service}" "/usr/bin/systemctl --no-block poweroff"
  assert_contains "${poweroff_timer}" "OnActiveSec=3s"
  assert_contains "${sudoers}" "NOPASSWD: /usr/local/sbin/piccie-shutdown"
  assert_not_contains "${sudoers}" "/usr/bin/systemctl"
}

test_r2_boot_file_is_imported_before_engine_start() {
  local setup="${REPO_ROOT}/image/setup-appliance.sh"
  local engine_unit="${REPO_ROOT}/image/piccie-engine.service"
  local template="${REPO_ROOT}/image/files/piccie-r2.txt"

  assert_contains "${setup}" "/boot/firmware/piccie-r2.txt"
  assert_contains "${setup}" "! -e /boot/firmware/piccie-r2.txt"
  assert_contains "${engine_unit}" "ExecStartPre=+/opt/piccie/venv/bin/python -m engine.r2_boot_config"
  assert_contains "${template}" "ACCOUNT_ID="
  assert_contains "${template}" "ACCESS_KEY_ID="
  assert_contains "${template}" "SECRET_ACCESS_KEY="
  assert_contains "${template}" "BUCKET_NAME=piccie-photos"
  assert_contains "${template}" "Object Read & Write"
  assert_not_contains "${template}" "PUBLIC_URL="
}

test_recovery_and_release_contracts_are_baked_into_image() {
  local setup="${REPO_ROOT}/image/setup-appliance.sh"
  local smoke="${REPO_ROOT}/image/smoke-qemu.sh"
  local bootdiag="${REPO_ROOT}/image/bootdiag.sh"
  local updater_sudoers="${REPO_ROOT}/image/files/piccie-restart-engine-sudoers"

  assert_contains "${setup}" "piccie-clock-sync"
  assert_contains "${setup}" "piccie-restart-engine"
  assert_contains "${setup}" "piccie-poweroff.timer"
  assert_contains "${smoke}" "/healthz"
  assert_contains "${bootdiag}" "piccie-boot-diag.previous.txt"
  assert_contains "${bootdiag}" "piccie-boot-count"
  assert_contains "${updater_sudoers}" "NOPASSWD: /usr/local/sbin/piccie-restart-engine"
  assert_not_contains "${updater_sudoers}" "piccie-update"
}

run_test() {
  local name="$1"
  "$name"
  PASS_COUNT=$((PASS_COUNT + 1))
  echo "ok ${PASS_COUNT} - ${name#test_}"
}

run_test test_partition_growth_requests_one_reboot
run_test test_second_boot_grows_and_verifies_ext4
run_test test_full_device_is_idempotent
run_test test_one_ext4_block_short_is_grown
run_test test_wrong_partition_number_fails_without_changes
run_test test_nonfinal_partition_fails_without_changes
run_test test_unexpected_filesystem_label_fails_without_changes
run_test test_degraded_mode_is_untouched
run_test test_tmpfs_mount_is_untouched
run_test test_real_mount_fails_without_changes
run_test test_stale_kernel_geometry_fails_without_changes
run_test test_partition_write_must_verify_before_reboot
run_test test_failure_is_recorded_for_fallback_gate
run_test test_success_clears_stale_failure_marker
run_test test_filesystem_resize_must_verify
run_test test_systemd_ordering_keeps_growth_offline
run_test test_root_is_readonly_without_runtime_boot_mutation
run_test test_safe_shutdown_uses_narrow_privileged_helper
run_test test_r2_boot_file_is_imported_before_engine_start
run_test test_recovery_and_release_contracts_are_baked_into_image

echo "PASS: ${PASS_COUNT} piccie-grow-data tests"
