# SPDX-License-Identifier: GPL-2.0-or-later
"""Host workflow simulations: page/sheet identity and fail-closed transitions."""
from pathlib import Path
import unittest
from unittest import mock
import subprocess

from scripts import manual_duplex

from scripts.manual_duplex import Backend, plan, run_workflow


class FakeBackend:
    def __init__(self, states=(9, 9)):
        self.states = list(states)
        self.sent = []
        self.canceled = []
        self.jobs = 0
        self.generation = "first"

    def instance(self):
        return self.generation

    def create(self):
        self.jobs += 1
        return self.jobs

    def send(self, job, path, *, timeout):
        self.sent.append((job, path))
        self.send_timeout = timeout

    def state(self, job):
        return self.states[job - 1]

    def cancel(self, job):
        self.canceled.append(job)


class ManualDuplexTests(unittest.TestCase):
    def execute(self, backend, confirm=lambda timeout: True, **kwargs):
        messages = []
        run_workflow(backend, Path("front"), Path("back"), confirm,
                     timeout=10, publish=messages.append, **kwargs)
        return messages

    def test_helper_failure_preserves_actionable_stderr(self):
        error = subprocess.CalledProcessError(
            1, ["helper", "instance", "8631"], stderr="provider lacks instance attribute; reinstall provider\n")
        with mock.patch.object(manual_duplex.subprocess, "run", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "reinstall provider"):
                Backend(Path("helper"), 8631).instance()

    def test_incompatible_provider_is_rejected_before_pdf_rendering(self):
        with mock.patch.object(manual_duplex.sys.stdin, "isatty", return_value=True), \
             mock.patch.object(Backend, "call", side_effect=RuntimeError("reinstall provider")) as call, \
             mock.patch.object(manual_duplex.sys, "stderr"):
            self.assertEqual(manual_duplex.main(["unused.pdf"]), 1)
        self.assertEqual(call.call_args_list, [mock.call("instance", 8631)])

    def test_send_uses_the_workflow_timeout(self):
        backend = FakeBackend()
        self.execute(backend)
        self.assertEqual(backend.send_timeout, 10)

    def test_send_time_is_included_in_the_pass_deadline(self):
        backend = FakeBackend((5, 9))
        now = [0]
        def slow_send(job, path, *, timeout):
            backend.sent.append((job, path))
            now[0] = 11
        backend.send = slow_send
        def unexpected_sleep(_):
            self.fail("pass deadline was reset after Send-Document")
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            self.execute(backend, clock=lambda: now[0], sleep=unexpected_sleep)
        self.assertEqual(backend.canceled, [1])
        self.assertEqual(len(backend.sent), 1)

    def test_native_send_timeout_matches_subprocess_budget(self):
        backend = Backend(Path("helper"), 8631)
        with mock.patch.object(backend, "call", return_value="") as call:
            backend.send(7, Path("front.pwg"), timeout=600)
        call.assert_called_once_with("send", 8631, 7, Path("front.pwg"), 600, timeout=605)

    def test_every_page_matches_its_sheet_in_reverse_stack_order(self):
        for count in (2, 3, 4, 5, 199, 200):
            for orientation in ("portrait", "landscape"):
                for binding in ("long-edge", "short-edge"):
                    with self.subTest(count=count, orientation=orientation, binding=binding):
                        order = plan(count, binding, orientation)
                        self.assertEqual(order.fronts, tuple(range(1, count + 1, 2)))
                        stack = list(reversed(order.fronts))
                        self.assertEqual(len(stack), len(order.backs))
                        for front, back in zip(stack, order.backs):
                            self.assertEqual(back, front + 1 if front < count else 0)
                        self.assertEqual(sorted(order.fronts + tuple(p for p in order.backs if p)),
                                         list(range(1, count + 1)))
                        self.assertEqual(order.back_rotation,
                                         180 if (binding == "long-edge") == (orientation == "portrait") else 0)

    def test_reject_unsupported_input(self):
        for count in (-1, 0, 1, 201):
            with self.assertRaises(ValueError):
                plan(count, "long-edge", "portrait")

    def test_back_bytes_require_confirmation_after_front_completion(self):
        backend = FakeBackend()
        def confirm(timeout):
            self.assertEqual(backend.sent, [(1, Path("front"))])
            self.assertEqual(backend.state(1), 9)
            return True
        self.assertEqual(self.execute(backend, confirm)[-1], "completed: both passes completed")
        self.assertEqual(backend.sent, [(1, Path("front")), (2, Path("back"))])

    def test_cancel_or_timeout_at_prompt_never_submits_backs(self):
        backend = FakeBackend()
        with self.assertRaisesRegex(RuntimeError, "canceled or timed out"):
            self.execute(backend, lambda timeout: False)
        self.assertEqual(len(backend.sent), 1)

    def test_ipp_cancellation_failure_and_unknown_state_never_complete(self):
        for states in ((7, 9), (8, 9), (0, 9), (9, 7), (9, 8), (9, 0)):
            backend = FakeBackend(states)
            messages = []
            with self.assertRaisesRegex(RuntimeError, "unsuccessful"):
                run_workflow(backend, Path("front"), Path("back"), lambda _: True,
                             timeout=1, publish=messages.append)
            self.assertTrue(messages[-1].startswith("incomplete:"))
            self.assertFalse(any(m.startswith("completed:") for m in messages))
            self.assertEqual(backend.canceled, [backend.jobs])

    def test_timeout_cancels_active_job(self):
        backend = FakeBackend((5, 9))
        times = iter((0, 11))
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            self.execute(backend, clock=lambda: next(times), sleep=lambda _: None)
        self.assertEqual(backend.canceled, [1])
        self.assertEqual(len(backend.sent), 1)

    def test_late_confirmation_does_not_authorize_backs(self):
        backend = FakeBackend()
        times = iter((0, 1, 12))
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            self.execute(backend, clock=lambda: next(times))
        self.assertEqual(len(backend.sent), 1)

    def test_interruption_during_prompt_does_not_resume(self):
        backend = FakeBackend()
        def interrupt(_):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.execute(backend, interrupt)
        self.assertEqual(len(backend.sent), 1)
        # A fresh controller always begins with new fronts and new confirmation.
        self.execute(FakeBackend())

    def test_provider_restart_at_prompt_rejects_even_retained_completed_job(self):
        backend = FakeBackend()
        def restart(_):
            backend.generation = "second"
            return True
        with self.assertRaisesRegex(RuntimeError, "restarted"):
            self.execute(backend, restart)
        self.assertEqual(len(backend.sent), 1)
        self.assertEqual(backend.canceled, [])

    def test_send_error_cancels_known_job_without_retry(self):
        backend = FakeBackend()
        def fail(job, path, *, timeout):
            raise RuntimeError("connection lost")
        backend.send = fail
        with self.assertRaisesRegex(RuntimeError, "connection lost"):
            self.execute(backend)
        self.assertEqual(backend.canceled, [1])
        self.assertEqual(backend.jobs, 1)


if __name__ == "__main__":
    unittest.main()
