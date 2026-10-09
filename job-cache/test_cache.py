import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "check", Path(__file__).with_name("cache.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReuseChecksTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.event = {
            "action": "synchronize",
            "pull_request": {"number": 42, "base": {"sha": "base"}},
        }
        self.environment = {
            "GITHUB_EVENT_PATH": str(self.root / "event.json"),
            "GITHUB_EVENT_NAME": "pull_request",
            "RUNNER_TEMP": str(self.root),
            "GITHUB_WORKSPACE": str(self.root),
            "HOST_CACHE_DIR": str(self.root / "host"),
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_RUN_ID": "20",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_WORKFLOW_REF": "owner/repo/.github/workflows/ci.yml@refs/pull/42/merge",
            "CHECK_NAME": "Browser Tests (1/3)",
        }
        self.patch = patch.dict(os.environ, self.environment)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.tree = "tree"

    def evaluate(
        self,
        *,
        conclusion="success",
        name="Browser Tests (1/3)",
        expired=False,
        run_id=10,
        error=None,
    ):
        Path(os.environ["GITHUB_EVENT_PATH"]).write_text(json.dumps(self.event))
        responses = [
            {
                "artifacts": [
                    {
                        "expired": expired,
                        "workflow_run": {"id": run_id, "head_sha": "a" * 40},
                    }
                ]
            },
            {"jobs": [{"name": name, "conclusion": conclusion}]},
        ]
        with (
            patch.object(module.subprocess, "check_output", return_value=self.tree),
            patch.object(module, "api", side_effect=error or responses) as api,
        ):
            return module.check(), api.call_args_list

    def test_github_fallback_populates_host_cache(self):
        (skip, key, source), calls = self.evaluate()
        self.assertTrue(skip)
        self.assertEqual(source, {"run-id": "10", "head-sha": "a" * 40})
        self.assertEqual(len(calls), 2)
        self.assertTrue(module.cache_path(key).is_file())
        self.assertEqual(module.cache_path(key).stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.evaluate()[1], [])

    def test_failure_or_other_shard_does_not_reuse(self):
        for options in [
            {"conclusion": "failure"},
            {"conclusion": "cancelled"},  # codespell:ignore cancelled
            {"conclusion": None},
            {"name": "Browser Tests (2/3)"},
            {"expired": True},
            {"run_id": 20},
        ]:
            with self.subTest(options=options):
                self.assertFalse(self.evaluate(**options)[0][0])

    def test_fingerprint_separates_inputs(self):
        _, original, _ = self.evaluate(conclusion="failure")[0]
        for variable in [
            "CHECK_NAME",
            "GITHUB_REPOSITORY",
            "GITHUB_WORKFLOW_REF",
            "RUNNER_OS",
            "RUNNER_ARCH",
        ]:
            with patch.dict(os.environ, {variable: "different"}):
                self.assertNotEqual(self.evaluate(conclusion="failure")[0][1], original)
        self.tree = "different-tree"
        self.assertNotEqual(self.evaluate(conclusion="failure")[0][1], original)
        self.tree = "tree"
        self.event["pull_request"]["base"]["sha"] = "different-base"
        self.assertNotEqual(self.evaluate(conclusion="failure")[0][1], original)
        self.event["pull_request"]["base"]["sha"] = "base"
        self.event["pull_request"]["number"] = 43
        self.assertNotEqual(self.evaluate(conclusion="failure")[0][1], original)

    def test_open_reopen_and_rerun_bypass_warm_cache(self):
        self.evaluate()
        for action in ["opened", "reopened"]:
            self.event["action"] = action
            (skip, key, source), calls = self.evaluate()
            self.assertFalse(skip)
            self.assertTrue(key)
            self.assertEqual(calls, [])
        self.event["action"] = "synchronize"
        with patch.dict(os.environ, {"GITHUB_RUN_ATTEMPT": "2"}):
            self.assertFalse(self.evaluate()[0][0])

    def test_main_and_manual_runs_do_not_reuse(self):
        for event in ["push", "workflow_dispatch"]:
            with patch.dict(os.environ, {"GITHUB_EVENT_NAME": event}):
                self.assertEqual(self.evaluate()[0], (False, "", {}))

    def test_api_failure_runs_checks(self):
        self.assertFalse(
            self.evaluate(error=TimeoutError("GitHub request timed out"))[0][0]
        )

    def test_missing_or_unwritable_host_cache_uses_github(self):
        with patch.dict(os.environ, {"HOST_CACHE_DIR": ""}):
            self.assertTrue(self.evaluate()[0][0])
        with patch.dict(os.environ, {"HOST_CACHE_DIR": str(self.root / "event.json")}):
            self.assertTrue(self.evaluate()[0][0])

    def test_corrupt_host_cache_falls_back_to_github(self):
        (_, key, _), _ = self.evaluate(conclusion="failure")
        module.remember(key, {"broken": True})
        self.assertTrue(self.evaluate()[0][0])

    def test_save_preserves_source_for_artifact_restore(self):
        (_, key, _), _ = self.evaluate(conclusion="failure")
        source = {"run-id": "123", "head-sha": "b" * 40}
        module.remember(key, source)
        (skip, _, restored), calls = self.evaluate()
        self.assertTrue(skip)
        self.assertEqual(restored, source)
        self.assertEqual(calls, [])

    def test_paginates_jobs(self):
        Path(os.environ["GITHUB_EVENT_PATH"]).write_text(json.dumps(self.event))
        responses = [
            {
                "artifacts": [
                    {"expired": False, "workflow_run": {"id": 10, "head_sha": "a" * 40}}
                ]
            },
            {"jobs": [{"name": "unrelated", "conclusion": "success"}] * 100},
            {"jobs": [{"name": "Browser Tests (1/3)", "conclusion": "success"}]},
        ]
        with (
            patch.object(module.subprocess, "check_output", return_value=self.tree),
            patch.object(module, "api", side_effect=responses) as api,
        ):
            self.assertTrue(module.check()[0])
            self.assertIn("page=2", api.call_args_list[-1].args[0])


if __name__ == "__main__":
    unittest.main()
