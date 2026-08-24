# HP LaserJet 1020 protocol, firmware bootstrap, and capability envelope

Research date: 2026-08-24

Wayfinder question: What exact-model facts must constrain the HP LaserJet 1020 macOS printing solution?

## Decision

Treat the reference printer as a **host-based monochrome raster device**, not as a generic PCL or PostScript printer. The implementation target is:

1. render each page on the Mac to a one-bit monochrome raster;
2. JBIG-compress the raster and wrap it in the LaserJet 1020 variant of Zenographics ZjStream;
3. send that stream over the USB printer data path;
4. before printing after every printer power-on, determine whether firmware is active and, when it is not, upload the exact `sihp1020` firmware image before accepting jobs; and
5. use the return path, if confirmed on the reference printer, for status and recoverable-error handling.

HP explicitly describes the LaserJet 1020 as host-based and explains that host-based printing computes the job on the computer rather than in the printer formatter ([HP Software Technical Reference, pp. 3 and 28](https://www.hp.com/ctg/Manual/c00378935.pdf#page=14)). OpenPrinting's exact-model implementation identifies its output as ZjStream and converts PBM raster input to that format ([`foo2zjs.c`, lines 3–18](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/foo2zjs.c#L3-L18)). These sources rule out a design that merely forwards PDF, PostScript, or PCL to the printer.

Firmware is an operational dependency but not currently a redistributable project asset. OpenPrinting's workflow fetches an HP-copyrighted 2005 image from an external site instead of storing it in the source tree ([`getweb.in`, lines 212–218](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/getweb.in#L212-L218)). Until a separate provenance decision establishes redistribution rights, the repository must not contain the firmware blob; installation must use a lawful user-supplied or official-source acquisition flow.

## Evidence standard

“Verified” below means stated by HP for the exact LaserJet 1020 or implemented in an exact-model path in OpenPrinting source. OpenPrinting is authoritative implementation evidence, not an HP protocol specification. Anything shared with the LaserJet 1018 or 1022 remains an implementation-family clue until it is exercised on the reference printer.

The USB observations in upstream source describe an HP LaserJet 1020, but they are not a capture of this project's reference printer or either required connection path. The hardware-capture ticket must therefore confirm descriptors and behavior before release claims are made.

## Exact-model USB identity and firmware state

| Property | Evidence-backed value | Confidence and consequence |
| --- | --- | --- |
| USB vendor/product | `03f0:2b17` | OpenPrinting's hotplug rule matches this pair specifically for “HP LaserJet 1020” and writes `sihp1020.dl` ([`hplj10xx.conf`, lines 70–75](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/hplj10xx.conf#L70-L75)). Use it as the expected identity, but confirm it on the reference printer. |
| Observed USB generation/speed | USB 2.00, 480 Mbit/s in the upstream sample | The exact-model diagnostic sample reports `Ver=2.00`, `Spd=480`, device class at interface level, and the same VID/PID ([`INSTALL.usb`, lines 18–23](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/INSTALL.usb#L18-L23)). HP also specifies USB 2.0 High Speed ([User Guide, p. 3](https://www.hp.com/ctg/Manual/c00264334.pdf#page=12)). Endpoint addresses and interface protocol are not yet verified. |
| IEEE 1284 device ID before firmware | Fields identify Hewlett-Packard, `HP LaserJet 1020`, command set `ACL`, and printer class | These fields are shown by upstream's `GET_DEVICE_ID` example ([`usb_printerid.1in`, lines 19–27](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/usb_printerid.1in#L19-L27)). Whitespace, escapes, and field order must be parsed defensively. `CMD:ACL` must not be interpreted as PCL support. |
| Firmware-active marker | Device ID gains `FWVER:20050309;` | Exact before/after example follows a raw write of `sihp1020.dl` ([`usb_printerid.1in`, lines 29–35](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/usb_printerid.1in#L29-L35)). Use presence of `FWVER`, not a hard-coded version, as the candidate state predicate; validate this on the reference printer. |
| Bootstrap lifetime | Required after every power-on | OpenPrinting's install notes state this for the 1020 and show both a raw USB write and the historical macOS raw-queue method ([`INSTALL`, lines 549–588](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/INSTALL#L549-L588)). Sleep/wake, cable reconnection, and hub reset behavior still need physical testing. |
| USB transfer model | Printer-class control request plus bulk data path is the standards-based expectation | USB-IF defines `GET_DEVICE_ID`, a mandatory Bulk OUT endpoint for PDL/PCP data, and an optional Bulk IN endpoint for returned status ([USB Device Class Definition for Printing Devices 1.1, §§4–5](https://www.usb.org/sites/default/files/usbprint11a021811.pdf)). The reference printer's interface subclass/protocol and endpoint set must be captured rather than assumed. |

The bootstrap should be idempotent: query the device ID, upload only when no firmware marker is present, wait for the device to settle, re-query, then expose the queue as ready. Do not blindly upload before every job. Whether a firmware upload causes re-enumeration is not established by the sources and must not be baked into the implementation before hardware capture.

## ZjStream data-path contract

The mature OpenPrinting implementation provides the best available executable description of the exact-model stream:

- The 1020 selects model variant `-z1`, suppresses `START_PLANE` with `-P`, and disables logical-clipping records with `-L0` ([exact-model PPD, lines 89–112](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/PPD/HP-LaserJet_1020.ppd#L89-L112)).
- Each page is a one-bit raster. The implementation pads the model-1 raster width to a 128-pixel boundary and JBIG-encodes it ([`foo2zjs.c`, lines 1167–1237](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/foo2zjs.c#L1167-L1237)).
- Encoded page data is carried as a 20-byte JBIG BIH followed by BID chunks capped at 65,536 bytes, with end padding ([`foo2zjs.c`, lines 757–815](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/foo2zjs.c#L757-L815)).
- The document is prefixed with PJL job, density, EconoMode, RET, and unsolicited-status requests, then the big-endian `JZJZ` stream header; it closes with PJL end-of-job framing ([`foo2zjs.c`, lines 817–938](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/foo2zjs.c#L817-L938)).
- Exact-model page records carry raster dimensions, resolution, source, copies, paper, media type, and EconoMode before the JBIG data ([`foo2zjs.c`, lines 584–688](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/foo2zjs.c#L584-L688)).

This is enough to define a clean encoder boundary and build golden-stream tests. It is not enough to claim that every field or status request behaves as intended on the reference printer; model-specific captures and print tests remain the acceptance authority.

## Verified capability envelope

### Physical and engine capabilities

| Capability | Exact-model fact | Product implication |
| --- | --- | --- |
| Output | Monochrome laser, host-based; 2 MB RAM | Render and compress on the Mac. Advertise grayscale/black only. Do not expose color. ([HP Software Technical Reference, p. 3](https://www.hp.com/ctg/Manual/c00378935.pdf#page=14)) |
| Speed | Up to 14 ppm A4, 15 ppm Letter; first page in as little as 10 seconds | Useful performance target, not a guaranteed per-job SLA. ([User Guide, p. 76](https://www.hp.com/ctg/Manual/c00264334.pdf#page=85)) |
| Quality | 600×600 dpi with REt, or FastRes 1200 effective quality described as 600×600×2 | Offer two named quality modes; do not claim native 1200×1200 dpi. EconoMode can be independently enabled. ([User Guide, pp. 16–17](https://www.hp.com/ctg/Manual/c00264334.pdf#page=25)) |
| Input/output | 150-sheet main tray, one-sheet priority feed, 100-sheet face-down output | Expose automatic/main versus manual/priority intent only after source-code behavior is validated. ([User Guide, pp. 3–6](https://www.hp.com/ctg/Manual/c00264334.pdf#page=12)) |
| Page size | 76×127 mm through 216×356 mm | Support custom size only inside this physical interval. ([User Guide, pp. 31 and 76](https://www.hp.com/ctg/Manual/c00264334.pdf#page=40)) |
| Media | Plain, light, heavy/cardstock, transparency, envelope, label, bond, rough, color stock, letterhead, preprinted, prepunched, recycled, and vellum modes are documented | Media selection is device-significant because HP says it controls fuser temperature. Preserve it through the stream rather than treating it as UI-only metadata. ([User Guide, pp. 17–20](https://www.hp.com/ctg/Manual/c00264334.pdf#page=26)) |
| Duplex | Manual two-sided printing only; paper passes through twice | Do not advertise automatic duplex. Manual duplex is a host workflow with long-/short-edge ordering and a user refeed step. ([User Guide, pp. 32–33](https://www.hp.com/ctg/Manual/c00264334.pdf#page=41)) |
| Duty cycle | 8,000 single-sided pages/month maximum, 1,000 average | Documentation and stress-test planning constraint; not a scheduler feature. ([User Guide, p. 76](https://www.hp.com/ctg/Manual/c00264334.pdf#page=85)) |

The HP Software Technical Reference has a conflicting tray table—10-sheet priority and 250-sheet main—while the exact-model User Guide repeatedly specifies one-sheet priority and 150-sheet main. The capability matrix should use the User Guide figures and confirm them physically; it should not copy the conflicting software-reference table.

### Device-directed controls to validate

Protocol and exact-model driver evidence support the following candidates for the capability matrix:

- paper size and custom dimensions;
- source selection (automatic/main versus manual/priority);
- media/fuser mode;
- 600×600 and FastRes-1200-equivalent raster modes;
- EconoMode;
- print density, with levels 1–5 exposed by the exact-model PPD ([PPD, lines 268–282](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/PPD/HP-LaserJet_1020.ppd#L268-L282));
- copies; and
- cleaning-page initiation and jam-recovery policy, both documented in HP's original host driver ([HP Software Technical Reference, pp. 57–58](https://www.hp.com/ctg/Manual/c00378935.pdf#page=68)).

These should not all be promised merely because a field exists in upstream code. Each needs a reference-printer test that demonstrates an observable effect. In particular, host-side copies are always possible, while hardware copy semantics and safe limits need testing.

### Host-composed features

Watermarks, scaling, orientation, N-up, booklet imposition, page borders, first-page-different-media composition, and manual-duplex page ordering are host-side composition/workflow features. HP documents them as host-driver features, and the device is host-based ([HP Software Technical Reference, pp. 28–55](https://www.hp.com/ctg/Manual/c00378935.pdf#page=39)). They may be supplied by macOS or the solution's raster pipeline, but they are not evidence of independent printer protocol features.

### Status and errors

HP documents two front-panel lights. Attention represents empty media, an open cartridge door, a missing cartridge, or other errors; Ready represents readiness ([User Guide, p. 5](https://www.hp.com/ctg/Manual/c00264334.pdf#page=14)). HP's original driver also supported bidirectional communication and on-screen error messages, including paper-out ([Software Technical Reference, pp. 15 and 58](https://www.hp.com/ctg/Manual/c00378935.pdf#page=26)). OpenPrinting emits PJL `INFO STATUS` and `USTATUS` requests, but the exact bytes returned by this reference printer and their mapping to macOS queue states are not established. Error reporting is therefore inside the destination, but its protocol contract must be captured from hardware.

## Exact model versus sibling-model inference

OpenPrinting deliberately shares model variant `1` among LaserJet 1018, 1020, and 1022 ([`foo2zjs.c`, lines 16–18 and 107–112](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/foo2zjs.c#L16-L18)). That supports reuse of the ZjStream encoder design, but it does **not** establish interchangeability:

- the 1020 has its own expected USB PID and `sihp1020` image;
- the 1018 uses a different PID and firmware image in the same hotplug table ([`hplj10xx.conf`, lines 63–74](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/hplj10xx.conf#L63-L74));
- the shared encoder list includes 1022, while the per-power-cycle firmware list does not ([`INSTALL`, lines 549–576](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/INSTALL#L549-L576)); and
- “LaserJet 1020 Plus” or other similarly named devices are not covered by this evidence.

Therefore, identify by captured descriptors and exact model string, select firmware by exact identity, and reject unknown siblings instead of guessing.

## Required reference-printer validation

The following evidence is still required before the capability matrix can mark these behaviors verified:

1. Capture the full USB device, configuration, interface, and endpoint descriptors before and after firmware, over both connection paths.
2. Capture the IEEE 1284 device ID before bootstrap and after successful bootstrap; verify whether the firmware version varies from the upstream example.
3. Determine whether upload causes disconnect/re-enumeration and how long readiness takes.
4. Capture bidirectional traffic for ready, paper-out, open door, missing cartridge, jam, cancellation, and job completion; map it to queue states.
5. Print golden pages at both quality modes, every intended page size/source/media mode, densities 1–5, copy counts, and manual duplex.
6. Test power cycle, USB detach/reattach, each connection path, Mac sleep/wake, interrupted firmware upload, interrupted job, and recovery without reboot.
7. Confirm the physical label and captured identity say **HP LaserJet 1020**, not a regional “1020 Plus” or sibling model.

## Consequence for later decisions

Architecture selection should evaluate solutions around four replaceable seams: macOS job ingestion/rasterization, a testable ZjStream encoder, a USB transport/status state machine, and lawful firmware acquisition/bootstrap. A generic printer-language backend is not viable. Reusing or independently implementing the mature C encoder is a licensing and maintainability decision for the architecture/provenance tickets, not a protocol unknown.

## Primary sources

- HP, [*HP LaserJet 1020 User Guide*](https://www.hp.com/ctg/Manual/c00264334.pdf), 2005.
- HP, [*HP LaserJet 1020 Software Technical Reference*](https://www.hp.com/ctg/Manual/c00378935.pdf), Edition 1, April 2005.
- USB-IF, [*USB Device Class Definition for Printing Devices, Release 1.1*](https://www.usb.org/sites/default/files/usbprint11a021811.pdf), January 2000.
- OpenPrinting, [`foo2zjs` source at commit `80499ed5bf6caa2963ad337e37cfda78a80aab1e`](https://github.com/OpenPrinting/foo2zjs/tree/80499ed5bf6caa2963ad337e37cfda78a80aab1e).
