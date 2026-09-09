#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Host-only PAPPL service lifecycle and fake-device integration test."""

from __future__ import annotations

import http.client
import hashlib
import json
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor


def start_service(executable: Path, root: Path) -> tuple[subprocess.Popen[str], int]:
    for name in ("state", "spool", "log", "run"):
        (root / name).mkdir(parents=True, exist_ok=True)
    device = root / "device"
    device.touch()
    process = subprocess.Popen(
        [
            executable,
            "--serve",
            "--state", str(root / "state/system.state"),
            "--spool", str(root / "spool"),
            "--log", str(root / "log/service.log"),
            "--socket", str(root / "run/service.sock"),
            "--device-uri", device.as_uri(),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    line = process.stdout.readline()
    fields = line.split()
    if len(fields) != 3 or fields[:2] != ["READY", "127.0.0.1"]:
        stderr = process.stderr.read() if process.stderr is not None else ""
        log = (root / "log/service.log").read_text(errors="replace")
        if "Operation not permitted" in log:
            raise PermissionError("sandbox denied loopback listener")
        raise AssertionError(f"service did not become ready: {line!r} {stderr!r}\n{log}")
    return process, int(fields[2])


def stop_service(process: subprocess.Popen[str]) -> None:
    process.send_signal(signal.SIGTERM)
    assert process.wait(timeout=10) == 0


def submit_raster(
    uri: str, raster: Path, *, user: str = "host-test", test_file: Path | None = None
) -> None:
    if test_file is None:
        test_file = Path("/usr/share/cups/ipptool/print-job-and-wait.test")
    for _attempt in range(20):
        result = subprocess.run(
            [
                "/usr/bin/ipptool", "-t",
                "-d", f"filename={raster}",
                "-d", "filetype=image/pwg-raster",
                "-d", f"user={user}",
                uri,
                test_file,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return
        if "server-error-busy" not in result.stdout:
            break
        time.sleep(0.05)
    raise AssertionError(
        f"raster submission failed: {result.stdout}\n{result.stderr}"
    )


def submit_golden_corpus(
    uri: str, raster_maker: Path, root: Path, corpus: Path, submit_test: Path
) -> int:
    manifest = json.loads((corpus / "manifest.json").read_text())
    submissions: list[Path] = []
    expected_pages = 0
    for index, document in enumerate(manifest["documents"]):
        pages = document["pages"]
        for page in pages:
            source = corpus / page["path"]
            assert hashlib.sha256(source.read_bytes()).hexdigest() == page["sha256"]
        expected_pages += len(pages)
        raster = root / f"private-document-{index}.pwg"
        seed = int(pages[0]["sha256"][:2], 16) + 1
        subprocess.run(
            [raster_maker, "pwg", raster, str(len(pages)), str(seed)],
            check=True,
        )
        submissions.append(raster)
    with ThreadPoolExecutor(max_workers=len(submissions)) as executor:
        futures = [
            executor.submit(
                submit_raster, uri, raster, user="private-user-sentinel",
                test_file=submit_test
            )
            for raster in submissions
        ]
        for future in futures:
            future.result()
    return expected_pages


def main() -> int:
    if len(sys.argv) != 8:
        return 2
    executable = Path(sys.argv[1]).resolve()
    raster_maker = Path(sys.argv[2]).resolve()
    invalid_job = Path(sys.argv[3]).resolve()
    invalid_quality = Path(sys.argv[4]).resolve()
    malformed_job = Path(sys.argv[5]).resolve()
    corpus = Path(sys.argv[6]).resolve()
    submit_test = Path(sys.argv[7]).resolve()
    with tempfile.TemporaryDirectory(prefix="hplj1020-pappl-") as directory:
        root = Path(directory)
        try:
            process, port = start_service(executable, root)
        except PermissionError:
            return 77
        try:
            with socket.create_connection(("::1", port), timeout=2):
                pass
            uri = f"ipp://127.0.0.1:{port}/ipp/print"
            web = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            web.request("GET", "/")
            response = web.getresponse()
            response.read()
            web.close()
            assert response.status == 404
            subprocess.run(
                [
                    "/usr/bin/ipptool", "-t",
                    uri, invalid_job,
                ],
                check=True,
            )
            assert (root / "device").stat().st_size == 0
            subprocess.run(
                ["/usr/bin/ipptool", "-t", uri, invalid_quality],
                check=True,
            )
            assert (root / "device").stat().st_size == 0
            malformed = root / "malformed.pwg"
            malformed.write_bytes(b"not a PWG raster document")
            subprocess.run(
                [
                    "/usr/bin/ipptool", "-t",
                    "-d", f"filename={malformed}",
                    uri, malformed_job,
                ],
                check=True,
            )
            assert (root / "device").stat().st_size == 0
            raster = root / "job.pwg"
            subprocess.run([raster_maker, "pwg", raster], check=True)
            submit_raster(uri, raster)
            deadline = time.monotonic() + 10
            while (root / "device").stat().st_size == 0 and time.monotonic() < deadline:
                time.sleep(0.05)
            pwg_size = (root / "device").stat().st_size
            assert pwg_size > 0
            pwg_output = (root / "device").read_bytes()
            assert pwg_output.startswith(b"\x1b%-12345X@PJL JOB\n")
            assert b"JZJZ" in pwg_output
            assert b"@PJL EOJ\n" in pwg_output
            raster = root / "job.urf"
            subprocess.run([raster_maker, "apple", raster], check=True)
            subprocess.run(
                [
                    "/usr/bin/ipptool", "-t",
                    "-d", f"filename={raster}",
                    "-d", "filetype=image/urf",
                    "-d", "user=host-test",
                    uri,
                    "/usr/share/cups/ipptool/print-job-and-wait.test",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            deadline = time.monotonic() + 10
            while ((root / "device").stat().st_size <= pwg_size and
                   time.monotonic() < deadline):
                time.sleep(0.05)
            assert (root / "device").stat().st_size > pwg_size
            combined_output = (root / "device").read_bytes()
            assert combined_output.count(b"JZJZ") == 2
            golden_pages = submit_golden_corpus(
                uri, raster_maker, root, corpus, submit_test
            )
            deadline = time.monotonic() + 15
            while ((root / "device").read_bytes().count(b"JZJZ") <
                   golden_pages + 2 and time.monotonic() < deadline):
                time.sleep(0.05)
            combined_output = (root / "device").read_bytes()
            assert combined_output.count(b"JZJZ") == golden_pages + 2
            assert combined_output.count(b"@PJL JOB\n") == golden_pages + 2
            assert combined_output.count(b"@PJL EOJ\n") == golden_pages + 2
        finally:
            stop_service(process)
        assert (root / "state/system.state").is_file()
        retained = b"".join(
            path.read_bytes()
            for directory in (root / "state", root / "spool", root / "log")
            for path in directory.rglob("*")
            if path.is_file()
        )
        assert b"private-user-sentinel" not in retained
        assert b"private-document-" not in retained

        process, port = start_service(executable, root)
        try:
            result = subprocess.run(
                [
                    "/usr/bin/ipptool", "-tv",
                    f"ipp://127.0.0.1:{port}/ipp/print",
                    "/usr/share/cups/ipptool/get-printer-attributes.test",
                ],
                check=True,
                text=True,
                capture_output=True,
            )
            format_attributes = "\n".join(
                line for line in result.stdout.splitlines()
                if "document-format-supported" in line
            )
            quality_attributes = "\n".join(
                line for line in result.stdout.splitlines()
                if "print-quality-supported" in line
            )
            default_format = "\n".join(
                line for line in result.stdout.splitlines()
                if "document-format-default" in line
            )
            assert "printer-resolution-supported (resolution) = 600dpi" in result.stdout
            assert "pwg-raster-document-type-supported (keyword) = black_1" in result.stdout
            assert "image/pwg-raster" in format_attributes
            assert "image/urf" in format_attributes
            assert "image/urf" in default_format
            assert "normal" in quality_attributes
            assert "application/octet-stream" not in format_attributes
            assert "application/vnd.hp-zjs" not in format_attributes
            assert "printer-dns-sd-name (nameWithoutLanguage) = " in result.stdout
        finally:
            stop_service(process)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
