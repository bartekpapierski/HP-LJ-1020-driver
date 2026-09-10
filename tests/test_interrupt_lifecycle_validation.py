# SPDX-License-Identifier: GPL-2.0-or-later
from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from scripts import interrupt_lifecycle_validation as interruption
from scripts import personal_install


class InterruptedLifecycleChecks(unittest.TestCase):
    def test_interrupts_only_after_real_queue_removal_completes(self) -> None:
        command = [
            "/usr/bin/sudo",
            "/usr/sbin/lpadmin",
            "-x",
            personal_install.QUEUE,
        ]
        with mock.patch.object(
            interruption.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(command, 0, "", ""),
        ) as run:
            with self.assertRaisesRegex(
                interruption.IntentionalInterruption,
                "after queue removal",
            ):
                interruption.InterruptAfterQueueRemoval()(command, text=True)

        run.assert_called_once_with(command, text=True)

    def test_non_target_commands_pass_through(self) -> None:
        command = ["/bin/test", "-e", "/tmp/example"]
        expected = subprocess.CompletedProcess(command, 0, "", "")
        with mock.patch.object(interruption.subprocess, "run", return_value=expected):
            result = interruption.InterruptAfterQueueRemoval()(command, text=True)
        self.assertIs(result, expected)


if __name__ == "__main__":
    unittest.main()
