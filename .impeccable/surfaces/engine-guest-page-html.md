---
version: 1
slug: "engine-guest-page-html"
primary_target: "engine/guest_page.html"
related_targets: ["engine/r2.py"]
---

# Guest strip page

Scope: the page a guest opens from the booth's QR code (`engine/guest_page.html`, rendered by `R2Uploader._session_html`). Visitor mode: Experience.

Audience and job: a party guest on their own phone, often on weak mobile data in a dim venue, saves their 2×6 strip. Repeat visits (next morning) are for re-saving.

Constraints: one self-contained document under the existing CSP (inline style and script only, `img-src https:`, no fonts, no external files); keep the iOS share-sheet save flow and the `<a id="download-strip" ... href="...">` markup that `verify_guest_download` parses. First visit only plays the print; repeat visits and reduced motion open on the finished state. Whole sequence must land the photo within about 2.5 s of the image arriving.

## Direction contract

THESIS: The strip is printed for you. The end of a piccie printer hangs across the top of the screen and the strip develops like instant film as it feeds out of the slot. It refuses the category default: a photo on a plain page with a download bar underneath.

OWN-WORLD: The booth's world. Warm paper ground (#f2ebe3), matte warm-white printer body with fine grain, the piccie wordmark raised in emboss on the printer face (lit from above, casting a soft shadow), a dark slot opening, a white print, a terracotta (#c45c4a) Save button. System UI type, no ornaments.

STORY: The guest sees their strip arrive physically, footer first, each photo developing out of a warm haze. The paper drops free, the printer lifts away, the strip settles at full screen height, and Save to Photos floats up. They save it.

FIRST VIEWPORT: The printer end spans the top ~140px, emboss centred above the slot. The strip comes out of the slot opening itself, hanging over the printer's lower lip at about 58% scale. "Printing your strip" sits near the bottom where the button will be. End state: strip centred at full available height, floating Save button pinned bottom centre.

FORM: Developing print, position 2 on the ordered list (dealt as the third card), with the fold-in from "The printer stays" that the paper must visibly exit the slot. seed:9d7363ce7c3deb33

Signature interaction and motion: three stepped feeds with mass (no linear tweens), a develop gradient clearing bottom-up, an 8px release drop, then the printer lifts on ease-in while the strip zooms on ease-out; the button rises last.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
