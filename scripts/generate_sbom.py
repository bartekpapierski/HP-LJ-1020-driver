#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Generate a minimal SPDX JSON inventory from the locked dependencies."""

from __future__ import annotations

import argparse
import json
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
        }
        for dependency in lock["dependencies"]
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"spdxVersion": "SPDX-2.3", "SPDXID": "SPDXRef-DOCUMENT", "name": "hplj1020", "dataLicense": "CC0-1.0", "packages": packages}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
