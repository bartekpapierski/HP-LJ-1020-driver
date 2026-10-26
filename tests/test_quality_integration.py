#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real IPP quality negotiation and exact-model bytes through a fake device."""
from pathlib import Path
import subprocess
import sys
import tempfile

from test_media_integration import metadata, run_ipp
from test_pappl_integration import install_test_firmware, start_service, stop_service


def request(attributes: str, *, operation: str = "Print-Job", state: int = 9,
            status: str = "successful-ok") -> str:
    body = f'''{{
OPERATION {operation}
GROUP operation-attributes-tag
ATTR charset attributes-charset utf-8
ATTR language attributes-natural-language en
ATTR uri printer-uri $uri
ATTR name requesting-user-name host-test
ATTR mimeMediaType document-format image/pwg-raster
GROUP job-attributes-tag
{attributes}
'''
    if operation == "Print-Job":
        body += "FILE $filename\n"
    body += f"STATUS {status}\n}}\n"
    if operation == "Print-Job" and status == "successful-ok":
        body += f'''{{
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
'''
    return body


def main() -> int:
    executable, maker = (Path(value).resolve() for value in sys.argv[1:])
    # Separate services keep each run below the strict 20-job history bound.
    for quality, dpi in ((4, 600), (5, 1200)):
        with tempfile.TemporaryDirectory(prefix="hplj-quality-") as directory:
            root = Path(directory)
            install_test_firmware(root)
            process, port = start_service(executable, root)
            uri = f"ipp://127.0.0.1:{port}/ipp/print"
            try:
                attrs = run_ipp(uri, Path("/usr/share/cups/ipptool/get-printer-attributes.test"))
                for advertised in (
                    "print-quality-supported (1setOf enum) = normal,high",
                    "printer-resolution-default (resolution) = 600dpi",
                    "printer-resolution-supported (1setOf resolution) = 600dpi,1200x600dpi",
                    "hplj-density-supported (rangeOfInteger) = 1-5",
                    "hplj-density-default (integer) = 3",
                    "hplj-economode-supported (1setOf boolean) = false,true",
                    "hplj-economode-default (boolean) = false",
                ):
                    assert advertised in attrs, (advertised, attrs)
                # URF cannot describe asymmetric FastRes input resolution.
                test = root / "urf-capabilities.test"
                test.write_text('''{
OPERATION Get-Printer-Attributes
GROUP operation-attributes-tag
ATTR charset attributes-charset utf-8
ATTR language attributes-natural-language en
ATTR uri printer-uri $uri
ATTR mimeMediaType document-format image/urf
ATTR keyword requested-attributes print-quality-supported,printer-resolution-supported,urf-supported
STATUS successful-ok
}
''')
                urf_attrs = run_ipp(uri, test)
                assert "print-quality-supported (enum) = normal" in urf_attrs, urf_attrs
                assert "printer-resolution-supported (resolution) = 600dpi" in urf_attrs
                assert "RS600" in urf_attrs and "RS600-1200" not in urf_attrs
                assert "PQ4" in urf_attrs and "PQ3-4-5" not in urf_attrs
                raster = root / "page.pwg"
                test = root / "quality.test"
                subprocess.run([maker, "pwg", raster, f"--x-dpi={dpi}"], check=True)
                invalid = (
                    "ATTR integer hplj-density 0", "ATTR integer hplj-density 6",
                    "ATTR keyword hplj-density 3", "ATTR integer hplj-density 2,3",
                    "ATTR keyword hplj-economode true", "ATTR boolean hplj-economode true,false",
                    "ATTR enum print-quality 3", "ATTR enum print-quality 6",
                    "ATTR resolution printer-resolution 1200dpi",
                    "ATTR resolution printer-resolution 300dpi",
                    "ATTR enum print-quality 4\nATTR resolution printer-resolution 1200x600dpi",
                    "ATTR enum print-quality 5\nATTR resolution printer-resolution 600dpi",
                )
                for attributes in invalid:
                    for operation in ("Validate-Job", "Create-Job", "Print-Job"):
                        test.write_text(request(attributes, operation=operation,
                                                status="client-error-attributes-or-values-not-supported"))
                        before = (root / "device").stat().st_size
                        run_ipp(uri, test, raster)
                        assert (root / "device").stat().st_size == before, attributes
                for attributes in ("ATTR enum print-quality 5",
                                   "ATTR resolution printer-resolution 1200x600dpi"):
                    test.write_text(request(attributes, status="client-error-attributes-or-values-not-supported")
                                    .replace("image/pwg-raster", "image/urf"))
                    before = (root / "device").stat().st_size
                    run_ipp(uri, test, raster)
                    assert (root / "device").stat().st_size == before
                # A header/request conflict must abort, with no device output.
                test.write_text(request(f"ATTR enum print-quality {9 - quality}", state=8))
                before = (root / "device").stat().st_size
                run_ipp(uri, test, raster)
                assert (root / "device").stat().st_size == before
                for density in range(1, 6):
                    for econ in (False, True):
                        test.write_text(request(f'''ATTR enum print-quality {quality}
ATTR resolution printer-resolution {dpi}x600dpi
ATTR integer hplj-density {density}
ATTR boolean hplj-economode {str(econ).lower()}'''))
                        before = (root / "device").stat().st_size
                        result = run_ipp(uri, test, raster)
                        output = (root / "device").read_bytes()[before:]
                        page = metadata(output)
                        assert page[8] == page[9] == 600, page
                        assert page[16] == dpi // 600, page
                        assert page[17] == page[12] // (dpi // 600), page
                        assert page[23] == int(econ), page
                        assert f"@PJL SET DENSITY={density}\n".encode() in output
                        assert b"@PJL SET ECONOMODE=" + (b"ON\n" if econ else b"OFF\n") in output
                        assert ("FastRes 1200" if quality == 5 else "600x600 dpi with REt") in result, result
                        assert f"density {density}; EconoMode {'on' if econ else 'off'}" in result
                # Persist/reload the printer, retaining vendor capability attributes.
                stop_service(process)
                process, port = start_service(executable, root)
                uri = f"ipp://127.0.0.1:{port}/ipp/print"
                reloaded = run_ipp(uri, Path("/usr/share/cups/ipptool/get-printer-attributes.test"))
                assert "hplj-density-supported (rangeOfInteger) = 1-5" in reloaded
                assert "hplj-economode-default (boolean) = false" in reloaded
                # Resolution alone selects the matching mode; absent vendor values reset.
                test.write_text(request(f"ATTR resolution printer-resolution {dpi}x600dpi"))
                before = (root / "device").stat().st_size
                run_ipp(uri, test, raster)
                output = (root / "device").read_bytes()[before:]
                assert metadata(output)[16] == dpi // 600
                assert b"@PJL SET DENSITY=3\n@PJL SET ECONOMODE=OFF\n" in output
                # Quality alone selects the same raster contract.
                test.write_text(request(f"ATTR enum print-quality {quality}"))
                run_ipp(uri, test, raster)
                if quality == 4:
                    # Neither control supplied retains true 600 dpi; URF also
                    # carries the independent density and EconoMode controls.
                    test.write_text(request(""))
                    run_ipp(uri, test, raster)
                    subprocess.run([maker, "apple", raster], check=True)
                    test.write_text(request("ATTR integer hplj-density 5\nATTR boolean hplj-economode true")
                                    .replace("image/pwg-raster", "image/urf"))
                    before = (root / "device").stat().st_size
                    run_ipp(uri, test, raster)
                    output = (root / "device").read_bytes()[before:]
                    assert metadata(output)[23] == 1
                    assert metadata(output)[16] == 1
                    assert b"@PJL SET DENSITY=5\n@PJL SET ECONOMODE=ON\n" in output
            finally:
                stop_service(process)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
