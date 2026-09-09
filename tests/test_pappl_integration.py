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


def start_service(
    executable: Path, root: Path, *, failing_device: bool = False
) -> tuple[subprocess.Popen[str], int]:
    for name in ("state", "spool", "log", "run"):
        (root / name).mkdir(parents=True, exist_ok=True)
    device = root / "device"
    if failing_device:
        device_uri = "hpljtest://fail-write"
    else:
        device.touch()
        device_uri = f"hpljtest://{device}"
    process = subprocess.Popen(
        [
            executable,
            "--serve",
            "--state", str(root / "state/system.state"),
            "--spool", str(root / "spool"),
            "--log", str(root / "log/service.log"),
            "--socket", str(root / "run/service.sock"),
            "--device-uri", device_uri,
            *([] if failing_device else ["--firmware", str(root / "firmware")]),
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


def install_test_firmware(root: Path) -> None:
    firmware = b"host-only synthetic firmware fixture"
    active = root / "firmware/active"
    active.mkdir(parents=True, mode=0o700)
    (root / "firmware").chmod(0o700)
    active.chmod(0o700)
    contents = active / "contents"
    metadata = active / "metadata"
    contents.write_bytes(firmware)
    metadata.write_text(
        "schema=1\n"
        "affirmation=lawful-acquisition\n"
        "source=host-only synthetic fixture\n"
        "version-build=20050309\n"
        f"sha256={hashlib.sha256(firmware).hexdigest()}\n"
    )
    contents.chmod(0o600)
    metadata.chmod(0o600)


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
        subprocess.run(
            [raster_maker, "pwg", raster,
             *(str(corpus / page["path"]) for page in pages)],
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


def assert_ordered_page_streams(output: bytes, expected_pages: int) -> None:
    prefix = b"\x1b%-12345X@PJL JOB\n"
    trailer = b"\x1b%-12345X@PJL EOJ\n\x1b%-12345X"
    offset = 0
    for _page in range(expected_pages):
        assert output.startswith(prefix, offset)
        end = output.find(trailer, offset + len(prefix))
        assert end >= 0
        stream = output[offset:end]
        assert stream.count(b"JZJZ") == 1
        offset = end + len(trailer)
    assert offset == len(output)


def assert_device_failure_propagates(
    executable: Path, raster_maker: Path, root: Path
) -> None:
    process, port = start_service(executable, root, failing_device=True)
    try:
        raster = root / "failure-job.pwg"
        subprocess.run([raster_maker, "pwg", raster, "--noise"], check=True)
        result = subprocess.run(
            [
                "/usr/bin/ipptool", "-t",
                "-d", f"filename={raster}",
                "-d", "filetype=image/pwg-raster",
                "-d", "user=host-test",
                f"ipp://127.0.0.1:{port}/ipp/print",
                "/usr/share/cups/ipptool/print-job-and-wait.test",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stdout
        assert "job-state (enum) = aborted" in result.stdout
        assert "aborted-by-system" in result.stdout
    finally:
        stop_service(process)


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
            queued = root / "queued-before-firmware.pwg"
            subprocess.run([raster_maker, "pwg", queued], check=True)
            with ThreadPoolExecutor(max_workers=1) as executor:
                queued_submission = executor.submit(
                    submit_raster, uri, queued, test_file=submit_test
                )
                time.sleep(0.25)
                assert (root / "device").stat().st_size == 0
                install_test_firmware(root)
                queued_submission.result(timeout=10)
            deadline = time.monotonic() + 10
            while (root / "device").stat().st_size == 0 and time.monotonic() < deadline:
                time.sleep(0.05)
            assert (root / "device").stat().st_size > 0
            trace = (root / "device.trace").read_text().splitlines()
            assert trace.index("discover") < trace.index("identity-pre-firmware")
            assert trace.index("identity-pre-firmware") < trace.index("firmware-upload")
            assert trace.index("firmware-upload") < trace.index("identity-ready")
            assert trace.index("identity-ready") < trace.index("print-write")
            baseline_size = (root / "device").stat().st_size
            subprocess.run(
                [
                    "/usr/bin/ipptool", "-t",
                    uri, invalid_job,
                ],
                check=True,
            )
            assert (root / "device").stat().st_size == baseline_size
            subprocess.run(
                ["/usr/bin/ipptool", "-t", uri, invalid_quality],
                check=True,
            )
            assert (root / "device").stat().st_size == baseline_size
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
            assert (root / "device").stat().st_size == baseline_size
            raster = root / "job.pwg"
            subprocess.run([raster_maker, "pwg", raster], check=True)
            submit_raster(uri, raster)
            deadline = time.monotonic() + 10
            while ((root / "device").stat().st_size <= baseline_size and
                   time.monotonic() < deadline):
                time.sleep(0.05)
            pwg_size = (root / "device").stat().st_size
            assert pwg_size > baseline_size
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
            assert combined_output.count(b"JZJZ") == 3
            golden_pages = submit_golden_corpus(
                uri, raster_maker, root, corpus, submit_test
            )
            deadline = time.monotonic() + 30
            while ((root / "device").read_bytes().count(b"JZJZ") <
                   golden_pages + 3 and time.monotonic() < deadline):
                time.sleep(0.05)
            combined_output = (root / "device").read_bytes()
            assert combined_output.count(b"JZJZ") == golden_pages + 3
            assert combined_output.count(b"@PJL JOB\n") == golden_pages + 3
            assert combined_output.count(b"@PJL EOJ\n") == golden_pages + 3
            assert_ordered_page_streams(combined_output, golden_pages + 3)
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
        assert b"JZJZ" not in retained
        assert b"@PJL JOB" not in retained

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

        failure_root = root / "failure-service"
        assert_device_failure_propagates(executable, raster_maker, failure_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
