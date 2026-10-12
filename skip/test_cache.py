import importlib.util
import json
import os
import re
import subprocess
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
            "pull_request": {
                "number": 42,
                "base": {"sha": "base"},
                "head": {"sha": "head"},
            },
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
            "GITHUB_JOB": "browser_tests",
            "MATRIX_JSON": '{"shard": 1}',
        }
        self.patch = patch.dict(os.environ, self.environment)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.tree = "tree"

    def evaluate(
        self,
        *,
        conclusion="success",
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
            {"conclusion": conclusion},
        ]
        with (
            patch.object(module.subprocess, "check_output", return_value=self.tree),
            patch.object(module, "api", side_effect=error or responses) as api,
        ):
            return module.check(), api.call_args_list

    def test_real_git_rewrites_reuse_results_but_code_changes_do_not(self):
        repo = self.root / "repo"
        repo.mkdir()

        def git(*args):
            return subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=CI test",
                    "-c",
                    "user.email=ci@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    "-c",
                    "core.hooksPath=/dev/null",
                    *args,
                ],
                text=True,
            ).strip()

        git("init", "--quiet")
        source = repo / "source.txt"
        source.write_text("base\n")
        git("add", "source.txt")
        git("commit", "--quiet", "-m", "Base")
        base = git("rev-parse", "HEAD")
        self.event["pull_request"]["base"]["sha"] = base
        for content in ["first\n", "second\n"]:
            source.write_text(content)
            git("commit", "--quiet", "-am", content.strip())

        def check():
            self.event["pull_request"]["head"]["sha"] = git("rev-parse", "HEAD")
            Path(os.environ["GITHUB_EVENT_PATH"]).write_text(json.dumps(self.event))
            return module.check()

        with (
            patch.dict(os.environ, {"GITHUB_WORKSPACE": str(repo)}),
            patch.object(module, "api", return_value={"artifacts": []}),
        ):
            skip, key, _ = check()
            self.assertFalse(skip)
            original = git("rev-parse", "HEAD")
            module.remember(key, {"run-id": "10", "head-sha": original})

            git("commit", "--quiet", "--amend", "-m", "Reworded")
            self.assertNotEqual(git("rev-parse", "HEAD"), original)
            self.assertEqual(check()[:2], (True, key))

            git("reset", "--soft", base)
            git("commit", "--quiet", "-m", "Squashed")
            self.assertEqual(git("rev-list", "--count", f"{base}..HEAD"), "1")
            self.assertEqual(check()[:2], (True, key))

            git("commit", "--quiet", "--amend", "-m", "Squashed [ci full]")
            self.assertEqual(check()[:2], (True, key))
            self.event["pull_request"]["labels"] = [{"name": "ci-full"}]
            self.assertEqual(check(), (False, "", {}))
            self.event["pull_request"]["labels"] = []
            self.assertEqual(check()[:2], (True, key))

            source.write_text("changed code\n")
            git("commit", "--quiet", "-am", "Changed code")
            skip, changed_key, _ = check()
            self.assertFalse(skip)
            self.assertNotEqual(changed_key, key)

    def test_filtered_fingerprint_ignores_files_outside_the_filter(self):
        repo = self.root / "repo"
        repo.mkdir()

        def git(*args):
            return subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=CI test",
                    "-c",
                    "user.email=ci@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    "-c",
                    "core.hooksPath=/dev/null",
                    *args,
                ],
                text=True,
            ).strip()

        def commit(path, content):
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text(content)
            git("add", path)
            git("commit", "--quiet", "-m", path)
            self.event["pull_request"]["head"]["sha"] = git("rev-parse", "HEAD")
            Path(os.environ["GITHUB_EVENT_PATH"]).write_text(json.dumps(self.event))
            return module.check()[1]

        git("init", "--quiet")
        filters = json.dumps({"backend": ["**", "!*.md", "!documentation/**"]})
        with (
            patch.dict(
                os.environ,
                {
                    "GITHUB_WORKSPACE": str(repo),
                    "PATH_FILTERS": filters,
                    "PATH_FILTER": "backend",
                },
            ),
            patch.object(module, "api", return_value={"artifacts": []}),
        ):
            original = commit("backend/app.py", "code\n")
            self.assertEqual(commit("documentation/guide.md", "docs\n"), original)
            self.assertEqual(commit("README.md", "readme\n"), original)
            self.assertNotEqual(commit("backend/app.py", "changed\n"), original)
            self.assertNotEqual(commit("docs/nested.md", "nested\n"), original)

            with patch.dict(os.environ, {"PATH_FILTER": ""}):
                unfiltered = module.check()[1]
                self.assertNotEqual(
                    commit("documentation/guide.md", "v3\n"), unfiltered
                )

    def test_glob_matching_mirrors_paths_filter(self):
        cases = [
            ("**", "a/b/.c", True),
            ("*.md", "README.md", True),
            ("*.md", "docs/README.md", False),
            ("documentation/**", "documentation/a/b.md", True),
            ("documentation/**", "documentation", True),
            ("documentation/**", "documentation.md", False),
            ("**/tests/test_*.py", "tests/test_a.py", True),
            ("**/tests/test_*.py", "src/x/tests/test_a.py", True),
            ("**/tests/test_*.py", "src/x/tests/sub/test_a.py", False),
            ("backend/src/**/tests/test_*.py", "backend/src/tests/test_a.py", True),
            ("backend/src/**/tests/test_*.py", "backend/src/a/tests/test_a.py", True),
            ("backend/src/**/tests/test_*.py", "backend/src/a/tests/a.py", False),
            (".github/workflows/ci.yml", ".github/workflows/ci.yml", True),
            (".github/workflows/ci.yml", ".github/workflows/ci.yaml", False),
            ("a?c", "abc", True),
            ("a?c", "a/c", False),
            ("a.b", "aXb", False),
        ]
        for pattern, path, expected in cases:
            with self.subTest(pattern=pattern, path=path):
                regex = re.compile(module.glob_regex(pattern))
                self.assertEqual(bool(regex.fullmatch(path)), expected)

    def test_excludes_win_and_a_file_needs_an_include(self):
        rules = [
            (exclude, re.compile(module.glob_regex(body)))
            for exclude, body in [
                (False, "backend/**"),
                (True, "backend/**/tests/**"),
                (False, "docs/*.md"),
            ]
        ]
        self.assertTrue(module.selected("backend/app.py", rules))
        self.assertFalse(module.selected("backend/app/tests/test_a.py", rules))
        self.assertTrue(module.selected("docs/a.md", rules))
        self.assertFalse(module.selected("frontend/app.elm", rules))
        self.assertFalse(module.selected("docs/a.md", rules[1:2]))

    def test_always_run_bypasses_warm_cache(self):
        self.evaluate()
        with patch.dict(os.environ, {"ALWAYS_RUN": "true"}):
            result, calls = self.evaluate()
            self.assertEqual(result, (False, "", {}))
            self.assertEqual(calls, [])

    def test_full_override_bypasses_all_caches(self):
        self.evaluate()
        self.event["pull_request"]["labels"] = [
            {"name": "self-hosted"}, {"name": "ci-full"},
        ]
        Path(os.environ["GITHUB_EVENT_PATH"]).write_text(json.dumps(self.event))
        with (
            patch.object(module.subprocess, "check_output") as git,
            patch.object(module, "api") as api,
        ):
            self.assertTrue(module.full_override())
            self.assertEqual(module.check(), (False, "", {}))
            git.assert_not_called()
            api.assert_not_called()

    def test_full_override_requires_exact_label(self):
        for labels in [[], [{"name": "self-hosted"}], [{"name": "ci-full-extra"}]]:
            with self.subTest(labels=labels):
                self.event["pull_request"]["labels"] = labels
                Path(os.environ["GITHUB_EVENT_PATH"]).write_text(json.dumps(self.event))
                self.assertFalse(module.full_override())

    def test_full_override_only_applies_to_pr_events(self):
        self.event["pull_request"]["labels"] = [{"name": "ci-full"}]
        Path(os.environ["GITHUB_EVENT_PATH"]).write_text(json.dumps(self.event))
        for event in ["push", "workflow_dispatch"]:
            with patch.dict(os.environ, {"GITHUB_EVENT_NAME": event}):
                self.assertFalse(module.full_override())

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
            {"expired": True},
            {"run_id": 20},
        ]:
            with self.subTest(options=options):
                self.assertFalse(self.evaluate(**options)[0][0])

    def test_fingerprint_separates_inputs(self):
        _, original, _ = self.evaluate(conclusion="failure")[0]
        for variable in [
            "GITHUB_JOB",
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

    def test_matrix_shards_have_distinct_keys(self):
        original = self.evaluate(conclusion="failure")[0][1]
        with patch.dict(os.environ, {"MATRIX_JSON": '{"shard": 2}'}):
            self.assertNotEqual(self.evaluate(conclusion="failure")[0][1], original)

    def test_matrix_object_order_does_not_change_key(self):
        with patch.dict(os.environ, {"MATRIX_JSON": '{"shard": 1, "os": "linux"}'}):
            original = self.evaluate(conclusion="failure")[0][1]
        with patch.dict(os.environ, {"MATRIX_JSON": '{"os": "linux", "shard": 1}'}):
            self.assertEqual(self.evaluate(conclusion="failure")[0][1], original)


if __name__ == "__main__":
    unittest.main()
