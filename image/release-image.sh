#!/usr/bin/env bash
# Reproducible release gate: clean tagged source, tests, image, QEMU, checksum.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"
PUBLISH=0
[[ "${1:-}" == "--publish" ]] && { PUBLISH=1; shift; }
[[ "$#" -eq 0 ]] || { echo "usage: $0 [--publish]" >&2; exit 2; }

VERSION="$(tr -d '[:space:]' <VERSION)"
TAG="v${VERSION}"
[[ -z "$(git status --porcelain)" ]] || {
  echo "release requires a clean worktree" >&2
  exit 2
}
git tag --points-at HEAD | grep -Fxq "${TAG}" || {
  echo "HEAD must carry tag ${TAG}" >&2
  exit 2
}

python3 -m pytest -q
node --test web/test/*.test.mjs
bash image/test-grow-data.sh
bash image/test-readonly-root.sh
bash image/test-performance.sh
bash image/test-shutdown.sh
bash image/test-appliance.sh

shopt -s nullglob
IMAGES=(.pi-gen/deploy/*-piccie.img .pi-gen/deploy/piccie.img)
((${#IMAGES[@]})) || { echo "built image not found" >&2; exit 3; }
IMAGE="$(ls -t "${IMAGES[@]}" | head -1)"
ARCHIVE=".pi-gen/deploy/piccie-${TAG}-arm64.img.xz"
xz -T0 -f -k -c "${IMAGE}" >"${ARCHIVE}"
if command -v sha256sum >/dev/null; then
  sha256sum "${ARCHIVE}" >"${ARCHIVE}.sha256"
else
  shasum -a 256 "${ARCHIVE}" >"${ARCHIVE}.sha256"
fi

if [[ "${PUBLISH}" -eq 1 ]]; then
  command -v gh >/dev/null || { echo "gh is required to publish" >&2; exit 4; }
  gh release view "${TAG}" >/dev/null
  gh release upload "${TAG}" "${ARCHIVE}" "${ARCHIVE}.sha256" --clobber
fi
echo "release ready: ${ARCHIVE}"
