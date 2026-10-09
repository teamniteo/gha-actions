import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "decision", Path(__file__).with_name("decision.py")
)
decision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decision)


class DecisionTest(unittest.TestCase):
    def test_always_run_ignores_all_skip_rules(self):
        self.assertFalse(
            decision.decide(
                {
                    "ALWAYS_RUN": "true",
                    "CACHED_SKIP": "true",
                    "PATH_MATCH": "false",
                    "SCHEDULE_SKIP": "true",
                }
            )[0]
        )

    def test_full_override_wins_over_all_skip_rules(self):
        self.assertEqual(
            decision.decide(
                {
                    "FULL": "true",
                    "CACHED_SKIP": "true",
                    "PATH_MATCH": "false",
                    "SCHEDULE_SKIP": "true",
                }
            )[0],
            False,
        )

    def test_each_skip_rule_explains_its_decision(self):
        for inputs, reason in [
            ({"CACHED_SKIP": "true"}, "Unchanged code"),
            ({"PATH_MATCH": "false"}, "No changed files"),
            ({"SCHEDULE_SKIP": "true", "INTERVAL_DAYS": "7"}, "within 7 days"),
        ]:
            with self.subTest(inputs=inputs):
                skip, explanation = decision.decide(inputs)
                self.assertTrue(skip)
                self.assertIn(reason, explanation)

    def test_run_reason_reports_the_actual_policy(self):
        env = {
            "GITHUB_EVENT_NAME": "pull_request",
            "EVENT_ACTION": "synchronize",
            "PATH_FILTER": "serverless",
            "PATH_MATCH": "true",
            "INTERVAL_DAYS": "0",
        }
        self.assertEqual(
            decision.decide(env),
            (
                False,
                "No reusable successful result; Changed files match filter 'serverless'",
            ),
        )
        env["EVENT_ACTION"] = "opened"
        self.assertEqual(
            decision.decide(env)[1],
            "opened event bypasses result reuse; Changed files match filter 'serverless'",
        )
        env.update(PATH_FILTER="", PATH_MATCH="", INTERVAL_DAYS="7")
        self.assertEqual(
            decision.decide(env)[1],
            "opened event bypasses result reuse; No path filter configured; "
            "No successful execution found within 7 days",
        )
        env.update(GITHUB_EVENT_NAME="push", INTERVAL_DAYS="0")
        self.assertEqual(
            decision.decide(env)[1], "push event bypasses result reuse and path filters"
        )

    def test_empty_or_matching_rules_run(self):
        for inputs in [{}, {"PATH_MATCH": "true"}, {"GITHUB_RUN_ATTEMPT": "2"}]:
            self.assertFalse(decision.decide(inputs)[0])

    def test_cli_logs_and_outputs_reason_and_clears_skipped_marker(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root, "outputs")
            env = {
                **os.environ,
                "GITHUB_OUTPUT": str(output),
                "GITHUB_ENV": str(Path(root, "env")),
                "GITHUB_JOB": "Demo Full",
                "PATH_MATCH": "false",
                "CACHE_KEY": "unused",
            }
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("decision.py"))],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("SKIP Demo Full: No changed files", result.stdout)
            self.assertEqual(Path(root, "env").read_text(), "GHA_SKIP_KEY=\n")
            self.assertIn(
                "skip=true\nkey=\nreason=No changed files", output.read_text()
            )

    def test_cli_run_decision_leaves_skip_absent(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root, "outputs")
            env = {
                **os.environ,
                "GITHUB_OUTPUT": str(output),
                "GITHUB_ENV": str(Path(root, "env")),
                "GITHUB_JOB": "Backend Tests",
                "FULL": "true",
            }
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("decision.py"))],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("RUN Backend Tests: Forced", result.stdout)
            self.assertIn("run=true\n", output.read_text())
            self.assertFalse(
                any(
                    line.startswith("skip=") for line in output.read_text().splitlines()
                )
            )

    def test_original_key_is_shared_with_save(self):
        with tempfile.TemporaryDirectory() as root:
            key = "ci-success-v2-" + "a" * 64
            env = {
                **os.environ,
                "GITHUB_OUTPUT": str(Path(root, "outputs")),
                "GITHUB_ENV": str(Path(root, "env")),
                "GITHUB_JOB": "backend_tests",
                "CACHE_KEY": key,
            }
            subprocess.run(
                [sys.executable, str(Path(__file__).with_name("decision.py"))],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(Path(root, "env").read_text(), f"GHA_SKIP_KEY={key}\n")
