# SPDX-License-Identifier: GPL-2.0-or-later
"""Behavioral tests for the audited build command-line interface."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts" / "build"


class BuildWrapperChecks(unittest.TestCase):
    def run_build(
        self, *arguments: str, root: Path = ROOT, environment: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(root / "scripts" / "build"), *arguments],
            cwd=root,
            check=False,
            text=True,
            capture_output=True,
            env=environment,
        )

    def test_repository_lock_verifies_without_network_access(self) -> None:
        result = self.run_build("--verify-lock")

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_personal_release_rejects_an_unverified_source_override(self) -> None:
        environment = {"HPLJ1020_SOURCE_OVERRIDE": "/tmp/not-a-source"}
        result = self.run_build("--personal-release", "--verify-lock", environment=environment)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("personal-release builds reject source overrides", result.stderr)

    def test_lock_rejects_a_floating_dependency_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "repository"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__", "build/"))
            lock_path = copy / "dependencies.lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["dependencies"][0]["version"] = "main"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")

            result = self.run_build("--verify-lock", root=copy)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("floating version", result.stderr)


if __name__ == "__main__":
    unittest.main()
