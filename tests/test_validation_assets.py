# SPDX-License-Identifier: GPL-2.0-or-later
"""Contract tests for validation schemas and the golden corpus."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_golden_corpus", ROOT / "scripts/check_golden_corpus.py"
)
assert SPEC is not None and SPEC.loader is not None
corpus_checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = corpus_checker
SPEC.loader.exec_module(corpus_checker)


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
        gate_spec = importlib.util.spec_from_file_location(
            "validation_gate_for_assets", ROOT / "scripts/validation_gate.py"
        )
        assert gate_spec is not None and gate_spec.loader is not None
        gate = importlib.util.module_from_spec(gate_spec)
        sys.modules[gate_spec.name] = gate
        gate_spec.loader.exec_module(gate)
        known, required = gate.requirements_for_milestone(
            ROOT / "docs/IMPLEMENTATION-SPEC.md", "PUBLIC"
        )
        matrix = json.loads(
            (ROOT / "validation/capability-matrix.json").read_text(encoding="utf-8")
        )
        rows = gate._scenario_map(matrix, known)
        self.assertEqual(required - set(rows), set())


if __name__ == "__main__":
    unittest.main()
