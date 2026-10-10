import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "dist_cache", Path(__file__).with_name("dist-cache.py")
)
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


class DistCacheTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        host = self.root / "host"
        host.mkdir()
        self.state = self.root / "state.json"
        self.event = self.root / "event.json"
        environment = patch.dict(os.environ, {
            "GITHUB_WORKSPACE": str(self.repo),
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_EVENT_PATH": str(self.event),
            "HOST_CACHE_DIR": str(host),
            "DIST_CACHE_ENABLED": "1",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.git("init", "--quiet")
        (self.repo / ".github").mkdir()
        (self.repo / ".github/dist-cache.json").write_text(json.dumps({
            "inputs": ["source.txt"],
            "outputs": ["dist"],
            "symlinks": {"static": "dist"},
        }))
        (self.repo / "source.txt").write_text("source")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Initial")
        self.set_pr_head()
        cache.restore(self.state)
        self.entry = Path(json.loads(self.state.read_text())["entry"])
        (self.repo / "dist").mkdir()
        (self.repo / "dist/output.txt").write_text("cached build")
        cache.save(self.state)
        cache.remove(self.repo / "dist")

    def git(self, *args):
        return subprocess.check_output([
            "git", "-C", str(self.repo),
            "-c", "user.name=CI test", "-c", "user.email=ci@example.invalid",
            "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
            *args,
        ], text=True).strip()

    def set_pr_head(self):
        self.event.write_text(json.dumps({
            "pull_request": {"head": {"sha": self.git("rev-parse", "HEAD")}},
        }))

    def test_full_pr_head_bypasses_warm_cache_and_save(self):
        self.git("commit", "--quiet", "--allow-empty", "-m", "Rebuild\n\n[ci full]")
        self.set_pr_head()
        self.git("commit", "--quiet", "--allow-empty", "-m", "Synthetic merge")
        # A previous invocation's state must not cause publication on this run.
        self.state.write_text(json.dumps({
            "root": str(self.repo), "entry": str(self.entry), "outputs": ["dist"],
        }))
        cache.restore(self.state)
        self.assertFalse((self.repo / "dist").exists())
        self.assertFalse((self.repo / "static").is_symlink())
        self.assertFalse(self.state.exists())
        cache.save(self.state)
        self.assertEqual((self.entry / "dist/output.txt").read_text(), "cached build")

    def test_only_latest_pr_commit_controls_override(self):
        self.git("commit", "--quiet", "--allow-empty", "-m", "Old [ci full]")
        self.git("commit", "--quiet", "--allow-empty", "-m", "Ordinary PR head")
        self.set_pr_head()
        self.git("commit", "--quiet", "--allow-empty", "-m", "Merge [ci full]")
        cache.restore(self.state)
        self.assertEqual((self.repo / "static/output.txt").read_text(), "cached build")

    def test_push_does_not_apply_pr_override(self):
        self.git("commit", "--quiet", "--allow-empty", "-m", "Release [ci full]")
        self.event.unlink()
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "push"}):
            cache.restore(self.state)
        self.assertEqual((self.repo / "static/output.txt").read_text(), "cached build")


if __name__ == "__main__":
    unittest.main()
