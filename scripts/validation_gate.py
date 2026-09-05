#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Evaluate capability evidence before a milestone or support claim."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any, Iterable

if __package__:
    from scripts import check_implementation_spec, json_schema, output_measurement
else:
    import check_implementation_spec  # type: ignore[no-redef]
    import json_schema  # type: ignore[no-redef]
    import output_measurement  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
SHA256 = re.compile(r"^[a-f0-9]{64}$")
GIT_COMMIT = re.compile(r"^[a-f0-9]{40}$")
MILESTONES = ("BASIC", "PERSONAL", "CAPABILITY", "PUBLIC")
STATES = {"verified", "unverified", "unsupported", "deferred"}
PRIVATE_SOURCE_PATH = re.compile(
    r"(?:/Users/[^/\s]+/[^\s]+|[A-Za-z0-9_.-]+\.(?:docx?|pages|pdf|rtf))",
    re.IGNORECASE,
)
EXPOSED_SECRET = re.compile(
    r"\b(?:credential|password|secret|token|user(?:name)?)\s*[:=]\s*\S+",
    re.IGNORECASE,
)
FIRMWARE_NAME = re.compile(r"\b(?:sihp1020\.(?:dl|img)|hp_laserjet_1020\.fw)\b", re.IGNORECASE)


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


def _object_list(value: Any, context: str) -> list[dict[str, Any]]:
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
    rows = _object_list(attempts, f"{context} attempts")
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
    for row in _object_list(matrix.get("scenarios"), "capability matrix scenarios"):
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
            if not isinstance(row["environment"], dict):
                raise ValidationError(f"verified scenario {scenario_id} has invalid environment")
            if not row["attempts"]:
                raise ValidationError(f"verified scenario {scenario_id} has no attempts")
            evidence = row.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                raise ValidationError(f"verified scenario {scenario_id} has no evidence")
            for digest in evidence:
                _sha(digest, f"{scenario_id} evidence pointer")
        scenarios[scenario_id] = row
    return scenarios


def _verify_evidence(
    manifest: dict[str, Any], evidence_root: Path, scenario_ids: set[str]
) -> dict[str, dict[str, Any]]:
    evidence_by_hash: dict[str, dict[str, Any]] = {}
    kinds: set[str] = set()
    for evidence in _object_list(manifest.get("evidence"), "validation evidence"):
        path_value = evidence.get("path")
        if not isinstance(path_value, str) or not path_value:
            raise ValidationError("validation evidence has no path")
        relative = Path(path_value)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValidationError(f"evidence path is not safely relative: {path_value}")
        digest = _sha(evidence.get("sha256"), f"evidence {path_value}")
        if evidence.get("immutable") is not True:
            raise ValidationError(f"evidence is not marked immutable: {path_value}")
        if evidence.get("result") != "passed":
            raise ValidationError(f"evidence did not pass: {path_value}")
        if evidence.get("privacyChecked") is not True:
            raise ValidationError(f"evidence lacks privacy review: {path_value}")
        bindings = evidence.get("scenarioIds")
        if not isinstance(bindings, list) or not bindings or any(
            not isinstance(scenario_id, str) for scenario_id in bindings
        ):
            raise ValidationError(f"evidence has no scenario binding: {path_value}")
        unknown_bindings = set(bindings) - scenario_ids
        if unknown_bindings:
            raise ValidationError(
                f"evidence has unknown scenario binding {sorted(unknown_bindings)[0]}"
            )
        root = evidence_root.resolve()
        path = (root / relative).resolve()
        if root not in path.parents:
            raise ValidationError(f"evidence path escapes its root: {path_value}")
        if not path.is_file() or file_sha256(path) != digest:
            raise ValidationError(f"evidence checksum mismatch: {path_value}")
        write_bits = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
        if path.stat().st_mode & write_bits:
            raise ValidationError(f"immutable evidence is writable: {path_value}")
        _validate_private_bytes(path)
        kind = evidence.get("kind")
        if kind not in {"sanitized-log", "measurement", "scan", "photograph", "summary", "manifest"}:
            raise ValidationError(f"evidence has an invalid kind: {path_value}")
        kinds.add(kind)
        if kind == "measurement":
            measurement_scenario = _validate_output_measurement(path)
            if set(bindings) != {measurement_scenario}:
                raise ValidationError(
                    f"output measurement {path_value} does not match its scenario binding"
                )
        elif kind in {"sanitized-log", "summary"}:
            _validate_utf8_text(path)
        if digest in evidence_by_hash:
            raise ValidationError(f"duplicate evidence digest: {digest}")
        evidence_by_hash[digest] = evidence
    required_kinds = {"sanitized-log", "measurement", "summary"}
    if not required_kinds <= kinds:
        missing = required_kinds - kinds
        raise ValidationError(f"validation run lacks evidence kind {sorted(missing)[0]}")
    return evidence_by_hash


def _validate_output_measurement(path: Path) -> str:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        output_measurement.validate_measurement(document)
    except (OSError, json.JSONDecodeError, output_measurement.MeasurementError) as error:
        raise ValidationError(f"invalid output measurement {path.name}: {error}") from error
    return str(document["scenarioId"])


def _validate_private_bytes(path: Path) -> None:
    try:
        content = path.read_bytes().decode("latin-1")
    except OSError as error:
        raise ValidationError(f"cannot inspect evidence privacy: {path.name}") from error
    if PRIVATE_SOURCE_PATH.search(content):
        raise ValidationError(f"evidence retains a private source filename: {path.name}")
    if EXPOSED_SECRET.search(content):
        raise ValidationError(f"evidence retains credentials or user identity: {path.name}")
    if FIRMWARE_NAME.search(content):
        raise ValidationError(f"evidence retains firmware identity: {path.name}")


def _validate_utf8_text(path: Path) -> None:
    try:
        path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ValidationError(f"text evidence is not UTF-8: {path.name}") from error


def _validate_environment(environment: Any, *, allow_vm: bool) -> dict[str, Any]:
    if not isinstance(environment, dict):
        raise ValidationError("validation environment must be an object")
    allowed_kinds = {"hosted-ci", "local-host", "reference-mac"}
    if allow_vm:
        allowed_kinds.add("supplementary-vm")
    if environment.get("kind") not in allowed_kinds:
        raise ValidationError("validation environment has an invalid kind")
    for field in ("macOSVersion", "macOSBuild"):
        if not isinstance(environment.get(field), str) or not environment[field]:
            raise ValidationError(f"validation environment has no {field}")
    if environment.get("architecture") != "arm64":
        raise ValidationError("validation environment is not arm64")
    return environment


def _validate_printer(printer: Any) -> dict[str, Any]:
    if not isinstance(printer, dict):
        raise ValidationError("printer identity must be an object")
    if printer.get("model") != "HP LaserJet 1020" or printer.get("vendorProduct") != "03f0:2b17":
        raise ValidationError("printer identity is not the reference printer model")
    _sha(printer.get("serialSha256"), "redacted printer serial identity")
    firmware = printer.get("firmwareVersion")
    if firmware is not None and (not isinstance(firmware, str) or not firmware):
        raise ValidationError("printer firmware identity is invalid")
    return printer


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
    try:
        matrix_schema = json.loads(
            (ROOT / "docs/spec/capability-matrix.schema.json").read_text(encoding="utf-8")
        )
        manifest_schema = json.loads(
            (ROOT / "docs/spec/validation-manifest.schema.json").read_text(encoding="utf-8")
        )
        json_schema.validate(matrix, matrix_schema)
        json_schema.validate(manifest, manifest_schema)
    except (OSError, json.JSONDecodeError, json_schema.SchemaError) as error:
        raise ValidationError(f"schema validation failed: {error}") from error
    scenarios = _scenario_map(matrix, known_requirements)
    missing = required_scenarios - set(scenarios)
    if missing:
        raise ValidationError(f"missing required scenario row {sorted(missing)[0]}")

    claims = _object_list(manifest.get("supportClaims"), "support claims")
    if manifest.get("redacted") is not True:
        raise ValidationError("validation manifest is not redacted")
    if claims and not (
        manifest.get("result") == "passed"
        and manifest.get("sealed") is True
        and manifest.get("redacted") is True
    ):
        raise ValidationError("support claim requires a passing, sealed, redacted manifest")
    if manifest.get("result") != "passed" or manifest.get("sealed") is not True:
        raise ValidationError(f"{milestone} gate requires a passing sealed manifest")
    environment = _validate_environment(manifest.get("environment"), allow_vm=True)
    if environment.get("kind") == "supplementary-vm":
        raise ValidationError("supplementary VM evidence cannot establish support")
    if claims and environment.get("kind") != "reference-mac":
        raise ValidationError("support claims require reference-Mac evidence")
    connection_paths = environment.get("connectionPaths")
    allowed_paths = {"host-only", "ugreen-thunderbolt-4-dock", "direct-usb-a-to-usb-c"}
    if (
        not isinstance(connection_paths, list)
        or any(not isinstance(path, str) or path not in allowed_paths for path in connection_paths)
    ):
        raise ValidationError("validation environment has no connection paths")

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
    for result in _object_list(manifest.get("scenarioResults"), "scenario results"):
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
        if manifest.get("result") == "passed" and result.get("state") != "verified":
            raise ValidationError(f"passing manifest contains non-verified result {scenario_id}")
        if not isinstance(result.get("summary"), str) or not result["summary"]:
            raise ValidationError(f"{scenario_id} result has no summary")
        if not isinstance(result.get("observedAt"), str) or not result["observedAt"]:
            raise ValidationError(f"{scenario_id} result has no timestamp")
        if result.get("state") == "verified" and not result["attempts"]:
            raise ValidationError(f"verified scenario result {scenario_id} has no attempts")
        results[str(scenario_id)] = result

    evidence_by_hash = _verify_evidence(manifest, evidence_root, set(scenarios))
    for scenario_id in sorted(required_scenarios):
        row = scenarios[scenario_id]
        result = results.get(scenario_id)
        if row["state"] != "verified" or result is None or result.get("state") != "verified":
            raise ValidationError(f"required scenario {scenario_id} is not verified")
        if any(attempt["outcome"] != "passed" for attempt in row["attempts"]):
            raise ValidationError(f"required scenario {scenario_id} has a failed attempt")
        if any(attempt["outcome"] != "passed" for attempt in result["attempts"]):
            raise ValidationError(f"required scenario {scenario_id} result has a failed attempt")
        row_environment = _validate_environment(row["environment"], allow_vm=True)
        if any(
            row_environment.get(field) != environment.get(field)
            for field in ("kind", "macOSVersion", "macOSBuild", "architecture")
        ):
            raise ValidationError(f"expired evidence for {scenario_id} environment identity")
        required_paths = {
            "host-only": {"host-only"},
            "ugreen-thunderbolt-4-dock": {"ugreen-thunderbolt-4-dock"},
            "direct-usb-a-to-usb-c": {"direct-usb-a-to-usb-c"},
            "both": {"ugreen-thunderbolt-4-dock", "direct-usb-a-to-usb-c"},
        }[row["connectionPath"]]
        if not required_paths <= set(connection_paths):
            raise ValidationError(f"{scenario_id} lacks its required connection path evidence")
        if row["connectionPath"] != "host-only" and (
            _validate_printer(row.get("printer")) != _validate_printer(manifest.get("printer"))
        ):
            raise ValidationError(f"{scenario_id} lacks exact printer and firmware identity")
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
        if not isinstance(pointers, list) or not pointers or not set(pointers) <= set(evidence_by_hash):
            raise ValidationError(f"{scenario_id} lacks passing immutable evidence")
        if any(scenario_id not in evidence_by_hash[digest]["scenarioIds"] for digest in pointers):
            raise ValidationError(f"{scenario_id} evidence is bound to another scenario")
        if not set(row["evidence"]) <= set(pointers):
            raise ValidationError(f"{scenario_id} matrix evidence is absent from the manifest")
        _check_reliability(scenario_id, row, result)

    for claim in claims:
        scenario_id = claim.get("scenarioId")
        statement = claim.get("statement")
        if scenario_id not in required_scenarios or not isinstance(statement, str) or not statement:
            raise ValidationError(f"support claim references ungated scenario {scenario_id}")
        if results[scenario_id].get("state") != "verified":
            raise ValidationError(f"support claim for {scenario_id} has no passing evidence")


def _check_reliability(
    scenario_id: str, row: dict[str, Any], result: dict[str, Any]
) -> None:
    requirements = row.get("reliabilityRequirements")
    observations = result.get("reliabilityObservations")
    if requirements is None:
        return
    if not isinstance(requirements, dict) or not isinstance(observations, dict):
        raise ValidationError(f"{scenario_id} lacks reliability observations")
    required_passes = requirements.get("criticalTransitionPassesPerConnectionPath")
    observed_passes = observations.get("criticalTransitionPassesPerConnectionPath")
    if not isinstance(required_passes, dict) or not isinstance(observed_passes, dict):
        raise ValidationError(f"{scenario_id} lacks per-path repetition counts")
    for path, minimum in required_passes.items():
        observed = observed_passes.get(path)
        if (
            not isinstance(minimum, int)
            or isinstance(minimum, bool)
            or not isinstance(observed, int)
            or isinstance(observed, bool)
            or observed < minimum
        ):
            raise ValidationError(f"{scenario_id} lacks five passing repetitions on {path}")
    minimum_soak = requirements.get("mixedDocumentSoakJobs")
    minimum_cycles = requirements.get("lifecycleCycles")
    maximum_restarts = requirements.get("maximumServiceRestartsDuringSoak")
    observed_soak = observations.get("mixedDocumentSoakJobs")
    observed_cycles = observations.get("lifecycleCycles")
    observed_restarts = observations.get("serviceRestartsDuringSoak")
    values = (minimum_soak, minimum_cycles, maximum_restarts, observed_soak, observed_cycles, observed_restarts)
    if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
        raise ValidationError(f"{scenario_id} has invalid reliability counters")
    if observed_soak < minimum_soak:
        raise ValidationError(f"{scenario_id} lacks the 20-job mixed-document soak")
    if observed_cycles < minimum_cycles:
        raise ValidationError(f"{scenario_id} lacks three complete lifecycle cycles")
    if observed_restarts > maximum_restarts:
        raise ValidationError(f"{scenario_id} restarted the service during the soak")


def requirements_for_milestone(spec_path: Path, milestone: str) -> tuple[set[str], set[str]]:
    requirements = check_implementation_spec.parse_requirements(
        spec_path.read_text(encoding="utf-8")
    )
    check_implementation_spec.check_requirement_set(requirements)
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
        write_bits = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
        if args.manifest.stat().st_mode & write_bits:
            raise ValidationError("sealed validation manifest is writable")
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
