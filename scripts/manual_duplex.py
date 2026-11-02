#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Guided, experimental PDF manual duplex through the local simplex provider."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Plan:
    fronts: tuple[int, ...]
    backs: tuple[int, ...]  # Zero is an intentional blank, consuming the odd sheet.
    back_rotation: int


def plan(pages: int, binding: str, orientation: str) -> Plan:
    if not 2 <= pages <= 200:
        raise ValueError("manual duplex requires 2..200 PDF pages (at most 100 sheets)")
    if binding not in {"long-edge", "short-edge"} or orientation not in {"portrait", "landscape"}:
        raise ValueError("invalid binding or orientation")
    fronts = tuple(range(1, pages + 1, 2))
    backs = tuple(page + 1 if page < pages else 0 for page in reversed(fronts))
    # Bottom edge of the physical sheet feeds first on reinsertion. Matches
    # pinned foo2zjs MANUALLONG rotation; landscape swaps the binding axes.
    rotate = (binding == "long-edge") != (orientation == "landscape")
    return Plan(fronts, backs, 180 if rotate else 0)


class Backend:
    def __init__(self, helper: Path, port: int):
        self.helper = helper
        self.port = port

    def call(self, *args: object, timeout: float = 120) -> str:
        try:
            result = subprocess.run([str(self.helper), *(str(arg) for arg in args)],
                                    text=True, capture_output=True, timeout=timeout, check=True)
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or "").strip() or f"exit status {error.returncode}"
            raise RuntimeError(f"duplex helper {args[0]} failed: {detail}") from error
        return result.stdout.strip()

    def instance(self) -> str:
        return self.call("instance", self.port)

    def create(self) -> int:
        job = int(self.call("create", self.port))
        if job <= 0:
            raise RuntimeError("provider did not return a job ID")
        return job

    def send(self, job: int, raster: Path, *, timeout: float) -> None:
        # PAPPL processes raster output before replying to Send-Document.
        # Let the native client use the pass budget; keep a bounded outer
        # watchdog with enough grace to receive its timeout diagnostic.
        self.call("send", self.port, job, raster, timeout, timeout=timeout + 5)

    def state(self, job: int) -> int:
        return int(self.call("state", self.port, job))

    def cancel(self, job: int) -> None:
        self.call("cancel", self.port, job)


def run_workflow(backend, front: Path, back: Path, confirm, *, timeout: float,
                 clock=time.monotonic, sleep=time.sleep, publish=print) -> None:
    """No checkpoint/replay: every new invocation starts a fresh front pass."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    active = None
    instance = backend.instance()

    def check_instance():
        if backend.instance() != instance:
            raise RuntimeError("provider restarted; start again with fresh paper")

    try:
        for name, raster in (("fronts", front), ("backs", back)):
            if name == "backs":
                publish("waiting-for-reinsertion")
                confirmation_deadline = clock() + timeout
                if not confirm(timeout) or clock() >= confirmation_deadline:
                    raise RuntimeError("reinsertion canceled or timed out")
                # Reject a missing, canceled, or changed front job after the wait.
                check_instance()
                if backend.state(active) != 9:
                    raise RuntimeError("front job no longer completed; start again with fresh paper")
            publish(f"printing-{name}")
            check_instance()
            active = backend.create()  # Obtain an ID before any document transmission.
            check_instance()
            deadline = clock() + timeout
            backend.send(active, raster, timeout=timeout)
            while True:
                check_instance()
                state = backend.state(active)
                if state == 9:
                    break
                if state not in {3, 4, 5, 6}:
                    raise RuntimeError(f"{name} job unsuccessful (IPP state {state})")
                if clock() >= deadline:
                    raise RuntimeError(f"{name} job timed out")
                sleep(0.25)
        publish("completed: both passes completed")
    except BaseException:
        if active is not None:
            try:
                if backend.instance() == instance:
                    backend.cancel(active)
                else:
                    publish(f"prior service stopped; job {active} was not replayed or canceled in the new service")
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                publish(f"could not confirm cancellation of job {active}: {error}")
        publish("incomplete: remove partial sheets; do not replay either pass; start again with fresh paper")
        raise


def confirmation(timeout: float) -> bool:
    print("Remove unused paper from the main tray. Keep the entire output stack in order; "
          "do not remove the odd final sheet. Reinsert printed sides DOWN, physical bottom "
          "edges feeding FIRST. Use the main tray and leave the priority slot empty.\n"
          "Inspect that all fronts printed correctly. Type REINSERTED to print backs; "
          "anything else cancels.", flush=True)
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    return bool(ready) and sys.stdin.readline().strip() == "REINSERTED"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--binding", choices=("long-edge", "short-edge"), default="long-edge")
    parser.add_argument("--orientation", choices=("portrait", "landscape"), default="portrait")
    parser.add_argument("--timeout", type=float, default=600,
                        help="seconds per pass and for reinsertion (default: 600)")
    parser.add_argument("--helper", type=Path, default=ROOT / "build/hplj1020-duplex-helper")
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be finite and positive")
    if not sys.stdin.isatty():
        parser.error("an interactive terminal is required for explicit reinsertion confirmation")
    backend = Backend(args.helper.resolve(), 8631)
    try:
        # Detect an older installed provider before reading or rendering the PDF.
        backend.instance()
        with tempfile.TemporaryDirectory(prefix="hplj-duplex-") as directory:
            root = Path(directory)
            pdf = root / "input.pdf"
            shutil.copyfile(args.pdf, pdf)
            pdf.chmod(0o600)
            pages = int(backend.call("count", pdf))
            order = plan(pages, args.binding, args.orientation)
            print(f"Experimental A4/plain-paper workflow: {pages} pages, {len(order.fronts)} sheets, "
                  f"{args.orientation}, {args.binding}. Keep other print jobs out of this printer "
                  "until both passes finish. Prepare fresh paper in the main tray.")
            front, back = root / "front.pwg", root / "back.pwg"
            for path, indices, rotation in ((front, order.fronts, 0), (back, order.backs, order.back_rotation)):
                backend.call("render", pdf, path, args.orientation, rotation, *indices)
            run_workflow(backend, front, back, confirmation, timeout=args.timeout)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        print(f"Manual duplex unsuccessful: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
