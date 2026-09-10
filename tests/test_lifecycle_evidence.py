# SPDX-License-Identifier: GPL-2.0-or-later
from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from scripts import json_schema
from scripts import output_measurement
from scripts import seal_lifecycle_evidence as sealer


ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 64
COMMIT = "b" * 40


class LifecycleEvidenceChecks(unittest.TestCase):
    def test_seals_schema_valid_redacted_success_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "run"
            evidence.mkdir()
            (evidence / "sanitized.log").write_text(
                "[2026-09-10T20:00:00Z] lifecycle passed\n", encoding="utf-8"
            )

            sealer.seal(
                evidence,
                matrix_path=ROOT / "validation/capability-matrix.json",
                run_id="issue-28-test",
                started_at="2026-09-10T20:00:00Z",
                result="passed",
                reason="all lifecycle stages passed",
                source_commit=COMMIT,
                dependency_lock_sha256=SHA,
                printer_serial_sha256=SHA,
                source_document_sha256=SHA,
                lifecycle_cycles=3,
                observed_pages=4,
                macos_version="26.6.2",
                macos_build="25G83",
                scale_error_percent=0.4,
                maximum_fiducial_displacement_mm=1.2,
                artifact_sha256=SHA,
                built_at="2026-09-10T20:01:00Z",
                xcode_build="Xcode 26.6 (17F113)",
                compiler="Apple clang 21.0.0",
                sdk_build="25F70",
                deployment_target="26.0",
            )

            manifest = json.loads((evidence / "manifest.json").read_text())
            measurement = json.loads(next((evidence / "measurements").glob("*.json")).read_text())
            build_manifest = json.loads((evidence / "build-manifest.json").read_text())
            manifest_schema = json.loads(
                (ROOT / "docs/spec/validation-manifest.schema.json").read_text()
            )
            measurement_schema = json.loads(
                (ROOT / "docs/spec/output-measurement.schema.json").read_text()
            )
            build_manifest_schema = json.loads(
                (ROOT / "docs/spec/build-manifest.schema.json").read_text()
            )
            json_schema.validate(manifest, manifest_schema)
            json_schema.validate(measurement, measurement_schema)
            json_schema.validate(build_manifest, build_manifest_schema)
            output_measurement.validate_measurement(measurement)
            self.assertEqual(manifest["result"], "passed")
            self.assertTrue(manifest["sealed"])
            self.assertTrue(manifest["redacted"])
            for path in evidence.iterdir():
                self.assertFalse(path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
            (evidence / "measurements").chmod(0o700)
            evidence.chmod(0o700)

    def test_failed_run_is_also_summarized_and_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "run"
            evidence.mkdir()
            (evidence / "sanitized.log").write_text(
                "[2026-09-10T20:00:00Z] FAILED: install failed\n", encoding="utf-8"
            )

            sealer.seal(
                evidence,
                matrix_path=ROOT / "validation/capability-matrix.json",
                run_id="issue-28-failed",
                started_at="2026-09-10T20:00:00Z",
                result="failed",
                reason="install failed",
                source_commit=COMMIT,
                dependency_lock_sha256=SHA,
                printer_serial_sha256=None,
                source_document_sha256=SHA,
                lifecycle_cycles=0,
                observed_pages=0,
                macos_version="26.6.2",
                macos_build="25G83",
                scale_error_percent=0,
                maximum_fiducial_displacement_mm=0,
                artifact_sha256=SHA,
                built_at="2026-09-10T20:01:00Z",
                xcode_build="Xcode 26.6 (17F113)",
                compiler="Apple clang 21.0.0",
                sdk_build="25F70",
                deployment_target="26.0",
            )

            manifest = json.loads((evidence / "manifest.json").read_text())
            measurement = json.loads(next((evidence / "measurements").glob("*.json")).read_text())
            output_measurement.validate_measurement(measurement)
            self.assertEqual(manifest["result"], "failed")
            self.assertTrue(manifest["sealed"])
            self.assertIn("result=failed", (evidence / "summary.txt").read_text())
            (evidence / "measurements").chmod(0o700)
            evidence.chmod(0o700)


if __name__ == "__main__":
    unittest.main()
