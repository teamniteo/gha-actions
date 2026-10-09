import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "vendor" / "pyyaml.zip"))
import yaml  # noqa: E402


def resolve(config, job, matrix):
    rule = config.get("jobs", {}).get(job, {})
    filters = config.get("filters", {})
    selected = rule.get("filter", "")
    if "always" in filters:
        raise ValueError("always is a reserved filter name")
    if "always-run" in rule:
        raise ValueError("Use filter: always for jobs that must always run")
    if selected and selected != "always" and selected not in filters:
        raise ValueError(f"Unknown filter {selected!r} for job {job!r}")
    schedule = rule.get("schedule", {})
    selector = schedule.get("matrix", {})
    scheduled = bool(schedule) and all(
        (matrix or {}).get(k) == v for k, v in selector.items()
    )
    days = int(schedule.get("days", 0)) if scheduled else 0
    artifact = schedule.get("artifact", "") if days else ""
    if days < 0 or days and not artifact:
        raise ValueError("A schedule requires nonnegative days and an artifact name")
    always = selected == "always"
    return {
        "always-run": str(always).lower(),
        "filter": selected,
        "filters": json.dumps(filters, separators=(",", ":")),
        "interval-days": str(days),
        "interval-artifact": artifact,
    }


if __name__ == "__main__":
    policy = os.environ.get("POLICY_FILE", "")
    config = (
        yaml.safe_load(Path(os.environ["GITHUB_WORKSPACE"], policy).read_text())
        if policy
        else {}
    )
    values = resolve(
        config,
        os.environ["GITHUB_JOB"],
        json.loads(os.environ.get("MATRIX_JSON") or "null"),
    )
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        for key, value in values.items():
            # JSON-encode path patterns; reject line breaks in scalar outputs.
            if "\n" in value or "\r" in value:
                raise ValueError(f"Invalid newline in {key}")
            output.write(f"{key}={value}\n")
