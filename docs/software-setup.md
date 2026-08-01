# Software setup

This guide takes Piccie from a download to a working Raspberry Pi. The main
steps are:

1. Download the Piccie image, or build it yourself.
2. Flash the image to a microSD card.
3. Copy the completed one-time `piccie-r2.txt` file to the flashed card's boot
   drive.
4. Start the Raspberry Pi, configure Wi-Fi on its touchscreen and complete
   onboarding.
5. Test the booth, then run the soak test before using it at an event.

## What you need

- A macOS, Linux or Windows computer
- A microSD card reader
- [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
- A genuine **32 GB high-endurance microSD card rated A2/U3**
- The assembled Piccie electronics, or at minimum the Pi, touchscreen and
  camera connected for testing

A high-endurance card is recommended because the booth runs for long periods
and writes photos throughout an event. The image starts with an 8 GB data
partition, then automatically expands it to use the remaining card capacity
during the first startup. Boot and system partitions stay fixed in size.

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
6. Select **Next**, skip all Raspberry Pi OS customisation if it is offered,
   and write the image. Do not configure Wi-Fi in Raspberry Pi Imager; Piccie
   asks for the network and password on its own touchscreen.
7. Wait for verification to finish before removing the card.

Writing the image erases the selected card. Check the storage target carefully.

## 3. Copy your R2 settings to the flashed card

After Raspberry Pi Imager finishes, remove and reinsert the microSD card if its
boot drive is not visible. The drive works on macOS, Windows and Linux. This
step is required after every flash and must be completed before the card's first
boot.

If you build or flash cards from a Piccie source checkout, keep a reusable
private copy at the project root:

```sh
./image/copy-r2-to-card.sh --init
```

Fill in the generated `piccie-r2.txt` once. Git ignores this private file. After
each flash, reinsert the card and run `./image/copy-r2-to-card.sh`. The helper
validates the settings and copies them to the top level of an identifiable
Raspberry Pi boot volume. If auto-detection is ambiguous, pass the volume
explicitly, such as `./image/copy-r2-to-card.sh /Volumes/bootfs`.

If you are not using the helper:

1. Open the blank `piccie-r2.txt` included on the microSD boot drive, or prepare
   a copy on your computer. The file contains the same instructions.
2. Sign in to the [Cloudflare dashboard](https://dash.cloudflare.com/), open
   **Storage & databases → R2**, and create a bucket named `piccie-photos`.
   Leave the bucket private.
3. On the R2 Overview page, find **Account Details → API Tokens** and select
   **Manage**.
4. Create an **Account API token** with **Object Read & Write** permission.
   Restrict the token to only the `piccie-photos` bucket.
5. Copy the Account ID, Access Key ID and Secret Access Key into the matching
   lines in `piccie-r2.txt`. Cloudflare shows the secret only once.
6. Leave `JURISDICTION=default` unless the bucket was explicitly created in the
   EU or FedRAMP jurisdiction.
7. Optional but recommended for remote maintenance: generate a dedicated SSH
   key on your computer, then put only its `.pub` contents after
   `SSH_AUTHORIZED_KEY=`. For example, run
   `ssh-keygen -t ed25519 -f ~/.ssh/piccie_ed25519 -C piccie-deploy`. Keep the
   private file (`~/.ssh/piccie_ed25519`) on your computer and never copy it to
   the card.
8. Save or copy the completed file to the top level of the microSD boot drive,
   replacing the blank template if necessary. Its name must be exactly
   `piccie-r2.txt`.
9. Confirm the file is present on the boot drive, then safely eject the
   microSD card.

The file should contain only these settings after the comment instructions:

```ini
ACCOUNT_ID=your-32-character-account-id
ACCESS_KEY_ID=your-r2-access-key-id
SECRET_ACCESS_KEY=your-r2-secret-access-key
BUCKET_NAME=piccie-photos
JURISDICTION=default
SSH_AUTHORIZED_KEY=ssh-ed25519 AAAA... piccie-deploy
```

Piccie validates and moves these values into the writable data partition before
the engine starts, then removes the readable credential copy from the boot
drive. It refuses incomplete files, unknown settings and degraded temporary
storage. If validation fails, shut down and open `piccie-r2-status.txt` on the
boot drive for the exact field to correct. The token should never grant access
to any other bucket. To rotate credentials later, place a newly completed
`piccie-r2.txt` on the boot drive; the next boot validates and replaces the old
R2 settings atomically.

R2 remains private. Piccie creates signed guest download links that work for
seven days, which is Cloudflare's maximum. Generate a new event link from the
booth if an older event needs to be shared again.

New photos use a readable event layout in R2:

```text
sarah-james-2026-06-14/
├── strips/
│   ├── sarah-james-strip-00001.jpg
│   └── sarah-james-strip-00002.jpg
├── photos/
│   ├── sarah-james-strip-00001-photo-01.jpg
│   ├── sarah-james-strip-00001-photo-02.jpg
│   └── sarah-james-strip-00001-photo-03.jpg
└── download-all.zip
```

The event name and date determine the folder name. Piccie adds `-2`, `-3` and
so on only when two events would otherwise use the same folder. Strip numbers
start at `00001`, never get reused after deletion, and stay attached to the
same session. In the event gallery, choose **Share event** to show a QR code.
Its **Download all photos** button downloads a ZIP containing both `strips/`
and `photos/`; individual guest QR codes still open only that guest's finished
strip. Older UUID-based R2 objects remain valid after an upgrade and are
removed through the existing deletion flow.

Do not add a Wi-Fi name or password to `piccie-r2.txt`. Wi-Fi is a separate
on-device setup step and is stored by the Raspberry Pi's network manager.
The SSH public key is not secret; its matching private key is. After onboarding,
change or remove the four-digit operator PIN and SSH key under **Settings → Operator
access**.

## 4. Complete first boot

Before powering on, connect the touchscreen, camera, active cooling and a
reliable Raspberry Pi power supply. On the first power-on, Piccie expands the
data partition and automatically restarts once before showing setup. Do not
remove power or the card during that restart.

1. Insert the flashed microSD card and power on the booth.
2. On the Piccie touchscreen, choose the Wi-Fi network and enter its password.
3. Confirm that Piccie found and securely imported the R2 file.
4. Choose a four-digit operator PIN.
5. Confirm or add your computer's SSH public key if you want remote updates and
   access to the soak test. A key included in `piccie-r2.txt` is already
   installed; then finish setup.

Piccie uploads a temporary private strip and downloads it through a signed R2
link before completing onboarding. The system partition is protected as
read-only from the first boot, so completing setup does not trigger another
restart. The menu appears immediately after the checks finish.

## 5. Check the booth

Before a long reliability run:

1. Create a test event.
2. Complete several three-photo sessions.
3. Confirm each strip appears in the event gallery.
4. Scan a QR code and download a strip on another device.
5. Disconnect Wi-Fi, take another strip, then reconnect and confirm the queued
   upload completes.
6. Check the camera framing, light, cooling fan and touchscreen response.
7. From the operator menu, select **Power**, confirm **Shut down**, and wait
   until the display is black and the green activity light has stopped before
   disconnecting power. Avoid unplugging a running booth.

## 6. Run the soak test

Run a powered soak test after assembling the booth, changing performance mode,
changing cooling or rebuilding the image. Eight hours is recommended before the
first real event.

From the computer whose SSH key was added during onboarding:

```bash
ssh pi@piccie.local
sudo DURATION_MINUTES=480 /data/app/current/scripts/pi_soak.sh
```

The test uses the booth's configured camera, completes the full three-photo
flow, waits for every R2 upload, downloads each guest link and byte-compares it
with the local strip. It also verifies that the active Wi-Fi profile is stored
on `/data`, measures the real settings-preview frame rate, watches the kiosk
page heartbeat, and checks the engine, Chromium, memory growth, temperature,
throttling, free storage, upload backlog and process restarts. A healthy run
ends with `soak_pass` and prints the log path. Do not use the booth for guests
while this test is running.

For development without R2 only, set `SKIP_UPLOAD_CHECK=1`. Never use that
option for an event-readiness run.

If the test fails, review the printed reason and the engine log before relying
on the booth at an event:

```bash
journalctl -u piccie-engine
```

The latest two persistent boot snapshots are kept in
`/data/diag/piccie-boot-diag.txt` and
`/data/diag/piccie-boot-diag.previous.txt`. They include a persistent boot
count, reset/throttling evidence, service state and recent logs.

## Updating an installed booth

If an SSH key was added during onboarding, most app and interface changes can
be installed without reflashing:

```bash
./scripts/deploy.sh 192.168.1.145
```

The update switches releases atomically and rolls back if its health check
fails. Changes to Raspberry Pi OS, Python dependencies, system services or the
partition layout still require a rebuilt image and a reflash. SSH password
login is disabled: the public key must already have been added during
onboarding.

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
