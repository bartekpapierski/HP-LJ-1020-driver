#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Audited personal-use installation and service lifecycle command."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts" / "build"
BUILT_PROVIDER = ROOT / "build" / "hplj1020"
STAGED_APP = ROOT / "build" / "personal-install" / "HP-LJ-1020.app"
APP_TEMPLATE = ROOT / "packaging" / "HP-LJ-1020.app"
PLIST_SOURCE = APP_TEMPLATE / "Contents" / "Library" / "LaunchDaemons" / "com.bartekpapierski.hplj1020.service.plist"
AUDIT_LOG = ROOT / "build" / "personal-install" / "audit.jsonl"

SERVICE_USER = "_hplj1020"
SERVICE_REAL_NAME = "HP LaserJet 1020 Service"
SERVICE_LABEL = "com.bartekpapierski.hplj1020.service"
QUEUE = "HP_LaserJet_1020"
QUEUE_URI = "ipp://127.0.0.1:8631/ipp/print"
INSTALL_ROOT = "/Library/Application Support/HP-LJ-1020"
INSTALLED_APP = f"{INSTALL_ROOT}/HP-LJ-1020.app"
STATE_ROOT = f"{INSTALL_ROOT}/state"
LOG_ROOT = "/Library/Logs/HP-LJ-1020"
SERVICE_PLIST = f"/Library/LaunchDaemons/{SERVICE_LABEL}.plist"
RECEIPT = "com.bartekpapierski.hplj1020"


@dataclass(frozen=True)
class Artifact:
    path: str
    owner: str
    group: str
    mode: str

    @property
    def metadata(self) -> str:
        return f"{self.owner}:{self.group}:{self.mode}"


PRIVATE_DIRECTORIES = tuple(
    Artifact(path, SERVICE_USER, SERVICE_USER, "700")
    for path in (
        STATE_ROOT,
        f"{INSTALL_ROOT}/config",
        f"{INSTALL_ROOT}/spool",
        f"{INSTALL_ROOT}/firmware",
        f"{INSTALL_ROOT}/cache",
        f"{INSTALL_ROOT}/run",
        f"{INSTALL_ROOT}/home",
        f"{INSTALL_ROOT}/home/Library",
        f"{INSTALL_ROOT}/home/Library/Application Support",
        LOG_ROOT,
    )
)
LOG_FILES = tuple(
    Artifact(f"{LOG_ROOT}/{name}", SERVICE_USER, SERVICE_USER, "600")
    for name in ("service.log", "daemon.stdout.log", "daemon.stderr.log")
)
REMOVAL_ARTIFACTS = (
    ("LaunchDaemon plist", SERVICE_PLIST),
    ("provider app", INSTALLED_APP),
    ("ownership marker", f"{INSTALL_ROOT}/.product-id"),
    ("state", STATE_ROOT),
    ("configuration", f"{INSTALL_ROOT}/config"),
    ("spool", f"{INSTALL_ROOT}/spool"),
    ("firmware and metadata", f"{INSTALL_ROOT}/firmware"),
    ("cache", f"{INSTALL_ROOT}/cache"),
    ("runtime socket state", f"{INSTALL_ROOT}/run"),
    ("private service home", f"{INSTALL_ROOT}/home"),
    ("remaining product root", INSTALL_ROOT),
    *(("log", artifact.path) for artifact in LOG_FILES),
    ("logs", LOG_ROOT),
)

Runner = Callable[..., subprocess.CompletedProcess[str]]

PREVIEWS = {
    "install": (
        "build and validate pinned sources without privilege",
        "ad-hoc sign nested provider code and app with hardened runtime without privilege",
        "create dedicated account _hplj1020",
        "create private state hierarchy",
        "install root-owned provider app",
        "install root-owned LaunchDaemon plist",
        "bootstrap LaunchDaemon",
        "create or reconcile queue HP_LaserJet_1020",
        "wait for final service UID, loopback listeners, and queue health",
        "no privileged USB helper is created",
    ),
    "disable": (
        "hold queue HP_LaserJet_1020",
        "disable and stop LaunchDaemon com.bartekpapierski.hplj1020.service",
        "preserve configuration, state, spool, firmware, cache, and logs",
    ),
    "enable": (
        "enable and bootstrap LaunchDaemon com.bartekpapierski.hplj1020.service",
        "wait for final service UID and loopback listeners",
        "enable and verify queue HP_LaserJet_1020",
    ),
    "uninstall": (
        f"disable service {SERVICE_LABEL} and hold queue {QUEUE} first",
        f"remove queue {QUEUE}",
        f"remove LaunchDaemon job {SERVICE_LABEL}",
        *(f"remove {description} {path}" for description, path in REMOVAL_ARTIFACTS),
        f"remove product-created account and group {SERVICE_USER} only when ownership markers match",
        f"forget product receipt {RECEIPT} if present",
        "audit every product-owned artifact as absent",
    ),
}


class InstallError(RuntimeError):
    pass


class CommandHost:
    def __init__(self, runner: Runner, audit: TextIO | None = None) -> None:
        self.runner = runner
        self.audit = audit

    def run(self, command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        repository = str(ROOT)
        redacted_command = [
            f"$REPOSITORY{argument[len(repository):]}"
            if argument == repository or argument.startswith(f"{repository}/")
            else argument
            for argument in command
        ]
        event = {"event": "command", "argv": redacted_command, "privileged": command[0] == "/usr/bin/sudo"}
        if self.audit is not None:
            self.audit.write(json.dumps(event, separators=(",", ":")) + "\n")
            self.audit.flush()
        result = self.runner(command, text=True, capture_output=True, check=False)
        if self.audit is not None:
            self.audit.write(json.dumps({"event": "result", "returncode": result.returncode}, separators=(",", ":")) + "\n")
            self.audit.flush()
        if check and result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            raise InstallError(f"command failed: {command[-1]}: {detail}")
        return result

    def admin(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self.run(["/usr/bin/sudo", *arguments], check=check)


def preview(operation: str, stdout: TextIO) -> None:
    print(f"Preview: {operation}", file=stdout)
    for item in PREVIEWS[operation]:
        print(f"- {item}", file=stdout)
    print("No changes made. Re-run with --apply --yes to authorize this exact plan.", file=stdout)


def preview_uninstall(host: CommandHost, stdout: TextIO) -> None:
    present = [
        path for path in (SERVICE_PLIST, INSTALL_ROOT, LOG_ROOT)
        if host.run(["/usr/bin/test", "-e", path], check=False).returncode == 0
    ]
    if host.run(["/bin/launchctl", "print", f"system/{SERVICE_LABEL}"], check=False).returncode == 0:
        present.append(f"launchd:{SERVICE_LABEL}")
    if validate_queue_ownership(host):
        present.append(f"queue:{QUEUE}")
    if account_record(host, "user") is not None:
        present.append(f"user:{SERVICE_USER}")
    if account_record(host, "group") is not None:
        present.append(f"group:{SERVICE_USER}")
    if host.run(["/usr/sbin/pkgutil", "--pkg-info", RECEIPT], check=False).returncode == 0:
        present.append(f"receipt:{RECEIPT}")
    if not present:
        print("Preview: uninstall", file=stdout)
        print("- no product-owned artifacts detected; run the absence audit only", file=stdout)
        print("No changes made.", file=stdout)
        return
    preview("uninstall", stdout)


def linked_libraries(host: CommandHost, binary: Path) -> list[str]:
    output = host.run(["/usr/bin/otool", "-L", str(binary)]).stdout
    return [
        line.strip().split(" ", 1)[0]
        for line in output.splitlines()[1:]
        if line.startswith(("\t", " "))
    ]


def bundle_non_system_libraries(host: CommandHost, executable: Path) -> list[Path]:
    original_libraries = [
        library for library in linked_libraries(host, executable)
        if library.startswith("/opt/homebrew/")
    ]
    frameworks = STAGED_APP / "Contents" / "Frameworks"
    frameworks.mkdir(parents=True, exist_ok=True)
    staged_by_name: dict[str, Path] = {}
    source_by_name: dict[str, Path] = {}
    for library in original_libraries:
        source = Path(library)
        resolved = source.resolve()
        if not resolved.is_file() or not resolved.is_relative_to(Path("/opt/homebrew")):
            raise InstallError(f"refusing non-system library outside Homebrew: {library}")
        destination = frameworks / source.name
        if source.name not in staged_by_name:
            shutil.copy2(resolved, destination)
            destination.chmod(0o755)
            staged_by_name[source.name] = destination
            source_by_name[source.name] = resolved
        host.run([
            "/usr/bin/install_name_tool", "-change", library,
            f"@executable_path/../Frameworks/{source.name}", str(executable),
        ])
    for name, destination in staged_by_name.items():
        host.run(["/usr/bin/install_name_tool", "-id", f"@rpath/{name}", str(destination)])
        for dependency in linked_libraries(host, source_by_name[name]):
            dependency_name = Path(dependency).name
            if (dependency.startswith("/opt/homebrew/")
                    and dependency_name in staged_by_name
                    and dependency_name != name):
                host.run([
                    "/usr/bin/install_name_tool", "-change", dependency,
                    f"@loader_path/{dependency_name}", str(destination),
                ])
    return list(staged_by_name.values())


def stage_and_sign(host: CommandHost) -> None:
    host.run([str(BUILD)])
    if not BUILT_PROVIDER.is_file() or BUILT_PROVIDER.is_symlink():
        raise InstallError(f"validated provider is missing or unsafe: {BUILT_PROVIDER}")
    if BUILT_PROVIDER.stat().st_uid != os.getuid():
        raise InstallError("validated provider must be owned by the invoking user")
    shutil.rmtree(STAGED_APP, ignore_errors=True)
    shutil.copytree(APP_TEMPLATE, STAGED_APP)
    executable = STAGED_APP / "Contents" / "MacOS" / "hplj1020"
    executable.parent.mkdir(parents=True)
    shutil.copy2(BUILT_PROVIDER, executable)
    executable.chmod(0o755)
    host.run(["/usr/bin/plutil", "-lint", str(STAGED_APP / "Contents" / "Info.plist")])
    nested_libraries = bundle_non_system_libraries(host, executable)
    for library in nested_libraries:
        host.run(["/usr/bin/codesign", "--force", "--sign", "-", "--options", "runtime", "--timestamp=none", str(library)])
    host.run(["/usr/bin/codesign", "--force", "--sign", "-", "--options", "runtime", "--timestamp=none", str(executable)])
    host.run(["/usr/bin/codesign", "--force", "--sign", "-", "--options", "runtime", "--timestamp=none", str(STAGED_APP)])
    host.run(["/usr/bin/codesign", "--verify", "--strict", "--deep", str(STAGED_APP)])


def account_record(host: CommandHost, kind: str) -> str | None:
    result = host.run(["/usr/bin/dscacheutil", "-q", kind, "-a", "name", SERVICE_USER], check=False)
    return result.stdout if result.returncode == 0 and "name:" in result.stdout else None


def record_field(record: str, name: str) -> str:
    prefix = f"{name}: "
    return next((line[len(prefix):] for line in record.splitlines() if line.startswith(prefix)), "")


def user_record_matches(user: str) -> bool:
    uid = record_field(user, "uid")
    return (
        record_field(user, "name") == SERVICE_USER
        and uid.isdigit()
        and 450 <= int(uid) <= 499
        and record_field(user, "gid") == uid
        and record_field(user, "dir") == "/var/empty"
        and record_field(user, "shell") == "/usr/bin/false"
        and record_field(user, "gecos") == SERVICE_REAL_NAME
    )


def group_record_matches(group: str) -> bool:
    group_id = record_field(group, "gid")
    return (
        record_field(group, "name") == SERVICE_USER
        and group_id.isdigit()
        and 450 <= int(group_id) <= 499
    )


def account_matches(user: str, group: str) -> bool:
    return (
        user_record_matches(user)
        and group_record_matches(group)
        and record_field(user, "gid") == record_field(group, "gid")
    )


def create_group(host: CommandHost, account_id: str) -> None:
    for mutation in (
        ("/usr/bin/dscl", ".", "-create", f"/Groups/{SERVICE_USER}"),
        ("/usr/bin/dscl", ".", "-create", f"/Groups/{SERVICE_USER}", "PrimaryGroupID", account_id),
        ("/usr/bin/dscl", ".", "-create", f"/Groups/{SERVICE_USER}", "Password", "*"),
    ):
        host.admin(*mutation)


def create_user(host: CommandHost, account_id: str) -> None:
    for mutation in (
        ("/usr/bin/dscl", ".", "-create", f"/Users/{SERVICE_USER}"),
        ("/usr/bin/dscl", ".", "-create", f"/Users/{SERVICE_USER}", "UniqueID", account_id),
        ("/usr/bin/dscl", ".", "-create", f"/Users/{SERVICE_USER}", "PrimaryGroupID", account_id),
        ("/usr/bin/dscl", ".", "-create", f"/Users/{SERVICE_USER}", "RealName", SERVICE_REAL_NAME),
        ("/usr/bin/dscl", ".", "-create", f"/Users/{SERVICE_USER}", "NFSHomeDirectory", "/var/empty"),
        ("/usr/bin/dscl", ".", "-create", f"/Users/{SERVICE_USER}", "UserShell", "/usr/bin/false"),
        ("/usr/bin/dscl", ".", "-create", f"/Users/{SERVICE_USER}", "IsHidden", "1"),
        ("/usr/bin/dscl", ".", "-create", f"/Users/{SERVICE_USER}", "Password", "*"),
    ):
        host.admin(*mutation)


def validate_account_state(host: CommandHost, *, product_owned: bool) -> None:
    user = account_record(host, "user")
    group = account_record(host, "group")
    if user is not None and group is not None:
        if not product_owned or not account_matches(user, group):
            raise InstallError(f"refusing colliding account or group {SERVICE_USER}")
        return
    if user is not None or group is not None:
        if not product_owned:
            raise InstallError(f"refusing colliding account or group {SERVICE_USER}")


def ensure_account(host: CommandHost, *, product_owned: bool) -> None:
    user = account_record(host, "user")
    group = account_record(host, "group")
    if user is not None and group is not None and account_matches(user, group):
        return
    if group is not None and user is None and group_record_matches(group):
        create_user(host, record_field(group, "gid"))
        return
    if user is not None and group is None and user_record_matches(user):
        create_group(host, record_field(user, "gid"))
        return
    if (user is not None or group is not None) and not product_owned:
        raise InstallError(f"refusing colliding account or group {SERVICE_USER}")
    if user is not None:
        host.admin("/usr/bin/dscl", ".", "-delete", f"/Users/{SERVICE_USER}", check=False)
    if group is not None:
        host.admin("/usr/bin/dscl", ".", "-delete", f"/Groups/{SERVICE_USER}", check=False)
    account_id = None
    for candidate in range(499, 449, -1):
        user_id = host.run(["/usr/bin/dscacheutil", "-q", "user", "-a", "uid", str(candidate)], check=False)
        group_id = host.run(["/usr/bin/dscacheutil", "-q", "group", "-a", "gid", str(candidate)], check=False)
        if "name:" not in user_id.stdout and "name:" not in group_id.stdout:
            account_id = str(candidate)
            break
    if account_id is None:
        raise InstallError("no free dedicated system UID/GID in 450...499")
    create_group(host, account_id)
    create_user(host, account_id)


def validate_path_owner(host: CommandHost, artifact: Artifact) -> bool:
    if host.admin("/usr/bin/test", "-e", artifact.path, check=False).returncode != 0:
        return False
    metadata = host.admin("/usr/bin/stat", "-f", "%Su:%Sg:%Lp", artifact.path).stdout.strip()
    if metadata != artifact.metadata:
        raise InstallError(f"refusing foreign installed path {artifact.path}: {metadata or 'unknown ownership'}")
    return True


def validate_product_marker(host: CommandHost, path: str) -> bool:
    if not validate_path_owner(host, Artifact(path, "root", "wheel", "644")):
        return False
    marker = host.admin("/bin/cat", path, check=False)
    if marker.returncode != 0 or marker.stdout.strip() != RECEIPT:
        raise InstallError(f"refusing foreign product marker: {path}")
    return True


def product_marker_matches(host: CommandHost, path: str) -> bool:
    try:
        return validate_product_marker(host, path)
    except InstallError:
        return False


def service_plist_matches(host: CommandHost) -> bool:
    result = host.admin("/bin/cat", SERVICE_PLIST, check=False)
    try:
        plist = plistlib.loads(result.stdout.encode("utf-8"))
    except (plistlib.InvalidFileException, ValueError):
        return False
    expected = {
        "Label": SERVICE_LABEL,
        "UserName": SERVICE_USER,
        "GroupName": SERVICE_USER,
        "WorkingDirectory": STATE_ROOT,
        "StandardOutPath": f"{LOG_ROOT}/daemon.stdout.log",
        "StandardErrorPath": f"{LOG_ROOT}/daemon.stderr.log",
    }
    arguments = plist.get("ProgramArguments")
    expected_program = f"{INSTALLED_APP}/Contents/Resources/hplj1020-service-supervisor"
    return (
        result.returncode == 0
        and all(plist.get(key) == value for key, value in expected.items())
        and isinstance(arguments, list)
        and bool(arguments)
        and arguments[0] == expected_program
    )


def has_product_ownership_evidence(host: CommandHost) -> bool:
    markers = (
        f"{INSTALL_ROOT}/.product-id",
        f"{INSTALLED_APP}/Contents/Resources/product-id",
    )
    if any(product_marker_matches(host, marker) for marker in markers):
        return True
    try:
        plist_exists = validate_path_owner(
            host, Artifact(SERVICE_PLIST, "root", "wheel", "644")
        )
    except InstallError:
        return False
    return plist_exists and service_plist_matches(host)


def validate_existing_installation(host: CommandHost) -> bool:
    product_owned = False
    root_exists = validate_path_owner(host, Artifact(INSTALL_ROOT, "root", "wheel", "755"))
    if root_exists:
        listing = host.admin("/usr/bin/find", INSTALL_ROOT, "-mindepth", "1", "-maxdepth", "1", "-print", check=False)
        allowed = {
            f"{INSTALL_ROOT}/{name}" for name in (
                ".product-id", "HP-LJ-1020.app", "cache", "config", "firmware",
                "home", "run", "spool", "state",
            )
        }
        unknown = sorted(set(listing.stdout.splitlines()) - allowed)
        if unknown:
            raise InstallError("refusing unrecognized installed paths: " + ", ".join(unknown))
    marker = f"{INSTALL_ROOT}/.product-id"
    marker_exists = validate_product_marker(host, marker)
    if marker_exists:
        product_owned = True
    for artifact in (*PRIVATE_DIRECTORIES, *LOG_FILES):
        validate_path_owner(host, artifact)
    if validate_path_owner(host, Artifact(INSTALLED_APP, "root", "wheel", "755")):
        app_marker = f"{INSTALLED_APP}/Contents/Resources/product-id"
        if not validate_product_marker(host, app_marker):
            raise InstallError(f"refusing provider app without product marker: {INSTALLED_APP}")
        identity = host.admin(
            "/usr/libexec/PlistBuddy", "-c", "Print :CFBundleIdentifier",
            f"{INSTALLED_APP}/Contents/Info.plist",
        ).stdout.strip()
        if identity != RECEIPT:
            raise InstallError(f"refusing foreign provider app: {INSTALLED_APP}")
        host.admin("/usr/bin/codesign", "--verify", "--strict", "--deep", INSTALLED_APP)
        product_owned = True
    if validate_path_owner(host, Artifact(SERVICE_PLIST, "root", "wheel", "644")):
        if not service_plist_matches(host):
            raise InstallError(f"refusing foreign LaunchDaemon plist: {SERVICE_PLIST}")
        product_owned = True
    return product_owned


def install_paths(host: CommandHost) -> None:
    for artifact in PRIVATE_DIRECTORIES:
        host.admin("/usr/bin/install", "-d", "-o", artifact.owner, "-g", artifact.group, "-m", artifact.mode, artifact.path)
    for artifact in LOG_FILES:
        exists = host.admin("/usr/bin/test", "-e", artifact.path, check=False)
        if exists.returncode != 0:
            host.admin("/usr/bin/install", "-o", artifact.owner, "-g", artifact.group, "-m", artifact.mode, "/dev/null", artifact.path)


def install_root(host: CommandHost) -> None:
    host.admin("/usr/bin/install", "-d", "-o", "root", "-g", "wheel", "-m", "755", INSTALL_ROOT)


def install_payload(host: CommandHost) -> None:
    host.admin("/usr/bin/ditto", str(STAGED_APP), INSTALLED_APP)
    host.admin("/usr/sbin/chown", "-R", "root:wheel", INSTALLED_APP)
    host.admin("/bin/chmod", "-R", "go-w", INSTALLED_APP)
    host.admin("/usr/bin/codesign", "--verify", "--strict", "--deep", INSTALLED_APP)
    host.admin("/usr/bin/install", "-o", "root", "-g", "wheel", "-m", "644", f"{INSTALLED_APP}/Contents/Resources/product-id", f"{INSTALL_ROOT}/.product-id")
    host.admin("/usr/bin/install", "-o", "root", "-g", "wheel", "-m", "644", f"{INSTALLED_APP}/Contents/Library/LaunchDaemons/{SERVICE_LABEL}.plist", SERVICE_PLIST)
    host.admin("/usr/bin/plutil", "-lint", SERVICE_PLIST)


def reconcile_queue(host: CommandHost) -> None:
    validate_queue_ownership(host)
    host.admin("/usr/sbin/lpadmin", "-p", QUEUE, "-v", QUEUE_URI, "-m", "everywhere", "-E", "-o", "printer-is-shared=false", "-o", "printer-error-policy=stop-printer")


def validate_queue_ownership(host: CommandHost) -> bool:
    query = host.run(["/usr/bin/lpstat", "-v"], check=False)
    prefix = f"device for {QUEUE}: "
    matches = [line for line in query.stdout.splitlines() if line.startswith(prefix)]
    if matches and matches != [f"{prefix}{QUEUE_URI}"]:
        raise InstallError(f"refusing foreign queue collision for {QUEUE}: {matches[0]}")
    return bool(matches)


def wait_ready(host: CommandHost) -> None:
    expected_uid = host.run(["/usr/bin/id", "-u", SERVICE_USER]).stdout.strip()
    last = "launchd job did not reach the provider"
    for _ in range(60):
        job = host.admin("/bin/launchctl", "print", f"system/{SERVICE_LABEL}", check=False)
        pid = next((line.split("=", 1)[1].strip() for line in job.stdout.splitlines() if line.strip().startswith("pid =")), "")
        if pid.isdigit():
            observed_uid = host.run(["/bin/ps", "-o", "uid=", "-p", pid], check=False).stdout.strip()
            provider = host.run(
                ["/usr/bin/pgrep", "-P", pid, "-x", "hplj1020"], check=False
            ).stdout.splitlines()
            provider_pid = provider[0].strip() if provider else ""
            provider_uid = (
                host.run(["/bin/ps", "-o", "uid=", "-p", provider_pid], check=False).stdout.strip()
                if provider_pid.isdigit() else ""
            )
            listeners = host.admin("/usr/sbin/lsof", "-nP", "-a", "-p", provider_pid, "-iTCP:8631", "-sTCP:LISTEN", check=False).stdout if provider_pid.isdigit() else ""
            has_v4 = "127.0.0.1:8631" in listeners
            has_v6 = "[::1]:8631" in listeners
            foreign = any("TCP" in line and "8631" in line and "127.0.0.1:8631" not in line and "[::1]:8631" not in line for line in listeners.splitlines())
            if observed_uid == expected_uid and provider_uid == expected_uid and has_v4 and has_v6 and not foreign:
                queue = host.run(["/usr/bin/lpstat", "-p", QUEUE], check=False)
                devices = host.run(["/usr/bin/lpstat", "-v"], check=False)
                queue_enabled = queue.returncode == 0 and "enabled" in queue.stdout.lower() and "disabled" not in queue.stdout.lower()
                if queue_enabled and f"device for {QUEUE}: {QUEUE_URI}" in devices.stdout:
                    return
            last = f"supervisor={pid or 'missing'} provider={provider_pid or 'missing'} uid={provider_uid or observed_uid or 'missing'}"
        time.sleep(0.5)
    raise InstallError(f"service readiness timed out ({last})")


def disable(host: CommandHost) -> None:
    failures: list[str] = []
    try:
        queue_owned = validate_queue_ownership(host)
    except InstallError as error:
        failures.append(str(error))
        queue_owned = False
    if queue_owned:
        policy = host.admin("/usr/sbin/lpadmin", "-p", QUEUE, "-o", "printer-is-shared=false", "-o", "printer-error-policy=stop-printer", check=False)
        if policy.returncode != 0:
            failures.append("queue policy update failed")
        held = host.admin("/usr/sbin/cupsdisable", QUEUE, check=False)
        if held.returncode != 0:
            failures.append("queue hold failed")
        queue = host.run(["/usr/bin/lpstat", "-p", QUEUE], check=False)
        if "disabled" not in queue.stdout.lower():
            failures.append(f"queue remains enabled: {QUEUE}")
    override = host.admin("/bin/launchctl", "disable", f"system/{SERVICE_LABEL}", check=False)
    if override.returncode != 0:
        failures.append("service disable override failed")
    host.admin("/bin/launchctl", "bootout", f"system/{SERVICE_LABEL}", check=False)
    loaded = host.admin("/bin/launchctl", "print", f"system/{SERVICE_LABEL}", check=False)
    if loaded.returncode == 0:
        failures.append(f"service remains loaded: {SERVICE_LABEL}")
    tcp_listeners = host.admin(
        "/usr/sbin/lsof", "-nP", "-iTCP:8631", "-sTCP:LISTEN", check=False
    )
    if any(line.strip() and not line.startswith("COMMAND") for line in tcp_listeners.stdout.splitlines()):
        failures.append("loopback listener remains active on port 8631")
    socket_listener = host.admin(
        "/usr/sbin/lsof", "-nP", f"{INSTALL_ROOT}/run/service.sock", check=False
    )
    if any(line.strip() and not line.startswith("COMMAND") for line in socket_listener.stdout.splitlines()):
        failures.append("product socket listener remains active")
    disabled = host.admin("/bin/launchctl", "print-disabled", "system", check=False)
    if f'"{SERVICE_LABEL}" => true' not in disabled.stdout:
        failures.append(f"service disable override is missing: {SERVICE_LABEL}")
    if failures:
        raise InstallError("disable incomplete: " + ", ".join(failures))


def enable(host: CommandHost) -> None:
    host.admin("/bin/launchctl", "bootout", f"system/{SERVICE_LABEL}", check=False)
    host.admin("/bin/launchctl", "enable", f"system/{SERVICE_LABEL}")
    host.admin("/bin/launchctl", "bootstrap", "system", SERVICE_PLIST)
    reconcile_queue(host)
    host.admin("/usr/sbin/cupsenable", QUEUE)
    wait_ready(host)


def install(host: CommandHost) -> None:
    stage_and_sign(host)
    host.admin("-v")
    product_owned = validate_existing_installation(host)
    validate_account_state(host, product_owned=product_owned)
    queue_owned = validate_queue_ownership(host)
    if queue_owned and not product_owned:
        raise InstallError(f"refusing unmarked queue collision for {QUEUE}")
    install_root(host)
    install_payload(host)
    disable(host)
    ensure_account(host, product_owned=True)
    install_paths(host)
    validate_existing_installation(host)
    try:
        host.admin("/bin/launchctl", "bootout", f"system/{SERVICE_LABEL}", check=False)
        host.admin("/bin/launchctl", "enable", f"system/{SERVICE_LABEL}")
        host.admin("/bin/launchctl", "bootstrap", "system", SERVICE_PLIST)
        reconcile_queue(host)
        wait_ready(host)
    except InstallError:
        disable(host)
        raise


def uninstall(host: CommandHost) -> None:
    ownership_evidence = has_product_ownership_evidence(host)
    try:
        product_owned = validate_existing_installation(host)
    except InstallError as error:
        if not ownership_evidence:
            raise
        failures = [str(error)]
        try:
            disable(host)
        except InstallError as disable_error:
            failures.append(str(disable_error))
        raise_removal_failure(host, failures)
    receipt = host.run(["/usr/sbin/pkgutil", "--pkg-info", RECEIPT], check=False)
    user = account_record(host, "user")
    group = account_record(host, "group")
    initial_residue = find_removal_residue(host)
    if not initial_residue:
        return
    if not product_owned:
        receipt_residue = f"receipt:{RECEIPT}"
        allowed_recovery_residue = {
            receipt_residue,
            f"launchd-disabled:{SERVICE_LABEL}",
        }
        if receipt.returncode == 0 and set(initial_residue) <= allowed_recovery_residue:
            failures: list[str] = []
            attempt_removal_step(
                host,
                ("/bin/launchctl", "enable", f"system/{SERVICE_LABEL}"),
                f"clear service disable override {SERVICE_LABEL}",
                failures,
            )
            if not failures:
                attempt_removal_step(
                    host,
                    ("/usr/sbin/pkgutil", "--forget", RECEIPT),
                    f"forget receipt {RECEIPT}",
                    failures,
                )
            if failures:
                host.admin("/bin/launchctl", "disable", f"system/{SERVICE_LABEL}", check=False)
                raise_removal_failure(host, failures)
            verify_clean_removal(host)
            return
        raise_removal_failure(
            host, ["refusing uninstall without verified product ownership"]
        )
    try:
        disable(host)
    except InstallError as error:
        raise_removal_failure(host, [str(error)])
    try:
        validate_account_state(host, product_owned=True)
    except InstallError as error:
        raise_removal_failure(host, [str(error)])
    queue_owned = validate_queue_ownership(host)
    failures: list[str] = []

    if queue_owned:
        attempt_removal_step(
            host, ("/usr/sbin/lpadmin", "-x", QUEUE), f"remove queue {QUEUE}", failures
        )
    attempt_removal_step(
        host, ("/bin/rm", "-rf", LOG_ROOT), f"remove logs {LOG_ROOT}", failures
    )
    if not failures:
        attempt_removal_step(
            host,
            ("/bin/rm", "-rf", INSTALL_ROOT),
            f"remove product root {INSTALL_ROOT}",
            failures,
        )
    data_remains = any(
        host.admin("/usr/bin/test", "-e", path, check=False).returncode == 0
        for path in (INSTALL_ROOT, LOG_ROOT)
    )
    if not data_remains:
        if user is not None:
            attempt_removal_step(
                host,
                ("/usr/bin/dscl", ".", "-delete", f"/Users/{SERVICE_USER}"),
                f"remove user {SERVICE_USER}",
                failures,
            )
        if group is not None:
            attempt_removal_step(
                host,
                ("/usr/bin/dscl", ".", "-delete", f"/Groups/{SERVICE_USER}"),
                f"remove group {SERVICE_USER}",
                failures,
            )

    blocking_residue = find_removal_residue(
        host, include_service_registration=False, include_receipt=False
    )
    if failures or blocking_residue:
        raise_removal_failure(host, failures)

    if not failures:
        attempt_removal_step(
            host,
            ("/bin/launchctl", "enable", f"system/{SERVICE_LABEL}"),
            f"clear service disable override {SERVICE_LABEL}",
            failures,
        )
    if not failures:
        attempt_removal_step(
            host,
            ("/bin/rm", "-f", SERVICE_PLIST),
            f"remove LaunchDaemon plist {SERVICE_PLIST}",
            failures,
        )
    if not failures and receipt.returncode == 0:
        attempt_removal_step(
            host,
            ("/usr/sbin/pkgutil", "--forget", RECEIPT),
            f"forget receipt {RECEIPT}",
            failures,
        )
    if failures:
        host.admin("/bin/launchctl", "disable", f"system/{SERVICE_LABEL}", check=False)
        raise_removal_failure(host, failures)
    verify_clean_removal(host)


def attempt_removal_step(
    host: CommandHost,
    command: tuple[str, ...],
    description: str,
    failures: list[str],
) -> None:
    result = host.admin(*command, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        failures.append(f"{description} failed: {detail}")


def raise_removal_failure(host: CommandHost, failures: list[str]) -> None:
    residue = find_removal_residue(host)
    details = failures + (["removal residue: " + ", ".join(residue)] if residue else [])
    raise InstallError("; ".join(details))


def verify_clean_removal(host: CommandHost) -> None:
    if not find_removal_residue(host):
        return
    host.admin("/bin/launchctl", "disable", f"system/{SERVICE_LABEL}", check=False)
    raise_removal_failure(host, [])


def service_disable_override_present(host: CommandHost) -> bool:
    disabled = host.admin("/bin/launchctl", "print-disabled", "system", check=False)
    return f'"{SERVICE_LABEL}" => true' in disabled.stdout


def find_removal_residue(
    host: CommandHost,
    *,
    include_service_registration: bool = True,
    include_receipt: bool = True,
) -> list[str]:
    residue: list[str] = []
    paths = (
        tuple(path for _, path in REMOVAL_ARTIFACTS)
        if include_service_registration
        else tuple(path for _, path in REMOVAL_ARTIFACTS if path != SERVICE_PLIST)
    )
    for path in paths:
        if host.admin("/usr/bin/test", "-e", path, check=False).returncode == 0:
            residue.append(path)
    if include_service_registration:
        if host.admin("/bin/launchctl", "print", f"system/{SERVICE_LABEL}", check=False).returncode == 0:
            residue.append(f"launchd:{SERVICE_LABEL}")
        if service_disable_override_present(host):
            residue.append(f"launchd-disabled:{SERVICE_LABEL}")
    queues = host.run(["/usr/bin/lpstat", "-v"], check=False)
    if any(line.startswith(f"device for {QUEUE}: ") for line in queues.stdout.splitlines()):
        residue.append(f"queue:{QUEUE}")
    if account_record(host, "user") is not None:
        residue.append(f"user:{SERVICE_USER}")
    if account_record(host, "group") is not None:
        residue.append(f"group:{SERVICE_USER}")
    if (include_receipt
            and host.run(["/usr/sbin/pkgutil", "--pkg-info", RECEIPT], check=False).returncode == 0):
        residue.append(f"receipt:{RECEIPT}")
    return residue


def status(host: CommandHost, stdout: TextIO) -> None:
    job = host.admin("/bin/launchctl", "print", f"system/{SERVICE_LABEL}", check=False)
    queue = host.run(["/usr/bin/lpstat", "-p", QUEUE], check=False)
    crash_loop = host.admin("/usr/bin/test", "-e", f"{INSTALL_ROOT}/run/crash-loop", check=False).returncode == 0
    service_state = "crash-loop" if crash_loop else "loaded" if job.returncode == 0 else "not-loaded"
    print(f"service={service_state}", file=stdout)
    print(f"queue={'available' if queue.returncode == 0 else 'absent-or-disabled'}", file=stdout)
    print("listener=verify with enable/install health check", file=stdout)
    if crash_loop:
        print("action=inspect local logs, correct the cause, then run enable", file=stdout)


def main(argv: Sequence[str] | None = None, *, runner: Runner = subprocess.run, stdout: TextIO = sys.stdout) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("install", "disable", "enable", "uninstall", "status"))
    parser.add_argument("--apply", action="store_true", help="perform the previewed lifecycle operation")
    parser.add_argument("--dry-run", action="store_true", help="print the mutation preview and make no changes")
    parser.add_argument("--yes", action="store_true", help="confirm the exact preview without an interactive prompt")
    args = parser.parse_args(argv)
    if args.apply and args.dry_run:
        print("--apply and --dry-run are mutually exclusive", file=stdout)
        return 2
    if args.operation == "status":
        status(CommandHost(runner), stdout)
        return 0
    if args.dry_run or not args.apply:
        if args.operation == "uninstall":
            preview_uninstall(CommandHost(runner), stdout)
        else:
            preview(args.operation, stdout)
        return 0
    if not args.yes:
        print("Refusing mutation without --yes after reviewing the preview.", file=stdout)
        return 2
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        with AUDIT_LOG.open("a", encoding="utf-8") as audit:
            audit.write(json.dumps({"event": "start", "operation": args.operation, "time": datetime.now(timezone.utc).isoformat()}, separators=(",", ":")) + "\n")
            host = CommandHost(runner, audit)
            if args.operation == "install":
                install(host)
                state = "enabled"
            elif args.operation == "disable":
                if not validate_existing_installation(host):
                    raise InstallError("refusing disable without the signed product ownership marker")
                disable(host)
                state = "disabled"
            elif args.operation == "enable":
                if not validate_existing_installation(host):
                    raise InstallError("refusing enable without the signed product ownership marker")
                enable(host)
                state = "enabled"
            else:
                uninstall(host)
                state = "clean"
            audit.write(json.dumps({"event": "complete", "operation": args.operation, "state": state}, separators=(",", ":")) + "\n")
        print(f"state={state}", file=stdout)
        print(f"audit={AUDIT_LOG}", file=stdout)
        return 0
    except (InstallError, OSError, shutil.Error) as error:
        if args.operation in {"disable", "enable"}:
            try:
                disable(CommandHost(runner))
            except (InstallError, OSError):
                pass
        safe_error = str(error).replace(str(ROOT), "$REPOSITORY")
        try:
            with AUDIT_LOG.open("a", encoding="utf-8") as audit:
                audit.write(json.dumps({"event": "failure", "operation": args.operation, "error": safe_error}, separators=(",", ":")) + "\n")
        except OSError:
            pass
        failure_state = "removal-incomplete" if args.operation == "uninstall" else f"{args.operation}-incomplete"
        print(f"state={failure_state}", file=stdout)
        print(f"error={safe_error}", file=stdout)
        print(f"audit={AUDIT_LOG}", file=stdout)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
