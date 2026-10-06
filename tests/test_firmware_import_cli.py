#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""The production import CLI fails closed without an approved payload."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


PROVIDER = Path(__file__).resolve().parents[1] / "build" / "hplj1020"


class FirmwareImportCliTests(unittest.TestCase):
    def test_missing_affirmation_does_not_consume_or_store_firmware(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "firmware"
            result = subprocess.run(
                [
                    PROVIDER, "--import-firmware", "--firmware", destination,
                    "--source", "synthetic fixture",
                ],
                input=b"synthetic fixture",
                capture_output=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertTrue(result.stderr.startswith(b"HP owns the required firmware"))
            self.assertIn(b"separate terms", result.stderr)
            self.assertIn(b"no redistribution rights", result.stderr)
            self.assertFalse(destination.exists())

    def test_unapproved_bytes_are_not_stored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "firmware"
            result = subprocess.run(
                [
                    PROVIDER, "--import-firmware", "--firmware", destination,
                    "--source", "synthetic fixture", "--affirm-lawful-acquisition",
                ],
                input=b"synthetic fixture",
                capture_output=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn(b"firmware-unsupported", result.stderr)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
