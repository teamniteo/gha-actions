"""Exercise diff collection with real Git histories and no GitHub network."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('diff.sh').resolve()


class DiffTest(unittest.TestCase):
    def test_large_fork_diff_excludes_new_base_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            source.mkdir()

            def git(*args):
                return subprocess.check_output(
                    ['git', '-C', str(source), *args], text=True,
                    stderr=subprocess.DEVNULL).strip()

            git('init', '-b', 'main')
            git('config', 'user.email', 'test@example.com')
            git('config', 'user.name', 'Test')
            (source / 'initial').write_text('initial\n')
            git('add', '.')
            git('commit', '-m', 'initial')
            git('checkout', '-b', 'fork')
            for i in range(301):
                (source / f'file-{i}').write_text('added\n')
            git('add', '.')
            git('commit', '-m', 'large PR')
            head = git('rev-parse', 'HEAD')
            git('checkout', 'main')
            (source / 'base-only').write_text('not part of PR\n')
            git('add', '.')
            git('commit', '-m', 'base advanced')
            base = git('rev-parse', 'HEAD')
            config = root / 'gitconfig'
            config.write_text(f'[url "file://{source}"]\n'
                              '    insteadOf = https://github.com/owner/repo.git\n')
            gh = root / 'gh'
            gh.write_text(f'#!/bin/sh\nset -eu\n'
                          f'test "$1 $2" = "pr view"\n'
                          f'echo "{base} {head}"\n')
            gh.chmod(0o755)
            context = root / 'context'
            context.mkdir()
            env = dict(os.environ, PATH=f'{root}:{os.environ["PATH"]}',
                       GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM='1',
                       CONTEXT=str(context), REPO='owner/repo', PR='1')
            subprocess.run(['bash', str(SCRIPT)], cwd=root, env=env,
                           check=True, capture_output=True, text=True)
            diff = (context / 'diff.patch').read_text()
            self.assertEqual(diff.count('diff --git '), 301)
            self.assertNotIn('base-only', diff)
            self.assertFalse(list(context.glob('diff-repository.*')))


if __name__ == '__main__':
    unittest.main()
