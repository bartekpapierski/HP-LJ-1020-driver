#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Create the one product-owned macOS queue without touching other queues."""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Callable, Sequence

LPSTAT = "/usr/bin/lpstat"
LPADMIN = "/usr/sbin/lpadmin"
Runner = Callable[..., subprocess.CompletedProcess[str]]


def reconcile(*, queue_name: str, device_uri: str, apply: bool,
              runner: Runner = subprocess.run) -> str:
    query = runner([LPSTAT, "-v"], text=True,
                   capture_output=True, check=False)
    if query.returncode != 0:
        raise RuntimeError(f"could not inspect CUPS queues: {query.stderr.strip()}")
    prefix = f"device for {queue_name}: "
    matches = [line for line in query.stdout.splitlines() if line.startswith(prefix)]
    if matches:
        expected = f"{prefix}{device_uri}"
        if matches != [expected]:
            raise RuntimeError(
                f"refusing foreign queue collision for {queue_name}: "
                f"{matches[0]}"
            )
        if not apply:
            return f"would verify {queue_name} as enabled IPP Everywhere"
    if not apply:
        return f"would create {queue_name} -> {device_uri} using IPP Everywhere"
    runner([LPADMIN, "-p", queue_name, "-v", device_uri, "-m", "everywhere", "-E"],
           text=True, check=True)
    verify = runner([LPSTAT, "-v"], text=True,
                    capture_output=True, check=True)
    expected = f"device for {queue_name}: {device_uri}"
    if expected not in verify.stdout.splitlines():
        raise RuntimeError("queue creation did not converge to the requested device URI")
    return "reconciled"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-name", required=True,
                        help="canonical runtime queue name")
    parser.add_argument("--device-uri", required=True,
                        help="canonical runtime IPP endpoint")
    parser.add_argument("--apply", action="store_true",
                        help="create the queue when it is absent")
    args = parser.parse_args(argv)
    try:
        print(reconcile(queue_name=args.queue_name, device_uri=args.device_uri,
                        apply=args.apply))
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"queue reconciliation failed: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
