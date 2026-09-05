#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Synchronize capability-matrix rows and affected-scope identities with the spec."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

if __package__:
    from scripts import check_implementation_spec
else:
    import check_implementation_spec  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "validation/capability-matrix.json"
SPEC_PATH = ROOT / "docs/IMPLEMENTATION-SPEC.md"
SCHEMA_ID = (
    "https://bartekpapierski.github.io/HP-LJ-1020-driver/"
    "schemas/capability-matrix-1.0.0.json"
)
MILESTONES = ("BASIC", "PERSONAL", "CAPABILITY", "PUBLIC")
SCOPE_PATHS = {
    "build-inputs": (
        "dependencies.lock.json",
        "generated-inputs.json",
        "scripts/build",
    ),
    "golden-corpus": ("validation/golden-corpus",),
    "implementation-contract": ("CONTEXT.md", "docs/IMPLEMENTATION-SPEC.md"),
    "product-source": ("CMakeLists.txt", "include", "src"),
    "validation-tooling": (
        "docs/spec",
        "scripts/check_golden_corpus.py",
        "scripts/check_implementation_spec.py",
        "scripts/json_schema.py",
        "scripts/output_measurement.py",
        "scripts/update_capability_matrix.py",
        "scripts/validation_gate.py",
    ),
}


def _files(paths: Iterable[str]) -> list[Path]:
    files: set[Path] = set()
    for value in paths:
        path = ROOT / value
        if path.is_file():
            files.add(path)
        elif path.is_dir():
            files.update(candidate for candidate in path.rglob("*") if candidate.is_file())
    return sorted(files)


def _scope_identity(paths: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for path in _files(paths):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _affected_scopes(requirements: list[Any]) -> list[str]:
    namespaces = {requirement.id.split("-", 1)[0] for requirement in requirements}
    scopes = {"implementation-contract"}
    if namespaces & {"ARCH", "DEV", "FW", "JOB", "INST", "SVC", "SEC", "DIAG", "SCOPE"}:
        scopes.add("product-source")
    if namespaces & {"BUILD", "LIC", "REL"}:
        scopes.add("build-inputs")
    if namespaces & {"VAL", "REL"}:
        scopes.add("validation-tooling")
    if any("GOLDEN" in scenario for requirement in requirements for scenario in requirement.coverage):
        scopes.add("golden-corpus")
    return sorted(scopes)


def _connection_path(requirements: list[Any], scenario_id: str) -> str:
    if scenario_id.endswith("-DIRECT") or "CLAIM-DIRECT" in scenario_id:
        return "direct-usb-a-to-usb-c"
    if scenario_id.endswith("-DOCK") or "CLAIM-DOCK" in scenario_id:
        return "ugreen-thunderbolt-4-dock"
    if any("REFERENCE_PRINTER" in requirement.verification for requirement in requirements):
        return "both"
    return "host-only"


def build_matrix(existing: dict[str, Any] | None = None) -> dict[str, Any]:
    requirements = check_implementation_spec.parse_requirements(
        SPEC_PATH.read_text(encoding="utf-8")
    )
    check_implementation_spec.check_requirement_set(requirements)
    grouped: dict[str, list[Any]] = defaultdict(list)
    for requirement in requirements:
        for scenario_id in requirement.coverage:
            grouped[scenario_id].append(requirement)

    old_scopes = existing.get("scopeIdentities", {}) if existing else {}
    old_rows = {
        row["scenarioId"]: row
        for row in existing.get("scenarios", [])
        if isinstance(row, dict) and isinstance(row.get("scenarioId"), str)
    } if existing else {}
    scopes = {name: _scope_identity(paths) for name, paths in SCOPE_PATHS.items()}
    rows: list[dict[str, Any]] = []
    for scenario_id, covered in sorted(grouped.items()):
        affected = _affected_scopes(covered)
        old = old_rows.get(scenario_id)
        invalidations = list(old.get("invalidatedBy", [])) if old else []
        if old and old.get("state") == "verified":
            for scope in affected:
                if old_scopes.get(scope) != scopes[scope]:
                    reason = f"affected scope changed: {scope}"
                    if reason not in invalidations:
                        invalidations.append(reason)
        all_deferred = all(requirement.status == "DEFERRED" for requirement in covered)
        row = {
            "scenarioId": scenario_id,
            "behavior": "; ".join(sorted({requirement.scope for requirement in covered})),
            "milestone": min(
                (requirement.milestone for requirement in covered), key=MILESTONES.index
            ),
            "requirementIds": sorted(requirement.id for requirement in covered),
            "provenance": sorted({
                f"Issue #{source}"
                for requirement in covered
                for source in requirement.sources
            }),
            "environment": None,
            "connectionPath": _connection_path(covered, scenario_id),
            "sourceCommit": None,
            "dependencyLockSha256": None,
            "printer": None,
            "expectedResult": " ".join(requirement.statement for requirement in covered),
            "observedResult": None,
            "executedAt": None,
            "durationSeconds": None,
            "evidence": [],
            "state": "deferred" if all_deferred else "unverified",
            "affectedScopes": affected,
            "invalidatedBy": invalidations,
            "attempts": [],
            "intermittencyExplanation": None,
            "reliabilityRequirements": {
                "criticalTransitionPassesPerConnectionPath": {
                    "ugreen-thunderbolt-4-dock": 5,
                    "direct-usb-a-to-usb-c": 5,
                },
                "mixedDocumentSoakJobs": 20,
                "maximumServiceRestartsDuringSoak": 0,
                "lifecycleCycles": 3,
            } if scenario_id == "SCN-REPETITION-SOAK" else None,
        }
        if old:
            for field in (
                "environment",
                "sourceCommit",
                "dependencyLockSha256",
                "printer",
                "observedResult",
                "executedAt",
                "durationSeconds",
                "evidence",
                "state",
                "attempts",
                "intermittencyExplanation",
                "reliabilityRequirements",
            ):
                row[field] = old.get(field, row[field])
            row["invalidatedBy"] = invalidations
        rows.append(row)
    return {
        "$schema": SCHEMA_ID,
        "schemaVersion": "1.0.0",
        "matrixVersion": 1,
        "scopeIdentities": scopes,
        "scenarios": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed matrix is stale")
    args = parser.parse_args(argv)
    existing = None
    if MATRIX_PATH.is_file():
        try:
            existing = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            print(f"invalid capability matrix: {error}", file=sys.stderr)
            return 1
    expected = json.dumps(build_matrix(existing), indent=2) + "\n"
    actual = MATRIX_PATH.read_text(encoding="utf-8") if MATRIX_PATH.is_file() else ""
    if args.check:
        if actual != expected:
            print("capability matrix is stale; run scripts/update_capability_matrix.py", file=sys.stderr)
            return 1
        print("capability matrix is current")
        return 0
    MATRIX_PATH.parent.mkdir(parents=True, exist_ok=True)
    MATRIX_PATH.write_text(expected, encoding="utf-8")
    print(f"updated {MATRIX_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
