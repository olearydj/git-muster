# AGENTS.md

`git-muster` is a small Python CLI that reports what local Git branches need attention. Typer and Rich provide the command interface; repository inspection uses the standard library and Git CLI.

## Boundaries

- Keep the default command a compact, one-shot report rather than an interactive Git client.
- Preserve configured upstream and publication as separate internal relationships; report ahead/behind against the push destination or matching remote branch.
- Keep GitHub PR data optional through the `gh` CLI.
- Do not add branch deletion, switching, merging, rebasing, pushing, configuration files, or a plugin system without an explicit scope change.
- The only default repository mutation is `git fetch --all --prune`; `--no-fetch` must remain fully read-only.
- Keep runtime dependencies limited to Typer and Rich unless an explicit requirement makes another package necessary.
- Keep release archives workflow-produced; never attach hand-built assets to a GitHub release.
- Keep immutable releases disabled while assets are attached after publication; enabling it would break the publish workflow.
- Pin every GitHub Action to a full commit SHA with a version comment.

## Layout

- `src/git_muster/cli.py`: command behavior and terminal presentation.
- `tests/`: offline tests using temporary Git repositories or command stubs.
- `README.md`: installation, usage, and behavioral boundaries.
- `CHANGELOG.md`: user-visible history; every release needs an entry.
- `SECURITY.md`: supported versions, reporting channel, and release-integrity claims.
- `.github/workflows/`: CI and the tag-verifying PyPI publish pipeline.
- `.github/scripts/`: helpers the publish pipeline runs; keep them standard-library only and tested.

## Handoff and context

- Keep transient restart state, current progress, blockers, and verification results in ignored `.ho/` notes created through the handoff skill.
- Add `PROJECT_CONTEXT.md` only when stable decisions, recurring pitfalls, or a durable source map outgrow this file and the README. Keep it short and do not use it as a task tracker or session transcript.

## Verification

```console
uv sync --locked --all-groups
uv run --locked pytest
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked ty check
uv build
```
