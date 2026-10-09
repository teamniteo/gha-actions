import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "policy", Path(__file__).with_name("config.py")
)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.config = policy.yaml.safe_load("""
filters:
  application: ['**', '!frontend/tests/**']
jobs:
  backend_checks:
    filter: always
  browser_tests:
    filter: application
  demo_content:
    filter: application
    schedule:
      matrix: {day: full}
      days: 7
      artifact: last_full_run
""")

    def test_always_run_is_selected_by_job_id(self):
        self.assertEqual(
            policy.resolve(self.config, "backend_checks", None)["always-run"], "true"
        )
        self.assertEqual(
            policy.resolve(self.config, "browser_tests", {})["always-run"], "false"
        )

    def test_filters_are_serialized_for_the_path_matcher(self):
        result = policy.resolve(self.config, "browser_tests", {"shard": 2})
        self.assertEqual(result["filter"], "application")
        self.assertIn('"application":["**","!frontend/tests/**"]', result["filters"])

    def test_schedule_only_applies_to_selected_matrix_shard(self):
        full = policy.resolve(self.config, "demo_content", {"day": "full"})
        self.assertEqual(full["interval-days"], "7")
        self.assertEqual(full["interval-artifact"], "last_full_run")
        for matrix in [{"day": 1}, {"day": "1"}, None]:
            daily = policy.resolve(self.config, "demo_content", matrix)
            self.assertEqual(daily["interval-days"], "0")
            self.assertEqual(daily["interval-artifact"], "")

    def test_unconfigured_jobs_use_normal_result_reuse(self):
        result = policy.resolve(self.config, "frontend_tests", None)
        self.assertEqual(result["always-run"], "false")
        self.assertEqual(result["filter"], "")
        self.assertEqual(result["interval-days"], "0")

    def test_invalid_rules_fail_instead_of_silently_skipping(self):
        for rule in [
            {"filter": "typo"},
            {"always-run": "false"},
            {"schedule": {"days": 7}},
        ]:
            with self.subTest(rule=rule), self.assertRaises(ValueError):
                policy.resolve({"jobs": {"job": rule}}, "job", {})

    def test_always_cannot_be_redefined_as_a_path_filter(self):
        with self.assertRaisesRegex(ValueError, "reserved"):
            policy.resolve({"filters": {"always": ["!**"]}}, "job", {})
