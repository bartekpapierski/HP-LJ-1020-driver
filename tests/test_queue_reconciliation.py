# SPDX-License-Identifier: GPL-2.0-or-later
from __future__ import annotations

import subprocess
import unittest

from scripts import reconcile_macos_queue as queue

QUEUE_NAME = "test_queue"
DEVICE_URI = "ipp://127.0.0.1:9999/ipp/print"


class FakeRunner:
    def __init__(self, results: list[subprocess.CompletedProcess[str]]) -> None:
        self.results = results
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        result = self.results.pop(0)
        if result.returncode != 0 and command[0] == queue.LPADMIN:
            raise subprocess.CalledProcessError(result.returncode, command)
        return result


def result(code: int, output: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout=output, stderr="")


class QueueReconciliationTests(unittest.TestCase):
    def test_absent_queue_is_created_once_and_verified(self) -> None:
        fake = FakeRunner([
            result(0), result(0),
            result(0, f"device for {QUEUE_NAME}: {DEVICE_URI}\n"),
        ])
        self.assertEqual(
            queue.reconcile(queue_name=QUEUE_NAME, device_uri=DEVICE_URI,
                            apply=True, runner=fake),
            "reconciled",
        )
        self.assertEqual(
            fake.commands[1],
            [queue.LPADMIN, "-p", QUEUE_NAME, "-v", DEVICE_URI,
             "-m", "everywhere", "-E"],
        )

    def test_matching_queue_is_reapplied_to_converge_model_and_enabled_state(self) -> None:
        existing = f"device for {QUEUE_NAME}: {DEVICE_URI}\n"
        fake = FakeRunner([result(0, existing), result(0), result(0, existing)])
        self.assertEqual(
            queue.reconcile(queue_name=QUEUE_NAME, device_uri=DEVICE_URI,
                            apply=True, runner=fake),
            "reconciled",
        )
        self.assertEqual(len(fake.commands), 3)

    def test_foreign_collision_is_never_modified(self) -> None:
        fake = FakeRunner([
            result(0, f"device for {QUEUE_NAME}: usb://unrelated/printer\n")
        ])
        with self.assertRaisesRegex(RuntimeError, "foreign queue collision"):
            queue.reconcile(queue_name=QUEUE_NAME, device_uri=DEVICE_URI,
                            apply=True, runner=fake)
        self.assertEqual(len(fake.commands), 1)


if __name__ == "__main__":
    unittest.main()
