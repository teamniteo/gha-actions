"""Exercise deployment recovery with a fake Fly CLI."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("start.sh")


class StartTests(unittest.TestCase):
    def recover(self, failure="", transient=False, cron_state="stopped"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cli = root / "flyctl"
            cli.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ["MOCK_ROOT"])
args = sys.argv[1:]
with (root / "commands").open("a") as log:
    log.write(" ".join(args) + "\\n")
if args[:2] == ["machine", "list"]:
    print(json.dumps([
        {"id": "web", "state": "stopped", "config": {"metadata": {"fly_process_group": "web"}}},
        {"id": "cron", "state": os.environ["CRON_STATE"], "config": {"metadata": {"fly_process_group": "cron"}}},
        {"id": "release", "config": {"metadata": {"fly_process_group": "fly_app_release_command"}}},
    ]))
elif " ".join(args[:3]) == os.environ["FAILURE"]:
    marker = root / "failed"
    first = not marker.exists()
    marker.touch()
    if first or not os.environ["TRANSIENT"]:
        sys.exit(1)
''')
            cli.chmod(0o755)
            sleep = root / "sleep"
            sleep.write_text("#!/bin/sh\nexit 0\n")
            sleep.chmod(0o755)
            result = subprocess.run(
                ["bash", str(SCRIPT)],
                env={**os.environ, "PATH": f"{root}:{os.environ['PATH']}",
                     "APP": "test", "MOCK_ROOT": str(root), "CRON_STATE": cron_state,
                     "FAILURE": failure, "TRANSIENT": "1" if transient else ""},
                capture_output=True, text=True,
            )
            return result, (root / "commands").read_text().splitlines()

    def test_success_excludes_release_machine(self):
        result, commands = self.recover()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any("release" in command for command in commands))
        self.assertIn("machine uncordon cron -a test", commands)

    def test_already_started_machine_is_not_started_again(self):
        result, commands = self.recover(cron_state="started")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("machine start cron -a test", commands)
        self.assertIn("machine uncordon cron -a test", commands)

    def test_capacity_failure_does_not_block_cron(self):
        result, commands = self.recover("machine start web")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(commands.count("machine start web -a test"), 3)
        self.assertEqual(commands.count("machine start cron -a test"), 1)
        self.assertLess(commands.index("machine uncordon cron -a test"),
                        len(commands) - 1)
        self.assertNotIn("machine uncordon web -a test", commands)

    def test_transient_failures_recover(self):
        for operation in ("start", "wait", "uncordon"):
            with self.subTest(operation=operation):
                result, commands = self.recover(f"machine {operation} web", True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(commands.count("machine start web -a test"),
                                 1 if operation == "uncordon" else 2)
                self.assertEqual(commands.count("machine start cron -a test"), 1)

    def test_persistent_wait_or_uncordon_failure_is_reported(self):
        for operation in ("wait", "uncordon"):
            with self.subTest(operation=operation):
                result, commands = self.recover(f"machine {operation} web")
                self.assertEqual(result.returncode, 1)
                self.assertIn("machine uncordon cron -a test", commands)


if __name__ == "__main__":
    unittest.main()
