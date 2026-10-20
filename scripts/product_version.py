# SPDX-License-Identifier: GPL-2.0-or-later
"""The tracked pre-1.0 product version, shared by build and release operations."""

import re
from pathlib import Path


def read_version(root: Path) -> str:
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"0\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version):
        raise ValueError("VERSION must be a pre-1.0 SemVer (0.x.y)")
    return version
