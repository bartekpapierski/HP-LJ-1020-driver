# Guided manual duplex — issue #39

Implemented for local experimentation; physical page order, reinsertion usability,
orientation and output quality remain unverified. No support claim is added.
The full-envelope gate (`SCN-CAPABILITY-GATE`) must pass before any claim.

Build with `scripts/build`, start the personal-use installation, then run from
an interactive terminal in the source checkout:

```sh
python3 scripts/manual_duplex.py document.pdf --binding long-edge --orientation portrait
```

The running installed provider must come from the same checkout as the helper.
Building alone does not replace the installed LaunchDaemon payload. If the
preflight says `hplj-service-instance` is missing, refresh the personal-use
installation through `scripts/personal_install.py update --tag TAG --apply --yes`
before retrying. The updater requires a clean checkout at the selected version
tag, including the duplex changes; `install` refuses to overwrite an existing
payload. Do not uninstall to work around this requirement, as that removes local
product data and user-supplied firmware. The preflight queries capabilities only; it submits no job and
runs before PDF rendering.

This explicit host workflow accepts 2–200 PDF pages, A4 plain paper, the main tray,
600 dpi, one copy, and long-edge or short-edge binding. It fits each PDF page
(including its intrinsic rotation) inside the 4 mm imageable area. `--orientation
landscape` adds a 90° composition rotation; physical feed axes stay A4 portrait.
Use portrait for PDFs whose own rotation already supplies the desired orientation.
Other media and composition controls are outside this workflow's current boundary.
The helper is built as `build/hplj1020-duplex-helper`; the controller is a
source-checkout command, not an installed print-dialog option.

The provider continues to advertise only `sides-supported=one-sided`.
`hplj-manual-duplex-workflow=experimental-host-guided-pdf` describes this separate
workflow, not a hardware duplex unit or a verified capability. Each pass is a
simplex IPP job, and every raster header and ZjStream remains simplex.
The terminal controller alone reports completion of the whole document. The
standard print queue shows each pass separately; a completed front job does not
mean the two-sided document completed.

## Ordering and reinsertion contract

Fronts print 1,3,5,… in ascending order. Face-down output puts the last front
on top. Keep this stack in order and put it in the main tray, printed sides down,
physical bottom edges feeding first. Empty unused paper from the tray first and
leave the priority slot empty. Do not submit other jobs until the workflow ends:
they can consume reinserted sheets. This source workflow does not reserve the
printer against other clients.

Backs print in descending sheet order. An odd final sheet receives a blank back:
for five pages, fronts are 1,3,5 and backs are blank,4,2. Retain the entire stack;
do not discard or reposition the odd sheet. The known blank is intentional.
For the fixed bottom-edge-first refeed, back rasters rotate 180° for portrait
long-edge and landscape short-edge, and 0° for the other two combinations.

The reinsertion convention follows the [HP user guide, printed pp. 32–33](https://www.hp.com/ctg/Manual/c00264334.pdf#page=41).
Long-edge back rotation and reverse even-page ordering follow pinned foo2zjs
`foo2zjs.c`'s `DMDUPLEX_MANUALLONG` path. These are implementation hypotheses
until confirmed on the reference printer through both connection paths.

## State, cancellation and recovery

Both raster passes are prepared in a private temporary directory before the
first job is created. The controller obtains an IPP job ID before sending a pass,
then polls until IPP reports completed. It never treats canceled, aborted,
missing or unknown jobs as successful. Only after front completion does it show
the refeed prompt; only the exact terminal response `REINSERTED` authorizes backs.
Inspect all front sheets before confirming. EOF, other input, Ctrl-C or the
reinsertion timeout leaves the document incomplete. The default timeout is 600
seconds per pass and for the prompt; network operations have additional bounded
I/O deadlines. `--timeout` changes the workflow deadline.

A failure, cancellation or timeout cancels the known active job when the same
service instance remains reachable; cancellation is best effort and can leave
partial physical output. The controller prints `incomplete`, returns nonzero,
and never retries a pass automatically. A per-service random instance identity
invalidates the workflow after a provider restart, even if completed job metadata
survives. IDs from the prior instance are never canceled against the new service.
There is no persisted resume token. A controller restart begins a fresh front
pass, requiring fresh paper and another confirmation. After an ungraceful process
exit, inspect/cancel any remaining queue job and remove partial sheets before a
fresh invocation. Temporary content is deleted on normal completion or handled
failure; an ungraceful kill may leave the private temporary directory for removal.

## Validation scenarios

Host simulations (`hplj1020-manual-duplex`) cover even/odd counts and the 100-sheet
boundary, both orientations and bindings, confirmation gating, cancellation,
front/back failure, timeout, interruption and provider restart. Native integration
(`hplj1020-duplex-integration`) renders synthetic PDFs, checks pixel bounds,
rotation and blank backs, verifies simplex-only advertisement, and submits both
passes through the real IPP/PAPPL pipeline to the fake device. These checks cannot
establish how sheets physically feed or land.

`SCN-MANUAL-DUPLEX-DIRECT` and `SCN-MANUAL-DUPLEX-DOCK` require all combinations
of even/odd count (2,3,4,5), portrait/landscape, and long-edge/short-edge on the
reference printer. Compose privacy-safe PDFs from the golden front/back artwork,
label every page with page number, sheet number, TOP and binding edge, and include
an asymmetric corner marker. Record front output order, stack arrangement,
refeed action, reverse output order, paired front/back page numbers, the odd
blank, and whether each side is upright when turned on the chosen binding edge.
Final sheets must contain 1/2,3/4,… in reading order, with no unexpected blanks,
duplicates or omissions. Ask the human operator to follow only the prompt and
record any ambiguity before offering assistance.

For each connection path also cancel before sending, during fronts, at the
prompt and during backs; let the prompt expire; restart the controller and the
provider at the prompt. Verify no backs before confirmation, no whole-document
success after partial output, no replay after restart, and a successful subsequent
fresh job. Repeat critical transitions five consecutive times per path. Retain
checksummed scans of both sides, objective scale (≤1%) and fiducial displacement
(≤2 mm) measurements, human inspection for clipping, readable fine patterns,
smearing, corruption, feed problems and orientation, plus the complete environment,
source revision, dependency lock and connection-path identity. Full-envelope
validation remains the release gate.
