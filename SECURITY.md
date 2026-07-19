# Security policy

Report vulnerabilities through GitHub's private security advisory feature. Do
not open a public issue for credentials exposure, authentication bypasses, or
remote-code execution.

Only the latest release receives security fixes. Reports should include the
release, Raspberry Pi OS version, reproduction steps, and impact. Never include
real R2 keys, Wi-Fi passwords, photo strips, or `/data/local.json`.

The engine listens on port 8080 so a paired phone can reach Template Studio.
LAN clients can only load the Studio assets and `/api/studio/*`; capture, event,
Wi-Fi, settings, onboarding, gallery and pairing endpoints remain loopback-only.
Studio installation requires a random in-memory token. It remains valid until
the booth creates a new pairing code or restarts.
