# Alembic Action

This GitHub Action verifies that you don't have missing migrations in your project by adding a step to your workflow.

```yaml
  - name: Checking consistency between alembic revision and models
    uses: teamniteo/gha-actions/alembic@main
    with:
      base: src/project/migrations/versions
```

# NIX-Shell Action

This GitHub Action sets nix up for use in CI. It supports GitHub managed runners, Namespace.so runners, and our own NixOS runners, on which it skips the installer entirely.

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

`NIX_PATH` defaults to `nixpkgs=<repo root>/nix/default.nix`, the root being `git rev-parse --show-toplevel`. It is absolute on purpose: `NIX_PATH` is one variable for the whole job, but this action's steps run from the workspace root while a job with `defaults.run.working-directory` runs elsewhere, so a relative path cannot be correct for both.

Pass `nix_path` to override. The value is used exactly as given and must exist, or the job fails -- an unusable path would otherwise be dropped by nix, leaving `<nixpkgs>` unresolvable and `nix-shell` falling back to whatever bash it can find. Pass `""` to leave `NIX_PATH` alone, for a job that sets it itself.

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

### Dist cache

On runners with `HOST_CACHE_DIR` and Python 3, **Restore dist cache** and **Save dist cache** surround **Evaluate the shell**. Outputs are restored before Nix setup and saved immediately after successful shell setup. Projects opt in with `.github/dist-cache.json`; no Makefile or Nix shell-hook changes are needed:

```json
{
  "inputs": ["frontend", "documentation", "default.nix", "shell.nix", "nix", "backend/src/trak/openapi.yaml"],
  "git_dates": ["documentation/*.md"],
  "outputs": ["frontend/dist", "frontend/.elm-land/src"],
  "symlinks": {"backend/src/trak/static/dist": "frontend/dist"}
}
```

Entries live under `$HOST_CACHE_DIR/dist`. All configured paths are checkout-relative. Include source inputs, generator code, Nix configuration and toolchain pins. Ignored generated files are excluded. The key includes source contents and declared environment values. Optional `git_dates` Git pathspecs include each matching file's last commit date (`%cs`), matching `make docs`; full Git history is required. Commit hashes are not included. Backend-only changes outside these inputs reuse the build. Saving uses the original key, computed before shell setup.

Symlinks are recreated after restoring outputs so the existing shell hook can skip building. Completed outputs are published atomically; the host clears the cache at boot or after draining. Missing cache infrastructure uses normal setup, including on Namespace. Set `DIST_CACHE_ENABLED: "0"` for deployments.

### Elm cache

On host-cache runners, Elm always uses a private temporary `ELM_HOME`. **Restore Elm cache** copies a completed snapshot from `$HOST_CACHE_DIR/elm`; **Save Elm cache** publishes one atomically after successful shell setup. Snapshots are keyed by tracked `elm.json` files, `nix/`, root Nix configuration, repository and runner platform. Jobs never write into a shared package tree. No project configuration is needed; Namespace keeps its existing cache setup.

# Debug Shell Action

This GitHub Action pauses the job and prints the one-line `ssh` command that gets you a shell inside it.

```yaml
  - uses: teamniteo/gha-actions/debug-shell@main
```

The CI runners are on Tailscale, so turn Tailscale on before you paste the command.

The pause is short by default: one minute for someone to show up. You can make it longer.

```yaml
  - uses: teamniteo/gha-actions/debug-shell@main
    with:
      wait_minutes: 5
      max_hold_minutes: 120
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

This GitHub Action builds the project's container image, pushes it to the app's registry on Fly.io and deploys it. Run the nix action first: flyctl, skopeo, uv, nix-build, jq and curl must be available on `PATH`.

The action creates a relocatable venv from `uv.lock` and runs `nix-build -A image --arg venv <path>`. Define the image in the project's `default.nix` using `pkgs.dockerTools.streamLayeredImage`, and accept `venv` as an argument. Use `project` (default `.`) for the Python project directory and `prebuild` for commands to run before building. A project that is not Python passes `build` instead, a command that produces the same executable `./result`.

Each deployment cordons and stops the app Machines before deploying, then starts and uncordons them. Once stopping has been attempted, the start-and-uncordon step also runs after failure or cancellation; the action still reports the original failure. Release-command Machines are excluded so cleanup cannot rerun migrations. A failed release command leaves the app Machines on their existing images, but a later rollout failure can leave some Machines updated. Restarting uses each Machine’s current image and does not undo database changes.

An app that cannot go away on every deploy, such as one with always-on workers or several deploys a day, passes `strategy: rolling`: the Machines keep running and `flyctl deploy --strategy rolling` replaces them one at a time, so the release command has run before the first Machine changes and the old version keeps serving until its replacement passes its checks. There is nothing to restart afterwards; a rollout that fails part way leaves a mix of versions, which the next deploy or a `flyctl deploy --image` of the previous tag resolves.

Configure the release command, service health checks and graceful shutdown in `backend/fly.toml` when the project has a `backend/` directory, or `fly.toml` at the repository root otherwise.

```yaml
  - name: Deploy to Fly.io
    uses: teamniteo/gha-actions/fly-deploy@main
    with:
      app: myproject
      token: ${{ secrets.FLY_API_TOKEN }}
```

The image is tagged with the commit it was built from (`sha`, defaulting to the pull request head, the `workflow_run` head or `github.sha`), which the app also gets as `GIT_COMMIT`, next to `DEPLOYED_AT`. Pass `org` to create the app when it does not exist yet, which is what a review app needs, and `secrets` to stage `KEY=VALUE` lines before the deploy. The action outputs the app's `url` and waits for it to respond, failing the deployment if it remains unavailable after bounded retries.

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

# Claude Review Action

This GitHub Action has Claude review a pull request. Claude leaves one inline comment per problem, and approves the pull request once every thread it opened is resolved and it finds nothing new. It cannot resolve threads, push or merge.

Claude reviews against the project's conventions: the `rules` (default `conventions backend frontend alembic`) from [teamniteo/claude](https://github.com/teamniteo/claude) at the revision `nix/flake.lock` pins, or `main` if it pins none, and `.claude/skills-local/hindsight-review/` when the project has it. It also reads the description, the comments and the existing review threads, so it does not raise a point that a thread already covers or the discussion has settled.

Mention `@claude` in a comment, review or review thread to ask it something: it answers in the thread, or with a comment, even when there is nothing new to review.

Run it on every pull request event. A check before Claude starts skips drafts, commits Claude already approved, and commits it already reviewed while its threads are still open, so most events take seconds. On non-draft PRs, a comment that mentions `@claude` runs it anyway, to answer. Drafts never trigger reviews or answers. A `claude-review` commit status marks each commit Claude has reviewed. Resolving a thread does not trigger workflows: the next push, comment or review picks it up.

The repository needs the [Claude GitHub App](https://github.com/apps/claude) installed and a `CLAUDE_CODE_OAUTH_TOKEN` secret from `claude setup-token`. Use GitHub-hosted runners: Claude's shell commands run in bubblewrap, which our NixOS runners do not allow.

```yaml
name: Claude review

on:
  pull_request:
    types: [opened, ready_for_review, reopened, synchronize]
  pull_request_review:
    types: [submitted]
  pull_request_review_comment:
    types: [created]
  issue_comment:
    types: [created]

jobs:
  review:
    # Humans only: Claude's own reviews and comments would retrigger it.
    if: >-
      github.event.sender.type != 'Bot' &&
      (github.event_name != 'issue_comment' || github.event.issue.pull_request)
    runs-on: ubuntu-latest
    # On the job, not the workflow: skipped runs (Claude's own events) must
    # not replace a pending review in the queue.
    concurrency:
      group: claude-review-${{ github.event.pull_request.number || github.event.issue.number }}
      cancel-in-progress: false
    permissions:
      contents: read
      pull-requests: read
      statuses: write # marks the commit Claude reviewed
      id-token: write # exchanged for a claude[bot] token
    steps:
      - uses: actions/checkout@v6
        with:
          # issue_comment runs on the default branch; review the PR instead.
          ref: ${{ github.event_name == 'issue_comment' && format('refs/pull/{0}/merge', github.event.issue.number) || '' }}
      - uses: teamniteo/gha-actions/claude-review@main
        with:
          claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
```

# Codex Review Action

Reviews PRs against the same conventions as Claude, posts inline findings, answers `@codex-niteo` questions, and approves when its threads are resolved. Use a GitHub App installation token as `github_token`; the default bot name is `codex-niteo` (override with `bot_name`). The App needs Contents: read, Pull requests: write, Issues: write, and Commit statuses: write. Optional inputs: `rules` (default: `conventions backend frontend alembic`) and `model` (default: `gpt-6-sol`).

Use a trusted private runner with Codex configured, `gh`, Python, and an unprivileged user without passwordless sudo. Pass its persistent directory as `codex_home` and use the runner-provided `codex` executable on `PATH`. The container provides isolation; Codex's inner sandbox is disabled. GitHub tokens are withheld from Codex and used by a separate publishing step. Confirmed authentication failures create `auth-required` in `codex_home` for the runner administrator to disable Codex eligibility until re-login.

Run Claude first so Codex sees its findings. Both agents check existing threads for the same cause and fix to reduce duplicates. Per-PR concurrency serializes the pair; different PRs can run concurrently on separate runners. Replace separate review workflows with this example:

```yaml
name: AI review

on:
  pull_request:
    types: [opened, ready_for_review, reopened, synchronize]
  pull_request_review:
    types: [submitted]
  pull_request_review_comment:
    types: [created]
  issue_comment:
    types: [created]

# Serialize the whole pair. Bot events get their own group so they cannot
# replace a pending human-triggered review.
concurrency:
  group: ai-review-${{ github.event.sender.type == 'Bot' && github.run_id || (github.event.pull_request.number || github.event.issue.number) }}
  cancel-in-progress: false

jobs:
  claude:
    if: >-
      github.event.sender.type != 'Bot' &&
      contains(fromJSON('["OWNER","MEMBER","COLLABORATOR"]'),
               github.event.comment.author_association || github.event.review.author_association || github.event.pull_request.author_association) &&
      (github.event_name != 'issue_comment' || github.event.issue.pull_request)
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: read
      statuses: write
      id-token: write
    steps:
      - uses: actions/checkout@v6
        with:
          ref: ${{ github.event_name == 'issue_comment' && format('refs/pull/{0}/merge', github.event.issue.number) || '' }}
          persist-credentials: false
      - uses: teamniteo/gha-actions/claude-review@main
        with:
          claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}

  codex:
    needs: claude
    # Still review after a Claude failure, but not a skip or cancellation.
    if: ${{ !cancelled() && contains(fromJSON('["success","failure"]'), needs.claude.result) }}
    runs-on: [self-hosted, codex-review]
    permissions:
      contents: read
    steps:
      - uses: actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1 # v3.2.0
        id: app
        with:
          app-id: ${{ vars.CODEX_APP_ID }}
          private-key: ${{ secrets.CODEX_APP_PRIVATE_KEY }}
      - uses: actions/checkout@v6
        with:
          ref: ${{ github.event_name == 'issue_comment' && format('refs/pull/{0}/merge', github.event.issue.number) || '' }}
          persist-credentials: false
      - uses: teamniteo/gha-actions/codex-review@main
        with:
          github_token: ${{ steps.app.outputs.token }}
          bot_name: ${{ steps.app.outputs.app-slug }}
          codex_home: /var/lib/codex-review
```

Each reviewer approves only after its own threads are resolved and a follow-up review finds nothing new. Resolving a thread does not trigger GitHub Actions: after resolving the reviewer's last thread, post a new PR comment (for example, `Resolved all threads`) or submit a review to trigger that follow-up without a new commit. Both reviewers use the same policy. Drafts never trigger reviews or answers. Already-approved commits and reviewed commits with unresolved threads skip reviewing, but mentions still get answers. Comments can also start a review of a commit the bot has not reviewed yet. The example restricts triggers to trusted collaborators.

# Skip and Skip Save Actions

`skip` decides and logs whether a CI job runs. `skip-save` records actual successful executions. Every required job still starts and retains its check name. Configure all skip policies in one checkout-relative YAML file:

```yaml
filters:
  application:
    - '**'
    - '!frontend/tests/**'
jobs:
  backend_checks:
    filter: always
  browser_tests:
    filter: application
  demo_content:
    filter: application
    schedule:
      matrix: {day: full}
      days: 7
      artifact: last_full_run
```

Each job calls the same action using its automatically inferred workflow job ID and matrix values:

```yaml

- uses: actions/checkout@v7
  with:
    fetch-depth: 2

- uses: teamniteo/gha-actions/skip@main
  id: skip
- run: make tests
  if: steps.skip.outputs.run

- uses: teamniteo/gha-actions/skip-save@main
  if: steps.skip.outputs.run
```

Exactly one of `run` or `skip` is present (`true`); the other is empty. `reason` explains the decision in outputs and logs. Jobs absent from the configuration use normal unchanged-tree result reuse without path or schedule rules. Both actions default to `.github/skip.yml`. Set `config` to use a different path, or explicitly set `config: ''` to disable policy rules. `filter: always` bypasses every skip rule and is suitable for commit-message validation.

Include `[ci full]` in the latest PR commit message to bypass result reuse, path filters and schedules. Main/manual runs do not reuse PR results or apply PR path filters. Opening/reopening PRs and workflow reruns bypass result reuse. Reruns also bypass schedules.

Successful results match repository, PR, base, merged tree, workflow job ID, canonical matrix values and runner platform. The host-cache is checked first; GitHub artifacts are the fallback. The fallback requires a successful source workflow because the API does not expose workflow job IDs for matching individual results. GitHub errors and cache misses run checks normally.

Schedule selectors match matrix values exactly. Use a repository-wide unique artifact name for each schedule. Only actual executions publish interval markers; skipped runs never postpone the interval. The source workflow must have succeeded. Both actions read the same policy file and infer schedules by job ID and matrix values. `skip` records the original result key in the job environment before tests can modify files. `skip-save` reads that key automatically and handles empty keys and interval markers internally and must run only after successful validation, never with `always()`.

Guard expensive steps rather than entire jobs. For downstream artifacts, use `run-id` and `head-sha` to restore the original successful output when skipping, and republish under the current commit name if needed. The decision alone cannot recreate artifacts or prevent external deployments.

Python 3 and Git must be available before shell setup. YAML is read using bundled pure-Python PyYAML, with no runtime installation. Jobs need `actions: read`; path-filtered jobs also need `pull-requests: read`.

## We're hiring!

At Niteo we regularly contribute back to the Open Source community. If you do too, we'd like to invite you to [join our team](https://niteo.co/careers)!

### Review token usage

Both review actions upload an `ai-review-usage-*` artifact with token counts by model: fresh input, cache reads, cache writes and output. Artifacts contain no prompts or review content and expire after 14 days. Usage capture is best-effort and never fails a review. Interrupted sessions without a terminal usage record are not estimated.
