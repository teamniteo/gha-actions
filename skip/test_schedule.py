import datetime
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
spec = importlib.util.spec_from_file_location(
    "schedule", Path(__file__).with_name("schedule.py")
)
schedule = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schedule)


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "INTERVAL_DAYS": "7",
                "INTERVAL_ARTIFACT": "last_full_run",
                "FULL": "false",
                "GITHUB_RUN_ATTEMPT": "1",
                "GITHUB_REPOSITORY": "owner/repo",
                "GITHUB_RUN_ID": "20",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def evaluate(self, *, age=1, conclusion="success", expired=False, run_id=10):
        created = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            days=age
        )
        responses = [
            {
                "artifacts": [
                    {
                        "expired": expired,
                        "created_at": created.isoformat(),
                        "workflow_run": {"id": run_id},
                    }
                ]
            },
            {"conclusion": conclusion},
        ]
        with patch.object(schedule, "api", side_effect=responses) as api:
            return schedule.skip(), api.call_count

    def test_only_recent_successful_matching_execution_skips(self):
        self.assertTrue(self.evaluate()[0])
        for options in [
            {"age": 8},
            {"conclusion": "failure"},
            {"expired": True},
            {"run_id": 20},
        ]:
            with self.subTest(options=options):
                self.assertFalse(self.evaluate(**options)[0])

    def test_override_rerun_and_disabled_schedule_make_no_requests(self):
        for change in [
            {"FULL": "true"},
            {"GITHUB_RUN_ATTEMPT": "2"},
            {"INTERVAL_DAYS": "0"},
        ]:
            with patch.dict(os.environ, change):
                self.assertEqual(self.evaluate(), (False, 0))

    def test_api_failure_runs_normally(self):
        with patch.object(schedule, "api", side_effect=OSError("timeout")):
            self.assertFalse(schedule.skip())
