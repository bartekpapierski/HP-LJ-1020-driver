# SPDX-License-Identifier: GPL-2.0-or-later
"""Behavioral tests for the host-only validation gate."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts import validation_gate as gate

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 64
COMMIT = "b" * 40
SCHEMA = (
    "https://bartekpapierski.github.io/HP-LJ-1020-driver/"
    "schemas/capability-matrix-1.0.0.json"
)


def attempt(number: int, outcome: str = "passed") -> dict[str, object]:
    return {
        "attempt": number,
        "outcome": outcome,
        "observedAt": "2026-09-05T10:00:00Z",
        "summary": outcome,
    }


def scenario(
    scenario_id: str = "SCN-ONE",
    requirement_ids: list[str] | None = None,
    state: str = "verified",
) -> dict[str, object]:
    return {
        "scenarioId": scenario_id,
        "behavior": "A required behavior",
        "milestone": "BASIC",
        "requirementIds": requirement_ids or ["VAL-001"],
        "provenance": ["Issue #9"],
        "environment": {
            "kind": "reference-mac",
            "macOSVersion": "26.6.1",
            "macOSBuild": "25G90",
            "architecture": "arm64",
        },
        "connectionPath": "host-only",
        "sourceCommit": COMMIT,
        "dependencyLockSha256": SHA,
        "printer": None,
        "expectedResult": "The behavior passes.",
        "observedResult": "The behavior passed.",
        "executedAt": "2026-09-05T10:00:00Z",
        "durationSeconds": 1,
        "evidence": [SHA],
        "state": state,
        "affectedScopes": ["validation-tooling"],
        "invalidatedBy": [],
        "attempts": [attempt(1)],
        "intermittencyExplanation": None,
        "reliabilityRequirements": None,
        "requiresArtifactEvidence": False,
    }


def matrix(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "$schema": SCHEMA,
        "schemaVersion": "1.0.0",
        "matrixVersion": 1,
        "scopeIdentities": {"validation-tooling": SHA},
        "scenarios": rows,
    }


def manifest(matrix_sha256: str) -> dict[str, object]:
    return {
        "$schema": (
            "https://bartekpapierski.github.io/HP-LJ-1020-driver/"
            "schemas/validation-manifest-1.0.0.json"
        ),
        "schemaVersion": "1.0.0",
        "runId": "run-1",
        "sourceCommit": COMMIT,
        "specificationCommit": COMMIT,
        "dependencyLockSha256": SHA,
        "buildManifestSha256": SHA,
        "capabilityMatrixSha256": matrix_sha256,
        "environment": {
            "kind": "reference-mac",
            "macOSVersion": "26.6.1",
            "macOSBuild": "25G90",
            "architecture": "arm64",
            "connectionPaths": ["host-only"],
        },
        "printer": None,
        "scopeIdentities": {"validation-tooling": SHA},
        "startedAt": "2026-09-05T10:00:00Z",
        "finishedAt": "2026-09-05T10:01:00Z",
        "result": "passed",
        "scenarioResults": [{
            "scenarioId": "SCN-ONE",
            "requirementIds": ["VAL-001"],
            "state": "verified",
            "summary": "passed",
            "observedAt": "2026-09-05T10:00:00Z",
            "evidenceSha256": [SHA],
            "attempts": [attempt(1)],
            "intermittencyExplanation": None,
            "reliabilityObservations": None,
        }],
        "evidence": [],
        "supportClaims": [{
            "scenarioId": "SCN-ONE",
            "statement": "A required behavior is supported.",
        }],
        "redacted": True,
        "sealed": True,
    }


class ValidationGateChecks(unittest.TestCase):
    def run_gate(
        self,
        rows: list[dict[str, object]],
        *,
        required_scenarios: set[str] | None = None,
        mutate_manifest=None,
        measurement_data: bytes | None = None,
        sanitized_log_data: bytes = b"validation passed\n",
        evidence_mode: int = 0o444,
        known_requirements: set[str] | None = None,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence_root = Path(temporary)
            primary_id = str(rows[0]["scenarioId"])
            primary_requirements = list(rows[0]["requirementIds"])
            measurement_document = {
                "$schema": (
                    "https://bartekpapierski.github.io/HP-LJ-1020-driver/"
                    "schemas/output-measurement-1.0.0.json"
                ),
                "schemaVersion": "1.0.0",
                "measurementId": "measurement-1",
                "scenarioId": primary_id,
                "sourceDocumentSha256": SHA,
                "measuredAt": "2026-09-05T10:00:00Z",
                "expected": {"pageCount": 1, "pageOrder": [1]},
                "observed": {
                    "pageCount": 1,
                    "pageOrder": [1],
                    "blankPages": [],
                    "partialPages": [],
                    "missingPages": [],
                    "duplicatePages": [],
                    "scaleErrorPercent": 0,
                    "maximumFiducialDisplacementMm": 0,
                    "clippingInsidePrintableRegion": False,
                    "orientationCorrect": True,
                    "mediaCorrect": True,
                },
                "visualInspection": {
                    "performed": True,
                    "finePatternsReadable": True,
                    "visibleCorruption": False,
                    "densityDiscontinuity": False,
                },
                "privacy": {
                    "documentContentsRetained": False,
                    "rasterPayloadRetained": False,
                    "zjStreamPayloadRetained": False,
                },
                "result": "passed",
            }
            evidence_files = (
                ("summary.txt", b"passed\n", "summary"),
                ("sanitized.log", sanitized_log_data, "sanitized-log"),
                (
                    "measurement.json",
                    measurement_data or (json.dumps(measurement_document) + "\n").encode(),
                    "measurement",
                ),
            )
            entries = []
            digests = []
            for path_value, content, kind in evidence_files:
                evidence = evidence_root / path_value
                evidence.write_bytes(content)
                evidence.chmod(evidence_mode if kind == "summary" else 0o444)
                digest = hashlib.sha256(content).hexdigest()
                digests.append(digest)
                entries.append({
                    "path": path_value,
                    "sha256": digest,
                    "kind": kind,
                    "immutable": True,
                    "result": "passed",
                    "privacyChecked": True,
                    "scenarioIds": [primary_id],
                })
            for row in rows:
                row["evidence"] = digests
            document = matrix(rows)
            matrix_bytes = gate.canonical_json(document)
            run = manifest(hashlib.sha256(matrix_bytes).hexdigest())
            run["dependencyLockSha256"] = SHA
            run["evidence"] = entries
            run["scenarioResults"][0]["scenarioId"] = primary_id
            run["scenarioResults"][0]["requirementIds"] = primary_requirements
            run["scenarioResults"][0]["evidenceSha256"] = digests
            run["supportClaims"][0]["scenarioId"] = primary_id
            if mutate_manifest is not None:
                mutate_manifest(run)
            gate.validate_gate(
                document,
                run,
                known_requirements=known_requirements or {
                    requirement
                    for row in rows
                    for requirement in row["requirementIds"]
                },
                required_scenarios=required_scenarios or {"SCN-ONE"},
                milestone="BASIC",
                evidence_root=evidence_root,
            )

    def test_passing_sealed_evidence_authorizes_a_support_claim(self) -> None:
        self.run_gate([scenario()])

    def test_missing_required_row_is_rejected(self) -> None:
        with self.assertRaisesRegex(gate.ValidationError, "missing required scenario"):
            self.run_gate([scenario()], required_scenarios={"SCN-ONE", "SCN-TWO"})

    def test_unknown_requirement_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(gate.ValidationError, "unknown requirement"):
            self.run_gate(
                [scenario(requirement_ids=["NOPE-999"])],
                known_requirements={"VAL-001"},
            )

    def test_unexplained_intermittency_is_rejected(self) -> None:
        row = scenario()
        row["attempts"] = [attempt(1), attempt(2, "failed")]
        with self.assertRaisesRegex(gate.ValidationError, "unexplained intermittency"):
            self.run_gate([row])

    def test_expired_affected_scope_is_rejected(self) -> None:
        def expire(run: dict[str, object]) -> None:
            run["scopeIdentities"]["validation-tooling"] = "c" * 64

        with self.assertRaisesRegex(gate.ValidationError, "expired evidence"):
            self.run_gate([scenario()], mutate_manifest=expire)

    def test_support_claim_without_a_passing_sealed_run_is_rejected(self) -> None:
        def unseal(run: dict[str, object]) -> None:
            run["sealed"] = False

        with self.assertRaisesRegex(gate.ValidationError, "support claim|sealed"):
            self.run_gate([scenario()], mutate_manifest=unseal)

    def test_support_claim_without_immutable_evidence_is_rejected(self) -> None:
        def make_mutable(run: dict[str, object]) -> None:
            run["evidence"][0]["immutable"] = False

        with self.assertRaisesRegex(gate.ValidationError, "immutable"):
            self.run_gate([scenario()], mutate_manifest=make_mutable)

    def test_writable_evidence_is_rejected(self) -> None:
        with self.assertRaisesRegex(gate.ValidationError, "is writable"):
            self.run_gate([scenario()], evidence_mode=0o644)

    def test_invalid_output_measurement_is_rejected_as_evidence(self) -> None:
        with self.assertRaisesRegex(gate.ValidationError, "output measurement"):
            self.run_gate([scenario()], measurement_data=b"{}")

    def test_failed_attempt_cannot_be_marked_verified(self) -> None:
        row = scenario()
        row["attempts"] = [attempt(1, "failed")]
        with self.assertRaisesRegex(gate.ValidationError, "failed attempt"):
            self.run_gate([row])

    def test_vm_evidence_cannot_pass_a_support_gate(self) -> None:
        def use_vm(run: dict[str, object]) -> None:
            run["environment"]["kind"] = "supplementary-vm"

        with self.assertRaisesRegex(gate.ValidationError, "VM evidence"):
            self.run_gate([scenario()], mutate_manifest=use_vm)

    def test_wrong_connection_path_is_rejected(self) -> None:
        def omit_path(run: dict[str, object]) -> None:
            run["environment"]["connectionPaths"] = []

        with self.assertRaisesRegex(gate.ValidationError, "connection path|connectionPaths"):
            self.run_gate([scenario()], mutate_manifest=omit_path)

    def test_reliability_gate_requires_five_passes_on_each_path(self) -> None:
        row = scenario("SCN-REPETITION-SOAK", ["VAL-012"])
        row["reliabilityRequirements"] = {
            "criticalTransitionPassesPerConnectionPath": {
                "ugreen-thunderbolt-4-dock": 5,
                "direct-usb-a-to-usb-c": 5,
            },
            "mixedDocumentSoakJobs": 20,
            "maximumServiceRestartsDuringSoak": 0,
            "lifecycleCycles": 3,
        }

        def insufficient(run: dict[str, object]) -> None:
            run["scenarioResults"][0]["reliabilityObservations"] = {
                "criticalTransitionPassesPerConnectionPath": {
                    "ugreen-thunderbolt-4-dock": 4,
                    "direct-usb-a-to-usb-c": 5,
                },
                "mixedDocumentSoakJobs": 20,
                "serviceRestartsDuringSoak": 0,
                "lifecycleCycles": 3,
            }

        with self.assertRaisesRegex(gate.ValidationError, "five passing repetitions"):
            self.run_gate(
                [row], required_scenarios={"SCN-REPETITION-SOAK"},
                mutate_manifest=insufficient,
            )

    def test_private_source_path_in_sanitized_log_is_rejected(self) -> None:
        with self.assertRaisesRegex(gate.ValidationError, "private source filename"):
            self.run_gate(
                [scenario()],
                sanitized_log_data=b"input=/Users/alice/Documents/private.pdf\n",
            )

    def test_evidence_for_another_scenario_is_rejected(self) -> None:
        def misbind(run: dict[str, object]) -> None:
            for evidence in run["evidence"]:
                evidence["scenarioIds"] = ["SCN-OTHER"]

        with self.assertRaisesRegex(gate.ValidationError, "unknown scenario binding"):
            self.run_gate([scenario()], mutate_manifest=misbind)

    def test_incomplete_environment_identity_is_rejected(self) -> None:
        def omit_build(run: dict[str, object]) -> None:
            del run["environment"]["macOSBuild"]

        with self.assertRaisesRegex(gate.ValidationError, "environment"):
            self.run_gate([scenario()], mutate_manifest=omit_build)

    def test_non_redacted_run_is_rejected_without_support_claims(self) -> None:
        def expose_run(run: dict[str, object]) -> None:
            run["supportClaims"] = []
            run["redacted"] = False

        with self.assertRaisesRegex(gate.ValidationError, "redacted"):
            self.run_gate([scenario()], mutate_manifest=expose_run)

    def test_missing_schema_identity_is_rejected(self) -> None:
        def omit_schema(run: dict[str, object]) -> None:
            del run["$schema"]

        with self.assertRaisesRegex(gate.ValidationError, "schema validation"):
            self.run_gate([scenario()], mutate_manifest=omit_schema)

    def test_undeclared_manifest_payload_is_rejected(self) -> None:
        def add_payload(run: dict[str, object]) -> None:
            run["firmwarePayload"] = "opaque bytes"

        with self.assertRaisesRegex(gate.ValidationError, "additional property"):
            self.run_gate([scenario()], mutate_manifest=add_payload)

    def test_invalid_run_timestamp_is_rejected(self) -> None:
        def break_timestamp(run: dict[str, object]) -> None:
            run["startedAt"] = "not-a-date"

        with self.assertRaisesRegex(gate.ValidationError, "date-time"):
            self.run_gate([scenario()], mutate_manifest=break_timestamp)

    def test_private_filename_in_manifest_summary_is_rejected(self) -> None:
        def expose_filename(run: dict[str, object]) -> None:
            run["scenarioResults"][0]["summary"] = "/Users/alice/private.pdf"

        with self.assertRaisesRegex(gate.ValidationError, "private source filename"):
            self.run_gate([scenario()], mutate_manifest=expose_filename)

    def test_hardware_scenario_requires_scan_or_photo_evidence(self) -> None:
        row = scenario()
        row["requiresArtifactEvidence"] = True
        with self.assertRaisesRegex(gate.ValidationError, "scan or photograph"):
            self.run_gate([row])


if __name__ == "__main__":
    unittest.main()
