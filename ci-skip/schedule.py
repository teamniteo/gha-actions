import datetime
import os
from pathlib import Path

from cache import api


def skip():
    days = int(os.environ["INTERVAL_DAYS"])
    if days <= 0 or os.environ["FULL"] == "true":
        return False
    if os.environ.get("GITHUB_RUN_ATTEMPT", "1") != "1":
        return False
    repo = os.environ["GITHUB_REPOSITORY"]
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=days
    )
    try:
        artifacts = api(
            f"repos/{repo}/actions/artifacts?name={os.environ['INTERVAL_ARTIFACT']}&per_page=100"
        )["artifacts"]
        for artifact in artifacts:
            if (
                artifact["expired"]
                or str(artifact["workflow_run"]["id"]) == os.environ["GITHUB_RUN_ID"]
            ):
                continue
            created = datetime.datetime.fromisoformat(
                artifact["created_at"].replace("Z", "+00:00")
            )
            if created <= cutoff:
                continue
            run_id = artifact["workflow_run"]["id"]
            page = 1
            while True:
                jobs = api(
                    f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100&page={page}"
                )["jobs"]
                if any(
                    job["name"] == os.environ["CHECK_NAME"]
                    and job["conclusion"] == "success"
                    for job in jobs
                ):
                    print(
                        f"Skipping scheduled job: successful run {run_id} is within {days} days"
                    )
                    return True
                if len(jobs) < 100:
                    break
                page += 1
    except (OSError, KeyError, ValueError, TypeError) as error:
        print(f"Unable to check schedule, running the job: {error}")
    return False


if __name__ == "__main__":
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"skip={str(skip()).lower()}\n")
