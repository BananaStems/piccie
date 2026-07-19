# Contributing to Piccie

Open an issue before large hardware, storage, or image-layout changes. Small bug
fixes can go directly to a pull request.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
PICCIE_CAMERA=mock ./scripts/dev.sh
.venv/bin/python -m pytest -q
```

Keep the application usable at 1024×600 with touch input. Do not add network
dependencies to capture, composition, local gallery viewing, or kiosk boot.

Never commit `config/local.json`, `data/`, R2 credentials, Wi-Fi passwords, SSH
private keys, photo strips, or a filled provisioning file. New dependencies need
a clear Pi 4 benefit and must be pinned in `requirements.txt`.

## Hardware

Open an issue before changing the reference enclosure or its mounting points.
Hardware contributions should include source CAD where possible, exported
print files, printer and material details, slicer settings, tolerances,
photographs and any bill-of-materials changes. Alternate mounting plates should
state exactly which board and revision they were tested with.

Do not submit a printed part under the software licence by assumption. The
project will document a separate hardware-design licence when the first CAD and
STL files are published.

By contributing, you agree that your contribution is licensed under the MIT
License unless a clearly identified hardware-design licence applies to the
files you are contributing.
