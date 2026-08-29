# AGENTS.md

`git-muster` is a small Python CLI that reports what local Git branches need attention. Typer and Rich provide the command interface; repository inspection uses the standard library and Git CLI.

## Boundaries

- Keep the default command a compact, one-shot report rather than an interactive Git client.
- Preserve exact configured-upstream ahead/behind semantics.
- Keep GitHub PR data optional through the `gh` CLI.
- Do not add branch deletion, switching, merging, rebasing, pushing, configuration files, or a plugin system without an explicit scope change.
- The only default repository mutation is `git fetch --all --prune`; `--no-fetch` must remain fully read-only.
- Keep runtime dependencies limited to Typer and Rich unless an explicit requirement makes another package necessary.

## Layout

- `src/git_muster/cli.py`: command behavior and terminal presentation.
- `tests/`: offline tests using temporary Git repositories or command stubs.
- `README.md`: installation, usage, and behavioral boundaries.

## Verification

```console
uv sync --locked --all-groups
uv run --locked pytest
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked ty check
uv build
```
