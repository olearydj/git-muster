# git-muster

[![CI](https://github.com/olearydj/git-muster/actions/workflows/ci.yml/badge.svg)](https://github.com/olearydj/git-muster/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/git-muster?logo=pypi&logoColor=white)](https://pypi.org/project/git-muster/)
[![Python 3.13–3.14](https://img.shields.io/badge/python-3.13%E2%80%933.14-blue.svg)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/olearydj/git-muster/blob/main/LICENSE)

Every branch, present and accounted for.

Git Muster is a compact command-line report for local Git branches. It separates worktree dirtiness from committed branch state, identifies what is published and what needs attention, shows linked worktrees, and adds pull-request status when the GitHub CLI is available.

```text
project :: feature/report
worktree, clean
--------------------------------------------------------------------------------
BRANCH (4 local)      REMOTE  STATE          WORKTREE       UPDATED  PULL REQUEST
  main                origin  ↓ behind 2     main-release   3h       -
▸ feature/report      origin  ↑ ahead 1      -              12m      #42 approved
  fix/parser          origin  ✓ in sync      -              2d       #39 merged
  experiment          -       · local only   -              1w       -
--------------------------------------------------------------------------------
1 other linked worktree:
  main → /worktrees/project/main-release
✓ working tree clean
1 with unpushed commits · 1 behind · 1 local only
```

## Features

- One scannable report covering every local branch.
- Publication state derived independently from the configured upstream.
- Ahead, behind, diverged, local-only, and remote-gone states.
- Conditional linked-worktree names and checkout paths.
- Draft, open, approved, changes-requested, merged, and closed GitHub pull requests.
- Clickable, underlined PR numbers in supported interactive terminals.
- Responsive terminal layout plus stable ASCII output for logs and pipes.
- Read-only operation with `--no-fetch`; no branch switching, deletion, merging, rebasing, or pushing.

## Requirements

- Python 3.13 or 3.14
- Git 2.23 or newer, for `git branch --show-current` and `for-each-ref`'s `%(worktreepath)`
- [uv](https://docs.astral.sh/uv/) for the recommended installation
- Optional: an authenticated [GitHub CLI](https://cli.github.com/) for pull-request information

## Install

Install the latest release from PyPI:

```console
uv tool install git-muster
```

Use `uv tool upgrade git-muster` to update an existing installation.

The installed commands are equivalent:

```console
git-muster
gm
git muster
```

For development from a clone:

```console
git clone https://github.com/olearydj/git-muster.git
cd git-muster
uv sync --locked --all-groups
uv run git-muster --help
```

## Usage

Run the report from anywhere inside a Git repository:

```console
git muster
```

By default, Git Muster runs `git fetch --all --prune --quiet` before reporting so remote-tracking references are current. When that fetch fails, because the machine is offline or a remote no longer answers, the report still renders from the references already on disk and says that branch states may be out of date. Skip all network activity and repository mutation with:

```console
git muster --no-fetch
```

Use ASCII without color or terminal hyperlinks for logs and pipes:

```console
git muster --plain
```

The built-in help includes examples, effects, linked-worktree behavior, and a Rich branch-state reference:

```console
git muster --help
git muster --version
```

### Color, symbols, and width

Color, Unicode symbols, and clickable pull-request numbers appear when the report is written to an interactive terminal that can render them. Git Muster honors the usual overrides:

| Variable | Effect |
|---|---|
| `NO_COLOR` | Disables color; symbols and layout are unchanged. |
| `FORCE_COLOR`, `CLICOLOR_FORCE` | Keep color when output is redirected to a file or pipe. |
| `COLUMNS` | Overrides the detected terminal width used to fit columns. |

`--plain` overrides all of them and emits pure ASCII, without color or terminal hyperlinks. Git Muster also falls back to those ASCII glyphs on its own whenever the destination stream cannot encode its symbols, so redirected output never fails to encode.

## Reading the report

| Column | Meaning |
|---|---|
| `BRANCH` | Local branch name; the leading marker identifies the current branch. |
| `REMOTE` | Push remote or matching remote branch; `-` means no current publication relationship. |
| `STATE` | Ahead/behind relationship between the local branch and its publication branch. |
| `WORKTREE` | Directory holding the branch when it is checked out elsewhere; omitted when none exist. |
| `UPDATED` | Relative date of the branch tip. |
| `PULL REQUEST` | Optional GitHub PR number and normalized state. |

Publication is deliberately separate from Git's configured upstream. A branch is recognized as published when it has a push destination or matching remote branch, even if it has no upstream or tracks a local parent branch. Git Muster retains both relationships internally but reports publication state by default.

| State | Meaning |
|---|---|
| `in sync` | Local and remote branch tips agree. |
| `ahead N` | Local commits have not been pushed. |
| `behind N` | Remote commits are missing locally. |
| `ahead N, behind M` | Local and remote histories have diverged. |
| `remote gone` | A configured same-name push or upstream branch no longer exists remotely. |
| `local only` | No push destination or matching remote branch currently exists. This does not claim the branch was never published. |

When another linked worktree holds a branch, Git Muster shows its directory in the table and lists the full checkout path below it. It does not scan those other worktrees for dirtiness or change them.

GitHub integration uses one optional `gh pr list --state all --limit 100` query, so a branch whose pull request falls outside the hundred most recent is reported without pull-request state. When several pull requests share a head branch, the newest open, draft, approved, or changes-requested one wins over closed and merged ones. Without an installed and authenticated `gh`, or when no remote points at a known GitHub host, the complete Git report still works and names the reason pull-request state is missing.

## Safety and scope

Git Muster reports; it does not manage branches or worktrees. It never switches, deletes, merges, rebases, or pushes branches. Its only default repository mutation is refreshing remote-tracking references with `git fetch --all --prune`; `--no-fetch` makes the entire run read-only.

Git Muster intentionally has no configuration file, interactive browser, branch tree, cleanup command, or plugin system.

## Development

Runtime dependencies are limited to Typer and Rich. Repository inspection uses the standard library and Git CLI, while tests create disposable local repositories and stub GitHub responses.

```console
uv sync --locked --all-groups
uv run --locked pytest
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked ty check
uv build
```

See [CONTRIBUTING.md](https://github.com/olearydj/git-muster/blob/main/CONTRIBUTING.md) before opening a pull request. CI runs the same checks on Python 3.13 and 3.14.

## Project documents

- [CHANGELOG.md](https://github.com/olearydj/git-muster/blob/main/CHANGELOG.md) for release history.
- [CONTRIBUTING.md](https://github.com/olearydj/git-muster/blob/main/CONTRIBUTING.md) for development and release steps.
- [SECURITY.md](https://github.com/olearydj/git-muster/blob/main/SECURITY.md) for reporting a vulnerability.

## License

Git Muster is available under the [MIT License](https://github.com/olearydj/git-muster/blob/main/LICENSE).
