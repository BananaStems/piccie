# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Hosts**: people who build a Piccie booth from a Raspberry Pi kit and run it at their own parties (weddings, birthdays). They set it up from their phone and manage events, templates and storage.
- **Guests**: party attendees. They tap the booth, take three photos, and scan a QR code to get their strip on their own phone, usually on mobile data, often in a dim, loud venue, sometimes reopening the link the next morning to save it again.

## Product Purpose

An open-source photo booth you build yourself. Guests get a finished 2×6 strip on their phone in seconds with no app, no sign-up and no booth Wi-Fi to join. Success: every guest leaves with their strip saved, and hosts own the photos in their own Cloudflare storage.

## Positioning

A self-built, self-hosted booth with rental-booth polish: one flashed image, phone-based setup, photos in the host's own bucket, MIT licence, no subscription.

## Operating Context

- Booth: Raspberry Pi 4, IMX708 camera, 7" 1024×600 touchscreen, LED lighting; guest mode is locked.
- Delivery is always online: strips reach guests only through cloud links (`piccie.link` short links or signed R2 URLs), never via the booth's own network.
- Guest download page is a single self-contained HTML document generated in `engine/r2.py` and uploaded beside the strip; strict CSP (inline style and script only, `img-src https:`, no external fonts or scripts).

## Capabilities and Constraints

- Strip: 600×1800 px JPEG (2×6″ at 300 DPI), three photos plus a template footer (event name, date). Templates vary per event.
- iOS saving goes through the share sheet (Save to Photos); other platforms use a download link.
- Event gallery page offers every strip plus a ZIP of the whole event.

## Brand Commitments

- Name always lowercase "piccie" in the wordmark (`web/assets/piccie-wordmark.svg`, deep red `#8f201c`).
- Booth UI world: warm paper grounds (`#f2ebe3`, `#faf6f0`), terracotta accent `#c45c4a`, Outfit UI face, dark warm ink `#2d2926`.
- Tagline: "Make the booth & the memories".
- The booth hardware is presented as a round, matte, warm-white object with a soft light ring (`docs/images/piccie-hero.jpg`).

## Evidence on Hand

- Product screenshots and hero art in `docs/images/` (sample strip uses illustrative people; not real customers).
- No testimonials, user counts or press exist; do not invent them.

## Product Principles

1. The guest's photo is the point; everything else gets out of its way.
2. Getting the photo must be fast and certain, even on a weak venue connection.
3. Feel like a well-made object, not a toy or a template.
4. Hosts own everything; nothing depends on a Piccie-run service.
