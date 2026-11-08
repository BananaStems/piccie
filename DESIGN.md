---
name: piccie
description: Make the booth & the memories. A warm-paper, terracotta, matte-object world shared by the booth kiosk, phone setup, template studio and guest strip page.
colors:
  terracotta: "#c45c4a"
  terracotta-deep: "#a8473a"
  wordmark-red: "#8f201c"
  paper: "#f2ebe3"
  paper-raised: "#faf6f0"
  ink: "#2d2926"
  muted: "#6b635b"
  error: "#a43e32"
  print-white: "#ffffff"
typography:
  display:
    fontFamily: "Outfit, system-ui, sans-serif"
    fontSize: "2.25rem"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Outfit, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Outfit, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Outfit, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: "-0.01em"
  label:
    fontFamily: "Outfit, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.01em"
  guest-body:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.35
  guest-button:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "19px"
    fontWeight: 700
    lineHeight: 1
rounded:
  sm: "10px"
  md: "16px"
  lg: "20px"
  pill: "999px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "20px"
  "6": "24px"
  "8": "32px"
components:
  button-primary:
    backgroundColor: "{colors.terracotta}"
    textColor: "{colors.print-white}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "0 16px"
    height: "52px"
  button-secondary:
    backgroundColor: "rgba(45, 38, 32, 0.06)"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "0 16px"
    height: "52px"
  input:
    backgroundColor: "{colors.paper-raised}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "0 16px"
    height: "52px"
  card:
    backgroundColor: "{colors.paper-raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "20px 24px 24px"
  guest-save:
    backgroundColor: "{colors.terracotta}"
    textColor: "{colors.print-white}"
    typography: "{typography.guest-button}"
    rounded: "{rounded.md}"
    padding: "0 26px"
    height: "56px"
  guest-save-active:
    backgroundColor: "{colors.terracotta-deep}"
    textColor: "{colors.print-white}"
  guest-print:
    backgroundColor: "{colors.print-white}"
    width: "min(calc((100svh - 20px - safe-top - actions) / 3), 100%)"
---

# Design System: piccie

## Overview

**Creative North Star: "The Well-Made Booth"**

piccie is a physical object first: a round, matte, warm-white booth with a soft light ring, and every screen inherits that object's materials. Grounds are warm paper, ink is a dark warm brown rather than black, the single action colour is terracotta, and the photo strip is the one pure-white thing on screen. Surfaces are matte and lightly grained, never glossy; depth comes from soft, warm-tinted shadows and, on the guest page, from modelled machine parts (an embossed wordmark, a recessed slot, a lip).

Density is calm and touch-first. The booth kiosk runs on a 7" 1024×600 panel with a 19px root, 52px controls and generous page padding; the phone setup page and template studio use the same palette and Outfit face at phone scale; the guest strip page is a single full-screen print with one floating action. Type is Outfit throughout, with tight negative tracking on headings, except on the guest page, where the strict inline-only CSP forbids any font file and the system UI stack stands in.

The guest page is the surface where the world is most literal: the end of a piccie printer hangs across the top of the screen and the strip develops out of its slot. Its parts (printer body, emboss, slot, lip, develop haze) are surface components, documented below, not global decoration for other screens.

**Key Characteristics:**
- Warm paper grounds, dark warm ink, one terracotta action colour.
- The photo strip sits on pure white and is the brightest object on screen.
- Matte, lightly grained surfaces; shadows always tinted warm brown.
- Outfit at semibold with negative tracking; system UI only where CSP forbids fonts.
- Lowercase "piccie" wordmark in deep wordmark red, used as an identity mark, never as a UI fill.

## Colors

A warm, low-chroma paper palette carrying a single saturated terracotta voice and a deeper brand red reserved for the wordmark.

### Primary
- **Terracotta** (#c45c4a): the action colour. Fills the booth's primary buttons and on-screen keyboard Done key, the guest page's Save button, studio shape defaults, and the selection/focus tint (`rgba(196,92,74,.14)` dim fill, `.55` focus border) on booth inputs.
- **Deep Terracotta** (#a8473a): the pressed state of the guest Save button and the setup page's accent-at-text-size colour (5.8:1 on white). Use it wherever terracotta must be read as small text or must darken on press.

### Secondary
- **Wordmark Red** (#8f201c): the lowercase piccie wordmark (`web/assets/piccie-wordmark.svg`). On the guest page it appears only as the tint of the Save button's ambient glow (`rgba(143,32,28,.5)`), tying the action back to the brand.

### Neutral
- **Booth Paper** (#f2ebe3): the page ground everywhere: kiosk screens, setup page body, guest page ground and `theme-color`.
- **Raised Paper** (#faf6f0): cards, inputs and setup cards sitting one step above the ground.
- **Warm Ink** (#2d2926): all primary text, focus outlines on the guest page, the setup step-number disc. Its RGB family (`45,38,32` / `45,41,38`) also tints every border and shadow.
- **Warm Muted** (#6b635b): secondary text and placeholders on every surface. It holds 4.7:1 or better on every paper, field and panel colour.
- **Error** (#a43e32): error text and the studio's error status fill. 5:1 or better on every paper colour; white text on it reads at 6.3:1.
- **Print White** (#ffffff): the strip's paper and text on terracotta. Nothing else on a paper ground is pure white.

Borders are ink at low alpha (`rgba(45,38,32,.12)`), and neutral hover/secondary fills are ink at 6-10% alpha, so the palette stays one hue family.

### Named Rules
**The One Voice Rule.** Terracotta is the only saturated colour on a screen, and it marks the action. A screen has one filled terracotta action; everything else is ink or paper.

**The Warm Ink Rule.** No neutral greys and no black shadows. Text, borders and shadows are all warm brown (`45,38,32`-family) at varying alpha. The guest printer's slot is the one native exception: it is a hole, and it goes near-black (#030202 to #2b2424).

**The Brightest Object Rule.** The photo strip is printed on pure white (#ffffff) and is the brightest object on screen. Grounds stay paper; never place the strip on a white page.

## Typography

**Display Font:** Outfit (self-hosted variable 400-700, with system-ui, sans-serif)
**Body Font:** Outfit (with system-ui, sans-serif)
**Guest page:** system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif

**Character:** Outfit is a round geometric sans that echoes the booth's round body; set semibold and tightly tracked it reads friendly but precise, a product label rather than a party flyer.

### Hierarchy
- **Display** (600, 2.25rem, 1.15, -0.03em): booth screen titles. On the 19px kiosk root this is about 43px. The setup page scales its h1 fluidly (`clamp(2rem, 8vw, 3rem)`, -0.04em).
- **Headline** (600, 1.5rem, 1.15, -0.02em): section headings and party-mode prompts.
- **Title** (600, 1.25rem, 1.15, -0.02em): card and step headings (setup step titles, studio sheet headers).
- **Body** (400, 1rem, 1.4, -0.01em): running text and inputs; subtitles cap at 36ch and use Warm Muted.
- **Label** (600, 0.875rem, line-height 1, -0.01em): button labels, the most-used size in the booth CSS.
- **Guest body** (400, 16px, 1.35): guest status line and the iOS save note (0.86-0.95rem, muted).
- **Guest button** (700, 19px, 1): the single Save to Photos label.

### Named Rules
**The Tight Tracking Rule.** Outfit is always tracked negative: -0.01em for body and labels, -0.02em for titles and headlines, -0.03em to -0.04em for display.

**The Inline-Only Rule.** The guest page's CSP is `default-src 'none'` with inline style only, so it loads no font file and uses the system UI stack. This is a hard constraint of the delivery format, not a lapse; every other surface uses self-hosted Outfit and never a font CDN (a CDN link stalled first paint at no-signal venues).

## Layout

The booth kiosk is a full-viewport flex column per screen with 32px horizontal and 24px vertical page padding, a 20px content gap and 12px control gap, on the 4px-based spacing scale (4, 8, 12, 16, 20, 24, 32). Admin content caps at 660px. Text sizes are rem off a 19px root so the whole UI scales for the 7" panel.

The phone setup page is a single centred column (max 720px, 20px/16px padding) of stacked cards, widening its forms at 620px. The template studio is a dark-bench workspace with a 360px side sheet that becomes a bottom sheet under 760px.

The guest page is a fixed full-screen stage: the print is centred and sized by height (width = available height / 3, honouring `svh` and safe-area insets), with a 126px action zone pinned to the bottom. During the print a 142px printer band spans the top at up to 520px wide.

## Elevation & Depth

Depth is soft and ambient, always warm-tinted, and mostly tonal: paper → raised paper → white print. Shadows are large, low-opacity and diffuse on containers; the guest page adds modelled, lit-from-above depth on its machine parts.

### Shadow Vocabulary
- **Ambient card** (`box-shadow: 0 12px 32px rgba(45,38,32,.1)`): booth overlays and raised panels (the `--shadow` token).
- **Setup card** (`box-shadow: 0 16px 42px rgba(45,38,32,.08)`): phone setup cards.
- **Focus halo** (`box-shadow: 0 0 0 3px rgba(196,92,74,.14)`): booth input focus.
- **Hanging print** (`filter: drop-shadow(0 1px 1px rgba(45,41,38,.16)) drop-shadow(0 14px 20px rgba(45,41,38,.2))`): the guest strip, as paper hanging in light.
- **Floating save** (`box-shadow: inset 0 1px 0 rgba(255,255,255,.22), 0 2px 4px rgba(45,41,38,.16), 0 14px 26px -10px rgba(143,32,28,.5)`): the guest Save button.

### Named Rules
**The Matte Grain Rule.** Matte surfaces carry fractal-noise grain (`feTurbulence` baseFrequency .85): the booth overlays it at 14% opacity across the kiosk, and the guest printer body multiplies it at 45%. Grain is texture on a material, never a pattern.

## Shapes

Corners are soft and rounded, never sharp and never fully pill-shaped on primary controls. The booth scale is 10px (controls, inputs), 16px (cards, the guest Save button), 20px (large panels) and 999px (badges and status pills only). Round geometry (the booth body, step-number discs, swatches) is a recurring motif. The guest printer is a 22px bottom-rounded band; its slot is a 9px-tall, 2px-radius opening.

## Components

### Buttons
Tactile and plain: flat fills, no gradients, a small press.
- **Shape:** gently rounded (10px), 52px tall, min 148px wide on the booth.
- **Primary:** Terracotta fill, white Label type, 16px horizontal padding.
- **Press:** `scale(0.98)` on the booth, `scale(.97)` in the studio, `translateY(1px)` plus Deep Terracotta on the guest page; transitions 150-220ms.
- **Secondary:** ink at 6% alpha with a 12%-alpha ink hairline border and ink text.
- **Focus:** keyboard only. Booth buttons take a 2px Terracotta outline at 2px offset (touch taps never show it); the guest Save takes a 3px Warm Ink outline.
- **Disabled:** 40-55% opacity.

### Inputs / Fields
- **Style:** Raised Paper fill (white on setup), 1px ink-alpha border, 10px radius, 52px tall, Body type.
- **Focus:** border shifts to terracotta (55% alpha) with a 3px terracotta halo.

### Cards / Containers
- **Corner Style:** 16px (booth event and template cards), 22px on phone setup cards.
- **Background:** Raised Paper on the Booth Paper ground.
- **Shadow Strategy:** hairline border at rest; ambient shadow only on overlays and setup cards.
- **Internal Padding:** 20px top, 24px sides and bottom.

### Guest Save button (signature)
The one action on the guest page, floating over the print. Terracotta, 56px tall, min 232px wide, 16px radius, 19px bold system type, a 20px inline stroke download icon, the Floating save shadow. Hover (hover-capable devices only) darkens to #b9513f, press to Deep Terracotta with a 1px drop. Focus is a 3px Warm Ink outline at 3px offset. On iOS it becomes "Save to Photos" through the share sheet, with a muted note beneath.

### Guest printer (signature, guest page only)
The end of a piccie printer, shown only while the strip prints. A matte warm-white body (vertical gradient #fdfbf7 → #f9f5ef → #f3eee6) with multiplied grain, the lowercase wordmark embossed in #faf7f2 (SVG diffuse plus specular lighting from azimuth 235°, elevation 38°, with a 1.6px warm cast shadow), and a 46px recessed lip carrying the slot. The slot is a near-black inset opening with a pale 3px lower lip; a 14px warm shade falls on the paper as it exits.

### Developing print and motion grammar (guest page only)
The strip feeds out of the slot at 58% scale in three stepped feeds with holds between (`cubic-bezier(.3,.7,.35,1)`, never linear tweens), revealed by a bottom-up clip. A warm haze (#cdc6bc) clears upward across the photos as they develop. The rollers release with an 8px drop, then the printer lifts away on ease-in (`cubic-bezier(.55,0,.8,.25)`, 470ms) while the strip zooms to full height on ease-out (`cubic-bezier(.2,.75,.15,1)`), and the Save button rises 16px last. The whole sequence is 2.05s from image load. It plays once per strip per phone; repeat visits, reduced motion, or any animation failure open on the finished state.

## Do's and Don'ts

### Do:
- **Do** use Booth Paper (#f2ebe3) as the ground and Raised Paper (#faf6f0) one step up; reserve pure white for the photo strip and text on terracotta.
- **Do** give each screen one filled Terracotta action and keep everything else ink or paper.
- **Do** tint every shadow and border with warm ink (`rgba(45,38,32,…)`), never neutral black.
- **Do** self-host Outfit and track it negative (-0.01em body, -0.02em titles, -0.03em display).
- **Do** keep touch targets at 52px or taller on the booth and 56px for the guest Save button.
- **Do** open any motion-led surface on its finished state for reduced motion and repeat visits, and never let an animation strand the photo or the save action.

### Don't:
- **Don't** load fonts, scripts or any external file on the guest page; its CSP allows inline style and script and `https:` images only.
- **Don't** use Wordmark Red (#8f201c) as a button, link or text colour; it belongs to the wordmark.
- **Don't** set the wordmark in anything but lowercase "piccie".
- **Don't** use neutral greys or pure black for text or shadows; the only near-black is the printer slot, because it is a hole.
- **Don't** place the strip on a white page; it must be the brightest object on screen.
