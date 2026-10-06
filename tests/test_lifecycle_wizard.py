# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise the wizard's logging and process-identity boundaries without sudo."""

import os
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIZARD = (ROOT / "scripts/reference_lifecycle_validation.sh").read_text()


def functions_between(start: str, end: str) -> str:
    return WIZARD[WIZARD.index(start + "() {"):WIZARD.index(end + "() {")]


class LifecycleWizardChecks(unittest.TestCase):
    def test_monitor_does_not_assign_pre_exec_root_credentials_to_service(self):
        code = '''
ps() {
  if [[ "$*" == *ucomm* ]]; then
    printf '%s\\n' "0 32013 1 xpcproxy /bin/bash $INSTALL_ROOT/HP-LJ-1020.app/Contents/Resources/hplj1020-service-supervisor"
    printf '%s\\n' "499 32013 1 bash /bin/bash $INSTALL_ROOT/HP-LJ-1020.app/Contents/Resources/hplj1020-service-supervisor"
  else
    printf '%s\\n' "0 32013 1 /bin/bash $INSTALL_ROOT/HP-LJ-1020.app/Contents/Resources/hplj1020-service-supervisor"
    printf '%s\\n' "499 32013 1 /bin/bash $INSTALL_ROOT/HP-LJ-1020.app/Contents/Resources/hplj1020-service-supervisor"
  fi
}
'''
        code += functions_between("product_process_rows", "product_processes_are_unprivileged")
        code += "product_process_rows"
        result = subprocess.run(
            ["bash", "-c", code], check=True, capture_output=True, text=True,
            env={**os.environ, "INSTALL_ROOT": "/Library/Application Support/HP-LJ-1020"},
        )
        self.assertEqual(result.stdout.splitlines(), ["499 32013 1 supervisor"])

    def test_failed_process_snapshot_is_not_reported_as_root_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            code = '''
set -euo pipefail
ps() { return 1; }
'''
            code += functions_between("product_process_rows", "product_processes_are_unprivileged")
            code += functions_between("start_privilege_monitor", "on_exit")
            code += "start_privilege_monitor\nwait \"$PRIVILEGE_MONITOR_PID\" || true"
            subprocess.run(
                ["bash", "-c", code], check=True, timeout=5,
                env={**os.environ, "INSTALL_ROOT": "/Library/Application Support/HP-LJ-1020",
                     "EVIDENCE_ROOT": directory},
            )
            self.assertFalse((Path(directory) / "privilege-violation.txt").exists())
            self.assertTrue((Path(directory) / "privilege-monitor-failure.txt").exists())

    def test_monitor_retains_actual_root_identity_without_command_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            code = '''
set -euo pipefail
ps() {
  printf '%s\\n' "0 123 1 hplj1020 $INSTALL_ROOT/HP-LJ-1020.app/Contents/MacOS/hplj1020 --source private-secret"
  return 1
}
'''
            code += functions_between("product_process_rows", "product_processes_are_unprivileged")
            code += functions_between("start_privilege_monitor", "on_exit")
            code += "start_privilege_monitor\nwait \"$PRIVILEGE_MONITOR_PID\" || true"
            subprocess.run(
                ["bash", "-c", code], check=True, timeout=5,
                env={**os.environ, "INSTALL_ROOT": "/Library/Application Support/HP-LJ-1020",
                     "EVIDENCE_ROOT": directory},
            )
            violation = (Path(directory) / "privilege-violation.txt").read_text()
            self.assertIn("uid=0 pid=123 parentPid=1 role=provider", violation)
            self.assertNotIn("private-secret", violation)
            self.assertNotIn("--source", violation)
            self.assertNotIn("/Library/", violation)

    def test_partial_account_creation_cleans_only_created_records(self):
        for failed_field, expected_user_deletion in (("PrimaryGroupID", False), ("UniqueID", True)):
            with self.subTest(failed_field=failed_field), tempfile.TemporaryDirectory() as directory:
                log = Path(directory) / "commands"
                code = '''
set -e
VALIDATION_ACCOUNT_OWNED=0
VALIDATION_GROUP_CREATED=0
VALIDATION_USER_CREATED=0
id() { return 1; }
dscacheutil() { return 0; }
next_validation_id() { printf '599'; }
record() { :; }
sudo() {
  printf '%s\\n' "$*" >> "$COMMAND_LOG"
  [[ "$*" != *" $FAILED_FIELD "* ]]
}
'''
                code += functions_between("create_validation_account", "remove_validation_account")
                code += functions_between("remove_validation_account", "product_process_rows")
                code += "trap remove_validation_account EXIT\ncreate_validation_account"
                result = subprocess.run(
                    ["bash", "-c", code], capture_output=True, text=True,
                    env={**os.environ, "TEST_USER": "fixture-account", "TEST_REAL_NAME": "Fixture",
                         "COMMAND_LOG": str(log), "FAILED_FIELD": failed_field},
                )
                self.assertNotEqual(result.returncode, 0)
                commands = log.read_text()
                self.assertIn("dscl . -delete /Groups/fixture-account", commands)
                self.assertEqual("dscl . -delete /Users/fixture-account" in commands,
                                 expected_user_deletion)

    def test_non_admin_submission_receives_fixture_bytes_not_a_private_path(self):
        fixture = ROOT / "validation/fixtures/lifecycle-calibration.pdf"
        code = '''
sudo() {
  [[ "$PWD" == /private/tmp ]] || return 1
  [[ "$*" != *"$TEST_PAGE"* ]] || return 1
  shasum -a 256 | awk '{print $1}'
}
confirm() { return 0; }
record() { :; }
fail() { return 1; }
sanitize() { cat; }
OBSERVED_PAGES=0
'''
        code += functions_between("submit_non_admin_job", "preserve_private_firmware")
        code += "submit_non_admin_job"
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                ["bash", "-c", code], check=True, capture_output=True, text=True,
                env={**os.environ, "TEST_PAGE": str(fixture), "TEST_USER": "fixture-account",
                     "QUEUE": "fixture-queue", "LOG": str(Path(directory) / "log")},
            )
        self.assertEqual(result.stdout.strip(), hashlib.sha256(fixture.read_bytes()).hexdigest())

    def test_monitor_distinguishes_product_processes_from_sudo_wrappers(self):
        install = "/Library/Application Support/HP-LJ-1020"
        provider = install + "/HP-LJ-1020.app/Contents/MacOS/hplj1020"
        supervisor = install + "/HP-LJ-1020.app/Contents/Resources/hplj1020-service-supervisor"
        rows = [
            f"0 100 1 sudo sudo -u _hplj1020 {provider} --import-firmware",
            f"499 101 1 hplj1020 {provider} --serve",
            f"499 102 1 bash /bin/bash {supervisor}",
            f"0 103 1 hplj1020 {provider} --serve",
            f"501 104 1 unrelated unrelated {provider}",
            f"0 105 1 bash /bin/bash {supervisor}",
        ]
        code = ('ps() { printf "%s\\n" "$PROCESS_ROWS"; }\n' +
                functions_between("product_process_rows", "product_processes_are_unprivileged") +
                "product_process_rows")
        result = subprocess.run(
            ["bash", "-c", code], check=True, capture_output=True, text=True,
            env={**os.environ, "INSTALL_ROOT": install, "PROCESS_ROWS": "\n".join(rows)},
        )
        self.assertEqual(result.stdout.splitlines(), [
            "499 101 1 provider", "499 102 1 supervisor", "0 103 1 provider",
            "0 105 1 supervisor",
        ])

    def test_record_redacts_command_arguments_as_well_as_output(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log"
            code = (functions_between("sanitize", "run_recorded") +
                    'record "run: /Users/secret/Projects/driver/scripts/install secret _hplj1020 hplj1020-validation"')
            result = subprocess.run(
                ["bash", "-c", code], check=True, capture_output=True, text=True,
                env={**os.environ, "ROOT": "/Users/secret/Projects/driver", "USER": "secret",
                     "TEST_USER": "hplj1020-validation", "LOG": str(log)},
            )
            self.assertEqual(log.read_text(), result.stdout)
            self.assertNotIn("secret", result.stdout)
            self.assertNotIn("_hplj1020", result.stdout)
            self.assertNotIn("hplj1020-validation", result.stdout)
            self.assertIn("$REPOSITORY/scripts/install", result.stdout)


if __name__ == "__main__":
    unittest.main()
