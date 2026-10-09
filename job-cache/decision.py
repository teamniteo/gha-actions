import os
from pathlib import Path


def decide(environment):
    if environment.get("ALWAYS_RUN") == "true":
        return False, "This job is configured to always run"
    if environment.get("FULL") == "true":
        return False, "Forced by [ci full] in the latest PR commit"
    if environment.get("CACHED_SKIP") == "true":
        return True, "Unchanged code already passed on the same PR base"
    if environment.get("PATH_MATCH") == "false":
        return True, "No changed files match this job's path filter"
    if environment.get("SCHEDULE_SKIP") == "true":
        return True, "A successful execution is within the configured interval"
    if environment.get("GITHUB_RUN_ATTEMPT", "1") != "1":
        return False, "Workflow rerun bypasses result reuse and the schedule"
    if environment.get("GITHUB_EVENT_NAME") != "pull_request":
        return (
            False,
            "Non-PR run bypasses result reuse and path filters; schedule is due or disabled",
        )
    return (
        False,
        "No reusable successful result; paths match or are unfiltered; schedule is due or disabled",
    )


if __name__ == "__main__":
    skip, reason = decide(os.environ)
    key = os.environ.get("CACHE_KEY", "")
    if (
        os.environ.get("PATH_MATCH") == "false"
        or os.environ.get("SCHEDULE_SKIP") == "true"
    ):
        key = ""
    print(f"{'SKIP' if skip else 'RUN'} {os.environ['CHECK_NAME']}: {reason}")
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"skip={str(skip).lower()}\nkey={key}\nreason={reason}\n")
