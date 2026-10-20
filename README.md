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

The production allow-list currently contains one provisional exact image from
HP's HPLIP 3.26.4 plug-in, with its expected printer-reported version. It is
not a support claim until reference-printer validation passes. Host tests use
synthetic bytes through a separate test seam; no firmware is in this repository
or in release artifacts. Import requires the user's own lawful acquisition and
explicit acceptance of HP's separate terms.

Support claims apply only to the reference printer, macOS version, and
connection path verified under the validation contract. This repository does
not currently produce a public binary release.

## Development service

The PAPPL application runs in the foreground with every writable path supplied
explicitly. It binds only to `127.0.0.1:8631`, `[::1]:8631`, and the supplied
Unix socket, disables DNS-SD and the PAPPL web interface, and saves state on
shutdown:

```sh
build/hplj1020 --serve \
  --state "/Library/Application Support/HP-LJ-1020/state/system.state" \
  --spool "/Library/Application Support/HP-LJ-1020/spool" \
  --log "/Library/Logs/HP-LJ-1020/service.log" \
  --socket "/Library/Application Support/HP-LJ-1020/run/service.sock" \
  --device-uri file:///path/to/host-test-device
```

Queue reconciliation can be previewed or applied separately. It creates only
`HP_LaserJet_1020`, uses the loopback IPP Everywhere URI, treats an exact
existing queue as success, and refuses a same-name foreign queue:

```sh
python3 scripts/reconcile_macos_queue.py \
  --queue-name HP_LaserJet_1020 \
  --device-uri ipp://127.0.0.1:8631/ipp/print
sudo python3 scripts/reconcile_macos_queue.py \
  --queue-name HP_LaserJet_1020 \
  --device-uri ipp://127.0.0.1:8631/ipp/print \
  --apply
```

## Personal-use installation

The audited lifecycle command previews all machine-wide mutations by default.
Build and staging run as the invoking user; `sudo` is requested only after the
provider has been assembled and ad-hoc signed with hardened runtime. Review the
preview, then explicitly apply the same fixed operation:

```sh
python3 scripts/personal_install.py install
python3 scripts/personal_install.py install --apply --yes
```

The installed legacy LaunchDaemon runs the provider as the non-login
`_hplj1020` account. It installs a root-owned app bundle and plist, creates the
complete private state hierarchy, limits IPP to loopback, and reconciles only
the `HP_LaserJet_1020` queue. Readiness requires the final service UID, both
loopback listeners, and queue health; launchd's temporary root trampoline is
not accepted as ready. No privileged USB helper is installed.

Every lifecycle change has a preview and uses the same convergent command:

```sh
python3 scripts/personal_install.py disable
python3 scripts/personal_install.py disable --apply --yes
python3 scripts/personal_install.py enable
python3 scripts/personal_install.py enable --apply --yes
python3 scripts/personal_install.py uninstall
python3 scripts/personal_install.py uninstall --apply --yes
python3 scripts/personal_install.py status
```

Disable preserves product data. Complete uninstall requires explicit
confirmation, removes only the fixed product paths/account/queue/receipt, and
audits their absence. Failed operations leave the service disabled and report
the exact failed command or remaining artifacts. The local structured audit is
written under `build/personal-install/audit.jsonl`; it contains operation and
command metadata, never print or firmware contents.

### Importing user-supplied firmware

Read and accept the firmware's applicable HP terms before importing. The
command displays the ownership and redistribution disclosure before reading
input; `--affirm-lawful-acquisition` records your affirmation, not a new license.
It accepts only the exact supported image and does not download firmware.
With a personal-use installation present, import a lawfully acquired local
file as the service account (the invoking shell opens the source file):

```sh
cd /private/tmp
sudo -u _hplj1020 "/Library/Application Support/HP-LJ-1020/HP-LJ-1020.app/Contents/MacOS/hplj1020" \
  --import-firmware --firmware "/Library/Application Support/HP-LJ-1020/firmware" \
  --source "HP HPLIP 3.26.4; locally acquired under accepted HP terms" \
  --affirm-lawful-acquisition < /absolute/path/to/your/firmware
```

Do not commit the source file or private imported copy. After a printer power
cycle, bootstrap allows 10 seconds before firmware upload and another 10 seconds
before querying activation. Already-loaded matching firmware is not uploaded again.

## Validation artifacts

`validation/capability-matrix.json` is the machine-readable inventory of every
scenario named by the implementation specification. Update its required rows
and affected-scope identities with:

```sh
python3 scripts/update_capability_matrix.py
```

Validation runs remain local under the ignored `validation/runs/` directory.
Each passing run retains a sanitized log, output measurement, and result summary;
mark the sealed manifest and all referenced evidence read-only before gating.
Run the administrator-authorized reference Mac lifecycle workflow with:

```sh
./scripts/reference_lifecycle_validation.sh
```

The wizard creates a temporary hidden non-admin account for queue submission,
removes it after the final absence audit, and retains only redacted evidence.
It targets macOS 26.7.1 (25G241), preserves the previously accepted firmware in
private temporary storage outside the repository, and re-imports it between
uninstall cycles. Four A4 calibration pages require physical confirmation and
ruler measurements. After sealing, it restores the working installation and
removes its temporary firmware copy. On failure, that copy stays private for
recovery; retry with `--firmware-source PATH` if the installed copy is gone.
Use `--leave-uninstalled` only when restoration is unwanted. The synthetic PDF
fixture is public; its development-only generator requires ReportLab, but the
wizard does not.
Evaluate a run before making a milestone or support claim with:

```sh
python3 scripts/validation_gate.py \
  --matrix validation/capability-matrix.json \
  --manifest validation/runs/RUN_ID/manifest.json \
  --milestone BASIC \
  --evidence-root validation/runs/RUN_ID
```

The gate accepts only passing, sealed, redacted manifests whose immutable
evidence checksums and affected-scope identities still match. Validate output
measurement records with `python3 scripts/output_measurement.py RECORD.json`.
The synthetic inputs and print-control cases in `validation/golden-corpus/`
contain no private document content.

## Source provenance

`third_party/foo2zjs/adaptations.json` is the authoritative record for the
pinned upstream revision and every future adaptation. The known `zjs.h` /
`zjrca.h` provenance risk is accepted only for a personal-use installation and
gates any public binary release; see `third_party/foo2zjs/PROVENANCE.md`.

### Local personal-release operations

`VERSION` is the only product SemVer source. CMake embeds it in the provider;
app staging generates both bundle version fields from it. `scripts/build` records
an explicit deployment target (defaults to the installed SDK version; override
with `--deployment-target`). This target alone is not a support claim.

Run `python3 -B scripts/personal_release.py --archive-root /path/outside/checkout`
with one of these subcommands, in order:

1. `prepare`: require a clean candidate merged into `main`, verify the dependency
   lock and generated inputs, audit reachable source history, build/test, stage
   and ad-hoc sign the app, archive it with `ditto`, and capture the Apple toolchain
   and build configuration. Prints a new run ID before work starts. Retain it.
2. `hosted-ci-passed --run-id ID --ci-run GITHUB_RUN_ID`: query GitHub for a
   successful `push` run of `.github/workflows/ci.yml` on `main` at the exact
   commit, including the required `host-checks` job. Uses the authenticated `gh`
   CLI, with no credential copied into the record.
3. `locally-validated --run-id ID --manifest validation/runs/RUN/manifest.json
   --matrix validation/runs/RUN/capability-matrix.json --evidence-root /local/evidence`:
   require the complete `PERSONAL` validation contract on the reference Mac and
   both connection paths. The evidence manifest must identify the prepared
   `runs/ID/inputs/build-manifest.json` by checksum, the exact commit, and lock.
   Validation remains a separate operation; this command never fabricates passes.
4. `sealed --run-id ID --notes /path/to/reviewed-notes.md`: create the immutable
   local `releases/v0.x.y/` directory. Notes need `##` sections named Changes,
   Support claims, Known limitations, Firmware requirements, Lifecycle
   instructions, Validation results, Dependency changes, and Checksums. The last
   section can refer to `SHA256SUMS` beside the notes.
5. `tagged --run-id ID --manifest ... --matrix ... --evidence-root ...
   --signing-key /path/to/ssh-key --allowed-signers /path/to/allowed-signers`:
   explicitly authorize local tag creation after rechecking CI, validation, and
   the seal. Git verifies an unattached SSH-signed annotated tag object against
   the supplied allowed-signers file before creating `refs/tags/v0.x.y` with a
   create-only compare-and-swap. A conflicting tag is never moved or deleted.
6. `installed --run-id ID`: observe a separately completed installation. Verify
   installed files against the exact sealed ZIP, product ownership, service
   health, and queue readiness. This command does not deploy or rebuild a payload;
   installation/update/rollback must use the lifecycle operations.

Re-running a stage verifies its recorded inputs and checksums. `prepare --run-id
ID` resumes an already prepared candidate; incomplete preparation needs a new
run. Archive operations are serialized. Interrupted sealing can resume only when
its complete inventory matches the expected bundle. A rejected operation writes
a new immutable, redacted record under `failed/`, invalidates its attempt, and
requires a new run ID. Failure records retain no command output or private paths.

The sealed directory contains the app ZIP, a verified source Git bundle,
dependency lock (including patch hashes), build manifest, the original validated
build manifest, SPDX JSON SBOM, notices, reviewed release notes, repository-relative
validation pointers, and `SHA256SUMS`. The final manifest adds CI identity while
preserving the exact build identity used by local validation. Source-history and
payload checks reject known firmware/private paths and credential signatures;
only canonical app files enter the payload. Keep private print data and sensitive
diagnostics outside the source checkout. Notes and validation evidence must be
reviewed for redaction before promotion.

Retain small redacted records indefinitely, and at least current/previous sealed
payloads and compatible-state snapshots. During final promotion, retain the
redacted build manifest and capability result under `validation/releases/v0.x.y/`;
this tool never commits those records, pushes tags, publishes a GitHub Release,
or operates public binary signing/distribution. Issue #32 supplies the host-tested
operations; final reference-Mac validation and actual tag authorization belong to
the promotion issue.
