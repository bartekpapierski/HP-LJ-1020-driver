# Connection-path validation audit: issues #30 and #31

## Current status (2026-10-20)

Work is paused at the owner's request; remaining physical checks are deferred.
Neither issue is complete. The chronological entries below preserve failures,
candidate changes and observations; later entries supersede earlier pending
statements for the same check.

Issue #30 now covers the actual direct UGREEN printer-to-USB-C cable. Separate
adapter acquisition and validation are excluded by the owner. One empty-tray
fault/reload/fresh-job test is accepted instead of five repetitions. The latest
installed paper-retry candidate passed that test's persistent warning and clean
reload/recovery output checks. Remaining scenarios and evidence are unverified;
prior revisions' physical results do not establish all checks on this revision.
Issue #31's complete dock validation remains outstanding. No broader path-support
claim or issue closure follows from these partial results.

Raw local runs are retained under ignored `validation/runs/` directories; this
committed audit is a narrative, not a sealed evidence bundle. Photos/scans and
final evidence sealing remain outstanding.

Audited 2026-10-07 against source commit
`75350bed95805e2cf47c34c74dade422f7b7671a` and sealed local run
`issue-28-20261007T182759Z`. Issue #28 establishes the personal installation
lifecycle. It does not complete either connection-path printing issue.

## Evidence already available

- All five entries in the lifecycle bundle's `checksums.txt` match.
- Its output measurement passes `scripts/output_measurement.py`: four A4
  calibration pages, maximum scale error 0.5%, maximum displacement 0 mm,
  and successful human inspection.
- The dock has three install/print/uninstall cycles. The direct path has a
  separate install/print/removal smoke test after a power-off/cable change.
- The direct-path check confirms the same reference printer by serial hash,
  USB VID/PID 03f0:2b17, and a different USB location from the dock.
- Dedicated-account execution, loopback listeners, no privileged helper,
  and preservation of unrelated queues and system CUPS passed.

These results cover lifecycle overlap only. Calibration pages are not the
golden corpus. The manifest's firmware version is null; adapter identity,
pre/post-firmware IEEE-1284 identity, and raw topology values are not retained.
The four-page measurement aggregates both paths rather than providing separate
corpus output records for each path. No scans or photographs are referenced.

## Remaining physical checks

Run separately for the UGREEN Thunderbolt 4 dock (#31) and direct
USB-A-to-USB-C adapter (#30). Keep the installed service running across device
recovery checks and the soak; record its process identity to detect restarts.

| Check | Required evidence |
| --- | --- |
| Path and device identity | Adapter/dock identity, topology, redacted printer identity and pre/post-firmware USB and IEEE-1284 identity; firmware version |
| Basic golden corpus | Text, vector/margin, raster and three-page documents through the standard queue and production raster/USB pipeline at true 600×600; document hashes and exact page order |
| Firmware-required behavior | Missing validated firmware produces actionable unavailable state; importing validated firmware allows a subsequent job |
| Cold bootstrap | Five consecutive power-cycle/bootstrap successes on each path, with output and no service restart |
| Already-loaded idempotence | Five consecutive observations that matching loaded firmware is not retransferred, followed by successful jobs |
| Disconnect/reconnect | Five consecutive recoveries on each path with subsequent jobs and no service restart |
| Sleep/wake | Five consecutive recoveries on each path with subsequent jobs and no service restart |
| Cancel before transmission | Five consecutive canceled jobs with zero job bytes and no page, followed by successful jobs |
| Cancel during transmission | Five consecutive cancellations with recorded byte-count/outcome and possible partial-page observation; no automatic replay, successful next job |
| Safe media faults | Empty tray, missing manual-feed media, observable cover-open, replenishment, and cancellation while waiting; five consecutive repetitions of applicable transitions and subsequent-job recovery; do not deliberately induce a jam |
| Mixed-document soak | 20 jobs per path, alternating text, vector/margins, raster and multi-page inputs; no service restart; record every result and page count/order |
| Output oracle | Per-path exact count/order; no unexplained blank, partial, missing or duplicate pages; no clipping in the declared printable region; scale error ≤1%; fiducial displacement ≤2 mm; correct media/orientation, readable fine patterns, no corruption or density discontinuity |
| Inspection artifacts | Human observations, measurements and checksummed scans/photos of synthetic output; no private job payloads |

Record timestamps, exact source/build/dependency identities, path, expected and
observed outcomes, and each repetition individually. Keep failed attempts.
An unexplained intermittent failure leaves the affected scenario unverified.
Do not infer direct-path success from dock evidence or mark a planned check
as executed. Seal new evidence separately; leave #28's bundle unchanged.

## Automated checks during this audit

- Golden-corpus coverage and source checksums pass.
- Implementation-spec checks pass in a clean committed source snapshot.
  Running them in the working checkout encounters generated C under the old
  ignored `build-stale-20260910T201019Z` directory.
- All 116 Python tests pass in that snapshot with the current built provider
  copied into its expected `build/hplj1020` location.
- CTest: 12 checks pass in the sandbox; loopback integration is sandbox-skipped.
  Its unsandboxed retry cannot bind port 8631 because the installed service
  occupies it. This retry does not establish an integration regression or a
  passing integration result.
- The BASIC validation gate rejects the lifecycle-only manifest: the first
  missing required row is `SCN-ACCOUNT-SAFETY`. The broader milestone remains
  unverified; #28's successful lifecycle result does not satisfy that gate.

Both issues remain open pending the physical checks above.

## Direct-path checks in progress

The initial golden-corpus run exposed a clipped bottom border and a 3 mm
vertical displacement. Raster inspection showed correct A4 geometry before
transmission. The driver had advertised zero margins despite the pinned
upstream PPD's 4 mm hardware margins. The candidate now advertises 4 mm and
updates existing saved media defaults. Human measurements on the installed
candidate confirmed a fully visible 200 × 287 mm rectangle and a top-left
circle 20 mm from both edges. This observation covers the reproduction;
the complete per-path output oracle is still pending.

The next mixed batch printed text and polygon only. Its provider became
unresponsive before grayscale and multi-page output. A live stack sample
shows the device monitor waiting for the printer lock while holding PAPPL's
system lock, and job completion waiting for the system lock. Device monitoring
has been moved from PAPPL's timer callback to a joined worker thread.

The updated source builds, passes the 12 non-network CTests, and passes the
full host integration test using an otherwise identical candidate with only
its listener port changed to 18631. Added contention coverage submits eight
jobs alongside HTTP requests with bounded timeouts. This stress check also
passed on the previous binary; it is not a deterministic reproduction of the
observed lock deadlock. The live stack sample remains the failure evidence.
Installation and physical corpus verification of the worker-thread candidate
are pending. Keep the failed runs separate from subsequent candidate evidence.

The first worker-thread installation attempt failed its test gate because
the integration service tried to bind production port 8631. The wizard restored
and enabled the previous app. One polygon printed during that attempt; it is
not evidence for the new candidate. CMake now builds the same service sources
as a separate integration executable on port 18631, while the production
executable retains port 8631. All 13 CTests pass with the restored production
provider running. Candidate installation and physical verification still
require the next completed run.

On 2026-10-11, the first physical empty-tray check exposed a status limitation.
On the restored direct topology, with both feeds empty, CUPS job 90/provider
job 46 was marked completed with one impression before physical output.
The human observed a blinking light and paper-feed attempts. Read-only USB
GET_PORT_STATUS returned `0x18` during that fault and again after replenishment;
the standard status byte did not expose paper-empty or error. Loading A4 paper
released the buffered page without a button press. Paper-wait reporting failed
this check; cancellation before transmission was not executed and must not be
claimed from this attempt. Further repetitions cannot establish the required
actionable state until a usable hardware-status mechanism is demonstrated.

The first physical cover-open check also failed actionable status reporting.
With paper loaded and the cartridge cover open, CUPS job 102/provider job 58
was reported completed with one impression, while the human confirmed no page
printed and an orange blinking light. USB GET_PORT_STATUS remained `0x18` and
the provider reported idle with no reasons. Closing the cover released the
buffered page automatically and cleared the orange light, as confirmed by the
human. Subsequent inspection confirmed the buffered page was clean and exactly
one additional clean page printed from recovery CUPS job 103/provider job 59,
without a provider restart. Neither physical fault can be inferred from the standard
status byte observed in these checks.

Current candidate progress supersedes the installation-pending notes above:
the worker-thread candidate was subsequently installed and its six-page corpus
passed human inspection. Five power cycles, five USB reconnects, five recorded
sleep/wake transitions (including DarkWake variants), and a 20-job/30-page soak
passed output inspection without a provider restart. All five cancellations
while USB was disconnected passed: zero reported impressions, no output on
reconnection, and one clean subsequent recovery page each. USB absence excludes
transmission during those cancellations; no transport-byte trace was captured.
These results do not establish cancellation during transmission, physical
fault reporting, or the remaining measurement and evidence requirements.

The human clarified the direct connection uses a UGREEN printer-to-USB-C cable,
with no separate USB-A-to-USB-C adapter. Earlier adapter descriptions were
assumptions and are superseded; the cable's exact model remains unspecified.
This establishes a direct-cable topology, not a separately tested adapter.
The human confirmed no separate adapter/USB-A printer cable is available.
Issue #30's explicit adapter verification boundary therefore remains unmet;
the direct-cable evidence is retained under its actual topology.
On A4, all four circle centers were measured 20 mm from their two nearest paper
edges: left/top coordinates (20,20), (190,20), (20,277), and (190,277) mm.
These match intended positions at the reported ruler precision; no measurement
uncertainty was supplied. Prior border measurements were 200 by 287 mm with
the complete border visible. Checksummed photos/scans remain outstanding.

A transfer-observability candidate now logs lifecycle state, cumulative bytes
sent and pages transmitted, without document or user names. Its integration
check verifies the completed byte count against actual fake-device output;
all 13 CTests passed. Physical installation and cancellation-during-transfer
validation are pending. Prior physical evidence belongs to the preceding
candidate and is preserved separately from the new transfer run.

The transfer-log candidate was installed and its Mach-O sections matched the
tested build. Five real during-transfer cancellations stopped after 262144,
327680, 393216, 393216 and 262144 bytes respectively, with zero complete pages
transmitted. The human confirmed no sheet from each canceled job and exactly
one clean subsequent recovery page, returning to idle. Provider PID 56134
remained unchanged. IPP job-impressions-completed reported one on a canceled
partial transfer despite zero complete pages in lifecycle metadata; that
counter must not be presented as physical page output.

Read-only descriptors show interface 0, alternate 0, printer class 7/subclass 1,
bidirectional protocol 2, bulk OUT endpoint 0x01 and bulk IN endpoint 0x81,
both 512-byte maximum packets. The existing transport reads only standard
control status and writes bulk OUT; whether bulk IN exposes usable fault
status remains unverified.

The corrected eight-second read-only windows drained the backlog and captured
current PJL status: closed/ready `10001 ONLINE=TRUE`, open `40021 ONLINE=FALSE`
in seven device/timed messages, then closed `10003 ONLINE=FALSE` (warm-up)
followed by `10001 ONLINE=TRUE`. GET_PORT_STATUS remained `0x18` throughout.
The initial 50-packet windows contained historical messages and are not used
to infer contemporaneous cover state. Sanitized probe summaries and capture
hashes are retained in the transfer run's `cover-input-probe.json`.

The PJL candidate drains bulk IN in bounded polls and parses only framed
device/timed/status messages. It handles fragmented/concatenated input, rejects
malformed and oversized frames, ignores job/page messages, resets on USB release,
maps observed `40021` to cover-open, and otherwise retains conservative generic
fault/offline reporting. A partially drained backlog cannot establish ready.
The captured cover-open fixture failed before the parser implementation and
passed afterward; all 14 CTests pass. Physical installation and five cover
checks remain pending. Paper-empty PJL codes and physical-completion handling
are not established by this cover-only candidate.

The PJL candidate was installed with matching Mach-O sections. All five
cover-open/closure repetitions passed on the direct UGREEN USB-C cable:
CUPS jobs 116–120/provider jobs 72–76 reported `cover-open`, waited with
`close the printer cover` and zero impressions, produced no page while open,
then automatically printed exactly one clean page after closure. Each final
status had no fault reasons; provider PID 60622 remained unchanged. This
supersedes the earlier failed cover reporting for this submitted-while-open
scenario; the failure evidence remains retained. Empty-tray reporting and
faults appearing after transmission remain unverified on this candidate.

The cover-only candidate still completed CUPS job 121/provider job 77 before
physical output while both feeds were empty. The eight-second probe captured
PJL `41004 ONLINE=FALSE` with standard status `0x18`. After reloading A4,
the sheet stopped halfway entering from the input tray with orange blinking.
The human cleared the stopped sheet via the cartridge door, reloaded paper,
and confirmed one clean text page and normal lights. This required physical
intervention and does not pass unattended empty-tray recovery.

The next, not-yet-installed candidate maps foreground paper-load codes and
keeps transmitted pages pending until a successful PJL document-end report.
Connection changes or absent completion require explicit retry. Regression
checks cover delayed completion and paper faults appearing after transmission;
all 14 CTests passed. Physical behavior remains unverified on this candidate.

The output-status candidate was installed in run
`issue-30-20261011-output-status`; all ten compared Mach-O sections match
the tested build. CUPS job 122/provider job 78 completed, and the human
confirmed exactly one clean text page. Provider PID 65702 runs as UID 499;
the printer is idle with no fault reasons on the direct-cable topology.
Empty-tray behavior on this installed candidate is the next physical check.

Output-status candidate empty-tray repetition 1: CUPS 123/provider 79
remained processing while the human confirmed constant paper-feed attempts.
At 20:25:44 UTC the job message was waiting for output completion; at
20:26:21 the printer briefly reported offline and clear the printer fault,
then at 20:26:31 reported no reasons, still processing. No media-empty
reason was observed during these snapshots. Fault reporting therefore has
not passed; reload recovery and its completion acknowledgement are pending.

After reload the human reported one automatically printed page and normal
lights. Provider job 79 was completed at 20:27:35 UTC; PID 65702 remained
unchanged. The fresh recovery CUPS 124/provider 80 also completed and the
printer returned idle with no reasons. Human confirmation of both pages
being clean is pending. This establishes automatic reload output for one
attempt, but does not repair the observed missing media-empty reporting.

The human confirmed one additional recovery page printed, without an
explicit cleanliness confirmation. A separate diagnostics candidate now
records changes in validated numeric PJL code, ONLINE flag and mapped
condition bits through the existing retained service log. No raw PJL display,
document or user text is logged. All 14 CTests, style and implementation-spec
checks pass; native installation and another controlled fault attempt are
pending. No hypothesis about the missing paper reason is yet established.

Numeric status diagnostics were installed in
`issue-30-20261011-status-diagnostics`, with all compared Mach-O sections
matching. Provider PID 68027 runs as UID 499. Provider job 81 transferred
6843 bytes and completed after the printer status changed from processing
10023/ONLINE true to ready 10001/ONLINE true. The human reported one page
printed; cleanliness is awaiting explicit confirmation. The bounded collector
is recording numeric status transitions without errors. Another empty-tray
attempt is being prepared; no paper-status pass is claimed.

The diagnostic attempt CUPS 126/provider 82 captured repeated status
transitions while feeds remained empty: 41004/ONLINE false/conditions 1
(paper empty), then 10023/ONLINE true/conditions 0 (processing), and
10003/ONLINE false/conditions 2 (warm-up). Bytes stayed 6843 and the
job remained pending. The parser cleared the load request on transient
processing/warm-up messages, explaining the inconsistent paper-empty reason.
The transition evidence is retained in `empty-tray-retry-transitions.json`.
A regression reproducing this sequence failed before the correction. The
new candidate retains paper-load conditions through these transient states
and clears them on explicit ready 10001/ONLINE true. It is not installed;
physical recovery of the diagnostic attempt is pending.

The paper-retry candidate was installed in
`issue-30-20261011-paper-retry`, with all compared Mach-O sections matching
the tested build. Provider PID 69836 runs as UID 499. Provider job 83
completed after a ready status (10001/ONLINE true); the human reported one
page printed, without explicit cleanliness confirmation. The printer is
idle with no fault reasons. Five empty-tray repetitions on this candidate
remain unverified; the first is being prepared.

Paper-retry verification 1/5: CUPS 128/provider 84 transmitted 6843 bytes
and remained pending. PJL 41004 established paper empty; subsequent 10003
and 10023 retained conditions=1 through repeated feed retries. At
20:35:19 UTC IPP reported media-empty,media-needed and job message load paper.
This confirms fault persistence for this waiting interval, unlike earlier
candidates. Human no-output confirmation, reload recovery and clean subsequent
job remain pending; this repetition is not yet a complete pass.

Verification 1 reload: human reports one page printed. At 20:36:19 UTC
provider job 84 was completed, printer idle with no fault reasons and
provider PID 69836 unchanged. A fresh recovery CUPS job 129 was submitted.
Explicit cleanliness/count confirmation for both pages remains pending.

The human explicitly confirmed both verification 1 pages were clean,
exactly one from the buffered job and one from the fresh recovery. Ready
10001/ONLINE true cleared the paper condition, and CUPS 129 also left
the queue with printer idle. This passes observed paper-fault persistence,
automatic reload output and fresh-job recovery for one repetition.
Separate explicit no-sheet-while-empty confirmation was not supplied.

The human explicitly requested skipping repeated empty-tray checks due to
limited time and accepts one test. Repetitions 2–5 are intentionally not
performed; no job for repetition 2 was submitted. Retain the single successful
fault-persistence/reload/fresh-job result without claiming five repetitions
or satisfaction of the original full issue acceptance gate. No further
empty-tray printing is authorized by this continuation.

Owner scope revision on 2026-10-11: separate USB-A-to-USB-C adapter
checks and acquisition are excluded permanently at the owner’s request.
Issue #30 now targets the actual direct UGREEN printer-to-USB-C cable.
The missing adapter is no longer a closure blocker under this revised scope;
no separate-adapter support claim is established. Other outstanding required
scenarios/evidence remain, including the unfinished dock validation in #31.
The earlier empty-tray repetition waiver is also reflected in #30.
