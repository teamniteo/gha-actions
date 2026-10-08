"""Exercise publishing without network access or credentials."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import publish


class PublishingTests(unittest.TestCase):
    def run_review(self, *, complete=True, findings=None, unresolved=False,
                   changed_head=False, skip="", thread_author="codex-niteo"):
        calls = []

        def api(endpoint, payload=None):
            calls.append((endpoint, payload))
            if payload is None:
                return {"head": {"sha": "changed" if changed_head else "head"}}
            if endpoint == "graphql":
                return {"data": {"repository": {"pullRequest": {"reviewThreads": {
                    "pageInfo": {"hasNextPage": False},
                    "nodes": [{"isResolved": not unresolved, "comments": {"nodes": [{
                        "author": {"login": thread_author}, "body": publish.MARKER,
                    }]}}],
                }}}}}
            return {}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "review-threads.json").write_text("[]")
            (root / "result.json").write_text(json.dumps({
                "complete": complete, "findings": findings or [], "answers": [],
            }))
            with patch.dict(os.environ, {
                "AUTHOR": "codex-niteo", "REPO": "owner/repo", "PR": "1", "HEAD": "head", "SKIP": skip,
                "CONTEXT": directory, "RESULT": str(root / "result.json"),
            }), patch.object(publish, "api", side_effect=api):
                publish.main()
        return calls

    def test_clean_review_approves_pinned_commit(self):
        calls = self.run_review()
        approval = next(payload for _, payload in calls if payload and payload.get("event") == "APPROVE")
        self.assertEqual(approval["commit_id"], "head")
        self.assertEqual(calls[-1][1]["context"], "codex-review")

    def test_unresolved_thread_blocks_approval(self):
        calls = self.run_review(unresolved=True)
        self.assertFalse(any(p and p.get("event") == "APPROVE" for _, p in calls))

    def test_rest_bot_suffix_also_blocks_approval(self):
        calls = self.run_review(unresolved=True, thread_author="codex-niteo[bot]")
        self.assertFalse(any(p and p.get("event") == "APPROVE" for _, p in calls))

    def test_other_bot_thread_does_not_block_approval(self):
        calls = self.run_review(unresolved=True, thread_author="claude")
        self.assertTrue(any(p and p.get("event") == "APPROVE" for _, p in calls))

    def test_findings_are_inline_and_block_approval(self):
        calls = self.run_review(findings=[{"path": "app.py", "line": 3, "body": "Bug"}])
        review = next(p for _, p in calls if p and p.get("event") == "COMMENT")
        self.assertEqual(review["comments"][0]["side"], "RIGHT")
        self.assertIn(publish.MARKER, review["comments"][0]["body"])
        self.assertFalse(any(p and p.get("event") == "APPROVE" for _, p in calls))

    def test_questions_only_does_not_review_or_mark(self):
        self.assertEqual(len(self.run_review(skip="draft")), 1)

    def test_incomplete_review_fails(self):
        with self.assertRaises(RuntimeError):
            self.run_review(complete=False)

    def test_head_change_fails(self):
        with self.assertRaises(RuntimeError):
            self.run_review(changed_head=True)


if __name__ == "__main__":
    unittest.main()
