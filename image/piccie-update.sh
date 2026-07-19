#!/usr/bin/env bash
# Install a code-only release from /data/app/incoming and roll back on failure.
set -euo pipefail

ARCHIVE="${1:-}"
APP_DIR=/data/app
INCOMING="${APP_DIR}/incoming"
RELEASES="${APP_DIR}/releases"
CURRENT="${APP_DIR}/current"
PYTHON=/opt/piccie/venv/bin/python

case "${ARCHIVE}" in
  "${INCOMING}"/*.tar.gz) ;;
  *) echo "update archive must be under ${INCOMING}" >&2; exit 2 ;;
esac
[[ -f "${ARCHIVE}" ]] || { echo "update archive not found" >&2; exit 2; }

RELEASE_ID="$(basename "${ARCHIVE}" .tar.gz)"
case "${RELEASE_ID}" in *[!A-Za-z0-9._-]*) echo "invalid release name" >&2; exit 2;; esac
DEST="${RELEASES}/${RELEASE_ID}"
TMP="${DEST}.new"
[[ ! -e "${DEST}" && ! -e "${TMP}" ]] || { echo "release already exists" >&2; exit 2; }
mkdir -p "${TMP}"

cleanup() { rm -rf -- "${TMP}"; }
trap cleanup EXIT

python3 - "${ARCHIVE}" "${TMP}" <<'PY'
import pathlib, sys, tarfile
archive, destination = sys.argv[1:]
root = pathlib.Path(destination).resolve()
with tarfile.open(archive, "r:gz") as bundle:
    for member in bundle.getmembers():
        target = (root / member.name).resolve()
        if root not in target.parents and target != root:
            raise SystemExit(f"unsafe archive path: {member.name}")
        if member.issym() or member.islnk() or member.isdev():
            raise SystemExit(f"unsupported archive entry: {member.name}")
    bundle.extractall(root)
PY

for required in engine web templates scripts requirements.txt constraints.txt VERSION; do
  [[ -e "${TMP}/${required}" ]] || { echo "release missing ${required}" >&2; exit 2; }
done

# The immutable image owns the Python environment. Code-only updates are safe and
# rollbackable; a dependency change requires a versioned appliance image.
if ! cmp -s "${CURRENT}/requirements.txt" "${TMP}/requirements.txt"; then
  echo "dependencies changed; install a new appliance image for this release" >&2
  exit 3
fi
if ! cmp -s "${CURRENT}/constraints.txt" "${TMP}/constraints.txt"; then
  echo "dependency constraints changed; install a new appliance image for this release" >&2
  exit 3
fi

"${PYTHON}" -m compileall -q "${TMP}/engine"
mv "${TMP}" "${DEST}"
trap - EXIT

PREVIOUS="$(readlink -f "${CURRENT}")"
rm -f -- "${APP_DIR}/current.next"
ln -s "${DEST}" "${APP_DIR}/current.next"
mv -Tf "${APP_DIR}/current.next" "${CURRENT}"
systemctl restart piccie-engine.service

HEALTHY=false
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8080/api/status >/dev/null 2>&1; then
    HEALTHY=true
    break
  fi
  sleep 1
done

if [[ "${HEALTHY}" != true ]]; then
  echo "release failed health check; rolling back to $(basename "${PREVIOUS}")" >&2
  rm -f -- "${APP_DIR}/current.next"
  ln -s "${PREVIOUS}" "${APP_DIR}/current.next"
  mv -Tf "${APP_DIR}/current.next" "${CURRENT}"
  systemctl restart piccie-engine.service
  exit 4
fi

rm -f -- "${ARCHIVE}"
echo "installed ${RELEASE_ID}"

# Keep the current release plus the three most recent fallbacks. Factory is tiny
# insurance and is never pruned.
mapfile -t OLD_RELEASES < <(
  find "${RELEASES}" -mindepth 1 -maxdepth 1 -type d ! -name factory -printf '%T@ %p\n' |
    sort -nr | tail -n +5 | cut -d' ' -f2-
)
for old in "${OLD_RELEASES[@]}"; do
  [[ "$(readlink -f "${CURRENT}")" == "${old}" ]] || rm -rf -- "${old}"
done
