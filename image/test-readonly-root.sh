#!/usr/bin/env bash
# Deterministic tests for the early read-only-root verifier and recovery marker.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="${REPO_ROOT}/image/piccie-lockdown.sh"
SETUP="${REPO_ROOT}/image/setup-appliance.sh"
SMOKE="${REPO_ROOT}/image/smoke-qemu.sh"
LIGHTDM_CONFIG="${REPO_ROOT}/image/pi-gen/stage2-piccie/files/lightdm/50-piccie.conf"
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

test_readonly_runtime_mountpoints_are_prepared() {
  grep -Fq "install -d -m 0755 /var/cache/lightdm" "${SETUP}" \
    || fail "LightDM cache mountpoint is not created before lockdown"
  grep -Fq "install -d -m 0755 /var/lib/systemd/linger" "${SETUP}" \
    || fail "systemd-logind state directory is not created before lockdown"
  grep -Fq "piccie-lightdm.conf" "${SETUP}" \
    || fail "LightDM writable directories are not provisioned by tmpfiles"
}

test_dns_uses_networkmanager_runtime_state() {
  grep -Fq "ln -s /run/NetworkManager/resolv.conf /etc/resolv.conf" "${SETUP}" \
    || fail "DNS does not use NetworkManager's writable runtime resolver file"
  grep -Fq "rc-manager=symlink" "${REPO_ROOT}/image/files/nm-keyfile-path.conf" \
    || fail "NetworkManager is not configured to manage the resolver symlink"
}

test_lightdm_authority_uses_writable_runtime_state() {
  awk '
    /^\[/ { section = $0 }
    section == "[LightDM]" && $0 == "user-authority-in-system-dir=true" { found = 1 }
    END { exit !found }
  ' "${LIGHTDM_CONFIG}" \
    || fail "LightDM user authority is not configured in the global LightDM section"
}

test_distro_root_growth_is_disabled() {
  grep -Fq "systemd-growfs-root.service rpi-resize.service" "${SETUP}" \
    || fail "distro root-growth services are not masked"
}

test_ssh_identity_uses_data() {
  grep -Fq "HostKey /data/ssh/ssh_host_ed25519_key" "${REPO_ROOT}/image/files/sshd-piccie.conf" \
    || fail "sshd does not use a persistent host identity on /data"
  grep -Fq "ssh-keygen -q -t ed25519" "${REPO_ROOT}/image/piccie-firstboot-datapart.sh" \
    || fail "first boot does not generate the persistent SSH host identity"
  grep -Fq "ssh_host_ed25519_key.pub" "${REPO_ROOT}/image/piccie-firstboot-datapart.sh" \
    || fail "first boot does not validate both halves of the SSH host identity"
  grep -Fq "After=piccie-firstboot-datapart.service" "${REPO_ROOT}/image/files/ssh-piccie.conf" \
    || fail "ssh.service is not ordered after first-boot data setup"
}

test_smoke_gate_rejects_local_filesystem_failures() {
  grep -Fq 'grep -q "Reached target local-fs.target"' "${SMOKE}" \
    || fail "smoke test does not require local-fs.target"
  grep -Fq "Dependency failed for local-fs.target" "${SMOKE}" \
    || fail "smoke test does not reject local-fs.target failure"
  grep -Fq "Cannot open access to console" "${SMOKE}" \
    || fail "smoke test does not reject locked emergency console"
}

for test_name in \
  test_readonly_root_is_accepted \
  test_writable_root_without_marker_is_forced_readonly \
  test_recovery_marker_remounts_and_verifies_writable \
  test_failed_recovery_remount_fails_closed \
  test_failed_readonly_enforcement_fails_closed \
  test_readonly_runtime_mountpoints_are_prepared \
  test_dns_uses_networkmanager_runtime_state \
  test_lightdm_authority_uses_writable_runtime_state \
  test_distro_root_growth_is_disabled \
  test_ssh_identity_uses_data \
  test_smoke_gate_rejects_local_filesystem_failures; do
  "${test_name}"
  PASS_COUNT=$((PASS_COUNT + 1))
  echo "ok ${PASS_COUNT} - ${test_name#test_}"
done

echo "PASS: ${PASS_COUNT} read-only-root tests"
