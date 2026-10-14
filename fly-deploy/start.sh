#!/usr/bin/env bash
set -euo pipefail

# Never restart a release-command Machine: it would rerun migrations.
machines=$(flyctl machine list -a "$APP" --json | jq '[.[] | select(.config.metadata.fly_process_group != "fly_app_release_command")]')
pending=$(jq -r '.[] | "\(.id) \(.state)"' <<< "$machines")
for attempt in 1 2 3; do
  failed=""
  while read -r id state; do
    [[ -n "$id" ]] || continue
    if { [[ "$state" == started ]] || flyctl machine start "$id" -a "$APP"; } &&
      { flyctl machine wait "$id" -a "$APP" --state started --wait-timeout 1m && state=started; } &&
      flyctl machine uncordon "$id" -a "$APP"; then
      echo "Machine $id recovered."
    else
      echo "::warning::Could not recover Machine $id (attempt $attempt/3)."
      failed+="$id $state"$'\n'
    fi
  done <<< "$pending"
  [[ -n "$failed" ]] || exit 0
  pending="$failed"
  if (( attempt < 3 )); then
    sleep 5
  fi
done
printf '::error::Machines still unrecovered after 3 attempts:\n%s' "$pending"
exit 1
