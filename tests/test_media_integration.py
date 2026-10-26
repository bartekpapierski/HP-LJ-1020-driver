#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise real IPP admission, CUPS raster geometry, and fake-device bytes."""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

from test_pappl_integration import install_test_firmware, start_service, stop_service


def run_ipp(uri: str, test: Path, raster: Path | None = None) -> str:
    command = ["/usr/bin/ipptool", "-tv"]
    if raster is not None:
        command += ["-f", str(raster)]
    result = subprocess.run(command + [uri, str(test)], text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def metadata(stream: bytes) -> dict[int, int]:
    offset = stream.index(b"JZJZ") + 4
    while offset + 16 <= len(stream):
        size, kind, count = struct.unpack_from(">III", stream, offset)
        if kind == 2:
            return {struct.unpack_from(">H", stream, offset + 20 + i * 12)[0]:
                    struct.unpack_from(">I", stream, offset + 24 + i * 12)[0]
                    for i in range(count)}
        offset += size
    raise AssertionError("missing page metadata")


def main() -> int:
    executable, maker = map(lambda s: Path(s).resolve(), sys.argv[1:])
    with tempfile.TemporaryDirectory(prefix="hplj-media-") as directory:
        root = Path(directory)
        install_test_firmware(root)
        process, port = start_service(executable, root)
        uri = f"ipp://127.0.0.1:{port}/ipp/print"
        try:
            attrs = run_ipp(uri, Path("/usr/share/cups/ipptool/get-printer-attributes.test"))
            assert "media-source-supported (1setOf keyword) = auto,main,manual" in attrs, attrs
            assert "x-dimension=7600-21600" in attrs and "y-dimension=12700-35600" in attrs
            raster = root / "page.pwg"
            test = root / "media.test"
            cases = [
                # Client composes landscape into a portrait physical raster.
                ("iso_a4_210x297mm", "auto", "", 9, 7, 9),
                ("na_legal_8.5x14in", "main", "ATTR enum orientation-requested 4", 9, 1, 5),
                ("custom_test_76x127mm", "manual", "", 9, 4, 256),
                ("custom_test_216x356mm", "main", "", 9, 1, 256),
                # Conflicting explicit media/source representations must abort.
                ("iso_a4_210x297mm", "main", "ATTR keyword media-source manual", 8, 0, 0),
                ("iso_a4_210x297mm", "main", "ATTR keyword media na_letter_8.5x11in", 8, 0, 0),
                ("iso_a4_210x297mm", "main", "", 8, 0, 0),  # Letter raster, A4 request.
                ("iso_a4_210x297mm", "manual", "", 9, 4, 9),  # Recovery.
                ("custom_test_100x150mm", "auto", "", 9, 7, 256),
                ("custom_test_123x234mm", "manual", "", 9, 4, 256),
                ("iso_a4_210x297mm", "main", "margin:0", 8, 0, 0),
                ("iso_a4_210x297mm", "main", "margin:-1", 8, 0, 0),
                ("iso_a4_210x297mm", "main", "margin:999999", 8, 0, 0),
                ("iso_a4_210x297mm", "tray-2", "", 8, 0, 0),
                ("iso_a4_210x297mm", "main", "raster-source", 8, 0, 0),
                ("iso_a4_210x297mm", "auto", "ATTR enum orientation-requested 5", 9, 7, 9),
                ("iso_a4_210x297mm", "auto", "ATTR enum orientation-requested 6", 9, 7, 9),
                ("iso_a4_210x297mm", "main", "size:21590x27940", 8, 0, 0),
                ("iso_a4_210x297mm", "auto", "size:21000x29700", 9, 7, 9),
            ]
            for index, (media, source, extra, state, source_code, paper_code) in enumerate(cases):
                input_media = "na_letter_8.5x11in" if index == 6 else media
                raster_source = ["--source=4"] if extra == "raster-source" else []
                if raster_source:
                    extra = ""
                subprocess.run([maker, "pwg", raster, f"--media={input_media}", *raster_source], check=True)
                # Dimensions-only media-col deliberately exercises PAPPL custom import.
                if media.startswith("custom_"):
                    width_mm, length_mm = map(int, media.split("_")[-1][:-2].split("x"))
                    width, length = width_mm * 100, length_mm * 100
                    selection = f"MEMBER collection media-size {{ MEMBER integer x-dimension {width} MEMBER integer y-dimension {length} }}"
                else:
                    selection = f"MEMBER keyword media-size-name {media}"
                if extra.startswith("size:"):
                    width, length = extra.split(":")[1].split("x")
                    selection += f" MEMBER collection media-size {{ MEMBER integer x-dimension {width} MEMBER integer y-dimension {length} }}"
                    extra = ""
                if extra.startswith("margin:"):
                    selection += f" MEMBER integer media-left-margin {extra.split(':')[1]}"
                    extra = ""
                test.write_text(f'''{{
OPERATION Print-Job
GROUP operation-attributes-tag
ATTR charset attributes-charset utf-8
ATTR language attributes-natural-language en
ATTR uri printer-uri $uri
ATTR name requesting-user-name host-test
ATTR mimeMediaType document-format image/pwg-raster
GROUP job-attributes-tag
ATTR collection media-col {{ {selection} MEMBER keyword media-source {source} }}
{extra}
FILE $filename
STATUS successful-ok
EXPECT job-id
}}
{{
OPERATION Get-Job-Attributes
GROUP operation-attributes-tag
ATTR charset attributes-charset utf-8
ATTR language attributes-natural-language en
ATTR uri printer-uri $uri
ATTR integer job-id $job-id
STATUS successful-ok
EXPECT job-state WITH-VALUE >5 REPEAT-NO-MATCH REPEAT-LIMIT 50
EXPECT job-state WITH-VALUE {state}
}}
''')
                before = (root / "device").stat().st_size
                result = run_ipp(uri, test, raster)
                output = (root / "device").read_bytes()[before:]
                if state == 8:
                    assert not output, (index, result)
                else:
                    page = metadata(output)
                    assert page[3] == paper_code and page[5] == source_code, page
                    assert ("Priority feed selected" if source == "manual" else
                            "Main tray selected" if source == "main" else "Automatic feed") in result
            # Unsupported media cannot be silently substituted even without fidelity.
            for media in ("iso_a3_297x420mm", "custom_test_75x127mm"):
                test.write_text(f'''{{
OPERATION Print-Job
GROUP operation-attributes-tag
ATTR charset attributes-charset utf-8
ATTR language attributes-natural-language en
ATTR uri printer-uri $uri
GROUP job-attributes-tag
ATTR keyword media {media}
FILE $filename
STATUS client-error-attributes-or-values-not-supported
}}
''')
                before = (root / "device").stat().st_size
                run_ipp(uri, test, raster)
                assert (root / "device").stat().st_size == before
        finally:
            stop_service(process)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
