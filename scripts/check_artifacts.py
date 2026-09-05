#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Reject firmware and binary-object leakage from build artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path


FORBIDDEN = ("firmware", "sihp", ".dl", ".img", ".fw")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    root = Path(parser.parse_args().directory)
    offending = [path for path in root.rglob("*") if any(word in path.name.lower() for word in FORBIDDEN)]
    if offending:
        raise SystemExit("forbidden artifact content: " + ", ".join(str(path) for path in offending))


if __name__ == "__main__":
    main()
