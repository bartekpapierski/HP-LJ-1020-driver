#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Validate privacy-safe output measurements against the print oracle."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SCHEMA_ID = (
    "https://bartekpapierski.github.io/HP-LJ-1020-driver/"
    "schemas/output-measurement-1.0.0.json"
)
SHA256 = re.compile(r"^[a-f0-9]{64}$")


class MeasurementError(ValueError):
    pass


def _exact_fields(value: dict[str, Any], expected: set[str], name: str) -> None:
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown or missing:
        details = []
        if unknown:
            details.append(f"unknown fields {', '.join(sorted(unknown))}")
        if missing:
            details.append(f"missing fields {', '.join(sorted(missing))}")
        raise MeasurementError(f"{name} has {'; '.join(details)}")


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MeasurementError(f"{name} must be an object")
    return value


def _integer_list(value: Any, name: str) -> list[int]:
    if not isinstance(value, list) or any(
        not isinstance(item, int) or isinstance(item, bool) or item < 1 for item in value
    ):
        raise MeasurementError(f"{name} must contain positive page numbers")
    if len(set(value)) != len(value):
        raise MeasurementError(f"{name} contains duplicate page numbers")
    return value


def _number(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise MeasurementError(f"{name} must be a number")
    return float(value)


def validate_measurement(document: dict[str, Any]) -> None:
    """Validate one measurement record, including whether its result is truthful."""
    if not isinstance(document, dict):
        raise MeasurementError("measurement must be an object")
    _exact_fields(document, {
        "$schema", "schemaVersion", "measurementId", "scenarioId",
        "sourceDocumentSha256", "measuredAt", "expected", "observed",
        "visualInspection", "privacy", "result",
    }, "measurement")
    if document.get("$schema") != SCHEMA_ID or document.get("schemaVersion") != "1.0.0":
        raise MeasurementError("unsupported output measurement schema")
    if not isinstance(document.get("measurementId"), str) or not document["measurementId"]:
        raise MeasurementError("measurementId is required")
    if not isinstance(document.get("scenarioId"), str) or not document["scenarioId"].startswith("SCN-"):
        raise MeasurementError("scenarioId is invalid")
    source_hash = document.get("sourceDocumentSha256")
    if not isinstance(source_hash, str) or not SHA256.fullmatch(source_hash):
        raise MeasurementError("sourceDocumentSha256 is invalid")
    if not isinstance(document.get("measuredAt"), str) or not document["measuredAt"]:
        raise MeasurementError("measuredAt is required")

    expected = _object(document.get("expected"), "expected")
    observed = _object(document.get("observed"), "observed")
    _exact_fields(expected, {"pageCount", "pageOrder"}, "expected")
    _exact_fields(observed, {
        "pageCount", "pageOrder", "blankPages", "partialPages", "missingPages",
        "duplicatePages", "scaleErrorPercent", "maximumFiducialDisplacementMm",
        "clippingInsidePrintableRegion", "orientationCorrect", "mediaCorrect",
    }, "observed")
    expected_count = expected.get("pageCount")
    observed_count = observed.get("pageCount")
    if not isinstance(expected_count, int) or isinstance(expected_count, bool) or expected_count < 1:
        raise MeasurementError("expected page count must be positive")
    if not isinstance(observed_count, int) or isinstance(observed_count, bool) or observed_count < 0:
        raise MeasurementError("observed page count must be non-negative")
    expected_order = _integer_list(expected.get("pageOrder"), "expected page order")
    observed_order = _integer_list(observed.get("pageOrder"), "observed page order")

    failures: list[str] = []
    if len(expected_order) != expected_count:
        raise MeasurementError("expected page count and order disagree")
    if len(observed_order) != observed_count:
        failures.append("observed page count and order disagree")
    if observed_count != expected_count:
        failures.append("page count")
    if observed_order != expected_order:
        failures.append("page order")
    for field, label in (
        ("blankPages", "blank pages"),
        ("partialPages", "partial pages"),
        ("missingPages", "missing pages"),
        ("duplicatePages", "duplicate pages"),
    ):
        if _integer_list(observed.get(field), label):
            failures.append(label)
    if abs(_number(observed.get("scaleErrorPercent"), "scale error")) > 1.0:
        failures.append("scale error exceeds 1 percent")
    displacement = _number(
        observed.get("maximumFiducialDisplacementMm"), "fiducial displacement"
    )
    if displacement < 0 or displacement > 2.0:
        failures.append("fiducial displacement exceeds 2 mm")
    for field, label, passing_value in (
        ("clippingInsidePrintableRegion", "clipping inside printable region", False),
        ("orientationCorrect", "orientation", True),
        ("mediaCorrect", "media selection", True),
    ):
        value = observed.get(field)
        if not isinstance(value, bool):
            raise MeasurementError(f"{label} must be boolean")
        if value is not passing_value:
            failures.append(label)

    inspection = _object(document.get("visualInspection"), "visualInspection")
    _exact_fields(inspection, {
        "performed", "finePatternsReadable", "visibleCorruption",
        "densityDiscontinuity",
    }, "visualInspection")
    for field in (
        "performed",
        "finePatternsReadable",
        "visibleCorruption",
        "densityDiscontinuity",
    ):
        if not isinstance(inspection.get(field), bool):
            raise MeasurementError(f"visual inspection {field} must be boolean")
    if not inspection["performed"]:
        failures.append("visual inspection was not performed")
    if not inspection["finePatternsReadable"]:
        failures.append("fine patterns are not readable")
    if inspection["visibleCorruption"]:
        failures.append("visible corruption")
    if inspection["densityDiscontinuity"]:
        failures.append("density discontinuity")

    privacy = _object(document.get("privacy"), "privacy")
    _exact_fields(privacy, {
        "documentContentsRetained", "rasterPayloadRetained", "zjStreamPayloadRetained",
    }, "privacy")
    for field, label in (
        ("documentContentsRetained", "document contents"),
        ("rasterPayloadRetained", "raster payload"),
        ("zjStreamPayloadRetained", "ZjStream payload"),
    ):
        if privacy.get(field) is not False:
            raise MeasurementError(f"privacy contract forbids retaining {label}")

    expected_result = "failed" if failures else "passed"
    if document.get("result") != expected_result:
        detail = failures[0] if failures else "all output criteria passed"
        raise MeasurementError(f"result does not match measurement: {detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("measurement", type=Path)
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.measurement.read_text(encoding="utf-8"))
        validate_measurement(document)
    except (OSError, json.JSONDecodeError, MeasurementError) as error:
        print(f"output measurement rejected: {error}", file=sys.stderr)
        return 1
    print("output measurement accepted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
