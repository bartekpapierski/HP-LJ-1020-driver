#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check the stable, synthetic print corpus and its content identities."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


SHA256 = re.compile(r"^[a-f0-9]{64}$")
REQUIRED_COVERAGE = {
    "text",
    "vectors",
    "raster-images",
    "margins",
    "multi-page-output",
    "media-controls",
    "quality-modes",
    "manual-duplex",
}
ALLOWED_SOURCE_SUFFIXES = {".svg", ".pgm"}


class CorpusError(ValueError):
    pass


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _nonempty_object_list(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or any(not isinstance(row, dict) for row in value):
        raise CorpusError(f"{name} must be a non-empty array of objects")
    return value


def check_corpus(root: Path) -> None:
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CorpusError(f"invalid corpus manifest: {error}") from error
    if manifest.get("schemaVersion") != "1.0.0" or manifest.get("corpusVersion") != 1:
        raise CorpusError("unsupported golden corpus version")
    if manifest.get("privacySafe") is not True:
        raise CorpusError("golden corpus is not marked privacy-safe")

    coverage: set[str] = set()
    document_ids: set[str] = set()
    for document in _nonempty_object_list(manifest.get("documents"), "documents"):
        document_id = document.get("documentId")
        if not isinstance(document_id, str) or not document_id or document_id in document_ids:
            raise CorpusError("missing or duplicate documentId")
        document_ids.add(document_id)
        if document.get("containsPrivateContent") is not False:
            raise CorpusError(f"{document_id} is not privacy-safe")
        document_coverage = document.get("coverage")
        if not isinstance(document_coverage, list) or any(
            item not in REQUIRED_COVERAGE for item in document_coverage
        ):
            raise CorpusError(f"{document_id} has invalid coverage")
        coverage.update(document_coverage)
        pages = document.get("pages")
        if not isinstance(pages, list) or not pages:
            raise CorpusError(f"{document_id} has no pages")
        numbers: list[int] = []
        for page in pages:
            if not isinstance(page, dict):
                raise CorpusError(f"{document_id} has an invalid page")
            number, path_value, digest = page.get("number"), page.get("path"), page.get("sha256")
            if not isinstance(number, int) or isinstance(number, bool) or number < 1:
                raise CorpusError(f"{document_id} has an invalid page number")
            numbers.append(number)
            if not isinstance(path_value, str):
                raise CorpusError(f"{document_id} has an invalid page path")
            relative = Path(path_value)
            if relative.is_absolute() or ".." in relative.parts or relative.suffix not in ALLOWED_SOURCE_SUFFIXES:
                raise CorpusError(f"{document_id} has an unsafe page path")
            path = root / relative
            if not isinstance(digest, str) or not SHA256.fullmatch(digest):
                raise CorpusError(f"{document_id} has an invalid page checksum")
            if not path.is_file() or _hash(path) != digest:
                raise CorpusError(f"{document_id} page checksum mismatch: {path_value}")
        if numbers != list(range(1, len(numbers) + 1)):
            raise CorpusError(f"{document_id} pages are not sequential")

    qualities: set[str] = set()
    media: set[str] = set()
    duplex = False
    for case in _nonempty_object_list(manifest.get("printCases"), "printCases"):
        if case.get("documentId") not in document_ids:
            raise CorpusError("print case references an unknown document")
        if not isinstance(case.get("caseId"), str) or not case["caseId"]:
            raise CorpusError("print case has no caseId")
        if not isinstance(case.get("media"), str) or not case["media"]:
            raise CorpusError(f"{case['caseId']} has no media control")
        if case.get("quality") not in {"600x600", "1200x600"}:
            raise CorpusError(f"{case['caseId']} has an invalid quality mode")
        if not isinstance(case.get("manualDuplex"), bool):
            raise CorpusError(f"{case['caseId']} has no manual-duplex setting")
        qualities.add(case["quality"])
        media.add(case["media"])
        duplex = duplex or case["manualDuplex"]
    if qualities != {"600x600", "1200x600"} or len(media) < 2 or not duplex:
        raise CorpusError("print cases do not exercise quality, media, and manual duplex controls")
    if coverage != REQUIRED_COVERAGE:
        missing = REQUIRED_COVERAGE - coverage
        raise CorpusError(f"golden corpus lacks coverage: {', '.join(sorted(missing))}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "corpus", nargs="?", type=Path,
        default=Path(__file__).resolve().parents[1] / "validation/golden-corpus",
    )
    args = parser.parse_args(argv)
    try:
        check_corpus(args.corpus)
    except CorpusError as error:
        print(f"golden corpus rejected: {error}", file=sys.stderr)
        return 1
    print("golden corpus verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
