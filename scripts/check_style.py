#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Apply the repository's dependency-free formatting and linting policy."""

from __future__ import annotations

import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".c", ".h", ".json", ".py", ".yml"}


def main() -> None:
    failures: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in {".git", "build", ".cache", "__pycache__"} for part in path.parts):
            continue
        if path.suffix not in TEXT_SUFFIXES and path.name not in {"CMakeLists.txt", "build"}:
            continue
        content = path.read_text(encoding="utf-8")
        if not content.endswith("\n") or any(line.rstrip() != line for line in content.splitlines()):
            failures.append(f"format: {path.relative_to(ROOT)}")
        if path.suffix == ".py" or path.name == "build":
            try:
                py_compile.compile(str(path), doraise=True)
            except py_compile.PyCompileError as error:
                failures.append(f"lint: {error}")
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
