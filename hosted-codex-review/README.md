# Hosted Codex reviews

Connect the target repository to Codex, then enable Code review for it in [Codex settings](https://chatgpt.com/codex/settings/code-review). A repository administrator or collaborator with push permission configures this. Reviews run on OpenAI's infrastructure and appear as `chatgpt-codex-connector[bot]`.

To try it, comment on a representative PR:

```text
@codex review
```

For automatic reviews, enable Automatic review and select the review trigger in Codex settings. No GitHub Actions workflow or private runner is needed for Codex. Keep the existing Claude workflow to receive reviews from `claude[bot]` too.

## Conventions

Hosted Codex follows applicable `AGENTS.md` review rules. It does not receive the conventions our Claude action downloads into the workflow's temporary directory. Commit the desired rule files into the target repository, for example under `.review-rules/`, using the same `teamniteo/claude` revision pinned in that project's `nix/flake.lock`. Update them when the pin changes. Files must be available in the hosted checkout, including any hindsight guidance, rather than only linked to a local Nix store.

Merge this section into the target repository's root `AGENTS.md`:

```markdown
## Code Review Rules

Read every file in .review-rules/ and, if present, every file in
.claude/skills-local/hindsight-review/ before reviewing.

Check conventions for every changed file, including tests: conventions.md
for everything, backend.md for Python, frontend.md for Elm, and alembic.md
for migrations. Follow hindsight-review/SKILL.md using the PR diff; skip
its report and question/check entries. Then check bugs, swallowed errors,
and security problems. Require code evidence and name the violated rule.
Skip style nits and formatting, types, coverage percentages, generated
files, and commit messages enforced by CI.

Check existing review threads, including Claude's and resolved threads.
Avoid findings with the same underlying cause and fix, even if wording
or line numbers differ. Respect human decisions in the PR discussion.
```

These are review instructions, not an enforced duplicate filter. The hosted service's documented default focuses on P0/P1 issues, so this does not promise the same findings as the custom Claude action.

## Run Claude first

For an initial comparison, leave automatic Codex reviews off. Wait for the Claude workflow to finish, then comment `@codex review`. This gives Codex a chance to consider Claude's existing findings. Inspect the results for convention coverage and duplicate comments.

Automatic hosted reviews run independently of GitHub Actions: workflow `needs` and concurrency do not serialize them after Claude. This example also does not implement the custom action's approval gate or select its Sol model. A hosted review completing is not equivalent to approving after all threads are resolved.

See OpenAI's [GitHub review guide](https://learn.chatgpt.com/docs/third-party/github) for setup, triggers, and `AGENTS.md` behaviour. This guide does not enable reviews or change repository settings.
