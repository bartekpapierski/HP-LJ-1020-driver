# Reusable open-source implementations and license provenance

_Research date: 2026-08-24. This is an engineering provenance assessment, not legal advice._

## Question

Which maintained or historically relevant open-source components can lawfully and technically contribute to the HP LaserJet 1020 macOS printing solution?

## Decision

Use source-built [OpenPrinting `foo2zjs`](https://github.com/OpenPrinting/foo2zjs/tree/80499ed5bf6caa2963ad337e37cfda78a80aab1e) as the authoritative reusable implementation of the LaserJet 1020 ZjStream encoder, and use [PAPPL 1.4.12](https://github.com/michaelrsweet/pappl/tree/6db8e137557ad84662e78d24fdb2a591c621f4ac) plus [libusb](https://github.com/libusb/libusb) as the leading reusable macOS/USB foundation. Treat `cups-filters`, `libcupsfilters`, `libppd`, and `pappl-retrofit` as optional conversion or migration aids, not as a mandatory legacy stack.

Do **not** redistribute HP firmware, HPLIP plug-ins, Apple's `rasterToHPZJS`/`commandToHPZJS` binaries, or binaries copied from community driver repositories. Until firmware redistribution permission is explicit, the project must keep firmware out of the repository and releases and require a lawful, user-initiated acquisition step. If `foo2zjs` code is incorporated into one executable, license that combined work under a GPL-compatible license and publish complete corresponding source; if it remains a separate program, preserve the component's GPL notices and source while documenting the process boundary.

## Findings

### 1. `foo2zjs` is the open implementation to reuse

The OpenPrinting fork explicitly lists the HP LaserJet 1020 and implements the relevant `foo2zjs` encoder in C. Its model notes select the LaserJet 1018/1020/1022 variant, and its wrapper renders to monochrome PBM before calling `foo2zjs` with the model-specific `-P -z1 -L0` behavior. The bundled LaserJet 1020 PPD records 600×600 and 1200×600 modes, draft/toner saving, density, media sizes/types, sources, and manual copies. These are valuable protocol and capability hypotheses, but they still need validation against the reference printer before entering the verified capability envelope. See the pinned [`foo2zjs.c`](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/foo2zjs.c), [`foo2zjs-wrapper.in`](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/foo2zjs-wrapper.in), and [LaserJet 1020 PPD](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/PPD/HP-LaserJet_1020.ppd).

The encoder and wrapper declare GPL version 2 or later, and Debian's machine-readable provenance assigns GPL-2+ to the project, including its JBIG implementation. The upstream `COPYING` file separately identifies HP-owned firmware images before saying that "everything else" is GPL; it does not grant an open-source license for those images. The repository therefore provides a reusable open encoder but not a safely redistributable firmware payload. See [project licensing](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/COPYING) and [Debian provenance](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/debian/copyright).

The repository is not abandoned: OpenPrinting published release `20260206` and continued accepting fixes through August 2026. However, the LaserJet 1020's macOS integration is historical. Its macOS instructions date from the Xcode 3/MacPorts/Fink era, mention disabling System Integrity Protection, install into system CUPS paths, and launch an Objective-C polling hotplug tool from `/etc/rc.local`. That glue must not be carried forward. The useful boundary is the encoder and protocol knowledge, not its installer or daemon design. See the [current release](https://github.com/OpenPrinting/foo2zjs/releases/tag/20260206), [historical macOS instructions](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/INSTALL.osx), and [historical hotplug source](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/osx-hotplug/osx-hplj-hotplug.m).

Local reproducibility check: at the pinned commit, `foo2zjs.c` plus the bundled `jbig.c`/`jbig_ar.c` compiled with Apple Clang to a native arm64 Mach-O executable and reported its upstream version. The stock Makefile expected an external `libjbig`, so production packaging needs an explicit, reproducible dependency choice rather than relying on the old build defaults.

**Disposition:** reuse or port from source; pin a reviewed commit; add golden raster-to-ZjStream fixtures and reference-printer tests; replace the shell/PPD wrapper with typed option mapping in the eventual product.

### 2. Firmware is the unresolved proprietary boundary

Both open and vendor stacks agree that the printer needs firmware after power-up. The `foo2zjs` macOS instructions say to send `sihp1020.dl` after each power cycle, and its Linux hotplug script checks HP USB vendor/product `03f0:2b17`, waits for enumeration, and transfers the firmware through the CUPS USB backend. See [`INSTALL.osx`](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/INSTALL.osx) and [`hplj1000`](https://github.com/OpenPrinting/foo2zjs/blob/80499ed5bf6caa2963ad337e37cfda78a80aab1e/hplj1000).

HP's current device table lists “HP LaserJet 1020 Printer” as USB-only, monochrome, “Full (End of support),” with a required driver plug-in. In the versioned HPLIP 3.26.4 source release, `data/models/models.dat` likewise marks `fw-download=True`, `plugin=1`, `plugin-reason=1`, `tech-class=LJZjsMono`, and USB PID `2b17`. The generated PPD says that the device requires a proprietary plug-in. See HP's [supported-device table](https://developers.hp.com/hp-linux-imaging-and-printing/supported_devices/index) and the [versioned HPLIP 3.26.4 source release](https://sourceforge.net/projects/hplip/files/hplip/3.26.4/).

The matching HPLIP 3.26.4 plug-in archive contains `hp_laserjet_1020.fw.gz`, `lj-arm64.so`, and `lj-x86_64.so`. Its `plugin.spec` assigns both the firmware and LaserJet print plug-in to the 1020. Its `license.txt` grants use of one copy with HP products, forbids modification and disassembly, and says the software may not be assigned, sublicensed, or otherwise transferred. The shared objects are Linux ELF binaries, including AArch64, not macOS Mach-O binaries. Thus HPLIP is current evidence and a possible black-box comparison source, but its proprietary plug-in is neither an open-source dependency nor a macOS runtime. The inspected, versioned archive is published at the URL in HPLIP's official plug-in manifest: [HPLIP 3.26.4 plug-in](https://www.openprinting.org/download/printdriver/auxfiles/HP/plugins/hplip-3.26.4-plugin.run); HPLIP itself explains the open/proprietary split in its [source `COPYING`](https://sourceforge.net/projects/hplip/files/hplip/3.26.4/).

`foo2zjs`'s current `getweb` no longer retrieves the 1020 payload from HP; it points to a third-party tarball. That is not sufficient provenance for a public release. A checksum proves identity, not redistribution permission.

**Disposition:** never commit or attach the firmware to GitHub. For development, accept a user-supplied path and record its SHA-256 locally. Before release, choose one of: obtain written redistribution permission; or implement a user-initiated downloader/extractor that obtains the payload directly from an authoritative distributor, presents the applicable terms, and stores it outside the app bundle. That flow needs a separate legal/provenance decision; do not silently download from mirrors.

### 3. PAPPL and libusb are suitable modern foundations

PAPPL is a C framework for Printer Applications—the recommended replacement for classic CUPS drivers. Stable release 1.4.12 supports macOS, CUPS 2.2 or later, Apple/PWG Raster and raw jobs, USB output through libusb, and states that most development occurs on Intel and Apple Silicon Macs. This matches the reference Mac and its CUPS 2.3.x generation better than current PAPPL development, which is moving to newer libcups. See the [PAPPL 1.4.12 README](https://github.com/michaelrsweet/pappl/blob/6db8e137557ad84662e78d24fdb2a591c621f4ac/README.md) and [release](https://github.com/michaelrsweet/pappl/releases/tag/v1.4.12).

PAPPL's USB backend discovers USB printer-class interfaces, claims the bulk endpoints, reads IEEE-1284 identity, writes job data, and maps basic port status to IPP reasons. PAPPL also exposes registration of custom device schemes, so a firmware-aware device layer can be added without treating the old `osx-hplj-hotplug` process as the architecture. Whether the unbootstrapped reference printer presents exactly the interface PAPPL expects is a hardware-test question, not something this source audit can settle. See the pinned [USB backend](https://github.com/michaelrsweet/pappl/blob/6db8e137557ad84662e78d24fdb2a591c621f4ac/pappl/device-usb.c) and [device API](https://github.com/michaelrsweet/pappl/blob/6db8e137557ad84662e78d24fdb2a591c621f4ac/pappl/device.h).

PAPPL uses Apache-2.0 with explicit CUPS exceptions for combinations with GPLv2/LGPLv2 software. libusb supports macOS through IOKit and is LGPL-2.1-or-later. Both projects were actively updated in August 2026; libusb released 1.0.30 in May 2026. See the [PAPPL license and exception](https://github.com/michaelrsweet/pappl/blob/6db8e137557ad84662e78d24fdb2a591c621f4ac/NOTICE), [libusb README](https://github.com/libusb/libusb/blob/9cc77779237ed550bc1ae0f01ed3f3ab70aec8dc/README), [Darwin backend](https://github.com/libusb/libusb/blob/9cc77779237ed550bc1ae0f01ed3f3ab70aec8dc/libusb/os/darwin_usb.c), and [LGPL text](https://github.com/libusb/libusb/blob/9cc77779237ed550bc1ae0f01ed3f3ab70aec8dc/COPYING).

**Disposition:** prototype against PAPPL 1.4.12 and a pinned libusb release. Prefer dynamic linking for libusb and ship its notices/source offer as required. Prove device claim, detach/reconnect, dock/direct connection paths, firmware transfer, and status reads before committing to PAPPL as the final shell.

### 4. OpenPrinting conversion/retrofit libraries are useful but optional

`libcupsfilters` exposes print-filter functionality as library calls for PPD-less Printer Applications. `libppd` isolates legacy PPD handling. `pappl-retrofit` wraps classic PPD/filter/backend drivers as Printer Applications. All three use Apache-2.0 with the CUPS GPL2/LGPL2 exception and were active in August 2026. See [`libcupsfilters`](https://github.com/OpenPrinting/libcupsfilters/tree/b95e5a4703d5ccf5129ffe49b6646bd7fbce91cf), [`libppd`](https://github.com/OpenPrinting/libppd/tree/4afdca97f4d416d2a19345bf53b613095a69f679), and [`pappl-retrofit`](https://github.com/OpenPrinting/pappl-retrofit/tree/37e769c463c23cfeebe4f8935db1b1c417884b61).

The retrofit path could quickly prove that a classic foo2zjs PPD/filter chain can sit behind an IPP surface. It also retains the most fragile parts of the historical stack: PPD interpretation, external commands, shell-oriented Foomatic options, and more dependencies. Current `cups-filters` has had to add review/hash controls around executable Foomatic PPD values, demonstrating that this is a real attack surface. See the current [Foomatic source and allow-list tooling](https://github.com/OpenPrinting/cups-filters/tree/82acfaf1e1515555d570638875b819a213095b50/filter/foomatic-rip).

**Disposition:** use `pappl-retrofit` only for a throwaway feasibility comparison if it materially shortens the next decision. For production, prefer a direct raster-to-ZjStream callback with a fixed, typed capability mapping. Add `libcupsfilters` only for a conversion that macOS/PAPPL does not already supply.

### 5. Ghostscript works, but changes the license and supply-chain posture

The historical chain uses Ghostscript to turn PDF/PostScript into PBM, then passes PBM to `foo2zjs`. Current Ghostscript is maintained and capable, but the open release is AGPL-3.0-or-later (or commercially licensed), with additional third-party notices. Bundling a 37 MB anonymous `gs-static` binary, as one community repository does, is not acceptable provenance. See Artifex's [license](https://github.com/ArtifexSoftware/ghostpdl/blob/master/LICENSE), [licensing FAQ](https://ghostscript.com/faq/), and [official releases](https://ghostscript.com/releases/).

**Disposition:** avoid bundling Ghostscript unless the selected architecture proves it necessary and the whole distribution adopts a compatible license/compliance plan with reproducible source. Prefer the macOS/PAPPL raster path for the basic printing milestone.

### 6. Community macOS repositories are test leads, not source suppliers

Two recent repositories demonstrate that the hardware can still be driven, but neither is an acceptable provenance base:

- [`anxkhn/hp1020-driver-mac` at `f9d2f7e`](https://github.com/anxkhn/hp1020-driver-mac/tree/f9d2f7e2a22b7bfb80d4cb51e42de61c88f7dfdc) says it extracted Apple's `rasterToHPZJS`, `commandToHPZJS`, PPD, and firmware/ACL file from Apple's HP 5.1.1 package. The repository has no license grant or source for those proprietary artifacts. Its README claims universal binaries, but the inspected executables are thin x86_64 Mach-O files signed with HP team identifier `6HB5Y2QTA3`, so native Apple Silicon support is also misrepresented. Apple itself says HP 5.1.1 is not compatible with macOS 12 or later. See the [repository README](https://github.com/anxkhn/hp1020-driver-mac/blob/f9d2f7e2a22b7bfb80d4cb51e42de61c88f7dfdc/README.md) and [Apple's official download page](https://support.apple.com/en-us/106385).
- [`FZJ-SDU/hp-laserjet-1020-plus-macos-driver` at `9eb1c35`](https://github.com/FZJ-SDU/hp-laserjet-1020-plus-macos-driver/tree/9eb1c35fa79615ff513094b02da4cbfa8aef58dc) ships arm64 `foo2zjs` and Ghostscript binaries plus HP firmware. Its README labels the pieces GPL/AGPL/proprietary, but the repository supplies no corresponding source or build scripts for the binaries and no redistribution grant for the firmware. Its custom filter starts a background `lp -oraw` firmware job from inside another print job, creating ordering/race and recursion risks rather than a lifecycle-aware bootstrap.

**Disposition:** do not copy files, history, packaging, or install scripts from either repository. They may inform black-box test cases after independent reproduction from authoritative sources.

## License compatibility and packaging rules

| Component | License/provenance | Safe use in this project | Required posture |
| --- | --- | --- | --- |
| `foo2zjs` encoder, JBIG code, wrapper, 1020 PPD | GPL-2.0-or-later | Yes, from pinned source | Preserve notices; publish complete corresponding source and build scripts. A combined derivative must be GPL-compatible. |
| PAPPL | Apache-2.0 plus CUPS GPL2/LGPL2 exception | Yes | Preserve `LICENSE`/`NOTICE`; pin stable release. |
| libusb | LGPL-2.1-or-later | Yes | Prefer dynamic linking; preserve license and source/relink rights. |
| `libcupsfilters`, `libppd`, `pappl-retrofit`, current `cups-filters` | Apache-2.0 plus CUPS exception | Yes, if needed | Preserve notices; avoid pulling in the whole retrofit stack without a measured benefit. |
| Ghostscript | AGPL-3.0-or-later or commercial | Technically yes; avoid by default | If distributed, adopt a compatible project/compliance plan and reproducible corresponding source. |
| HPLIP open source | Per-file GPL v2/v3, MIT, BSD | Reference or selective source use only | Audit every copied file; do not assume one project-wide license. |
| HPLIP plug-in and firmware | HP proprietary plug-in terms; no transfer | No redistribution | User-acquired only unless HP grants redistribution permission. |
| Apple/HP legacy filters and ACL firmware | Proprietary binaries; no source/license grant found | No | Do not vendor, modify, sign, or redistribute. |
| Community prebuilt artifacts | Mixed/absent provenance | No | Reproduce functionality independently from upstream source. |

Two clean packaging choices remain available to the later architecture/license decision:

1. **Single copyleft work:** integrate the encoder with the application and license the combined source under GPL-2.0-or-later or a compatible later GPL version, while carrying Apache/LGPL notices and obligations. This is easiest to explain and audit.
2. **Separated components:** keep a permissively licensed application/framework and invoke an independently built GPL `foo2zjs` executable through a narrow raster/ZjStream process boundary. Distribute source and notices for both. Have counsel or an experienced open-source reviewer confirm that the designed boundary is genuinely separable before relying on this to keep the application permissively licensed.

A permissive clean-room ZjStream reimplementation is possible in principle, but it is not the shortest route to the basic printing milestone. If pursued later, write a protocol specification from public behavior and independently captured streams, keep the implementer away from GPL source, and record that process. Do not reverse-engineer HP/HPLIP/Apple binaries contrary to their terms.

## Implementation consequences for later decisions

1. Pin and vendor no binaries. Every shipped executable must come from a reproducible build whose source and license are recorded in an SBOM.
2. Start encoder validation with the pinned `foo2zjs` source and golden files; replace Foomatic shell composition with typed parameters.
3. Prototype PAPPL 1.4.12 + libusb on the reference Mac, but make firmware bootstrap and re-enumeration explicit state transitions around the reference printer.
4. Keep firmware outside Git, source archives, installer payloads, caches committed to CI, and GitHub Releases.
5. Compare output against HPLIP or Apple's legacy solution only on a user's lawfully installed copy; do not import their code or data.
6. Add automated license/SBOM generation and a `THIRD_PARTY_NOTICES` file before publishing any installer.

## Bottom line

There is enough maintained open source to build the macOS printing solution without shipping a proprietary print engine: `foo2zjs` supplies the proven ZjStream encoder, while PAPPL/libusb supply a current Apple-Silicon-capable application and USB layer. Firmware remains the one non-open payload and must be handled as user-acquired until redistribution rights are explicit. Recent community bundles prove interest and possible behavior, but their copied binaries and firmware would compromise the project's open-source and release provenance.
