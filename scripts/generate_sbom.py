#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Generate a minimal SPDX JSON inventory from the locked dependencies."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    output = Path(parser.parse_args().output)
    lock = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))
    packages = [
        {
            "SPDXID": f"SPDXRef-{dependency['name']}",
            "name": dependency["name"],
            "versionInfo": dependency.get("version", dependency.get("commit")),
            "downloadLocation": dependency["sourceUrl"],
            "checksums": [{"algorithm": "SHA256", "checksumValue": dependency["sha256"]}],
            "licenseConcluded": dependency["licenseExpression"],
            "licenseDeclared": dependency["licenseExpression"],
            "copyrightText": "NOASSERTION",
            "filesAnalyzed": False,
        }
        for dependency in lock["dependencies"]
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "spdxVersion": "SPDX-2.3", "SPDXID": "SPDXRef-DOCUMENT", "name": "hplj1020",
        "dataLicense": "CC0-1.0",
        "documentNamespace": "https://bartekpapierski.github.io/HP-LJ-1020-driver/spdx/" + uuid.uuid4().hex,
        "creationInfo": {"creators": ["Tool: hplj1020-generate-sbom"],
                         "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
        "packages": packages,
        "relationships": [{"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES",
                           "relatedSpdxElement": package["SPDXID"]} for package in packages],
    }
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
