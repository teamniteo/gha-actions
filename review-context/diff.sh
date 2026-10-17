#!/usr/bin/env bash
set -euo pipefail

# The diff API rejects PRs with more than 300 files. Fetch both histories
# instead, so the merge-base diff also works after a shallow checkout and
# when the PR comes from a fork. Never execute code from the fetched trees.
read -r base head < <(gh pr view "$PR" --repo "$REPO" \
  --json baseRefOid,headRefOid --jq '"\(.baseRefOid) \(.headRefOid)"')
repository=$(mktemp -d "$CONTEXT/diff-repository.XXXXXX")
trap 'rm -rf "$repository"' EXIT

git init --bare "$repository" >/dev/null
review_git() {
  git -C "$repository" -c credential.helper= \
    -c 'credential.helper=!gh auth git-credential' "$@"
}
review_git remote add origin "https://github.com/$REPO.git"
# Partial clone avoids downloading unchanged blobs. Keep complete commit
# history so merge-base remains correct even for long-lived branches.
review_git fetch --quiet --no-tags --filter=blob:none origin "$base" "$head"
review_git diff --no-ext-diff --no-textconv "$base...$head" > "$CONTEXT/diff.patch"
