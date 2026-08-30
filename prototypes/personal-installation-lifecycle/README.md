# Personal installation lifecycle evidence harness

This is a disposable macOS 26 arm64 prototype for issue #11. It tests the
selected personal-installation boundary before that boundary becomes product
architecture.

It answers four questions:

1. Can an ad-hoc-signed app register its bundled PAPPL provider as an
   `SMAppService` LaunchDaemon on the reference Mac?
2. Does the daemon run as the dedicated `_hplj1020` account and listen only on
   localhost?
3. Can a hidden non-admin account submit through a standard macOS CUPS queue?
4. Can the dedicated service account discover and claim the reference printer
   through PAPPL's public USB API without a privileged helper?

The harness deliberately stops the later checks if Service Management rejects
registration. A negative result is useful evidence; it means the ad-hoc
LaunchDaemon boundary must change. A failed USB discovery is not evidence for a
helper. Only a discovered device whose claim fails opens that investigation.

## Run

From the repository root:

```sh
./prototypes/personal-installation-lifecycle/wizard.sh
```

The wizard explains and confirms every system change before making it. macOS
will ask for an administrator password and may require approval under System
Settings → General → Login Items & Extensions. Connect the HP LaserJet 1020
through the reference UGREEN dock when prompted.

The final stage previews cleanup. The evidence directory remains under
`/private/tmp/hplj1020-lifecycle-evidence.*`; return that path with the result.

If a run stops before the cleanup stage, recover the exact prototype-owned
artifacts without rebuilding:

```sh
./prototypes/personal-installation-lifecycle/wizard.sh --cleanup-only
```

## Scope and safety

- Downloads checksum-pinned OpenSSL and libusb archives and a commit-pinned
  PAPPL checkout.
- Builds an arm64 app in a unique `/private/tmp` directory.
- Installs only `HP LJ 1020 Lifecycle Prototype.app` and prototype-owned state,
  log, CUPS queue, and hidden account names.
- Refuses to reuse or remove matching account names unless their prototype
  markers match.
- The USB probe claims and releases the device but sends no firmware or print
  data.
- This is feasibility evidence, not production installer code.
