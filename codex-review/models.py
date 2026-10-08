"""Resolve family aliases from the installed Codex client's model catalogue."""

import json
import re
import subprocess
import threading


def newest(models, family):
    candidates = []
    for model in models:
        name = model["model"]
        match = re.fullmatch(r"gpt-(\d+(?:\.\d+)*)-" + re.escape(family), name)
        if match and not model.get("hidden", False):
            candidates.append((tuple(map(int, match[1].split("."))), name))
    if not candidates:
        raise RuntimeError(f"Codex lists no visible {family} model; choose an explicit model")
    return max(candidates)[1]


def resolve(name, env):
    if name not in {"latest-sol", "latest-astra"}:
        return name
    process = subprocess.Popen(["codex", "app-server", "-c", 'sandbox_mode="danger-full-access"'], env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, text=True)
    timer = threading.Timer(30, process.kill)
    timer.start()
    request_id = 0

    def send(message):
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    def request(method, params):
        nonlocal request_id
        request_id += 1
        send({"id": request_id, "method": method, "params": params})
        for line in process.stdout:
            response = json.loads(line)
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise RuntimeError(f"Codex {method} failed: {response['error']}")
            return response["result"]
        raise RuntimeError("Codex model discovery stopped or exceeded 30 seconds")

    try:
        request("initialize", {"clientInfo": {"name": "codex_review", "version": "1.0"}})
        send({"method": "initialized", "params": {}})
        models, cursor = [], None
        while True:
            page = request("model/list", {"limit": 100, "includeHidden": False, "cursor": cursor})
            models.extend(page["data"])
            cursor = page.get("nextCursor")
            if not cursor:
                break
        return newest(models, name.removeprefix("latest-"))
    finally:
        timer.cancel()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdin.close()
        process.stdout.close()
