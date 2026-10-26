# Print quality validation — issue #38

Controls are implemented for local testing. Physical output remains unverified;
no support claim follows from IPP advertisement or matching encoder bytes.

| Control | IPP request | Input raster | Exact-model encoding |
| --- | --- | --- | --- |
| 600×600 with REt (default) | `print-quality=4` (normal) | 600×600, one bit per sample | 600×600 resolution, VIDEO_BPP=1, RET=MEDIUM |
| FastRes 1200 | `print-quality=5` (high) | 1200×600, one bit per sample | 600×600 resolution, VIDEO_BPP=2, VIDEO_X=RASTER_X/2, RET=MEDIUM |
| Density | integer `hplj-density=1..5`, default 3 | unchanged | PJL DENSITY=1..5 |
| EconoMode | boolean `hplj-economode`, default false | unchanged | PJL ECONOMODE=ON/OFF and page ZJI_ECONOMODE=1/0 |

FastRes accepts PWG Raster input. Apple Raster (URF) carries a single square
resolution, so its format-specific capabilities remain normal/600 dpi (`PQ4`,
`RS600`); high/asymmetric URF requests are rejected. Density and EconoMode work
in either raster format at its supported resolution.

`printer-resolution` describes the **input raster**, not native device dpi.
Resolution alone selects the matching quality; quality alone selects the matching
input resolution. When both are present they must agree. No request defaults to
true 600×600. Draft is unsupported; toner saving is the independent EconoMode
control. Native 1200×1200 is neither accepted nor advertised. Density and EconoMode
are independent in both quality modes. No host pixel thinning simulates toner saving.
Job messages name the selected mode, density, EconoMode, and source instruction.
Later device/recovery messages may replace the job message.

The authorities are the locally cached, hash-verified OpenPrinting/foo2zjs commit
`80499ed5bf6caa2963ad337e37cfda78a80aab1e`: exact-model
`PPD/HP-LaserJet_1020.ppd` lines 104–112 and 268–282, and `foo2zjs.c`
page items (648–675), PJL settings (838–840), and model-1 conversion (1864–1875).
See also the quality evidence in `docs/research/laserjet-1020-protocol.md`.
FastRes is the documented effective-quality name, not a claim that native optical
resolution increased. Pixel geometry truncates each physical sheet dimension
and margin at the horizontal input dpi and 600 vertical dpi. JBIG alone pads the
cropped raster width to 128 samples; VIDEO_X divides the unpadded width by BPP,
including odd widths, exactly as upstream does.

Host scenarios `SCN-QUALITY-ENCODING`, `SCN-DENSITY-ENCODING`, and
`SCN-ECONOMODE-ENCODING` compare all 20 mode × density × EconoMode combinations
against independently generated pinned-upstream stream hashes. The tiny codec
vector uses `-z1 -P -L0 -r{600,1200}x600 -g13x2 -p9 -T{1..5}` with/without `-t`;
only JobAttr4's timestamp is normalized. Production admission separately checks
physical geometry. Real PAPPL integration verifies advertised values, defaults,
quality-only/resolution-only selection, all 20 combinations, and device metadata.
`SCN-QUALITY-REJECTION` checks Validate-Job, Create-Job, and Print-Job rejection
of out-of-range, multi-valued, mistyped, unknown and conflicting requests, plus
header/request disagreement, with zero output on the fake device. Later invalid
pages abort without replaying earlier pages.

Physical scenarios `SCN-QUALITY-OUTPUT`, `SCN-DENSITY-OUTPUT`, and
`SCN-ECONOMODE-OUTPUT` use the 20 `CASE-QUALITY-*` corpus cases on **each** of the
direct USB-A-to-USB-C adapter and UGREEN Thunderbolt 4 dock. Print the public text
and fine-patterns page at A4 with 4 mm margins. Keep paper stock, scanner exposure,
scan resolution and auto-enhancement settings fixed; label each retained scan by
mode, density, and EconoMode outside the measured region. Include a 100 mm scale
reference and fiducials from the vectors/margins corpus in the same run.

Objective oracles: exact page count/order, 600×600 device metadata with the
expected VIDEO_BPP, scale error ≤1%, fiducial displacement ≤2 mm, correct
orientation, no clipping inside the 4 mm printable region. Record the mean
normalized darkness of identical solid and halftone patches for every setting;
compare each density against level 3 and each EconoMode-on page against its
mode/density-matched off page. Retain raw measurements and fixed-exposure scans;
no undocumented numerical density or effective-resolution threshold is invented.
Human inspection judges readable text/fine patterns, edge quality, no visible
corruption, banding or unexplained density discontinuities, and whether increasing
density darkens output and EconoMode reduces coverage without losing intended
content. Record a failed or indistinguishable effect explicitly; protocol bytes
alone cannot pass that control's physical scenario or justify a FastRes claim.

Retain sanitized output measurements and visual decisions using the existing
validation-manifest workflow, including source commit, dependency lock, macOS
version/build, printer and firmware identity, and connection path. Both paths
must pass every case and the dependent full-envelope gate (`VAL-011`) before any
support claim. All physical matrix rows remain unverified until then.
