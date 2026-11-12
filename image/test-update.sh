#!/usr/bin/env bash
# Exercise piccie-update.sh against a fake /data/app: install, failed health
# check -> rollback, and an archive that tries to write outside its release.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$(uname -s)" != "Linux" ]]; then
  echo "test-update: skipped (the updater needs GNU coreutils)"
  exit 0
fi

TMP="$(mktemp -d)"
trap 'rm -rf -- "${TMP}"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

mkdir -p "${TMP}/bin"
printf '#!/bin/sh\nexit 0\n' >"${TMP}/bin/sudo"
printf '#!/bin/sh\n[ "${FAKE_HEALTH:-ok}" = ok ]\n' >"${TMP}/bin/curl"
printf '#!/bin/sh\nexit 0\n' >"${TMP}/bin/pkill"
chmod +x "${TMP}/bin/"*

make_release() { # dir
  mkdir -p "$1/engine" "$1/web" "$1/templates" "$1/scripts"
  : >"$1/engine/__init__.py"
  echo "fastapi" >"$1/requirements.txt"
  echo "pins" >"$1/constraints.txt"
  echo 1 >"$1/VERSION"
  echo 1 >"$1/BUILD"
}

CASE=0
fresh_app() {
  CASE=$((CASE + 1))
  APP="${TMP}/app-${CASE}"
  mkdir -p "${APP}/incoming" "${APP}/releases"
  make_release "${APP}/releases/factory"
  ln -s "${APP}/releases/factory" "${APP}/current"
}

update() { # archive, extra env...
  local archive="$1"; shift
  env PICCIE_UPDATE_APP_DIR="${APP}" PICCIE_UPDATE_PYTHON="$(command -v python3)" \
    PICCIE_UPDATE_HEALTH_TRIES=1 PICCIE_UPDATE_TEST_BIN="${TMP}/bin" "$@" \
    bash "${ROOT}/image/piccie-update.sh" "${archive}"
}

make_release "${TMP}/good"

fresh_app
tar -C "${TMP}/good" -czf "${APP}/incoming/good.tar.gz" .
update "${APP}/incoming/good.tar.gz" >/dev/null
[[ "$(readlink "${APP}/current")" == "${APP}/releases/good" ]] || fail "good release not current"
[[ ! -e "${APP}/rollback" && ! -e /dev/shm/piccie-update ]] || fail "update markers left behind"
[[ ! -e "${APP}/incoming/good.tar.gz" ]] || fail "installed archive not removed"

fresh_app
tar -C "${TMP}/good" -czf "${APP}/incoming/bad.tar.gz" .
status=0
update "${APP}/incoming/bad.tar.gz" FAKE_HEALTH=down >/dev/null 2>&1 || status=$?
[[ "${status}" -eq 4 ]] || fail "unhealthy release exited ${status}, expected 4"
[[ "$(readlink "${APP}/current")" == "${APP}/releases/factory" ]] || fail "no rollback to factory"
[[ ! -e "${APP}/releases/bad" && ! -e "${APP}/incoming/bad.tar.gz" ]] || fail "failed release kept"
[[ ! -e "${APP}/rollback" && ! -e /dev/shm/piccie-update ]] || fail "rollback markers left behind"

fresh_app
python3 - "${APP}/incoming/evil.tar.gz" <<'PY'
import io, sys, tarfile
with tarfile.open(sys.argv[1], "w:gz") as bundle:
    info = tarfile.TarInfo("../escaped.txt")
    info.size = 1
    bundle.addfile(info, io.BytesIO(b"x"))
PY
if update "${APP}/incoming/evil.tar.gz" >/dev/null 2>&1; then fail "unsafe archive accepted"; fi
[[ ! -e "${APP}/releases/escaped.txt" ]] || fail "archive wrote outside its release"
[[ "$(readlink "${APP}/current")" == "${APP}/releases/factory" ]] || fail "unsafe archive changed current"

# Boot after a power cut mid-update: note present, updater not running.
restore() { env PICCIE_UPDATE_APP_DIR="${APP}" PICCIE_UPDATE_FLAG="${TMP}/updating" bash "${ROOT}/image/piccie-restore-release"; }
fresh_app
make_release "${APP}/releases/unproven"
ln -sfn "${APP}/releases/unproven" "${APP}/current"
echo "${APP}/releases/factory" >"${APP}/rollback"
: >"${TMP}/updating"
restore
[[ "$(readlink "${APP}/current")" == "${APP}/releases/unproven" ]] || fail "restored while the updater was running"
rm -f -- "${TMP}/updating"
restore >/dev/null
[[ "$(readlink "${APP}/current")" == "${APP}/releases/factory" ]] || fail "unproven release not rolled back at boot"
[[ ! -e "${APP}/rollback" ]] || fail "rollback note kept after restore"

echo "test-update: ok"
