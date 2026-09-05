# Third-party notices

This file records notices and terms for dependencies selected for the macOS
printing solution. No third-party source or binary is vendored at this stage.
When a component is incorporated, its complete, applicable notices and source
obligations remain in force; this inventory does not relicense any component.

## foo2zjs and bundled JBIG

Planned source adaptation: OpenPrinting `foo2zjs` commit
`80499ed5bf6caa2963ad337e37cfda78a80aab1e`.

`foo2zjs` states that the program began as Robert Szalai's `pbmtozjs`, uses
Markus Kuhn's JBIG-KIT compression library, and was overhauled by Rick
Richardson. `jbig.c` and `jbig_ar.c` are copyright 1995–2014 Markus Kuhn.
The source declares GNU GPL version 2 or later. The GPL version 2 text is in
`LICENSE`; the selected project boundary is GPL-2.0-or-later. Preserve every
upstream header and add a prominent modification notice to each adapted file.

The upstream `COPYING` file identifies HP-owned firmware and other proprietary
assets separately; none are included here. The exact pin, adaptation records,
and accepted `zjs.h` / unidentified `zjrca.h` provenance risk are in
`third_party/foo2zjs/`.

## PAPPL

PAPPL 1.4.12 is planned from commit
`6db8e137557ad84662e78d24fdb2a591c621f4ac`. Its NOTICE identifies copyright
© 2020–2026 Michael R Sweet, © 2007–2019 Apple Inc., and © 1997–2007 Easy
Software Products. PAPPL is Apache-2.0; the complete license text is in
`LICENSES/Apache-2.0.txt`.

PAPPL's NOTICE grants an optional exception for object-form embedded portions
from Apache sections 4(a), 4(b), and 4(d), and a GPLv2 `Combined Software`
exception for conflicting Apache sections. Preserve the upstream `LICENSE` and
`NOTICE` verbatim with any distributed PAPPL source or binary.

## libusb

libusb is planned as a dynamically linked dependency at 1.0.30. It is
LGPL-2.1-or-later; the complete license text is in
`LICENSES/LGPL-2.1-or-later.txt`. Its AUTHORS file credits Johannes Erdfelt,
Daniel Drake, Peter Stuge, Nathan Hjelm, Pete Batard, Ludovic Rousseau, Michael
Plante, Hans de Goede, Martin Pieuchot, Toby Gray, and Chris Dickens, plus its
listed contributors. Preserve libusb's complete AUTHORS and COPYING material,
and provide applicable source and relinking rights if it is distributed.
