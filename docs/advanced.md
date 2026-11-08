# Advanced

For builders who want to compile the image, update the booth from a computer,
stress-test it, or change the code.

## Build the image yourself

You need Git, Docker and at least 20 GB of free disk space. The first build
takes 30–60 minutes and writes the image to `.pi-gen/deploy/piccie.img`. Flash
it the same way as a downloaded image, choosing that file under **Use custom**.

### macOS

1. Install and start [Docker Desktop for Mac](https://docs.docker.com/desktop/setup/install/mac-install/).
2. In Terminal:

   ```bash
   git clone https://github.com/BananaStems/piccie.git
   cd piccie
   ./image/build-image.sh --docker
   ```

Keep Docker Desktop open until the build finishes.

### Linux

1. Install [Docker Engine](https://docs.docker.com/engine/install/) and check
   that `docker run hello-world` works without `sudo`.
2. Install the build tools (Debian or Ubuntu shown):

   ```bash
   sudo apt update
   sudo apt install -y git rsync python3
   ```

3. Clone and build:

   ```bash
   git clone https://github.com/BananaStems/piccie.git
   cd piccie
   ./image/build-image.sh --docker
   ```

### Windows (WSL 2)

Build inside Ubuntu on WSL 2, not from PowerShell.

1. In PowerShell as Administrator, install Ubuntu, then restart if asked:

   ```powershell
   wsl --install -d Ubuntu
   ```

2. Install [Docker Desktop for Windows](https://docs.docker.com/desktop/features/wsl/).
   Turn on **Use the WSL 2 based engine**, and turn on Ubuntu under **Settings →
   Resources → WSL Integration**.
3. In the Ubuntu terminal, install the tools and build inside your Linux home
   folder (not under `/mnt/c`, which is much slower):

   ```bash
   sudo apt update
   sudo apt install -y git rsync python3
   cd ~
   git clone https://github.com/BananaStems/piccie.git
   cd piccie
   ./image/build-image.sh --docker
   ```

### Faster rebuilds

After one full build, app-only changes can reuse the workspace:

```bash
./image/build-image.sh --docker --incremental
```

To continue a failed build without starting again:

```bash
./image/build-image.sh --docker --continue
```

## Update over Wi-Fi

App and interface updates install over the network without reflashing. You
need an SSH key on the booth.

1. Make a key on your computer, if you don't have one:

   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/piccie_ed25519 -C piccie
   ```

2. Paste the contents of `~/.ssh/piccie_ed25519.pub` (the `.pub` file, never
   the private key) into **SSH public key** on the setup page. To open it
   later: **Settings → Operator access → Open on phone or computer**.
3. Tell SSH to use that key for the booth. Add this to `~/.ssh/config`, using
   your booth's IP address if `piccie.local` doesn't resolve:

   ```text
   Host piccie.local 192.168.1.145
     User pi
     IdentityFile ~/.ssh/piccie_ed25519
     IdentitiesOnly yes
   ```

4. From your copy of the repository, deploy:

   ```bash
   ./scripts/deploy.sh 192.168.1.145
   ```

The update switches over in one step and rolls back by itself if the health
check fails. Password login is disabled, so the key must be added first.

Changes to Raspberry Pi OS, Python dependencies, system services or the card
layout still need a new image. The booth refuses an update whose
`requirements.txt` or `constraints.txt` changed.

## Run the soak test

Run this after assembling the booth, rebuilding the image, or changing
cooling or performance mode. Eight hours is recommended before a first event.
Don't let guests use the booth while it runs.

```bash
ssh pi@piccie.local
sudo DURATION_MINUTES=480 /data/app/current/scripts/pi_soak.sh
```

It runs the full three-photo flow over and over with the real camera, waits for
every upload, downloads each guest link and checks it matches the strip on the
booth. Along the way it watches temperature, throttling, memory, storage, the
upload backlog, Wi-Fi and the kiosk screen. A healthy run ends with
`soak_pass` and prints where the log is.

`SKIP_UPLOAD_CHECK=1` skips the cloud checks for development only. Never use it
to prove a booth is ready for an event.

## Logs and diagnostics

```bash
journalctl -u piccie-engine
```

The last two boot reports are kept in `/data/diag/piccie-boot-diag.txt` and
`/data/diag/piccie-boot-diag.previous.txt`. They include a boot count, power
and throttling warnings, service states and recent logs.

## Develop on your computer

Run Piccie without a Raspberry Pi:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
PICCIE_CAMERA=mock ./scripts/dev.sh
```

Open <http://127.0.0.1:8080> in a 1024×600 window. On a Mac,
`PICCIE_CAMERA=webcam` uses the built-in camera.

Run the checks:

```bash
.venv/bin/python -m pytest -q
bash -n image/*.sh scripts/*.sh
```

Put local credentials in `config/local.json`; Git ignores it. See
[CONTRIBUTING.md](../CONTRIBUTING.md) for code guidelines and releases.
