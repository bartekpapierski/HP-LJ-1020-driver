# Personal service launch-boundary result

Date: 2026-08-31

Reference environment: macOS 26.6.1, Apple Silicon

Reference connection path: UGREEN Thunderbolt 4 dock

Final evidence: `/private/tmp/hplj1020-launch-boundary-evidence.rN8STa`

## Verdict

An administrator-installed legacy LaunchDaemon is a viable launch boundary for
the source-built **personal-use installation**. It runs the ad-hoc-signed PAPPL
provider machine-wide as the dedicated unprivileged `_hplj1020` account without
Developer ID signing or notarization.

This replaces the rejected app-bundled `SMAppService` LaunchDaemon only for the
personal-use installation. Preserve `SMAppService` for a future signed and
notarized **public binary release**.

## Final observed gates

- The pinned build used PAPPL 1.4.12 at commit
  `6db8e137557ad84662e78d24fdb2a591c621f4ac`, OpenSSL 3.6.3, and libusb
  1.0.30, with ad-hoc hardened-runtime signing.
- A partial installation containing the account, directories, and executables
  but no plist or loaded job converged through the normal install operation.
- The root-owned plist under `/Library/LaunchDaemons` started the root-owned
  provider executable under UID 499 (`_hplj1020`).
- The provider listened only on `127.0.0.1:8631`, `[::1]:8631`, and its
  UID-specific local socket. No non-loopback TCP listener was present.
- A standard macOS CUPS queue targeted
  `ipp://localhost:8631/ipp/print/LaunchBoundary`.
- A separate non-admin account submitted the CUPS test page; PAPPL accepted,
  rasterized, and completed one page into the file-backed evidence device.
- The dedicated service account discovered and claimed the reference HP
  LaserJet 1020 through the dock. The printer was in its pre-firmware identity,
  so the probe recorded `usb_probe_firmware_identity=absent`.
- USB claim succeeded without privilege. A privileged USB or firmware helper is
  unnecessary and remains unjustified.
- Complete uninstall removed the job, plist, executable/state/log trees, queue,
  and both prototype accounts. The absence audit passed.
- A clean reinstall repeated process identity, loopback listener, standard
  queue, non-admin job completion, and dedicated-account USB claim, followed by
  another passing final absence audit.
- Independent readback after the harness finished confirmed the launchd job,
  plist, product trees, accounts, and queue were absent.

## Architectural consequence

Release operations for the personal-use installation should use an explicit
administrator action to install a protected legacy LaunchDaemon plist and
root-owned payload, while the daemon itself runs as the dedicated unprivileged
account. Installation must create PAPPL's private state hierarchy, quote paths
containing spaces, converge from partial state, wait for the final service UID
and listener rather than launchd's temporary `xpcproxy`, and remove every owned
artifact on uninstall.

This prototype validates the launch, local printing, USB-access, and lifecycle
boundary. It does not broaden support beyond the reference Mac and dock, make a
direct-adapter support claim, redistribute firmware, or establish a public
binary release channel.
