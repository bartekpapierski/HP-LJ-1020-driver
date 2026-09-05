# SPDX-License-Identifier: GPL-2.0-or-later
"""Contract tests for validation schemas and the golden corpus."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts import check_golden_corpus as corpus_checker
from scripts import json_schema
from scripts import validation_gate as gate

ROOT = Path(__file__).resolve().parents[1]


class ValidationSchemaChecks(unittest.TestCase):
    def schema(self, name: str) -> dict[str, object]:
        return json.loads((ROOT / "docs/spec" / name).read_text(encoding="utf-8"))

    def test_capability_scenario_records_the_complete_validation_identity(self) -> None:
        schema = self.schema("capability-matrix.schema.json")
        scenario = schema["$defs"]["scenario"]
        required = set(scenario["required"])
        self.assertTrue({
            "environment",
            "sourceCommit",
            "dependencyLockSha256",
            "printer",
            "observedResult",
            "executedAt",
            "evidence",
            "affectedScopes",
            "attempts",
            "intermittencyExplanation",
        } <= required)
        self.assertEqual(
            set(scenario["properties"]["state"]["enum"]),
            {"verified", "unverified", "unsupported", "deferred"},
        )

    def test_validation_manifest_can_bind_evidence_and_support_claims(self) -> None:
        schema = self.schema("validation-manifest.schema.json")
        required = set(schema["required"])
        self.assertTrue({"scopeIdentities", "supportClaims"} <= required)
        evidence = schema["$defs"]["checksummedPath"]
        self.assertEqual(evidence["properties"]["immutable"]["const"], True)

    def test_output_measurement_schema_forbids_retained_payloads(self) -> None:
        schema = self.schema("output-measurement.schema.json")
        privacy = schema["properties"]["privacy"]["properties"]
        self.assertEqual(privacy["documentContentsRetained"]["const"], False)
        self.assertEqual(privacy["rasterPayloadRetained"]["const"], False)
        self.assertEqual(privacy["zjStreamPayloadRetained"]["const"], False)


class GoldenCorpusChecks(unittest.TestCase):
    def test_repository_corpus_is_complete_and_privacy_safe(self) -> None:
        corpus_checker.check_corpus(ROOT / "validation/golden-corpus")


class CapabilityMatrixChecks(unittest.TestCase):
    def test_repository_matrix_contains_every_non_deferred_scenario(self) -> None:
        known, required = gate.requirements_for_milestone(
            ROOT / "docs/IMPLEMENTATION-SPEC.md", "PUBLIC"
        )
        matrix = json.loads(
            (ROOT / "validation/capability-matrix.json").read_text(encoding="utf-8")
        )
        schema = json.loads(
            (ROOT / "docs/spec/capability-matrix.schema.json").read_text(encoding="utf-8")
        )
        json_schema.validate(matrix, schema)
        rows = gate._scenario_map(matrix, known)
        self.assertEqual(required - set(rows), set())


if __name__ == "__main__":
    unittest.main()
