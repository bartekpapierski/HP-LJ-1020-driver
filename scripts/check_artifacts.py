#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Reject firmware and binary-object leakage from build artifacts."""

from __future__ import annotations

import argparse
import hashlib
import re
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO


FORBIDDEN_NAMES = {"firmware", "sihp1020.dl", "hp_laserjet_1020.fw"}
FORBIDDEN_SUFFIXES = {".dl", ".firmware", ".fw", ".img"}
SHA256 = re.compile(r"^[a-f0-9]{64}$")


class ArtifactError(ValueError):
    pass


def name_is_forbidden(name: str) -> bool:
    path = PurePosixPath(name)
    lowered_parts = [part.lower() for part in path.parts]
    return (
        any(part in FORBIDDEN_NAMES for part in lowered_parts)
        or path.suffix.lower() in FORBIDDEN_SUFFIXES
    )


def stream_sha256(source: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := source.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def file_sha256(path: Path) -> str:
    with path.open("rb") as source:
        return stream_sha256(source)


def archive_contains_forbidden(path: Path, forbidden_digests: set[str]) -> bool:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                if name_is_forbidden(member.filename):
                    return True
                with archive.open(member) as source:
                    if stream_sha256(source) in forbidden_digests:
                        return True
    if tarfile.is_tarfile(path):
        with tarfile.open(path) as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                if name_is_forbidden(member.name):
                    return True
                source = archive.extractfile(member)
                if source is not None and stream_sha256(source) in forbidden_digests:
                    return True
    return False


def check_artifacts(root: Path, forbidden_digests: set[str] | None = None) -> None:
    digests = forbidden_digests or set()
    offending = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and (
            name_is_forbidden(path.relative_to(root).as_posix())
            or file_sha256(path) in digests
            or archive_contains_forbidden(path, digests)
        )
    ]
    if offending:
        raise ArtifactError(
            "forbidden artifact content: " + ", ".join(str(path) for path in offending)
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("--forbidden-sha256", action="append", default=[])
    arguments = parser.parse_args()
    invalid = [digest for digest in arguments.forbidden_sha256 if not SHA256.fullmatch(digest)]
    if invalid:
        raise SystemExit("invalid forbidden SHA-256")
    root = Path(arguments.directory)
    try:
        check_artifacts(root, set(arguments.forbidden_sha256))
    except ArtifactError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
