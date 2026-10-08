"""Run Codex, recording confirmed authentication failures for the runner host."""

import os
from pathlib import Path
import re
import subprocess
import sys

AUTH_FAILURE = re.compile(
    r"Your access token could not be refreshed because your refresh token "
    r"(?:has expired|was already used|was revoked)|"
    r"Your session has ended|"
    r"(?:^|ERROR: )Not logged in\s*$",
    re.IGNORECASE,
)


def main():
    home = Path(os.environ["CODEX_HOME"])
    flag = home / "auth-required"
    if flag.exists():
        print("Codex needs re-login on this runner; use codex-review-login.", file=sys.stderr)
        return 1
    # Tokens used for publishing must never reach Codex or its child processes.
    env = {key: value for key, value in os.environ.items() if key not in {"GH_TOKEN", "GITHUB_TOKEN"}}
    process = subprocess.Popen(["codex", *sys.argv[1:]], env=env, stderr=subprocess.PIPE,
                               text=True, errors="replace")
    auth_failed = False
    for line in process.stderr:
        sys.stderr.write(line)
        auth_failed |= bool(AUTH_FAILURE.search(line))
    code = process.wait()
    if code != 0 and auth_failed:
        flag.touch(mode=0o600)
        print("Codex authentication failed; this slot needs re-login. Ordinary CI remains available.",
              file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
