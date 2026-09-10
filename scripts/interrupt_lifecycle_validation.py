#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Interrupt a real uninstall immediately after removing its product queue."""

from __future__ import annotations

import subprocess

if __package__:
    from scripts import personal_install
else:
    import personal_install  # type: ignore[no-redef]


class IntentionalInterruption(RuntimeError):
    pass


class InterruptAfterQueueRemoval:
    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(command, **kwargs)
        if command == [
            "/usr/bin/sudo",
            "/usr/sbin/lpadmin",
            "-x",
            personal_install.QUEUE,
        ]:
            raise IntentionalInterruption("uninstall interrupted after queue removal")
        return result


def main() -> int:
    try:
        personal_install.main(
            ["uninstall", "--apply", "--yes"],
            runner=InterruptAfterQueueRemoval(),
        )
    except IntentionalInterruption as error:
        print(error)
        return 130
    print("uninstall reached completion before the interruption point")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
