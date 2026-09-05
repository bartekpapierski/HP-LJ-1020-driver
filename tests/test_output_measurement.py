# SPDX-License-Identifier: GPL-2.0-or-later
"""Behavioral tests for the privacy-safe output measurement contract."""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts import output_measurement as measurement

ROOT = Path(__file__).resolve().parents[1]


def passing_measurement() -> dict[str, object]:
    return {
        "$schema": (
            "https://bartekpapierski.github.io/HP-LJ-1020-driver/"
            "schemas/output-measurement-1.0.0.json"
        ),
        "schemaVersion": "1.0.0",
        "measurementId": "measurement-1",
        "scenarioId": "SCN-OUTPUT-ORACLE",
        "sourceDocumentSha256": "a" * 64,
        "measuredAt": "2026-09-05T10:00:00Z",
        "expected": {"pageCount": 2, "pageOrder": [1, 2]},
        "observed": {
            "pageCount": 2,
            "pageOrder": [1, 2],
            "blankPages": [],
            "partialPages": [],
            "missingPages": [],
            "duplicatePages": [],
            "scaleErrorPercent": 1.0,
            "maximumFiducialDisplacementMm": 2.0,
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


class OutputMeasurementChecks(unittest.TestCase):
    def test_boundary_values_pass(self) -> None:
        measurement.validate_measurement(passing_measurement())

    def test_wrong_page_order_is_rejected(self) -> None:
        document = passing_measurement()
        document["observed"]["pageOrder"] = [2, 1]
        with self.assertRaisesRegex(measurement.MeasurementError, "page order"):
            measurement.validate_measurement(document)

    def test_scale_over_one_percent_is_rejected(self) -> None:
        document = passing_measurement()
        document["observed"]["scaleErrorPercent"] = 1.01
        with self.assertRaisesRegex(measurement.MeasurementError, "scale error"):
            measurement.validate_measurement(document)

    def test_displacement_over_two_millimetres_is_rejected(self) -> None:
        document = passing_measurement()
        document["observed"]["maximumFiducialDisplacementMm"] = 2.01
        with self.assertRaisesRegex(measurement.MeasurementError, "fiducial displacement"):
            measurement.validate_measurement(document)

    def test_retaining_a_payload_is_rejected(self) -> None:
        document = passing_measurement()
        document["privacy"]["rasterPayloadRetained"] = True
        with self.assertRaisesRegex(measurement.MeasurementError, "raster payload"):
            measurement.validate_measurement(document)

    def test_machine_measurements_cannot_replace_visual_inspection(self) -> None:
        document = passing_measurement()
        document["visualInspection"]["performed"] = False
        with self.assertRaisesRegex(measurement.MeasurementError, "visual inspection"):
            measurement.validate_measurement(document)


if __name__ == "__main__":
    unittest.main()
