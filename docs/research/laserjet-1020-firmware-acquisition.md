# LaserJet 1020 firmware acquisition boundary

_Checked 2026-09-26. Engineering provenance note, not legal advice._

## Finding

The absence of a standalone firmware download on HP's general support page does not mean HP offers no acquisition route. [HP's HPLIP device table](https://developers.hp.com/hp-linux-imaging-and-printing/supported_devices/index) identifies the original **HP LaserJet 1020 Printer** (distinct from the newer LaserJet Tank 1020) as USB-only with a required driver plug-in. [HP explains](https://developers.hp.com/hp-linux-imaging-and-printing/binary_plugin.html) that the HPLIP binary plug-in is proprietary, is obtained during Linux `hp-setup` or `hp-plugin`, and requires the user to read and accept its license. [HP's own plug-in download page](https://developers.hp.com/hp-linux-imaging-and-printing/plugins) links versioned, HP-hosted archives, including [3.26.4](https://developers.hp.com/sites/default/files/2026-05/hplip-3.26.4-plugin.run) and [3.26.6](https://developers.hp.com/sites/default/files/2026-09/hplip-3.26.6-plugin.run) as of this check.

The project's earlier [first-party archive inspection](open-source-provenance.md) recorded that the HPLIP 3.26.4 plug-in includes `hp_laserjet_1020.fw.gz`, with `plugin.spec` assigning it to this model. This is a *firmware source within a proprietary Linux plug-in*, not a standalone macOS firmware download or a macOS-compatible driver. The HPLIP archive release number is not a verified firmware build number. No production firmware SHA-256 or firmware-version identifier has been established by this source check.

## Exact 3.26.4 license review (2026-09-26)

I fetched the 3.26.4 archive from the [OpenPrinting URL listed in HPLIP's own versioned plug-in manifest](https://hplip.sourceforge.net/plugin.conf), because the [HP-hosted direct link](https://developers.hp.com/sites/default/files/2026-05/hplip-3.26.4-plugin.run) returned HTTP 403 to the reference Mac. The 11,493,127-byte archive's SHA-256 is `199f78f8af7f36894d7180e9090963ce2550a75ec701f8a4ba37665a9746fdf0`, exactly the value in manifest section `[3.26.4]`. I inspected its embedded `license.txt` and `plugin.spec` as read-only tar members; I did **not** run the installer or extract the firmware payload. [HP's plug-in page](https://developers.hp.com/hp-linux-imaging-and-printing/plugins) also lists the same version. These links identify the archive; the exact legal text is the `license.txt` *inside* that verified archive, not the page text.

The embedded terms say, in substance:

- §1 licenses **one copy** for use **with HP printing products only**; “Use” includes storing, loading, installing, and executing. It forbids modification and disabling license/control features. It does not expressly limit use to Linux, although [HP describes the plug-in as working with its Linux open-source printing software](https://developers.hp.com/hp-linux-imaging-and-printing/binary_plugin.html).
- §3 allows copies or adaptations only for archival purposes or when an essential step in authorized use, requires copyright notices on copies/adaptations, and bars copying onto a public network.
- §4 bars disassembly, decompilation, decryption, and reverse engineering absent HP's prior written consent, subject to limited jurisdictional exceptions. Neither ordinary archive-member extraction nor sending unmodified firmware to the identified printer requires investigating the binary's internals; whether selective extraction is an allowed “essential step” under §3 is not settled by the text.
- §5 forbids assignment, sublicensing, or other transfer of the terms or software. §§6–10 cover termination, export, warranty, and liability. The preamble says downloading **and installing** constitutes agreement; [HP's installation documentation](https://developers.hp.com/hp-linux-imaging-and-printing/binary_plugin.html) separately says the user must read and agree to the license at driver installation.

The archive's `plugin.spec` assigns `hp_laserjet_1020` to both `laserjet_print_plugin` and `firmware`, and specifies the firmware member as `data/firmware/$PRODUCT.fw.gz`. This supports compatibility of the candidate with the original 1020, not permission to repackage it. No text found expressly permits use of a single extracted firmware member with an independently written macOS driver; equally, the license grant itself contains no explicit OS restriction. That is a **legal interpretation risk**, not a technical fact we can resolve by testing. This note is not legal advice.

**Conservative project boundary:** do not bundle, commit, upload to evidence, redistribute, modify, or auto-fetch HP's archive or firmware. For an individual local experiment on the user's own HP LaserJet 1020, proceed only after the user has read the exact embedded license and explicitly accepted its terms and the extraction/independent-driver uncertainty. Keep the candidate and any installed copy outside the repository and accessible only locally; retain notices; do not reverse-engineer it. For a distributed acquisition/import feature or a public release that depends on this interpretation, obtain HP's written clarification or qualified legal review first.

## Consequence for the current reference run

The user read the exact embedded license and explicitly accepted its terms and
the extraction/independent-driver uncertainty in a local Terminal wizard on
2026-09-26. The wizard recorded only the verified archive digest and the two
acceptance flags in a private temporary file. No firmware entered Git or the
validation evidence. Streaming the LaserJet 1020 member yielded 128,999 bytes
with SHA-256 `9a6d03c858d9cf64ba86fdbe6cf0beec1297d2e45e606162b19f3857efae4ff4`.
The driver provisionally pins that exact image with expected printer-reported
version `20080222`, observed on the reference printer on 2026-10-06 after a
successful transfer and a 10-second wait before querying IEEE-1284 identity.
The earlier `20050309` expectation came from a different image's example in the
[foo2zjs `usb_printerid` manual](https://sources.debian.org/src/foo2zjs/20171202dfsg0-2/usb_printerid.1in)
and was not evidence for this digest. Without the wait, the immediate identity
query and both reconnect attempts timed out. The image is already PJL-enveloped;
no conversion or modification was performed. A subsequent cold-start probe using
the corrected production version and wait completed activation in one attempt,
reached `HPLJ_DEVICE_READY`, and read port status with `conditions=0`. A
direct USB-C print then produced the corrected-firmware test page (CUPS job 20)
and the previously held USB-C test page. Printing after a power cycle with the
service running still failed (jobs 21 and 22): active polling reproduced an
activation timeout in an isolated probe using the exact bundled USB library.
The same retained USB context recovered when queries waited until the green
ready light. Adding a 10-second pre-upload wait to the polling probe recovered
firmware `20080222` and status `conditions=0`; production now waits both before
upload and before querying activation. The user subsequently confirmed printing
after a power cycle with the service running on direct USB-C (job 23), printing
through the UGREEN dock (job 24), and dock power-cycle recovery (job 25).
These observations are not sealed full-lifecycle evidence and do not complete
issue #28's three-cycle, non-admin, privilege, removal, and recovery acceptance
criteria. Prior failed prints remain blocked results, not passing validation.
If the user wants a legally unambiguous path, seek HP's written permission or
another rights-cleared source.
