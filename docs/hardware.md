# Build Piccie

This guide describes the Piccie reference build: a Raspberry Pi 4 photobooth
whose main enclosure prints as a single piece. It records what has been proven,
what can be substituted and what still needs to be documented before the first
hardware release.

## Reference build

The enclosure was designed around a Raspberry Pi 4 Model B with 4 GB of RAM and
to fit the build plate of a Bambu Lab X1C. Printers with a similarly sized or
larger plate should be suitable, but check the main body's final STL dimensions
against your usable build area before slicing.

The screen is a structural constraint, not just a resolution choice. A
replacement must match the physical dimensions, connector positions and
mounting pattern used by the supplied model.

### Raspberry Pi 5

The software may be portable to a Raspberry Pi 5, but the v1 mounting plate and
enclosure were not designed for it. A Pi 5 build needs a new mounting solution,
clearance checks and thermal testing. Until those exist, the Pi 4 is the
supported reference hardware.

## Performance mode

Piccie can enable a fixed performance profile from **Settings → System
performance**. Select the detected board, choose the mode, acknowledge the
warning and select **Apply & restart**.

The current Raspberry Pi 4 profile uses the firmware-supported `arm_boost=1`
setting, which raises compatible board revisions to as much as 1.8 GHz. It does
not set a custom voltage or force the processor to remain at its highest clock.
Raspberry Pi 5 can be selected so Piccie identifies the hardware correctly, but
only standard mode is available until a profile has been validated in the
physical enclosure.

Performance mode increases heat and power demand. Use active cooling and a
reliable Raspberry Pi power supply. After enabling it, run the booth for at
least one hour and complete several test photo sessions before relying on it at
an event. For a fuller check, run the [powered soak test](../README.md#testing-and-long-event-reliability).

If a booth becomes unstable, return to standard mode. If it cannot boot, mount
the boot partition on another computer and remove the block between `# BEGIN
PICCIE PERFORMANCE` and `# END PICCIE PERFORMANCE` in `config.txt`. Piccie also
keeps the original file as `config.txt.piccie-original` on first use.

## Printed parts

Piccie uses four printed parts.

| Part | Purpose | Recommended material |
| --- | --- | --- |
| Main body | Holds the screen, camera, light and internal assembly | PETG |
| LED diffuser | Softens the dismantled ring light | Clear or white PETG |
| Raspberry Pi mounting plate | Locates the Pi 4 and its hardware | PETG |
| Back cover | Closes the enclosure for service and transport | PETG |

PETG was used throughout the reference build to reduce the risk of parts
deforming from heat inside the enclosure. Clear PETG worked for the diffuser;
white PETG was also tested successfully. PLA has not been validated for a booth
running for hours in a warm venue.

The STL files and validated print settings are not yet included. Before the
first hardware release this guide still needs the final file names, print
orientation, supports, layer height, wall count, infill and measured print
times.

## Bill of materials

These are reference parts, not sponsored links. Marketplace listings and
selected variants can change, so verify the description, dimensions and
connectors before ordering.

| Qty | Part | Reference | Notes |
| ---: | --- | --- | --- |
| 1 | Raspberry Pi 4 Model B, 4 GB | Local Raspberry Pi retailer | Reference and currently supported board |
| 1 | Pi 4 heatsink and fan | [AliExpress reference part](https://www.aliexpress.com/item/1005007209436358.html) | Used only for the Pi 4 reference build |
| 1 | IMX708 camera, 75° NoIR | [AliExpress reference part](https://www.aliexpress.com/item/1005010149719151.html) | Confirm the 75° NoIR variant before ordering |
| 1 | 10-inch LED ring light | [AliExpress reference part](https://www.aliexpress.com/item/1005002504336987.html) | Donor light; dismantled for the build and its supplied diffuser is not used |
| 1 | HDMI touchscreen | [AliExpress reference part](https://www.aliexpress.com/item/1005009096258871.html) | Touch support is required; the reference UI targets 1024×600 |
| TBD | Heat-set threaded inserts | [Amazon Australia reference set](https://www.amazon.com.au/dp/B0G423B5BD) | Exact sizes and quantities will be added after final assembly verification |
| TBD | Threaded standoffs and fasteners | Supplied with the reference hardware | Exact sizes and quantities will be added after final assembly verification |
| As required | PETG filament | Any suitable supplier | Opaque colour for the enclosure; clear or white for the diffuser |

### Details still required

A complete, reproducible bill of materials also needs the following recorded
from the finished reference booth:

- Touchscreen manufacturer, exact model and physical dimensions
- Raspberry Pi power supply specification
- Storage type and minimum capacity
- Camera ribbon, HDMI, USB/touch and internal power cable lengths
- LED ring power and control arrangement
- Heat-set insert sizes and quantities
- Standoff, screw and nut sizes and quantities
- Any adhesive, tape, strain relief or cable-management hardware

These items should be confirmed from the physical build rather than guessed.

## Lighting modification

The reference build reuses the light source and electronics from a 10-inch LED
ring, while replacing the supplied diffuser with the printed Piccie diffuser.
Document the exact teardown and wiring with photographs before treating this as
a beginner assembly step.

Disconnect power before opening the light. Only adapt a low-voltage USB or DC
unit whose wiring you understand; do not expose or modify mains-voltage parts.

## High-level assembly

The final photographed assembly guide will provide the exact order. At a high
level, the build is expected to follow this sequence:

1. Install the heat-set inserts in the printed parts.
2. Fit the touchscreen, camera and printed diffuser to the main body.
3. Install the dismantled LED ring components and route their wiring.
4. Attach the cooled Raspberry Pi 4 to its mounting plate using standoffs.
5. Connect display, touch, camera, lighting and power cables.
6. Test the electronics before fitting the back cover.
7. Flash and complete the [Piccie first-boot setup](../README.md#first-boot).

Do not use this outline as a substitute for the forthcoming fastener map and
assembly photographs.

## Contributing hardware improvements

Useful hardware contributions include alternate screen mounts, a validated
Raspberry Pi 5 plate, improved cable routing and tested parts available in
other regions. Include source CAD where possible, the exact printer and
material used, slicer settings, tolerances, photographs and any required bill
of materials changes.

The repository still needs an explicit licence for the CAD and STL files before
they are published. The MIT licence currently covers the software; it should
not be assumed to define the terms for reproducing the physical design.
