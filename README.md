<p align="center">
  <img src="web/assets/piccie-wordmark.svg" alt="piccie" width="220">
</p>

<p align="center"><strong>Make the booth &amp; the memories</strong></p>

[![CI](https://github.com/BananaStems/piccie/actions/workflows/ci.yml/badge.svg)](https://github.com/BananaStems/piccie/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/BananaStems/piccie?display_name=tag&sort=semver)](https://github.com/BananaStems/piccie/releases/latest)
[![MIT License](https://img.shields.io/badge/license-MIT-29231e.svg)](LICENSE)
[![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-4%20Model%20B-c45c4a.svg)](docs/hardware.md)

![Piccie — Make the booth & the memories](docs/images/piccie-hero.jpg)

Piccie combines a Raspberry Pi, touchscreen, camera and printed enclosure into
a self-contained photobooth. Guests take three photos and scan a QR code to
download their strip. Organisers create events, manage galleries and design
templates from a phone connected to the same Wi-Fi.

Piccie is self-hosted. The booth stores its own data and uploads finished strips
directly to a private bucket in your Cloudflare R2 account. It creates
seven-day signed guest links without a Worker, OAuth client, GitHub connection
or public bucket. Optionally, connect your own domain to a second bucket for
short links and smaller QR codes that don't expire.

Guest QR codes point straight to R2 over HTTPS. A guest can use mobile data or
any Wi-Fi; their phone never needs to join the booth's network.

R2 media is organised by event name and date. For example, an event named
“Sarah & James” on 14 June 2026 uses `sarah-james-2026-06-14/`, with finished
strips under `strips/` and the three original captures under `photos/`. Strip
numbers are permanent five-digit identifiers such as
`sarah-james-strip-00001.jpg`. From the event gallery, **Share event** displays
a QR code whose **Download all photos** action transfers one ZIP containing
both folders.

## First-time setup

1. Flash the Piccie image with Raspberry Pi Imager and skip its operating-system
   customisation options.
2. Boot Piccie and choose the Wi-Fi network on its touchscreen. That's the only
   thing you type on the booth.
3. Scan the QR code the booth shows, or open its address on a computer on the
   same Wi-Fi. Paste your Cloudflare R2 details, optionally add a custom domain
   and an SSH public key, choose the operator PIN, and select **Finish setup**.

Cloud storage, the custom domain and the SSH key can be changed later from
**Settings → Operator access → Open on phone or computer**.

## Get started

Choose the guide you need:

1. **[Set up the software](docs/software-setup.md)** — download the ready-made
   image, or build it yourself on macOS, Linux or Windows. Then flash the
   microSD card, prepare Cloudflare R2, complete setup and run the reliability
   test.
2. **[Build the hardware](docs/hardware.md)** — see the current parts list and
   printed components. STL files and full assembly instructions are coming
   soon.

## Piccie in action

| Booth admin | Phone template studio |
| --- | --- |
| ![Piccie event admin screen](docs/images/admin.png) | ![Piccie Template Studio on a phone](docs/images/template-studio.png) |

| Start a session | Take photos | Download the strip |
| --- | --- | --- |
| ![Piccie guest start screen](docs/images/tap-to-start.png) | ![Piccie photo capture screen](docs/images/photo-capture.png) | ![Piccie finished strip and download QR code](docs/images/download-strip.png) |

## Project status

The software is usable and tested on the Raspberry Pi 4 Model B reference
booth. The hardware release is not complete: STL files, final fastener
quantities and photographed assembly instructions still need to be published.

For development and contribution instructions, read
[CONTRIBUTING.md](CONTRIBUTING.md). Piccie is released under the MIT licence;
third-party font licensing is recorded in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
