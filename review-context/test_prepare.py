"""Exercise shared review policy with GitHub responses, without network access."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('prepare.sh').resolve()


class PrepareTest(unittest.TestCase):
    def prepare(self, event='pull_request', comment='', reviewed=False,
                approved=False, draft=False, threads=None, author='claude', marker=''):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = dict(draft=draft, reviewed=reviewed, approved=approved,
                           threads=threads or [], author=author, marker=marker)
            (root / 'fixture.json').write_text(json.dumps(fixture))
            gh = root / 'gh'
            gh.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
f=json.loads(Path(os.environ['FIXTURE']).read_text())
a=sys.argv[1:]
if a[:2] == ['pr','view']:
    if 'isDraft,headRefOid' in a: print(str(f['draft']).lower()+' abc')
    else: print(json.dumps(dict(comments=[],reviews=[])))
elif 'graphql' in a: print(json.dumps(f['threads']))
elif any('/reviews?' in x for x in a):
    print(json.dumps([dict(user=dict(login=f['author']+'[bot]'),state='APPROVED',body=f['marker'],commit_id='abc')] if f['approved'] else []))
else: print(json.dumps(dict(statuses=[dict(context='test-review')] if f['reviewed'] else [])))
''')
            gh.chmod(0o755)
            # Convention loading remains offline in this policy test.
            curl = root / 'curl'
            curl.write_text('#!/bin/sh\nexit 0\n')
            curl.chmod(0o755)
            output = root / 'output'
            env = dict(os.environ, PATH=f'{root}:{os.environ["PATH"]}',
                       FIXTURE=str(root/'fixture.json'), CONTEXT=str(root/'context'),
                       PR='1', REPO='owner/repo', AUTHOR=author, MARKER=marker,
                       STATUS='test-review', MENTION='@'+author, EVENT=event,
                       COMMENT=comment, RULES='conventions', GITHUB_OUTPUT=str(output))
            subprocess.run(['bash', str(SCRIPT)], env=env, cwd=root,
                           check=True, capture_output=True, text=True)
            return dict(line.split('=', 1) for line in output.read_text().splitlines())

    def test_new_commit_reviews(self):
        self.assertEqual(self.prepare()['mode'], 'review')

    def test_comment_only_answers(self):
        for event in ('issue_comment', 'pull_request_review_comment'):
            self.assertEqual(self.prepare(event, '@claude why?')['mode'], 'answer')
            self.assertEqual(self.prepare(event)['mode'], 'skip')

    def test_mentions_do_not_match_longer_bot_names(self):
        self.assertEqual(self.prepare('issue_comment', '@claude-other why?')['mode'], 'skip')

    def test_resolved_threads_allow_follow_up_review_on_comments(self):
        for author, marker in (('claude', ''), ('codex-niteo', '<!-- codex-review -->')):
            threads = [dict(id=1, resolved=True, comments=[
                dict(author=author+'[bot]', body=marker, at='2026-01-01')])]
            for event in ('issue_comment', 'pull_request_review_comment', 'pull_request_review'):
                with self.subTest(author=author, event=event):
                    result = self.prepare(event, reviewed=True, threads=threads,
                                          author=author, marker=marker)
                    self.assertEqual(result['mode'], 'review')
                    self.assertEqual(result['skip'], '')
                    self.assertEqual(result['run'], 'true')

    def test_follow_up_comments_preserve_review_guards(self):
        for author, marker in (('claude', ''), ('codex-niteo', '<!-- codex-review -->')):
            threads = [dict(id=1, resolved=False, comments=[
                dict(author=author, body=marker, at='2026-01-01')])]
            for event in ('issue_comment', 'pull_request_review_comment'):
                for guard in (dict(draft=True), dict(approved=True), dict(threads=threads)):
                    with self.subTest(author=author, event=event, guard=guard):
                        kwargs = dict(reviewed=True, author=author, marker=marker, **guard)
                        self.assertEqual(self.prepare(event, **kwargs)['mode'], 'skip')
                        self.assertEqual(self.prepare(event, '@'+author+' why?', **kwargs)['mode'], 'answer')

    def test_codex_rereview_comment_after_resolution(self):
        # https://github.com/mayetrx/vend/pull/910#issuecomment-6069560753
        marker = '<!-- codex-review -->'
        threads = [dict(id=1, resolved=True, comments=[
            dict(author='codex-niteo', body=marker, at='2026-01-01')])]
        result = self.prepare('issue_comment', '@codex-niteo rereview', reviewed=True,
                              threads=threads, author='codex-niteo', marker=marker)
        self.assertEqual(result['mode'], 'review')
        self.assertEqual(result['skip'], '')

    def test_approved_commit_skips_but_answers_mentions(self):
        self.assertEqual(self.prepare(reviewed=True, approved=True)['mode'], 'skip')
        self.assertEqual(self.prepare(comment='@claude why?', reviewed=True, approved=True)['mode'], 'answer')

    def test_draft_skips_but_answers_mentions(self):
        self.assertEqual(self.prepare(draft=True)['mode'], 'skip')
        self.assertEqual(self.prepare(draft=True, comment='@claude why?')['mode'], 'answer')

    def test_codex_app_mention_answers_without_review(self):
        result=self.prepare('issue_comment', '@codex-niteo why?', author='codex-niteo')
        self.assertEqual(result['mode'], 'answer')
        result=self.prepare('issue_comment', '@codex why?', author='codex-niteo')
        self.assertEqual(result['mode'], 'skip')

    def test_bot_suffix_does_not_hide_open_threads(self):
        threads=[dict(id=1, resolved=False, comments=[dict(author='codex-niteo[bot]', body='codex', at='2026-01-01')])]
        result=self.prepare(reviewed=True, threads=threads, author='codex-niteo', marker='codex')
        self.assertEqual(result['mode'], 'skip')
        self.assertEqual(result['open'], '1')

    def test_marker_separates_reviewers_sharing_identity(self):
        threads=[dict(id=1, resolved=False, comments=[dict(author='github-actions', body='other', at='2026-01-01')])]
        result=self.prepare(reviewed=True, threads=threads, author='github-actions', marker='codex')
        self.assertEqual(result['open'], '0')
        threads[0]['comments'][0]['body']='codex'
        result=self.prepare(reviewed=True, threads=threads, author='github-actions', marker='codex')
        self.assertEqual(result['mode'], 'skip')


if __name__ == '__main__':
    unittest.main()
