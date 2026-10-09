"""Run the strategy selector with fake CLI commands, without network access."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("strategy.sh")


class StrategyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.log = self.root / "commands"
        self.output = self.root / "output"
        executable = self.root / "mock"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import os, pathlib, shlex, subprocess, sys\n"
            "name = pathlib.Path(sys.argv[0]).name\n"
            'with open(os.environ["COMMAND_LOG"], "a") as f:\n'
            '    f.write(name + " " + " ".join(sys.argv[1:]) + "\\n")\n'
            'if name == "alembic":\n'
            '    print(os.environ.get("HEADS", "new (head)"))\n'
            '    sys.exit(int(os.environ.get("HEADS_STATUS", "0")))\n'
            'if name == "flyctl":\n'
            '    if os.environ.get("SSH_STATUS"): sys.exit(1)\n'
            '    command = sys.argv[sys.argv.index("-C") + 1]\n'
            '    env = {**os.environ, "DATABASE_URL": "remote-database"}\n'
            "    sys.exit(subprocess.run(shlex.split(command), env=env).returncode)\n"
            'if name == "psql":\n'
            '    assert sys.argv[1] == "remote-database", sys.argv\n'
            '    assert sys.argv[-1] == "SELECT version_num FROM public.alembic_version ORDER BY version_num", sys.argv\n'
            '    print(os.environ.get("CURRENT", "new"))\n'
            '    sys.exit(int(os.environ.get("DB_STATUS", "0")))\n'
        )
        executable.chmod(0o755)
        for name in ("alembic", "flyctl", "psql"):
            (self.root / name).symlink_to(executable)
        self.env = {
            **os.environ,
            "PATH": f"{self.root}:{os.environ['PATH']}",
            "COMMAND_LOG": str(self.log),
            "GITHUB_OUTPUT": str(self.output),
            "APP": "test-app",
            "STRATEGY": "auto",
            "ALEMBIC_CONFIG": "config with spaces.ini",
            "DATABASE_URL": "runner-database-must-not-be-used",
        }

    def select(self, **env):
        return subprocess.run(
            ["bash", str(SCRIPT)],
            env={**self.env, **env},
            capture_output=True,
            text=True,
        )

    def test_matching_database_rolls(self):
        result = self.select()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_text(), "strategy=rolling\n")
        self.assertIn("alembic -c config with spaces.ini heads", self.log.read_text())

    def test_changed_or_unknown_database_stops(self):
        for env in (
            {"CURRENT": "old"},
            {"CURRENT": ""},
            {"SSH_STATUS": "1"},
            {"DB_STATUS": "1"},
        ):
            with self.subTest(env=env):
                self.output.unlink(missing_ok=True)
                result = self.select(**env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.output.read_text(), "strategy=stop\n")

    def test_multiple_heads_are_sorted(self):
        result = self.select(HEADS="b (head)\na (head)", CURRENT="a\nb")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_text(), "strategy=rolling\n")

    def test_explicit_strategies_skip_database_checks(self):
        for strategy in ("stop", "rolling"):
            with self.subTest(strategy=strategy):
                self.output.unlink(missing_ok=True)
                result = self.select(STRATEGY=strategy)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.output.read_text(), f"strategy={strategy}\n")
                self.assertFalse(self.log.exists())

    def test_invalid_strategy_fails(self):
        self.assertNotEqual(self.select(STRATEGY="typo").returncode, 0)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.log.exists())

    def test_invalid_local_config_fails_before_ssh(self):
        self.assertNotEqual(self.select(HEADS_STATUS="1").returncode, 0)
        self.assertFalse(self.output.exists())
        self.assertNotIn("flyctl", self.log.read_text())


if __name__ == "__main__":
    unittest.main()
