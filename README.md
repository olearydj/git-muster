# git-muster

Every branch, present and accounted for.

`git-muster` is a small, read-only command-line report for local Git branches. It shows the current worktree, publication state, recent activity, linked worktrees, and associated GitHub pull requests.

Publication is deliberately separate from Git's configured upstream. A branch is recognized as published when it has a push destination or a matching remote branch, even if it has no upstream or tracks a local parent branch. The report keeps the upstream relationship internally but uses the publication relationship for its compact `REMOTE` and `STATE` columns.

## Install

Install from a local checkout with [uv](https://docs.astral.sh/uv/):

```console
uv tool install .
```

Because the executable is named `git-muster`, Git also exposes it as a subcommand:

```console
git muster
git muster -h
```

The report fetches and prunes remote-tracking references before it runs. Skip that network operation when necessary:

```console
git muster --no-fetch
```

Use stable ASCII output without color for logs and pipes:

```console
git muster --plain
```

The built-in help explains each branch state, command effects, and common invocations:

```console
git muster -h
git-muster --help
git-muster --version
```

GitHub pull-request information is optional. When an authenticated [GitHub CLI](https://cli.github.com/) is available, the report distinguishes draft, open, approved, changes-requested, merged, and closed pull requests. PR numbers are clickable in supported interactive terminals; all Git information works without `gh`.

When a branch is checked out in another linked worktree, a compact `WORKTREE` column appears. Git Muster reports that association but does not inspect or manage the other worktree.

## Development

Python 3.13 and 3.14 are supported. Runtime dependencies are limited to Typer and Rich; repository inspection uses the standard library and Git CLI.

```console
uv sync --locked --all-groups
uv run --locked pytest
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked ty check
uv build
```

`git-muster` does not switch, delete, merge, rebase, or push branches. Its only repository mutation is the default `git fetch --all --prune`; `--no-fetch` makes the entire run read-only.
