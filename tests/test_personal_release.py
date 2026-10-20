# SPDX-License-Identifier: GPL-2.0-or-later
"""Host-only release operations: no printer, signing identity, CI secret, or tag promotion."""

from __future__ import annotations

import argparse
import contextlib
import io
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from scripts import personal_release as release
from scripts.product_version import read_version

ROOT = Path(__file__).resolve().parents[1]


class PersonalReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "repository"
        self.root.mkdir()
        self.archive = self.base / "archive"
        self.operation = release.Release(self.root, self.archive)
        self.run_id = uuid.uuid4().hex
        self.path = self.operation.run_path(self.run_id)
        self.git("init", "-q")
        self.git("config", "user.name", "Host Test")
        self.git("config", "user.email", "host@example.invalid")
        (self.root / "VERSION").write_text("0.1.0\n")
        self.git("add", ".")
        self.git("commit", "-qm", "candidate")
        self.commit = self.git("rev-parse", "HEAD")

    def cleanup(self) -> None:
        for parent, directories, files in os.walk(self.temporary.name):
            Path(parent).chmod(0o755)
            for name in directories:
                path = Path(parent) / name
                if not path.is_symlink():
                    path.chmod(0o755)
            for name in files:
                path = Path(parent) / name
                if not path.is_symlink():
                    path.chmod(0o644)
        self.temporary.cleanup()

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, check=True,
                              capture_output=True, text=True).stdout.strip()

    def prepared(self) -> None:
        inputs = self.path / "inputs"
        inputs.mkdir(parents=True)
        for name in ("source.bundle", "HP-LJ-1020.app.zip", "dependencies.lock.json",
                     "THIRD_PARTY_NOTICES.md", "sbom.spdx.json"):
            (inputs / name).write_text("public fixture\n")
        release.write_json(inputs / "build-manifest.json", {"ciRun": None})
        release.readonly(inputs)
        self.operation.record(self.run_id, "prepared", list(inputs.iterdir()),
                              commit=self.commit, version="0.1.0")

    def validated(self) -> list[dict]:
        self.prepared()
        self.operation.record(self.run_id, "hosted-ci-passed", [],
                              ci={"provider": "github-actions", "runId": "17", "commit": self.commit})
        pointer = {}
        for name in ("manifest", "matrix"):
            file = self.root / f"{name}.json"
            file.write_text("{}\n")
            pointer[name] = {"path": file.name, "sha256": release.digest(file)}
        self.operation.record(self.run_id, "locally-validated", [], validation=pointer)
        return self.operation.records(self.run_id)

    def notes(self) -> Path:
        file = self.base / "notes.md"
        file.write_text("\n".join(f"## {field}\nReviewed." for field in release.NOTES_FIELDS))
        return file

    def test_single_version_rejects_non_semver_and_compatibility_promises(self) -> None:
        self.assertEqual(read_version(self.root), "0.1.0")
        for invalid in ("v0.1.0", "0.01.0", "1.0.0", "0.1", "0.1.0\n0.2.0"):
            (self.root / "VERSION").write_text(invalid)
            with self.assertRaises(ValueError):
                read_version(self.root)

    def test_archive_must_be_outside_checkout(self) -> None:
        with self.assertRaisesRegex(release.ReleaseError, "outside"):
            release.Release(self.root, self.root / "build/releases")

    def test_dirty_candidate_is_rejected_before_any_host_command(self) -> None:
        (self.root / "untracked").write_text("dirty")
        with self.assertRaisesRegex(release.ReleaseError, "clean"):
            self.operation.candidate()

    def test_source_bundle_is_real_and_removed_private_history_is_rejected(self) -> None:
        output = self.base / "source.bundle"
        self.operation.source_bundle(output, self.commit)
        self.assertIn(self.commit, self.git("bundle", "list-heads", str(output)))
        (self.root / ".env").write_text("private fixture")
        self.git("add", ".")
        self.git("commit", "-qm", "private")
        (self.root / ".env").unlink()
        self.git("add", "-u")
        self.git("commit", "-qm", "removed")
        with self.assertRaisesRegex(release.ReleaseError, "prohibited path"):
            self.operation.source_bundle(self.base / "bad.bundle", self.git("rev-parse", "HEAD"))
        self.assertFalse((self.base / "bad.bundle").exists())

    def test_known_firmware_is_rejected_under_an_unremarkable_filename(self) -> None:
        content = b"nonproprietary firmware test fixture"
        (self.root / "ordinary-data.bin").write_bytes(content)
        self.git("add", ".")
        self.git("commit", "-qm", "disguised artifact")
        with mock.patch.object(release, "FIRMWARE_DIGESTS", {hashlib.sha256(content).hexdigest()}):
            with self.assertRaisesRegex(release.ReleaseError, "prohibited content"):
                self.operation.source_bundle(self.base / "forbidden.bundle", self.git("rev-parse", "HEAD"))
        self.assertFalse((self.base / "forbidden.bundle").exists())

    def test_preparation_builds_once_and_verifies_resume(self) -> None:
        (self.root / "dependencies.lock.json").write_text("{}")
        (self.root / "THIRD_PARTY_NOTICES.md").write_text("notices")
        app = self.base / "app"
        app.mkdir()
        real_command = self.operation.command

        def command(*args: str, **kwargs: object) -> str:
            if args[0] == "/usr/bin/ditto":
                Path(args[-1]).write_text("zip fixture")
                return ""
            if args[0] == release.sys.executable:
                Path(args[-1]).write_text("{}")
                return ""
            return real_command(*args, **kwargs)

        with (mock.patch.object(self.operation, "candidate", return_value=(self.commit, "0.1.0")),
              mock.patch.object(self.operation, "merged"),
              mock.patch.object(self.operation, "check_payload"),
              mock.patch.object(self.operation, "build_manifest", return_value={"ciRun": None}),
              mock.patch.object(self.operation, "command", side_effect=command),
              mock.patch.object(release.personal_install, "STAGED_APP", app),
              mock.patch.object(release.personal_install, "stage_and_sign") as build):
            self.operation.prepare(self.run_id)
            self.operation.prepare(self.run_id)
            self.assertEqual(build.call_count, 1)
        self.assertEqual(len(self.operation.records(self.run_id)), 1)
        self.assertFalse(self.git("tag", "--list"))

    def test_prepared_resume_rejects_a_different_candidate(self) -> None:
        self.prepared()
        with (mock.patch.object(self.operation, "candidate", return_value=("0" * 40, "0.1.0")),
              mock.patch.object(self.operation, "merged")):
            with self.assertRaisesRegex(release.ReleaseError, "identity changed"):
                self.operation.prepare(self.run_id)

    def test_resume_detects_modified_or_added_inputs(self) -> None:
        self.prepared()
        file = self.path / "inputs/source.bundle"
        file.chmod(0o644)
        file.write_text("corrupt")
        file.chmod(0o444)
        with self.assertRaisesRegex(release.ReleaseError, "checksum"):
            self.operation.records(self.run_id)

    def test_resume_rejects_inventory_growth(self) -> None:
        self.prepared()
        inputs = self.path / "inputs"
        inputs.chmod(0o755)
        (inputs / "extra").write_text("unrecorded")
        with self.assertRaisesRegex(release.ReleaseError, "inventory"):
            self.operation.records(self.run_id)

    def test_sealing_is_readonly_complete_and_resumable_after_interruption(self) -> None:
        records = self.validated()
        notes = self.notes()
        with mock.patch.object(self.operation, "record", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.operation.seal(self.run_id, records, notes)
        bundle = self.archive / "releases/v0.1.0"
        first = release.inventory(bundle)
        self.operation.seal(self.run_id, records, notes)
        self.assertEqual(first, release.inventory(bundle))
        self.operation.verify_seal(bundle)
        self.assertEqual(len(self.operation.records(self.run_id)), 4)
        self.assertIn("SHA256SUMS", first)
        self.assertIn("validation-pointer.json", first)
        self.assertIn("validated-build-manifest.json", first)
        self.assertEqual(release.document(bundle / "build-manifest.json")["ciRun"]["runId"], "17")
        self.assertFalse(self.git("tag", "--list"))

    def test_sealed_corruption_is_rejected_even_when_file_is_readonly(self) -> None:
        records = self.validated()
        self.operation.seal(self.run_id, records, self.notes())
        bundle = self.archive / "releases/v0.1.0"
        notes = bundle / "RELEASE-NOTES.md"
        notes.chmod(0o644)
        notes.write_text("changed")
        notes.chmod(0o444)
        with self.assertRaisesRegex(release.ReleaseError, "inventory mismatch"):
            self.operation.verify_seal(bundle)

    def test_failed_attempts_have_distinct_redacted_immutable_records_and_no_tags(self) -> None:
        self.prepared()
        first = self.operation.failure(self.run_id, "locally-validated")
        second = self.operation.failure(self.run_id, "locally-validated")
        self.assertNotEqual(first, second)
        for failure_id in (first, second):
            summary = self.archive / "failed" / failure_id / "summary.json"
            value = release.document(summary)
            self.assertEqual(value["sourceCommit"], self.commit)
            self.assertTrue(value["redacted"])
            self.assertFalse(summary.stat().st_mode & 0o222)
            self.assertNotIn(str(self.base), summary.read_text())
        with self.assertRaisesRegex(release.ReleaseError, "new run ID"):
            self.operation.records(self.run_id)
        self.assertFalse(self.git("tag", "--list"))
        self.assertFalse((self.archive / "releases").exists())

    def test_cli_failure_records_cause_without_external_error_details(self) -> None:
        output = io.StringIO()
        with (mock.patch.object(release, "ROOT", self.root),
              mock.patch.object(release.Release, "candidate", side_effect=OSError("private /Users/example/input")),
              contextlib.redirect_stdout(output), contextlib.redirect_stderr(output)):
            result = release.main(["--archive-root", str(self.archive), "prepare"])
        self.assertEqual(result, 1)
        summaries = list((self.archive / "failed").glob("*/summary.json"))
        self.assertEqual(len(summaries), 1)
        self.assertEqual(release.document(summaries[0])["reason"], "file-operation-failed")
        self.assertNotIn("/Users/example", summaries[0].read_text() + output.getvalue())
        self.assertFalse(self.git("tag", "--list"))

    def test_ci_rejects_wrong_commit_wrong_workflow_and_missing_check(self) -> None:
        valid = {"head_sha": self.commit, "head_branch": "main", "event": "push",
                 "path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success"}
        jobs = {"jobs": [{"name": "host-checks", "conclusion": "success"}]}
        for field, bad in (("head_sha", "0" * 40), ("event", "pull_request"),
                           ("path", ".github/workflows/other.yml"), ("conclusion", "failure")):
            with mock.patch.object(self.operation, "command", return_value=json.dumps({**valid, field: bad})):
                with self.assertRaises(release.ReleaseError):
                    self.operation.ci(self.commit, "17")
        with mock.patch.object(self.operation, "command", side_effect=[json.dumps(valid), '{"jobs":[]}']):
            with self.assertRaises(release.ReleaseError):
                self.operation.ci(self.commit, "17")
        with mock.patch.object(self.operation, "command", side_effect=[json.dumps(valid), json.dumps(jobs)]):
            self.assertEqual(self.operation.ci(self.commit, "17")["commit"], self.commit)

    def test_build_manifest_records_toolchain_lock_and_final_archives(self) -> None:
        self.prepared()
        (self.root / "build").mkdir()
        (self.root / "build/CMakeCache.txt").write_text(
            "CMAKE_BUILD_TYPE:STRING=Debug\nCMAKE_OSX_DEPLOYMENT_TARGET:STRING=26.0\n"
            "CMAKE_C_FLAGS:STRING=\nCMAKE_OSX_ARCHITECTURES:STRING=arm64\n"
        )
        (self.root / "generated-inputs.json").write_text('{"inputs": []}')
        (self.root / "docs/spec").mkdir(parents=True)
        shutil_source = ROOT / "docs/spec/build-manifest.schema.json"
        (self.root / "docs/spec/build-manifest.schema.json").write_bytes(shutil_source.read_bytes())
        with mock.patch.object(self.operation, "command", return_value="recorded tool version"):
            manifest = self.operation.build_manifest(self.commit, "0.1.0", self.path / "inputs")
        self.assertEqual(manifest["source"]["commit"], self.commit)
        self.assertEqual(manifest["toolchain"]["deploymentTarget"], "26.0")
        self.assertEqual(manifest["signingMode"], "ad-hoc-hardened-runtime")
        artifact = next(row for row in manifest["artifacts"] if row["path"] == "HP-LJ-1020.app.zip")
        self.assertEqual(artifact["sha256"], release.digest(self.path / "inputs/HP-LJ-1020.app.zip"))
        self.assertEqual(manifest["dependencyLock"]["sha256"], release.digest(self.path / "inputs/dependencies.lock.json"))

    def test_validation_identity_cannot_be_supplied_for_another_build(self) -> None:
        self.prepared()
        manifest = self.root / "validation.json"
        manifest.write_text(json.dumps({"sourceCommit": "0" * 40}))
        with self.assertRaisesRegex(release.ReleaseError, "identity mismatch"):
            self.operation.validate(self.operation.records(self.run_id)[0], manifest,
                                    self.root / "matrix.json", self.base)

    def test_tag_cannot_skip_gates(self) -> None:
        self.prepared()
        with mock.patch.object(self.operation, "candidate", return_value=(self.commit, "0.1.0")):
            with self.assertRaisesRegex(release.ReleaseError, "out of order"):
                self.operation.advance(self.run_id, "tagged", argparse.Namespace())
        self.assertFalse(self.git("tag", "--list"))

    def test_signed_tag_is_verified_before_creation_and_never_replaced(self) -> None:
        records = self.validated()
        self.operation.seal(self.run_id, records, self.notes())
        records = self.operation.records(self.run_id)
        key = self.base / "test-signing-key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
        allowed = self.base / "allowed-signers"
        allowed.write_text("host@example.invalid " + key.with_suffix(".pub").read_text())
        # A valid signature from an untrusted key cannot create even a temporary tag.
        rejected = self.base / "rejected-signers"
        rejected.write_text("")
        with self.assertRaises(subprocess.CalledProcessError):
            self.operation.tag(records, key, rejected)
        self.assertFalse(self.git("tag", "--list"))
        self.operation.tag(records, key, allowed)
        first = self.git("rev-parse", "refs/tags/v0.1.0")
        self.assertEqual(self.git("rev-parse", "v0.1.0^{commit}"), self.commit)
        self.operation.tag(records, key, allowed)
        self.assertEqual(self.git("rev-parse", "refs/tags/v0.1.0"), first)
        # A conflicting tag name is never deleted or moved.
        self.git("tag", "-d", "v0.1.0")
        self.git("tag", "v0.1.0")
        conflict = self.git("rev-parse", "refs/tags/v0.1.0")
        with self.assertRaises(subprocess.CalledProcessError):
            self.operation.tag(records, key, allowed)
        self.assertEqual(self.git("rev-parse", "refs/tags/v0.1.0"), conflict)

    def test_missing_or_private_notes_never_seal(self) -> None:
        records = self.validated()
        notes = self.notes()
        notes.write_text(notes.read_text() + "\npassword=do-not-retain\n")
        with self.assertRaises(ValueError):
            self.operation.seal(self.run_id, records, notes)
        self.assertFalse((self.archive / "releases/v0.1.0").exists())


if __name__ == "__main__":
    unittest.main()
