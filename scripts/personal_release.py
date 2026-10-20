#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Local, immutable personal-release records. Never publishes or uploads artifacts."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True

if __package__:
    from scripts import check_artifacts, json_schema, personal_install, update_capability_matrix, validation_gate
    from scripts.product_version import read_version
else:
    import check_artifacts
    import json_schema
    import personal_install
    import update_capability_matrix
    import validation_gate
    from product_version import read_version

ROOT = Path(__file__).resolve().parents[1]
STAGES = ("prepared", "hosted-ci-passed", "locally-validated", "sealed", "tagged", "installed")
SHA = re.compile(r"[a-f0-9]{40}")
# Reference member identity, also recorded in src/firmware.c and the acquisition research.
FIRMWARE_DIGESTS = {"9a6d03c858d9cf64ba86fdbe6cf0beec1297d2e45e606162b19f3857efae4ff4"}
PRIVATE = re.compile(r"(?:^|/)(?:\.env(?:\.[^/]*)?|\.ssh|credentials|secrets?|spool|diagnostics)(?:/|$)|\.(?:pem|key|p12|pfx)$", re.I)
SECRET = re.compile(rb"-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}")
NOTES_FIELDS = ("Changes", "Support claims", "Known limitations", "Firmware requirements", "Lifecycle instructions", "Validation results", "Dependency changes", "Checksums")


class ReleaseError(ValueError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    return check_artifacts.file_sha256(path)


def document(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2, sort_keys=True)
        output.write("\n")
    path.chmod(0o444)


def readonly(path: Path) -> None:
    for item in sorted(path.rglob("*"), reverse=True):
        if item.is_symlink():
            raise ReleaseError("symlinks are prohibited in release records")
        item.chmod(0o555 if item.is_dir() else 0o444)
    path.chmod(0o555)


def inventory(path: Path) -> dict[str, str]:
    result = {}
    for item in path.rglob("*"):
        if item.is_symlink() or not (item.is_file() or item.is_dir()):
            raise ReleaseError("unsafe release entry")
        if item.is_file():
            result[item.relative_to(path).as_posix()] = digest(item)
    return dict(sorted(result.items()))


def safe_file(root: Path, relative: str) -> Path:
    path = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts or path.is_symlink():
        raise ReleaseError("unsafe record path")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ReleaseError("record escapes its root")
    return path


def private_check(path: Path) -> None:
    if PRIVATE.search(path.name) or SECRET.search(path.read_bytes()):
        raise ReleaseError("private content rejected")


class Release:
    def __init__(self, root: Path, archive: Path):
        self.root = root.resolve()
        self.archive = archive.resolve()
        if self.archive.is_relative_to(self.root):
            raise ReleaseError("release archives must be outside the source checkout")

    def command(self, *args: str, input: str | None = None) -> str:
        return subprocess.run(args, cwd=self.root, check=True, capture_output=True,
                              text=True, input=input).stdout.strip()

    def git(self, *args: str, input: str | None = None) -> str:
        return self.command("git", *args, input=input)

    def candidate(self) -> tuple[str, str]:
        if self.git("status", "--porcelain", "--untracked-files=all"):
            raise ReleaseError("candidate worktree must be clean")
        if os.environ.get("HPLJ1020_SOURCE_OVERRIDE"):
            raise ReleaseError("source overrides are prohibited")
        commit = self.git("rev-parse", "HEAD")
        if not SHA.fullmatch(commit):
            raise ReleaseError("invalid source commit")
        self.command(sys.executable, "scripts/build", "--personal-release", "--verify-lock")
        return commit, read_version(self.root)

    def merged(self, commit: str) -> None:
        result = json.loads(self.command("gh", "api", f"repos/{{owner}}/{{repo}}/compare/{commit}...main"))
        if result["status"] not in {"ahead", "identical"}:
            raise ReleaseError("candidate is not merged into main")

    def run_path(self, run_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ReleaseError("invalid run ID")
        return self.archive / "runs" / run_id

    def records(self, run_id: str) -> list[dict]:
        path = self.run_path(run_id)
        records = []
        previous = None
        for stage in STAGES:
            file = path / f"{stage}.json"
            if not file.exists():
                break
            if file.is_symlink() or file.stat().st_mode & 0o222:
                raise ReleaseError("stage record is writable or unsafe")
            record = document(file)
            if (record["stage"] != stage or record["runId"] != run_id or
                    record["previousSha256"] != previous):
                raise ReleaseError("broken stage chain")
            for name, checksum in record["outputs"].items():
                output = safe_file(self.archive, name)
                if not output.is_file() or output.stat().st_mode & 0o222 or digest(output) != checksum:
                    raise ReleaseError("stage output checksum or immutability mismatch")
            if records and any(record[key] != records[0][key] for key in ("commit", "version")):
                raise ReleaseError("stage identity mismatch")
            if stage == "prepared":
                inputs = path / "inputs"
                expected = {"runs/" + run_id + "/inputs/" + name: value
                            for name, value in inventory(inputs).items()}
                if expected != record["outputs"]:
                    raise ReleaseError("prepared inventory mismatch")
            if stage == "tagged":
                if self.git("rev-parse", f"refs/tags/{record['data']['tag']}") != record["data"]["tagObject"]:
                    raise ReleaseError("immutable tag changed")
            records.append(record)
            previous = digest(file)
        if not records:
            raise ReleaseError("run is not prepared")
        if (path / "failed.json").exists():
            raise ReleaseError("failed runs require a new run ID")
        return records

    def record(self, run_id: str, stage: str, outputs: list[Path], **data: object) -> dict:
        path = self.run_path(run_id)
        index = STAGES.index(stage)
        if index:
            prior = self.records(run_id)
            if len(prior) != index:
                raise ReleaseError("stage out of order")
            base = prior[0]
            previous = digest(path / f"{STAGES[index - 1]}.json")
        else:
            base = data
            previous = None
        record = {"stage": stage, "runId": run_id, "commit": base["commit"],
                  "version": base["version"], "recordedAt": now(), "previousSha256": previous,
                  "outputs": {p.relative_to(self.archive).as_posix(): digest(p) for p in outputs},
                  "data": data}
        write_json(path / f"{stage}.json", record)
        return record

    def failure(self, run_id: str, stage: str, reason: str = "release-stage-rejected") -> str:
        # Never retain exception text, command output, host paths, or private evidence.
        failure_id = uuid.uuid4().hex
        directory = self.archive / "failed" / failure_id
        directory.mkdir(parents=True)
        try:
            commit = self.git("rev-parse", "HEAD")
        except subprocess.CalledProcessError:
            commit = None
        summary = {"runId": failure_id, "attemptRunId": run_id, "sourceCommit": commit,
                   "stage": stage, "result": "failed", "reason": reason,
                   "redacted": True, "recordedAt": now()}
        write_json(directory / "summary.json", summary)
        write_json(directory / "checksums.json", {"summary.json": digest(directory / "summary.json")})
        readonly(directory)
        path = self.run_path(run_id)
        if path.exists() and not (path / "failed.json").exists():
            write_json(path / "failed.json", {"failureId": failure_id})
        return failure_id

    def source_bundle(self, output: Path, commit: str) -> None:
        # Check every reachable historical blob: HEAD-only inspection misses removed secrets.
        for line in self.git("rev-list", "--objects", commit).splitlines():
            oid, _, name = line.partition(" ")
            if name and (PRIVATE.search(name) or check_artifacts.name_is_forbidden(name)):
                raise ReleaseError("prohibited path in source history")
            if self.git("cat-file", "-t", oid) == "blob":
                blob = subprocess.run(["git", "cat-file", "blob", oid], cwd=self.root,
                                      capture_output=True, check=True).stdout
                if SECRET.search(blob) or hashlib.sha256(blob).hexdigest() in FIRMWARE_DIGESTS:
                    raise ReleaseError("prohibited content in source history")
        self.git("bundle", "create", str(output), "HEAD")
        self.git("bundle", "verify", str(output))

    def prepare(self, run_id: str) -> None:
        commit, version = self.candidate()
        self.merged(commit)
        path = self.run_path(run_id)
        if path.exists():
            records = self.records(run_id)
            if (records[0]["commit"], records[0]["version"]) != (commit, version):
                raise ReleaseError("candidate identity changed")
            if len(records) >= 3:
                self.verify_pointer(records[2]["data"]["validation"])
            if len(records) >= 4:
                self.verify_seal(safe_file(self.archive, records[3]["data"]["bundle"]))
            return
        path.mkdir(parents=True)
        inputs = path / "inputs"
        inputs.mkdir()
        self.source_bundle(inputs / "source.bundle", commit)
        personal_install.stage_and_sign(personal_install.CommandHost(subprocess.run), personal_release=True)
        app = personal_install.STAGED_APP
        self.check_payload(app, version)
        self.command("/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                     str(app), str(inputs / "HP-LJ-1020.app.zip"))
        shutil.copyfile(self.root / "dependencies.lock.json", inputs / "dependencies.lock.json")
        shutil.copyfile(self.root / "THIRD_PARTY_NOTICES.md", inputs / "THIRD_PARTY_NOTICES.md")
        self.command(sys.executable, "scripts/generate_sbom.py", "--output", str(inputs / "sbom.spdx.json"))
        manifest = self.build_manifest(commit, version, inputs)
        write_json(inputs / "build-manifest.json", manifest)
        self.check_payload(app, version)
        if self.candidate() != (commit, version):
            raise ReleaseError("source changed during preparation")
        readonly(inputs)
        self.record(run_id, "prepared", list(inputs.iterdir()), commit=commit, version=version)

    def check_payload(self, app: Path, version: str) -> None:
        expected = inventory(personal_install.APP_TEMPLATE)
        for name in inventory(app):
            if (name not in expected and name != "Contents/MacOS/hplj1020" and
                    not re.fullmatch(r"Contents/Frameworks/[^/]+\.dylib", name) and
                    name != "Contents/_CodeSignature/CodeResources"):
                raise ReleaseError("unexpected app payload entry")
        check_artifacts.check_artifacts(app, FIRMWARE_DIGESTS)
        for file in app.rglob("*"):
            if file.is_file():
                private_check(file)
        info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
        if info["CFBundleShortVersionString"] != version or info["CFBundleVersion"] != version:
            raise ReleaseError("app version mismatch")
        self.command("/usr/bin/codesign", "--verify", "--deep", "--strict", str(app))
        signature = subprocess.run(["/usr/bin/codesign", "-dv", "--verbose=4", str(app)],
                                   capture_output=True, text=True, check=True).stderr
        if "Signature=adhoc" not in signature or "runtime" not in signature:
            raise ReleaseError("release payload requires ad-hoc hardened-runtime signing")

    def build_manifest(self, commit: str, version: str, inputs: Path) -> dict:
        cache = (self.root / "build/CMakeCache.txt").read_text()
        configuration = {}
        for line in cache.splitlines():
            if re.match(r"(?:CMAKE_(?:BUILD_TYPE|(?:C|OBJC)_FLAGS[^:]*|(?:EXE|STATIC)_LINKER_FLAGS[^:]*|OSX_DEPLOYMENT_TARGET|OSX_ARCHITECTURES)):", line):
                key, value = line.split("=", 1)
                configuration[key.split(":")[0]] = value
        sdk_version = self.command("xcrun", "--sdk", "macosx", "--show-sdk-version")
        deployment = configuration.get("CMAKE_OSX_DEPLOYMENT_TARGET")
        if not deployment:
            raise ReleaseError("release build needs an explicit deployment target")
        schema = document(self.root / "docs/spec/build-manifest.schema.json")
        manifest = {"$schema": schema["$id"], "schemaVersion": "1.0.0", "productVersion": version,
                    "source": {"commit": commit, "cleanTree": True, "specificationCommit": commit},
                    "toolchain": {"xcodeBuild": self.command("xcodebuild", "-version"),
                                  "compiler": self.command("xcrun", "clang", "--version"),
                                  "sdkBuild": self.command("xcrun", "--sdk", "macosx", "--show-sdk-build-version"),
                                  "deploymentTarget": deployment, "architectures": ["arm64"]},
                    "configuration": {**configuration, "sdkVersion": sdk_version},
                    "dependencyLock": {"path": "dependencies.lock.json", "sha256": digest(inputs / "dependencies.lock.json")},
                    "generatedInputs": document(self.root / "generated-inputs.json")["inputs"],
                    "signingMode": "ad-hoc-hardened-runtime", "builtAt": now(), "ciRun": None,
                    "artifacts": [{"path": name, "sha256": checksum} for name, checksum in inventory(inputs).items()]}
        json_schema.validate(manifest, schema)
        validation_gate._validate_redacted_strings(manifest, "build manifest")
        return manifest

    def ci(self, commit: str, ci_run: str) -> dict:
        if not re.fullmatch(r"[0-9]+", ci_run):
            raise ReleaseError("invalid hosted CI run ID")
        base = f"repos/{{owner}}/{{repo}}/actions/runs/{ci_run}"
        run = json.loads(self.command("gh", "api", base))
        if (run["head_sha"] != commit or run["head_branch"] != "main" or
                run["event"] != "push" or run["path"] != ".github/workflows/ci.yml" or
                run["status"] != "completed" or run["conclusion"] != "success"):
            raise ReleaseError("hosted CI does not pass for the exact merged commit")
        jobs = json.loads(self.command("gh", "api", base + "/jobs?per_page=100"))
        checks = [job for job in jobs["jobs"] if job["name"] == "host-checks"]
        if len(checks) != 1 or checks[0]["conclusion"] != "success":
            raise ReleaseError("required hosted check did not pass")
        return {"provider": "github-actions", "runId": ci_run, "commit": commit}

    def validate(self, record: dict, manifest_path: Path, matrix: Path, evidence: Path) -> dict:
        manifest_path = manifest_path.resolve()
        matrix = matrix.resolve()
        for path in (manifest_path, matrix):
            if not path.is_relative_to(self.root):
                raise ReleaseError("validation pointers must be repository relative")
        manifest = document(manifest_path)
        inputs = self.run_path(record["runId"]) / "inputs"
        if (manifest["sourceCommit"] != record["commit"] or
                manifest["specificationCommit"] != record["commit"] or
                manifest["dependencyLockSha256"] != digest(inputs / "dependencies.lock.json") or
                manifest["buildManifestSha256"] != digest(inputs / "build-manifest.json") or
                manifest["environment"]["kind"] != "reference-mac"):
            raise ReleaseError("validation identity mismatch")
        expected_scopes = update_capability_matrix.build_matrix()["scopeIdentities"]
        if document(matrix)["scopeIdentities"] != expected_scopes:
            raise ReleaseError("validation source scopes changed")
        args = ["--matrix", str(matrix), "--manifest", str(manifest_path), "--milestone", "PERSONAL",
                "--evidence-root", str(evidence), "--spec", str(self.root / "docs/IMPLEMENTATION-SPEC.md")]
        if validation_gate.main(args) != 0:
            raise ReleaseError("personal validation contract rejected")
        return {"manifest": {"path": manifest_path.relative_to(self.root).as_posix(), "sha256": digest(manifest_path)},
                "matrix": {"path": matrix.relative_to(self.root).as_posix(), "sha256": digest(matrix)}}

    def verify_pointer(self, pointer: dict) -> None:
        for item in pointer.values():
            if digest(safe_file(self.root, item["path"])) != item["sha256"]:
                raise ReleaseError("validation pointer changed")

    def seal(self, run_id: str, records: list[dict], notes: Path) -> None:
        pointer = records[2]["data"]["validation"]
        self.verify_pointer(pointer)
        private_check(notes)
        text = notes.read_text(encoding="utf-8")
        validation_gate._validate_redacted_strings(text, "release notes")
        if any(f"## {field}" not in text for field in NOTES_FIELDS):
            raise ReleaseError("release notes are missing required sections")
        destination = self.archive / "releases" / f"v{records[0]['version']}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        # A completed directory without its stage record can be recovered only by exact inventory.
        with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
            stage = Path(temporary) / "bundle"
            shutil.copytree(self.run_path(run_id) / "inputs", stage)
            for file in stage.iterdir():
                file.chmod(0o644)
            stage.chmod(0o755)
            manifest_path = stage / "build-manifest.json"
            manifest = document(manifest_path)
            manifest["ciRun"] = records[1]["data"]["ci"]
            # The original validated build identity is retained separately, without rewriting evidence.
            manifest_path.rename(stage / "validated-build-manifest.json")
            write_json(manifest_path, manifest)
            write_json(stage / "validation-pointer.json", pointer)
            (stage / "RELEASE-NOTES.md").write_text(text, encoding="utf-8")
            check_artifacts.check_artifacts(stage, FIRMWARE_DIGESTS)
            sums = "".join(f"{checksum}  {name}\n" for name, checksum in inventory(stage).items())
            (stage / "SHA256SUMS").write_text(sums, encoding="utf-8")
            if destination.exists():
                if inventory(destination) != inventory(stage):
                    raise ReleaseError("conflicting sealed version")
                readonly(destination)
                self.verify_seal(destination)
            else:
                stage.rename(destination)
                readonly(destination)
        self.record(run_id, "sealed", list(destination.iterdir()), bundle=destination.relative_to(self.archive).as_posix())

    def verify_seal(self, bundle: Path) -> None:
        actual = inventory(bundle)
        if any(item.stat().st_mode & 0o222 for item in [bundle, *bundle.rglob("*")]):
            raise ReleaseError("sealed directory is writable")
        expected = {}
        for line in (bundle / "SHA256SUMS").read_text().splitlines():
            checksum, name = line.split("  ", 1)
            if name in expected:
                raise ReleaseError("duplicate seal entry")
            expected[name] = checksum
        actual.pop("SHA256SUMS")
        if actual != expected:
            raise ReleaseError("sealed inventory mismatch")

    def tag(self, records: list[dict], key: Path, allowed_signers: Path) -> None:
        record = records[0]
        tag = f"v{record['version']}"
        bundle = safe_file(self.archive, records[3]["data"]["bundle"])
        self.verify_seal(bundle)
        message = f"Personal release {tag}\nSHA256SUMS {digest(bundle / 'SHA256SUMS')}\n"
        config = ("-c", "gpg.format=ssh", "-c", f"gpg.ssh.allowedSignersFile={allowed_signers.resolve()}")
        existing = self.git("tag", "--list", tag)
        if existing:
            self.git(*config, "verify-tag", tag)
            if (self.git("rev-parse", f"{tag}^{{commit}}") != record["commit"] or
                    self.git("cat-file", "tag", tag).split("\n\n", 1)[1].split("-----BEGIN SSH SIGNATURE-----")[0] != message):
                raise ReleaseError("conflicting immutable tag")
            return
        # Sign and verify the unattached object before the only ref mutation (create-only CAS).
        content = (f"object {record['commit']}\ntype commit\ntag {tag}\n"
                   f"tagger {self.git('var', 'GIT_COMMITTER_IDENT')}\n\n{message}")
        with tempfile.TemporaryDirectory() as temporary:
            unsigned = Path(temporary) / "tag"
            unsigned.write_text(content, encoding="utf-8")
            self.command("ssh-keygen", "-Y", "sign", "-n", "git", "-f", str(key.resolve()), str(unsigned))
            oid = self.git("mktag", input=content + unsigned.with_suffix(".sig").read_text())
            self.git(*config, "verify-tag", oid)
            self.git("update-ref", f"refs/tags/{tag}", oid, "0" * 40)

    def advance(self, run_id: str, stage: str, args: argparse.Namespace) -> None:
        records = self.records(run_id)
        candidate = self.candidate()
        if candidate != (records[0]["commit"], records[0]["version"]):
            raise ReleaseError("candidate identity changed")
        index = STAGES.index(stage)
        if len(records) > index:
            if len(records) >= 3:
                self.verify_pointer(records[2]["data"]["validation"])
            if len(records) >= 4:
                self.verify_seal(safe_file(self.archive, records[3]["data"]["bundle"]))
            if stage == "hosted-ci-passed":
                self.ci(candidate[0], records[1]["data"]["ci"]["runId"])
            elif stage == "locally-validated":
                self.validate(records[0], args.manifest, args.matrix, args.evidence_root)
            elif stage == "tagged":
                self.tag(records, args.signing_key, args.allowed_signers)
            elif stage == "installed":
                self.verify_installed(records)
            return
        if len(records) != index:
            raise ReleaseError("stage out of order")
        if stage == "hosted-ci-passed":
            self.record(run_id, stage, [], ci=self.ci(candidate[0], args.ci_run))
        elif stage == "locally-validated":
            pointer = self.validate(records[0], args.manifest, args.matrix, args.evidence_root)
            self.record(run_id, stage, [], validation=pointer)
        elif stage == "sealed":
            self.seal(run_id, records, args.notes)
        elif stage == "tagged":
            self.ci(candidate[0], records[1]["data"]["ci"]["runId"])
            self.verify_pointer(records[2]["data"]["validation"])
            pointer = self.validate(records[0], args.manifest, args.matrix, args.evidence_root)
            if pointer != records[2]["data"]["validation"]:
                raise ReleaseError("tag validation differs from sealed validation")
            self.tag(records, args.signing_key, args.allowed_signers)
            self.record(run_id, stage, [], tag=f"v{candidate[1]}",
                        tagObject=self.git("rev-parse", f"refs/tags/v{candidate[1]}"))
        elif stage == "installed":
            checksum = self.verify_installed(records)
            self.record(run_id, stage, [], payloadSha256=checksum)

    def verify_installed(self, records: list[dict]) -> str:
        # Observe installation only; transactional update/rollback belongs to the lifecycle command.
        bundle = safe_file(self.archive, records[3]["data"]["bundle"])
        self.verify_seal(bundle)
        with zipfile.ZipFile(bundle / "HP-LJ-1020.app.zip") as archive:
            expected = {name.split("/", 1)[1]: hashlib.sha256(archive.read(name)).hexdigest()
                        for name in archive.namelist() if name.startswith("HP-LJ-1020.app/") and not name.endswith("/")}
        if not expected or inventory(Path(personal_install.INSTALLED_APP)) != expected:
            raise ReleaseError("installed payload differs from sealed payload")
        host = personal_install.CommandHost(subprocess.run)
        if not personal_install.validate_existing_installation(host):
            raise ReleaseError("installation ownership verification failed")
        personal_install.wait_ready(host, require_queue=True)
        return digest(bundle / "HP-LJ-1020.app.zip")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, required=True)
    sub = parser.add_subparsers(dest="stage", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--run-id", help="resume an already prepared run after verification")
    for stage in STAGES[1:]:
        command = sub.add_parser(stage)
        command.add_argument("--run-id", required=True)
        if stage == "hosted-ci-passed":
            command.add_argument("--ci-run", required=True)
        if stage in {"locally-validated", "tagged"}:
            command.add_argument("--manifest", type=Path, required=True)
            command.add_argument("--matrix", type=Path, required=True)
            command.add_argument("--evidence-root", type=Path, required=True)
        if stage == "sealed":
            command.add_argument("--notes", type=Path, required=True)
        if stage == "tagged":
            command.add_argument("--signing-key", type=Path, required=True)
            command.add_argument("--allowed-signers", type=Path, required=True)
    args = parser.parse_args(argv)
    run_id = getattr(args, "run_id", None) or uuid.uuid4().hex
    try:
        release = Release(ROOT, args.archive_root)
        release.run_path(run_id)
    except ValueError as error:
        parser.error(str(error))
    stage = "prepared" if args.stage == "prepare" else args.stage
    release.archive.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Serialize all archive and tag changes; a second invocation waits and re-verifies.
    with (release.archive / ".operation.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if stage == "prepared":
                print(f"candidate run: {run_id}", flush=True)
                release.prepare(run_id)
            else:
                release.advance(run_id, stage, args)
        except (OSError, ValueError, KeyError, TypeError, personal_install.InstallError,
                subprocess.CalledProcessError) as error:
            reason = ("policy-check-failed" if isinstance(error, ReleaseError) else
                      "host-command-failed" if isinstance(error, (subprocess.CalledProcessError, personal_install.InstallError)) else
                      "file-operation-failed" if isinstance(error, OSError) else "invalid-record")
            failure = release.failure(run_id, stage, reason)
            print(f"personal release rejected; immutable redacted failure {failure}", file=sys.stderr)
            return 1
    print(f"{stage}: {run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
