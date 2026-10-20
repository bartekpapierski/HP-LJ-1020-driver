#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Durable, fixed-path personal installation transactions (administrator helper)."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

if __package__:
    from scripts import personal_install as install
else:
    import personal_install as install

# No migration code comes from the payload. Add explicit, reviewed steps here.
SCHEMA = 1
STATE_CONTRACT = {"version": SCHEMA, "readableVersions": [0, 1], "startupAdmissionGate": 1}
DATA = ("config", "state", "spool", "firmware", "cache", "home")
PAYLOAD = "HP-LJ-1020.app"


def durable_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(value, output, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    sync_directory(path.parent)


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def inventory(root: Path) -> dict:
    """Include empty directories, modes, and ownership; reject links and special files."""
    result = {}
    for path in (root, *sorted(root.rglob("*"))):
        metadata = path.lstat()
        if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
            raise install.InstallError(f"unsafe snapshot entry: {path.name}")
        result[str(path.relative_to(root))] = [
            stat.S_IMODE(metadata.st_mode), metadata.st_uid, metadata.st_gid,
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
        ]
    return result


class MacRuntime:
    def __init__(self, host: install.CommandHost):
        self.host = host

    def ipp(self, operation: str, *, empty: bool = False, accepting: bool = False, uri: str = install.QUEUE_URI) -> None:
        # The provider's Disable-Printer closes direct IPP admission. CUPS alone
        # cannot protect against clients submitting directly to port 8631.
        body = ("{\nOPERATION " + operation + "\nGROUP operation-attributes-tag\n"
                "ATTR charset attributes-charset utf-8\n"
                "ATTR language attributes-natural-language en\n"
                "ATTR uri printer-uri $uri\nATTR name requesting-user-name root\n")
        if empty:
            body += ("ATTR keyword which-jobs not-completed\n"
                     "ATTR boolean my-jobs false\nATTR keyword requested-attributes job-id\n")
        body += "STATUS successful-ok\n" + ("EXPECT !job-id\n" if empty else "")
        if accepting:
            body += "EXPECT printer-is-accepting-jobs OF-TYPE boolean WITH-VALUE true\n"
        body += "}\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".test") as test:
            test.write(body)
            test.flush()
            self.host.run(["/usr/bin/ipptool", "-T", "5", "-t", uri, test.name])

    def no_jobs(self) -> None:
        result = self.host.run(["/usr/bin/lpstat", "-W", "not-completed", "-o", install.QUEUE])
        if result.stdout.strip():
            raise install.InstallError("update deferred: macOS queue has unfinished jobs")
        self.ipp("Get-Jobs", empty=True)

    def preflight(self) -> None:
        if not install.validate_existing_installation(self.host):
            raise install.InstallError("update requires an owned installation")
        if not install.validate_queue_ownership(self.host):
            raise install.InstallError("update requires the existing product queue")
        self.contract(Path(install.INSTALLED_APP))
        # Only an enabled, healthy installation is eligible for an update.
        # Existing queue options are never replaced by lpadmin -m everywhere.
        install.wait_ready(self.host)
        self.ipp("Get-Printer-Attributes", accepting=True)
        self.ipp("Get-Printer-Attributes", accepting=True,
                 uri=f"ipp://127.0.0.1:631/printers/{install.QUEUE}")
        self.no_jobs()

    def close_admission(self) -> None:
        durable_json(Path(install.STATE_ROOT) / "system.state.update-held", {"held": True})
        self.host.admin("/usr/sbin/cupsreject", install.QUEUE)
        self.ipp("Disable-Printer")
        self.no_jobs()  # Close the admission/check race before stopping anything.

    def stop(self) -> None:
        install.disable(self.host, preserve_queue_policy=True)

    def start(self) -> None:
        # Both replacement and retained payload must implement this contract.
        # Disable-Printer alone is lost when PAPPL restarts.
        durable_json(Path(install.STATE_ROOT) / "system.state.update-held", {"held": True})
        self.host.admin("/bin/launchctl", "enable", f"system/{install.SERVICE_LABEL}")
        self.host.admin("/bin/launchctl", "bootstrap", "system", install.SERVICE_PLIST)
        install.wait_ready(self.host, require_queue=False)

    def health(self) -> None:
        # Queue remains held until service health passes.
        install.wait_ready(self.host, require_queue=False)
        if not install.validate_queue_ownership(self.host):
            raise install.InstallError("existing queue disappeared during activation")

    def release(self) -> None:
        marker = Path(install.STATE_ROOT) / "system.state.update-held"
        marker.unlink(missing_ok=True)
        sync_directory(marker.parent)
        self.ipp("Enable-Printer")
        self.host.admin("/usr/sbin/cupsenable", install.QUEUE)
        self.host.admin("/usr/sbin/cupsaccept", install.QUEUE)
        install.wait_ready(self.host)

    def copy(self, source: Path, destination: Path) -> None:
        self.host.admin("/usr/bin/ditto", str(source), str(destination))

    def backup_queue(self, destination: Path) -> None:
        options = self.host.run(["/usr/bin/lpoptions", "-p", install.QUEUE]).stdout
        durable_json(destination / "queue.json", {
            "name": install.QUEUE, "uri": install.QUEUE_URI,
            "enabled": True, "accepting": True, "options": options,
        })
        ppd = Path("/etc/cups/ppd") / f"{install.QUEUE}.ppd"
        if ppd.exists():
            self.copy(ppd, destination / "queue.ppd")
            with (destination / "queue.ppd").open("rb") as stream:
                os.fsync(stream.fileno())

    def validate(self, app: Path) -> None:
        info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
        marker = (app / "Contents/Resources/product-id").read_text().strip()
        if info.get("CFBundleIdentifier") != install.RECEIPT or marker != install.RECEIPT:
            raise install.InstallError("replacement identity mismatch")
        self.contract(app)
        self.host.admin("/usr/bin/codesign", "--verify", "--strict", "--deep", str(app))
        self.host.admin("/usr/bin/plutil", "-lint", str(app / "Contents/Library/LaunchDaemons" / f"{install.SERVICE_LABEL}.plist"))

    @staticmethod
    def contract(app: Path) -> None:
        path = app / "Contents/Resources/state-schema.json"
        if not path.is_file() or json.loads(path.read_text()) != STATE_CONTRACT:
            raise install.InstallError("payload lacks compatible state and startup admission contract; establish a clean installation first")


class Transaction:
    """All mutations run under one administrator-held flock.

    An uncommitted journal rolls back on the next invocation. Sources are never
    consumed during restore, so interrupted restoration can be repeated.
    launchd stays persistently disabled across every payload/state replacement.
    """

    def __init__(self, root: Path, plist: Path, runtime: MacRuntime, checkpoint=None):
        self.root = root
        self.plist = plist
        self.runtime = runtime
        self.store = root / "transactions"
        self.journal = self.store / "pending.json"
        self.checkpoint = checkpoint or (lambda phase: None)

    def phase(self, record: dict, phase: str) -> None:
        record["phase"] = phase
        durable_json(self.journal, record)
        self.checkpoint(phase)

    def copy(self, source: Path, destination: Path) -> None:
        self.runtime.copy(source, destination)
        if inventory(source) != inventory(destination):
            raise install.InstallError("copied payload/state differs from its source")
        # ditto preserves source ownership/mode. Sync bytes before journaling.
        entries = (destination, *destination.rglob("*"))
        for path in entries:
            if path.is_file():
                with path.open("rb") as stream:
                    os.fsync(stream.fileno())
        for path in sorted((entry for entry in entries if entry.is_dir()),
                           key=lambda entry: len(entry.parts), reverse=True):
            sync_directory(path)
        sync_directory(destination.parent)

    def snapshot(self, destination: Path) -> None:
        destination.mkdir(mode=0o700)
        for name in (PAYLOAD, *DATA):
            source = self.root / name
            if source.exists():
                inventory(source)
                self.copy(source, destination / name)
                self.checkpoint("snapshot-" + name)
        self.copy(self.plist, destination / "service.plist")
        self.runtime.backup_queue(destination)
        durable_json(destination / "inventory.json", inventory(destination))
        sync_directory(destination)

    def verify(self, snapshot: Path) -> None:
        expected = json.loads((snapshot / "inventory.json").read_text())
        actual = inventory(snapshot)
        actual.pop("inventory.json", None)
        if expected != actual:
            raise install.InstallError("retained payload/state inventory mismatch; service must remain disabled")

    def replace(self, source: Path, destination: Path) -> None:
        # A fixed sibling temporary is safe to discard on replay under the lock.
        temporary = destination.with_name(destination.name + ".replacement")
        parked = destination.with_name(destination.name + ".displaced")
        self.remove(temporary)
        self.copy(source, temporary)
        self.remove(parked)
        if destination.exists():
            destination.rename(parked)
        self.checkpoint("replace-" + destination.name + "-parked")
        temporary.rename(destination)
        sync_directory(destination.parent)
        self.checkpoint("replace-" + destination.name + "-installed")
        self.remove(parked)

    @staticmethod
    def remove(path: Path) -> None:
        if path.is_symlink():
            raise install.InstallError("refusing symlink at transaction path")
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    def migrate(self) -> None:
        path = self.root / "config/state-version.json"
        version = json.loads(path.read_text())["version"] if path.exists() else 0
        if type(version) is not int or not 0 <= version <= SCHEMA:
            raise install.InstallError("incompatible persistent state version")
        if version == 0:
            # v0 -> v1 is metadata-only; PAPPL state and firmware stay opaque.
            self.checkpoint("migration-0-1-before")
            durable_json(path, {"version": 1})
            config = path.parent.stat()
            os.chown(path, config.st_uid, config.st_gid)
            path.chmod(0o600)
            self.checkpoint("migration-0-1-after")
        self.checkpoint("migrated")

    def restore(self, snapshot: Path) -> None:
        self.verify(snapshot)
        for name in (PAYLOAD, *DATA):
            destination = self.root / name
            if (snapshot / name).exists():
                self.replace(snapshot / name, destination)
            else:
                self.remove(destination)
            self.checkpoint("restore-" + name)
        self.replace(snapshot / "service.plist", self.plist)
        self.checkpoint("restore-plist")

    def finish(self, record: dict, outcome: str) -> None:
        durable_json(self.store / "last-result.json", {**record, "outcome": outcome})
        self.journal.unlink()
        sync_directory(self.store)

    def recover(self) -> bool:
        if not self.journal.exists():
            return False
        record = json.loads(self.journal.read_text())
        run = self.run_path(record["run"])
        if record["phase"] == "committed":
            # Admission may already be open: never revert a committed runtime
            # (or interrupt jobs accepted since commit) on finalization retry.
            self.runtime.health()
            self.runtime.release()
            self.finish(record, record.get("recoveryOutcome", record["operation"] + "-complete"))
            return True
        # No service/payload changes precede the admission journal. Preparation
        # is disposable and the existing service need not be touched.
        if record["phase"] == "preparing":
            self.finish(record, "prepare-failed")
            return True
        if record["phase"] == "admission":
            # stop/snapshot cannot have started yet; undo only admission holds.
            self.runtime.release()
            self.finish(record, "deferred")
            return True
        self.runtime.stop()
        if record["phase"] == "stopping":
            # Stop was interrupted before any live files were changed.
            self.runtime.start()
            self.runtime.health()
            record["recoveryOutcome"] = "unchanged"
            self.phase(record, "committed")
            self.runtime.release()
            self.finish(record, "unchanged")
            return True
        self.phase(record, "restoring")
        self.restore(run / "before")
        self.runtime.start()
        self.runtime.health()
        self.checkpoint("restored-health")
        record["recoveryOutcome"] = "rolled-back"
        self.phase(record, "committed")
        self.runtime.release()
        self.checkpoint("recovery-released")
        self.finish(record, "rolled-back")
        return True

    def run_path(self, name: str) -> Path:
        if len(name) != 32 or any(c not in "0123456789abcdef" for c in name):
            raise install.InstallError("invalid transaction identity")
        return self.store / name

    def execute(self, source: Path | None, identity: dict) -> None:
        self.store.mkdir(exist_ok=True, mode=0o700)
        if (self.store.is_symlink() or self.store.stat().st_uid != os.getuid()
                or stat.S_IMODE(self.store.stat().st_mode) != 0o700):
            raise install.InstallError("unsafe transaction store")
        with (self.store / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.journal.exists():
                try:
                    self.recover()
                except Exception:
                    pending = json.loads(self.journal.read_text()) if self.journal.exists() else {}
                    if pending and pending["phase"] != "committed":
                        self.runtime.stop()
                    raise
                return  # Recovery is a complete operation; never start a new update implicitly.
            self.runtime.preflight()
            rollback = None
            if source is None:
                pointer = json.loads((self.store / "previous.json").read_text())
                rollback = self.run_path(pointer["run"]) / "before"
                self.verify(rollback)
            run_id = uuid.uuid4().hex
            run = self.run_path(run_id)
            run.mkdir(mode=0o700)
            record = {"run": run_id, "identity": identity, "operation": "rollback" if source is None else "update"}
            try:
                self.phase(record, "preparing")
                if source is not None:
                    inventory(source)
                    self.copy(source, run / PAYLOAD)
                    inventory(run / PAYLOAD)
                    # Root-owned private copy closes user staging races.
                    for path in (run / PAYLOAD, *(run / PAYLOAD).rglob("*")):
                        os.chown(path, os.getuid(), os.getgid())
                        path.chmod(stat.S_IMODE(path.stat().st_mode) & ~0o022)
                    self.runtime.validate(run / PAYLOAD)
                self.phase(record, "admission")
                self.runtime.close_admission()
                self.phase(record, "stopping")
                self.runtime.stop()
                self.snapshot(run / "before")
                self.verify(run / "before")
                self.phase(record, "backed-up")
                if rollback is None:
                    self.replace(run / PAYLOAD, self.root / PAYLOAD)
                    self.checkpoint("payload-replaced")
                    self.replace(self.root / PAYLOAD / "Contents/Library/LaunchDaemons" / f"{install.SERVICE_LABEL}.plist", self.plist)
                    self.phase(record, "migrating")
                    self.migrate()
                else:
                    self.restore(rollback)
                self.phase(record, "starting")
                self.runtime.start()
                self.runtime.health()
                self.phase(record, "healthy")
                durable_json(self.store / "previous.json", {"run": run_id})
                self.phase(record, "committed")
                self.runtime.release()
                self.checkpoint("released")
                self.finish(record, "rolled-back" if rollback else "updated")
            except Exception:
                record["failedPhase"] = record["phase"]
                durable_json(self.journal, record)
                try:
                    self.recover()
                except Exception as error:
                    pending = json.loads(self.journal.read_text()) if self.journal.exists() else {}
                    committed = not pending or pending["phase"] == "committed"
                    if not committed:
                        self.runtime.stop()
                    state = "finalization incomplete" if committed else "rollback incomplete; service disabled"
                    raise install.InstallError(f"{state}; rerun rollback: {error}") from error
                raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("update", "rollback"))
    parser.add_argument("--staged", type=Path)
    parser.add_argument("--tag")
    parser.add_argument("--commit")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("administrator helper must run through the audited lifecycle command")
    if args.operation == "update" and (args.staged is None or not args.tag or not args.commit):
        parser.error("update requires staged payload and source identity")
    def bounded_run(*arguments, **kwargs):
        return subprocess.run(*arguments, **kwargs, timeout=15)

    host = install.CommandHost(bounded_run, sys.stdout)
    transaction = Transaction(Path(install.INSTALL_ROOT), Path(install.SERVICE_PLIST), MacRuntime(host))
    try:
        if not install.validate_product_marker(host, f"{install.INSTALL_ROOT}/.product-id"):
            raise install.InstallError("transaction requires the owned product root")
        install.validate_path_owner(host, install.Artifact(install.INSTALL_ROOT, "root", "wheel", "755"))
        transaction.execute(args.staged if args.operation == "update" else None,
                            {"tag": args.tag, "commit": args.commit})
        result = json.loads((transaction.store / "last-result.json").read_text())
        print(f"transaction-outcome={result['outcome']}")
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired, install.InstallError) as error:
        print(f"transaction failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
