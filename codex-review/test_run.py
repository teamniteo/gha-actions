"""Only confirmed auth failures should quarantine Codex, never ordinary CI."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('run.py')


class RunTests(unittest.TestCase):
    def run_codex(self, message, code=1, flagged=False, event=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / 'codex'
            executable.write_text(f'#!{sys.executable}\nimport os, sys\nassert "GH_TOKEN" not in os.environ\nassert "GITHUB_TOKEN" not in os.environ\nprint({message!r}, file=sys.stderr)\nsys.exit({code})\n')
            events = root / "events.jsonl"
            events.write_text(event or "")
            executable.chmod(0o755)
            flag = root / 'auth-required'
            if flagged:
                flag.touch()
            result = subprocess.run([sys.executable, '-B', str(SCRIPT), 'exec'],
                env=dict(os.environ, CODEX_HOME=directory, EVENTS=str(events), PATH=f'{root}:{os.environ["PATH"]}',
                         GH_TOKEN='must-not-reach-codex', GITHUB_TOKEN='must-not-reach-codex'),
                capture_output=True, text=True)
            return result, flag.exists()

    def test_refresh_failure_requires_login(self):
        result, flagged = self.run_codex('ERROR: Your access token could not be refreshed because your refresh token was revoked. Please log out and sign in again.')
        self.assertEqual(result.returncode, 1)
        self.assertTrue(flagged)

    def test_missing_login_is_auth_failure(self):
        self.assertTrue(self.run_codex('Not logged in')[1])

    def test_json_auth_failure_requires_login(self):
        self.assertTrue(self.run_codex("", event='{"type":"error","message":"Not logged in"}')[1])
        self.assertTrue(self.run_codex("", event='{"type":"turn.failed","error":{"message":"Your session has ended"}}')[1])
        self.assertFalse(self.run_codex("", event='{"type":"item.completed","message":"Not logged in"}')[1])

    def test_rate_limits_and_network_errors_do_not_disable_slot(self):
        for message in ('429 rate limit exceeded', 'connection timed out', '401 Unauthorized', 'invalid model'):
            self.assertFalse(self.run_codex(message)[1])

    def test_success_does_not_create_flag(self):
        result, flagged = self.run_codex('ok', code=0)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(flagged)

    def test_flagged_slot_refuses_another_review(self):
        result, flagged = self.run_codex('should not execute', flagged=True)
        self.assertTrue(flagged)
        self.assertNotIn('should not execute', result.stderr)


if __name__ == '__main__':
    unittest.main()
