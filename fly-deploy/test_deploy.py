"""Run with python -m unittest discover -s fly-deploy -v; requires bash and jq."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parent
MOCK = r"""
import json
import os
from pathlib import Path
import sys

root = Path(os.environ["MOCK_ROOT"])
command = Path(sys.argv[0]).name
args = sys.argv[1:]
with (root / "calls").open("a") as log:
    log.write(json.dumps([command, *args]) + "\n")
state = json.loads((root / "machines").read_text())
failure = os.environ.get("FAILURE", "")
if command == "git":
    print("new")
elif command == "flyctl":
    if args[:2] == ["machine", "list"]:
        print(json.dumps(state))
    elif args[0] == "deploy":
        if os.environ.get("STOPPED_FOR_MIGRATIONS"):
            assert all(m["state"] == "stopped" and m.get("cordoned") for m in state)
        if failure == "migration":
            sys.exit(1)
        for machine in state:
            machine["config"]["env"]["MIGRATIONS_TREE"] = "new"
    elif args[:2] == ["machine", "cordon"]:
        next(m for m in state if m["id"] == args[2])["cordoned"] = True
    elif args[:2] == ["machine", "stop"]:
        assert all(m.get("cordoned") for m in state), "Cordon everyone before stopping"
        assert "--wait-timeout" in args, "Must wait before migrating"
        if failure == "stop":
            sys.exit(1)
        next(m for m in state if m["id"] == args[2])["state"] = "stopped"
    elif args[:2] == ["machine", "start"]:
        if failure == "start":
            sys.exit(1)
        machine = next(m for m in state if m["id"] == args[2])
        machine["state"] = "started"
        machine["checks"] = [{
            "status": "critical" if failure == "health" else "passing",
            "updated_at": "2000-01-01T00:00:00Z" if failure == "stale" else "9999-01-01T00:00:00Z",
        }]
        if failure == "missing":
            machine["checks"] = []
    elif args[:2] == ["machine", "uncordon"]:
        machine = next(m for m in state if m["id"] == args[2])
        assert machine["state"] == "started"
        assert machine["checks"][0]["status"] == "passing"
        machine["cordoned"] = False
    elif args[:2] == ["ips", "list"]:
        print("address v4 shared")
elif command == "curl":
    assert "--fail" in args, "HTTP errors must fail readiness"
elif command == "timeout":
    os.execvp(args[1], args[1:])
(root / "machines").write_text(json.dumps(state))
"""


def machine(name, state="started", tree="old"):
    return {
        "id": name,
        "state": state,
        "config": {"env": {"MIGRATIONS_TREE": tree}, "services": [{"checks": [{}]}]},
        "checks": [],
    }


class DeployTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for command in ("git", "flyctl", "curl", "sleep", "timeout"):
            path = self.root / command
            path.write_text(f"#!{sys.executable}\n{MOCK}")
            path.chmod(0o755)
        (self.root / "env").touch()
        self.env = {
            **os.environ,
            "PATH": f"{self.root}:{os.environ['PATH']}",
            "APP": "test-app",
            "SHA": "candidate",
            "MIGRATIONS": "migrations",
            "GITHUB_ENV": str(self.root / "env"),
            "MOCK_ROOT": str(self.root),
            "FAILURE": "",
            "STOPPED_FOR_MIGRATIONS": "",
        }

    def run_deploy(self, machines, failure=""):
        (self.root / "machines").write_text(json.dumps(machines))
        self.env["FAILURE"] = failure
        for script in ("stop-for-migrations.sh", "deploy.sh"):
            result = subprocess.run(
                ["bash", str(SCRIPTS / script)],
                env=self.env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode:
                return result
            self.env.update(
                line.split("=", 1)
                for line in (self.root / "env").read_text().splitlines()
            )
        return result

    def calls(self, *prefix):
        return [
            call
            for line in (self.root / "calls").read_text().splitlines()
            if (call := json.loads(line))[: len(prefix)] == list(prefix)
        ]

    def test_unchanged_migrations_do_not_stop(self):
        result = self.run_deploy([machine("one", tree="new")])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.calls("flyctl", "machine", "cordon"))
        self.assertFalse(self.calls("flyctl", "machine", "stop"))
        self.assertEqual(len(self.calls("flyctl", "deploy")), 1)

    def test_first_deploy_does_not_stop(self):
        result = self.run_deploy([])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.calls("flyctl", "machine", "cordon"))

    def test_changed_migrations_stop_every_machine_and_restore_after_health(self):
        result = self.run_deploy([machine("one"), machine("two")])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls("flyctl", "machine", "stop")), 2)
        self.assertEqual(len(self.calls("flyctl", "machine", "uncordon")), 2)

    def test_stopped_machine_does_not_abort_shutdown(self):
        result = self.run_deploy([machine("one"), machine("two", state="stopped")])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls("flyctl", "machine", "stop")), 1)
        self.assertEqual(len(self.calls("flyctl", "machine", "start")), 2)

    def test_all_machines_must_match_the_migration_tree(self):
        result = self.run_deploy([machine("one", tree="new"), machine("two")])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls("flyctl", "machine", "stop")), 2)

    def test_missing_tree_requires_maintenance(self):
        result = self.run_deploy([machine("one", tree=None)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls("flyctl", "machine", "stop")), 1)

    def test_stop_failure_prevents_migration(self):
        result = self.run_deploy([machine("one")], failure="stop")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls("flyctl", "deploy"))
        self.assertFalse(self.calls("flyctl", "machine", "uncordon"))

    def test_migration_failure_keeps_maintenance(self):
        result = self.run_deploy([machine("one")], failure="migration")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls("flyctl", "machine", "start"))
        self.assertFalse(self.calls("flyctl", "machine", "uncordon"))

    def test_start_failure_keeps_maintenance(self):
        result = self.run_deploy([machine("one")], failure="start")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls("flyctl", "machine", "uncordon"))

    def test_unhealthy_missing_or_stale_checks_keep_maintenance(self):
        for failure in ("health", "missing", "stale"):
            with self.subTest(failure=failure):
                result = self.run_deploy([machine("one")], failure=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.calls("flyctl", "machine", "uncordon"))


if __name__ == "__main__":
    unittest.main()
