#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit local status and allow-listed diagnostic bundles. No network I/O."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "1.0.0"
MAX_LOG_BYTES = 10 * 1024 * 1024
MAX_LOG_AGE = 14 * 24 * 60 * 60
DEVICE_STATES = (
    "disconnected", "pre-firmware", "awaiting-firmware", "firmware-transfer-failed",
    "firmware-unverified", "firmware-present", "ready", "unsupported",
)
ERRORS = (
    "none", "invalid-state", "unsupported-device", "device-access-denied",
    "device-protocol", "device-disconnected", "device-timeout", "transfer-incomplete",
    "firmware-missing", "firmware-affirmation-required", "firmware-unsupported",
    "firmware-corrupt", "firmware-storage-failed", "firmware-transfer-failed",
    "firmware-unverified", "raster-invalid", "cancelled", "encoding-failed",
    "queue-unavailable", "media-empty", "manual-feed-required", "cover-open", "device-fault",
)
ACTIONS = (
    "none", "restart-service", "connect-reference-printer", "check-usb-permissions",
    "reconnect-printer", "reconnect-printer", "reconnect-printer",
    "check-output-before-explicit-retry", "import-lawfully-acquired-firmware",
    "affirm-lawful-acquisition", "select-supported-firmware", "reacquire-firmware",
    "retry-firmware-import", "reconnect-and-retry-firmware", "power-cycle-printer",
    "correct-document-format", "none", "retry-job", "run-enable",
    "load-paper", "load-manual-feed", "close-cover", "clear-device-fault",
)
DISCLOSURE = (
    "GPL-2.0-or-later; independent of HP, Apple, and OpenPrinting; no warranty. "
    "HP firmware is separately licensed, user-supplied, and local only. "
    "Support claims require reference-Mac and connection-path validation."
)


def encode(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def integer(value: object, maximum: int = (1 << 63) - 1) -> bool:
    return type(value) is int and 0 <= value <= maximum


def versions(raw: object) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    result = {}
    for name in ("productVersion", "pappl", "libusb", "foo2zjs"):
        value = raw.get(name)
        pattern = r"[a-f0-9]{40}" if name == "foo2zjs" else r"[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}"
        result[name] = value if isinstance(value, str) and re.fullmatch(pattern, value) else "unavailable"
    return result


def sanitize_snapshot(raw: object, now: int) -> dict:
    result = {"observedAt": None, "device": "unknown", "firmware": "unknown",
              "deviceIdentity": None,
              "connectionPath": {"transport": "unknown", "route": "unobserved"},
              "error": "status-unavailable", "action": "run-enable-and-recheck",
              "versions": versions(None)}
    if not isinstance(raw, dict) or raw.get("schemaVersion") != SCHEMA_VERSION:
        return result
    dependencies = raw.get("dependencies")
    result["versions"] = versions({
        **(dependencies if isinstance(dependencies, dict) else {}),
        "productVersion": raw.get("productVersion"),
    })
    observed = raw.get("time")
    if not integer(observed) or not 0 <= now - observed <= 5:
        result["error"] = "status-stale"
        return result
    device, error = raw.get("device"), raw.get("error")
    if not integer(device, len(DEVICE_STATES) - 1) or not integer(error, len(ERRORS) - 1):
        return result
    result.update(observedAt=observed, device=DEVICE_STATES[device],
                  error=ERRORS[error], action=ACTIONS[error])
    if type(raw.get("firmwareAvailable")) is bool:
        result["firmware"] = "validated-local" if raw["firmwareAvailable"] else "firmware-required"
    if device not in (0, 7):
        result["deviceIdentity"] = {"model": "HP LaserJet 1020", "vendorId": "03f0",
                                    "productId": "2b17", "serial": "redacted"}
    result["connectionPath"] = {
        "transport": "usb" if device not in (0, 7) else "unobserved",
        # USB identity cannot distinguish the approved adapter from the dock.
        "route": "unclassified",
    }
    return result


def read_private(host, path: str, maximum: int) -> str | None:
    result = host.admin("/bin/dd", f"if={path}", f"bs={maximum + 1}", "count=1", check=False)
    if result.returncode or len(result.stdout.encode()) > maximum:
        return None
    return result.stdout


def collect_status(host, *, now: int | None = None) -> dict:
    # Imported lazily so personal_install can route its existing status command here.
    if __package__:
        from scripts import personal_install as install
    else:
        import personal_install as install
    now = int(time.time()) if now is None else now
    snapshot = read_private(host, f"{install.STATE_ROOT}/system.state.diagnostics.json", 262144)
    try:
        raw = json.loads(snapshot) if snapshot is not None else None
    except (ValueError, TypeError):
        raw = None
    result = sanitize_snapshot(raw, now)
    installed = host.run(["/bin/test", "-x", f"{install.INSTALLED_APP}/Contents/MacOS/hplj1020"], check=False)
    result["installation"] = "present" if installed.returncode == 0 else "absent-or-inaccessible"
    if installed.returncode == 0 and result["versions"]["productVersion"] == "unavailable":
        reported = host.run([f"{install.INSTALLED_APP}/Contents/MacOS/hplj1020", "--version"], check=False)
        if reported.returncode == 0:
            parsed = {}
            for line in reported.stdout.splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[0] in ("hplj1020", "pappl", "libusb", "foo2zjs"):
                    parsed["productVersion" if parts[0] == "hplj1020" else parts[0]] = parts[1]
            result["versions"] = versions(parsed)
    service = host.admin("/bin/launchctl", "print", f"system/{install.SERVICE_LABEL}", check=False)
    crash = host.admin("/bin/test", "-e", f"{install.INSTALL_ROOT}/run/crash-loop", check=False)
    queue = host.run(["/usr/bin/lpstat", "-p", install.QUEUE], check=False)
    result.update(schemaVersion=SCHEMA_VERSION, disclosure=DISCLOSURE,
                  retention={"maximumLogBytes": MAX_LOG_BYTES, "maximumLogAgeSeconds": MAX_LOG_AGE,
                             "maximumCompletedJobs": 20, "historySafetySeconds": 60})
    result["service"] = ("crash-loop" if crash.returncode == 0 else
                         "running" if service.returncode == 0 and re.search(r"\bpid = [1-9][0-9]*\b", service.stdout)
                         else "loaded" if service.returncode == 0 else "not-loaded")
    prefix = f"printer {install.QUEUE} "
    result["queue"] = ("disabled" if queue.returncode == 0 and any(
        line.startswith(prefix) and "disabled" in line for line in queue.stdout.splitlines())
        else "available" if queue.returncode == 0 and any(
            line.startswith(prefix) for line in queue.stdout.splitlines()) else "unavailable")
    if result["service"] != "running":
        result.update(device="unknown", firmware="unknown", observedAt=None, deviceIdentity=None,
                      connectionPath={"transport": "unknown", "route": "unobserved"},
                      error="service-unavailable", action="run-enable")
    elif result["queue"] != "available":
        result.update(error="queue-unavailable", action="run-enable")
    return result


def sanitize_logs(raw: str, now: int) -> bytes:
    output = bytearray()
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("schemaVersion") != SCHEMA_VERSION:
            continue
        stamp = event.get("time")
        if not integer(stamp) or not 0 <= now - stamp < MAX_LOG_AGE:
            continue
        safe = {"schemaVersion": SCHEMA_VERSION, "time": stamp}
        if event.get("event") == "service":
            safe["event"] = "service"
        elif event.get("event") == "job" and all(
            integer(event.get(key), bound) for key, bound in (
                ("state", 9), ("error", len(ERRORS) - 1),
                ("bytesSent", (1 << 63) - 1), ("pagesCompleted", (1 << 32) - 1))
        ):
            safe.update(event="job", **{key: event[key] for key in (
                "state", "error", "bytesSent", "pagesCompleted")})
        else:
            continue
        record = encode(safe)
        if len(output) + len(record) > MAX_LOG_BYTES:
            break
        output.extend(record)
    return bytes(output)


def create_bundle(host, destination: Path, *, now: int | None = None) -> None:
    if __package__:
        from scripts import personal_install as install
    else:
        import personal_install as install
    now = int(time.time()) if now is None else now
    inventory = json.loads((ROOT / "docs/spec/diagnostic-bundle-inventory.v1.json").read_text())
    files = {"status.json": encode(collect_status(host, now=now))}
    omitted = {"configuration/redacted.json": "no-exportable-configuration"}
    raw = read_private(host, f"{install.LOG_ROOT}/service.log", MAX_LOG_BYTES)
    if raw is None:
        omitted["logs/service.jsonl"] = "unavailable-or-oversized"
    else:
        files["logs/service.jsonl"] = sanitize_logs(raw, now)
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}
    # A manifest cannot checksum itself. Its checksum is in checksums.sha256;
    # the checksum file is the sole checksum exclusion, per the inventory.
    files["manifest.json"] = encode({
        "schemaVersion": inventory["schemaVersion"],
        "inventoryVersion": inventory["inventoryVersion"],
        "inventorySchema": inventory["$schema"], "createdAt": now,
        "omitted": omitted, "sha256": hashes,
        "checksumFile": "checksums.sha256",
    })
    files["checksums.sha256"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(files.items())
    ).encode()
    entries = {entry["path"]: entry for entry in inventory["entries"]}
    for name, data in files.items():
        if name not in entries or len(data) > entries[name]["maximumBytes"]:
            raise ValueError("diagnostic inventory limit exceeded")
    # Build only already-redacted bytes; deterministic tar metadata excludes
    # account names, absolute paths, and filesystem timestamps.
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w", format=tarfile.USTAR_FORMAT) as bundle:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o600
            bundle.addfile(info, io.BytesIO(data))
    data = archive.getvalue()
    if len(data) > inventory["maximumBundleBytes"]:
        raise ValueError("diagnostic bundle size limit exceeded")
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(data)
