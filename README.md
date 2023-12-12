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

This GitHub Action sets nix for use in CI. It supports GitHub Managed Runners
and Namespace.so Runners. 

```yaml
  - name: Configure nix
    uses: teamniteo/gha-actions/nix@main
    with:
      auth_token: '${{ secrets.CACHIX_AUTH_TOKEN }}'
```

By default, this action assumes that:
* You are using the `niteo` cachix cache.
* You have `./nix/default.nix` in your repo where nix can find nixpkgs.

You can set your project specific values like so:

```yaml
  - name: Configure nix
    uses: teamniteo/gha-actions/nix@main
    with:
      auth_token: '${{ secrets.CACHIX_AUTH_TOKEN }}'
      cache: myproject
      nix_path: nixpkgs=nixos-unstable
      push_filter: (-source$|nixpkgs\.tar\.gz$)
      namespace_runner: false
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
