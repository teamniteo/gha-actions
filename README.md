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

## We're hiring!

At Niteo we regularly contribute back to the Open Source community. If you do too, we'd like to invite you to [join our team](https://niteo.co/careers)!
