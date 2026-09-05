#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Evaluate capability evidence before a milestone or support claim."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SHA256 = re.compile(r"^[a-f0-9]{64}$")
GIT_COMMIT = re.compile(r"^[a-f0-9]{40}$")
MILESTONES = ("BASIC", "PERSONAL", "CAPABILITY", "PUBLIC")
STATES = {"verified", "unverified", "unsupported", "deferred"}


class ValidationError(ValueError):
    pass


def canonical_json(document: Any) -> bytes:
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha(value: Any, context: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValidationError(f"{context} is not a SHA-256")
    return value


def _commit(value: Any, context: str) -> str:
    if not isinstance(value, str) or not GIT_COMMIT.fullmatch(value):
        raise ValidationError(f"{context} is not a full Git commit")
    return value


def _objects(value: Any, context: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValidationError(f"{context} must be an array of objects")
    return value


def _ids(value: Any, known: set[str], context: str) -> set[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
        raise ValidationError(f"{context} must contain requirement IDs")
    unknown = set(value) - known
    if unknown:
        raise ValidationError(f"{context} contains unknown requirement {sorted(unknown)[0]}")
    if len(set(value)) != len(value):
        raise ValidationError(f"{context} contains duplicate requirement IDs")
    return set(value)


def _check_intermittency(attempts: Any, explanation: Any, context: str) -> None:
    rows = _objects(attempts, f"{context} attempts")
    outcomes: set[str] = set()
    numbers: set[int] = set()
    for attempt in rows:
        number = attempt.get("attempt")
        outcome = attempt.get("outcome")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1 or number in numbers:
            raise ValidationError(f"{context} has invalid attempt numbering")
        numbers.add(number)
        if outcome not in {"passed", "failed"}:
            raise ValidationError(f"{context} has invalid attempt outcome")
        outcomes.add(outcome)
        if not isinstance(attempt.get("observedAt"), str) or not attempt["observedAt"]:
            raise ValidationError(f"{context} attempt has no timestamp")
        if not isinstance(attempt.get("summary"), str) or not attempt["summary"]:
            raise ValidationError(f"{context} attempt has no result summary")
    if len(outcomes) > 1 and not (isinstance(explanation, str) and explanation.strip()):
        raise ValidationError(f"{context} has unexplained intermittency")


def _scenario_map(
    matrix: dict[str, Any], known_requirements: set[str]
) -> dict[str, dict[str, Any]]:
    if matrix.get("schemaVersion") != "1.0.0" or matrix.get("matrixVersion") != 1:
        raise ValidationError("unsupported capability matrix version")
    scopes = matrix.get("scopeIdentities")
    if not isinstance(scopes, dict):
        raise ValidationError("capability matrix has no scope identities")
    for name, identity in scopes.items():
        if not isinstance(name, str) or not name:
            raise ValidationError("capability matrix has an invalid affected scope")
        _sha(identity, f"scope identity {name}")
    scenarios: dict[str, dict[str, Any]] = {}
    for row in _objects(matrix.get("scenarios"), "capability matrix scenarios"):
        scenario_id = row.get("scenarioId")
        if not isinstance(scenario_id, str) or not scenario_id.startswith("SCN-"):
            raise ValidationError("capability matrix has an invalid scenario ID")
        if scenario_id in scenarios:
            raise ValidationError(f"duplicate capability matrix scenario {scenario_id}")
        _ids(row.get("requirementIds"), known_requirements, scenario_id)
        if row.get("milestone") not in MILESTONES:
            raise ValidationError(f"{scenario_id} has an invalid milestone")
        if row.get("state") not in STATES:
            raise ValidationError(f"{scenario_id} has an invalid state")
        affected = row.get("affectedScopes")
        if not isinstance(affected, list) or not affected or any(scope not in scopes for scope in affected):
            raise ValidationError(f"{scenario_id} has an unknown or missing affected scope")
        invalidations = row.get("invalidatedBy")
        if not isinstance(invalidations, list) or any(not isinstance(item, str) for item in invalidations):
            raise ValidationError(f"{scenario_id} has invalid invalidation records")
        _check_intermittency(
            row.get("attempts"), row.get("intermittencyExplanation"), scenario_id
        )
        if row["state"] == "verified":
            for field in ("environment", "sourceCommit", "dependencyLockSha256", "observedResult", "executedAt"):
                if row.get(field) in (None, ""):
                    raise ValidationError(f"verified scenario {scenario_id} is missing {field}")
            _commit(row["sourceCommit"], f"{scenario_id} source identity")
            _sha(row["dependencyLockSha256"], f"{scenario_id} dependency identity")
            evidence = row.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                raise ValidationError(f"verified scenario {scenario_id} has no evidence")
            for digest in evidence:
                _sha(digest, f"{scenario_id} evidence pointer")
        scenarios[scenario_id] = row
    return scenarios


def _verify_evidence(manifest: dict[str, Any], evidence_root: Path) -> set[str]:
    evidence_hashes: set[str] = set()
    for evidence in _objects(manifest.get("evidence"), "validation evidence"):
        path_value = evidence.get("path")
        if not isinstance(path_value, str) or not path_value:
            raise ValidationError("validation evidence has no path")
        relative = Path(path_value)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValidationError(f"evidence path is not safely relative: {path_value}")
        digest = _sha(evidence.get("sha256"), f"evidence {path_value}")
        if evidence.get("immutable") is not True:
            raise ValidationError(f"evidence is not marked immutable: {path_value}")
        root = evidence_root.resolve()
        path = (root / relative).resolve()
        if root not in path.parents:
            raise ValidationError(f"evidence path escapes its root: {path_value}")
        if not path.is_file() or file_sha256(path) != digest:
            raise ValidationError(f"evidence checksum mismatch: {path_value}")
        if digest in evidence_hashes:
            raise ValidationError(f"duplicate evidence digest: {digest}")
        evidence_hashes.add(digest)
    return evidence_hashes


def validate_gate(
    matrix: dict[str, Any],
    manifest: dict[str, Any],
    *,
    known_requirements: set[str],
    required_scenarios: set[str],
    milestone: str,
    evidence_root: Path,
    matrix_sha256: str | None = None,
) -> None:
    """Reject a milestone unless every support claim has current sealed evidence."""
    if milestone not in MILESTONES:
        raise ValidationError(f"unknown milestone {milestone}")
    scenarios = _scenario_map(matrix, known_requirements)
    missing = required_scenarios - set(scenarios)
    if missing:
        raise ValidationError(f"missing required scenario row {sorted(missing)[0]}")

    claims = _objects(manifest.get("supportClaims"), "support claims")
    if claims and not (
        manifest.get("result") == "passed"
        and manifest.get("sealed") is True
        and manifest.get("redacted") is True
    ):
        raise ValidationError("support claim requires a passing, sealed, redacted manifest")
    if manifest.get("result") != "passed" or manifest.get("sealed") is not True:
        raise ValidationError(f"{milestone} gate requires a passing sealed manifest")

    recorded_matrix_hash = _sha(
        manifest.get("capabilityMatrixSha256"), "capability matrix identity"
    )
    _commit(manifest.get("sourceCommit"), "validation source identity")
    _commit(manifest.get("specificationCommit"), "specification identity")
    _sha(manifest.get("dependencyLockSha256"), "validation dependency identity")
    _sha(manifest.get("buildManifestSha256"), "build manifest identity")
    actual_matrix_hash = matrix_sha256 or hashlib.sha256(canonical_json(matrix)).hexdigest()
    if recorded_matrix_hash != actual_matrix_hash:
        raise ValidationError("capability matrix identity does not match the gated matrix")
    manifest_scopes = manifest.get("scopeIdentities")
    if not isinstance(manifest_scopes, dict):
        raise ValidationError("validation manifest has no affected-scope identities")

    results: dict[str, dict[str, Any]] = {}
    for result in _objects(manifest.get("scenarioResults"), "scenario results"):
        scenario_id = result.get("scenarioId")
        if scenario_id not in scenarios:
            raise ValidationError(f"manifest references unknown scenario {scenario_id}")
        if scenario_id in results:
            raise ValidationError(f"manifest duplicates scenario result {scenario_id}")
        result_ids = _ids(result.get("requirementIds"), known_requirements, str(scenario_id))
        if result_ids != set(scenarios[scenario_id]["requirementIds"]):
            raise ValidationError(f"{scenario_id} requirement IDs differ from the matrix")
        _check_intermittency(
            result.get("attempts"), result.get("intermittencyExplanation"), str(scenario_id)
        )
        if result.get("state") not in STATES:
            raise ValidationError(f"{scenario_id} result has an invalid state")
        if not isinstance(result.get("summary"), str) or not result["summary"]:
            raise ValidationError(f"{scenario_id} result has no summary")
        if not isinstance(result.get("observedAt"), str) or not result["observedAt"]:
            raise ValidationError(f"{scenario_id} result has no timestamp")
        results[str(scenario_id)] = result

    evidence_hashes = _verify_evidence(manifest, evidence_root)
    for scenario_id in sorted(required_scenarios):
        row = scenarios[scenario_id]
        result = results.get(scenario_id)
        if row["state"] != "verified" or result is None or result.get("state") != "verified":
            raise ValidationError(f"required scenario {scenario_id} is not verified")
        if row["invalidatedBy"]:
            raise ValidationError(f"expired evidence for {scenario_id}: {row['invalidatedBy'][0]}")
        for scope in row["affectedScopes"]:
            if manifest_scopes.get(scope) != matrix["scopeIdentities"][scope]:
                raise ValidationError(f"expired evidence for {scenario_id} affected scope {scope}")
        if row["sourceCommit"] != manifest.get("sourceCommit"):
            raise ValidationError(f"expired evidence for {scenario_id} source identity")
        if row["dependencyLockSha256"] != manifest.get("dependencyLockSha256"):
            raise ValidationError(f"expired evidence for {scenario_id} dependency identity")
        pointers = result.get("evidenceSha256")
        if not isinstance(pointers, list) or not pointers or not set(pointers) <= evidence_hashes:
            raise ValidationError(f"{scenario_id} lacks passing immutable evidence")
        if not set(row["evidence"]) <= set(pointers):
            raise ValidationError(f"{scenario_id} matrix evidence is absent from the manifest")

    for claim in claims:
        scenario_id = claim.get("scenarioId")
        statement = claim.get("statement")
        if scenario_id not in required_scenarios or not isinstance(statement, str) or not statement:
            raise ValidationError(f"support claim references ungated scenario {scenario_id}")
        if results[scenario_id].get("state") != "verified":
            raise ValidationError(f"support claim for {scenario_id} has no passing evidence")


def _load_spec_module() -> Any:
    path = ROOT / "scripts/check_implementation_spec.py"
    spec = importlib.util.spec_from_file_location("implementation_spec", path)
    if spec is None or spec.loader is None:
        raise ValidationError("cannot load implementation specification checker")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def requirements_for_milestone(spec_path: Path, milestone: str) -> tuple[set[str], set[str]]:
    checker = _load_spec_module()
    requirements = checker.parse_requirements(spec_path.read_text(encoding="utf-8"))
    checker.check_requirement_set(requirements)
    maximum = MILESTONES.index(milestone)
    known = {requirement.id for requirement in requirements}
    required = {
        scenario
        for requirement in requirements
        if requirement.status != "DEFERRED"
        and MILESTONES.index(requirement.milestone) <= maximum
        for scenario in requirement.coverage
    }
    return known, required


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--milestone", required=True, choices=MILESTONES)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--spec", type=Path, default=ROOT / "docs/IMPLEMENTATION-SPEC.md")
    args = parser.parse_args(argv)
    try:
        matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        known, required = requirements_for_milestone(args.spec, args.milestone)
        validate_gate(
            matrix,
            manifest,
            known_requirements=known,
            required_scenarios=required,
            milestone=args.milestone,
            evidence_root=args.evidence_root,
            matrix_sha256=file_sha256(args.matrix),
        )
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as error:
        print(f"validation gate rejected: {error}", file=sys.stderr)
        return 1
    print(f"{args.milestone} validation gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
