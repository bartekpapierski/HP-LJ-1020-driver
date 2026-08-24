# Viable macOS 26 printing architectures for the HP LaserJet 1020

Research date: 2026-08-24

## Question

Which architecture can make a USB-only, legacy host-raster printer behave like a normal macOS 26 printer on Apple Silicon—available in Printers & Scanners, the standard Print dialog, and the system print queue—while remaining supportable, secure, and distributable?

## Decision

Use a **user-space IPP Printer Application**, with **PAPPL 1.4.x as the first framework to prototype**. Implement the printer-specific raster encoder, firmware bootstrap, USB lifecycle, and status translation in **C**, because PAPPL, CUPS/libcups, and libusb expose C APIs and PAPPL requires a C99 compiler. A small Swift app may later own installation, service approval, and diagnostics, but Swift should not sit in the print-data hot path.

The process boundary should be:

```text
macOS apps / standard Print dialog
              |
       IPP + Apple/PWG Raster
              |
  local HP 1020 Printer Application
    - queue, capabilities, job state
    - raster -> printer-native stream
    - firmware bootstrap if required
    - reconnect/cancel/error handling
              |
        libusb / user-space USB
              |
        HP LaserJet 1020
```

This is the durable replacement model chosen by CUPS/OpenPrinting: Printer Applications emulate standards-conforming IPP printers while adapting legacy hardware behind the service. PAPPL already supplies an embedded IPP Everywhere service, Apple/PWG Raster ingestion, USB transport via libusb, job management, status surfaces, and DNS-SD integration, and its v1.4.11 release supports CUPS 2.2+ and is developed/tested on Apple Silicon Macs ([PAPPL v1.4.11 README at the release commit](https://github.com/michaelrsweet/pappl/blob/ad86a0a8473f0f83233a374226561181570d4f81/README.md)).

This decision is architectural, not proof that the complete path works on the reference printer. The next prototype must prove local discovery/addition, raster negotiation, unprivileged USB claiming, firmware re-enumeration, cancellation, and reconnect behavior on macOS 26 over both required cable paths.

## Reference-platform observation

Commands run on the reference Mac during this investigation reported:

- macOS 26.6.1 (build 25G76), `arm64`
- Apple CUPS 2.3.4, API 2.3
- the installed `lpadmin(8)` still accepts PPD-backed models and device URIs, but labels every model other than `everywhere`, PPD files, printer drivers, and backends as deprecated

This means a classic CUPS package is technically available as a transition or diagnostic path today, not that it is a stable product foundation. The same deprecation is present in Apple CUPS release history ([Apple CUPS changes](https://github.com/apple/cups/blob/a8968fc4257322b1e4e191c4bccedea98d7b053e/CHANGES.md)) and in current OpenPrinting guidance, which says Printer Applications replace drivers for non-IPP printers ([Printer Applications and Printer Drivers](https://openprinting.github.io/cups/drivers.html)).

## Architecture comparison

| Architecture | Standard macOS UI/queue | USB/printer adaptation | Lifecycle and compatibility | Security/distribution burden | Verdict |
| --- | --- | --- | --- | --- | --- |
| PAPPL-based local IPP Printer Application | Exposes an IPP Everywhere/AirPrint-like printer that macOS can add and use through its standard surfaces | Built-in libusb device layer plus C callbacks for printer-native conversion and status | Matches the CUPS replacement architecture; PAPPL v1.4.11 supports the reference CUPS version and Apple Silicon | A persistent helper and signed/notarized package are needed; privilege must be measured | **Recommended** |
| Hand-written local IPP service | Same integration is possible if it implements IPP, capability/status attributes, accepted raster formats, and DNS-SD correctly | Fully custom | Durable protocol boundary, but recreates queue, conformance, discovery, web/admin, and job-lifecycle code already in PAPPL | Similar service/package burden, with much more custom attack surface | Viable fallback only if PAPPL proves incompatible |
| Classic CUPS PPD + filter + backend | Native CUPS queue and print dialog integration | Filter converts CUPS Raster; backend handles firmware and USB | Works with the reference CUPS 2.3.4, but the interfaces are deprecated and targeted for removal in CUPS 3 | Installs executable code/configuration into system printing paths; CUPS itself calls legacy drivers a security/distribution problem | Prototype or emergency compatibility fallback, **not** release architecture |
| DriverKit/USBDriverKit system extension plus a print front end | None by itself; it still needs an IPP Printer Application or CUPS integration | Strong USB transport mechanism for devices requiring an actual driver | Current Apple API on Apple Silicon, but adds a host app, system extension lifecycle, provisioning, entitlements, and user approval | Highest approval and signing burden | Last-resort transport only if normal user-space USB access cannot work |
| Direct USB CLI/app | Does not become a normal system printer | Can exercise firmware, protocol, and USB quickly | Useful for bring-up tests only | Low initially, but bypasses the required user experience | Prototype tool, not product architecture |
| `ipp-usb` bridge or direct AirPrint | Would integrate well | Only forwards HTTP/IPP-over-USB already implemented by the device; it does not translate a proprietary legacy raster protocol | No path for a printer that does not itself implement IPP-over-USB | Not applicable | Excluded unless hardware research unexpectedly proves native IPP-over-USB |

### Why the Printer Application fits macOS

Apple's current macOS 26 guide says macOS normally uses AirPrint, can add USB printers, and can add IPP print servers through Printers & Scanners. It also exposes the selected printer in the system Print dialog and Print Center ([Add a printer on macOS 26](https://support.apple.com/guide/mac-help/connect-a-printer-to-your-mac-mh14004/26/mac/26)). A Printer Application places the legacy adaptation behind that supported IPP boundary instead of injecting model-specific behavior into every client or depending on a deprecated PPD interface.

OpenPrinting defines a Printer Application as a program that mimics an IPP/2.0 printer and explicitly recommends PAPPL for porting raster drivers. It identifies Printer Applications as the bridge for older non-IPP hardware and documents that CUPS 3 removes classic driver and PPD support ([OpenPrinting driver guidance](https://openprinting.github.io/cups/drivers.html), [CUPS 3.0 architecture](https://github.com/OpenPrinting/cups/wiki/CUPS-3.0)). PAPPL's own model describes each emulated IPP Printer as having an Output Device URI and driver that determine how the service communicates with physical hardware ([PAPPL IPP extensions](https://github.com/michaelrsweet/pappl/blob/ad86a0a8473f0f83233a374226561181570d4f81/doc/IPP-EXTENSIONS.md)).

There is also a close upstream macOS precedent: `hp-printer-app` is a PAPPL-based HP PCL spooler with USB and IPP Everywhere support, distributes a package for macOS 11+ on Intel and Apple Silicon, and runs its service under `launchd` ([HP Printer Application documentation](https://github.com/michaelrsweet/hp-printer-app/blob/b521969bd1ee558aacf952dfabc35dd10769e093/DOCUMENTATION.md), [its launch daemon definition](https://github.com/michaelrsweet/hp-printer-app/blob/b521969bd1ee558aacf952dfabc35dd10769e093/org.msweet.hp-printer-app.plist)). The LaserJet 1020 cannot simply use that application's PCL driver; the value of the precedent is the macOS/PAPPL integration and packaging shape.

### Why not make a classic CUPS driver the product

A classic driver consists of a PPD describing capabilities plus filters that convert jobs into device data and optionally a backend that discovers and communicates with the printer ([Apple CUPS printer-driver design](https://github.com/apple/cups/blob/a8968fc4257322b1e4e191c4bccedea98d7b053e/filter/postscript-driver.shtml)). That model maps directly to older open-source drivers and could shorten a first experiment.

It is nevertheless the wrong long-term seam. CUPS deprecated printer drivers beginning with 2.3 and plans to remove drivers, raw queues, and the PPD API in CUPS 3. OpenPrinting also calls out PPD limitations for dynamic state and the security/distribution problems caused by executable driver packages ([CUPS driver transition rationale](https://openprinting.github.io/cups/drivers.html), [CUPS roadmap](https://github.com/OpenPrinting/cups/wiki/Roadmap)). A new open-source macOS project should not begin on an API whose owner has already published its replacement.

### Why DriverKit is conditional, not primary

Apple positions DriverKit as a user-space device-driver framework and USBDriverKit for custom or non-class-compliant USB devices. A DriverKit driver is an app extension delivered inside a host app and installed through System Extensions; development and deployment require DriverKit/USB transport entitlements and provisioning ([DriverKit overview](https://developer.apple.com/documentation/driverkit), [USBDriverKit overview](https://developer.apple.com/documentation/usbdriverkit), [DriverKit entitlement workflow](https://developer.apple.com/documentation/driverkit/communicating-between-a-driverkit-extension-and-a-client-app)). It solves hardware ownership and transport, not printing, so an IPP service would still be required above it.

Apple also documents direct user-space I/O Kit access for locating, opening, and communicating with USB device interfaces, with a USB entitlement specifically required when the application is sandboxed ([USB Device Interface Guide](https://developer.apple.com/library/archive/documentation/DeviceDrivers/Conceptual/USBBook/USBIntro/USBIntro.html), [`com.apple.security.device.usb`](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.device.usb)). PAPPL uses libusb for precisely this ordinary USB path. Therefore DriverKit should be introduced only if a prototype proves that the macOS class-driver binding or required device-reset/re-enumeration behavior cannot be handled safely from the normal service process.

### Why `ipp-usb` is not a protocol converter

OpenPrinting's `ipp-usb` daemon exposes USB devices that already speak IPP-over-USB by proxying their HTTP operations and DNS-SD advertisement; its documented purpose is driverless support for AirPrint-compatible USB devices ([`ipp-usb(8)`](https://github.com/OpenPrinting/ipp-usb/blob/master/ipp-usb.8.md)). It does not turn an arbitrary legacy raster stream into IPP. The protocol/hardware research ticket must confirm the LaserJet's interfaces, but `ipp-usb` is not a candidate adaptation layer unless the device unexpectedly implements IPP-over-USB.

## Process, privileges, and packaging

Start the prototype as a foreground, per-user process bound to loopback and talking directly to USB. Promote it only after measurement:

1. If the process can claim the printer, load firmware, survive device re-enumeration, and reconnect after sleep without elevation, package it as a user LaunchAgent or app-managed background helper.
2. If USB access or boot/login availability demonstrably requires elevation, isolate only the USB/firmware portion or the whole Printer Application as a narrowly configured LaunchDaemon. Do not assume root before that evidence exists.
3. Do not add DriverKit unless ordinary user-space access is proven inadequate.

For macOS 13+, Apple directs apps to register LaunchAgents and LaunchDaemons with `SMAppService`; helpers live inside the signed app bundle, are visible in Login Items, and a LaunchDaemon requires administrator approval ([SMAppService](https://developer.apple.com/documentation/servicemanagement/smappservice), [updating helper executables](https://developer.apple.com/documentation/servicemanagement/updating-helper-executables-from-earlier-versions-of-macos)). This is preferable for the final package to copying a mutable plist into `/Library/LaunchDaemons`, even though the older `hp-printer-app` package proves that legacy launchd packaging works.

For direct public distribution, Apple requires executable code to carry appropriate Developer ID signatures, hardened runtime, secure timestamps, and notarization; flat installer packages are supported notarization artifacts, and installer packages use a Developer ID Installer certificate ([Notarizing macOS software](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution), [packaging Mac software](https://developer.apple.com/documentation/xcode/packaging-mac-software-for-distribution)). This affects release engineering, not the open-source build: developer builds can remain locally signed or source-built while the package layout is kept notarization-ready.

## Language and dependency choice

- **C for the service and printer driver core.** It is the native interface language of PAPPL, libcups, and libusb, avoids a second FFI boundary in raster/USB hot paths, and is directly supported by Apple Clang. PAPPL itself specifies C99 and Clang on macOS ([PAPPL v1.4.11 requirements](https://github.com/michaelrsweet/pappl/blob/ad86a0a8473f0f83233a374226561181570d4f81/README.md)).
- **Swift only for optional macOS product UI.** It is appropriate for an installer/controller that uses `SMAppService`, opens diagnostics, and explains approval state. The basic printing milestone does not need a custom GUI.
- **Do not build a new Swift IPP server or USB stack first.** That would replace maintained C implementations with bespoke protocol and bridging code without improving macOS integration.
- **Pin PAPPL 1.4.x for the first prototype.** The v1.4.11 release accepts CUPS 2.2+, matching the observed Apple CUPS 2.3.4. PAPPL's current development branch has moved its dependency floor to CUPS 2.5 or libcups 3, so an upgrade or vendored libcups3 must be an explicit later decision rather than an accidental build change ([v1.4.11 README](https://github.com/michaelrsweet/pappl/blob/ad86a0a8473f0f83233a374226561181570d4f81/README.md), [current PAPPL README](https://github.com/michaelrsweet/pappl/blob/master/README.md)).

## Prototype acceptance gates

The recommended architecture advances only if a macOS 26 prototype demonstrates all of the following on the reference M1 Pro Mac:

1. A loopback-bound PAPPL service advertises or can be manually added as an IPP printer and appears in Printers & Scanners, the Print dialog, Print Center, and normal job cancellation flows.
2. Preview or another standard app submits a one-page monochrome job in a format the service accepts; the service receives correctly sized raster data and maps paper size, resolution, copies, orientation, and quality to its driver callback.
3. The process discovers and claims the exact LaserJet 1020 USB identity through both direct USB-C adapter and UGREEN dock paths.
4. Firmware bootstrap and any USB re-enumeration are handled without losing the queued job.
5. Disconnect/reconnect, power cycle, cancellation, no-paper recovery, and Mac sleep/wake produce truthful IPP job/printer states and do not require reinstalling the queue.
6. The same tests are attempted without root. Any elevation requirement must be tied to a recorded failing operation and reduced to the smallest helper boundary.

Failure of gate 1 or PAPPL raster negotiation graduates the hand-written IPP-service fallback for investigation. Failure of gates 3–4 under ordinary user-space USB access graduates DriverKit as a transport-only investigation. Neither failure justifies making the deprecated classic CUPS interface the shipping architecture.

## Remaining risks and decisions this ticket does not settle

- The exact printer-native language, firmware requirement, legal firmware acquisition path, and observable device status belong to the protocol/capability and provenance research tickets.
- PAPPL advertises IPP Everywhere compatibility, but calling a product “AirPrint certified” may involve Apple's licensing/certification requirements; the project only needs standards-compatible local macOS printing unless later research establishes a reason to seek that mark.
- The daemon privilege boundary depends on physical USB tests, not documentation alone.
- Bundled third-party libraries, rasterizers, and firmware flows must follow the separate license/provenance decision.
- The final installer/service design depends on whether a per-user helper meets the hardware lifecycle gates.

## Primary sources

- Apple, [Add a printer to your printer list on macOS 26](https://support.apple.com/guide/mac-help/connect-a-printer-to-your-mac-mh14004/26/mac/26)
- Apple, [About AirPrint](https://support.apple.com/en-us/102895)
- Apple CUPS, [source and release history](https://github.com/apple/cups)
- OpenPrinting, [Printer Applications and Printer Drivers](https://openprinting.github.io/cups/drivers.html)
- OpenPrinting, [CUPS 3.0 architecture](https://github.com/OpenPrinting/cups/wiki/CUPS-3.0)
- PAPPL, [v1.4.11 release source](https://github.com/michaelrsweet/pappl/tree/ad86a0a8473f0f83233a374226561181570d4f81)
- HP Printer Application, [macOS/PAPPL precedent](https://github.com/michaelrsweet/hp-printer-app/tree/b521969bd1ee558aacf952dfabc35dd10769e093)
- Apple, [DriverKit](https://developer.apple.com/documentation/driverkit) and [USBDriverKit](https://developer.apple.com/documentation/usbdriverkit)
- Apple, [Service Management](https://developer.apple.com/documentation/servicemanagement)
- Apple, [Notarizing macOS software before distribution](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
