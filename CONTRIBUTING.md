# Contributing

Small corrections, documentation improvements, bug fixes, and focused features are welcome through pull requests. Git Muster is intentionally a compact, one-shot report rather than a general Git client, so proposed features should preserve the boundaries in `AGENTS.md`.

## Development setup

Fork and clone the repository, then create a purpose-named branch. The project supports Python 3.13 and 3.14 and uses [uv](https://docs.astral.sh/uv/) for environments, locking, running tools, and builds.

```console
uv sync --locked --all-groups
uv run --locked git-muster --help
```

## Before opening a pull request

Update tests and user-facing documentation when behavior changes, then run the complete local check:

```console
uv run --locked pytest
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked ty check
uv build
git diff --check
```

Keep the change focused and inspect the complete diff before committing. Do not include local environments, caches, build artifacts, transient `.ho/` notes, unrelated cleanup, or changes made only to exercise Git Muster against another repository.

In the pull-request description, explain what changed, why it helps, and how it was verified. If the report layout changes, include a representative terminal capture or plain-text sample.

## Releases

Release tags must match the version in `pyproject.toml`. Publishing a GitHub release automatically rebuilds and verifies that tag, then publishes the resulting wheel and source distribution through PyPI Trusted Publishing. The manual workflow input exists only to publish or retry an existing release tag; never add a long-lived PyPI token.
