# SPDX-License-Identifier: GPL-2.0-or-later
from __future__ import annotations

import importlib.util
import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_artifacts", ROOT / "scripts/check_artifacts.py"
)
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class ArtifactPolicyChecks(unittest.TestCase):
    def test_firmware_module_object_is_not_mistaken_for_firmware_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "firmware.c.o").write_bytes(b"synthetic object fixture")

            checker.check_artifacts(root)

    def test_hp_firmware_payload_name_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "sihp1020.dl").write_bytes(b"synthetic payload fixture")

            with self.assertRaisesRegex(checker.ArtifactError, "forbidden artifact content"):
                checker.check_artifacts(root)

    def test_firmware_nested_in_an_archive_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with zipfile.ZipFile(root / "release.zip", "w") as archive:
                archive.writestr("Resources/firmware/sihp1020.dl", b"synthetic payload fixture")

            with self.assertRaisesRegex(checker.ArtifactError, "release.zip"):
                checker.check_artifacts(root)

    def test_known_firmware_contents_are_rejected_after_renaming(self) -> None:
        payload = b"synthetic known firmware contents"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "payload.bin").write_bytes(payload)

            with self.assertRaisesRegex(checker.ArtifactError, "payload.bin"):
                checker.check_artifacts(root, {digest})

    def test_known_firmware_contents_are_rejected_inside_renamed_archive_member(self) -> None:
        payload = b"synthetic known firmware contents"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with zipfile.ZipFile(root / "release.zip", "w") as archive:
                archive.writestr("Resources/payload.bin", payload)

            with self.assertRaisesRegex(checker.ArtifactError, "release.zip"):
                checker.check_artifacts(root, {digest})


if __name__ == "__main__":
    unittest.main()
