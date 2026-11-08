# Security policy

Report vulnerabilities through GitHub's private security advisory feature. Do
not open a public issue for credentials exposure, authentication bypasses, or
remote-code execution.

Only the latest release receives security fixes. Reports should include the
release, Raspberry Pi OS version, reproduction steps, and impact. Never include
real R2 keys, Wi-Fi passwords, photo strips, or `/data/local.json`.

R2 credentials are entered once on Piccie's setup page and stored only in
mode-0600 `/data/local.json`; the page never reads the secret back. Use an
Object Read & Write token restricted to the Piccie bucket(s), and rotate it if
the card is lost or reused. The setup page is served over plain HTTP on the
local network, so finish setup on a network you trust. Wi-Fi credentials are
entered on Piccie's touchscreen and kept by the network manager.

A custom domain makes the bucket it is connected to public. Piccie therefore
requires a second bucket for the domain, refuses a domain that serves the
private bucket, and copies only finished strips, event galleries and event ZIPs
there under HMAC-derived names that cannot be guessed. Never connect a domain to
the private bucket: its readable object names can be enumerated.

The setup page accepts one SSH public key. Public keys are safe to copy; private
keys are not. Piccie installs only the validated public key in
`/data/ssh/authorized_keys`. Keep the matching private key on the operator's
computer and never place it on the microSD card or in this repository.

The engine listens on port 8080 so a paired phone can reach Template Studio and
the setup page. LAN clients can only load those pages' assets, `/api/studio/*`
and `/api/setup/*`; capture, event, Wi-Fi, settings, gallery and pairing
endpoints remain loopback-only. Studio installation requires a random in-memory
token. It remains valid until the booth creates a new pairing code or restarts.
Setup requires an in-memory eight-character code (about 40 bits) shown on the
booth. Only the booth can create it, and only behind the operator PIN once one
is set. It stops working when first-time setup finishes, when the Settings code
is closed, or when the booth restarts.
