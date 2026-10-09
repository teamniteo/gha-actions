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
            ({"SCHEDULE_SKIP": "true"}, "configured interval"),
        ]:
            with self.subTest(inputs=inputs):
                skip, explanation = decision.decide(inputs)
                self.assertTrue(skip)
                self.assertIn(reason, explanation)

    def test_empty_or_matching_rules_run(self):
        for inputs in [{}, {"PATH_MATCH": "true"}, {"GITHUB_RUN_ATTEMPT": "2"}]:
            self.assertFalse(decision.decide(inputs)[0])

    def test_cli_logs_and_outputs_reason_and_clears_skipped_marker(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root, "outputs")
            env = {
                **os.environ,
                "GITHUB_OUTPUT": str(output),
                "CHECK_NAME": "Demo Full",
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
            self.assertIn(
                "skip=true\nkey=\nreason=No changed files", output.read_text()
            )
