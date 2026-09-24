#!/usr/bin/env bash
set -euo pipefail

tree=$(git rev-parse "HEAD:$MIGRATIONS")
echo "MIGRATIONS_TREE=$tree" >> "$GITHUB_ENV"
machines=$(flyctl machine list -a "$APP" --json)
if jq -e --arg tree "$tree" 'all(.[]; .config.env.MIGRATIONS_TREE == $tree)' <<< "$machines" > /dev/null; then
  exit 0
fi

echo "The migrations changed since the running release: stopping the app for the deploy"
while read -r id; do
  flyctl machine cordon "$id" -a "$APP"
done < <(jq -r '.[].id' <<< "$machines")

while read -r id state; do
  if [[ "$state" != stopped ]]; then
    flyctl machine stop "$id" -a "$APP" --wait-timeout 1m
  fi
done < <(jq -r '.[] | "\(.id) \(.state)"' <<< "$machines")
echo "STOPPED_FOR_MIGRATIONS=1" >> "$GITHUB_ENV"
