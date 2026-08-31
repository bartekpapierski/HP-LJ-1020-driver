# Personal service launch-boundary probe

This throwaway macOS 26 arm64 prototype answers one question for
"Prove a viable personal service launch boundary": can an administrator-installed
legacy LaunchDaemon run the source-built, ad-hoc-signed PAPPL provider as the
dedicated `_hplj1020` account without Developer ID signing or notarization?

It reuses the pinned PAPPL 1.4.12, OpenSSL 3.6.3, libusb 1.0.30, and USB probe
from the preceding lifecycle experiment. The only architectural variable is the
launch boundary: a root-owned executable under
`/Library/Application Support/HP-LJ-1020/Prototype/bin` and a root-owned plist
under `/Library/LaunchDaemons`.

## Run on the reference Mac

Connect the HP LaserJet 1020 through the UGREEN dock, power it on, then run from
the repository root:

```sh
./prototypes/service-launch-boundary/wizard.sh
```

The wizard builds from pinned sources, previews every system-owned artifact,
and asks before using `sudo`. It then exercises:

1. recovery from an installation interrupted after payload placement;
2. PAPPL process identity and a loopback-only listener;
3. a standard macOS queue and non-admin print submission;
4. dedicated-account USB discovery and claim;
5. complete uninstall with an absence audit; and
6. a clean reinstall followed by the same runtime checks and final uninstall.

Evidence remains in a unique
`/private/tmp/hplj1020-launch-boundary-evidence.*` directory. Send that path back
for review. If the wizard is interrupted, recover the exact prototype artifacts
with:

```sh
./prototypes/service-launch-boundary/wizard.sh --cleanup-only
```

## Safety boundary

- The probe never transmits firmware or print data to the USB printer. The
  standard queue targets PAPPL's file-backed test printer.
- It refuses to reuse or delete either account unless all prototype markers
  match.
- Cleanup targets only the named plist, queue, accounts, application-support
  tree, and log tree listed by the wizard.
- A USB helper remains forbidden unless the dedicated-account probe discovers
  the reference printer and specifically fails to claim it.
- This is feasibility evidence, not production installer code.
