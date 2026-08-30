# Changelog

Notable changes to Git Muster. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.1] - 2026-08-29

### Changed

- Rich 15 is now an accepted runtime dependency; the report and its help render identically on 14 and 15.
- `--plain` now explicitly promises ASCII interface glyphs rather than rewriting Unicode text from the repository.

### Fixed

- A successful GitHub CLI response containing a non-empty list with no object rows now reports unexpected data instead of appearing to contain no pull requests.

## [0.4.0] - 2026-08-29

### Added

- A warning when `git fetch` fails, so a report built from stale remote-tracking refs is never presented as current.
- `FORCE_COLOR` and `CLICOLOR_FORCE` support for color in pipes; `NO_COLOR` still wins over both.
- Automatic fallback to ASCII output when the destination stream cannot encode Git Muster's symbols, and virtual-terminal setup so ANSI styling works on Windows consoles.
- A `SECURITY.md` policy, this changelog, and Dependabot coverage for GitHub Actions and Python dependencies.

### Changed

- Missing pull-request data now names the actual cause: the GitHub CLI is not installed, is not logged in, has no GitHub remote, could not reach GitHub, or returned unexpected data.
- When several pull requests share a head branch, the report prefers the newest open, draft, approved, or changes-requested one instead of whichever GitHub listed first.
- Failed Git commands report Git's own message rather than only the command that failed.
- Merged and closed pull requests are resolved before the draft flag, so a closed draft is no longer shown, or ranked, as active work.
- Pull-request rows without a usable head branch and positive integer number are ignored, and a response with no usable row at all now reports unexpected data instead of an empty column.
- Release archives attached to a GitHub release are now uploaded by the publishing workflow, so they are byte-identical to the files published to PyPI. A failed upload can be reattached from PyPI's own archives, verified by digest, without republishing.

### Fixed

- `--plain` now uses ASCII for all built-in decorations; the summary line no longer emits a `·` separator.
- `FORCE_COLOR` and `CLICOLOR_FORCE` now apply to redirected output on Windows, where console setup previously suppressed them.
- Truncated branch and worktree names now fit their column exactly, instead of overflowing it by one cell whenever the ASCII ellipsis was used.

## [0.3.1] - 2026-08-29

First public release: a one-shot branch report covering publication state, ahead/behind counts, linked worktrees, and optional GitHub pull-request status, published to PyPI with Trusted Publishing.

[Unreleased]: https://github.com/olearydj/git-muster/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/olearydj/git-muster/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/olearydj/git-muster/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/olearydj/git-muster/releases/tag/v0.3.1
