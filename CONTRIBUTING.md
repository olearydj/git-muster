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

Release tags must match the version in `pyproject.toml`, and every release needs a `CHANGELOG.md` entry.

1. Move the `Unreleased` notes into a dated version section in `CHANGELOG.md`.
2. Bump `version` in `pyproject.toml` and run `uv lock` so the lockfile records it.
3. Commit, tag the exact version (`git tag -a v1.2.3 -m "git-muster 1.2.3"`), and push the branch and the tag.
4. Publish a GitHub release for that tag, using the changelog entry as its notes.

Publishing the release runs `.github/workflows/publish-pypi.yml`, which rebuilds and verifies the tag, publishes the wheel and source distribution through PyPI Trusted Publishing, and then attaches those same archives to the GitHub release. Do not upload release archives by hand: assets built outside the workflow carry no verification and no attestation. Never add a long-lived PyPI token.

Because the workflow attaches archives after the release is published, [immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases) must stay disabled for this repository; enabling that setting would reject every asset upload.

Recovering a failed run depends on how far it got. PyPI files are immutable, so a version PyPI already holds is never republished:

- Failed before PyPI accepted the version: dispatch the workflow again for the same tag, or re-run the failed jobs.
- Published to PyPI but the assets did not attach: dispatch the workflow for that tag with `assets_only` enabled. That run validates the tag and its release, skips the build entirely, then downloads the archives from PyPI, verifies their SHA-256 digests, and attaches those exact files. Rebuilding is deliberately avoided: two compatible uv versions can produce wheels that differ in build metadata, and an old tag may no longer build even though its published files remain valid.
- Published something wrong: release a new version. Never move a published tag or retry a version PyPI already holds.
