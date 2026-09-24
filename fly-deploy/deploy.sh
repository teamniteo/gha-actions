#!/usr/bin/env bash
set -euo pipefail

flyctl deploy -a "$APP" --image "registry.fly.io/$APP:$SHA" --ha=false -e "GIT_COMMIT=$SHA" -e "DEPLOYED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)" ${MIGRATIONS_TREE:+-e "MIGRATIONS_TREE=$MIGRATIONS_TREE"}
if [[ "${STOPPED_FOR_MIGRATIONS:-}" ]]; then
  machines=$(flyctl machine list -a "$APP" --json | jq -r '.[].id')
  started_at=$(date -u +%Y-%m-%dT%H:%M:%S)
  for id in $machines; do
    flyctl machine start "$id" -a "$APP"
    flyctl machine wait "$id" -a "$APP" --state started --wait-timeout 5m
  done

  # Deploy leaves stopped autostart machines stopped, without checking health.
  # https://github.com/teamniteo/ops/issues/2943
  ready=false
  for ((attempt = 0; attempt < 60; attempt++)); do
    status=$(flyctl machine list -a "$APP" --json)
    if jq -e --arg started_at "$started_at" '
      length > 0 and all(.[];
        .state == "started" and
        ((.checks // []) | length) >=
          ((.config.checks // {} | length) + ([.config.services[]?.checks[]?] | length)) and
        all(.checks[]?; .status == "passing" and .updated_at[0:19] >= $started_at)
      )
    ' <<< "$status" > /dev/null; then
      ready=true
      break
    fi
    sleep 5
  done
  if [[ "$ready" != true ]]; then
    echo "Machines failed their health checks; leaving the app cordoned" >&2
    exit 1
  fi

  for id in $machines; do flyctl machine uncordon "$id" -a "$APP"; done
fi
flyctl ips list -a "$APP" | grep -q " v4 " || flyctl ips allocate-v4 --shared -a "$APP"
curl --fail --silent --show-error --output /dev/null --max-time 10 --retry 12 --retry-all-errors --retry-delay 3 --retry-max-time 60 "https://$APP.fly.dev"
