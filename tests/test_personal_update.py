# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise real filesystem transactions with a simulated macOS service."""

from __future__ import annotations

import io
import fcntl
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import personal_install as install
from scripts import personal_update as update


class PowerLoss(BaseException):
    pass


class Runtime:
    def __init__(self, root):
        self.root = root
        self.running = True
        self.accepting = True
        self.busy = False
        self.calls = []
        self.failure = None
        self.started = []

    def event(self, name):
        self.calls.append(name)
        if self.failure == name:
            self.failure = None
            raise install.InstallError(name)

    def preflight(self):
        self.event("preflight")
        if self.busy:
            raise install.InstallError("active job")

    def close_admission(self):
        self.accepting = False
        self.event("close-admission")

    def stop(self):
        self.event("stop")
        self.running = False

    def start(self):
        self.event("start")
        app = (self.root / update.PAYLOAD / "binary").read_text()
        state = (self.root / "state/system.state").read_text()
        self.started.append((app, state))
        self.running = True

    def health(self):
        self.event("health")

    def release(self):
        self.event("release")
        self.accepting = True

    def copy(self, source, destination):
        self.event("copy")
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)

    def validate(self, app):
        self.event("validate")
        if (app / "binary").read_text() != "new":
            raise install.InstallError("bad payload")

    def backup_queue(self, destination):
        update.durable_json(destination / "queue.json", {"options": "media=A4", "enabled": True})


class Transactions(unittest.TestCase):
    def fixture(self, base):
        root = base / "installed"
        root.mkdir()
        app = root / update.PAYLOAD
        app.mkdir()
        (app / "binary").write_text("old")
        for name in update.DATA:
            (root / name).mkdir(mode=0o700)
        (root / "state/system.state").write_text("old-state")
        (root / "config/settings").write_text("user settings")
        (root / "firmware/user.bin").write_bytes(b"private firmware")
        (root / "home/empty").mkdir(mode=0o700)
        plist = base / "service.plist"
        plist.write_text("original plist")
        source = base / "staged"
        (source / "Contents/Library/LaunchDaemons").mkdir(parents=True)
        (source / "Contents/Library/LaunchDaemons" / f"{install.SERVICE_LABEL}.plist").write_text("new plist")
        (source / "binary").write_text("new")
        runtime = Runtime(root)
        return update.Transaction(root, plist, runtime), runtime, source

    def assert_old(self, transaction, runtime):
        self.assertEqual((transaction.root / update.PAYLOAD / "binary").read_text(), "old")
        self.assertEqual((transaction.root / "state/system.state").read_text(), "old-state")
        self.assertEqual((transaction.root / "config/settings").read_text(), "user settings")
        self.assertFalse((transaction.root / "config/state-version.json").exists())
        self.assertEqual(transaction.plist.read_text(), "original plist")
        self.assertEqual((transaction.root / "firmware/user.bin").read_bytes(), b"private firmware")
        self.assertTrue(runtime.running)
        self.assertTrue(runtime.accepting)
        self.assertFalse(transaction.journal.exists())
        self.assertNotIn(("old", "new-state"), runtime.started)

    def test_update_retains_exact_prior_and_current_payload_and_state(self):
        with tempfile.TemporaryDirectory() as directory:
            txn, runtime, source = self.fixture(Path(directory))
            txn.execute(source, {"tag": "v1.0.0", "commit": "a" * 40})
            pointer = json.loads((txn.store / "previous.json").read_text())
            snapshot = txn.run_path(pointer["run"]) / "before"
            txn.verify(snapshot)
            self.assertEqual((snapshot / update.PAYLOAD / "binary").read_text(), "old")
            self.assertEqual((txn.root / update.PAYLOAD / "binary").read_text(), "new")
            self.assertEqual(json.loads((txn.root / "config/state-version.json").read_text()), {"version": 1})
            self.assertTrue(runtime.accepting)
            self.assertLess(runtime.calls.index("validate"), runtime.calls.index("close-admission"))
            self.assertLess(runtime.calls.index("health"), runtime.calls.index("release"))
            shutil.rmtree(source)  # rollback has no source or build dependency
            txn.execute(None, {})
            self.assert_old(txn, runtime)
            # Rolling back the rollback restores its exact payload/state too.
            txn.execute(None, {})
            self.assertEqual((txn.root / update.PAYLOAD / "binary").read_text(), "new")

    def test_busy_installation_is_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            txn, runtime, source = self.fixture(Path(directory))
            runtime.busy = True
            with self.assertRaises(install.InstallError):
                txn.execute(source, {})
            self.assertEqual(runtime.calls, ["preflight"])
            self.assert_old(txn, runtime)

    def test_every_forward_boundary_recovers_after_power_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            txn, _, source = self.fixture(Path(directory))
            phases = []
            txn.checkpoint = phases.append
            txn.execute(source, {})
        for index, phase in enumerate(phases):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                txn, runtime, source = self.fixture(Path(directory))
                count = 0

                def interrupt(observed):
                    nonlocal count
                    current = count
                    count += 1
                    if current == index:
                        raise PowerLoss(observed)

                txn.checkpoint = interrupt
                with self.assertRaises(PowerLoss):
                    txn.execute(source, {})
                txn.checkpoint = lambda _: None
                self.assertTrue(txn.recover())
                if phase in {"committed", "released"}:
                    self.assertEqual((txn.root / update.PAYLOAD / "binary").read_text(), "new")
                    self.assertFalse(txn.journal.exists())
                else:
                    self.assert_old(txn, runtime)

    def test_every_failure_boundary_rolls_back_before_commit(self):
        phases = ("preparing", "admission", "stopping", "snapshot-state", "backed-up",
                  "replace-HP-LJ-1020.app-parked", "payload-replaced", "migrating",
                  "migration-0-1-before", "migration-0-1-after", "migrated", "starting", "healthy")
        for phase in phases:
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                txn, runtime, source = self.fixture(Path(directory))
                fired = False

                def fail(observed):
                    nonlocal fired
                    if observed == phase and not fired:
                        fired = True
                        raise OSError("injected " + observed)

                txn.checkpoint = fail
                with self.assertRaises(OSError):
                    txn.execute(source, {})
                self.assert_old(txn, runtime)

    def test_every_restore_boundary_can_be_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            txn, _, source = self.fixture(Path(directory))
            txn.execute(source, {})
            phases = []
            txn.checkpoint = phases.append
            txn.execute(None, {})
        for index, phase in enumerate(phases):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                txn, runtime, source = self.fixture(Path(directory))
                txn.execute(source, {})
                # Make the newer compatible state distinguishable from backup.
                (txn.root / "state/system.state").write_text("new-state")
                count = 0

                def interrupt(observed):
                    nonlocal count
                    current = count
                    count += 1
                    if current == index:
                        raise PowerLoss(observed)

                txn.checkpoint = interrupt
                with self.assertRaises(PowerLoss):
                    txn.execute(None, {})
                txn.checkpoint = lambda _: None
                txn.recover()
                expected = "old" if phase in {"committed", "released"} else "new"
                self.assertEqual((txn.root / update.PAYLOAD / "binary").read_text(), expected)
                self.assertNotIn(("old", "new-state"), runtime.started)
                self.assertFalse(txn.journal.exists())

    def test_host_failures_recover_and_corrupt_retained_payload_fails_closed(self):
        for failure in ("copy", "validate", "close-admission", "stop", "start", "health", "release"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                txn, runtime, source = self.fixture(Path(directory))
                runtime.failure = failure
                with self.assertRaises(install.InstallError):
                    txn.execute(source, {})
                if failure != "release":
                    self.assert_old(txn, runtime)
                else:
                    self.assertEqual((txn.root / update.PAYLOAD / "binary").read_text(), "new")
        with tempfile.TemporaryDirectory() as directory:
            txn, runtime, source = self.fixture(Path(directory))
            txn.execute(source, {})
            pointer = json.loads((txn.store / "previous.json").read_text())
            (txn.run_path(pointer["run"]) / "before" / update.PAYLOAD / "binary").write_text("tampered")
            runtime.calls.clear()
            with self.assertRaises(install.InstallError):
                txn.execute(None, {})
            self.assertEqual(runtime.calls, ["preflight"])
            self.assertEqual((txn.root / update.PAYLOAD / "binary").read_text(), "new")

    def test_failed_automatic_restore_keeps_journal_and_service_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            txn, runtime, source = self.fixture(Path(directory))
            runtime.failure = "health"

            def fail_restore(phase):
                if phase == "restore-state":
                    raise OSError("restore unavailable")

            txn.checkpoint = fail_restore
            with self.assertRaisesRegex(install.InstallError, "rollback incomplete"):
                txn.execute(source, {})
            self.assertTrue(txn.journal.exists())
            self.assertFalse(runtime.running)
            txn.checkpoint = lambda _: None
            txn.recover()
            self.assert_old(txn, runtime)

    def test_automatic_restore_survives_interruption_at_every_boundary(self):
        def interrupt_activation(txn, source):
            def stop_at_start(phase):
                if phase == "starting":
                    raise PowerLoss(phase)

            txn.checkpoint = stop_at_start
            with self.assertRaises(PowerLoss):
                txn.execute(source, {})

        with tempfile.TemporaryDirectory() as directory:
            txn, _, source = self.fixture(Path(directory))
            interrupt_activation(txn, source)
            phases = []
            txn.checkpoint = phases.append
            txn.recover()
        for index, phase in enumerate(phases):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                txn, runtime, source = self.fixture(Path(directory))
                interrupt_activation(txn, source)
                count = 0

                def interrupt(observed):
                    nonlocal count
                    current = count
                    count += 1
                    if current == index:
                        raise PowerLoss(observed)

                txn.checkpoint = interrupt
                with self.assertRaises(PowerLoss):
                    txn.recover()
                txn.checkpoint = lambda _: None
                runtime.calls.clear()
                txn.recover()
                self.assert_old(txn, runtime)
                if phase in {"committed", "recovery-released"}:
                    self.assertNotIn("stop", runtime.calls)

    def test_migration_is_idempotent_and_future_state_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            txn, runtime, source = self.fixture(Path(directory))
            txn.migrate()
            first = update.inventory(txn.root / "config")
            txn.migrate()
            self.assertEqual(first, update.inventory(txn.root / "config"))
            version = txn.root / "config/state-version.json"
            version.write_text('{"version": 99}')
            with self.assertRaises(install.InstallError):
                txn.execute(source, {})
            self.assertEqual(json.loads(version.read_text()), {"version": 99})
            self.assertEqual((txn.root / update.PAYLOAD / "binary").read_text(), "old")

    def test_failed_resumed_restoration_disables_service_and_retains_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            txn, runtime, source = self.fixture(Path(directory))

            def interrupt(phase):
                if phase == "starting":
                    raise PowerLoss(phase)

            txn.checkpoint = interrupt
            with self.assertRaises(PowerLoss):
                txn.execute(source, {})
            txn.checkpoint = lambda _: None
            runtime.failure = "health"
            with self.assertRaises(install.InstallError):
                txn.execute(None, {})
            self.assertFalse(runtime.running)
            self.assertTrue(txn.journal.exists())
            txn.execute(None, {})
            self.assert_old(txn, runtime)

    def test_links_and_unsafe_transaction_names_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            txn, runtime, source = self.fixture(Path(directory))
            (source / "link").symlink_to(txn.root / "firmware/user.bin")
            with self.assertRaises(install.InstallError):
                txn.execute(source, {})
            self.assert_old(txn, runtime)
            with self.assertRaises(install.InstallError):
                txn.run_path("../../foreign")

    def test_concurrent_transaction_is_refused_without_live_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            txn, runtime, source = self.fixture(Path(directory))
            txn.store.mkdir(mode=0o700)
            with (txn.store / "lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                with self.assertRaises(BlockingIOError):
                    txn.execute(source, {})
            self.assertEqual(runtime.calls, [])
            self.assert_old(txn, runtime)


class Interface(unittest.TestCase):
    def test_update_preview_has_no_commands_and_requires_explicit_tag(self):
        runner = mock.Mock()
        output = io.StringIO()
        self.assertEqual(install.main(["update", "--tag", "v0.1.0"], runner=runner, stdout=output), 0)
        runner.assert_not_called()
        self.assertIn("retain exact payload", output.getvalue())
        with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
            install.main(["update"], runner=runner)

    def test_tag_identity_and_clean_source_are_checked_before_and_after_build(self):
        def runner(command, **kwargs):
            argument = command[-1]
            value = "a" * 40 if argument == "HEAD" or argument.startswith("refs/tags/") else ""
            return subprocess.CompletedProcess(command, 0, value, "")

        host = install.CommandHost(mock.Mock(side_effect=runner))
        with mock.patch.object(install, "stage_and_sign") as stage:
            install.update(host, "v" + install.read_version(install.ROOT))
        stage.assert_called_once_with(host, personal_release=True)
        commands = host.runner.call_args_list
        self.assertEqual(commands[-1].args[0][0], "/usr/bin/sudo")
        self.assertIn("--commit", commands[-1].args[0])
        with mock.patch.object(install, "stage_and_sign") as stage:
            with self.assertRaises(install.InstallError):
                install.update(host, "main")
            stage.assert_not_called()

    def test_dirty_or_moving_source_never_reaches_administrator_activation(self):
        for dirty in (True, False):
            with self.subTest(dirty=dirty):
                commands = []
                staged = False

                def runner(command, **kwargs):
                    commands.append(command)
                    argument = command[-1]
                    if command[0] == "/usr/bin/sudo":
                        self.fail("unverified source reached activation")
                    value = "a" * 40
                    if "--porcelain" in command:
                        value = " M VERSION" if dirty else ""
                    elif staged and argument == "HEAD":
                        value = "b" * 40
                    return subprocess.CompletedProcess(command, 0, value, "")

                def stage(*args, **kwargs):
                    nonlocal staged
                    staged = True

                with mock.patch.object(install, "stage_and_sign", side_effect=stage):
                    with self.assertRaises(install.InstallError):
                        install.update(install.CommandHost(runner), "v" + install.read_version(install.ROOT))

    def test_old_payload_without_a_startup_gate_is_incompatible(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            with self.assertRaisesRegex(install.InstallError, "startup admission"):
                update.MacRuntime.contract(app)
            resource = app / "Contents/Resources/state-schema.json"
            resource.parent.mkdir(parents=True)
            resource.write_text(json.dumps(update.STATE_CONTRACT))
            update.MacRuntime.contract(app)

    def test_runtime_checks_both_job_surfaces_and_closes_both_admission_paths(self):
        commands = []
        tests = []

        def runner(command, **kwargs):
            commands.append(command)
            if command[0] == "/usr/bin/ipptool":
                tests.append(Path(command[-1]).read_text())
            return subprocess.CompletedProcess(command, 0, "", "")

        runtime = update.MacRuntime(install.CommandHost(runner))
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(install, "STATE_ROOT", directory):
            runtime.close_admission()
            self.assertTrue((Path(directory) / "system.state.update-held").exists())
        self.assertEqual(commands[0][1], "/usr/sbin/cupsreject")
        self.assertIn("OPERATION Disable-Printer", tests[0])
        self.assertIn("which-jobs not-completed", tests[1])
        self.assertIn("EXPECT !job-id", tests[1])
        self.assertTrue(any(command[:3] == ["/usr/bin/lpstat", "-W", "not-completed"] for command in commands))


if __name__ == "__main__":
    unittest.main()
