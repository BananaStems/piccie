#!/usr/bin/env bash
# Build a flashable Piccie SD image with pi-gen.
#
# Linux (native):     ./image/build-image.sh
# macOS / Docker:     ./image/build-image.sh --docker
# Rebuild app only:   ./image/build-image.sh --docker --incremental   (~2–5 min)
# Resume after error: ./image/build-image.sh --docker --continue
#
# Output: .pi-gen/deploy/piccie.img (flash with Raspberry Pi Imager or balenaEtcher)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PI_GEN_DIR="${PI_GEN_DIR:-${REPO_ROOT}/.pi-gen}"
PI_GEN_REPO="${PI_GEN_REPO:-https://github.com/RPi-Distro/pi-gen.git}"
PI_GEN_BRANCH="${PI_GEN_BRANCH:-arm64}"
PI_GEN_COMMIT="${PI_GEN_COMMIT:-4ad56cc850fa60adcc7f07dc15879bc95cc1d281}"
USE_DOCKER=0
INCREMENTAL=0
CONTINUE_BUILD=0

for arg in "$@"; do
  case "${arg}" in
    --docker) USE_DOCKER=1 ;;
    --incremental) INCREMENTAL=1 ;;
    --continue) CONTINUE_BUILD=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: ./image/build-image.sh [--docker] [--incremental] [--continue]

  --docker       Build inside Docker (required on macOS)
  --incremental  Skip stages 0–2; rebuild only stage2-piccie (~2–5 min).
                 Requires a previous full build in .pi-gen/work/
  --continue     Resume a failed build without starting from scratch

Speed tips:
  - Use --incremental while iterating on Piccie code
  - Native Linux build is faster than Docker-on-Mac (no QEMU overhead)
  - Set APT_PROXY=http://host:3142 for apt-cacher-ng on your LAN
  - Put WORK_DIR on fast storage: WORK_DIR=/mnt/nvme/pi-gen-work ./image/build-image.sh
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: ${arg}" >&2
      exit 1
      ;;
  esac
done

if [[ "${USE_DOCKER}" -eq 0 && "$(uname -s)" == "Darwin" ]]; then
  echo "On macOS, image builds run inside Docker (--docker)."
  USE_DOCKER=1
fi

if [[ ! -f "${PI_GEN_DIR}/build.sh" ]]; then
  echo "Cloning pi-gen into ${PI_GEN_DIR}..."
  git clone --depth 1 --branch "${PI_GEN_BRANCH}" "${PI_GEN_REPO}" "${PI_GEN_DIR}"
fi
if [[ "$(git -C "${PI_GEN_DIR}" rev-parse HEAD)" != "${PI_GEN_COMMIT}" ]]; then
  echo "Checking out pinned pi-gen revision ${PI_GEN_COMMIT}..."
  git -C "${PI_GEN_DIR}" fetch --depth 1 origin "${PI_GEN_COMMIT}"
  git -C "${PI_GEN_DIR}" checkout --detach "${PI_GEN_COMMIT}"
fi

echo "Syncing Piccie source into pi-gen workspace..."
rm -rf "${PI_GEN_DIR}/piccie-src"
install -d "${PI_GEN_DIR}/piccie-src/config"
rsync -a \
  "${REPO_ROOT}/engine" \
  "${REPO_ROOT}/web" \
  "${REPO_ROOT}/templates" \
  "${REPO_ROOT}/image" \
  "${REPO_ROOT}/scripts" \
  "${REPO_ROOT}/requirements.txt" \
  "${REPO_ROOT}/constraints.txt" \
  "${REPO_ROOT}/VERSION" \
  "${REPO_ROOT}/README.md" \
  "${REPO_ROOT}/LICENSE" \
  "${REPO_ROOT}/THIRD_PARTY_NOTICES.md" \
  "${PI_GEN_DIR}/piccie-src/"
printf '%s\n' "$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo image)" \
  > "${PI_GEN_DIR}/piccie-src/BUILD"
install -m 644 "${REPO_ROOT}/config/local.example.json" \
  "${PI_GEN_DIR}/piccie-src/config/local.example.json"

echo "Applying Piccie pi-gen overrides (boot config + 3-partition layout)..."
cp "${REPO_ROOT}/image/pigen/cmdline.txt" "${PI_GEN_DIR}/stage1/00-boot-files/files/cmdline.txt"
cp "${REPO_ROOT}/image/pigen/config.txt"  "${PI_GEN_DIR}/stage1/00-boot-files/files/config.txt"
cp "${REPO_ROOT}/image/pigen/fstab"       "${PI_GEN_DIR}/stage1/01-sys-tweaks/files/fstab"
cp "${REPO_ROOT}/image/pigen/export-prerun.sh" "${PI_GEN_DIR}/export-image/prerun.sh"
cp "${REPO_ROOT}/image/pigen/export-04-set-partuuid.sh" "${PI_GEN_DIR}/export-image/04-set-partuuid/00-run.sh"
chmod +x "${PI_GEN_DIR}/export-image/prerun.sh" "${PI_GEN_DIR}/export-image/04-set-partuuid/00-run.sh"

echo "Patching pi-gen apt keyring (debian-archive-keyring required before first apt update)..."
KEYRING_FILE="${PI_GEN_DIR}/stage0/00-configure-apt/files/debian-archive-keyring.pgp"
APT_RUN="${PI_GEN_DIR}/stage0/00-configure-apt/00-run.sh"
if [[ ! -f "${KEYRING_FILE}" ]]; then
  docker run --rm debian:trixie cat /usr/share/keyrings/debian-archive-keyring.pgp > "${KEYRING_FILE}"
fi
if ! grep -q 'debian-archive-keyring.pgp' "${APT_RUN}"; then
  python3 - "${APT_RUN}" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text()
needle = 'install -m 644 files/raspberrypi-archive-keyring.pgp "${ROOTFS_DIR}/usr/share/keyrings/"'
insert = needle + '\ninstall -m 644 files/debian-archive-keyring.pgp "${ROOTFS_DIR}/usr/share/keyrings/"'
if needle in text:
    path.write_text(text.replace(needle, insert, 1))
PY
fi

echo "Installing custom pi-gen stage..."
rm -rf "${PI_GEN_DIR}/stage2-piccie"
cp -a "${REPO_ROOT}/image/pi-gen/stage2-piccie" "${PI_GEN_DIR}/stage2-piccie"
chmod +x "${PI_GEN_DIR}/stage2-piccie/01-piccie/00-run.sh"
touch "${PI_GEN_DIR}/stage2-piccie/EXPORT_IMAGE"
install -d "${PI_GEN_DIR}/stage2-piccie/files/lightdm"

cp "${REPO_ROOT}/image/pi-gen/config.template" "${PI_GEN_DIR}/config"

# Lite base + our kiosk stage only — skip desktop (stage3) and stock stage4/5 images.
touch "${PI_GEN_DIR}/stage3/SKIP" "${PI_GEN_DIR}/stage4/SKIP" "${PI_GEN_DIR}/stage5/SKIP"
touch "${PI_GEN_DIR}/stage2/SKIP_IMAGES" "${PI_GEN_DIR}/stage2/SKIP_NOOBS"

if [[ "${INCREMENTAL}" -eq 1 ]]; then
  WORK_BASE=""
  for candidate in \
    "${PI_GEN_DIR}/work/piccie/stage2" \
    "${PI_GEN_DIR}/work/stage2"; do
    if [[ -d "${candidate}" ]]; then
      WORK_BASE="${candidate}"
      break
    fi
  done
  if [[ -z "${WORK_BASE}" ]]; then
    echo "No previous build found under ${PI_GEN_DIR}/work/" >&2
    echo "Run a full build first (without --incremental)." >&2
    exit 1
  fi
  echo "Incremental build: skipping stages 0–2, rebuilding stage2-piccie only..."
  touch "${PI_GEN_DIR}/stage0/SKIP" "${PI_GEN_DIR}/stage1/SKIP" "${PI_GEN_DIR}/stage2/SKIP"
else
  rm -f "${PI_GEN_DIR}/stage0/SKIP" "${PI_GEN_DIR}/stage1/SKIP" "${PI_GEN_DIR}/stage2/SKIP"
fi

if [[ "${INCREMENTAL}" -eq 1 ]]; then
  echo "Building Piccie image (incremental, usually a few minutes)..."
elif [[ "${CONTINUE_BUILD}" -eq 1 ]]; then
  echo "Resuming Piccie image build..."
else
  echo "Building Piccie image (full build, 30–60 minutes the first time)..."
fi

cd "${PI_GEN_DIR}"

BUILD_ENV=()
if [[ "${CONTINUE_BUILD}" -eq 1 ]]; then
  BUILD_ENV+=(CONTINUE=1)
fi
if [[ "${INCREMENTAL}" -eq 1 || "${CONTINUE_BUILD}" -eq 1 ]]; then
  BUILD_ENV+=(CLEAN=1)
fi
if [[ "${USE_DOCKER}" -eq 1 && ( "${INCREMENTAL}" -eq 1 || "${CONTINUE_BUILD}" -eq 1 ) ]]; then
  BUILD_ENV+=(PRESERVE_CONTAINER=1)
fi

if [[ "${USE_DOCKER}" -eq 1 ]]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required for --docker builds." >&2
    exit 1
  fi
  if [[ ! -f "${PI_GEN_DIR}/build-docker.sh" ]]; then
    echo "pi-gen build-docker.sh not found in ${PI_GEN_DIR}" >&2
    exit 1
  fi
  if ((${#BUILD_ENV[@]} > 0)); then
    env "${BUILD_ENV[@]}" ./build-docker.sh
  else
    ./build-docker.sh
  fi
else
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "Re-running build with sudo..."
    exec sudo -E env PI_GEN_DIR="${PI_GEN_DIR}" REPO_ROOT="${REPO_ROOT}" INCREMENTAL="${INCREMENTAL}" CONTINUE_BUILD="${CONTINUE_BUILD}" "$0" "$@"
  fi
  if ((${#BUILD_ENV[@]} > 0)); then
    env "${BUILD_ENV[@]}" ./build.sh
  else
    ./build.sh
  fi
fi

IMG_PATH="${PI_GEN_DIR}/deploy/piccie.img"
if [[ ! -f "${IMG_PATH}" ]]; then
  IMG_PATH="$(ls -t "${PI_GEN_DIR}"/deploy/*-piccie.img 2>/dev/null | head -1 || true)"
fi
if [[ -n "${IMG_PATH}" && -f "${IMG_PATH}" ]]; then
  echo ""
  echo "Build complete."
  echo "Flash this file to your SD card:"
  echo "  ${IMG_PATH}"
  echo ""
  echo "First boot opens Wi-Fi and storage setup on the booth touchscreen."
else
  echo "Build finished; check ${PI_GEN_DIR}/deploy/ for output images."
fi
