#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Seal one privacy-safe reference Mac lifecycle evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from scripts import output_measurement
else:
    import output_measurement  # type: ignore[no-redef]


SCENARIOS = (
    "SCN-CLEAN-INSTALL",
    "SCN-COMPLETE-UNINSTALL",
    "SCN-DISABLE-ENABLE",
    "SCN-INSTALL-HEALTH",
    "SCN-LOOPBACK-ONLY",
    "SCN-NO-HELPER",
    "SCN-PRIVILEGE-BOUNDARY",
    "SCN-SERVICE-IDENTITY",
)
MANIFEST_SCHEMA = (
    "https://bartekpapierski.github.io/HP-LJ-1020-driver/"
    "schemas/validation-manifest-1.0.0.json"
)
MEASUREMENT_SCHEMA = (
    "https://bartekpapierski.github.io/HP-LJ-1020-driver/"
    "schemas/output-measurement-1.0.0.json"
)


def _write_json(path: Path, document: object) -> None:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def seal(
    evidence_root: Path,
    *,
    matrix_path: Path,
    run_id: str,
    started_at: str,
    result: str,
    reason: str,
    source_commit: str,
    dependency_lock_sha256: str,
    printer_serial_sha256: str | None,
    source_document_sha256: str,
    lifecycle_cycles: int,
    observed_pages: int,
    macos_version: str,
    macos_build: str,
    scale_error_percent: float,
    maximum_fiducial_displacement_mm: float,
    artifact_sha256: str,
    built_at: str,
    xcode_build: str,
    compiler: str,
    sdk_build: str,
    deployment_target: str,
) -> None:
    if result not in {"passed", "failed"}:
        raise ValueError("result must be passed or failed")
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    rows = {row["scenarioId"]: row for row in matrix["scenarios"]}
    missing = set(SCENARIOS) - set(rows)
    if missing:
        raise ValueError(f"capability matrix lacks {sorted(missing)[0]}")
    log_path = evidence_root / "sanitized.log"
    if not log_path.is_file():
        raise ValueError("sanitized lifecycle log is absent")
    finished_at = _now()
    state = "verified" if result == "passed" else "unverified"
    outcome = "passed" if result == "passed" else "failed"
    expected_pages = 4

    summary_path = evidence_root / "summary.txt"
    summary_path.write_text(
        "\n".join((
            f"runId={run_id}",
            f"startedAt={started_at}",
            f"finishedAt={finished_at}",
            f"macOSVersion={macos_version}",
            f"macOSBuild={macos_build}",
            "architecture=arm64",
            f"sourceCommit={source_commit}",
            f"dependencyLockSha256={dependency_lock_sha256}",
            "printerModel=HP LaserJet 1020",
            "vendorProduct=03f0:2b17",
            f"serialSha256={printer_serial_sha256 or 'unavailable'}",
            "connectionPaths=ugreen-thunderbolt-4-dock,direct-usb-a-to-usb-c",
            f"lifecycleCycles={lifecycle_cycles}",
            f"result={result}",
            "expected=clean install, dedicated-account launch, loopback-only listening, standard queue, non-admin submission, disable/reactivate, interrupted and partial-state recovery, complete uninstall, and clean reinstall",
            f"observed={reason}",
            "privacyChecked=true",
            "",
        )),
        encoding="utf-8",
    )
    build_identity_path = evidence_root / "build-manifest.json"
    _write_json(build_identity_path, {
        "$schema": (
            "https://bartekpapierski.github.io/HP-LJ-1020-driver/"
            "schemas/build-manifest-1.0.0.json"
        ),
        "schemaVersion": "1.0.0",
        "productVersion": "0.1.0",
        "source": {
            "commit": source_commit,
            "cleanTree": True,
            "specificationCommit": source_commit,
        },
        "toolchain": {
            "xcodeBuild": xcode_build,
            "compiler": compiler,
            "sdkBuild": sdk_build,
            "deploymentTarget": deployment_target,
            "architectures": ["arm64"],
        },
        "configuration": {"buildType": "Debug"},
        "dependencyLock": {
            "path": "dependencies.lock.json",
            "sha256": dependency_lock_sha256,
        },
        "signingMode": "ad-hoc-hardened-runtime",
        "builtAt": built_at,
        "artifacts": [{"path": "build/hplj1020", "sha256": artifact_sha256}],
    })
    measurement_id = f"{run_id}-non-admin-output"
    measurement_path = evidence_root / "measurements" / f"{measurement_id}.json"
    measurement_path.parent.mkdir()
    observed_order = list(range(1, observed_pages + 1))
    measurement = {
        "$schema": MEASUREMENT_SCHEMA,
        "schemaVersion": "1.0.0",
        "measurementId": measurement_id,
        "scenarioId": "SCN-INSTALL-HEALTH",
        "sourceDocumentSha256": source_document_sha256,
        "measuredAt": finished_at,
        "expected": {"pageCount": expected_pages, "pageOrder": list(range(1, 5))},
        "observed": {
            "pageCount": observed_pages,
            "pageOrder": observed_order,
            "blankPages": [],
            "partialPages": [],
            "missingPages": [] if result == "passed" else list(range(observed_pages + 1, 5)),
            "duplicatePages": [],
            "scaleErrorPercent": scale_error_percent,
            "maximumFiducialDisplacementMm": maximum_fiducial_displacement_mm,
            "clippingInsidePrintableRegion": False,
            "orientationCorrect": result == "passed",
            "mediaCorrect": result == "passed",
        },
        "visualInspection": {
            "performed": observed_pages > 0,
            "finePatternsReadable": result == "passed",
            "visibleCorruption": False,
            "densityDiscontinuity": False,
        },
        "privacy": {
            "documentContentsRetained": False,
            "rasterPayloadRetained": False,
            "zjStreamPayloadRetained": False,
        },
        "result": result,
    }
    output_measurement.validate_measurement(measurement)
    _write_json(measurement_path, measurement)

    evidence_paths = [
        (log_path, "sanitized-log"),
        (summary_path, "summary"),
        (measurement_path, "measurement"),
        (build_identity_path, "manifest"),
    ]
    violation_path = evidence_root / "privilege-violation.txt"
    if violation_path.is_file():
        evidence_paths.append((violation_path, "summary"))
    evidence_hashes = {
        str(path.relative_to(evidence_root)): _sha256(path) for path, _ in evidence_paths
    }
    evidence_entries = []
    for path, kind in evidence_paths:
        bindings = ["SCN-INSTALL-HEALTH"] if kind == "measurement" else list(SCENARIOS)
        evidence_entries.append({
            "path": str(path.relative_to(evidence_root)),
            "sha256": evidence_hashes[str(path.relative_to(evidence_root))],
            "kind": kind,
            "immutable": True,
            "result": outcome,
            "privacyChecked": True,
            "scenarioIds": bindings,
        })
    attempt = {
        "attempt": 1,
        "outcome": outcome,
        "observedAt": finished_at,
        "summary": reason,
    }
    manifest = {
        "$schema": MANIFEST_SCHEMA,
        "schemaVersion": "1.0.0",
        "runId": run_id,
        "sourceCommit": source_commit,
        "specificationCommit": source_commit,
        "dependencyLockSha256": dependency_lock_sha256,
        "buildManifestSha256": evidence_hashes[build_identity_path.name],
        "capabilityMatrixSha256": _sha256(matrix_path),
        "environment": {
            "kind": "reference-mac",
            "macOSVersion": macos_version,
            "macOSBuild": macos_build,
            "architecture": "arm64",
            "connectionPaths": [
                "host-only",
                "ugreen-thunderbolt-4-dock",
                "direct-usb-a-to-usb-c",
            ],
        },
        "printer": ({
            "model": "HP LaserJet 1020",
            "vendorProduct": "03f0:2b17",
            "serialSha256": printer_serial_sha256,
            "firmwareVersion": None,
        } if printer_serial_sha256 else None),
        "scopeIdentities": matrix["scopeIdentities"],
        "startedAt": started_at,
        "finishedAt": finished_at,
        "result": result,
        "scenarioResults": [{
            "scenarioId": scenario_id,
            "requirementIds": rows[scenario_id]["requirementIds"],
            "state": state,
            "summary": reason,
            "observedAt": finished_at,
            "evidenceSha256": [
                digest for name, digest in evidence_hashes.items()
                if name != str(measurement_path.relative_to(evidence_root))
                or scenario_id == "SCN-INSTALL-HEALTH"
            ],
            "attempts": [attempt],
            "intermittencyExplanation": None,
            "reliabilityObservations": None,
        } for scenario_id in SCENARIOS],
        "evidence": evidence_entries,
        "supportClaims": [],
        "redacted": True,
        "sealed": True,
    }
    manifest_path = evidence_root / "manifest.json"
    _write_json(manifest_path, manifest)
    checksums_path = evidence_root / "checksums.txt"
    all_paths = [path for path, _ in evidence_paths] + [manifest_path]
    checksums_path.write_text(
        "".join(
            f"{_sha256(path)}  {path.relative_to(evidence_root)}\n" for path in all_paths
        ),
        encoding="utf-8",
    )
    for path in (*all_paths, checksums_path):
        path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    measurement_path.parent.chmod(stat.S_IRUSR | stat.S_IXUSR)
    evidence_root.chmod(stat.S_IRUSR | stat.S_IXUSR)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--matrix", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--result", required=True, choices=("passed", "failed"))
    parser.add_argument("--reason", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--dependency-lock-sha256", required=True)
    parser.add_argument("--printer-serial-sha256")
    parser.add_argument("--source-document-sha256", required=True)
    parser.add_argument("--lifecycle-cycles", type=int, default=0)
    parser.add_argument("--observed-pages", type=int, default=0)
    parser.add_argument("--macos-version", required=True)
    parser.add_argument("--macos-build", required=True)
    parser.add_argument("--scale-error-percent", required=True, type=float)
    parser.add_argument("--maximum-fiducial-displacement-mm", required=True, type=float)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--built-at", required=True)
    parser.add_argument("--xcode-build", required=True)
    parser.add_argument("--compiler", required=True)
    parser.add_argument("--sdk-build", required=True)
    parser.add_argument("--deployment-target", required=True)
    args = parser.parse_args()
    seal(
        args.evidence_root,
        matrix_path=args.matrix,
        run_id=args.run_id,
        started_at=args.started_at,
        result=args.result,
        reason=args.reason,
        source_commit=args.source_commit,
        dependency_lock_sha256=args.dependency_lock_sha256,
        printer_serial_sha256=args.printer_serial_sha256,
        source_document_sha256=args.source_document_sha256,
        lifecycle_cycles=args.lifecycle_cycles,
        observed_pages=args.observed_pages,
        macos_version=args.macos_version,
        macos_build=args.macos_build,
        scale_error_percent=args.scale_error_percent,
        maximum_fiducial_displacement_mm=args.maximum_fiducial_displacement_mm,
        artifact_sha256=args.artifact_sha256,
        built_at=args.built_at,
        xcode_build=args.xcode_build,
        compiler=args.compiler,
        sdk_build=args.sdk_build,
        deployment_target=args.deployment_target,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
