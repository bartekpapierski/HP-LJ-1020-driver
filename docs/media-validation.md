# Media geometry and source validation — issue #36

Implementation is available for local testing. All physical scenarios remain
unverified. Passing host tests does not establish a support claim; full-envelope
validation must pass on the reference printer through both the direct USB-A-to-
USB-C adapter and UGREEN Thunderbolt 4 dock.

The canonical table is `src/media.c`, using exact-model pinned PPD paper codes
and PWG dimensions. It includes A4, Letter, Legal, Executive, A5, A6, JIS B5,
ISO B5, #10/C5/DL/Monarch envelopes, postcard, double postcard, 8.5×13-inch
foolscap, and 197×273 mm 16k. Envelope ISO B5 shares ISO B5 dimensions and uses
the single ISO B5 size entry. The PPD's rounded PostScript dimensions and its
incorrect ISO B5 imageable-area entry are not geometry authorities.

Custom media require explicit `media-col/media-size` dimensions in hundredths
of a millimeter: width 7600–21600, length 12700–35600, inclusive. Both sources
have the same documented dimensional range. Standard names must agree with
explicit dimensions. All four margins are 400; borderless, offsets, negative
margins, larger or impossible image boxes are rejected. Physical width and
length stay in feed axes: landscape and reverse orientations are client-side
composition within that sheet raster, not a rotated sheet-size declaration.
The pinned CUPS 2 conversion truncates each sheet dimension and margin to the
selected horizontal input dpi and 600 vertical dpi (see `docs/quality-validation.md`). ZjStream VIDEO/RASTER dimensions are the cropped printable region;
JBIG width alone is padded to a 128-pixel boundary, with white padding. Custom
paper uses code 256 as in the pinned model-1 path; no Minolta-specific custom
items are emitted.

`SCN-MEDIA-GEOMETRY` is host-only. Run the media and encoder contracts plus
real PAPPL media integration. Check every advertised size against CUPS and
ZjStream paper, resolution, printable dimensions, JBIG dimensions, and source.
Exercise exact limits, just-outside limits, rounding transitions, unknown names,
invalid margins, mismatched size/name/dimensions, rotated feed axes, explicit
source conflicts, and recovery with a valid next job. Rejected first pages must
produce no page bytes. Later invalid pages must abort without replaying pages
already sent. Small upstream codec goldens test clipping, bit polarity/order,
non-byte-aligned printable widths, and deterministic white padding independently
of physical-media admission.

`SCN-MEDIA-OUTPUT` requires a separate retained run on each connection path.
For each standard size and custom minimum/maximum, print a synthetic page at
600 dpi with a 100 mm reference line where it fits (50 mm on minimum sheets),
fiducials at known positions just inside each 4 mm margin, a labelled orientation
arrow, and marks immediately inside and outside the printable boundary. Include
portrait, landscape, reverse portrait, and reverse landscape client composition.
Also exercise a nonstandard interior size, e.g. 123×234 mm. Record requested
size, raster dimensions, selected source, paper code, and the expected clipping
rectangle. Pass only with exact page count/order, scale error ≤1%, fiducial
displacement ≤2 mm, correct orientation, no clipping inside the printable region,
no marks from outside it, and no corruption. Scan with a physical scale reference
for measurements; human inspection remains the artifact-quality oracle. Retain
redacted evidence through the existing output-measurement/validation-manifest
workflow with macOS build, source commit, lock, printer and firmware identity.

`SCN-MEDIA-SOURCE-SELECTION` also requires independent evidence on both paths.
Use visibly different synthetic sheets in the main tray and priority feed:

- `auto` → code 7; establish priority-sheet precedence and main-tray fallback.
- `main` → code 1; the job message instructs removal of priority-feed sheets.
  Verify printing from the main tray under that precondition. Separately record
  what happens with a priority sheet present; do not claim hardware isolation
  from the code alone.
- `manual` → code 4; the job message asks for one priority-feed sheet. Confirm
  the selected sheet, then test an empty priority feed, replenish one sheet,
  and verify safe completion. Cancel another job while waiting, then submit a
  new valid job. Observe actual device status rather than inventing a paper-out
  signal from the selected source. Verify no duplicate/blank page, safe explicit
  retry after any partial transmission, and subsequent printing without service
  restart or reinstall. Never deliberately induce a jam.

Record expected versus observed source and recovery outcomes, including a
source code ignored by the printer. Any mismatch fails the scenario and blocks
that support claim. Neither scenario changes to verified until the dependent
full-envelope validation accepts the evidence from both paths.
