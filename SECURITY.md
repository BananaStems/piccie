# Security policy

Report vulnerabilities through GitHub's private security advisory feature. Do
not open a public issue for credentials exposure, authentication bypasses, or
remote-code execution.

Only the latest release receives security fixes. Reports should include the
release, Raspberry Pi OS version, reproduction steps, and impact. Never include
real R2 keys, Wi-Fi passwords, photo strips, or `/data/local.json`.

The image includes a documented `piccie-r2.txt` template on the FAT boot
partition. Users complete or copy this file onto the boot drive after flashing
and before first boot. Once completed, it contains a live secret. Piccie imports
it into protected `/data/local.json` and deletes the boot copy before starting
the engine. Because deleted FAT data may be forensically recoverable, keep the
card inside the booth and use an Object Read & Write token restricted to only
the Piccie bucket. Rotate the token if the card is lost or reused. Wi-Fi
credentials are entered on Piccie's touchscreen and must never be added to the
R2 file.

The engine listens on port 8080 so a paired phone can reach Template Studio.
LAN clients can only load the Studio assets and `/api/studio/*`; capture, event,
Wi-Fi, settings, onboarding, gallery and pairing endpoints remain loopback-only.
Studio installation requires a random in-memory token. It remains valid until
the booth creates a new pairing code or restarts.
