import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


def api(path):
    request = urllib.request.Request(
        f"{os.environ.get('GITHUB_API_URL', 'https://api.github.com')}/{path}",
        headers={
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def cache_path(key):
    root = os.environ.get("HOST_CACHE_DIR")
    return Path(root, "ci-success", key) if root else None


def remember(key, source):
    path = cache_path(key)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary.write(json.dumps(source).encode())
        os.chmod(temporary.name, 0o644)
        os.replace(temporary.name, path)
    except OSError as error:
        print(f"Host cache unavailable: {error}")


def full_override():
    if os.environ["GITHUB_EVENT_NAME"] != "pull_request":
        return False
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    message = subprocess.check_output(
        [
            "git",
            "-C",
            os.environ["GITHUB_WORKSPACE"],
            "log",
            "-1",
            "--format=%B",
            event["pull_request"]["head"]["sha"],
        ],
        text=True,
    )
    return "[ci full]" in message


def check(full=None):
    if os.environ.get("ALWAYS_RUN") == "true":
        return False, "", {}
    if os.environ["GITHUB_EVENT_NAME"] != "pull_request":
        return False, "", {}
    if full is None:
        full = full_override()
    if full:
        return False, "", {}
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    pr = event["pull_request"]
    tree = subprocess.check_output(
        ["git", "-C", os.environ["GITHUB_WORKSPACE"], "rev-parse", "HEAD^{tree}"],
        text=True,
    ).strip()
    identity = [
        os.environ["GITHUB_REPOSITORY"],
        os.environ["GITHUB_WORKFLOW_REF"].split("@")[0],
        pr["number"],
        pr["base"]["sha"],
        tree,
        os.environ["GITHUB_JOB"],
        json.loads(os.environ.get("MATRIX_JSON") or "null"),
        os.environ.get("RUNNER_OS"),
        os.environ.get("RUNNER_ARCH"),
        hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    ]
    key = (
        "ci-success-v2-"
        + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    )
    Path(os.environ["RUNNER_TEMP"], "job-cache-marker.txt").write_text(tree)
    if (
        event["action"] != "synchronize"
        or int(os.environ.get("GITHUB_RUN_ATTEMPT", "1")) > 1
    ):
        return False, key, {}
    try:
        path = cache_path(key)
        if path is not None:
            source = json.loads(path.read_text())
            if not isinstance(source["run-id"], str) or not source["run-id"].isdigit():
                raise ValueError("Invalid cached run ID")
            if not isinstance(source["head-sha"], str) or not re.fullmatch(
                r"[0-9a-f]{40}", source["head-sha"]
            ):
                raise ValueError("Invalid cached head SHA")
            print("Reusing successful checks from host-cache")
            return True, key, source
    except (OSError, ValueError, KeyError, TypeError):
        pass
    repo = os.environ["GITHUB_REPOSITORY"]
    try:
        artifacts = api(f"repos/{repo}/actions/artifacts?name={key}&per_page=100")
        for candidate in artifacts["artifacts"]:
            run_id = candidate["workflow_run"]["id"]
            if candidate["expired"] or str(run_id) == os.environ["GITHUB_RUN_ID"]:
                continue
            run = api(f"repos/{repo}/actions/runs/{run_id}")
            if run["conclusion"] == "success":
                print(f"Reusing successful checks from run {run_id}")
                source = {
                    "run-id": str(run_id),
                    "head-sha": candidate["workflow_run"]["head_sha"],
                }
                remember(key, source)
                return True, key, source
    except (OSError, subprocess.SubprocessError, KeyError, ValueError) as error:
        print(f"Unable to reuse checks, running the job: {error}")
    return False, key, {}


if __name__ == "__main__":
    if sys.argv[1:] == ["save"]:
        if not re.fullmatch(r"ci-success-v2-[0-9a-f]{64}", os.environ["CACHE_KEY"]):
            raise ValueError("Invalid cache key")
        remember(
            os.environ["CACHE_KEY"],
            {"run-id": os.environ["GITHUB_RUN_ID"], "head-sha": os.environ["HEAD_SHA"]},
        )
    else:
        full = full_override()
        skip, key, source = check(full=full)
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
            output.write(
                f"skip={str(skip).lower()}\nkey={key}\nfull={str(full).lower()}\n"
            )
            for name, value in source.items():
                output.write(f"{name}={value}\n")
