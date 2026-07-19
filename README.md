# Piccie

**A complete open-source photobooth you can 3D print, build and own.**

[![CI](https://github.com/BananaStems/piccie/actions/workflows/ci.yml/badge.svg)](https://github.com/BananaStems/piccie/actions/workflows/ci.yml)
[![MIT License](https://img.shields.io/badge/license-MIT-29231e.svg)](LICENSE)
[![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-4%20Model%20B-c45c4a.svg)](docs/hardware.md)

![Piccie — Print the booth. Make the memories.](docs/images/piccie-hero.jpg)

Piccie turns a Raspberry Pi and readily available parts into a touch-first
photobooth for weddings, parties and events. The enclosure is designed to print
on most common 3D printers, the software guides you through setup, and every
photo stays under your control.

Its companion web app turns your phone into a template studio. Design a strip,
preview it on the phone and send it straight to your Piccie when it is ready.

No proprietary controller. No required subscription. No service operated by
this project. Just a booth you can build, repair and make your own.

**[Build your Piccie](#build-your-piccie)** ·
**[Design templates on your phone](#your-template-studio-in-your-pocket)** ·
**[Run it locally](#local-development)**

> **Piccie is preparing for its first hardware release.** The software is in
> active development. Printable files, assembly photography, final fastener
> quantities and the validated bill of materials will be published with the
> first hardware release.

## Piccie in action

| Run an event | Design on your phone |
| --- | --- |
| ![Piccie event admin screen](docs/images/admin.png) | ![Piccie Template Studio on a phone](docs/images/template-studio.png) |

| Welcome guests | Take the photos | Download the strip |
| --- | --- | --- |
| ![Piccie guest start screen](docs/images/tap-to-start.png) | ![Piccie photo capture screen](docs/images/photo-capture.png) | ![Piccie finished strip and download QR code](docs/images/download-strip.png) |

## A DIY photobooth that feels finished

Piccie fills the space between expensive commercial booths and DIY builds that
never quite become an appliance. It combines printable hardware with a focused
touchscreen experience, so guests can use it confidently and organisers can run
an event without reaching for a keyboard.

- **Print the enclosure.** The main body is a single print, supported by three
  smaller functional parts.
- **Build with accessible hardware.** Start with a Raspberry Pi, camera,
  touchscreen and LED ring rather than a proprietary control system.
- **Set up on the booth.** Connect Wi-Fi, add private storage and choose an
  operator PIN from the touchscreen.
- **Design from your phone.** Build custom templates in the companion web app
  and send them directly to the booth when they are ready.
- **Keep control.** Photos, credentials and event data stay on hardware and
  cloud storage you operate.
- **Keep shooting offline.** Capture and strip creation continue when venue
  Wi-Fi drops, then queued uploads resume when the connection returns.
- **Change it.** The software and printable hardware are open for repair,
  adaptation and new ideas.

## One booth, the whole event

### For guests

Guests start a session, take three photos, preview their finished 2×6-inch strip
and scan a QR code to download it. The interface stays focused on the moment;
admin controls remain out of sight.

### For organisers

Create events, set start and end times, choose a strip design, reconnect venue
Wi-Fi and browse every completed strip from the booth. At the end of the event,
generate a private QR code or URL for the host to view and download their
gallery.

### For makers

Create a template without editing files or working on the booth's small screen.
Deploy software updates without reflashing, then run built-in diagnostics and
soak tests before a long event. Piccie remains a project you can understand and
maintain, not a sealed product you have to work around.

## Your template studio, in your pocket

Make every Piccie fit the event. Scan a pairing code on the booth to open the
companion web app on your phone—there is nothing else to install and no desktop
design software to learn.

Add text, choose fonts and colours, arrange layers and bring in celebration
graphics or your own image overlays. Preview the finished strip on your phone
and keep adjusting it without interrupting the booth. When the design is ready,
select **Install on booth** to send it directly to Piccie.

The studio keeps text and shapes in the footer while allowing image overlays to
extend over the bottom quarter of the final photo. This keeps every design
usable without taking away the space meant for guests.

The companion app runs directly from Piccie and keeps the draft on the phone
until it is installed. The phone only needs to be on the same Wi-Fi as the
booth. Font files and their available licence text travel with the template, so
the finished design remains ready when the venue connection does not.

Custom templates are immutable and stored under `/data/templates`. Archiving a
template hides it from new events without changing completed or existing ones.
An archived template can be restored, or permanently deleted once no event
references it.

## Build your Piccie

The [hardware and printing guide](docs/hardware.md) covers the reference parts,
four printed components, material choices, compatibility limits and the details
still being validated.

The first enclosure contains four prints:

- Main body
- LED diffuser
- Raspberry Pi mounting plate
- Back cover

The v1 enclosure and mounting plate are designed for a **Raspberry Pi 4 Model B
with 4 GB of RAM**. A Raspberry Pi 5 may run the software, but it does not fit
the current mounting plate and has not been thermally validated. Supporting it
will require a new mounting design.

## How Piccie works

Photo capture and strip composition happen on the booth. Finished strips upload
to the owner's private Cloudflare R2 bucket while the three source frames remain
local. A self-hosted Cloudflare Worker protects strip and event links before
serving them. Piccie itself receives no photos, event data or credentials.

If the connection drops, the booth keeps the photos and retries pending uploads
later. Guests see a clear offline message instead of waiting on a QR code that
cannot load.

## First boot

There is no credentials file to copy onto the card. Deploy your own gallery
Worker using [`cloud/README.md`](cloud/README.md), then:

1. Flash the appliance image and power on Piccie.
2. Choose a Wi-Fi network on the touchscreen.
3. Select Cloudflare R2 and enter an Object Read & Write token scoped to the
   Worker's bucket, plus the Worker's `workers.dev` URL.
4. Choose the operator PIN and, if wanted, add your computer's SSH public key
   for remote updates.

Piccie checks the storage connection before completing setup. Cloudflare calls
the two S3 credentials **Access Key ID** and **Secret Access Key**. The bucket
stays private; no custom domain or public `r2.dev` access is required.

R2 and Wi-Fi credentials are stored under `/data` with mode `0600`. They are
never copied into the image, runtime release or `config.json`.

## Events and private galleries

Every event has an end date and time. It can be launched for 24 hours after that
time, then Piccie marks it **Concluded** and prevents accidental new sessions.
Editing the end time reopens the event; its gallery remains available.

From an event's Gallery, select **Share event** to create a QR code and private
URL. The host can view each completed strip or download the event as a ZIP.
Creating a new link revokes the old one, and disabling sharing removes access.
Each link is restricted to its own event.

## Build the appliance image

Linux or Docker with about 20 GB free is required. On macOS:

```bash
./image/build-image.sh --docker
```

The result is `.pi-gen/deploy/piccie.img`. The build pins its pi-gen source
revision and Python dependencies. App-only rebuilds can reuse the existing
pi-gen work directory:

```bash
./image/build-image.sh --docker --incremental
```

The image contains a minimal X11/Openbox/Chromium kiosk, the camera engine, a
separate writable `/data` partition, hardware watchdog configuration and a
read-only root filesystem enabled after setup.

## Remote updates

Add your computer's SSH public key during first boot, then deploy code, template
or interface changes without reflashing:

```bash
./scripts/deploy.sh pi@piccie.local
```

Piccie checks the update, switches releases atomically, restarts the engine and
waits for a health check. If that check fails, it restores the previous release.
The factory release and recent rollback versions remain on disk.

Changes to `requirements.txt`, Raspberry Pi OS, libcamera, systemd units or the
partition layout still require a new appliance image. This keeps live updates
small and safely reversible.

## Local development

```bash
PICCIE_CAMERA=mock ./scripts/dev.sh
```

Open <http://127.0.0.1:8080> at a 1024×600 viewport. Use
`PICCIE_CAMERA=webcam` to use the Mac camera. Local development skips first-boot
onboarding and may omit R2; in that case, the result screen uses the local strip
URL.

Local secrets belong in `config/local.json`, which Git ignores. Start from
`config/local.example.json` only when testing R2 locally.

## Testing and long-event reliability

```bash
.venv/bin/python -m pytest -q
bash -n image/*.sh scripts/*.sh
```

The automated suite covers storage migrations, power-loss recovery, R2 keys and
deletion tombstones, camera settings, composition, template installation, event
expiry, admin authentication, persistence and a complete mock-camera capture
flow.

For a powered Raspberry Pi soak test:

```bash
sudo DURATION_MINUTES=480 /data/app/current/scripts/pi_soak.sh
```

The soak test records engine and Chromium memory, process stability,
temperature, throttling, free space, upload backlog and capture latency. It
fails if either the engine or kiosk restarts unexpectedly.

## Operations and recovery

- Runtime data: `/data`
- Active release: `/data/app/current`
- Engine logs: `journalctl -u piccie-engine`
- Diagnostics: `/data/diag`
- Service restart: `sudo systemctl restart piccie-engine`

The hidden corner gesture in party mode requests the operator PIN. A browser or
engine restart resumes the active event instead of exposing the admin screen.

Create `/boot/firmware/piccie-no-readonly` from another computer before booting
to skip root-filesystem lockdown during recovery.

## Help make Piccie better

Piccie should be easy to build, repair and understand. Software fixes, tested
part alternatives, assembly improvements and new mounting plates are welcome.
Read [CONTRIBUTING.md](CONTRIBUTING.md) before making a large change.

The software is MIT licensed. Outfit is distributed under the SIL Open Font
License 1.1; see [third-party notices](THIRD_PARTY_NOTICES.md). Security reports
are described in [SECURITY.md](SECURITY.md).

## Repository artwork

[`docs/images/piccie-social-preview.jpg`](docs/images/piccie-social-preview.jpg)
is sized for GitHub's repository social preview. Upload it under **Settings →
General → Social preview** after forking or importing the project.
