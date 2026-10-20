# SPDX-License-Identifier: GPL-2.0-or-later
from __future__ import annotations

import hashlib
import io
import json
import stat
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from scripts import diagnostics as diag
from scripts import personal_install as install

NOW = 1800000000
SECRETS = ["PRIVATE-DOCUMENT-CONTENTS", "RASTER-PAYLOAD", "ZJSTREAM-PAYLOAD",
           "Confidential.pdf", "private-user", "password=secret", "FIRMWARE-CONTENTS",
           "unrelated-system-data", "SERIAL-123456789"]


def snapshot():
    return {"schemaVersion": "1.0.0", "time": NOW, "device": 6, "error": 0,
            "firmwareAvailable": True, "productVersion": "0.1.0",
            "dependencies": {"pappl": "1.4.12", "libusb": "1.0.30", "foo2zjs": "a" * 40},
            "private": SECRETS}


class Host:
    def __init__(self):
        self.raw = snapshot()
        self.log = json.dumps({"schemaVersion": "1.0.0", "time": NOW, "event": "job",
                               "state": 6, "error": 0, "bytesSent": 123,
                               "pagesCompleted": 1, "private": SECRETS}) + "\n"
        self.running = True
        self.queue = True
        self.calls = []

    def admin(self, *args, check=True):
        return self.run(list(args), check=check)

    def run(self, command, check=True):
        self.calls.append(command)
        code, output = 0, ""
        if command[0] == "/bin/dd":
            output = self.log if "service.log" in command[1] else json.dumps(self.raw)
            code = int(output is None)
        elif command[0] == "/bin/launchctl":
            code, output = (0, "pid = 123\n" + " ".join(SECRETS)) if self.running else (1, "")
        elif command[0] == "/usr/bin/lpstat":
            code, output = (0, f"printer {install.QUEUE} is idle.\n" + " ".join(SECRETS)) if self.queue else (1, "")
        else:
            code = 1
        return subprocess.CompletedProcess(command, code, output, " ".join(SECRETS))


class DiagnosticTests(unittest.TestCase):
    def test_local_status_and_actions(self):
        host = Host()
        result = diag.collect_status(host, now=NOW)
        self.assertEqual(result["device"], "ready")
        self.assertEqual(result["service"], "running")
        self.assertEqual(result["firmware"], "validated-local")
        self.assertEqual(result["deviceIdentity"]["serial"], "redacted")
        self.assertEqual(result["deviceIdentity"]["vendorId"], "03f0")
        self.assertEqual(result["connectionPath"]["route"], "unclassified")
        for code, name in enumerate(diag.ERRORS):
            host.raw["error"] = code
            result = diag.collect_status(host, now=NOW)
            self.assertEqual(result["error"], name)
            self.assertEqual(result["action"], diag.ACTIONS[code])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_stale_unavailable_and_stopped_do_not_claim_ready(self):
        host = Host()
        self.assertEqual(diag.collect_status(host, now=NOW + 6)["device"], "unknown")
        host.running = False
        self.assertEqual(diag.collect_status(host, now=NOW)["error"], "service-unavailable")
        self.assertEqual(diag.collect_status(host, now=NOW)["device"], "unknown")
        host.running = True
        host.queue = False
        self.assertEqual(diag.collect_status(host, now=NOW)["error"], "queue-unavailable")
        for raw in (None, [], {}, {"schemaVersion": "1.0.0", "time": True},
                    {**snapshot(), "device": True}, {**snapshot(), "error": -1}):
            self.assertEqual(diag.sanitize_snapshot(raw, NOW)["device"], "unknown")

    def test_archive_inventory_checksums_permissions_determinism_and_privacy(self):
        host = Host()
        host.log += " ".join(SECRETS) + "\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diagnostics.tar"
            diag.create_bundle(host, path, now=NOW)
            archive = path.read_bytes()
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            for secret in SECRETS:
                self.assertNotIn(secret.encode(), archive)
            with tarfile.open(path) as bundle:
                files = {item.name: bundle.extractfile(item).read() for item in bundle}
                for item in bundle.getmembers():
                    self.assertEqual((item.uid, item.gid, item.uname, item.gname, item.mtime), (0, 0, "", "", 0))
            self.assertEqual(set(files), {"manifest.json", "status.json", "checksums.sha256", "logs/service.jsonl"})
            manifest = json.loads(files["manifest.json"])
            self.assertEqual(manifest["inventoryVersion"], "1.0.0")
            self.assertIn("configuration/redacted.json", manifest["omitted"])
            for name, checksum in manifest["sha256"].items():
                self.assertEqual(hashlib.sha256(files[name]).hexdigest(), checksum)
            for line in files["checksums.sha256"].decode().splitlines():
                checksum, name = line.split("  ")
                self.assertEqual(hashlib.sha256(files[name]).hexdigest(), checksum)
            second = Path(directory) / "second.tar"
            diag.create_bundle(host, second, now=NOW)
            self.assertEqual(second.read_bytes(), archive)
            with self.assertRaises(FileExistsError):
                diag.create_bundle(host, second, now=NOW)

    def test_logs_reject_free_text_unknown_enums_types_and_expired_events(self):
        events = [
            {"schemaVersion": "1.0.0", "time": NOW - diag.MAX_LOG_AGE, "event": "service"},
            {"schemaVersion": "1.0.0", "time": NOW + 1, "event": "service"},
            {"schemaVersion": "1.0.0", "time": NOW, "event": "Confidential.pdf"},
            {"schemaVersion": "1.0.0", "time": NOW, "event": "job", "state": True},
            {"schemaVersion": "1.0.0", "time": NOW, "event": "job", "state": 200},
        ]
        self.assertEqual(diag.sanitize_logs("\n".join(map(json.dumps, events)), NOW), b"")
        raw = Host().log * 100000
        self.assertLessEqual(len(diag.sanitize_logs(raw, NOW)), diag.MAX_LOG_BYTES)

    def test_unavailable_logs_report_omission(self):
        host = Host()
        host.log = None
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.tar"
            diag.create_bundle(host, path, now=NOW)
            with tarfile.open(path) as bundle:
                manifest = json.load(bundle.extractfile("manifest.json"))
                self.assertIn("logs/service.jsonl", manifest["omitted"])
                self.assertNotIn("logs/service.jsonl", bundle.getnames())

    def test_cli_requires_explicit_output_and_status_never_creates_bundle(self):
        output = io.StringIO()
        self.assertEqual(install.main(["diagnostics"], stdout=output), 2)
        self.assertIn("--output", output.getvalue())

    def test_cli_status_is_read_only_and_bundle_is_explicit(self):
        host = Host()
        def runner(command, **kwargs):
            return host.run(command[1:] if command[0] == "/usr/bin/sudo" else command)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(diag.time, "time", return_value=NOW):
            output = io.StringIO()
            self.assertEqual(install.main(["status"], runner=runner, stdout=output), 0)
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertEqual(json.loads(output.getvalue())["device"], "ready")
            path = Path(directory) / "explicit.tar"
            self.assertEqual(install.main(["diagnostics", "--output", str(path)],
                                          runner=runner, stdout=io.StringIO()), 0)
            self.assertTrue(path.is_file())
        self.assertTrue(all(command[0] in (
            "/bin/dd", "/bin/test", "/bin/launchctl", "/usr/bin/lpstat")
            for command in host.calls))

    def test_privacy_on_known_fields_not_just_unknown_fields(self):
        for secret in SECRETS:
            raw = snapshot()
            raw.update(productVersion=secret, device=secret, error=secret)
            raw["dependencies"] = dict.fromkeys(("pappl", "libusb", "foo2zjs"), secret)
            self.assertNotIn(secret, json.dumps(diag.sanitize_snapshot(raw, NOW)))
            event = json.loads(Host().log)
            for key in ("time", "state", "error", "bytesSent", "pagesCompleted"):
                contaminated = {**event, key: secret}
                self.assertEqual(diag.sanitize_logs(json.dumps(contaminated), NOW), b"")


if __name__ == "__main__":
    unittest.main()
