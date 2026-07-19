# Software setup

This guide takes Piccie from a download to a working Raspberry Pi. The main
steps are:

1. Download the Piccie image, or build it yourself.
2. Flash the image to a microSD card.
3. Start the Raspberry Pi and complete onboarding.
4. Test the booth, then run the soak test before using it at an event.

## What you need

- A macOS, Linux or Windows computer
- A microSD card reader
- [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
- A genuine **32 GB high-endurance microSD card rated A2/U3**
- The assembled Piccie electronics, or at minimum the Pi, touchscreen and
  camera connected for testing

A high-endurance card is recommended because the booth runs for long periods
and writes photos throughout an event. The current image reserves a fixed 8 GB
data partition, so a larger card does not currently provide more photo storage.

## 1. Get the image

### Download the ready-made image

Open the [latest Piccie release](https://github.com/BananaStems/piccie/releases/latest)
and download the file ending in `-arm64.img.xz`. You do not need to extract it;
Raspberry Pi Imager can flash the compressed file directly.

Each release also includes a `.sha256` file. You can use it to verify that the
download is complete and unchanged before flashing.

### Build it yourself

Building from source requires Git, Docker and at least 20 GB of free disk
space. It is useful if you want to inspect or change everything included in the
image.

On macOS or Linux, clone the repository before following the platform steps:

```bash
git clone https://github.com/BananaStems/piccie.git
cd piccie
```

Windows users should install WSL first and clone the repository inside Ubuntu,
as described in the Windows section below.

The first build usually takes 30–60 minutes. The finished image is written to
`.pi-gen/deploy/`, normally as `.pi-gen/deploy/piccie.img`.

### macOS

1. Install and start [Docker Desktop for Mac](https://docs.docker.com/desktop/setup/install/mac-install/).
2. Open Terminal in the cloned `piccie` folder.
3. Run:

   ```bash
   ./image/build-image.sh --docker
   ```

Docker Desktop must remain open until the build finishes.

### Linux

1. Install [Docker Engine](https://docs.docker.com/engine/install/) or Docker
   Desktop for your distribution.
2. Install the local build tools. On Debian or Ubuntu:

   ```bash
   sudo apt update
   sudo apt install -y git rsync python3
   ```

3. Confirm `docker run hello-world` works without `sudo`.
4. From the cloned `piccie` folder, run:

   ```bash
   ./image/build-image.sh --docker
   ```

### Windows with WSL 2

Piccie builds inside Ubuntu on WSL 2. Do not run the build script directly from
PowerShell or Command Prompt.

1. Open PowerShell as Administrator and install Ubuntu:

   ```powershell
   wsl --install -d Ubuntu
   ```

2. Restart Windows if prompted, then open Ubuntu once to finish its setup.
3. Install [Docker Desktop for Windows](https://docs.docker.com/desktop/features/wsl/).
4. In Docker Desktop, enable **Use the WSL 2 based engine**, then enable Ubuntu
   under **Settings → Resources → WSL Integration**.
5. In the Ubuntu terminal, install the build tools:

   ```bash
   sudo apt update
   sudo apt install -y git rsync python3
   ```

6. Clone Piccie inside the Linux home folder, not under `/mnt/c`:

   ```bash
   cd ~
   git clone https://github.com/BananaStems/piccie.git
   cd piccie
   ./image/build-image.sh --docker
   ```

Keeping the repository in the WSL filesystem avoids the slower Windows/Linux
file-sharing path during the image build.

### Rebuilding after a change

After one successful full build, app-only changes can use the existing build
workspace:

```bash
./image/build-image.sh --docker --incremental
```

To continue a failed full build without starting again:

```bash
./image/build-image.sh --docker --continue
```

## 2. Flash the microSD card

1. Install and open [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. Insert the microSD card into your computer.
3. Select **Raspberry Pi 4** as the device.
4. Under the operating-system choice, select **Use custom** and choose either
   the downloaded `.img.xz` file or the generated `piccie.img` file from
   `.pi-gen/deploy/`.
5. Select the microSD card as the storage target.
6. Select **Next**, skip Raspberry Pi OS customisation if it is offered, and
   write the image.
7. Wait for verification to finish before removing the card.

Writing the image erases the selected card. Check the storage target carefully.

## 3. Complete first boot

Before powering on, connect the touchscreen, camera, active cooling and a
reliable Raspberry Pi power supply.

1. Insert the flashed microSD card and power on the booth.
2. Choose the Wi-Fi network used for initial setup.
3. Select Cloudflare R2 as the storage provider.
4. Enter the bucket credentials and Worker URL created with the
   [self-hosted gallery guide](../cloud/README.md).
5. Choose an operator PIN.
6. Add your computer's SSH public key if you want remote updates and access to
   the soak test.

Piccie verifies the storage connection before completing onboarding. The
bucket remains private and no custom domain is required.

## 4. Check the booth

Before a long reliability run:

1. Create a test event.
2. Complete several three-photo sessions.
3. Confirm each strip appears in the event gallery.
4. Scan a QR code and download a strip on another device.
5. Disconnect Wi-Fi, take another strip, then reconnect and confirm the queued
   upload completes.
6. Check the camera framing, light, cooling fan and touchscreen response.

## 5. Run the soak test

Run a powered soak test after assembling the booth, changing performance mode,
changing cooling or rebuilding the image. Eight hours is recommended before the
first real event.

From the computer whose SSH key was added during onboarding:

```bash
ssh pi@piccie.local
sudo DURATION_MINUTES=480 /data/app/current/scripts/pi_soak.sh
```

The test repeatedly creates mock sessions while checking the engine, Chromium,
memory growth, temperature, throttling, free storage, upload backlog and process
restarts. A healthy run ends with `soak_pass` and prints the log path. Do not use
the booth for guests while this test is running.

If the test fails, review the printed reason and the engine log before relying
on the booth at an event:

```bash
journalctl -u piccie-engine
```

## Updating an installed booth

If an SSH key was added during onboarding, most app and interface changes can
be installed without reflashing:

```bash
./scripts/deploy.sh pi@piccie.local
```

The update switches releases atomically and rolls back if its health check
fails. Changes to Raspberry Pi OS, Python dependencies, system services or the
partition layout still require a rebuilt image and a reflash.

## Local development

To run Piccie on a development computer without building an image:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
PICCIE_CAMERA=mock ./scripts/dev.sh
```

Open <http://127.0.0.1:8080> at a 1024×600 viewport. On macOS,
`PICCIE_CAMERA=webcam` uses the Mac camera.

Run the automated checks with:

```bash
.venv/bin/python -m pytest -q
bash -n image/*.sh scripts/*.sh
```

Local credentials belong in `config/local.json`, which Git ignores.
