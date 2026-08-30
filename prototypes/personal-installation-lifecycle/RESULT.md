# Personal installation lifecycle result

Date: 2026-08-30  
Reference environment: macOS 26.6.1, Apple Silicon  
Tested boundary: ad-hoc-signed app in `/Applications` with an embedded
`SMAppService` LaunchDaemon running as `_hplj1020`

## Verdict

The tested boundary is not viable for a personal source build. Service
Management accepted and submitted the embedded LaunchDaemon, but macOS launch
constraints prevented its ad-hoc-signed provider executable from starting.

The failure occurred before PAPPL executed:

- The installed app passed `codesign --verify --deep --strict`.
- launchd resolved `BundleProgram` to the expected executable inside the app.
- AMFI rejected that executable because it was ad-hoc signed or did not have a
  recognized certificate chain.
- launchd recorded `OS_REASON_CODESIGNING | Launch Constraint Violation`, then
  settled at `last exit code = 78: EX_CONFIG` and `job state = spawn failed`.
- The localhost listener, standard queue, non-admin submission, and dedicated
  account USB probe were therefore blocked, not failed.

This confirms the signing boundary documented by the macOS 26 Service
Management SDK: an app containing a LaunchDaemon must be notarized. Ad-hoc
signing is enough to validate bundle integrity but not enough to launch the
daemon.

## Architectural consequence

Do not use an `SMAppService` LaunchDaemon for the personal-use installation
unless the build is signed with an accepted identity and notarized. Keep that
path for a future public binary release.

The next personal-use experiment must test one explicit alternative:

1. a user-session Login Item or LaunchAgent, accepting that the provider runs
   only while the owner is logged in; or
2. an administrator-installed legacy LaunchDaemon in a protected system
   location, retaining the dedicated service account and testing whether the
   explicit admin installation satisfies launch policy.

No privileged USB helper is justified by this run because the provider never
reached USB discovery or claim. The helper decision remains gated on an actual
dedicated-account USB claim failure.
