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

This GitHub Action builds the project's container image, pushes it to the app's registry on Fly.io and deploys it. Run the nix action first: flyctl and skopeo come from the project's dev shell, and so does `make image`, which must leave the image stream script at `./result`.

```yaml
  - name: Deploy to Fly.io
    uses: teamniteo/gha-actions/fly-deploy@main
    with:
      app: myproject
      token: ${{ secrets.FLY_API_TOKEN }}
```

The image is tagged with the commit it was built from (`sha`, defaulting to the pull request head, the `workflow_run` head or `github.sha`), which the app also gets as `GIT_COMMIT`, next to `DEPLOYED_AT`. Pass `org` to create the app when it does not exist yet, which is what a review app needs, and `secrets` to stage `KEY=VALUE` lines before the deploy. The action outputs the app's `url`, and only returns once that URL answers, which a freshly created app takes a few seconds to do.

```yaml
  - name: Deploy the review app
    id: deploy
    uses: teamniteo/gha-actions/fly-deploy@main
    with:
      app: myproject-pr-${{ github.event.number }}
      org: niteo
      token: ${{ secrets.FLY_API_TOKEN }}
      secrets: |
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
