import json
import os
from pathlib import Path


def decide(environment):
    path_filter = environment.get("PATH_FILTER", "")
    interval = int(environment.get("INTERVAL_DAYS") or "0")
    if environment.get("ALWAYS_RUN") == "true":
        return False, "This job is configured to always run"
    if environment.get("FULL") == "true":
        return False, "Forced by [ci full] in the latest PR commit"
    if environment.get("CACHED_SKIP") == "true":
        return True, "Unchanged code already passed on the same PR base"
    if environment.get("PATH_MATCH") == "false":
        return True, f"No changed files match filter {path_filter!r}"
    if environment.get("SCHEDULE_SKIP") == "true":
        return True, f"A successful execution is within {interval} days"
    if environment.get("GITHUB_RUN_ATTEMPT", "1") != "1":
        return False, "Workflow rerun bypasses result reuse and the schedule"
    event = environment.get("GITHUB_EVENT_NAME", "unknown")
    if event != "pull_request":
        reasons = [f"{event} event bypasses result reuse and path filters"]
    else:
        action = environment.get("EVENT_ACTION", "synchronize")
        reasons = [
            "No reusable successful result"
            if action == "synchronize"
            else f"{action} event bypasses result reuse"
        ]
        if environment.get("PATH_MATCH") == "true":
            reasons.append(f"Changed files match filter {path_filter!r}")
        elif not path_filter:
            reasons.append("No path filter configured")
        else:
            reasons.append(f"Filter {path_filter!r} was not evaluated")
    if interval:
        reasons.append(f"No successful execution found within {interval} days")
    return False, "; ".join(reasons)


if __name__ == "__main__":
    skip, reason = decide(os.environ)
    key = os.environ.get("CACHE_KEY", "")
    if (
        os.environ.get("PATH_MATCH") == "false"
        or os.environ.get("SCHEDULE_SKIP") == "true"
    ):
        key = ""
    matrix = json.loads(os.environ.get("MATRIX_JSON") or "null")
    label = os.environ["GITHUB_JOB"] + (
        f" {json.dumps(matrix, sort_keys=True)}" if matrix else ""
    )
    print(f"{'SKIP' if skip else 'RUN'} {label}: {reason}")
    with Path(os.environ["GITHUB_ENV"]).open("a") as environment:
        environment.write(f"GHA_SKIP_KEY={key}\n")
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        if skip:
            output.write("skip=true\n")
        else:
            output.write("run=true\n")
        output.write(f"key={key}\nreason={reason}\n")
