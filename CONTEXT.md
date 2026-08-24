# HP LaserJet 1020 macOS Printing

This context defines the product language for making an HP LaserJet 1020 usable through the standard macOS printing experience.

## Language

**macOS printing solution**:
The open-source product that makes the HP LaserJet 1020 available through macOS's standard printer setup, print dialog, and print queue.
_Avoid_: Driver, utility, printing app

**reference printer**:
The specific HP LaserJet 1020 unit used to establish device identity, capabilities, and release behavior.
_Avoid_: Any LaserJet 1020-family printer, test printer

**reference Mac**:
The Apple Silicon Mac used as the primary compatibility and release-validation environment.
_Avoid_: All Macs, development machine

**connection path**:
One supported physical USB route between the reference Mac and reference printer: either a direct USB-A-to-USB-C adapter or the UGREEN Thunderbolt 4 dock.
_Avoid_: Connection type, USB mode

**basic printing milestone**:
The first usable release boundary: ordinary monochrome documents print through the standard macOS printing experience over every supported connection path.
_Avoid_: Prototype, minimal driver

**verified capability envelope**:
The complete set of printer behaviors confirmed by authoritative documentation, protocol evidence, and tests on the reference printer.
_Avoid_: All features, full support

**capability matrix**:
The evidence-backed record that maps every behavior in the verified capability envelope to its support and validation status.
_Avoid_: Feature list, checklist
