import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "elm_cache", Path(__file__).with_name("elm-cache.py")
)
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


class ElmCacheTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.host = self.root / "host"
        self.host.mkdir()
        self.state = self.root / "state.json"
        environment = patch.dict(os.environ, {
            "GITHUB_WORKSPACE": str(self.repo),
            "GITHUB_REPOSITORY": "teamniteo/project",
            "HOST_CACHE_DIR": str(self.host),
            "RUNNER_OS": "Linux",
            "RUNNER_ARCH": "X64",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.git("init", "--quiet")
        (self.repo / "nix").mkdir()
        self.commit({"frontend/elm.json": "v1", "nix/flake.lock": "week 1"})
        self.job(compile=["elm/core"])

    def git(self, *args):
        return subprocess.check_output([
            "git", "-C", str(self.repo),
            "-c", "user.name=CI test", "-c", "user.email=ci@example.invalid",
            "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
            *args,
        ], text=True).strip()

    def commit(self, files):
        for name, content in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Change")

    def job(self, compile=()):
        """Restore into a fresh ELM_HOME, compile packages, save; return the home's packages."""
        home = Path(tempfile.mkdtemp(dir=self.root))
        with patch.dict(os.environ, {"ELM_HOME": str(home)}):
            cache.restore(self.state)
            restored = self.packages(home)
            for package in compile:
                artifacts = home / "0.19.1/packages" / package / "1.0.0/artifacts.dat"
                artifacts.parent.mkdir(parents=True)
                artifacts.write_bytes(b"compiled")
            cache.save(self.state)
        return restored

    def packages(self, home):
        return {
            str(path.relative_to(home / "0.19.1/packages").parent.parent)
            for path in home.glob("0.19.1/packages/*/*/*/artifacts.dat")
        }

    def snapshots(self):
        return sorted((self.host / "elm").glob("snapshot-*"))

    def test_nix_update_keeps_snapshot(self):
        self.commit({"nix/flake.lock": "week 2", "flake.lock": "week 2"})
        self.assertEqual(self.job(), {"elm/core"})
        self.assertEqual(len(self.snapshots()), 1)

    def test_elm_change_restores_newest_snapshot_and_publishes_new_packages(self):
        [first] = self.snapshots()
        os.utime(first, (0, 0))
        self.commit({"frontend/elm.json": "v2"})
        self.assertEqual(self.job(compile=["elm/http"]), {"elm/core"})
        [second] = set(self.snapshots()) - {first}
        self.assertGreater(second.stat().st_mtime, first.stat().st_mtime)
        self.commit({"frontend/elm.json": "v3"})
        self.assertEqual(self.job(), {"elm/core", "elm/http"})

    def test_fallback_without_new_packages_publishes_nothing(self):
        self.commit({"frontend/elm.json": "v2"})
        self.assertEqual(self.job(), {"elm/core"})
        self.assertEqual(len(self.snapshots()), 1)

    def test_other_repository_does_not_fall_back(self):
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "teamniteo/other"}):
            self.assertEqual(self.job(), set())

    def test_other_platform_does_not_fall_back(self):
        with patch.dict(os.environ, {"RUNNER_ARCH": "ARM64"}):
            self.assertEqual(self.job(), set())


if __name__ == "__main__":
    unittest.main()
