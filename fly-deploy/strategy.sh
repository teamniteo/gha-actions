#!/usr/bin/env bash
# Run from the caller's project directory. Unknown DB state means stop.
set -euo pipefail

case "$STRATEGY" in
    stop|rolling)
        echo "strategy=$STRATEGY" >> "$GITHUB_OUTPUT"
        exit 0
        ;;
    auto) ;;
    *) echo "::error::strategy must be stop, rolling or auto, not '$STRATEGY'"; exit 1 ;;
esac

heads=$(alembic -c "$ALEMBIC_CONFIG" heads | awk '{print $1}' | sort)
selected_strategy=stop
# Query the running app's database, not the previous Git commit: deployments
# can be skipped or fail after migrations have already been applied.
# DATABASE_URL must expand on the remote Machine.
# shellcheck disable=SC2016
if current=$(flyctl ssh console -a "$APP" --quiet -C 'sh -c '\''psql "$DATABASE_URL" -XAt --set ON_ERROR_STOP=on -c "SELECT version_num FROM public.alembic_version ORDER BY version_num"'\'''); then
    if [[ -n "$current" && "$current" == "$heads" ]]; then
        selected_strategy=rolling
    fi
else
    echo "Could not read the deployed database revision; using stop." >&2
fi

echo "Deployment strategy: $selected_strategy"
echo "strategy=$selected_strategy" >> "$GITHUB_OUTPUT"
