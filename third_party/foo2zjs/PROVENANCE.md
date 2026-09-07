# foo2zjs provenance

The only approved upstream source is OpenPrinting/foo2zjs commit
`80499ed5bf6caa2963ad337e37cfda78a80aab1e`:

<https://github.com/OpenPrinting/foo2zjs/tree/80499ed5bf6caa2963ad337e37cfda78a80aab1e>

The build compiles unmodified `jbig.c` and `jbig_ar.c` directly from the pinned,
hash-verified source archive. The in-process model-1 adapter is derived from
`foo2zjs.c` and recorded in `adaptations.json`; it retains the upstream license
history and a prominent `Modified by HP-LJ-1020-driver contributors` notice.
`upstream-files.json` records the audited upstream file hashes. No firmware or
third-party binary is vendored. Do not substitute the unsigned Quirinux mirror
or another revision.

## Accepted personal-use risk; public-release gate

Upstream `zjs.h` says some material came from an unidentified `zjrca.h`. Its
provenance could not be located. This risk is accepted only for a personal-use
installation. A public binary release is blocked until the risk
is resolved, the code is replaced, or a formal review explicitly accepts it.
