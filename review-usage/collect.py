"""Extract token counts, without uploading review content or execution logs."""

import argparse
import json
import os
from pathlib import Path


def count(value):
    if type(value) is not int or value < 0:
        raise ValueError("Invalid token count")
    return value


def codex_usage(path, model):
    totals = {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0}
    found = False
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "turn.completed":
            continue
        usage = event["usage"]
        cached = count(usage["cached_input_tokens"])
        fresh = count(usage["input_tokens"]) - cached
        totals["input"] += count(fresh)
        totals["cache_read"] += cached
        totals["output"] += count(usage["output_tokens"])
        found = True
    return [{"model": model or "unknown", "tokens": totals}] if found else []


def claude_usage(path):
    results = [
        item for item in json.loads(path.read_text()) if item.get("type") == "result"
    ]
    if not results:
        return []
    # The terminal result already includes all turns and subagents.
    result = results[-1]
    models = result.get("modelUsage")
    if models:
        return [
            {
                "model": model,
                "tokens": {
                    "input": count(usage["inputTokens"]),
                    "cache_read": count(usage["cacheReadInputTokens"]),
                    "cache_write": count(usage["cacheCreationInputTokens"]),
                    "output": count(usage["outputTokens"]),
                },
            }
            for model, usage in models.items()
        ]
    usage = result["usage"]
    return [
        {
            "model": "unknown",
            "tokens": {
                "input": count(usage["input_tokens"]),
                "cache_read": count(usage.get("cache_read_input_tokens", 0)),
                "cache_write": count(usage.get("cache_creation_input_tokens", 0)),
                "output": count(usage["output_tokens"]),
            },
        }
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("reviewer", choices=["claude", "codex"])
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--model", default="")
    args = parser.parse_args()
    args.destination.unlink(missing_ok=True)
    try:
        usage = (
            codex_usage(args.source, args.model)
            if args.reviewer == "codex"
            else claude_usage(args.source)
        )
        if not usage:
            raise ValueError("No terminal usage record")
        record = {
            "version": 1,
            "reviewer": args.reviewer,
            "run_id": int(os.environ["GITHUB_RUN_ID"]),
            "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
            "job": os.environ["GITHUB_JOB"],
            "repository": os.environ["GITHUB_REPOSITORY"],
            "usage": usage,
        }
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(record) + "\n"
        args.destination.write_text(payload)
    except (OSError, ValueError, KeyError, TypeError):
        print(
            "::warning::Review token usage is unavailable; no usage artifact was written."
        )


if __name__ == "__main__":
    main()
