# SPDX-License-Identifier: GPL-2.0-or-later
"""Behavioral tests for the host-only validation gate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validation_gate", ROOT / "scripts/validation_gate.py"
)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


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
    }


def matrix(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "$schema": SCHEMA,
        "schemaVersion": "1.0.0",
        "matrixVersion": 1,
        "scopeIdentities": {"validation-tooling": SHA},
        "scenarios": rows,
    }


def manifest(matrix_sha256: str, evidence_path: str) -> dict[str, object]:
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
        }],
        "evidence": [{
            "path": evidence_path,
            "sha256": SHA,
            "kind": "summary",
            "immutable": True,
        }],
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
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence_root = Path(temporary)
            evidence = evidence_root / "summary.txt"
            evidence.write_bytes(b"evidence")
            digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
            for row in rows:
                row["evidence"] = [digest]
            document = matrix(rows)
            matrix_bytes = gate.canonical_json(document)
            run = manifest(hashlib.sha256(matrix_bytes).hexdigest(), evidence.name)
            run["dependencyLockSha256"] = SHA
            run["evidence"][0]["sha256"] = digest
            run["scenarioResults"][0]["evidenceSha256"] = [digest]
            if mutate_manifest is not None:
                mutate_manifest(run)
            gate.validate_gate(
                document,
                run,
                known_requirements={"VAL-001"},
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
            self.run_gate([scenario(requirement_ids=["NOPE-999"])])

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

        with self.assertRaisesRegex(gate.ValidationError, "support claim"):
            self.run_gate([scenario()], mutate_manifest=unseal)

    def test_support_claim_without_immutable_evidence_is_rejected(self) -> None:
        def make_mutable(run: dict[str, object]) -> None:
            run["evidence"][0]["immutable"] = False

        with self.assertRaisesRegex(gate.ValidationError, "not marked immutable"):
            self.run_gate([scenario()], mutate_manifest=make_mutable)


if __name__ == "__main__":
    unittest.main()
