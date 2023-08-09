# Alembic Action

This GitHub Action verifies that you don't have missing migrations in your project
by adding a step to your workflow.

```yaml
  - name: Checking consistency between alembic revision and models
    uses: teamniteo/gha-alembic-migration@main
    with:
      base: src/project/migrations/versions
```
