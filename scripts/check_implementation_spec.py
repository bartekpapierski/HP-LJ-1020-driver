#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Host-only conformance check for the normative implementation specification."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


REQUIREMENT_ROW = re.compile(r"^\|\s*([A-Z]+-[0-9]{3})\s*\|")
REQUIREMENT_ID = re.compile(r"^[A-Z]+-[0-9]{3}$")
SCENARIO_ID = re.compile(r"^SCN-[A-Z0-9-]+$")
KEYWORD = re.compile(r"\b(?:MUST NOT|MUST|SHOULD|MAY)\b")
DECISION_LINK = re.compile(
    r"\[Issue #(\d+)\]\(https://github\.com/bartekpapierski/"
    r"HP-LJ-1020-driver/issues/(\d+)\)"
)
ALLOWED_STATUSES = {"REQUIRED", "EVIDENCE GAP", "DEFERRED"}
ALLOWED_MILESTONES = {"BASIC", "PERSONAL", "CAPABILITY", "PUBLIC"}
ALLOWED_VERIFICATION = {
    "STATIC",
    "HOST",
    "REFERENCE_MAC",
    "REFERENCE_PRINTER",
    "HUMAN_REVIEW",
    "RELEASE_RECORD",
}
REQUIRED_DECISIONS = set(range(1, 16))
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
GPL_IDENTIFIER = "SPDX-License-Identifier: GPL-2.0-or-later"
FOO2ZJS_COMMIT = "80499ed5bf6caa2963ad337e37cfda78a80aab1e"
SOURCE_SUFFIXES = {".c", ".h", ".m", ".mm", ".py", ".sh", ".swift", ".html", ".plist"}
SKIPPED_DIRECTORY_NAMES = {".git", "__pycache__"}
PROHIBITED_FIRMWARE_NAMES = {"sihp1020.dl", "sihp1020.img"}
PROHIBITED_BINARY_SUFFIXES = {".a", ".bin", ".dylib", ".exe", ".fw", ".o", ".so"}
PROHIBITED_BINARY_MAGICS = (b"\x7fELF", b"MZ", b"\xca\xfe\xba\xbe", b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf")
REQUIRED_HEADINGS = {
    "## Problem Statement",
    "## Solution",
    "## User Stories",
    "## Implementation Decisions",
    "## Testing Decisions",
    "## Out of Scope",
    "## Further Notes",
    *{f"### {number}. {title}" for number, title in enumerate(
        (
            "Purpose, scope, audience, and conformance",
            "Domain terms and fixed support boundary",
            "System architecture and global invariants",
            "Component contracts",
            "Configuration, persistent state, and artifact contracts",
            "Installation and service lifecycle",
            "Firmware and device lifecycle",
            "Print-job lifecycle and recovery",
            "Security, privacy, privilege, and diagnostics",
            "Build and dependency contract",
            "Licensing and firmware compliance",
            "Personal-release operations",
            "Validation contract and support claims",
            "Deferred public-release seams",
            "Requirement-to-decision traceability index",
        ),
        start=1,
    )},
}
TRANSITION_HEADER = (
    "| From | Trigger | Preconditions | Required actions | Success state | "
    "Failure state | Retry policy | Retained data | Observable status |"
)


class CheckError(ValueError):
    pass


@dataclass(frozen=True)
class Requirement:
    id: str
    statement: str
    status: str
    milestone: str
    verification: tuple[str, ...]
    coverage: tuple[str, ...]
    scope: str
    sources: tuple[int, ...]
    line: int


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_requirements(text: str) -> list[Requirement]:
    requirements: list[Requirement] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not REQUIREMENT_ROW.match(line):
            continue
        cells = _split_row(line)
        if len(cells) != 8:
            raise CheckError(
                f"line {line_number}: requirement row has {len(cells)} fields; expected 8"
            )
        req_id, statement, status, milestone, verification, coverage, scope, source = cells
        if status != "DEFERRED" and not coverage:
            raise CheckError(f"line {line_number}: requirement {req_id} is uncovered")
        if not all(cells):
            raise CheckError(f"line {line_number}: requirement {req_id} has an empty field")
        if status not in ALLOWED_STATUSES:
            raise CheckError(f"line {line_number}: requirement {req_id} has unknown status {status!r}")
        if milestone not in ALLOWED_MILESTONES:
            raise CheckError(
                f"line {line_number}: requirement {req_id} has unknown milestone {milestone!r}"
            )
        classes = tuple(part.strip() for part in verification.split(","))
        unknown_classes = set(classes) - ALLOWED_VERIFICATION
        if unknown_classes:
            raise CheckError(
                f"line {line_number}: requirement {req_id} has unknown verification class(es) "
                + ", ".join(sorted(unknown_classes))
            )
        scenarios = tuple(part.strip() for part in coverage.split(","))
        if any(not SCENARIO_ID.fullmatch(item) for item in scenarios):
            raise CheckError(f"line {line_number}: requirement {req_id} has invalid coverage IDs")
        if not KEYWORD.search(statement):
            raise CheckError(
                f"line {line_number}: requirement {req_id} has no normative keyword"
            )
        links = DECISION_LINK.findall(source)
        if not links:
            raise CheckError(f"line {line_number}: requirement {req_id} has no source-decision link")
        mismatches = [(label, target) for label, target in links if label != target]
        if mismatches:
            raise CheckError(
                f"line {line_number}: requirement {req_id} has mismatched decision link {mismatches[0]}"
            )
        sources = tuple(int(label) for label, _ in links)
        unknown_decisions = set(sources) - REQUIRED_DECISIONS
        if unknown_decisions:
            raise CheckError(
                f"line {line_number}: requirement {req_id} links unknown decision(s) "
                + ", ".join(str(number) for number in sorted(unknown_decisions))
            )
        requirements.append(
            Requirement(
                id=req_id,
                statement=statement,
                status=status,
                milestone=milestone,
                verification=classes,
                coverage=scenarios,
                scope=scope,
                sources=sources,
                line=line_number,
            )
        )
    if not requirements:
        raise CheckError("the specification contains no requirement rows")
    return requirements


def check_requirement_set(requirements: Iterable[Requirement]) -> dict[str, Requirement]:
    by_id: dict[str, Requirement] = {}
    by_namespace: dict[str, list[int]] = defaultdict(list)
    source_decisions: set[int] = set()
    for requirement in requirements:
        if requirement.id in by_id:
            raise CheckError(f"duplicate requirement ID {requirement.id}")
        by_id[requirement.id] = requirement
        namespace, number = requirement.id.split("-")
        by_namespace[namespace].append(int(number))
        source_decisions.update(requirement.sources)
    for namespace, numbers in by_namespace.items():
        expected = list(range(1, len(numbers) + 1))
        if sorted(numbers) != expected:
            raise CheckError(
                f"namespace {namespace} is not sequential from 001: found {sorted(numbers)}"
            )
    missing_decisions = REQUIRED_DECISIONS - source_decisions
    if missing_decisions:
        raise CheckError(
            "settled decisions have no requirement mapping: "
            + ", ".join(f"#{number}" for number in sorted(missing_decisions))
        )
    return by_id


def check_hidden_normative_statements(text: str) -> None:
    for line_number, line in enumerate(text.splitlines(), start=1):
        if REQUIREMENT_ROW.match(line):
            continue
        if line.startswith("The terms `MUST`"):
            continue
        if KEYWORD.search(line):
            raise CheckError(
                f"line {line_number}: normative keyword appears outside a requirement row"
            )


def check_document_structure(text: str) -> None:
    headings = {line for line in text.splitlines() if line.startswith("#")}
    missing = REQUIRED_HEADINGS - headings
    if missing:
        raise CheckError("missing required section(s): " + ", ".join(sorted(missing)))
    transition_count = text.splitlines().count(TRANSITION_HEADER)
    if transition_count != 5:
        raise CheckError(
            f"expected five normative lifecycle transition tables; found {transition_count}"
        )


def _json_pointer(document: Any, pointer: str, context: str) -> Any:
    current = document
    if pointer == "#":
        return current
    if not pointer.startswith("#/"):
        raise CheckError(f"{context}: unsupported local reference {pointer!r}")
    for raw_part in pointer[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise CheckError(f"{context}: unresolved local reference {pointer!r}")
        current = current[part]
    return current


def _walk_json(value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CheckError(f"{path}: invalid JSON: {error}") from error


def check_schema_catalog(root: Path) -> tuple[dict[str, dict[str, Any]], set[str]]:
    catalog_path = root / "docs/spec/schema-catalog.json"
    catalog = load_json(catalog_path)
    if catalog.get("catalogVersion") != "1.0.0":
        raise CheckError(f"{catalog_path}: unsupported catalogVersion")
    if catalog.get("jsonSchemaDialect") != JSON_SCHEMA_DIALECT:
        raise CheckError(f"{catalog_path}: unexpected JSON Schema dialect")
    artifacts = catalog.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise CheckError(f"{catalog_path}: artifacts must be a non-empty array")

    by_id: dict[str, dict[str, Any]] = {}
    schema_documents: dict[str, tuple[Path, Any]] = {}
    seen_names: set[str] = set()
    for artifact in artifacts:
        required = {
            "name",
            "schemaPath",
            "schemaId",
            "schemaVersion",
            "instancePath",
            "instanceRequiredNow",
        }
        if not isinstance(artifact, dict) or set(artifact) != required:
            raise CheckError(f"{catalog_path}: each catalog entry must contain exactly {sorted(required)}")
        if artifact["name"] in seen_names:
            raise CheckError(f"{catalog_path}: duplicate artifact name {artifact['name']}")
        seen_names.add(artifact["name"])
        schema_path = root / artifact["schemaPath"]
        if not schema_path.is_file():
            raise CheckError(f"{catalog_path}: missing schema {artifact['schemaPath']}")
        schema = load_json(schema_path)
        if schema.get("$schema") != JSON_SCHEMA_DIALECT:
            raise CheckError(f"{schema_path}: unexpected or missing $schema")
        if schema.get("$id") != artifact["schemaId"]:
            raise CheckError(f"{schema_path}: $id does not match the catalog")
        version = schema.get("properties", {}).get("schemaVersion", {}).get("const")
        if version != artifact["schemaVersion"]:
            raise CheckError(f"{schema_path}: schemaVersion const does not match the catalog")
        if artifact["schemaId"] in by_id:
            raise CheckError(f"{catalog_path}: duplicate schemaId {artifact['schemaId']}")
        by_id[artifact["schemaId"]] = artifact
        schema_documents[artifact["schemaId"]] = (schema_path, schema)
        instance_path = artifact["instancePath"]
        if artifact["instanceRequiredNow"]:
            if "<" in instance_path or not (root / instance_path).is_file():
                raise CheckError(f"{catalog_path}: required instance is missing: {instance_path}")

    allowed_schema_ids = set(by_id) | {JSON_SCHEMA_DIALECT}
    for schema_id, (schema_path, schema) in schema_documents.items():
        for key, value in _walk_json(schema):
            if key == "$ref" and isinstance(value, str):
                if value.startswith("#"):
                    _json_pointer(schema, value, str(schema_path))
                elif value not in allowed_schema_ids:
                    raise CheckError(f"{schema_path}: unknown external $ref {value!r}")
            if key == "$schema" and isinstance(value, str) and value not in allowed_schema_ids:
                raise CheckError(f"{schema_path}: unknown $schema {value!r}")
    return by_id, allowed_schema_ids


def check_catalog_pins(text: str, artifacts: Iterable[dict[str, Any]]) -> None:
    for artifact in artifacts:
        for field in ("schemaPath", "schemaVersion", "instancePath"):
            value = artifact[field]
            if f"`{value}`" not in text:
                raise CheckError(
                    f"specification does not pin catalog {field} {value!r} for {artifact['name']}"
                )


def check_diagnostic_inventory(root: Path, allowed_schema_ids: set[str]) -> None:
    path = root / "docs/spec/diagnostic-bundle-inventory.v1.json"
    inventory = load_json(path)
    required = {
        "$schema",
        "schemaVersion",
        "inventoryVersion",
        "maximumBundleBytes",
        "entries",
        "prohibitedDataClasses",
    }
    if set(inventory) != required:
        raise CheckError(f"{path}: inventory fields do not match the normative schema")
    if inventory["$schema"] not in allowed_schema_ids:
        raise CheckError(f"{path}: unknown schema reference {inventory['$schema']!r}")
    if inventory["schemaVersion"] != "1.0.0" or inventory["inventoryVersion"] != "1.0.0":
        raise CheckError(f"{path}: unsupported version")
    entries = inventory["entries"]
    if not isinstance(entries, list) or not entries:
        raise CheckError(f"{path}: entries must be a non-empty array")
    paths: set[str] = set()
    total = 0
    entry_fields = {"path", "presence", "producer", "content", "maximumBytes", "privacyTransforms"}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != entry_fields:
            raise CheckError(f"{path}: an entry has missing or unknown fields")
        if entry["path"] in paths:
            raise CheckError(f"{path}: duplicate bundle path {entry['path']}")
        paths.add(entry["path"])
        if entry["presence"] not in {"required", "optional"}:
            raise CheckError(f"{path}: invalid presence for {entry['path']}")
        if not isinstance(entry["maximumBytes"], int) or entry["maximumBytes"] <= 0:
            raise CheckError(f"{path}: invalid maximumBytes for {entry['path']}")
        if not isinstance(entry["privacyTransforms"], list) or not entry["privacyTransforms"]:
            raise CheckError(f"{path}: missing privacy transforms for {entry['path']}")
        total += entry["maximumBytes"]
    if total > inventory["maximumBundleBytes"]:
        raise CheckError(f"{path}: entry maxima exceed maximumBundleBytes")


def _candidate_instance_paths(root: Path) -> Iterable[Path]:
    exact = [root / "dependencies.lock.json"]
    for path in exact:
        if path.is_file():
            yield path
    validation = root / "validation"
    if validation.is_dir():
        yield from validation.rglob("*.json")


def check_instance_references(
    root: Path,
    known_requirements: set[str],
    allowed_schema_ids: set[str],
) -> None:
    matrix_path = root / "validation/capability-matrix.json"
    matrix_coverage: set[str] = set()
    for path in _candidate_instance_paths(root):
        document = load_json(path)
        for key, value in _walk_json(document):
            if key in {"$schema", "schemaId"} and isinstance(value, str):
                if value not in allowed_schema_ids:
                    raise CheckError(f"{path}: unknown schema reference {value!r}")
            if key == "requirementIds" and isinstance(value, list):
                for req_id in value:
                    if not isinstance(req_id, str) or req_id not in known_requirements:
                        raise CheckError(f"{path}: unknown requirement reference {req_id!r}")
                    if path == matrix_path:
                        matrix_coverage.add(req_id)
    if matrix_path.is_file():
        specification = parse_requirements(
            (root / "docs/IMPLEMENTATION-SPEC.md").read_text(encoding="utf-8")
        )
        expected = {req.id for req in specification if req.status != "DEFERRED"}
        missing = expected - matrix_coverage
        if missing:
            raise CheckError(
                f"{matrix_path}: non-deferred requirements lack scenario coverage: "
                + ", ".join(sorted(missing))
            )


def _repository_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIPPED_DIRECTORY_NAMES for part in path.parts):
            continue
        yield path


def _read_text(path: Path, description: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise CheckError(f"{description}: cannot read {path}: {error}") from error


def check_licensing_and_provenance(root: Path) -> None:
    license_text = _read_text(root / "LICENSE", "GPL-2.0 license text")
    if "GNU GENERAL PUBLIC LICENSE" not in license_text or "Version 2, June 1991" not in license_text:
        raise CheckError("GPL-2.0 license text is missing or incomplete")

    notices = _read_text(root / "THIRD_PARTY_NOTICES.md", "third-party notices")
    for notice in (
        "## foo2zjs and bundled JBIG",
        "Robert Szalai",
        "Markus Kuhn",
        "GPL version 2 or later",
        "## PAPPL",
        "Michael R Sweet",
        "embedded portions",
        "Combined Software",
        "## libusb",
        "Johannes Erdfelt",
        "relinking rights",
        "GPL-2.0-or-later",
    ):
        if notice not in notices:
            raise CheckError(f"third-party notices omit {notice}")
    for path, marker in (
        (root / "LICENSES/Apache-2.0.txt", "Apache License"),
        (root / "LICENSES/LGPL-2.1-or-later.txt", "GNU LESSER GENERAL PUBLIC LICENSE"),
    ):
        if marker not in _read_text(path, "third-party license text"):
            raise CheckError(f"third-party license text is missing or incomplete: {path}")

    for path in _repository_files(root):
        if path.suffix not in SOURCE_SUFFIXES:
            continue
        if GPL_IDENTIFIER not in _read_text(path, "original source")[:1024]:
            raise CheckError(f"{path}: missing SPDX-License-Identifier: GPL-2.0-or-later")

    provenance_path = root / "third_party/foo2zjs/adaptations.json"
    provenance = load_json(provenance_path)
    expected_fields = {"schemaVersion", "upstream", "adaptations"}
    if not isinstance(provenance, dict) or set(provenance) != expected_fields:
        raise CheckError(f"{provenance_path}: invalid provenance record")
    upstream = provenance["upstream"]
    if not isinstance(upstream, dict) or upstream != {
        "repository": "https://github.com/OpenPrinting/foo2zjs.git",
        "commit": FOO2ZJS_COMMIT,
        "license": "GPL-2.0-or-later",
    }:
        raise CheckError(f"{provenance_path}: pinned foo2zjs commit or source is inconsistent")
    adaptations = provenance["adaptations"]
    if not isinstance(adaptations, list):
        raise CheckError(f"{provenance_path}: adaptations must be an array")
    upstream_files_path = root / "third_party/foo2zjs/upstream-files.json"
    upstream_files = load_json(upstream_files_path)
    if not isinstance(upstream_files, dict) or set(upstream_files) != {"schemaVersion", "commit", "files"}:
        raise CheckError(f"{upstream_files_path}: invalid pinned upstream file record")
    files = upstream_files["files"]
    if upstream_files["schemaVersion"] != "1.0.0" or upstream_files["commit"] != FOO2ZJS_COMMIT or not isinstance(files, dict):
        raise CheckError(f"{upstream_files_path}: invalid pinned upstream file record")
    if not files or any(
        not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts
        or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
        for path, digest in files.items()
    ):
        raise CheckError(f"{upstream_files_path}: invalid pinned upstream file record")
    risk_text = _read_text(root / "third_party/foo2zjs/PROVENANCE.md", "accepted foo2zjs provenance risk")
    for statement in (
        "Upstream `zjs.h`",
        "unidentified `zjrca.h`",
        "accepted only for a personal-use\ninstallation",
        "public binary release is blocked",
    ):
        if statement not in risk_text:
            raise CheckError("accepted foo2zjs provenance risk is missing or inconsistent")
    seen_paths: set[str] = set()
    for adaptation in adaptations:
        required = {"path", "upstreamPath", "sha256", "modifiedNotice"}
        if not isinstance(adaptation, dict) or set(adaptation) != required:
            raise CheckError(f"{provenance_path}: invalid adaptation record")
        path = adaptation["path"]
        if not isinstance(path, str) or path in seen_paths or Path(path).is_absolute() or ".." in Path(path).parts:
            raise CheckError(f"{provenance_path}: invalid adaptation path")
        upstream_path = adaptation["upstreamPath"]
        if not isinstance(upstream_path, str) or not upstream_path or Path(upstream_path).is_absolute() or ".." in Path(upstream_path).parts:
            raise CheckError(f"{provenance_path}: invalid upstream adaptation path")
        if upstream_path not in files:
            raise CheckError(f"{provenance_path}: unknown pinned upstream file {upstream_path}")
        digest = adaptation["sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise CheckError(f"{provenance_path}: invalid adaptation sha256")
        modified_notice = adaptation["modifiedNotice"]
        if modified_notice != "Modified by HP-LJ-1020-driver contributors":
            raise CheckError(f"{provenance_path}: invalid adaptation modified notice")
        seen_paths.add(path)
        adapted_path = root / "third_party/foo2zjs" / path
        if not adapted_path.is_file() or modified_notice not in _read_text(adapted_path, "adapted foo2zjs source"):
            raise CheckError(f"{adapted_path}: adapted foo2zjs source is not marked as modified")
        if hashlib.sha256(adapted_path.read_bytes()).hexdigest() != digest:
            raise CheckError(f"{adapted_path}: adaptation sha256 is inconsistent")

    foo2zjs_root = root / "third_party/foo2zjs"
    metadata = {foo2zjs_root / "PROVENANCE.md", provenance_path, upstream_files_path}
    undeclared = [path for path in _repository_files(foo2zjs_root) if path not in metadata and str(path.relative_to(foo2zjs_root)) not in seen_paths]
    if undeclared:
        raise CheckError(f"{undeclared[0]}: foo2zjs source or patch is not recorded in adaptations.json")

    for path in _repository_files(root):
        name = path.name.lower()
        data = path.read_bytes()[:4]
        if name in PROHIBITED_FIRMWARE_NAMES or name in {"hp_laserjet_1020.fw.gz", "sihp1020.dl.gz"} or path.suffix.lower() == ".firmware":
            raise CheckError(f"{path}: prohibited firmware artifact")
        if path.suffix.lower() in PROHIBITED_BINARY_SUFFIXES or data.startswith(PROHIBITED_BINARY_MAGICS):
            raise CheckError(f"{path}: prohibited third-party binary artifact")


def run(root: Path) -> None:
    spec_path = root / "docs/IMPLEMENTATION-SPEC.md"
    try:
        text = spec_path.read_text(encoding="utf-8")
    except OSError as error:
        raise CheckError(f"{spec_path}: cannot read specification: {error}") from error
    requirements = parse_requirements(text)
    known = check_requirement_set(requirements)
    check_document_structure(text)
    check_hidden_normative_statements(text)
    schemas, allowed_schema_ids = check_schema_catalog(root)
    check_catalog_pins(text, schemas.values())
    check_diagnostic_inventory(root, allowed_schema_ids)
    check_instance_references(root, set(known), allowed_schema_ids)
    check_licensing_and_provenance(root)


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path(__file__).resolve().parents[1]
    try:
        run(root)
    except CheckError as error:
        print(f"implementation spec check failed: {error}", file=sys.stderr)
        return 1
    print("implementation spec check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
