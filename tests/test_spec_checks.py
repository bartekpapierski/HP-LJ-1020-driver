from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_implementation_spec", ROOT / "scripts/check_implementation_spec.py"
)
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)


def row(
    req_id: str = "SCOPE-001",
    status: str = "REQUIRED",
    coverage: str = "SCN-TEST",
    source: str = "[Issue #1](https://github.com/bartekpapierski/HP-LJ-1020-driver/issues/1)",
) -> str:
    return (
        f"| {req_id} | The implementation MUST pass. | {status} | BASIC | HOST | "
        f"{coverage} | Test | {source} |"
    )


class RequirementChecks(unittest.TestCase):
    def test_duplicate_ids_are_rejected(self) -> None:
        requirements = checker.parse_requirements(row() + "\n" + row())
        with self.assertRaisesRegex(checker.CheckError, "duplicate requirement ID"):
            checker.check_requirement_set(requirements)

    def test_missing_coverage_is_rejected(self) -> None:
        with self.assertRaisesRegex(checker.CheckError, "uncovered"):
            checker.parse_requirements(row(coverage=""))

    def test_missing_traceability_field_is_rejected(self) -> None:
        with self.assertRaisesRegex(checker.CheckError, "empty field"):
            checker.parse_requirements(row().replace("| Test |", "|  |"))

    def test_broken_decision_link_is_rejected(self) -> None:
        broken = "[Issue #1](https://github.com/bartekpapierski/HP-LJ-1020-driver/issues/2)"
        with self.assertRaisesRegex(checker.CheckError, "mismatched decision link"):
            checker.parse_requirements(row(source=broken))

    def test_normative_keyword_outside_row_is_rejected(self) -> None:
        with self.assertRaisesRegex(checker.CheckError, "outside a requirement row"):
            checker.check_hidden_normative_statements("An implementation MUST drift.\n")


class ArtifactReferenceChecks(unittest.TestCase):
    def test_unknown_requirement_reference_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            validation = root / "validation/runs/test"
            validation.mkdir(parents=True)
            (validation / "manifest.json").write_text(
                json.dumps({"requirementIds": ["NOPE-999"]}), encoding="utf-8"
            )
            with self.assertRaisesRegex(checker.CheckError, "unknown requirement reference"):
                checker.check_instance_references(root, {"SCOPE-001"}, set())

    def test_unknown_schema_reference_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "validation").mkdir()
            (root / "validation/artifact.json").write_text(
                json.dumps({"$schema": "https://example.invalid/unknown.json"}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(checker.CheckError, "unknown schema reference"):
                checker.check_instance_references(root, set(), set())


class LicensingAndProvenanceChecks(unittest.TestCase):
    def copy_repository(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name) / "repository"
        shutil.copytree(
            ROOT,
            root,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
        )
        self.addCleanup(temporary.cleanup)
        return temporary, root

    def test_complete_license_and_provenance_baseline_passes(self) -> None:
        _, root = self.copy_repository()

        checker.check_licensing_and_provenance(root)

    def test_missing_gpl_license_is_rejected(self) -> None:
        _, root = self.copy_repository()
        (root / "LICENSE").unlink()

        with self.assertRaisesRegex(checker.CheckError, "GPL-2.0 license text"):
            checker.check_licensing_and_provenance(root)

    def test_original_source_without_required_spdx_identifier_is_rejected(self) -> None:
        _, root = self.copy_repository()
        source = root / "prototypes/pwg-to-pbm.c"
        source.write_text(source.read_text(encoding="utf-8").replace(
            "SPDX-License-Identifier: GPL-2.0-or-later\n", "", 1
        ), encoding="utf-8")

        with self.assertRaisesRegex(checker.CheckError, "missing SPDX-License-Identifier"):
            checker.check_licensing_and_provenance(root)

    def test_unpinned_foo2zjs_provenance_is_rejected(self) -> None:
        _, root = self.copy_repository()
        record = root / "third_party/foo2zjs/adaptations.json"
        record.write_text(record.read_text(encoding="utf-8").replace(
            "80499ed5bf6caa2963ad337e37cfda78a80aab1e", "0" * 40
        ), encoding="utf-8")

        with self.assertRaisesRegex(checker.CheckError, "pinned foo2zjs commit"):
            checker.check_licensing_and_provenance(root)

    def test_hp_firmware_artifact_is_rejected(self) -> None:
        _, root = self.copy_repository()
        firmware = root / "firmware/sihp1020.dl"
        firmware.parent.mkdir()
        firmware.write_bytes(b"not redistributable")

        with self.assertRaisesRegex(checker.CheckError, "prohibited firmware artifact"):
            checker.check_licensing_and_provenance(root)


if __name__ == "__main__":
    unittest.main()
