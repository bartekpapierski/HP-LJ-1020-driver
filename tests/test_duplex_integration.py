#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Native PDF renderer and real simplex IPP passes against the fake device."""
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.manual_duplex import Backend, plan, run_workflow
from test_pappl_integration import install_test_firmware, start_service, stop_service
from test_media_integration import run_ipp


def make_pdf(path, count, *, width=595, height=842, rotation=0, origin=(0, 0)):
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    kids = []
    for index in range(count):
        kids.append(f"{len(objects) + 1} 0 R")
        x, y = origin
        content = f"0 g {x + 30 + index * 40} {y + 40} 20 60 re f".encode()
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [{x} {y} {x + width} {y + height}] /Rotate {rotation} /Contents {len(objects) + 2} 0 R >>".encode())
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
    objects[1] = f"<< /Type /Pages /Count {count} /Kids [{' '.join(kids)}] >>".encode()
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, value in enumerate(objects, 1):
        offsets.append(len(output))
        output += f"{number} 0 obj\n".encode() + value + b"\nendobj\n"
    xref = len(output)
    output += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    for offset in offsets[1:]:
        output += f"{offset:010} 00000 n \n".encode()
    output += f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(output)


def check_legacy_provider(helper):
    class LegacyProvider(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            # Successful IPP reply from a provider predating the instance attr.
            reply = b'\x02\x00\x00\x00' + body[4:8] + b'\x03'
            self.send_response(200)
            self.send_header('Content-Type', 'application/ipp')
            self.send_header('Content-Length', str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args):
            pass

    with HTTPServer(('127.0.0.1', 0), LegacyProvider) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = subprocess.run([helper, 'instance', str(server.server_port)],
                                    text=True, capture_output=True, timeout=10)
            assert result.returncode == 1
            assert 'tagged-source update' in result.stderr, result.stderr
            assert 'successful-ok' not in result.stderr, result.stderr
        finally:
            server.shutdown()
            thread.join()


def check_slow_send(helper):
    class SlowProvider(BaseHTTPRequestHandler):
        requests = 0
        delay = 16

        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            type(self).requests += 1
            time.sleep(type(self).delay)
            reply = b'\x02\x00\x00\x00' + body[4:8] + b'\x03'
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'application/ipp')
                self.send_header('Content-Length', str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    with HTTPServer(('127.0.0.1', 0), SlowProvider) as server, tempfile.TemporaryDirectory() as directory:
        raster = Path(directory) / 'fixture.pwg'
        raster.write_bytes(b'host-only upload fixture')
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            backend = Backend(helper, server.server_port)
            # PAPPL can defer its response until physical output completes.
            # Default direct-helper timeout must survive the former 15s limit.
            result = subprocess.run([helper, 'send', str(server.server_port), '1', raster],
                                    text=True, capture_output=True, timeout=25)
            assert result.returncode == 0, result.stderr
            assert SlowProvider.requests == 1, 'upload must not be replayed'
            SlowProvider.delay = 0.5
            try:
                backend.send(1, raster, timeout=0.2)
                raise AssertionError('send ignored the configured pass timeout')
            except RuntimeError as error:
                assert 'pages may already have printed' in str(error), str(error)
                assert 'Undefined error' not in str(error), str(error)
            assert SlowProvider.requests == 2, 'timed-out upload must not be replayed'
        finally:
            server.shutdown()
            thread.join()


def check_pdf_scale(helper, reader):
    # A known physical mark provides an oracle independent of the renderer.
    # PDF points are 1/72 inch, while PWG samples are 1/600 inch.
    cases = [(595, 842, 0, 'portrait', (0, 0)),
             (595, 842, 0, 'landscape', (0, 0)),
             (842, 595, 0, 'portrait', (0, 0)),
             (842, 595, 0, 'landscape', (0, 0)),
             (595, 842, 90, 'portrait', (0, 0)),
             (595, 842, 180, 'portrait', (0, 0)),
             (595, 842, 270, 'portrait', (0, 0)),
             (595, 842, 0, 'portrait', (20, 30))]
    with tempfile.TemporaryDirectory(prefix='hplj-pdf-scale-') as directory:
        root = Path(directory)
        for index, (width, height, rotation, orientation, origin) in enumerate(cases):
            pdf, raster = root / 'input.pdf', root / f'page-{index}.pwg'
            make_pdf(pdf, 2, width=width, height=height, rotation=rotation, origin=origin)
            subprocess.run([helper, 'render', pdf, raster, orientation, '0', '1'], check=True)
            result = subprocess.run([reader, raster], text=True, capture_output=True, check=True)
            left, top, right, bottom = map(int, result.stdout.split())
            swapped = (rotation + (90 if orientation == 'landscape' else 0)) % 180 == 90
            page_width, page_height = (height, width) if swapped else (width, height)
            scale = min(600 / 72, (4960 - 2 * 94) / page_width, (7015 - 2 * 94) / page_height)
            expected_width, expected_height = ((60, 20) if swapped else (20, 60))
            assert abs((right - left + 1) - expected_width * scale) <= 2, (cases[index], result.stdout, scale)
            assert abs((bottom - top + 1) - expected_height * scale) <= 2, (cases[index], result.stdout, scale)


def main():
    executable, helper, reader = (Path(arg).resolve() for arg in sys.argv[1:])
    check_pdf_scale(helper, reader)
    check_legacy_provider(helper)
    check_slow_send(helper)
    with tempfile.TemporaryDirectory(prefix="hplj-duplex-test-") as directory:
        root = Path(directory)
        install_test_firmware(root)
        process, port = start_service(executable, root)
        backend = Backend(helper, port)
        try:
            attrs = run_ipp(f"ipp://127.0.0.1:{port}/ipp/print",
                            Path('/usr/share/cups/ipptool/get-printer-attributes.test'))
            assert "sides-supported (keyword) = one-sided" in attrs, attrs
            query = root / 'workflow.test'
            query.write_text('{\nOPERATION Get-Printer-Attributes\nGROUP operation-attributes-tag\nATTR charset attributes-charset utf-8\nATTR language attributes-natural-language en\nATTR uri printer-uri $uri\nATTR keyword requested-attributes hplj-manual-duplex-workflow\nSTATUS successful-ok\n}\n')
            workflow = run_ipp(f"ipp://127.0.0.1:{port}/ipp/print", query)
            assert "hplj-manual-duplex-workflow (keyword) = experimental-host-guided-pdf" in workflow, workflow
            generation = backend.instance()
            for count, orientation, binding in ((2, 'portrait', 'long-edge'),
                                                (3, 'landscape', 'short-edge'),
                                                (4, 'portrait', 'short-edge'),
                                                (5, 'landscape', 'long-edge')):
                pdf = root / 'input.pdf'
                make_pdf(pdf, count)
                assert int(backend.call('count', pdf)) == count
                order = plan(count, binding, orientation)
                front, back = root / f'front-{count}.pwg', root / f'back-{count}.pwg'
                backend.call('render', pdf, front, orientation, 0, *order.fronts)
                backend.call('render', pdf, back, orientation, order.back_rotation, *order.backs)
                def pixels(path):
                    result = subprocess.run([reader, path], text=True, capture_output=True, check=True)
                    return [tuple(map(int, line.split())) for line in result.stdout.splitlines()]
                # Compare all ordered/rotated pages with independently rendered
                # source pages and pixel-space rotation, including the odd blank.
                for raster, indices, rotation in ((front, order.fronts, 0), (back, order.backs, order.back_rotation)):
                    actual = pixels(raster)
                    for index, page in enumerate(indices):
                        if page == 0:
                            assert actual[index] == (-1, -1, -1, -1)
                            continue
                        single = root / f'single-{count}-{page}.pwg'
                        backend.call('render', pdf, single, orientation, 0, page)
                        expected = pixels(single)[0]
                        if rotation:
                            left, top, right, bottom = expected
                            expected = (4959 - right, 7014 - bottom, 4959 - left, 7014 - top)
                        assert all(abs(a - b) <= 1 for a, b in zip(actual[index], expected)), (actual[index], expected)
                assert front.stat().st_mode & 0o777 == 0o600
                before = (root / 'device').stat().st_size
                def confirm(_):
                    # Front pass complete and no back pass has been created.
                    output = (root / 'device').read_bytes()[before:]
                    assert output.count(b'JZJZ') == len(order.fronts)
                    return True
                messages = []
                run_workflow(backend, front, back, confirm, timeout=15, publish=messages.append)
                output = (root / 'device').read_bytes()[before:]
                assert output.count(b'JZJZ') == 2 * len(order.fronts)
                assert messages[-1].startswith('completed:')
            before = (root / 'device').stat().st_size
            def restart_at_prompt(_):
                nonlocal process
                stop_service(process)
                process, port = start_service(executable, root)
                backend.port = port
                assert backend.instance() != generation
                return True
            messages = []
            try:
                run_workflow(backend, front, back, restart_at_prompt, timeout=15, publish=messages.append)
                raise AssertionError('restart unexpectedly allowed backs')
            except RuntimeError as error:
                assert 'restarted' in str(error)
            assert messages[-1].startswith('incomplete:')
            output = (root / 'device').read_bytes()[before:]
            assert output.count(b'JZJZ') == len(order.fronts), 'restart sent back bytes'
            before = (root / 'device').stat().st_size
            try:
                run_workflow(backend, front, back, lambda _: False, timeout=15, publish=lambda _: None)
                raise AssertionError('cancellation unexpectedly allowed backs')
            except RuntimeError as error:
                assert 'canceled' in str(error)
            output = (root / 'device').read_bytes()[before:]
            assert output.count(b'JZJZ') == len(order.fronts), 'cancellation sent back bytes'
        finally:
            stop_service(process)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
