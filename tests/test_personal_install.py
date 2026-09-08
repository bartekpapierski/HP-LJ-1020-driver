# SPDX-License-Identifier: GPL-2.0-or-later
"""Host-only integration tests for the personal-use lifecycle CLI."""

from __future__ import annotations

import io
import plistlib
import subprocess
import unittest
from unittest import mock

from scripts import personal_install as installer


class FakeMac:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.service_loaded = False
        self.service_disabled = False
        self.queue_present = False
        self.queue_enabled = True

    def __call__(self, command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        joined = " ".join(command)
        if "launchctl bootout" in joined:
            self.service_loaded = False
        if "launchctl bootstrap" in joined:
            self.service_loaded = True
        if "launchctl disable" in joined:
            self.service_disabled = True
        if "launchctl enable" in joined:
            self.service_disabled = False
        if "cupsdisable" in joined:
            self.queue_enabled = False
        if "lpadmin -p" in joined and " -E" in joined:
            self.queue_present = True
            self.queue_enabled = True
        if "lpadmin -x" in joined:
            self.queue_present = False
        if command[:3] == ["/usr/bin/sudo", "/usr/bin/test", "-e"]:
            return subprocess.CompletedProcess(command, 1, "", "")
        if command[:2] == ["/usr/sbin/pkgutil", "--pkg-info"]:
            return subprocess.CompletedProcess(command, 1, "", "")
        if command[:2] == ["/usr/bin/otool", "-L"]:
            output = (
                f"{command[-1]}:\n"
                "\t/usr/lib/libcups.2.dylib (compatibility version 2.0.0, current version 2.14.0)\n"
                "\t/opt/homebrew/opt/openssl@3/lib/libssl.3.dylib (compatibility version 3.0.0, current version 3.0.0)\n"
                "\t/opt/homebrew/opt/openssl@3/lib/libcrypto.3.dylib (compatibility version 3.0.0, current version 3.0.0)\n"
            )
            return subprocess.CompletedProcess(command, 0, output, "")
        if command[-3:] == ["-q", "user", "-a"]:
            return subprocess.CompletedProcess(command, 1, "", "")
        if command[:4] == ["/usr/bin/dscacheutil", "-q", "user", "-a"]:
            return subprocess.CompletedProcess(command, 1, "", "")
        if command[:4] == ["/usr/bin/dscacheutil", "-q", "group", "-a"]:
            return subprocess.CompletedProcess(command, 1, "", "")
        if command[:2] == ["/usr/bin/id", "-u"]:
            return subprocess.CompletedProcess(command, 0, "499\n", "")
        if "launchctl print-disabled" in joined:
            output = f'"{installer.SERVICE_LABEL}" => true\n' if self.service_disabled else ""
            return subprocess.CompletedProcess(command, 0, output, "")
        if "launchctl print" in joined:
            return subprocess.CompletedProcess(
                command, 0 if self.service_loaded else 1,
                "pid = 123\n" if self.service_loaded else "", ""
            )
        if command[:3] == ["/bin/ps", "-o", "uid="]:
            return subprocess.CompletedProcess(command, 0, "499\n", "")
        if command[:2] == ["/usr/bin/pgrep", "-P"]:
            return subprocess.CompletedProcess(command, 0, "124\n", "")
        if "/usr/sbin/lsof" in command:
            if "-p" not in command:
                return subprocess.CompletedProcess(command, 1, "", "")
            output = (
                "hplj1020 123 _hplj1020 TCP 127.0.0.1:8631 (LISTEN)\n"
                "hplj1020 123 _hplj1020 TCP [::1]:8631 (LISTEN)\n"
            )
            return subprocess.CompletedProcess(command, 0, output, "")
        if command[:2] == ["/usr/bin/lpstat", "-v"]:
            return subprocess.CompletedProcess(
                command,
                0 if self.queue_present else 1,
                ("device for HP_LaserJet_1020: "
                 "ipp://127.0.0.1:8631/ipp/print\n") if self.queue_present else "",
                "",
            )
        if command[:2] == ["/usr/bin/lpstat", "-p"]:
            return subprocess.CompletedProcess(
                command, 0 if self.queue_present else 1,
                ("printer HP_LaserJet_1020 is idle. enabled\n" if self.queue_enabled
                 else "printer HP_LaserJet_1020 disabled\n") if self.queue_present else "", ""
            )
        return subprocess.CompletedProcess(command, 0, "", "")


class ForeignInstallMac(FakeMac):
    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if (command[:3] == ["/usr/bin/sudo", "/usr/bin/test", "-e"]
                and command[-1] == installer.INSTALL_ROOT):
            self.commands.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:3] == ["/usr/bin/sudo", "/usr/bin/stat", "-f"]:
            self.commands.append(command)
            return subprocess.CompletedProcess(command, 0, "someone:staff:777\n", "")
        return super().__call__(command, **kwargs)


class ProductInstallMac(FakeMac):
    marker = f"{installer.INSTALL_ROOT}/.product-id"

    def __init__(self) -> None:
        super().__init__()
        self.service_loaded = True
        self.queue_present = True
        self.root_present = True

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["/usr/bin/sudo", "/bin/rm", "-rf"] and command[-1] == installer.INSTALL_ROOT:
            self.root_present = False
        if (command[:3] == ["/usr/bin/sudo", "/usr/bin/test", "-e"]
                and command[-1] in {installer.INSTALL_ROOT, self.marker}
                and self.root_present):
            self.commands.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:3] == ["/usr/bin/sudo", "/usr/bin/stat", "-f"]:
            self.commands.append(command)
            metadata = "root:wheel:644\n" if command[-1] == self.marker else "root:wheel:755\n"
            return subprocess.CompletedProcess(command, 0, metadata, "")
        if command[:3] == ["/usr/bin/sudo", "/usr/bin/find", installer.INSTALL_ROOT]:
            self.commands.append(command)
            return subprocess.CompletedProcess(command, 0, f"{self.marker}\n", "")
        if command[:3] == ["/usr/bin/sudo", "/bin/cat", self.marker]:
            self.commands.append(command)
            return subprocess.CompletedProcess(command, 0, f"{installer.RECEIPT}\n", "")
        return super().__call__(command, **kwargs)


class PersonalInstallTests(unittest.TestCase):
    def test_packaging_keeps_the_service_unprivileged_and_nested(self) -> None:
        service = plistlib.loads(installer.PLIST_SOURCE.read_bytes())
        info = plistlib.loads(
            (installer.APP_TEMPLATE / "Contents" / "Info.plist").read_bytes()
        )

        self.assertEqual(service["Label"], installer.SERVICE_LABEL)
        self.assertEqual(service["UserName"], installer.SERVICE_USER)
        self.assertEqual(service["GroupName"], installer.SERVICE_USER)
        self.assertEqual(info["CFBundleIdentifier"], installer.RECEIPT)
        executable = service["ProgramArguments"][0]
        self.assertEqual(
            executable,
            f"{installer.INSTALLED_APP}/Contents/Resources/hplj1020-service-supervisor",
        )
        self.assertFalse(service["KeepAlive"])
        supervisor = (
            installer.APP_TEMPLATE / "Contents" / "Resources"
            / "hplj1020-service-supervisor"
        ).read_text(encoding="utf-8")
        self.assertIn("for attempt in 1 2 3", supervisor)
        self.assertIn("CRASH_MARKER", supervisor)
        self.assertNotIn("sudo", supervisor)
        self.assertNotIn("sudo", " ".join(service["ProgramArguments"]))
        self.assertFalse(any("helper" in argument.lower() for argument in service["ProgramArguments"]))

    def test_install_preview_lists_every_machine_wide_mutation_without_running_commands(self) -> None:
        fake = FakeMac()
        output = io.StringIO()

        result = installer.main(["install"], runner=fake, stdout=output)

        self.assertEqual(result, 0)
        self.assertEqual(fake.commands, [])
        preview = output.getvalue()
        for mutation in (
            "create dedicated account _hplj1020",
            "create private state hierarchy",
            "install root-owned provider app",
            "install root-owned LaunchDaemon plist",
            "bootstrap LaunchDaemon",
            "create or reconcile queue HP_LaserJet_1020",
        ):
            self.assertIn(mutation, preview)
        self.assertIn("no privileged USB helper", preview)

    def test_dry_run_alias_never_runs_commands(self) -> None:
        fake = FakeMac()
        output = io.StringIO()

        result = installer.main(["install", "--dry-run"], runner=fake, stdout=output)

        self.assertEqual(result, 0)
        self.assertEqual(fake.commands, [])
        self.assertIn("No changes made", output.getvalue())

    def test_install_builds_and_signs_before_any_administrator_command(self) -> None:
        fake = FakeMac()
        output = io.StringIO()

        result = installer.main(
            ["install", "--apply", "--yes"],
            runner=fake,
            stdout=output,
        )

        self.assertEqual(result, 0, output.getvalue())
        sudo_index = next(index for index, command in enumerate(fake.commands) if command[0] == "/usr/bin/sudo")
        signing = [
            command for command in fake.commands[:sudo_index]
            if command[:2] == ["/usr/bin/codesign", "--force"]
        ]
        self.assertEqual(len(signing), 4)
        self.assertTrue(all("runtime" in command for command in signing))
        self.assertTrue(any("Contents/Frameworks/libssl.3.dylib" in command[-1] for command in signing))
        self.assertTrue(any("Contents/Frameworks/libcrypto.3.dylib" in command[-1] for command in signing))
        self.assertTrue(all(command[0] != "/usr/bin/sudo" for command in fake.commands[:sudo_index]))
        self.assertIn("state=enabled", output.getvalue())

    def test_uninstall_requires_confirmation_and_removes_only_fixed_product_artifacts(self) -> None:
        fake = ProductInstallMac()
        output = io.StringIO()

        refused = installer.main(["uninstall", "--apply"], runner=fake, stdout=output)
        self.assertEqual(refused, 2)
        self.assertEqual(fake.commands, [])

        result = installer.main(
            ["uninstall", "--apply", "--yes"], runner=fake, stdout=output
        )
        self.assertEqual(result, 0, output.getvalue())
        commands = [" ".join(command) for command in fake.commands]
        self.assertTrue(any("launchctl bootout system/com.bartekpapierski.hplj1020.service" in command for command in commands))
        self.assertTrue(any("lpadmin -x HP_LaserJet_1020" in command for command in commands))
        self.assertTrue(any("/Library/Application Support/HP-LJ-1020" in command for command in commands))
        self.assertFalse(any("/Library/Printers" in command or "/etc/cups" in command for command in commands))
        self.assertIn("state=clean", output.getvalue())
        self.assertTrue(any("test -e /Library/LaunchDaemons/" in command for command in commands))

    def test_clean_uninstall_performs_only_the_absence_audit(self) -> None:
        fake = FakeMac()
        output = io.StringIO()

        result = installer.main(
            ["uninstall", "--apply", "--yes"], runner=fake, stdout=output
        )

        self.assertEqual(result, 0)
        mutations = (
            "launchctl bootout", "lpadmin -x", "dscl . -delete", "/bin/rm -rf"
        )
        commands = [" ".join(command) for command in fake.commands]
        self.assertFalse(any(token in command for token in mutations for command in commands))
        self.assertIn("state=clean", output.getvalue())

    def test_reinstall_does_not_truncate_existing_logs(self) -> None:
        class ExistingLogsMac(FakeMac):
            def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                if (command[:3] == ["/usr/bin/sudo", "/usr/bin/test", "-e"]
                        and command[-1].startswith("/Library/Logs/HP-LJ-1020/")):
                    self.commands.append(command)
                    return subprocess.CompletedProcess(command, 0, "", "")
                if command[:3] == ["/usr/bin/sudo", "/usr/bin/stat", "-f"]:
                    self.commands.append(command)
                    mode = "600" if command[-1].endswith(".log") else "700"
                    return subprocess.CompletedProcess(
                        command, 0, f"_hplj1020:_hplj1020:{mode}\n", ""
                    )
                return super().__call__(command, **kwargs)

        fake = ExistingLogsMac()

        result = installer.main(
            ["install", "--apply", "--yes"],
            runner=fake,
            stdout=io.StringIO(),
        )

        self.assertEqual(result, 0)
        commands = [" ".join(command) for command in fake.commands]
        self.assertFalse(any("/dev/null /Library/Logs/HP-LJ-1020/" in command for command in commands))

    def test_install_refuses_a_foreign_collision_before_mutating_it(self) -> None:
        fake = ForeignInstallMac()
        output = io.StringIO()
        result = installer.main(
            ["install", "--apply", "--yes"], runner=fake, stdout=output
        )

        self.assertEqual(result, 1)
        self.assertIn("refusing foreign installed path", output.getvalue())
        commands = [" ".join(command) for command in fake.commands]
        self.assertFalse(any(" dscl . -create " in command for command in commands))
        self.assertFalse(any(" ditto " in command for command in commands))

    def test_uninstall_refuses_foreign_data_before_removal(self) -> None:
        fake = ForeignInstallMac()
        output = io.StringIO()
        result = installer.main(
            ["uninstall", "--apply", "--yes"], runner=fake, stdout=output
        )

        self.assertEqual(result, 1)
        commands = [" ".join(command) for command in fake.commands]
        self.assertFalse(any("rm -rf" in command for command in commands))

    def test_install_recovers_a_product_owned_group_only_account(self) -> None:
        marker = f"{installer.INSTALL_ROOT}/.product-id"

        class PartialAccountMac(FakeMac):
            def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                if (command[:3] == ["/usr/bin/sudo", "/usr/bin/test", "-e"]
                        and command[-1] in {installer.INSTALL_ROOT, marker}):
                    self.commands.append(command)
                    return subprocess.CompletedProcess(command, 0, "", "")
                if command[:3] == ["/usr/bin/sudo", "/usr/bin/stat", "-f"]:
                    self.commands.append(command)
                    metadata = "root:wheel:644\n" if command[-1] == marker else "root:wheel:755\n"
                    return subprocess.CompletedProcess(command, 0, metadata, "")
                if command[:3] == ["/usr/bin/sudo", "/usr/bin/find", installer.INSTALL_ROOT]:
                    self.commands.append(command)
                    return subprocess.CompletedProcess(command, 0, f"{marker}\n", "")
                if command[:3] == ["/usr/bin/sudo", "/bin/cat", marker]:
                    self.commands.append(command)
                    return subprocess.CompletedProcess(command, 0, f"{installer.RECEIPT}\n", "")
                if command[:4] == ["/usr/bin/dscacheutil", "-q", "group", "-a"]:
                    self.commands.append(command)
                    record = f"name: {installer.SERVICE_USER}\ngid: 499\n"
                    return subprocess.CompletedProcess(command, 0, record, "")
                return super().__call__(command, **kwargs)

        fake = PartialAccountMac()
        result = installer.main(
            ["install", "--apply", "--yes"], runner=fake, stdout=io.StringIO()
        )

        self.assertEqual(result, 0)
        commands = [" ".join(command) for command in fake.commands]
        self.assertTrue(any(f"dscl . -create /Users/{installer.SERVICE_USER}" in command for command in commands))
        self.assertFalse(any(f"dscl . -create /Groups/{installer.SERVICE_USER}" in command for command in commands))

    def test_readiness_rejects_a_disabled_queue(self) -> None:
        class DisabledQueueMac(FakeMac):
            def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                if command[:2] == ["/usr/bin/lpstat", "-p"]:
                    self.commands.append(command)
                    return subprocess.CompletedProcess(
                        command, 0, "printer HP_LaserJet_1020 disabled\n", ""
                    )
                return super().__call__(command, **kwargs)

        fake = DisabledQueueMac()
        output = io.StringIO()
        with mock.patch("scripts.personal_install.time.sleep"):
            result = installer.main(
                ["install", "--apply", "--yes"], runner=fake, stdout=output
            )

        self.assertEqual(result, 1)
        self.assertIn("readiness timed out", output.getvalue())
        self.assertFalse(fake.service_loaded)

    def test_uninstall_reports_all_remaining_artifacts(self) -> None:
        class ResidueMac(ProductInstallMac):
            removal_started = False

            def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                if command[:3] == ["/usr/bin/sudo", "/bin/rm", "-rf"]:
                    self.removal_started = True
                if (self.removal_started
                        and command[:3] == ["/usr/bin/sudo", "/usr/bin/test", "-e"]):
                    self.commands.append(command)
                    return subprocess.CompletedProcess(command, 0, "", "")
                return super().__call__(command, **kwargs)

        output = io.StringIO()
        result = installer.main(
            ["uninstall", "--apply", "--yes"], runner=ResidueMac(), stdout=output
        )

        self.assertEqual(result, 1)
        self.assertIn("removal residue:", output.getvalue())
        self.assertIn("/Library/Application Support/HP-LJ-1020", output.getvalue())

    def test_failed_queue_removal_keeps_marker_and_service_disabled_for_retry(self) -> None:
        class QueueRemovalFailureMac(ProductInstallMac):
            def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                if "/usr/sbin/lpadmin" in command and "-x" in command:
                    self.commands.append(command)
                    return subprocess.CompletedProcess(command, 1, "", "denied")
                return super().__call__(command, **kwargs)

        fake = QueueRemovalFailureMac()
        output = io.StringIO()
        result = installer.main(
            ["uninstall", "--apply", "--yes"], runner=fake, stdout=output
        )

        self.assertEqual(result, 1)
        self.assertTrue(fake.root_present)
        self.assertTrue(fake.service_disabled)
        commands = [" ".join(command) for command in fake.commands]
        self.assertFalse(any(f"/bin/rm -rf {installer.INSTALL_ROOT}" in command for command in commands))

    def test_disable_and_enable_use_the_same_fixed_service_and_queue(self) -> None:
        fake = ProductInstallMac()
        output = io.StringIO()

        self.assertEqual(
            installer.main(["disable", "--apply", "--yes"], runner=fake, stdout=output),
            0,
        )
        self.assertEqual(
            installer.main(["enable", "--apply", "--yes"], runner=fake, stdout=output),
            0,
        )

        commands = [" ".join(command) for command in fake.commands]
        self.assertTrue(any("lpadmin -p HP_LaserJet_1020 -o printer-is-shared=false -o printer-error-policy=stop-printer" in command for command in commands))
        self.assertTrue(any("launchctl disable system/com.bartekpapierski.hplj1020.service" in command for command in commands))
        self.assertTrue(any("launchctl enable system/com.bartekpapierski.hplj1020.service" in command for command in commands))
        self.assertIn("state=disabled", output.getvalue())
        self.assertIn("state=enabled", output.getvalue())

    def test_disable_stops_service_and_reports_a_failed_queue_hold(self) -> None:
        class FailedQueueHoldMac(ProductInstallMac):
            def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                if "/usr/sbin/cupsdisable" in command:
                    self.commands.append(command)
                    return subprocess.CompletedProcess(command, 1, "", "denied")
                return super().__call__(command, **kwargs)

        fake = FailedQueueHoldMac()
        output = io.StringIO()
        result = installer.main(
            ["disable", "--apply", "--yes"], runner=fake, stdout=output
        )

        self.assertEqual(result, 1)
        self.assertFalse(fake.service_loaded)
        self.assertIn("queue hold failed", output.getvalue())

    def test_disable_reports_an_orphaned_listener(self) -> None:
        class OrphanListenerMac(ProductInstallMac):
            def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                if "/usr/sbin/lsof" in command and "-p" not in command:
                    self.commands.append(command)
                    return subprocess.CompletedProcess(
                        command, 0, "hplj1020 321 _hplj1020 TCP 127.0.0.1:8631 (LISTEN)\n", ""
                    )
                return super().__call__(command, **kwargs)

        output = io.StringIO()
        result = installer.main(
            ["disable", "--apply", "--yes"], runner=OrphanListenerMac(), stdout=output
        )

        self.assertEqual(result, 1)
        self.assertIn("listener remains active", output.getvalue())


if __name__ == "__main__":
    unittest.main()
