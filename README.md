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

The production allow-list is intentionally empty until an exact firmware hash
and version/build identifier are accepted from reference-printer evidence. Host
tests exercise the import policy with synthetic bytes through a separate test
seam; they cannot enable production firmware import.

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
