# Hardware

> **Work in progress:** The files to print are ready. Final print settings,
> fastener quantities and a photographed assembly guide are still to come.

This page lists the parts used by the Piccie reference build so prospective
builders can understand the scope and begin checking availability. Marketplace
listings can change; verify the selected variant and dimensions before buying.

## Supported reference build

The current enclosure is designed around a **Raspberry Pi 4 Model B with 4 GB
of RAM** and a 1024×600 touchscreen. A Raspberry Pi 5 may run the software, but
it does not fit the current mounting plate and has not been thermally validated
inside the enclosure.

## Parts to buy

| Qty | Part | Reference | Notes |
| ---: | --- | --- | --- |
| 1 | Raspberry Pi 4 Model B, 4 GB | Raspberry Pi retailer | Supported reference board |
| 1 | 32 GB high-endurance A2/U3 microSD card | Reputable storage retailer | Recommended system card |
| 1 | Reliable Pi 4 USB-C power supply | Raspberry Pi retailer | Use a supply rated for the Pi and connected accessories |
| 1 | Pi 4 heatsink and fan | [Reference part](https://www.aliexpress.com/item/1005007209436358.html) | Active cooling is strongly recommended |
| 1 | IMX708 camera, 75° NoIR | [Reference part](https://www.aliexpress.com/item/1005010149719151.html) | Select the 75° NoIR variant |
| 1 | 10-inch LED ring light | [Reference part](https://www.aliexpress.com/item/1005002504336987.html) | Donor light; its supplied diffuser is replaced |
| 1 | 7-inch HDMI touchscreen | [Reference part](https://www.aliexpress.com/item/1005009096258871.html) | Touch support is required; reference resolution is 1024×600 |
| TBD | Heat-set threaded inserts | [Reference set](https://www.amazon.com.au/dp/B0G423B5BD) | Exact sizes and quantities are still being recorded |
| TBD | Threaded standoffs, screws and nuts | Often supplied with the hardware | Exact sizes and quantities are still being recorded |
| As required | PETG filament | Any suitable supplier | Opaque for the body; clear or white for the diffuser |

The final bill of materials will also specify the camera ribbon, HDMI cable,
USB touch cable, internal power leads, LED wiring and cable lengths.

## Parts to print

Piccie has five printed parts. Each comes as a 3MF file (millimetre units, opens
in any current slicer) and an STL file:

| Part | Files | Size (mm) | Material |
| --- | --- | --- | --- |
| Main body | [3MF](../hardware/body.3mf) · [STL](../hardware/body.stl) | 245 × 245 × 62 | Opaque PETG |
| LED diffuser | [3MF](../hardware/diffuser.3mf) · [STL](../hardware/diffuser.stl) | 242 × 242 × 8 | Clear or white PETG |
| Raspberry Pi mounting plate | [3MF](../hardware/pisupport.3mf) · [STL](../hardware/pisupport.stl) | 240 × 70 × 9 | PETG |
| Back cover | [3MF](../hardware/lid.3mf) · [STL](../hardware/lid.stl) | 240 × 227 × 2 | PETG |
| Stand | [3MF](../hardware/stand.3mf) · [STL](../hardware/stand.stl) | 100 × 38 × 62 | PETG |

The main body needs a build plate of at least 245 × 245 mm, such as a Bambu Lab
X1C, P1S or A1. PETG reduces the chance of heat-related warping during long
events.

To change the design, open [piccie.step](../hardware/piccie.step) in any CAD
program. It holds all five parts as solid bodies.

## Lighting note

The build reuses the light source and electronics from the 10-inch ring light,
then replaces its original diffuser with the printed Piccie diffuser. Final
teardown and wiring instructions will be published with assembly photographs.
Only modify a low-voltage USB or DC light whose wiring you understand; never
open or adapt mains-voltage equipment.

## What remains before release

- Hardware-design licence
- Slicer settings and print orientation
- Heat-set insert and fastener map
- Exact cable specifications
- Step-by-step assembly photographs
- Thermal validation and final fit checks

Until those items are published, this parts list is planning information rather
than a complete assembly guide.
