"""Publish structured Codex output; the agent never gets a GitHub token."""

import json
import os
import subprocess
from pathlib import Path

MARKER = "<!-- codex-review -->"


def api(endpoint, payload=None):
    args = ["gh", "api", endpoint]
    if payload is not None:
        args += ["--method", "POST", "--input", "-"]
    result = subprocess.run(
        args, input=json.dumps(payload) if payload is not None else None,
        text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout)


def main():
    result = json.loads(Path(os.environ["RESULT"]).read_text())
    if result["complete"] is not True:
        raise RuntimeError("Codex did not complete the review; no approval or status posted")
    repo, pr, head = (os.environ[key] for key in ("REPO", "PR", "HEAD"))
    base = f"repos/{repo}/pulls/{pr}"
    # A push during the review invalidates both findings and approval.
    if api(base)["head"]["sha"] != head:
        raise RuntimeError("PR head changed during review; wait for the next run")
    threads = json.loads((Path(os.environ["CONTEXT"]) / "review-threads.json").read_text())
    thread_ids = {thread["id"] for thread in threads}
    for answer in result["answers"]:
        body = f"{MARKER}\n{answer['body']}"
        comment_id = answer["comment_id"]
        if comment_id:
            if comment_id not in thread_ids:
                raise ValueError("Answer refers to a thread outside this PR")
            api(f"{base}/comments/{comment_id}/replies", {"body": body})
        else:
            api(f"repos/{repo}/issues/{pr}/comments", {"body": body})
    if os.environ["SKIP"]:
        return
    findings = result["findings"]
    if findings:
        api(f"{base}/reviews", {
            "commit_id": head, "event": "COMMENT", "body": MARKER,
            "comments": [dict(path=f["path"], line=f["line"], side="RIGHT",
                              body=f"{MARKER}\n{f['body']}") for f in findings],
        })
    else:
        # Re-fetch immediately before approval: threads may change while Codex runs.
        query = '''query($owner:String!,$name:String!,$pr:Int!,$cursor:String){
          repository(owner:$owner,name:$name){pullRequest(number:$pr){
            reviewThreads(first:100,after:$cursor){pageInfo{hasNextPage endCursor}
              nodes{isResolved comments(first:1){nodes{author{login} body}}}}
          }}}'''
        owner, name = repo.split("/")
        cursor = None
        unresolved = False
        while True:
            data = api("graphql", {"query": query, "variables": {
                "owner": owner, "name": name, "pr": int(pr), "cursor": cursor,
            }})
            if data.get("errors"):
                raise RuntimeError(data["errors"])
            page = data["data"]["repository"]["pullRequest"]["reviewThreads"]
            for thread in page["nodes"]:
                comments = thread["comments"]["nodes"]
                if comments:
                    first = comments[0]
                    author = (first.get("author") or {}).get("login")
                    if author == "github-actions[bot]" and MARKER in first["body"]:
                        unresolved |= not thread["isResolved"]
            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]
        if not unresolved:
            api(f"{base}/reviews", {"commit_id": head, "event": "APPROVE", "body": MARKER})
    api(f"repos/{repo}/statuses/{head}", {
        "state": "success", "context": "codex-review", "description": "Reviewed by Codex",
    })


if __name__ == "__main__":
    main()
