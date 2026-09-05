# HP LaserJet 1020 macOS Printing Solution

This macOS printing solution is independent of, and not affiliated with or
endorsed by, HP, Apple, or OpenPrinting.

Original project code and the combined work containing the in-process
`foo2zjs`/JBIG encoder are licensed under GPL-2.0-or-later; see `LICENSE`.
It is supplied without warranty. Third-party ownership, notices, and license
terms are recorded in `THIRD_PARTY_NOTICES.md` and `LICENSES/`.

User-supplied firmware is proprietary, separately licensed, and excluded
from this repository, diagnostics, caches, source archives, and every release
artifact. A personal-use installation accepts only a lawfully obtained,
supported user-supplied firmware. Import does not grant any right
to redistribute the firmware. The imported firmware remains local to the
reference Mac and complete uninstall removes it and its metadata.

Support claims apply only to the reference printer, macOS version, and
connection path verified under the validation contract. This repository does
not currently produce a public binary release.

## Source provenance

`third_party/foo2zjs/adaptations.json` is the authoritative record for the
pinned upstream revision and every future adaptation. The known `zjs.h` /
`zjrca.h` provenance risk is accepted only for a personal-use installation and
gates any public binary release; see `third_party/foo2zjs/PROVENANCE.md`.
