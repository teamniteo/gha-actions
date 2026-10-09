#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${GHA_SKIP_PYTHON:-}" ]]; then
  GHA_SKIP_PYTHON="$(command -v python3)"
fi
if ! "$GHA_SKIP_PYTHON" -c 'import yaml' 2>/dev/null; then
  skip_venv="$(mktemp -d "$RUNNER_TEMP/gha-skip-python.XXXXXX")"
  python3 -m venv "$skip_venv"
  GHA_SKIP_PYTHON="$skip_venv/bin/python"
  "$GHA_SKIP_PYTHON" -m pip install --disable-pip-version-check --only-binary=:all: 'PyYAML==6.0.3'
fi
export GHA_SKIP_PYTHON
printf 'GHA_SKIP_PYTHON=%s\n' "$GHA_SKIP_PYTHON" >> "$GITHUB_ENV"
