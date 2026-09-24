# Alembic Action

This GitHub Action verifies that you don't have missing migrations in your project
by adding a step to your workflow.

```yaml
  - name: Checking consistency between alembic revision and models
    uses: teamniteo/gha-actions/alembic@main
    with:
      base: src/project/migrations/versions
```

# NIX-Shell Action

This GitHub Action sets nix up for use in CI. It supports GitHub managed
runners, Namespace.so runners, and our own NixOS runners, on which it skips
the installer entirely.

```yaml
  - name: Configure nix
    uses: teamniteo/gha-actions/nix@main
    with:
      auth_token: '${{ secrets.CACHIX_AUTH_TOKEN }}'
```

By default, this action assumes that:
* You are using the `niteo` cachix cache.
* You have `nix/default.nix` in your repo where nix can find nixpkgs.

Every step that runs after this action already has the nix shell environment loaded, through `BASH_ENV` -- there is no need to wrap steps in `nix-shell --run`. The same hook turns on `set -o pipefail`, so a command that fails in the middle of a pipeline fails the step. 

`NIX_PATH` defaults to `nixpkgs=<repo root>/nix/default.nix`, the root being
`git rev-parse --show-toplevel`. It is absolute on purpose: `NIX_PATH` is one
variable for the whole job, but this action's steps run from the workspace
root while a job with `defaults.run.working-directory` runs elsewhere, so a
relative path cannot be correct for both.

Pass `nix_path` to override. The value is used exactly as given and must
exist, or the job fails -- an unusable path would otherwise be dropped by nix,
leaving `<nixpkgs>` unresolvable and `nix-shell` falling back to whatever bash
it can find. Pass `""` to leave `NIX_PATH` alone, for a job that sets it
itself.

You can set your project specific values like so:

```yaml
  - name: Configure nix
    uses: teamniteo/gha-actions/nix@main
    with:
      auth_token: '${{ secrets.CACHIX_AUTH_TOKEN }}'
      cache: myproject
      nix_path: 'nixpkgs=${{ github.workspace }}/other/default.nix'
      push_filter: (-source$|nixpkgs\.tar\.gz$)
```


# Uncommited changes Action

This GitHub Action checks if there are uncommited or not ignored files present after the steps ran.

```yaml
  - name: Check for uncommitted-changes
    uses: teamniteo/gha-actions/uncommitted-changes@main
```

You can exclude some files like so:

```yaml
        with:
            files: "!graphs/*.png"
```

Or multiple files likes:

```
        with:
            files: |
              !graphs/*.png
              !mockups/*.bmpr
```

# Fly Deploy Action

This GitHub Action builds the project's container image, pushes it to the app's registry on Fly.io and deploys it. Run the nix action first: flyctl, skopeo, uv and nix-build come from the project's dev shell.

The action makes a relocatable venv from the project's `uv.lock` with the dev shell's Python and runs `nix-build -A image --arg venv <path>`, so the project's `default.nix` must expose an `image` attribute that takes `venv`. `fly-deploy/image.nix` is that image: the runtime Python, the venv and the app's files under `/app`, with `PATH` and CA certificates set. Fly's init does not use the image's `PATH` for `Cmd`, so spell out `/app/.venv/bin/...`. Reach it through a non-flake input on this repo:

```nix
image = import "${pkgs.flakeSources.gha-actions}/fly-deploy/image.nix" {
  inherit pkgs python venv;
  name = "registry.fly.io/canario";
  app = lib.fileset.toSource { root = ./backend; fileset = lib.fileset.unions [ ./backend/etc ./backend/src ]; };
  files."src/canario/static/dist" = ./frontend/dist;
  cmd = [ "/app/.venv/bin/gunicorn" "--paste" "etc/production.ini" "--bind" ":8080" ];
};
```

```yaml
  - name: Deploy to Fly.io
    uses: teamniteo/gha-actions/fly-deploy@main
    with:
      app: canario
      token: ${{ secrets.FLY_API_TOKEN }}
      project: backend
      prebuild: make -C frontend dist
```

The release command in `fly.toml` runs before any machine changes. Give `migrations` the directory of migration files and the action compares its tree with every deployed machine's. When it differs, all machines are cordoned and the action waits for them to stop before deploying. Afterward, machines are started and their configured health checks must pass before routing is restored. A stop, migration, or startup failure leaves maintenance in place. Requests during maintenance may receive gateway errors; the app should provide an appropriate error page. Configure `kill_signal` and `kill_timeout` in `fly.toml` for the application's shutdown behavior.

```yaml
      migrations: backend/src/canario/db/versions
```

Run the deployment regression tests with `python3 -m unittest discover -s fly-deploy -v` (requires Bash and jq). These use a simulated Fly CLI and do not deploy anything.

Review apps give `org` so the app is created when it does not exist, and `secrets` as KEY=VALUE lines that are staged before the deploy. The `url` output is the app's fly.dev address.

```yaml
  - name: Deploy the review app
    id: deploy
    uses: teamniteo/gha-actions/fly-deploy@main
    with:
      app: canario-pr-${{ github.event.number }}
      org: canario-review
      token: ${{ secrets.FLY_API_TOKEN }}
      secrets: |
        REVIEWAPP=true
        SENTRY_DSN=${{ secrets.SENTRY_DSN }}
```

# Fly Destroy Action

This GitHub Action destroys a Fly.io app when it exists, which is how a review app goes away with its pull request. Run the nix action first for flyctl.

```yaml
  - name: Destroy the review app
    if: github.event.action == 'closed'
    uses: teamniteo/gha-actions/fly-destroy@main
    with:
      app: myproject-pr-${{ github.event.number }}
      token: ${{ secrets.FLY_API_TOKEN }}
```

## We're hiring!

At Niteo we regularly contribute back to the Open Source community. If you do too, we'd like to invite you to [join our team](https://niteo.co/careers)!
