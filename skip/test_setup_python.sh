#!/usr/bin/env bash
set -euo pipefail

setup_script="$(cd "$(dirname "$0")" && pwd)/setup-python.sh"
test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT
export RUNNER_TEMP="$test_root"
export GITHUB_ENV="$test_root/github-env"
unset GHA_SKIP_PYTHON
python3 -m venv "$test_root/bare"
export PATH="$test_root/bare/bin:$PATH"
if python3 -c 'import yaml' 2>/dev/null; then
  echo 'Expected the isolated interpreter to lack PyYAML' >&2
  exit 1
fi
# shellcheck source=skip/setup-python.sh
source "$setup_script"
"$GHA_SKIP_PYTHON" -c 'import yaml; assert yaml.__version__ == "6.0.3"'
selected_python="$GHA_SKIP_PYTHON"
# shellcheck source=skip/setup-python.sh
PATH=/nonexistent source "$setup_script"
test "$GHA_SKIP_PYTHON" = "$selected_python"
grep -Fx "GHA_SKIP_PYTHON=$selected_python" "$GITHUB_ENV"
unset GHA_SKIP_PYTHON
PATH="$(dirname "$selected_python"):$PATH"
export PATH
expected_python="$(command -v python3)"
# shellcheck source=skip/setup-python.sh
source "$setup_script"
test "$GHA_SKIP_PYTHON" = "$expected_python"
