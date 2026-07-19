#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt -r requirements-dev.txt

export PICCIE_DATA_DIR="${PICCIE_DATA_DIR:-./data}"
export PICCIE_CAMERA="${PICCIE_CAMERA:-webcam}"

echo "Piccie dev server: http://localhost:8080"
echo "Camera mode: ${PICCIE_CAMERA} (set PICCIE_CAMERA=mock for placeholders)"
echo "Tip: resize browser to 1024×600 or use Chrome DevTools device mode"
echo "Reset setup: rm -rf ${PICCIE_DATA_DIR}"
echo ""

.venv/bin/python -m engine.main
