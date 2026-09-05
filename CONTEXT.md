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

**validation contract**:
The evidence rules and test scenarios that a behavior, environment, or release must satisfy before it can be represented as verified.
_Avoid_: Test plan, quality checklist

**support claim**:
A statement that a specific behavior is verified in a named macOS version and applicable connection path under the validation contract.
_Avoid_: Expected compatibility, assumed support

**clean product state**:
A macOS environment with no artifacts owned by the macOS printing solution; it does not imply a fresh operating-system installation.
_Avoid_: Clean machine, fresh macOS installation

**personal-use installation**:
The currently supported deployment boundary: a locally built installation used only by the project owner on the reference Mac.
_Avoid_: Public release, generally available build

**personal release**:
A tagged source revision whose locally built personal-use installation is identified by a retained build manifest, dependency lock, artifact checksums, and validation evidence; it is not a published binary distribution.
_Avoid_: Public release, GitHub Release, installer download

**user-supplied firmware**:
The HP-owned, separately licensed binary the reference printer requires after power-on, acquired outside the macOS printing solution and retained only on the reference Mac.
_Avoid_: Bundled firmware, project firmware, redistributable firmware

**firmware-required state**:
A personal-use installation in which product artifacts are installed but printing is unavailable because no validated user-supplied firmware is present.
_Avoid_: Failed installation, ready installation

**public binary release**:
A prebuilt distribution intended for installation by people other than the project owner through the normal macOS trust and installation experience.
_Avoid_: Personal-use installation, source build
